from __future__ import annotations

import unittest

from alpha_sniper.coiled import CoiledRegistry
from alpha_sniper.coincidence import CoincidenceEngine
from alpha_sniper.config import SniperConfig
from alpha_sniper.engine import run_paper
from alpha_sniper.risk import RiskGovernor
from alpha_sniper.types import Account, Bar, Coincidence, Pulse, SymbolProfile
from alpha_sniper.universe import PossibilitySurface


def _bar(symbol: str, ts: float, close: float, **kw) -> Bar:
    return Bar(
        ts=ts,
        symbol=symbol,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        volume=kw.get("volume", 1000),
        taker_buy_ratio=kw.get("taker_buy_ratio", 0.5),
        large_print_share=kw.get("large_print_share", 0.0),
        book_depth_usd=kw.get("book_depth_usd", 20_000),
        exchange_inflow=kw.get("exchange_inflow", 0.0),
        listing_event=kw.get("listing_event", ""),
        narrative=kw.get("narrative", ""),
        unlock_pressure=kw.get("unlock_pressure", 0.0),
        social_heat=kw.get("social_heat", 0.1),
        is_alpha=kw.get("is_alpha", False),
        is_weekend=kw.get("is_weekend", False),
    )


class CoincidenceTests(unittest.TestCase):
    def test_same_family_is_one_vote(self):
        eng = CoincidenceEngine(SniperConfig())
        ts = 10_000.0
        for i, sid in enumerate(["volume_vacuum", "silence_break", "informed_flow_fake"]):
            p = Pulse(sid, "microstructure", "X", "long", 0.8, ts + i, {})
            self.assertIsNone(eng.ingest(p, silence_before=0.9))

    def test_three_families_after_silence_fires(self):
        eng = CoincidenceEngine(SniperConfig())
        ts = 10_000.0
        pulses = [
            Pulse("a", "microstructure", "X", "long", 0.8, ts, {}),
            Pulse("b", "catalyst", "X", "long", 0.9, ts + 1, {}),
            Pulse("c", "positioning", "X", "long", 0.7, ts + 2, {}),
        ]
        self.assertIsNone(eng.ingest(pulses[0], 0.9))
        self.assertIsNone(eng.ingest(pulses[1], 0.9))
        coin = eng.ingest(pulses[2], 0.9)
        self.assertIsNotNone(coin)
        self.assertEqual(len(coin.families), 3)

    def test_no_silence_no_trade_on_long(self):
        eng = CoincidenceEngine(SniperConfig())
        ts = 10_000.0
        for fam in ("microstructure", "catalyst", "positioning"):
            coin = eng.ingest(Pulse(fam, fam, "X", "long", 0.9, ts, {}), silence_before=0.1)
        self.assertIsNone(coin)

    def test_short_allows_exhaustion_instead_of_silence(self):
        eng = CoincidenceEngine(SniperConfig())
        ts = 10_000.0
        coin = None
        for fam in ("microstructure", "calendar", "positioning"):
            coin = eng.ingest(Pulse(fam, fam, "Y", "short", 0.8, ts, {}), silence_before=0.05, exhaustion=0.8)
        self.assertIsNotNone(coin)
        self.assertEqual(coin.side, "short")


class UniverseTests(unittest.TestCase):
    def test_btc_is_not_hunting_ground(self):
        cfg = SniperConfig()
        u = PossibilitySurface(cfg)
        u.set_profiles(
            [
                SymbolProfile("BTCUSDT", "large", "beta", 1, 1e12, 1e8, False),
                SymbolProfile("COILUSDT", "alpha", "ai", 1, 5e6, 1e4, True),
            ]
        )
        self.assertFalse(u.in_hunting_ground("BTCUSDT"))
        self.assertTrue(u.in_hunting_ground("COILUSDT"))
        self.assertGreater(u.possibility("COILUSDT"), 0.7)
        self.assertEqual(u.possibility("BTCUSDT"), 0.0)
        thin = Bar(
            ts=0, symbol="THIN", open=1, high=1, low=1, close=1, volume=999999,
            book_depth_usd=15, is_alpha=True,
        )
        u.set_profiles(list(u.profiles.values()) + [
            SymbolProfile("THIN", "alpha", "vapor", 1, 8e5, 20, True)
        ])
        self.assertLess(u.exit_liquidity("THIN", thin), 0.28)


class CoiledSilenceTests(unittest.TestCase):
    def test_slow_grind_is_exhaustion_not_silence(self):
        reg = CoiledRegistry(SniperConfig())
        px = 1.0
        for i in range(130):
            px *= 1.004
            reg.on_bar(_bar("D", i * 900, px, volume=5000, book_depth_usd=20_000))
        st = reg.states["D"]
        self.assertLess(st.silence, 0.4)
        self.assertGreater(st.exhaustion, 0.5)


