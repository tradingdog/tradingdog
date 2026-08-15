from __future__ import annotations

import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from .binance_feed import BinanceFeed, Quote, kline_is_closed, profile_from_quote
from .config import SniperConfig
from .engine import AlphaSniperEngine
from .persist import apply_state, clear_state, load_state, save_state
from .snapshot import build_snapshot
from .types import SymbolProfile

BAR_SEC = 15 * 60
HUNT_BARS = 192
MIN_WARM_BARS = 130
UNIVERSE_REFRESH_SEC = 6 * 3600


class RealSimSession:
    """币安真实行情 + 模拟资金。默认不下真实订单。"""

    mode = "binance_sim"

    def __init__(self, config: SniperConfig | None = None):
        self.config = config or SniperConfig()
        self.lock = threading.RLock()
        self.feed = BinanceFeed()
        self._rebuild()

    def _rebuild(self) -> None:
        self.running = True
        self.finished = False
        self.speed = 1
        self.ready = False
        self.boot_error = ""
        self.allow_new = True
        self.blocked: set[str] = set()
        self.engine = AlphaSniperEngine(self.config)
        self.equity_curve: list[dict] = []
        self.price_tails: dict[str, list[list[float]]] = {}
        self.watch: list[str] = ["BTCUSDT"]
        self.quotes: dict[str, Quote] = {}
        self._last_bar_ts: dict[str, float] = {}
        self._depths: dict[str, float] = {}
        self._closes: dict[str, list[float]] = defaultdict(list)
        self._warm_done = False
        self.last_poll = 0.0
        self.loop_error = ""
        self.saved_at = 0.0
        self.universe_ts = 0.0
        self.health: dict = {}
        self._last_save = 0.0
        self._journal_n = 0
        self.feed = BinanceFeed()

    def bootstrap(self) -> None:
        try:
            self._bootstrap_inner()
        except Exception as exc:
            self.boot_error = str(exc)[:240]
            self.ready = False

    def _bootstrap_inner(self) -> None:
        if not self.feed.ping():
            raise RuntimeError(self.feed.status.last_error or "币安行情连不上")
        self.feed.check_key()
        self.feed.load_alpha_symbols()
        self.feed.load_announcements()
        tickers = self.feed.ticker_24h()
        self.feed.refresh_quotes(tickers)
        saved = load_state()
        btc = self.feed.quotes.get("BTCUSDT")
        picked = self.feed.pick_universe(22)
        symbols = ["BTCUSDT"] + [q.symbol for q in picked]
        if saved:
            for raw in list(saved.get("open") or []) + list(saved.get("watch") or []):
                if isinstance(raw, dict):
                    sym = str(raw.get("symbol") or "")
                else:
                    sym = str(raw or "")
                if sym.endswith("USDT") and sym not in symbols:
                    symbols.append(sym)
        profiles = [SymbolProfile("BTCUSDT", "large", "btc", btc.price if btc else 1.0, 1e12, 8e7, False)]
        profiles += [
            profile_from_quote(self.feed.quotes[s])
            for s in symbols
            if s != "BTCUSDT" and s in self.feed.quotes
        ]
        missing = [s for s in symbols if s != "BTCUSDT" and s not in self.feed.quotes]
        if missing:
            try:
                extra = self.feed.ticker_24h(missing)
                self.feed.refresh_quotes((tickers or []) + extra)
            except Exception:
                extra = []
            for s in missing:
                q = self.feed.quotes.get(s)
                if q:
                    profiles.append(profile_from_quote(q))
        with self.lock:
            self.engine.attach_profiles(profiles)
            self.watch = [p.symbol for p in profiles]
            self.engine.allow_new_entries = False
            self.engine.record_events = False
            self._closes = defaultdict(list)
            self._last_bar_ts = {}

        hist = self._load_histories(self.watch)
        by_ts: dict[int, dict[str, list]] = defaultdict(dict)
        for sym, (_depth, rows) in hist.items():
            for k in rows:
                try:
                    by_ts[int(k[0])][sym] = k
                except (TypeError, ValueError, IndexError):
                    continue
        stamps = sorted(by_ts)
        now = time.time()
        closed = [t for t in stamps if kline_is_closed(next(iter(by_ts[t].values())), now)]
        hunt_n = 0 if saved else min(HUNT_BARS, max(0, len(closed) - MIN_WARM_BARS))
        split = len(closed) - hunt_n
        warm_stamps = closed[:split]
        hunt_stamps = closed[split:]
        last_closed = closed[-1] if closed else 0

        for ts in warm_stamps:
            self._replay_stamp(by_ts[ts], listing_ts=last_closed if saved else 0, allow_open=False)
        if saved:
            for ts in hunt_stamps:
                self._replay_stamp(by_ts[ts], listing_ts=last_closed, allow_open=False)
            with self.lock:
                apply_state(self, saved)
                self.engine.allow_new_entries = self.allow_new and self.running
                self.engine.record_events = True
        else:
            with self.lock:
                self.engine.allow_new_entries = self.allow_new and self.running
                self.engine.record_events = True
            for ts in hunt_stamps:
                self._replay_stamp(by_ts[ts], listing_ts=last_closed, allow_open=True)
        if stamps and stamps[-1] not in closed:
            self._replay_stamp(by_ts[stamps[-1]], listing_ts=0, allow_open=False)

        with self.lock:
            self._warm_done = True
            self.ready = True
            self.last_poll = time.time()
            self.universe_ts = time.time()
            wall = time.time()
            for sym in self.watch:
                q = self.feed.quotes.get(sym)
                if q:
                    self.quotes[sym] = q
                    self.engine.pulse_price(sym, q.price, wall)
            opens = sum(1 for e in self.engine.journal if e.kind == "open")
            self.health = {
                "hunt_bars": len(hunt_stamps),
                "hunt_opens": opens,
                "open_now": self.engine.book.open_count(),
                "closed": len(self.engine.book.closed),
                "restored": bool(saved),
                "watch": len(self.watch),
                "note": (
                    "从上次状态恢复"
                    if saved
                    else "启动时用最近约 48 小时已收盘的 15 分钟 K 线，按同一套开仓纪律回放"
                ),
            }
            self._record(force=True)
            print(
                f"[sniper] 就绪 盯盘{len(self.watch)} 回放K线{len(hunt_stamps)} "
                f"开仓{opens} 持仓{self.engine.book.open_count()} "
                f"近失{len(self.engine.near_misses)} 恢复={bool(saved)}",
                flush=True,
            )

    def _load_histories(self, symbols: list[str]) -> dict[str, tuple[float, list]]:
        out: dict[str, tuple[float, list]] = {}

        def one(sym: str):
            depth = self.feed.depth_usd(sym) if sym != "BTCUSDT" else 8e7
            if depth <= 1 and sym != "BTCUSDT":
                q = self.feed.quotes.get(sym)
                depth = max((q.quote_volume * 0.004) if q else 0.0, 2_000)
            rows = self.feed.klines(sym, "15m", 400)
            return sym, depth, rows

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(one, s) for s in symbols]
            for fut in as_completed(futs):
                try:
                    sym, depth, rows = fut.result()
                except Exception:
                    continue
                self._depths[sym] = depth
                out[sym] = (depth, rows or [])
        return out

    def _replay_stamp(
        self,
        kmap: dict[str, list],
        listing_ts: int,
        allow_open: bool,
        indicators_only: bool = False,
    ) -> None:
        ordered = ["BTCUSDT"] + [s for s in self.watch if s != "BTCUSDT"]
        for sym in ordered:
            k = kmap.get(sym)
            if not k:
                continue
            try:
                close_px = float(k[4])
                open_ms = int(k[0])
            except (TypeError, ValueError, IndexError):
                continue
            xs = self._closes[sym]
            xs.append(close_px)
            if len(xs) > 800:
                self._closes[sym] = xs[-500:]
                xs = self._closes[sym]
            if len(xs) >= 96 and xs[-96] > 0:
                chg = xs[-1] / xs[-96] - 1.0
            else:
                q = self.feed.quotes.get(sym)
                chg = q.change24h if q else 0.0
            listing = self._listing_flag(sym) if listing_ts and open_ms == listing_ts else ""
            quote = self.feed.quotes.get(sym)
            bar = self.feed.kline_to_bar(sym, k, quote, self._depths.get(sym, 0.0), listing, change_24h=chg)
            with self.lock:
                if indicators_only:
                    self.engine.ingest_history(bar)
                    self._last_bar_ts[sym] = bar.ts
                    continue
                prev = self.engine.allow_new_entries
                blocked = sym in self.blocked
                self.engine.allow_new_entries = bool(allow_open and prev and not blocked)
                self.engine.step(bar)
                self.engine.allow_new_entries = prev
                self._last_bar_ts[sym] = bar.ts

    def _listing_flag(self, symbol: str) -> str:
        base = symbol.replace("USDT", "")
        for art in self.feed.announcements:
            title = art.get("title") or ""
            if base and base in title.upper() and any(w in title for w in ("上线", "List", "list", "Alpha")):
                return "alpha_list" if "Alpha" in title or "alpha" in title else "spot_list"
        return ""

    def poll(self, bars: bool = True) -> None:
        if not self.ready:
            return
        with self.lock:
            watch = list(self.watch)
        try:
            tickers = self.feed.ticker_24h(watch)
            self.feed.refresh_quotes(tickers)
        except Exception as exc:
            self.feed.status.last_error = str(exc)[:180]
            self.feed.status.ok = False
            return
        now = time.time()
        pending: list[tuple[str, Quote]] = []
        refresh_universe = False
        with self.lock:
            self.last_poll = now
            self.engine.allow_new_entries = self.allow_new and self.running
            if now - self.universe_ts >= UNIVERSE_REFRESH_SEC:
                refresh_universe = True
            for sym in list(self.watch):
                q = self.feed.quotes.get(sym)
                if q is None:
                    continue
                self.quotes[sym] = q
                self.engine.pulse_price(sym, q.price, now)
                last = self._last_bar_ts.get(sym, 0)
                if bars and now >= last + 2 * BAR_SEC - 2:
                    pending.append((sym, q))
            if not pending and not refresh_universe:
                self._record()
                return
        if refresh_universe:
            try:
                self._refresh_universe()
            except Exception as exc:
                self.loop_error = f"换盯盘失败: {exc}"[:240]
        for sym, q in pending:
            try:
                ks = self.feed.klines(sym, "15m", 3)
            except Exception:
                continue
            closed = [k for k in ks if kline_is_closed(k, now)]
            if not closed:
                continue
            k = closed[-1]
            try:
                open_t = float(k[0]) / 1000.0
                close_px = float(k[4])
            except (TypeError, ValueError, IndexError):
                continue
            with self.lock:
                last = self._last_bar_ts.get(sym, 0)
                if open_t <= last:
                    continue
                xs = self._closes[sym]
                xs.append(close_px)
                if len(xs) > 800:
                    self._closes[sym] = xs[-500:]
                    xs = self._closes[sym]
                if len(xs) >= 96 and xs[-96] > 0:
                    chg = xs[-1] / xs[-96] - 1.0
                else:
                    chg = q.change24h
                bar = self.feed.kline_to_bar(
                    sym, k, q, self._depths.get(sym, 0.0), self._listing_flag(sym), change_24h=chg
                )
                prev = self.engine.allow_new_entries
                if sym in self.blocked:
                    self.engine.allow_new_entries = False
                self.engine.step(bar)
                self.engine.allow_new_entries = prev
                self._last_bar_ts[sym] = bar.ts
        with self.lock:
            self._record()

    def _refresh_universe(self) -> None:
        try:
            all_tickers = self.feed.ticker_24h()
            self.feed.refresh_quotes(all_tickers)
        except Exception as exc:
            self.feed.status.last_error = str(exc)[:180]
            return
        picked = self.feed.pick_universe(22)
        with self.lock:
            held = {t.symbol for t in self.engine.book.open.values() if t.status == "open"}
            nxt = ["BTCUSDT"] + [q.symbol for q in picked]
            for sym in held:
                if sym not in nxt:
                    nxt.append(sym)
            added = [s for s in nxt if s not in self.watch]
            self.watch = nxt
            profiles = []
            btc = self.feed.quotes.get("BTCUSDT")
            profiles.append(SymbolProfile("BTCUSDT", "large", "btc", btc.price if btc else 1.0, 1e12, 8e7, False))
            for s in nxt:
                if s == "BTCUSDT":
                    continue
                q = self.feed.quotes.get(s)
                if q:
                    profiles.append(profile_from_quote(q))
            self.engine.attach_profiles(profiles)
            self.universe_ts = time.time()
        if not added:
            return
        hist = self._load_histories(added)
        by_ts: dict[int, dict[str, list]] = defaultdict(dict)
        for sym, (_depth, rows) in hist.items():
            for k in rows:
                try:
                    by_ts[int(k[0])][sym] = k
                except (TypeError, ValueError, IndexError):
                    continue
        now = time.time()
        for ts in sorted(by_ts):
            self._replay_stamp(by_ts[ts], listing_ts=0, allow_open=False, indicators_only=True)

    def start(self) -> None:
        with self.lock:
            self.running = True
            self.allow_new = True
            self.engine.allow_new_entries = True

    def pause(self) -> None:
        with self.lock:
            self.running = False
            self.allow_new = False
            self.engine.allow_new_entries = False

    def set_allow_new(self, allow: bool) -> None:
        with self.lock:
            self.allow_new = bool(allow)
            self.engine.allow_new_entries = self.allow_new and self.running

    def flatten(self) -> None:
        with self.lock:
            self.engine.flatten_all(time.time(), "手动全部平仓")
            self._record(force=True)

    def flatten_one(self, thesis_id: str) -> None:
        with self.lock:
            self.engine.flatten_one(thesis_id, time.time(), "手动平仓")
            self._record(force=True)

    def reset(self) -> None:
        clear_state()
        with self.lock:
            allow = self.allow_new
            running = self.running
            blocked = set(self.blocked)
            self._rebuild()
            self.blocked = blocked
            self.allow_new = allow
            self.running = running
        threading.Thread(target=self.bootstrap, daemon=True).start()

    def block(self, symbol: str) -> None:
        with self.lock:
            if symbol:
                self.blocked.add(symbol.upper())

    def unblock(self, symbol: str) -> None:
        with self.lock:
            self.blocked.discard(symbol.upper())

    def set_speed(self, speed: int) -> None:
        with self.lock:
            self.speed = max(1, min(8, int(speed)))

    def skip_to_event(self) -> str:
        self.poll()
        return "polled"

    def tick(self, n_bars: int = 1) -> None:
        self.poll()

    def snapshot(self) -> dict:
        with self.lock:
            snap = build_snapshot(self)
            snap["mode"] = "binance_sim"
            snap["live_market"] = True
            snap["sim_funds"] = True
            snap["ready"] = self.ready
            snap["boot_error"] = self.boot_error
            snap["allow_new"] = self.allow_new
            snap["blocked"] = sorted(self.blocked)
            snap["last_poll"] = self.last_poll
            snap["loop_error"] = self.loop_error
            snap["health"] = {
                **self.health,
                "watch": len(self.watch),
                "saved_at": self.saved_at,
                "loop_error": self.loop_error,
                "scan": dict(self.engine.scan),
                "persist": bool(self.saved_at),
            }
            snap["feed"] = {
                "ok": self.feed.status.ok,
                "host": self.feed.status.host,
                "latency_ms": self.feed.status.latency_ms,
                "last_error": self.feed.status.last_error,
                "key_ok": self.feed.status.key_ok,
                "key_note": self.feed.status.key_note,
                "symbols": self.feed.status.symbols,
                "alpha": len(self.feed.alpha),
                "last_poll": self.last_poll,
                "watch": len(self.watch),
            }
            snap["quotes"] = [
                {
                    "symbol": q.symbol,
                    "price": q.price,
                    "change24h": round(q.change24h, 4),
                    "quote_volume": round(q.quote_volume, 0),
                    "is_alpha": q.is_alpha,
                    "bucket": q.bucket,
                }
                for q in sorted(self.quotes.values(), key=lambda x: abs(x.change24h), reverse=True)[:40]
            ]
            snap["announcements"] = self.feed.announcements[:8]
            snap["script"] = [
                {"day": 0, "symbol": "", "title": a.get("title", ""), "hint": "币安公告", "status": "live"}
                for a in self.feed.announcements[:8]
            ]
            return snap

    def _record(self, force: bool = False) -> None:
        eq = self.engine.equity()
        now = time.time()
        self.equity_curve.append(
            {
                "t": round(now / 86400.0, 5),
                "e": round(eq, 2),
                "c": round(self.engine.account.cash, 2),
                "v": round(self.engine.account.vault, 2),
            }
        )
        if len(self.equity_curve) > 800:
            self.equity_curve = self.equity_curve[::2][-600:]
        n = len(self.engine.journal)
        if force or n != self._journal_n or now - self._last_save >= 20:
            try:
                save_state(self)
                self.saved_at = now
                self._last_save = now
                self._journal_n = n
            except Exception as exc:
                self.loop_error = f"落盘失败: {exc}"[:240]
