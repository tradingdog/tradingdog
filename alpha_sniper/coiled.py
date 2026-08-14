from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from math import sqrt

from .config import SniperConfig
from .types import Bar, Side, SymbolProfile, Venue


@dataclass
class CoiledState:
    symbol: str
    compression: float
    volume_dry: float
    silence: float
    vacuum: float
    exhaustion: float
    coiled_score: float
    preferred_side: Side
    venue: Venue
    invalidation_hint: float
    armed: bool


class CoiledRegistry:
    """缩簧表：开火前就把失效价、通道、方向算好。点火后只许执行。"""

    def __init__(self, config: SniperConfig):
        self.config = config
        self.profiles: dict[str, SymbolProfile] = {}
        self._bars: dict[str, deque[Bar]] = defaultdict(lambda: deque(maxlen=96 * 30))
        self.states: dict[str, CoiledState] = {}

    def set_profiles(self, profiles: list[SymbolProfile]) -> None:
        self.profiles = {p.symbol: p for p in profiles}

    def on_bar(self, bar: Bar) -> CoiledState:
        hist = self._bars[bar.symbol]
        hist.append(bar)
        state = self._compute(bar.symbol)
        self.states[bar.symbol] = state
        return state

    def _compute(self, symbol: str) -> CoiledState:
        hist = list(self._bars[symbol])
        profile = self.profiles.get(symbol)
        venue: Venue = "alpha" if (profile and profile.is_alpha) else "spot"
        if len(hist) < 24:
            return CoiledState(symbol, 0, 0, 0, 0, 0, 0, "long", venue, hist[-1].close if hist else 0.0, False)

        closes = [b.close for b in hist]
        volumes = [b.volume for b in hist]
        rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0]

        short = rets[-24:] if len(rets) >= 24 else rets
        long = rets[-96:] if len(rets) >= 96 else rets
        vol_s = _stdev(short)
        vol_l = _stdev(long) or 1e-9
        compression = _clamp(1.0 - vol_s / vol_l) if vol_l > 0 else 0.0

        v_s = _mean(volumes[-24:])
        v_l = _mean(volumes[-96 * 3 :]) or 1e-9
        volume_dry = _clamp(1.0 - v_s / v_l)

        last_big = 0
        peak = closes[0]
        trough = closes[0]
        last_swing_i = 0
        for i, c in enumerate(closes):
            if c > peak:
                peak = c
            if c < trough:
                trough = c
            if trough > 0 and (c / trough - 1.0) >= 0.20:
                last_swing_i = i
                peak = c
                trough = c
            elif peak > 0 and (peak / c - 1.0) >= 0.20:
                last_swing_i = i
                peak = c
                trough = c
        last_big = len(closes) - 1 - last_swing_i
        silence = _clamp(last_big / 80.0)
        window = closes[-96 * 5 :] if len(closes) >= 20 else closes
        wmin = min(window)
        rng = (max(window) - wmin) / wmin if wmin > 0 else 0.0
        silence = _clamp(min(silence, 1.0 - rng / 0.25))

        depth = hist[-1].book_depth_usd or (profile.typical_depth_usd if profile else 1.0)
        vacuum = _clamp(1.0 - depth / max((profile.typical_depth_usd if profile else depth), 1.0) * 0.5)
        # 深度相对日量越薄，真空越高
        day_vol = _mean(volumes[-96:]) if len(volumes) >= 8 else _mean(volumes)
        if day_vol > 0:
            vacuum = _clamp(0.5 * vacuum + 0.5 * (1.0 - min(1.0, depth / max(day_vol * 0.05, 1.0))))

        stretch = _sum(rets[-96:]) if len(rets) >= 16 else _sum(rets)
        exhaustion = _clamp(abs(stretch) / 0.50)

        coiled = _clamp(0.34 * compression + 0.28 * volume_dry + 0.22 * silence + 0.16 * vacuum)
        armed = coiled >= 0.42 and silence >= self.config.min_silence * 0.7

        # 预计算方向：默认为多；若已抛物且解锁压力在，预案为空
        side: Side = "long"
        if hist[-1].unlock_pressure > 0.6 and _sum(rets[-16:]) > 0.35:
            side = "short"
            venue = "futures_1x"

        box_low = min(b.low for b in hist[-24:])
        box_high = max(b.high for b in hist[-24:])
        if side == "long":
            invalidation = box_low * 0.985
        else:
            invalidation = box_high * 1.015

        return CoiledState(
            symbol=symbol,
            compression=compression,
            volume_dry=volume_dry,
            silence=silence,
            vacuum=vacuum,
            exhaustion=exhaustion,
            coiled_score=coiled,
            preferred_side=side,
            venue=venue,
            invalidation_hint=invalidation,
            armed=armed,
        )


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sum(xs: list[float]) -> float:
    return sum(xs)


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
