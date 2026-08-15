from __future__ import annotations

from dataclasses import dataclass

from .config import SniperConfig
from .types import Venue


@dataclass
class Fill:
    symbol: str
    side: str  # buy / sell
    qty: float
    price: float
    fee: float
    venue: Venue
    ts: float


class PaperVenue:
    """纸上撮合。现货与 Alpha 当现货；1x 合约允许空头，杠杆禁止 >1。"""

    def __init__(self, config: SniperConfig):
        self.config = config
        self.marks: dict[str, float] = {}
        self.fills: list[Fill] = []

    def on_price(self, symbol: str, price: float) -> None:
        self.marks[symbol] = price

    def execute(self, symbol: str, venue: Venue, is_buy: bool, notional: float, ts: float, leverage: float = 1.0) -> Fill | None:
        if leverage > self.config.max_leverage + 1e-9:
            return None
        px = self.marks.get(symbol)
        if px is None or px <= 0 or notional <= 0:
            return None
        slip = self.config.slippage_bps / 10_000.0
        fee_r = self.config.fee_bps / 10_000.0
        if venue == "alpha":
            slip *= 1.8
        price = px * (1.0 + slip) if is_buy else px * (1.0 - slip)
        qty = notional / price
        fee = notional * fee_r
        fill = Fill(symbol, "buy" if is_buy else "sell", qty, price, fee, venue, ts)
        self.fills.append(fill)
        return fill
