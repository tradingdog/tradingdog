from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SniperConfig:
    starting_usdt: float = 1000.0
    target_usdt: float = 100_000.0
    horizon_days: int = 180

    max_concurrent: int = 2
    base_risk_frac: float = 0.10
    moonshot_frac: float = 0.25
    max_loss_frac: float = 0.05
    daily_kill_frac: float = 0.12
    weekly_kill_frac: float = 0.25
    max_leverage: float = 1.0

    min_independent_families: int = 3
    coincidence_window_sec: float = 24 * 3600
    moonshot_families: int = 4
    fuse_families: tuple[str, ...] = ("catalyst", "narrative", "calendar")

    min_possibility: float = 0.45
    min_ignition: float = 0.50
    max_crowding: float = 0.55
    min_exit_liquidity: float = 0.28
    min_silence: float = 0.40
    min_conviction: float = 0.52
    time_stop_min_move: float = 0.20
    max_chase_above_box: float = 0.12

    coiled_breakout_hours: float = 72.0
    catalyst_hours: float = 168.0
    dump_hours: float = 48.0
    trail_drawdown: float = 0.25
    scale_40: float = 0.40
    scale_100: float = 1.00
    scale_frac: float = 0.25

    vault_lock_of_gain: float = 0.15
    post_win_moonshot_ban_hours: float = 48.0
    post_loss_cooldown_hours: float = 24.0
    btc_stress_24h: float = -0.06

    fee_bps: float = 8.0
    slippage_bps: float = 12.0
    live: bool = False
    bar_seconds: float = 3600.0
    live_interval: str = "1h"
    paper_bar_seconds: float = 15 * 60
    paper_days: int = 60
    seed: int = 42

    excluded_large_caps: tuple[str, ...] = field(
        default_factory=lambda: (
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
            "ADAUSDT", "LTCUSDT", "BCHUSDT", "LINKUSDT", "AVAXUSDT", "ZECUSDT",
            "SUIUSDT", "DOTUSDT", "TRXUSDT", "TONUSDT", "SHIBUSDT",
        )
    )
