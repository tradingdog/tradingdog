from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .types import Thesis


@dataclass
class MemoryRecord:
    thesis_id: str
    symbol: str
    side: str
    families: list[str]
    ret: float
    reason: str
    fat_tail: bool
    fakeout: bool


class PostmortemMemory:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.records: list[MemoryRecord] = []

    def remember(self, thesis: Thesis) -> MemoryRecord:
        if thesis.entry <= 0 or thesis.exit_price is None:
            ret = 0.0
        else:
            raw = thesis.exit_price / thesis.entry - 1.0
            ret = raw if thesis.side == "long" else -raw
        # 用已实现盈亏相对名义更稳
        if thesis.notional > 0:
            ret = thesis.realized_pnl / thesis.notional
        fat = ret >= 0.5
        fake = ret <= 0.0 and thesis.exit_reason in {"invalidation", "time_stop"}
        rec = MemoryRecord(
            thesis_id=thesis.id,
            symbol=thesis.symbol,
            side=thesis.side,
            families=list(thesis.families),
            ret=ret,
            reason=thesis.exit_reason,
            fat_tail=fat,
            fakeout=fake,
        )
        self.records.append(rec)
        self._flush()
        return rec

    def _flush(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(r) for r in self.records]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
