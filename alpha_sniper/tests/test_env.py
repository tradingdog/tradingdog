from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from alpha_sniper.env import load_env


class EnvTests(unittest.TestCase):
    def test_load_env_does_not_override_existing(self):
        os.environ["ALPHA_SNIPER_TEST_KEY"] = "keep-me"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("ALPHA_SNIPER_TEST_KEY=new\nALPHA_SNIPER_TEST_OTHER=1\n", encoding="utf-8")
            load_env(path)
        self.assertEqual(os.environ["ALPHA_SNIPER_TEST_KEY"], "keep-me")
        self.assertEqual(os.environ.get("ALPHA_SNIPER_TEST_OTHER"), "1")
        os.environ.pop("ALPHA_SNIPER_TEST_OTHER", None)
        os.environ.pop("ALPHA_SNIPER_TEST_KEY", None)

    def test_snapshot_does_not_leak_keys(self):
        from alpha_sniper.env import binance_keys
        from alpha_sniper.config import SniperConfig
        from alpha_sniper.session import LiveSession

        key, secret = binance_keys()
        snap = json.dumps(LiveSession(SniperConfig(paper_days=1, seed=1)).snapshot(), ensure_ascii=False)
        if key:
            self.assertNotIn(key, snap)
        if secret:
            self.assertNotIn(secret, snap)
