"""Live updates: "something of this kind changed", pushed to open screens.

THE OWNER ASKED FOR IT (2026-10-12), and the security half was built
first and waited: core/change_hints.py. Read its docstring before this
one. The rule that shapes everything here:

    EVENTS CARRY NO DATA. An event says "something of this kind
    changed", never what changed. The client then refetches through the
    SAME authorised endpoints it already uses.

So a hint is `{"object_type": "Customer", "change": "updated"}` and
nothing else, filtered per caller through their own visible schema --
a caller who may not know `Customer` exists is never told one changed.

SERVER-SENT EVENTS, NOT WEBSOCKETS. The traffic is one-way, the
browser's EventSource reconnects by itself, and an SSE response is an
ordinary GET that the session cookie, the middleware and the proxy in
front already understand. WebSockets would buy a return channel nothing
uses.

WHERE CHANGES COME FROM -- two places, because two processes write:

  A PUBLICATION. `scripts/run_sync.py` is a separate process, so this
  one cannot be told; it LOOKS. Every POLL_SECONDS it reads each gold
  table's current snapshot id; for any that moved, it first moves the
  server onto the new publication (api/reload.follow_publications --
  without which a running server kept serving the old one) and then
  hints "updated".

  AN APPLIED WRITE, in this process: the confirmation route calls
  `publish` for each type a write touched, with its verb.

EVERY STREAM ENDS AFTER MAX_STREAM_SECONDS, deliberately. The caller's
visible schema is computed once, at connect; a role changed or a
session revoked afterwards would otherwise keep receiving type names
for as long as the tab stayed open. EventSource reconnects on its own,
and the reconnect authenticates again -- so the worst case is a few
minutes of type names, never data.

IT HOLDS NO REQUEST WORKER. The route is async and waits on a queue, so
an open tab costs a coroutine, not one of the thread pool's slots that
queries run in.
"""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable

from core.change_hints import describe_hint, hints_for

logger = logging.getLogger(__name__)

#: How often a publication is looked for, while anyone is listening.
POLL_SECONDS = 5.0
#: A comment line this often keeps proxies from closing an idle stream.
HEARTBEAT_SECONDS = 15.0
#: Then the stream ends and the browser reconnects -- re-authenticating.
MAX_STREAM_SECONDS = 600.0
#: Per connection. A tab that stops reading loses hints rather than
#: growing memory; the next hint for the same type says the same thing.
QUEUE_LIMIT = 100


class ChangeBus:
    """Fan-out of (object_type, change) to every open stream.

    `publish` may be called from any thread -- writes are applied in the
    request thread pool -- so it hands each event to the subscriber's
    own event loop rather than touching the queue directly.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()

    @property
    def listening(self) -> bool:
        with self._lock:
            return bool(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
        with self._lock:
            self._subscribers.add((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = {pair for pair in self._subscribers if pair[1] is not queue}

    def publish(self, object_type: str, change: str) -> None:
        # Validated HERE, at the source, so nothing richer than a type
        # and a verb can ever be queued.
        describe_hint(object_type, change)
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(_offer, queue, (object_type, change))
            except RuntimeError:
                # That loop has closed; its stream is gone.
                self.unsubscribe(queue)


def _offer(queue: asyncio.Queue, item) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        pass


def gold_snapshots(catalog, object_types) -> dict:
    """{object_type: current snapshot id} for every published gold table."""
    from core.ontology.gold_view import GOLD_NAMESPACE

    current = {}
    for object_type in object_types:
        try:
            snapshot = catalog.load_table(f"{GOLD_NAMESPACE}.{object_type}").current_snapshot()
        except Exception:  # noqa: BLE001 - not published is not a change
            continue
        if snapshot is not None:
            current[object_type] = snapshot.snapshot_id
    return current


async def watch_publications(bus: ChangeBus, sources: Callable[[], tuple],
                             poll_seconds: float = POLL_SECONDS,
                             on_publication: "Callable[[], object] | None" = None) -> None:
    """Notices a new gold publication: moves the server onto it, then
    hints "updated" for each type that moved.

    `sources()` returns (catalog, object_types) for the CURRENT
    generation, asked each time so a configuration reload is followed.
    The first look only records where things stand.

    ALWAYS POLLS, listeners or not. The hints need a listener; moving
    the server onto the new publication (`on_publication`, which is
    api/reload.follow_publications) does not -- before this, a running
    server served the previous publication until somebody restarted it.
    The poll is one catalog read per type, in a thread.

    THE MOVE COMES FIRST, so a screen told to refetch fetches the new
    publication rather than the one it already has.
    """
    seen: dict | None = None
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            catalog, object_types = sources()
            if catalog is None:
                continue
            current = await asyncio.to_thread(gold_snapshots, catalog, object_types)
        except Exception as exc:  # noqa: BLE001 - a missed poll is not an outage
            logger.warning("live updates: could not read publications (%s)", type(exc).__name__)
            continue
        moved = [] if seen is None else [
            object_type for object_type, snapshot_id in current.items()
            if seen.get(object_type) != snapshot_id]
        seen = current
        if not moved:
            continue
        if on_publication is not None:
            try:
                await asyncio.to_thread(on_publication)
            except Exception as exc:  # noqa: BLE001 - the old publication still serves
                logger.warning("live updates: could not follow a publication (%s)",
                               type(exc).__name__)
        for object_type in moved:
            bus.publish(object_type, "updated")


async def event_stream(bus: ChangeBus, visible_schema: dict, is_disconnected,
                       max_seconds: float | None = None,
                       heartbeat_seconds: float | None = None) -> AsyncIterator[str]:
    """One caller's stream, in the text/event-stream format."""
    # READ AT CALL TIME, so a test (or an operator patching the module)
    # changes them for the next stream rather than never.
    max_seconds = MAX_STREAM_SECONDS if max_seconds is None else max_seconds
    heartbeat_seconds = HEARTBEAT_SECONDS if heartbeat_seconds is None else heartbeat_seconds
    queue = bus.subscribe()
    loop = asyncio.get_running_loop()
    ends_at = loop.time() + max_seconds
    try:
        # How long the browser waits before reconnecting after the end.
        yield "retry: 3000\n\n"
        while (remaining := ends_at - loop.time()) > 0:
            if await is_disconnected():
                return
            try:
                object_type, change = await asyncio.wait_for(
                    queue.get(), timeout=min(heartbeat_seconds, remaining))
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            # PER CALLER, through the rule that already decides which
            # types this caller may know exist.
            for allowed in hints_for(visible_schema, [object_type]):
                yield f"event: change\ndata: {json.dumps(describe_hint(allowed, change))}\n\n"
    finally:
        bus.unsubscribe(queue)
