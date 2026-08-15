from __future__ import annotations

import itertools
from .config import SniperConfig
from .types import Opportunity, Thesis


_ids = itertools.count(1)


def set_id_counter(n: int) -> None:
    global _ids
    _ids = itertools.count(max(1, int(n)))


class ThesisBook:
    def __init__(self, config: SniperConfig):
        self.config = config
        self.open: dict[str, Thesis] = {}
        self.closed: list[Thesis] = []

    def has_symbol(self, symbol: str) -> bool:
        return any(t.symbol == symbol and t.status == "open" for t in self.open.values())

    def open_count(self) -> int:
        n = 0
        for t in self.open.values():
            if t.status != "open":
                continue
            # 已按计划减过仓的剩余仓不占新开仓名额
            if t.scaled_40 and t.remaining_qty <= t.qty * 0.55 + 1e-12:
                continue
            n += 1
        return n

    def open_from(self, opp: Opportunity, price: float, qty: float, notional: float, now: float) -> Thesis:
        hours = opp.time_stop_hours
        thesis = Thesis(
            id=f"T{_ids.__next__()}",
            symbol=opp.symbol,
            side=opp.side,
            venue=opp.venue,
            hypothesis=_hypothesis(opp),
            opened_ts=now,
            entry=price,
            qty=qty,
            remaining_qty=qty,
            notional=notional,
            invalidation=opp.invalidation,
            time_stop_ts=now + hours * 3600,
            peak=price,
            families=opp.coincidence.families,
            scores=opp.scores,
        )
        self.open[thesis.id] = thesis
        return thesis

    def mark(self, symbol: str, price: float) -> None:
        for t in self.open.values():
            if t.symbol != symbol or t.status != "open":
                continue
            if t.side == "long":
                t.peak = max(t.peak, price)
            else:
                t.peak = min(t.peak, price)

    def unrealized(self, marks: dict[str, float]) -> float:
        total = 0.0
        for t in self.open.values():
            if t.status != "open" or t.remaining_qty <= 0:
                continue
            px = marks.get(t.symbol)
            if px is None:
                continue
            total += _pnl(t, px, t.remaining_qty)
        return total

    def manage(self, symbol: str, price: float, now: float) -> list[tuple[Thesis, str, float]]:
        """返回需要执行的减仓/平仓：(thesis, reason, qty_to_close)。"""
        actions: list[tuple[Thesis, str, float]] = []
        for t in list(self.open.values()):
            if t.symbol != symbol or t.status != "open":
                continue
            self.mark(symbol, price)
            ret = _return(t, price)
            if t.side == "long" and price <= t.invalidation:
                actions.append((t, "invalidation", t.remaining_qty))
                continue
            if t.side == "short" and price >= t.invalidation:
                actions.append((t, "invalidation", t.remaining_qty))
                continue
            if now >= t.time_stop_ts and abs(ret) < 0.08:
                actions.append((t, "time_stop", t.remaining_qty))
                continue
            trail = self.config.trail_drawdown
            if t.side == "long" and t.peak > t.entry:
                dd = (t.peak - price) / t.peak
                if dd >= trail and ret >= 0.2:
                    actions.append((t, "trail", t.remaining_qty))
                    continue
            if t.side == "short" and t.peak < t.entry:
                dd = (price - t.peak) / t.peak if t.peak else 0.0
                if dd >= trail and ret >= 0.2:
                    actions.append((t, "trail", t.remaining_qty))
                    continue
            if (not t.scaled_40) and ret >= self.config.scale_40:
                qty = t.qty * self.config.scale_frac
                qty = min(qty, t.remaining_qty)
                if qty > 0:
                    t.scaled_40 = True
                    actions.append((t, "scale_40", qty))
            elif (not t.scaled_100) and ret >= self.config.scale_100:
                qty = t.qty * self.config.scale_frac
                qty = min(qty, t.remaining_qty)
                if qty > 0:
                    t.scaled_100 = True
                    actions.append((t, "scale_100", qty))
        return actions

    def apply_fill(self, thesis: Thesis, reason: str, qty: float, price: float, now: float, fee: float) -> float:
        qty = min(qty, thesis.remaining_qty)
        pnl = _pnl(thesis, price, qty) - fee
        thesis.remaining_qty -= qty
        thesis.realized_pnl += pnl
        if thesis.remaining_qty <= 1e-12:
            thesis.remaining_qty = 0.0
            thesis.status = "closed"
            thesis.exit_price = price
            thesis.exit_ts = now
            thesis.exit_reason = reason
            self.closed.append(thesis)
            self.open.pop(thesis.id, None)
        return pnl


def _hypothesis(opp: Opportunity) -> str:
    fams = ",".join(opp.coincidence.families)
    return (
        f"{'做多' if opp.side == 'long' else '做空'} {opp.symbol}："
        f"{fams} 同时出现（横盘安静度 {opp.coincidence.silence_before:.2f}），"
        f"拥挤度 {opp.scores.crowding:.2f}。{opp.reason}"
    )


def _return(t: Thesis, price: float) -> float:
    if t.entry <= 0:
        return 0.0
    raw = (price / t.entry - 1.0)
    return raw if t.side == "long" else -raw


def _pnl(t: Thesis, price: float, qty: float) -> float:
    if t.side == "long":
        return (price - t.entry) * qty
    return (t.entry - price) * qty
