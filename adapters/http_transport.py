"""One HTTP POST to a model server that can be abandoned part-way (AL-11).

THE GAP. A person who closes the Query page set a cancel event, and the
agent loop noticed it -- between hops. The model call already running
went on to the end: on a CPU deployment that is up to minutes of the
only model slot spent on an answer nobody will read, while the next
person's question queues behind it.

STOPPING OUR WAIT IS NOT ENOUGH. Abandoning the call in Python while
the request stays open leaves the server generating. Ollama stops a
generation only when its request ends -- "Ollama only cancels a
generation when its HTTP request context ends" (ollama-exporter PR 8,
which hit exactly this) -- so the connection itself has to close.

HOW: the socket is shut down from a watcher thread. `requests` gives no
handle on the connection it is blocked reading, so the session used for
this one call is mounted with an adapter whose connection class records
each connection as it opens (urllib3's documented ConnectionCls hook).
When the cancel event is set the watcher calls shutdown() on it; the
blocked read fails at once, the server sees the connection go, and the
caller gets LLMCancelled rather than a transport error.

ONE SESSION PER CALL, which is also what `requests.post` does, so
nothing about connection reuse changes.
"""

import socket
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from core.llm.interface import LLMCancelled

#: How often the watcher looks at the cancel event. The disconnect
#: watcher in api/routes.py polls every 0.5 s, so this is not the slow
#: part.
_POLL_SECONDS = 0.1


class _OpenConnections:
    def __init__(self):
        self._lock = threading.Lock()
        self._connections: list = []

    def add(self, connection) -> None:
        with self._lock:
            self._connections.append(connection)

    def shut_down(self) -> None:
        with self._lock:
            for connection in self._connections:
                sock = getattr(connection, "sock", None)
                if sock is None:
                    continue
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass                        # already closed: the goal


def _tracking_adapter(opened: _OpenConnections) -> HTTPAdapter:
    def recording(base):
        class Recording(base):
            def connect(self):
                super().connect()
                opened.add(self)
        return Recording

    class HttpPool(HTTPConnectionPool):
        ConnectionCls = recording(HTTPConnection)

    class HttpsPool(HTTPSConnectionPool):
        ConnectionCls = recording(HTTPSConnection)

    class Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {"http": HttpPool, "https": HttpsPool}

    return Adapter(max_retries=0)


def post(url: str, *, json, timeout: float, headers: "dict | None" = None,
         cancel: "threading.Event | None" = None) -> requests.Response:
    """requests.post, plus: set `cancel` and the call ends, connection
    and all. Without `cancel` it is exactly requests.post."""
    extra = {"headers": headers} if headers is not None else {}
    if cancel is None:
        return requests.post(url, json=json, timeout=timeout, **extra)
    if cancel.is_set():
        raise LLMCancelled("The request was cancelled before the model was called.")

    opened = _OpenConnections()
    finished = threading.Event()

    def watch() -> None:
        while not finished.is_set():
            if cancel.wait(_POLL_SECONDS):
                opened.shut_down()
                return

    watcher = threading.Thread(target=watch, name="model-call-cancel", daemon=True)
    watcher.start()
    try:
        with requests.Session() as session:
            adapter = _tracking_adapter(opened)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            return session.post(url, json=json, timeout=timeout, **extra)
    except requests.RequestException as exc:
        if cancel.is_set():
            raise LLMCancelled("The request was cancelled while the model was answering; "
                               "the connection was closed so the server stops too.") from exc
        raise
    finally:
        finished.set()
