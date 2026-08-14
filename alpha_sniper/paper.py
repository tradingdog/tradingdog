from __future__ import annotations

import random
from dataclasses import dataclass

from .config import SniperConfig
from .types import Bar, SymbolProfile


@dataclass
class _Path:
    price: float
    volume: float


class PaperUniverse:
    """
    可复现的纸上宇宙。不是为了画出漂亮曲线，而是种下几类「别人会怎么死」的事件，
    检验框架会不会：预先埋伏、忽略假突破、空衰竭、买滞后、BTC 大跌时拒绝新多。
    """

    def __init__(self, config: SniperConfig):
        self.config = config
        self.rng = random.Random(config.seed)
        self.profiles = _profiles()
        self._path = {p.symbol: _Path(p.base_price, 8_000) for p in self.profiles}
        self.symbols = [p.symbol for p in self.profiles]

    def bar(self, symbol: str, ts: float) -> Bar:
        day = ts / 86400.0
        is_weekend = int(day) % 7 >= 5
        st = self._path[symbol]
        profile = next(p for p in self.profiles if p.symbol == symbol)
        noise = 1.0 + self.rng.uniform(-0.0018, 0.0018)

        listing = ""
        taker = 0.50
        large = 0.05
        inflow = 0.0
        unlock = 0.0
        social = 0.08
        depth = profile.typical_depth_usd
        vol_mult = 1.0
        drift = 0.0
        narrative = profile.narrative

        if symbol == "BTCUSDT":
            if 24.0 <= day < 26.0:
                drift = -0.0042  # 约 24h 内深跌，触发体制过滤
            else:
                drift = self.rng.uniform(-0.0004, 0.0004)
            vol_mult = 1.2
            social = 0.4
        elif symbol == "COILUSDT":
            if day < 1.2:
                vol_mult = 3.2
                depth = profile.typical_depth_usd
            elif day < 5.0:
                vol_mult = 0.35
                depth = profile.typical_depth_usd * 0.18
                drift = self.rng.uniform(-0.00015, 0.00015)
            elif 5.0 <= day < 5.04:
                listing = "alpha_list"
                vol_mult = 14.0
                large = 0.55
                taker = 0.78
                depth = profile.typical_depth_usd * 0.12
                drift = 0.035
                social = 0.22
            elif 5.04 <= day < 6.2:
                vol_mult = 8.0
                large = 0.42
                taker = 0.7
                drift = 0.012
                social = 0.45
            else:
                vol_mult = 1.4
                drift = self.rng.uniform(-0.001, 0.001)
                social = 0.3
        elif symbol == "FAKEUSDT":
            # 一直吵、天天晃，单独放量。没有沉寂，也没有第二、第三族。
            drift = self.rng.uniform(-0.006, 0.006)
            social = 0.7
            vol_mult = 2.0
            if 8.0 <= day < 8.15:
                vol_mult = 9.0
                drift = 0.008
                social = 0.85
                large = 0.08
                taker = 0.56
        elif symbol == "DUMPUSDT":
            if day < 10.0:
                vol_mult = 1.6
                drift = 0.0008
                social = 0.3
            elif 10.0 <= day < 12.0:
                vol_mult = 4.0
                drift = 0.0045  # 抛物线
                social = 0.75
                large = 0.2
                taker = 0.66
            elif 12.0 <= day < 12.2:
                unlock = 0.85
                inflow = 0.82
                large = 0.58
                taker = 0.28
                vol_mult = 11.0
                drift = -0.018
                social = 0.8
                depth = profile.typical_depth_usd * 0.3
            else:
                vol_mult = 3.0
                drift = -0.003 if day < 13.5 else self.rng.uniform(-0.002, 0.001)
                unlock = 0.4
                social = 0.5
        elif symbol == "LEADUSDT":
            if 17.8 <= day < 18.6:
                vol_mult = 7.0
                large = 0.4
                taker = 0.7
                drift = 0.01
                social = 0.7
            else:
                drift = self.rng.uniform(-0.0008, 0.0008)
                social = 0.25 if day < 17.8 else 0.4
        elif symbol == "LAGUSDT":
            if day < 18.4:
                vol_mult = 0.4 if day > 1 else 2.5
                depth = profile.typical_depth_usd * 0.2
                drift = self.rng.uniform(-0.0002, 0.0002)
                social = 0.1
            elif 18.4 <= day < 18.55:
                vol_mult = 12.0
                large = 0.5
                taker = 0.74
                depth = profile.typical_depth_usd * 0.15
                drift = 0.02
                social = 0.2
            elif day < 19.5:
                vol_mult = 6.0
                drift = 0.008
                large = 0.36
                taker = 0.65
                social = 0.35
            else:
                drift = self.rng.uniform(-0.001, 0.001)
        elif symbol == "WEEKUSDT":
            if is_weekend and 30 <= day < 32:
                vol_mult = 6.5
                large = 0.4
                taker = 0.72
                depth = profile.typical_depth_usd * 0.08
                drift = 0.014
                social = 0.15
            else:
                vol_mult = 0.5 if day > 1 else 2.0
                depth = profile.typical_depth_usd * 0.22
                drift = self.rng.uniform(-0.0003, 0.0003)
        elif symbol == "STRESSUSDT":
            if 24.2 <= day < 25.5:
                listing = "spot_list"
                vol_mult = 10.0
                large = 0.5
                taker = 0.7
                drift = 0.006
                social = 0.2
                depth = profile.typical_depth_usd * 0.2
            else:
                vol_mult = 0.5 if day > 1 else 2.2
                drift = self.rng.uniform(-0.0002, 0.0002)
                depth = profile.typical_depth_usd * 0.25
        elif symbol == "THINUSDT":
            depth = 15.0  # 几乎没有退出通道
            vol_mult = 0.2
            if 20 <= day < 20.1:
                listing = "alpha_list"
                vol_mult = 20.0
                large = 0.6
                taker = 0.8
                drift = 0.05
            else:
                drift = self.rng.uniform(-0.0004, 0.0004)
        elif symbol == "DEADUSDT":
            vol_mult = 0.4
            drift = self.rng.uniform(-0.0002, 0.0002)
            depth = profile.typical_depth_usd * 0.3
        else:
            drift = self.rng.uniform(-0.0005, 0.0005)

        open_px = st.price
        close_px = max(0.0001, open_px * (1.0 + drift) * noise)
        high = max(open_px, close_px) * (1.0 + abs(drift) * 0.3 + 0.0005)
        low = min(open_px, close_px) * (1.0 - abs(drift) * 0.3 - 0.0005)
        volume = st.volume * vol_mult * (1.0 + self.rng.uniform(-0.05, 0.05))
        st.price = close_px

        return Bar(
            ts=ts,
            symbol=symbol,
            open=open_px,
            high=high,
            low=max(low, 0.0001),
            close=close_px,
            volume=max(volume, 1.0),
            taker_buy_ratio=taker,
            large_print_share=large,
            book_depth_usd=depth,
            exchange_inflow=inflow,
            listing_event=listing,
            narrative=narrative,
            unlock_pressure=unlock,
            social_heat=social,
            is_alpha=profile.is_alpha,
            is_weekend=is_weekend,
        )


