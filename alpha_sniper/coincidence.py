from __future__ import annotations

from collections import defaultdict, deque

from .config import SniperConfig
from .types import Coincidence, Pulse


class CoincidenceEngine:
    """跨独立证据族共振。同族多条脉冲只算一票，防止「三个成交量指标」假突破。"""

    def __init__(self, config: SniperConfig):
        self.config = config
        self._buf: dict[str, deque[Pulse]] = defaultdict(lambda: deque(maxlen=256))

    def ingest(self, pulse: Pulse, silence_before: float, exhaustion: float = 0.0) -> Coincidence | None:
        buf = self._buf[pulse.symbol]
        buf.append(pulse)
        window = self.config.coincidence_window_sec
        cutoff = pulse.ts - window
        recent = [p for p in buf if p.ts >= cutoff and p.side == pulse.side]
        if not recent:
            return None

        best: dict[str, Pulse] = {}
        for p in recent:
            prev = best.get(p.family)
            if prev is None or p.strength > prev.strength:
                best[p.family] = p
        if len(best) < self.config.min_independent_families:
            return None
        # 多头要沉寂压缩；空头可用「抛物线衰竭」代替沉寂。热闹且不衰竭 = 拥挤，不配叫发现。
        if pulse.side == "short" and exhaustion >= 0.55:
            premise = exhaustion
        elif silence_before >= self.config.min_silence:
            premise = silence_before
        else:
            return None

        families = tuple(sorted(best))
        pulses = tuple(best[f] for f in families)
        # 族越多、强度越齐，共振分越高
        strengths = [p.strength for p in pulses]
        avg = sum(strengths) / len(strengths)
        bonus = 0.08 * max(0, len(best) - 3)
        score = min(1.0, avg * (0.72 + 0.28 * min(1.0, premise)) + bonus)
        return Coincidence(
            symbol=pulse.symbol,
            side=pulse.side,
            ts=pulse.ts,
            families=families,
            pulses=pulses,
            score=score,
            silence_before=silence_before,
        )

    def forget(self, symbol: str) -> None:
        self._buf.pop(symbol, None)

    def votes(self, symbol: str, now: float) -> list[dict]:
        cutoff = now - self.config.coincidence_window_sec
        best: dict[tuple[str, str], Pulse] = {}
        for p in self._buf.get(symbol, []):
            if p.ts < cutoff:
                continue
            key = (p.family, p.side)
            prev = best.get(key)
            if prev is None or p.strength > prev.strength:
                best[key] = p
        return [
            {
                "family": p.family,
                "side": p.side,
                "strength": round(p.strength, 3),
                "sensor": p.sensor_id,
                "ts": p.ts,
            }
            for p in best.values()
        ]
