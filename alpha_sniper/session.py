from __future__ import annotations

import threading

from .config import SniperConfig
from .engine import AlphaSniperEngine
from .paper import PaperUniverse
from .snapshot import build_snapshot


WATCH = ("BTCUSDT", "COILUSDT", "DUMPUSDT", "LAGUSDT", "LEADUSDT", "FAKEUSDT", "STRESSUSDT")


class LiveSession:
    """可暂停、加速、跳到下一枪的纸上演练。给观察台用，不替代 run_paper。"""

    def __init__(self, config: SniperConfig | None = None):
        self.config = config or SniperConfig(paper_days=36, seed=42)
        self.lock = threading.RLock()
        self.running = False
        self.finished = False
        self.speed = 8
        self.engine = AlphaSniperEngine(self.config)
        self.world = PaperUniverse(self.config)
        self.ts = 0.0
        self.equity_curve: list[dict] = []
        self.price_tails: dict[str, list[list[float]]] = {s: [] for s in WATCH}
        self._rebuild()

    def _rebuild(self) -> None:
        self.engine = AlphaSniperEngine(self.config)
        self.world = PaperUniverse(self.config)
        self.engine.attach_profiles(self.world.profiles)
        self.ts = 0.0
        self.finished = False
        self.running = False
        self.equity_curve = []
        self.price_tails = {s: [] for s in WATCH}
        self._record()

    def reset(self) -> None:
        with self.lock:
            self._rebuild()

    def start(self) -> None:
        with self.lock:
            if not self.finished:
                self.running = True

    def pause(self) -> None:
        with self.lock:
            self.running = False

    def set_speed(self, speed: int) -> None:
        with self.lock:
            self.speed = max(1, min(256, int(speed)))

    def tick(self, n_bars: int = 1) -> None:
        with self.lock:
            self._tick_unlocked(n_bars)

    def _tick_unlocked(self, n_bars: int) -> None:
        if self.finished:
            return
        step = self.config.paper_bar_seconds
        end = self.config.paper_days * 86400
        ordered = ["BTCUSDT"] + [s for s in self.world.symbols if s != "BTCUSDT"]
        for _ in range(max(1, n_bars)):
            if self.ts > end:
                self.engine.flatten_all(end)
                self.finished = True
                self.running = False
                self._record()
                return
            for symbol in ordered:
                self.engine.step(self.world.bar(symbol, self.ts))
            self._record()
            self.ts += step

    def skip_to_event(self) -> str:
        """快进到下一笔开火/离场，方便人眼跟上「一枪」。"""
        with self.lock:
            start = len(self.engine.journal)
            for _ in range(4000):
                if self.finished:
                    return "end"
                self._tick_unlocked(1)
                fresh = self.engine.journal[start:]
                if any(e.kind in {"open", "close"} for e in fresh):
                    self.running = False
                    return "event"
            return "timeout"

    def snapshot(self) -> dict:
        with self.lock:
            return build_snapshot(self)

    def _record(self) -> None:
        eq = self.engine.equity()
        self.equity_curve.append(
            {
                "t": round(self.engine.now / 86400.0, 4),
                "e": round(eq, 2),
                "c": round(self.engine.account.cash, 2),
                "v": round(self.engine.account.vault, 2),
            }
        )
        if len(self.equity_curve) > 800:
            self.equity_curve = self.equity_curve[::2][-600:]
        day = self.engine.now / 86400.0
        for sym in WATCH:
            px = self.engine.venue.marks.get(sym)
            if px is None:
                continue
            tail = self.price_tails.setdefault(sym, [])
            tail.append([round(day, 4), round(px, 8)])
            if len(tail) > 240:
                self.price_tails[sym] = tail[-240:]
