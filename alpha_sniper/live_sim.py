from __future__ import annotations

import threading
import time

from .binance_feed import BinanceFeed, Quote, profile_from_quote
from .config import SniperConfig
from .engine import AlphaSniperEngine
from .snapshot import build_snapshot
from .types import SymbolProfile


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
        self._warm_done = False
        self.last_poll = 0.0
        self.feed = BinanceFeed()

    def bootstrap(self) -> None:
        try:
            if not self.feed.ping():
                raise RuntimeError(self.feed.status.last_error or "币安行情连不上")
            self.feed.check_key()
            self.feed.load_alpha_symbols()
            self.feed.load_announcements()
            tickers = self.feed.ticker_24h()
            self.feed.refresh_quotes(tickers)
            btc = self.feed.quotes.get("BTCUSDT")
            picked = self.feed.pick_universe(22)
            symbols = ["BTCUSDT"] + [q.symbol for q in picked]
            profiles = [SymbolProfile("BTCUSDT", "large", "btc", btc.price if btc else 1.0, 1e12, 8e7, False)]
            profiles += [
                profile_from_quote(self.feed.quotes[s])
                for s in symbols
                if s != "BTCUSDT" and s in self.feed.quotes
            ]
            with self.lock:
                self.engine.attach_profiles(profiles)
                self.watch = [p.symbol for p in profiles]
                self.engine.allow_new_entries = False
            for sym in list(self.watch):
                self._warmup_symbol(sym)
            with self.lock:
                self.engine.allow_new_entries = self.allow_new and self.running
                self._warm_done = True
                self.ready = True
                self.last_poll = time.time()
                for sym in self.watch:
                    q = self.feed.quotes.get(sym)
                    if q:
                        self.quotes[sym] = q
                self._record()
        except Exception as exc:
            self.boot_error = str(exc)[:240]
            self.ready = False

    def _listing_flag(self, symbol: str) -> str:
        base = symbol.replace("USDT", "")
        for art in self.feed.announcements:
            title = art.get("title") or ""
            if base and base in title.upper() and any(w in title for w in ("上线", "List", "list", "Alpha")):
                return "alpha_list" if "Alpha" in title or "alpha" in title else "spot_list"
        return ""

    def _warmup_symbol(self, symbol: str) -> None:
        quote = self.feed.quotes.get(symbol)
        depth = self.feed.depth_usd(symbol) if symbol != "BTCUSDT" else 8e7
        self._depths[symbol] = depth
        rows = self.feed.klines(symbol, "15m", 400)
        listing = self._listing_flag(symbol)
        with self.lock:
            for k in rows:
                bar = self.feed.kline_to_bar(symbol, k, quote, depth, listing if k is rows[-1] else "")
                self.engine.step(bar)
                self._last_bar_ts[symbol] = bar.ts
            if quote:
                self.engine.venue.on_price(symbol, quote.price)

    def poll(self) -> None:
        with self.lock:
            if not self.ready:
                return
            try:
                tickers = self.feed.ticker_24h()
                self.feed.refresh_quotes(tickers)
            except Exception as exc:
                self.feed.status.last_error = str(exc)[:180]
                self.feed.status.ok = False
                return
            now = time.time()
            self.last_poll = now
            self.engine.allow_new_entries = self.allow_new and self.running
            for sym in list(self.watch):
                q = self.feed.quotes.get(sym)
                if q is None:
                    continue
                self.quotes[sym] = q
                self.engine.pulse_price(sym, q.price, now)
                last = self._last_bar_ts.get(sym, 0)
                if now - last < 15 * 60:
                    continue
                try:
                    ks = self.feed.klines(sym, "15m", 2)
                except Exception:
                    continue
                if not ks:
                    continue
                k = ks[-1]
                bar = self.feed.kline_to_bar(sym, k, q, self._depths.get(sym, 0.0), self._listing_flag(sym))
                if bar.ts <= last:
                    continue
                prev = self.engine.allow_new_entries
                if sym in self.blocked:
                    self.engine.allow_new_entries = False
                self.engine.step(bar)
                self.engine.allow_new_entries = prev
                self._last_bar_ts[sym] = bar.ts
            self._record()

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
            self._record()

    def flatten_one(self, thesis_id: str) -> None:
        with self.lock:
            self.engine.flatten_one(thesis_id, time.time(), "手动平仓")
            self._record()

    def reset(self) -> None:
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
            }
            snap["quotes"] = [
                {
                    "symbol": q.symbol,
                    "price": q.price,
                    "change24h": round(q.change24h, 4),
                    "quote_volume": round(q.quote_volume, 0),
                    "is_alpha": q.is_alpha,
                }
                for q in sorted(self.quotes.values(), key=lambda x: abs(x.change24h), reverse=True)[:40]
            ]
            snap["announcements"] = self.feed.announcements[:8]
            snap["script"] = [
                {"day": 0, "symbol": "", "title": a.get("title", ""), "hint": "币安公告", "status": "live"}
                for a in self.feed.announcements[:8]
            ]
            return snap

    def _record(self) -> None:
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
