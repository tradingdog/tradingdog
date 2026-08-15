from __future__ import annotations

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import SniperConfig
from .env import load_env
from .live_sim import RealSimSession
from .session import LiveSession

WEBUI = Path(__file__).resolve().parent / "webui"


class Watchtower:
    def __init__(self, session: LiveSession, host: str = "0.0.0.0", port: int = 8765):
        self.session = session
        self.host = host
        self.port = port
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        session = self.session
        stop = self._stop

        def loop() -> None:
            while not stop.is_set():
                try:
                    with session.lock:
                        running = session.running and not session.finished
                        n = session.speed
                    if running or getattr(session, "mode", "") == "binance_sim":
                        session.tick(n)
                except Exception as exc:
                    try:
                        session.loop_error = str(exc)[:240]
                    except Exception:
                        pass
                    time.sleep(4.0)
                    continue
                time.sleep(2.4 if getattr(session, "mode", "") == "binance_sim" else 0.28)

        threading.Thread(target=loop, daemon=True).start()
        handler = _make_handler(session)
        httpd = ThreadingHTTPServer((self.host, self.port), handler)
        try:
            httpd.serve_forever()
        finally:
            stop.set()
            httpd.server_close()


def _make_handler(session: LiveSession):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_HEAD(self) -> None:
            path = urlparse(self.path).path
            if path.startswith("/api/"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/state":
                self._json(session.snapshot())
                return
            if path == "/api/stream":
                self._sse()
                return
            self._static(path)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/api/control":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self.send_error(400)
                return
            action = body.get("action")
            if action == "start":
                session.start()
            elif action == "pause":
                session.pause()
            elif action == "reset":
                session.reset()
            elif action == "speed":
                session.set_speed(int(body.get("speed", 8)))
            elif action == "next":
                session.skip_to_event()
            elif action == "flatten" and hasattr(session, "flatten"):
                session.flatten()
            elif action == "close" and hasattr(session, "flatten_one"):
                session.flatten_one(str(body.get("thesis_id", "")))
            elif action == "allow" and hasattr(session, "set_allow_new"):
                session.set_allow_new(bool(body.get("allow", True)))
            elif action == "refresh" and hasattr(session, "poll"):
                session.poll(bars=False)
            elif action == "block" and hasattr(session, "block"):
                session.block(str(body.get("symbol", "")))
            elif action == "unblock" and hasattr(session, "unblock"):
                session.unblock(str(body.get("symbol", "")))
            else:
                self.send_error(400)
                return
            self._json(session.snapshot())

        def _json(self, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(session.snapshot(), ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _static(self, path: str) -> None:
            rel = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
            target = (WEBUI / rel).resolve()
            root = WEBUI.resolve()
            if root not in target.parents and target != root:
                self.send_error(404)
                return
            if not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if target.suffix == ".js":
                mime = "text/javascript; charset=utf-8"
            elif target.suffix == ".css":
                mime = "text/css; charset=utf-8"
            elif target.suffix == ".html":
                mime = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def run_ui(host: str = "0.0.0.0", port: int = 8765, days: int = 36, seed: int = 42, paper: bool = False) -> None:
    load_env()
    if paper:
        session = LiveSession(SniperConfig(paper_days=days, seed=seed))
        print(f"监控台  http://127.0.0.1:{port}  （本地回放，不是币安行情）")
    else:
        session = RealSimSession(SniperConfig())
        print("正在后台从币安拉行情（资金仍是模拟，不会下真单）…")
        threading.Thread(target=session.bootstrap, daemon=True).start()
        print(f"监控台  http://127.0.0.1:{port}  （真实行情 + 模拟资金）")
    Watchtower(session, host=host, port=port).serve_forever()
