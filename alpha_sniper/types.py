from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Venue = Literal["spot", "futures_1x", "alpha"]
Side = Literal["long", "short"]
Regime = Literal["risk_on", "chop", "btc_stress"]
IgnitionKind = Literal["informed", "retail_fomo", "unknown"]
EngineState = Literal["SQUAT", "ARMED", "IN_THESIS"]
EvidenceFamily = Literal[
    "microstructure",
    "catalyst",
    "positioning",
    "narrative",
    "calendar",
]


@dataclass(frozen=True)
class Pulse:
    """单个传感器的一次脉冲。单独出现是噪音，不构成下单理由。"""

    sensor_id: str
    family: EvidenceFamily
    symbol: str
    side: Side
    strength: float
    ts: float
    evidence: dict = field(default_factory=dict)


@dataclass
class Coincidence:
    symbol: str
    side: Side
    ts: float
    families: tuple[str, ...]
    pulses: tuple[Pulse, ...]
    score: float
    silence_before: float


@dataclass
class FourScores:
    possibility: float
    ignition: float
    crowding: float
    exit_liquidity: float

    def tradable(self, min_poss: float = 0.45, min_ign: float = 0.5, max_crowd: float = 0.62, min_exit: float = 0.28) -> bool:
        return (
            self.possibility >= min_poss
            and self.ignition >= min_ign
            and self.crowding <= max_crowd
            and self.exit_liquidity >= min_exit
        )


@dataclass
class Opportunity:
    symbol: str
    side: Side
    venue: Venue
    ts: float
    coincidence: Coincidence
    scores: FourScores
    conviction: float
    reason: str
    invalidation: float
    time_stop_hours: float
    ignition_kind: IgnitionKind
    precomputed: bool


@dataclass
class Thesis:
    id: str
    symbol: str
    side: Side
    venue: Venue
    hypothesis: str
    opened_ts: float
    entry: float
    qty: float
    notional: float
    invalidation: float
    time_stop_ts: float
    peak: float
    scaled_40: bool = False
    scaled_100: bool = False
    families: tuple[str, ...] = ()
    scores: FourScores | None = None
    status: str = "open"
    exit_price: float | None = None
    exit_ts: float | None = None
    exit_reason: str = ""
    realized_pnl: float = 0.0
    remaining_qty: float = 0.0


@dataclass
class Bar:
    ts: float
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    taker_buy_ratio: float = 0.5
    large_print_share: float = 0.0
    book_depth_usd: float = 0.0
    exchange_inflow: float = 0.0
    listing_event: str = ""
    narrative: str = ""
    unlock_pressure: float = 0.0
    social_heat: float = 0.0
    is_alpha: bool = False
    is_weekend: bool = False


@dataclass
class SymbolProfile:
    symbol: str
    listing_tier: Literal["large", "mid", "small", "alpha"]
    narrative: str
    base_price: float
    circulating_float_usd: float
    typical_depth_usd: float
    is_alpha: bool = False


@dataclass
class Account:
    cash: float
    vault: float = 0.0
    starting: float = 1000.0
    high_watermark: float = 1000.0
    last_double_lock: float = 1000.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    day_stamp: int = 0
    week_stamp: int = 0
    cooldown_until: float = 0.0
    moonshot_ban_until: float = 0.0
    halted_until: float = 0.0

    def equity(self, mark_to_market: float = 0.0) -> float:
        return self.cash + self.vault + mark_to_market

    def tradable_equity(self, mark_to_market: float = 0.0) -> float:
        return max(0.0, self.cash + mark_to_market)