def _profiles() -> list[SymbolProfile]:
    return [
        SymbolProfile("BTCUSDT", "large", "beta", 60000, 1_200_000_000_000, 80_000_000, False),
        SymbolProfile("ETHUSDT", "large", "beta", 3000, 400_000_000_000, 40_000_000, False),
        SymbolProfile("BNBUSDT", "large", "beta", 500, 80_000_000_000, 15_000_000, False),
        SymbolProfile("COILUSDT", "alpha", "ai-agent", 0.08, 4_500_000, 18_000, True),
        SymbolProfile("FAKEUSDT", "small", "meme", 0.40, 12_000_000, 40_000, False),
        SymbolProfile("DUMPUSDT", "small", "gamefi", 0.22, 18_000_000, 50_000, False),
        SymbolProfile("LEADUSDT", "small", "ai-agent", 0.15, 22_000_000, 60_000, False),
        SymbolProfile("LAGUSDT", "alpha", "ai-agent", 0.03, 3_200_000, 12_000, True),
        SymbolProfile("WEEKUSDT", "small", "weekend", 0.11, 8_000_000, 20_000, False),
        SymbolProfile("STRESSUSDT", "small", "misc", 0.09, 7_000_000, 22_000, False),
        SymbolProfile("THINUSDT", "alpha", "vapor", 0.002, 800_000, 20, True),
        SymbolProfile("DEADUSDT", "small", "dead", 0.50, 9_000_000, 25_000, False),
    ]


def expected_event_map() -> dict[str, str]:
    return {
        "COILUSDT": "long_snipe",
        "FAKEUSDT": "skip_fakeout",
        "DUMPUSDT": "short_dump",
        "LAGUSDT": "long_laggard",
        "STRESSUSDT": "skip_btc_stress",
        "THINUSDT": "skip_no_exit",
        "DEADUSDT": "skip_nothing",
    }