class RiskTests(unittest.TestCase):
    def test_rejects_leverage_above_1x(self):
        g = RiskGovernor(SniperConfig())
        self.assertTrue(g.leverage_ok("futures_1x", 1.0))
        self.assertFalse(g.leverage_ok("futures_1x", 2.0))

    def test_btc_stress_blocks_longs(self):
        g = RiskGovernor(SniperConfig())
        acc = Account(cash=1000, starting=1000)
        self.assertEqual(g.allow_new(acc, 0, 0, "btc_stress", "long"), "btc_stress")
        self.assertIsNone(g.allow_new(acc, 0, 0, "btc_stress", "short"))

    def test_ratchet_locks_on_double(self):
        g = RiskGovernor(SniperConfig())
        acc = Account(cash=2200, starting=1000, last_double_lock=1000)
        locked = g.ratchet(acc, 2200)
        self.assertGreater(locked, 0)
        self.assertGreater(acc.vault, 0)
        self.assertAlmostEqual(acc.cash + acc.vault, 2200)


class LiveGuardTests(unittest.TestCase):
    def test_live_is_off_and_leverage_blocked(self):
        from alpha_sniper.live_binance import LiveBinanceGuard

        g = LiveBinanceGuard(SniperConfig(live=False), api_key="", api_secret="")
        self.assertFalse(g.can_live())
        with self.assertRaises(PermissionError):
            g.assert_order_legal("futures_1x", 1.0)
        g2 = LiveBinanceGuard(SniperConfig(live=True), api_key="x", api_secret="y")
        with self.assertRaises(PermissionError):
            g2.assert_order_legal("futures_1x", 3.0)


class PaperPathTests(unittest.TestCase):
    def test_paper_catches_fat_tail_and_skips_noise(self):
        cfg = SniperConfig(paper_days=36, seed=42, paper_bar_seconds=15 * 60)
        eng = run_paper(cfg)
        traded = {t.symbol: t for t in eng.book.closed}
        self.assertIn("COILUSDT", traded, f"should snipe coil, got {list(traded)}")
        self.assertEqual(traded["COILUSDT"].side, "long")
        self.assertIn("DUMPUSDT", traded, f"should short dump, got {list(traded)}")
        self.assertEqual(traded["DUMPUSDT"].side, "short")
        self.assertIn("LAGUSDT", traded, f"should buy narrative laggard, got {list(traded)}")
        self.assertEqual(traded["LAGUSDT"].side, "long")
        self.assertIn("narrative", traded["LAGUSDT"].families)
        self.assertNotIn("FAKEUSDT", traded)
        self.assertNotIn("DEADUSDT", traded)
        self.assertNotIn("THINUSDT", traded)
        # DUMP 应做成空头；若没吃到也不许做成追高多
        if "DUMPUSDT" in traded:
            self.assertEqual(traded["DUMPUSDT"].side, "short")
        stress_longs = [t for t in eng.book.closed if t.symbol == "STRESSUSDT" and t.side == "long"]
        self.assertEqual(stress_longs, [])
        self.assertTrue(any(why == "btc_stress" for _, why in eng.skips) or "STRESSUSDT" not in traded)


class ChaseMissTests(unittest.TestCase):
    def test_three_families_without_silence_is_logged(self):
        from alpha_sniper.coiled import CoiledState
        from alpha_sniper.engine import AlphaSniperEngine

        eng = AlphaSniperEngine()
        eng.record_events = True
        ts = 1_700_000_000.0
        for fam in ("microstructure", "catalyst", "positioning"):
            eng.coincidence.ingest(Pulse(fam, fam, "XUSDT", "long", 0.9, ts, {}), silence_before=0.05)
        bar = _bar("XUSDT", ts, 1.0)
        coiled = CoiledState("XUSDT", 0.1, 0.1, 0.05, 0.1, 0.1, 0.12, "long", "spot", 0.97, False)
        eng._log_blocked_coincidence(bar, coiled, set())
        self.assertTrue(eng.near_misses)
        self.assertIn("追涨", eng.near_misses[-1]["reason"])
        self.assertEqual(eng.near_misses[-1]["origin"], "live")
        self.assertGreater(eng.near_misses[-1]["seen_at"], 0)
        self.assertEqual(eng.scan["blocked_chase"], 1)


