from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from pathlib import Path

from alpha_sniper.config import SniperConfig
from alpha_sniper.session import LiveSession
from alpha_sniper.web import _make_handler


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_human_readable(self):
        session = LiveSession(SniperConfig(paper_days=2, seed=42))
        session.tick(8)
        snap = session.snapshot()
        self.assertIn(snap["state"], {"SQUAT", "ARMED", "IN_THESIS"})
        self.assertTrue(snap["narration"])
        self.assertTrue(any(w in snap["narration"] + snap["state_zh"] for w in ("空仓", "持仓", "盯")))
        self.assertGreaterEqual(snap["account"]["equity"], 1)
        self.assertTrue(snap["hunt"])
        self.assertTrue(snap["discoveries"])
        self.assertIn("trades", snap["performance"])
        self.assertTrue(snap["rules"])
        self.assertTrue(any(row["family_lamps"] for row in snap["hunt"]))
        self.assertEqual(len(snap["risk"]["gates"]), 6)
        self.assertFalse(snap["live"])

    def test_next_shot_lands_on_coil(self):
        session = LiveSession(SniperConfig(paper_days=36, seed=42))
        kind = session.skip_to_event()
        self.assertEqual(kind, "event")
        snap = session.snapshot()
        self.assertTrue(
            any(t["symbol"] == "COILUSDT" and t["side"] == "long" for t in snap["theses"]),
            snap["theses"],
        )
        self.assertTrue(any("COIL" in snap["narration"] or t["symbol"] == "COILUSDT" for t in snap["theses"]))
        coil = next(t for t in snap["theses"] if t["symbol"] == "COILUSDT")
        self.assertGreater(coil["notional"], 10)
        self.assertGreater(coil["entry"], 0)
        self.assertGreater(coil["invalidation"], 0)
        self.assertIn("做多", coil["why_side"])
        self.assertTrue(coil["binance_url"].endswith("COIL_USDT?type=spot"))

    def test_manual_flatten_closes_open_position(self):
        session = LiveSession(SniperConfig(paper_days=36, seed=42))
        session.skip_to_event()
        self.assertTrue(session.snapshot()["theses"])
        session.flatten()
        self.assertFalse(session.snapshot()["theses"])
        self.assertTrue(any(t["exit_reason"] == "手动全部平仓" for t in session.snapshot()["closed"]))


class ReplayFileTests(unittest.TestCase):
    def test_replay_json_ready_for_browser(self):
        path = Path(__file__).resolve().parents[1] / "webui" / "replay.json"
        self.assertTrue(path.is_file(), "先运行 python -m alpha_sniper export")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["frames"]), 20)
        first = data["frames"][0]
        self.assertIn("narration", first)
        self.assertIn("hunt", first)
        self.assertIn("account", first)
        from alpha_sniper.export_replay import build_standalone

        stand = build_standalone()
        text = stand.read_text(encoding="utf-8")
        self.assertIn("<!DOCTYPE html>", text)
        self.assertIn('id="replay-data"', text)
        self.assertIn("交易监控", text)
        self.assertGreater(stand.stat().st_size, 50_000)


class HttpTests(unittest.TestCase):
    def test_pages_and_state(self):
        session = LiveSession(SniperConfig(paper_days=2, seed=42))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(session))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
            self.assertIn("交易监控", html)
            self.assertIn("发现了什么", html)
            self.assertIn("成绩单", html)
            self.assertIn("当前持仓", html)
            self.assertIn("继续开仓", html)
            self.assertIn('id="discoveries" class="disc-wrap"', html)
            self.assertNotIn("下一枪", html)
            self.assertNotIn("当前命题", html)
            css = urllib.request.urlopen(f"http://127.0.0.1:{port}/app.css", timeout=5).read().decode()
            self.assertIn("--amber", css)
            self.assertIn("disc-wrap", css)
            self.assertIn("overflow-anchor: none", css)
            self.assertIn("max-width: 720px", css)
            self.assertIn("position: sticky", css)
            js = urllib.request.urlopen(f"http://127.0.0.1:{port}/app.js", timeout=5).read().decode()
            self.assertIn("disc-head", js)
            self.assertIn("可用资金", js)
            self.assertIn("锁定利润", js)
            self.assertIn("restoreDiscScroll", js)
            self.assertIn("patchDiscoveryLive", js)
            self.assertNotIn("__OPEN_INIT", js)
            raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5).read()
            state = json.loads(raw.decode())
            self.assertIn("narration", state)
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/control",
                data=json.dumps({"action": "start"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            opened = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            self.assertTrue(opened["running"])
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/control",
                data=json.dumps({"action": "pause"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            paused = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            self.assertFalse(paused["running"])
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/control",
                data=json.dumps({"action": "start"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resumed = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            self.assertTrue(resumed["running"])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
