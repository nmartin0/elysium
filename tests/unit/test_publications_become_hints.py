"""A sync in ANOTHER process publishes; this one notices (live updates).

api/live_updates.watch_publications reads each gold table's snapshot id
while anyone is listening, and hints "updated" for the ones that moved.
"""

import asyncio
from types import SimpleNamespace

from api.live_updates import ChangeBus, watch_publications


class _Catalog:
    """Gold tables whose current snapshot the test moves by hand."""

    def __init__(self):
        self.snapshots = {"Customer": 1, "Account": 7}
        self.reads = 0

    def load_table(self, identifier):
        self.reads += 1
        object_type = identifier.split(".", 1)[1]
        if object_type not in self.snapshots:
            raise LookupError(identifier)
        return SimpleNamespace(current_snapshot=lambda: SimpleNamespace(
            snapshot_id=self.snapshots[object_type]))


async def _run(catalog, steps, listen=True):
    bus = ChangeBus()
    queue = bus.subscribe() if listen else None
    watcher = asyncio.create_task(watch_publications(
        bus, lambda: (catalog, ["Customer", "Account", "Unpublished"]), poll_seconds=0.01))
    received = []
    for step in steps:
        await asyncio.sleep(0.05)
        step()
    await asyncio.sleep(0.05)
    watcher.cancel()
    while queue is not None and not queue.empty():
        received.append(queue.get_nowait())
    return received


def test_a_moved_snapshot_is_a_hint_and_an_unmoved_one_is_not():
    catalog = _Catalog()

    def publish_customer():
        catalog.snapshots["Customer"] = 2

    assert asyncio.run(_run(catalog, [publish_customer])) == [("Customer", "updated")]


def test_starting_up_is_not_a_change():
    """The first look only records where things stand."""
    assert asyncio.run(_run(_Catalog(), [])) == []


def test_a_publication_is_followed_before_anyone_is_told():
    """The server moves onto the new publication FIRST, so a screen told
    to refetch gets it -- and it moves whether or not anyone is
    listening, because API callers read gold too."""
    catalog = _Catalog()
    order = []

    async def run():
        bus = ChangeBus()
        original = bus.publish
        bus.publish = lambda *hint: (order.append("hint"), original(*hint))
        watcher = asyncio.create_task(watch_publications(
            bus, lambda: (catalog, ["Customer"]), poll_seconds=0.01,
            on_publication=lambda: order.append("followed")))
        await asyncio.sleep(0.05)
        catalog.snapshots["Customer"] = 2
        await asyncio.sleep(0.05)
        watcher.cancel()

    asyncio.run(run())

    assert order == ["followed", "hint"]
