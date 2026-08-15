from __future__ import annotations

from .config import SniperConfig
from .types import Account, Opportunity, Thesis, Venue


class RiskGovernor:
    """空仓是主状态。杠杆硬顶 1x。月亮仓只在四族共振且拥挤极低时出现。"""

    def __init__(self, config: SniperConfig):
        self.config = config

    def roll_clocks(self, account: Account, now: float) -> None:
        day = int(now // 86400)
        week = int(now // (86400 * 7))
        if day != account.day_stamp:
            account.day_stamp = day
            account.daily_pnl = 0.0
        if week != account.week_stamp:
            account.week_stamp = week
            account.weekly_pnl = 0.0

    def allow_new(self, account: Account, open_count: int, now: float, regime: str, side: str) -> str | None:
        if now < account.halted_until:
            return "halted"
        if now < account.cooldown_until:
            return "cooldown"
        if open_count >= self.config.max_concurrent:
            return "max_concurrent"
        if regime == "btc_stress" and side == "long":
            return "btc_stress"
        tradable = account.tradable_equity()
        if tradable < 20:
            return "no_cash"
        return None

    def size(self, account: Account, opp: Opportunity, now: float, mark_to_market: float = 0.0) -> tuple[float, bool]:
        eq = max(account.tradable_equity(mark_to_market), 1.0)
        moonshot = (
            len(opp.coincidence.families) >= self.config.moonshot_families
            and opp.scores.possibility >= 0.78
            and opp.scores.crowding <= 0.28
            and opp.ignition_kind == "informed"
            and now >= account.moonshot_ban_until
        )
        frac = self.config.moonshot_frac if moonshot else self.config.base_risk_frac
        # 退出通道差则强制缩小，避免纸面百倍
        frac *= 0.55 + 0.45 * opp.scores.exit_liquidity
        frac *= 0.7 + 0.3 * opp.conviction
        notional = min(eq * frac, account.cash * 0.95)
        # 1x 硬顶：名义不能超过可交易权益
        notional = min(notional, eq * self.config.max_leverage)
        return max(0.0, notional), moonshot

    def leverage_ok(self, venue: Venue, requested: float) -> bool:
        if requested > self.config.max_leverage + 1e-9:
            return False
        if venue == "futures_1x" and requested > 1.0:
            return False
        return True

    def register_pnl(self, account: Account, pnl: float, now: float, was_win: bool, win_ret: float) -> None:
        account.daily_pnl += pnl
        account.weekly_pnl += pnl
        if account.daily_pnl <= -self.config.daily_kill_frac * account.starting:
            account.halted_until = now + 20 * 3600
        if account.weekly_pnl <= -self.config.weekly_kill_frac * account.starting:
            account.halted_until = now + 3 * 86400
        if was_win and win_ret >= 0.5:
            account.moonshot_ban_until = now + self.config.post_win_moonshot_ban_hours * 3600
        if not was_win:
            account.cooldown_until = now + self.config.post_loss_cooldown_hours * 3600

    def ratchet(self, account: Account, equity: float) -> float:
        """权益翻倍时把该段盈利的一部分锁进金库，防止 20x 回吐。"""
        locked = 0.0
        while equity >= account.last_double_lock * 2.0 and account.cash > 0:
            gain = account.last_double_lock
            lock = min(account.cash * 0.9, gain * self.config.vault_lock_of_gain)
            if lock <= 0:
                break
            account.cash -= lock
            account.vault += lock
            account.last_double_lock *= 2.0
            locked += lock
        account.high_watermark = max(account.high_watermark, equity)
        return locked

    def stop_price_ok(self, thesis: Thesis, entry: float) -> bool:
        if entry <= 0:
            return False
        if thesis.side == "long":
            risk = (entry - thesis.invalidation) / entry
        else:
            risk = (thesis.invalidation - entry) / entry
        return 0 < risk <= 0.35
