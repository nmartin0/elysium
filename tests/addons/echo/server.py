"""The example add-on's server, for Elysium's tests of add-ons (BLOCKING.md
item 3, step 2): it answers with what reached it, so a test can see what
the proxy passed, and it can misbehave on request, so a test can see the
supervisor cope.

IT USES sdk/python/elysium_addon.py AS AN ADD-ON WOULD -- a copy of that
file is what an add-on carries; here it is imported from where it lives,
so the tests check the file add-ons copy rather than a copy of it.

    GET  /health    200, unless `options.health` is "never" or "fail-after"
                    has passed
    ANY  /whoami    who is asking (401 without a good token) and what
                    arrived: method, path as sent, query, header names, body
    GET  /cookie    tries to set a cookie and redirect, and returns HTML
    GET  /events    an event stream: `options.events` events, then ends;
                    ?forever=1 keeps sending a comment line each second
    GET  /start     the start file as read, its secret withheld
    GET  /env       the names in its environment

Options (from the deployment's addons.yaml) that make it misbehave:
    {"ignore_term": true}   carry on through SIGTERM and through its standard
                            input closing, to be killed
    {"exit_after": 0.5}     exit with status 3 that many seconds after starting
    {"health": "never"}     never answer /health with 200
"""

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sdk" / "python"))

import elysium_addon  # noqa: E402 -- found through the path above


def make_server(info: dict, port: int = 0) -> ThreadingHTTPServer:
    options = info.get("options") or {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            pass

        def _send(self, status: int, body: bytes, content_type: str = "application/json",
                  extra: "dict | None" = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value) -> None:
            self._send(status, json.dumps(value).encode())

        def _route(self) -> None:
            path, _, query = self.path.partition("?")
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if path == "/health":
                return self._json(503 if options.get("health") == "never" else 200, {"ok": True})
            try:
                who = elysium_addon.identity(self.headers, info)
            except elysium_addon.NotSignedIn as refused:
                return self._json(401, {"error": str(refused)})
            if path.startswith("/whoami"):
                return self._json(200, {"user": who["sub"], "claims": who, "method": self.command,
                                        "path": path, "query": query,
                                        "headers": sorted(h.lower() for h in self.headers.keys()),
                                        "body": body.decode("utf-8", "replace")})
            if path == "/cookie":
                return self._send(200, b"<script>document.title='ran'</script>", "text/html",
                                  {"Set-Cookie": "elysium_session=stolen; Path=/",
                                   "Location": f"http://127.0.0.1:{self.server.server_address[1]}/x",
                                   "ETag": '"e1"'})
            if path == "/events":
                return self._events("forever=1" in query)
            if path == "/env":
                return self._json(200, sorted(os.environ))
            if path == "/start":
                shown = json.loads(json.dumps(info))
                shown["identity"]["secret"] = "(withheld)"
                return self._json(200, shown)
            return self._json(404, {"error": "no such path"})

        def _events(self, forever: bool) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            count = 0
            try:
                while forever or count < int(options.get("events", 3)):
                    self.wfile.write(f"data: {count}\n\n".encode() if not forever else b": alive\n\n")
                    self.wfile.flush()
                    count += 1
                    time.sleep(1.0 if forever else 0.05)
            except OSError:
                pass
            self.close_connection = True

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _route

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    info = elysium_addon.start()
    options = info.get("options") or {}
    server = make_server(info, int(os.environ["PORT"]))
    if options.get("ignore_term"):
        signal.signal(signal.SIGTERM, lambda *_: None)
    else:
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    if not options.get("ignore_term"):
        # A STUBBORN ONE ignores its standard input closing too, so only
        # SIGKILL at the deadline can stop it.
        elysium_addon.exit_when_elysium_does()
    if "exit_after" in options:
        threading.Timer(float(options["exit_after"]), lambda: os._exit(3)).start()
    print(f"echo listening on {server.server_address[1]}", flush=True)
    server.serve_forever()
    print("echo stopped cleanly", flush=True)


if __name__ == "__main__":
    main()
