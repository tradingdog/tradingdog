from __future__ import annotations

from .types import Bar, IgnitionKind


def classify_ignition(bar: Bar, volume_z: float) -> IgnitionKind:
    """同样是放量：大单吃簿更像知情；碎单涌入更像 FOMO。"""
    if volume_z < 1.2:
        return "unknown"
    large = bar.large_print_share
    taker = bar.taker_buy_ratio
    if large >= 0.38 and (taker >= 0.62 or taker <= 0.38):
        return "informed"
    if large <= 0.16 and bar.social_heat >= 0.55:
        return "retail_fomo"
    if large >= 0.28:
        return "informed"
    return "unknown"


def ignition_score(kind: IgnitionKind, coincidence_score: float, volume_z: float) -> float:
    kind_w = {"informed": 1.0, "unknown": 0.72, "retail_fomo": 0.35}[kind]
    z = max(0.0, min(1.0, volume_z / 4.0))
    return max(0.0, min(1.0, 0.55 * coincidence_score + 0.25 * z + 0.20 * kind_w))
