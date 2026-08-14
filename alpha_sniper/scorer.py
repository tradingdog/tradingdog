from __future__ import annotations

from .config import SniperConfig
from .types import Coincidence, FourScores, IgnitionKind, Opportunity, Venue


class ConvictionScorer:
    def __init__(self, config: SniperConfig):
        self.config = config
        self.family_combo_boost: dict[tuple[str, ...], float] = {
            ("catalyst", "microstructure", "positioning"): 0.12,
            ("calendar", "microstructure", "positioning"): 0.10,
            ("catalyst", "microstructure", "narrative"): 0.11,
            ("calendar", "catalyst", "microstructure", "positioning"): 0.16,
        }

    def learn(self, families: tuple[str, ...], fat_tail: bool, fakeout: bool) -> None:
        key = tuple(sorted(families))
        cur = self.family_combo_boost.get(key, 0.0)
        if fat_tail:
            self.family_combo_boost[key] = min(0.25, cur + 0.03)
        elif fakeout:
            self.family_combo_boost[key] = max(-0.12, cur - 0.04)

    def score(
        self,
        coincidence: Coincidence,
        scores: FourScores,
        kind: IgnitionKind,
        venue: Venue,
        reason: str,
        invalidation: float,
        time_stop_hours: float,
        precomputed: bool,
    ) -> Opportunity | None:
        if not scores.tradable(
            self.config.min_possibility,
            self.config.min_ignition,
            self.config.max_crowding,
            self.config.min_exit_liquidity,
        ):
            return None
        if kind == "retail_fomo" and scores.crowding > 0.45:
            return None

        boost = self.family_combo_boost.get(tuple(sorted(coincidence.families)), 0.0)
        kind_adj = {"informed": 0.08, "unknown": 0.0, "retail_fomo": -0.18}[kind]
        pre_adj = 0.06 if precomputed else -0.08
        conviction = _clamp(
            0.42 * coincidence.score
            + 0.22 * scores.possibility
            + 0.18 * scores.ignition
            + 0.10 * (1.0 - scores.crowding)
            + 0.08 * scores.exit_liquidity
            + boost
            + kind_adj
            + pre_adj
        )
        if conviction < self.config.min_conviction:
            return None
        return Opportunity(
            symbol=coincidence.symbol,
            side=coincidence.side,
            venue=venue,
            ts=coincidence.ts,
            coincidence=coincidence,
            scores=scores,
            conviction=conviction,
            reason=reason,
            invalidation=invalidation,
            time_stop_hours=time_stop_hours,
            ignition_kind=kind,
            precomputed=precomputed,
        )


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
