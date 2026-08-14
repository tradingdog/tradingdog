from __future__ import annotations

from .config import SniperConfig
from .types import Venue


class LiveBinanceGuard:
    """
    实盘边界。框架默认纸上；没有密钥、没有显式 live，任何下单都拒绝。
    杠杆 >1x 在这里也会被挡掉，避免配置漂移。

    计划中的场内入口（有密钥后再接，不入库）：
    - 现货下单 / 深度 / 成交
    - 1x 逐仓合约（只为了空头权）
    - Alpha 现货式买卖
    - 公告与 Alpha 上币列表的轮询（事件驱动，不能只等 K 线）
    """

    def __init__(self, config: SniperConfig, api_key: str = "", api_secret: str = ""):
        self.config = config
        self.api_key = api_key
        self.api_secret = api_secret

    def can_live(self) -> bool:
        return bool(self.config.live and self.api_key and self.api_secret)

    def assert_order_legal(self, venue: Venue, leverage: float) -> None:
        if leverage > 1.0 + 1e-9:
            raise PermissionError("只允许 1x")
        if venue not in ("spot", "futures_1x", "alpha"):
            raise PermissionError("只允许现货 / 1x 合约 / Alpha")
        if not self.can_live():
            raise PermissionError("实盘关闭：使用 python -m alpha_sniper paper")
