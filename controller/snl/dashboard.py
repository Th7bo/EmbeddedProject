"""Live dashboard for the controller: http://localhost:8080 (stdlib only).

GET  /        the page (dashboard.html)
GET  /events  Server-Sent Events: a JSON snapshot every time something changes
POST /press   body "short" | "long": acts like the base's button
POST /tag     body "<UID> <cell>" per line: map board tags to cells (saved to tags.toml)
POST /scanned/clear  forget the list of scanned, unmapped tags
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

log = logging.getLogger("snl.web")
PAGE = Path(__file__).with_name("dashboard.html")


class Hub:
    """Latest snapshot + recent events, shared between the game loop and the HTTP threads."""

    def __init__(self):
        self.cond = threading.Condition()
        self.version = 0
        self.snapshot = "{}"
        self.events: deque[dict] = deque(maxlen=40)

    def update(self, snapshot: dict, events: list[dict]) -> None:
        for e in events:
            self.events.appendleft({**e, "t": time.strftime("%H:%M:%S")})
        body = json.dumps({**snapshot, "events": list(self.events)}, separators=(",", ":"))
        with self.cond:
            if body != self.snapshot:
                self.snapshot = body
                self.version += 1
                self.cond.notify_all()


def serve(hub: Hub, press: Callable[[str], None], set_tag: Callable[[str, int], None],
          clear_scanned: Callable[[], None], host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):  # keep the controller log readable
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                seen = -1
                try:
                    while True:
                        with hub.cond:
                            if hub.version == seen:
                                hub.cond.wait(timeout=15)
                            version, body = hub.version, hub.snapshot
                        if version == seen:
                            self.wfile.write(b": keepalive\n\n")
                        else:
                            seen = version
                            self.wfile.write(f"data: {body}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_error(404)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)).decode().strip()
            if self.path == "/tag":
                pairs = [line.split() for line in body.splitlines() if line.strip()]
                if not pairs or any(len(p) != 2 or not p[1].isdigit() or not 1 <= int(p[1]) <= 16
                                    or not all(c in "0123456789abcdefABCDEF" for c in p[0]) for p in pairs):
                    self.send_error(400, "body must be '<hex UID> <cell 1-16>' per line")
                    return
                for uid, cell in pairs:
                    set_tag(uid.upper(), int(cell))
                self.send_response(204)
                self.end_headers()
                return
            if self.path == "/scanned/clear":
                clear_scanned()
                self.send_response(204)
                self.end_headers()
                return
            if self.path != "/press":
                self.send_error(404)
                return
            kind = body
            if kind not in ("short", "long"):
                self.send_error(400, "body must be short or long")
                return
            log.info("dashboard: %s press", kind)
            press(kind)
            self.send_response(204)
            self.end_headers()

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="dashboard", daemon=True).start()
    log.info("dashboard on http://%s:%d", "localhost" if host in ("127.0.0.1", "0.0.0.0") else host, port)
    return srv
