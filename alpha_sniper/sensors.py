from __future__ import annotations

import time
from collections import defaultdict, deque

from .coiled import CoiledState
from .types import Bar, Pulse, Side


class SensorHub:
    """所有传感器只吐脉冲。谁都不许直接下单。"""

    def __init__(self):
        self._vol: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=96 * 5))

    def on_bar(self, bar: Bar, coiled: CoiledState) -> list[Pulse]:
        self._vol[bar.symbol].append(bar.volume)
        z = self._volume_z(bar.symbol)
        pulses: list[Pulse] = []
        pulses += self._vacuum(bar, coiled, z)
        pulses += self._tape(bar, coiled, z)
        pulses += self._silence_break(bar, coiled, z)
        pulses += self._listing(bar, coiled)
        pulses += self._flow(bar, coiled, z)
        pulses += self._inflow_dump(bar, coiled)
        pulses += self._unlock(bar, coiled)
        pulses += self._weekend(bar, coiled, z)
        pulses += self._liquidity_hours(bar, coiled, z)
        pulses += self._alpha_pipeline(bar, coiled)
        return [p for p in pulses if p.strength >= 0.35]

    def volume_z(self, symbol: str) -> float:
        return self._volume_z(symbol)

    def _volume_z(self, symbol: str) -> float:
        xs = list(self._vol[symbol])
        if len(xs) < 12:
            return 0.0
        mean = sum(xs[:-1]) / max(1, len(xs) - 1)
        var = sum((x - mean) ** 2 for x in xs[:-1]) / max(1, len(xs) - 2)
        sd = var ** 0.5
        if sd <= 1e-9:
            return 0.0
        return (xs[-1] - mean) / sd

    def _vacuum(self, bar: Bar, coiled: CoiledState, z: float) -> list[Pulse]:
        if coiled.vacuum < 0.40 or z < 1.4:
            return []
        side: Side = "long" if bar.taker_buy_ratio >= 0.55 else "short"
        strength = min(1.0, 0.4 + 0.25 * coiled.vacuum + 0.12 * z)
        return [Pulse("volume_vacuum", "microstructure", bar.symbol, side, strength, bar.ts, {"z": z, "vacuum": coiled.vacuum})]

    def _tape(self, bar: Bar, coiled: CoiledState, z: float) -> list[Pulse]:
        """大单一边倒的磁带，不要求真空。抛物线出货靠这个补上微观结构族。"""
        if z < 2.0 or bar.large_print_share < 0.28:
            return []
        if bar.taker_buy_ratio <= 0.36:
            side: Side = "short"
        elif bar.taker_buy_ratio >= 0.64:
            side = "long"
        else:
            return []
        strength = min(1.0, 0.35 + 0.15 * z + 0.5 * bar.large_print_share)
        return [Pulse("aggressive_tape", "microstructure", bar.symbol, side, strength, bar.ts, {"z": z})]

    def _silence_break(self, bar: Bar, coiled: CoiledState, z: float) -> list[Pulse]:
        if coiled.silence < 0.4 or z < 1.6:
            return []
        side: Side = "long" if bar.close >= bar.open else "short"
        strength = min(1.0, 0.35 + 0.4 * coiled.silence + 0.1 * z)
        return [Pulse("silence_break", "microstructure", bar.symbol, side, strength, bar.ts, {"silence": coiled.silence})]

    def _listing(self, bar: Bar, coiled: CoiledState) -> list[Pulse]:
        if not bar.listing_event:
            return []
        strength = 0.9 if "alpha" in bar.listing_event else 0.72
        return [Pulse("listing_catalyst", "catalyst", bar.symbol, "long", strength, bar.ts, {"event": bar.listing_event})]

    def _flow(self, bar: Bar, coiled: CoiledState, z: float) -> list[Pulse]:
        if bar.large_print_share < 0.32 or z < 0.8:
            return []
        side: Side = "long" if bar.taker_buy_ratio >= 0.58 else "short"
        if bar.taker_buy_ratio <= 0.42:
            side = "short"
        strength = min(1.0, 0.3 + 0.9 * bar.large_print_share)
        return [Pulse("informed_flow", "positioning", bar.symbol, side, strength, bar.ts, {"large": bar.large_print_share})]

    def _inflow_dump(self, bar: Bar, coiled: CoiledState) -> list[Pulse]:
        if bar.exchange_inflow < 0.55:
            return []
        strength = min(1.0, 0.4 + 0.6 * bar.exchange_inflow)
        return [Pulse("exchange_inflow", "positioning", bar.symbol, "short", strength, bar.ts, {"inflow": bar.exchange_inflow})]

    def _unlock(self, bar: Bar, coiled: CoiledState) -> list[Pulse]:
        if bar.unlock_pressure < 0.5:
            return []
        return [Pulse("unlock_calendar", "calendar", bar.symbol, "short", min(1.0, bar.unlock_pressure), bar.ts, {})]

    def _weekend(self, bar: Bar, coiled: CoiledState, z: float) -> list[Pulse]:
        if not bar.is_weekend or coiled.vacuum < 0.4 or z < 1.1:
            return []
        side: Side = "long" if bar.taker_buy_ratio >= 0.52 else "short"
        return [Pulse("weekend_vacuum", "calendar", bar.symbol, side, 0.55 + 0.3 * coiled.vacuum, bar.ts, {})]

    def _liquidity_hours(self, bar: Bar, coiled: CoiledState, z: float) -> list[Pulse]:
        """UTC 薄流动性时段：只给已经缩簧的币凑日历票，避免给已经在跑的龙头凑齐三类。"""
        hour = time.gmtime(bar.ts).tm_hour
        thin = bar.is_weekend or hour in {22, 23, 0, 1, 2, 3, 4}
        if not thin or not coiled.armed or coiled.silence < 0.45 or coiled.exhaustion >= 0.35 or z < 1.2:
            return []
        side: Side = "long" if bar.taker_buy_ratio >= 0.52 else "short"
        return [
            Pulse(
                "liquidity_hours",
                "calendar",
                bar.symbol,
                side,
                0.50 + 0.25 * coiled.silence,
                bar.ts,
                {"hour": hour},
            )
        ]

    def _alpha_pipeline(self, bar: Bar, coiled: CoiledState) -> list[Pulse]:
        if not bar.is_alpha:
            return []
        if bar.listing_event == "alpha_list":
            return [Pulse("alpha_new_listing", "catalyst", bar.symbol, "long", 0.95, bar.ts, {})]
        return []
