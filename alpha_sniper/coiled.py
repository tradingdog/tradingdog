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
    box_high: float = 0.0
    box_low: float = 0.0
    ignited: bool = False
    pullback_ready: bool = False
    extended: bool = False
    range_expand: float = 1.0


class CoiledRegistry:
    """缩箱体：用点火前的K线算失效价。当前K线只判断有没有突破/回踩。"""

    def __init__(self, config: SniperConfig):
        self.config = config
        self.profiles: dict[str, SymbolProfile] = {}
        self._bars: dict[str, deque[Bar]] = defaultdict(lambda: deque(maxlen=96 * 30))
        self.states: dict[str, CoiledState] = {}
        self._ignite_i: dict[str, int] = {}
        self._ignite_side: dict[str, Side] = {}
        self._ignite_box: dict[str, tuple[float, float]] = {}
        self._seen: dict[str, int] = {}

    def set_profiles(self, profiles: list[SymbolProfile]) -> None:
        self.profiles = {p.symbol: p for p in profiles}

    def on_bar(self, bar: Bar) -> CoiledState:
        hist = self._bars[bar.symbol]
        hist.append(bar)
        self._seen[bar.symbol] = self._seen.get(bar.symbol, 0) + 1
        state = self._compute(bar.symbol)
        self.states[bar.symbol] = state
        return state

    def _compute(self, symbol: str) -> CoiledState:
        hist = list(self._bars[symbol])
        profile = self.profiles.get(symbol)
        venue: Venue = "alpha" if (profile and profile.is_alpha) else "spot"
        last = hist[-1]
        if len(hist) < 25:
            return CoiledState(symbol, 0, 0, 0, 0, 0, 0, "long", venue, last.close, False)

        prev = hist[:-1]
        closes = [b.close for b in prev]
        volumes = [b.volume for b in prev]
        rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0]
        n_day = max(8, int(round(86400 / max(self.config.bar_seconds, 60.0))))

        short = rets[-n_day:] if len(rets) >= n_day else rets
        long = rets[-n_day * 4 :] if len(rets) >= n_day else rets
        vol_s = _stdev(short)
        vol_l = _stdev(long) or 1e-9
        compression = _clamp(1.0 - vol_s / vol_l) if vol_l > 0 else 0.0

        v_s = _mean(volumes[-n_day:])
        v_l = _mean(volumes[-n_day * 7 :]) or 1e-9
        rel_dry = _clamp(1.0 - v_s / v_l)
        peak_vol = max(volumes) if volumes else 1e-9
        abs_dry = _clamp(1.0 - v_s / peak_vol)
        volume_dry = _clamp(0.55 * rel_dry + 0.45 * abs_dry)

        last_swing_i = 0
        peak = closes[0]
        trough = closes[0]
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
        quiet_need = max(24, n_day * 3)
        silence = _clamp(last_big / float(quiet_need))
        window = closes[-n_day * 5 :] if len(closes) >= 20 else closes
        wmin = min(window)
        rng = (max(window) - wmin) / wmin if wmin > 0 else 0.0
        silence = _clamp(min(silence, 1.0 - rng / 0.25))

        depth = last.book_depth_usd or (profile.typical_depth_usd if profile else 1.0)
        vacuum = _clamp(1.0 - depth / max((profile.typical_depth_usd if profile else depth), 1.0) * 0.5)
        day_vol = _mean(volumes[-n_day:]) if len(volumes) >= 8 else _mean(volumes)
        if day_vol > 0:
            vacuum = _clamp(0.5 * vacuum + 0.5 * (1.0 - min(1.0, depth / max(day_vol * 0.05, 1.0))))

        stretch_1d = abs(_sum(rets[-n_day:])) if rets else 0.0
        stretch_4d = abs(_sum(rets[-n_day * 4 :])) if len(rets) >= n_day else stretch_1d
        exhaustion = _clamp(max(stretch_1d, stretch_4d) / 0.50)

        coiled = _clamp(0.20 * compression + 0.22 * volume_dry + 0.40 * silence + 0.18 * vacuum)
        armed = coiled >= 0.42 and silence >= self.config.min_silence * 0.7

        box_n = min(len(prev), n_day)
        box_slice = prev[-box_n:]
        box_low = min(b.low for b in box_slice)
        box_high = max(b.high for b in box_slice)
        this_range = max(last.high - last.low, 1e-12)
        med_range = _median([max(b.high - b.low, 0.0) for b in box_slice]) or 1e-12
        range_expand = this_range / med_range
        body_pos = (last.close - last.low) / this_range

        ignite_long = last.close > box_high and range_expand >= 1.6 and body_pos >= 0.55
        ignite_short = last.close < box_low and range_expand >= 1.6 and body_pos <= 0.45
        seen = self._seen.get(symbol, len(hist))
        if ignite_long:
            self._ignite_i[symbol] = seen
            self._ignite_side[symbol] = "long"
            self._ignite_box[symbol] = (box_low, box_high)
        elif ignite_short:
            self._ignite_i[symbol] = seen
            self._ignite_side[symbol] = "short"
            self._ignite_box[symbol] = (box_low, box_high)

        ignite_i = self._ignite_i.get(symbol)
        ignite_side = self._ignite_side.get(symbol, "long")
        stored_box = self._ignite_box.get(symbol, (box_low, box_high))
        hold = max(3, int(round(8 * 3600 / max(self.config.bar_seconds, 60.0))))
        recent = ignite_i is not None and (seen - ignite_i) <= hold
        ignited = bool(recent or ignite_long or ignite_short)

        sbox_low, sbox_high = stored_box
        pullback_ready = False
        if recent and ignite_side == "long":
            pullback_ready = last.low <= sbox_high * 1.02 and last.close >= sbox_high * 0.992 and last.close > sbox_low
        elif recent and ignite_side == "short":
            pullback_ready = last.high >= sbox_low * 0.98 and last.close <= sbox_low * 1.008 and last.close < sbox_high

        chase = self.config.max_chase_above_box
        extended = last.close >= sbox_high * (1.0 + chase) if ignite_side == "long" else last.close <= sbox_low * (1.0 - chase)

        side: Side = "long"
        if last.unlock_pressure > 0.6 and _sum(rets[-16:]) > 0.35:
            side = "short"
            venue = "futures_1x"
        elif ignite_short or (recent and ignite_side == "short"):
            side = "short"
            venue = "futures_1x"

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
            box_high=box_high,
            box_low=box_low,
            ignited=ignited,
            pullback_ready=pullback_ready,
            extended=extended,
            range_expand=range_expand,
        )


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _sum(xs: list[float]) -> float:
    return sum(xs)


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    return ys[len(ys) // 2]


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
