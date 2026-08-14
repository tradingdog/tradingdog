"""Alpha Sniper：币安非对称机会猎手（现货 / 1x / Alpha）。"""

__version__ = "0.1.0"

from .config import SniperConfig
from .engine import AlphaSniperEngine
from .types import Opportunity, Pulse, Side, Thesis, Venue

__all__ = [
    "AlphaSniperEngine",
    "Opportunity",
    "Pulse",
    "Side",
    "SniperConfig",
    "Thesis",
    "Venue",
    "__version__",
]
