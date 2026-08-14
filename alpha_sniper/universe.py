from __future__ import annotations

from collections import defaultdict, deque

from .config import SniperConfig
from .types import Bar, FourScores, SymbolProfile


class PossibilitySurface:
    """负空间猎场：先问「有没有资格走出大涨大跌」，再谈时机。"""

    def __init__(self, config: SniperConfig):
        self.config = config
        self.profiles: dict[str, SymbolProfile] = {}
        self._closes: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=96 * 7))
        self._volumes: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=96 * 7))
        self._social: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=96 * 3))
        self.btc_ret_24h: float = 0.0

    def set_profiles(self, profiles: list[SymbolProfile]) -> None:
        self.profiles = {p.symbol: p for p in profiles}

    def on_bar(self, bar: Bar) -> None:
        self._closes[bar.symbol].append(bar.close)
        self._volumes[bar.symbol].append(bar.volume)
        self._social[bar.symbol].append(bar.social_heat)
        if bar.symbol == "BTCUSDT":
            closes = self._closes[bar.symbol]
            if len(closes) >= 96:
                prev = closes[-96]
                if prev > 0:
                    self.btc_ret_24h = bar.close / prev - 1.0

    def regime(self) -> str:
        if self.btc_ret_24h <= self.config.btc_stress_24h:
            return "btc_stress"
        if abs(self.btc_ret_24h) < 0.015:
            return "chop"
        return "risk_on"

    def in_hunting_ground(self, symbol: str) -> bool:
        if symbol in self.config.excluded_large_caps:
            return False
        profile = self.profiles.get(symbol)
        if profile is None:
            return False
        if profile.listing_tier == "large":
            return False
        return True

    def possibility(self, symbol: str) -> float:
        profile = self.profiles.get(symbol)
        if profile is None or not self.in_hunting_ground(symbol):
            return 0.0
        # 体量越小、越薄，越有资格走出倍数；但过薄会在 exit 分数里被否决。
        float_usd = max(profile.circulating_float_usd, 1.0)
        if float_usd >= 5_000_000_000:
            size_score = 0.05
        elif float_usd >= 500_000_000:
            size_score = 0.22
        elif float_usd >= 50_000_000:
            size_score = 0.55
        elif float_usd >= 5_000_000:
            size_score = 0.82
        else:
            size_score = 0.95
        if profile.listing_tier == "alpha":
            size_score = min(1.0, size_score + 0.08)
        return _clamp(size_score)

    def crowding(self, symbol: str, already_moved: float) -> float:
        heats = self._social[symbol]
        heat = sum(heats) / len(heats) if heats else 0.0
        move = min(1.0, abs(already_moved) / 0.35)
        return _clamp(0.55 * heat + 0.45 * move)

    def exit_liquidity(self, symbol: str, bar: Bar | None = None) -> float:
        profile = self.profiles.get(symbol)
        if profile is None:
            return 0.0
        depth = bar.book_depth_usd if bar is not None else profile.typical_depth_usd
        need = max(0.10 * self.config.starting_usdt, 40.0)
        # 深度必须能吞下数次减仓；成交量不能冒充退出通道（放量时薄盘仍会卡死）。
        return _clamp(depth / (need * 5.0))

    def already_moved(self, symbol: str, lookback: int = 24) -> float:
        closes = self._closes[symbol]
        if len(closes) < 2:
            return 0.0
        window = list(closes)[-lookback:]
        if window[0] <= 0:
            return 0.0
        return window[-1] / window[0] - 1.0

    def scores_partial(self, symbol: str, bar: Bar | None = None) -> FourScores:
        moved = self.already_moved(symbol)
        return FourScores(
            possibility=self.possibility(symbol),
            ignition=0.0,
            crowding=self.crowding(symbol, moved),
            exit_liquidity=self.exit_liquidity(symbol, bar),
        )


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