class PersistTests(unittest.TestCase):
    def test_saves_and_restores_open_thesis(self):
        import tempfile
        from pathlib import Path

        from alpha_sniper import persist as persist_mod
        from alpha_sniper.engine import JournalEvent
        from alpha_sniper.live_sim import RealSimSession
        from alpha_sniper.types import FourScores, Thesis

        session = RealSimSession()
        session.engine.account.cash = 880
        thesis = Thesis(
            id="T9",
            symbol="FOOUSDT",
            side="long",
            venue="spot",
            hypothesis="test",
            opened_ts=1_700_000_000,
            entry=1.0,
            qty=100,
            notional=100,
            invalidation=0.9,
            time_stop_ts=1_700_000_000 + 12 * 3600,
            peak=1.02,
            families=("microstructure", "catalyst", "positioning"),
            scores=FourScores(0.7, 0.6, 0.2, 0.5),
            remaining_qty=100,
        )
        session.engine.book.open[thesis.id] = thesis
        session.engine.journal.append(JournalEvent(thesis.opened_ts, "open", thesis.symbol, "测"))
        session.engine.venue.on_price("FOOUSDT", 1.01)
        session._last_bar_ts = {"FOOUSDT": 1_700_000_000.0}
        old = persist_mod.STATE_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                persist_mod.STATE_PATH = Path(tmp) / "live_state.json"
                persist_mod.save_state(session)
                payload = persist_mod.load_state()
                self.assertIsNotNone(payload)
                self.assertEqual(payload.get("bar_interval"), "1h")
                self.assertEqual(payload.get("version"), 2)
                fresh = RealSimSession()
                persist_mod.apply_state(fresh, payload)
                self.assertAlmostEqual(fresh.engine.account.cash, 880)
                self.assertIn("T9", fresh.engine.book.open)
                self.assertEqual(fresh.engine.book.open["T9"].symbol, "FOOUSDT")
                self.assertTrue(any(e.kind == "open" for e in fresh.engine.journal))
                self.assertAlmostEqual(fresh._last_bar_ts["FOOUSDT"], 1_700_000_000.0)
        finally:
            persist_mod.STATE_PATH = old


class BoxBreakoutTests(unittest.TestCase):
    def test_quiet_box_then_wide_body_ignites(self):
        reg = CoiledRegistry(SniperConfig())
        px = 1.0
        for i in range(90):
            vol = 6000 if i < 25 else 350
            reg.on_bar(_bar("MOONUSDT", i * 3600, px, volume=vol, book_depth_usd=8_000))
        self.assertTrue(reg.states["MOONUSDT"].armed)
        self.assertFalse(reg.states["MOONUSDT"].ignited)
        st = reg.on_bar(
            Bar(
                ts=90 * 3600,
                symbol="MOONUSDT",
                open=1.0,
                high=1.09,
                low=0.998,
                close=1.08,
                volume=12_000,
                taker_buy_ratio=0.74,
                large_print_share=0.45,
                book_depth_usd=5_000,
            )
        )
        self.assertTrue(st.ignited)
        self.assertFalse(st.extended)
        self.assertGreater(st.range_expand, 1.6)

    def test_extended_without_catalyst_waits_for_pullback(self):
        from alpha_sniper.coiled import CoiledState
        from alpha_sniper.engine import AlphaSniperEngine

        eng = AlphaSniperEngine()
        bar = _bar("MOONUSDT", 1_700_000_000, 1.20)
        coiled = CoiledState(
            "MOONUSDT", 0.6, 0.6, 0.7, 0.5, 0.1, 0.6, "long", "spot", 0.97, True,
            box_high=1.0, box_low=0.96, ignited=True, pullback_ready=False, extended=True, range_expand=3.0,
        )
        lag = Coincidence(
            "MOONUSDT", "long", bar.ts, ("microstructure", "narrative", "positioning"), (), 0.8, 0.7,
        )
        why = eng._morphology_reason(bar, coiled, lag)
        self.assertIsNotNone(why)
        self.assertIn("回踩", why)
        listed = Coincidence(
            "MOONUSDT", "long", bar.ts, ("microstructure", "catalyst", "positioning"), (), 0.8, 0.7,
        )
        self.assertIsNone(eng._morphology_reason(bar, coiled, listed))

    def test_no_fuse_is_rejected(self):
        from alpha_sniper.coiled import CoiledState
        from alpha_sniper.engine import AlphaSniperEngine

        eng = AlphaSniperEngine()
        bar = _bar("XUSDT", 1, 1.0)
        coiled = CoiledState(
            "XUSDT", 0.6, 0.6, 0.7, 0.5, 0.1, 0.6, "long", "spot", 0.97, True,
            ignited=True, pullback_ready=False, extended=False,
        )
        coin = Coincidence("XUSDT", "long", 1, ("microstructure", "positioning"), (), 0.8, 0.7)
        why = eng._morphology_reason(bar, coiled, coin)
        self.assertIsNotNone(why)
        self.assertIn("导火线", why)


class AnnouncementMatchTests(unittest.TestCase):
    def test_listing_and_delist_keywords(self):
        from alpha_sniper.binance_feed import match_announcement

        self.assertEqual(match_announcement("Binance Will List FOO", "FOO"), "spot_list")
        self.assertEqual(match_announcement("Binance Alpha 上线 BAR", "BAR"), "alpha_list")
        self.assertEqual(match_announcement("Binance Will Delist BAZ", "BAZ"), "delist")
        self.assertEqual(match_announcement("无相关", "FOO"), "")


if __name__ == "__main__":
    unittest.main()
