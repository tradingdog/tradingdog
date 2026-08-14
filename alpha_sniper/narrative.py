from __future__ import annotations

from collections import defaultdict, deque

from .types import Bar, Side


class NarrativeLagEngine:
    """龙头先动时不追龙头，去找同叙事里仍在缩簧的滞后币。"""

    def __init__(self, lookback: int = 64):
        self.lookback = lookback
        self._ret: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=lookback))
        self._narr: dict[str, str] = {}
        self._last_close: dict[str, float] = {}

    def on_bar(self, bar: Bar) -> None:
        prev = self._last_close.get(bar.symbol)
        if prev and prev > 0:
            self._ret[bar.symbol].append(bar.close / prev - 1.0)
        self._last_close[bar.symbol] = bar.close
        if bar.narrative:
            self._narr[bar.symbol] = bar.narrative

    def laggard_pulse_strength(self, symbol: str, coiled_score: float, already_moved: float) -> tuple[float, str]:
        narr = self._narr.get(symbol)
        if not narr:
            return 0.0, ""
        leaders = []
        for other, n in self._narr.items():
            if n != narr or other == symbol:
                continue
            rets = list(self._ret[other])
            if len(rets) < 4:
                continue
            acc = 1.0
            for r in rets[-48:]:
                acc *= 1.0 + r
            moved = acc - 1.0
            leaders.append((other, moved))
        if not leaders:
            return 0.0, ""
        best = max(leaders, key=lambda x: x[1])
        if best[1] < 0.15:
            return 0.0, ""
        # 自己还没动、仍相对压缩，才叫滞后机会
        if already_moved > 0.08 or coiled_score < 0.20:
            return 0.0, ""
        strength = min(1.0, 0.45 + 0.8 * best[1] + 0.2 * coiled_score)
        return strength, f"narrative_lag:{narr}:{best[0]}:+{best[1]:.0%}"

    def dump_cluster(self, symbol: str) -> float:
        """同板块一起崩时，空头叙事族加分（仍需其它族共振）。"""
        narr = self._narr.get(symbol)
        if not narr:
            return 0.0
        downs = 0
        n = 0
        for other, tag in self._narr.items():
            if tag != narr:
                continue
            rets = list(self._ret[other])
            if len(rets) < 4:
                continue
            n += 1
            if sum(rets[-8:]) < -0.12:
                downs += 1
        if n < 2:
            return 0.0
        return downs / n


def preferred_side_from_narrative(lag_strength: float, dump_frac: float) -> Side | None:
    if dump_frac >= 0.6 and lag_strength < 0.2:
        return "short"
    if lag_strength >= 0.5:
        return "long"
    return None
