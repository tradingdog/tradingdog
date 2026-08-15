from __future__ import annotations

from dataclasses import dataclass

from .coiled import CoiledRegistry
from .coincidence import CoincidenceEngine
from .config import SniperConfig
from .ignition import classify_ignition, ignition_score
from .memory import PostmortemMemory
from .narrative import NarrativeLagEngine
from .risk import RiskGovernor
from .scorer import ConvictionScorer
from .sensors import SensorHub
from .thesis import ThesisBook
from .types import Account, Bar, Opportunity, Pulse, Thesis
from .universe import PossibilitySurface
from .venues import PaperVenue


@dataclass
class JournalEvent:
    ts: float
    kind: str
    symbol: str
    detail: str


class AlphaSniperEngine:
    def __init__(self, config: SniperConfig | None = None):
        self.config = config or SniperConfig()
        self.account = Account(
            cash=self.config.starting_usdt,
            starting=self.config.starting_usdt,
            high_watermark=self.config.starting_usdt,
            last_double_lock=self.config.starting_usdt,
        )
        self.universe = PossibilitySurface(self.config)
        self.coiled = CoiledRegistry(self.config)
        self.coincidence = CoincidenceEngine(self.config)
        self.narrative = NarrativeLagEngine()
        self.sensors = SensorHub()
        self.scorer = ConvictionScorer(self.config)
        self.risk = RiskGovernor(self.config)
        self.book = ThesisBook(self.config)
        self.memory = PostmortemMemory()
        self.venue = PaperVenue(self.config)
        self.journal: list[JournalEvent] = []
        self.now: float = 0.0
        self.skips: list[tuple[str, str]] = []
        self.recent_pulses: list[Pulse] = []
        self.recent_coincidences: list = []
        self.near_misses: list[dict] = []

    def attach_profiles(self, profiles) -> None:
        self.universe.set_profiles(profiles)
        self.coiled.set_profiles(profiles)

    def equity(self) -> float:
        return self.account.equity(self.book.unrealized(self.venue.marks))

    def step(self, bar: Bar) -> list[Thesis]:
        self.now = bar.ts
        self.venue.on_price(bar.symbol, bar.close)
        self.universe.on_bar(bar)
        coiled = self.coiled.on_bar(bar)
        self.narrative.on_bar(bar)
        self.risk.roll_clocks(self.account, bar.ts)

        closed: list[Thesis] = []
        for thesis, reason, qty in self.book.manage(bar.symbol, bar.close, bar.ts):
            t = self._reduce(thesis, reason, qty, bar.close, bar.ts)
            if t is not None:
                closed.append(t)

        self.risk.ratchet(self.account, self.equity())

        if not self.universe.in_hunting_ground(bar.symbol):
            return closed

        pulses = self.sensors.on_bar(bar, coiled)
        moved = self.universe.already_moved(bar.symbol)
        lag_s, lag_why = self.narrative.laggard_pulse_strength(bar.symbol, coiled.coiled_score, moved)
        if lag_s >= 0.5:
            pulses.append(
                Pulse("narrative_lag", "narrative", bar.symbol, "long", min(1.0, lag_s), bar.ts, {"why": lag_why})
            )
        dump_frac = self.narrative.dump_cluster(bar.symbol)
        if dump_frac >= 0.6:
            pulses.append(Pulse("narrative_dump", "narrative", bar.symbol, "short", dump_frac, bar.ts, {}))

        if pulses:
            self.recent_pulses.extend(pulses)
            if len(self.recent_pulses) > 240:
                self.recent_pulses = self.recent_pulses[-240:]

        seen: set[tuple[str, str]] = set()
        for pulse in pulses:
            coin = self.coincidence.ingest(pulse, coiled.silence, coiled.exhaustion)
            if coin is None:
                continue
            key = (coin.symbol, coin.side)
            if key in seen or self.book.has_symbol(coin.symbol):
                continue
            seen.add(key)
            self.recent_coincidences.append(coin)
            if len(self.recent_coincidences) > 80:
                self.recent_coincidences = self.recent_coincidences[-80:]
            opp = self._opportunity(bar, coiled, coin, lag_why)
            if opp is None:
                self.near_misses.append(
                    {
                        "ts": bar.ts,
                        "symbol": bar.symbol,
                        "side": coin.side,
                        "families": list(coin.families),
                        "reason": "三族亮了，但可能性/拥挤/退出/信念没过门，继续蹲",
                    }
                )
                if len(self.near_misses) > 40:
                    self.near_misses = self.near_misses[-40:]
                continue
            deny = self.risk.allow_new(
                self.account, self.book.open_count(), bar.ts, self.universe.regime(), opp.side
            )
            if deny:
                self.skips.append((bar.symbol, deny))
                self.journal.append(JournalEvent(bar.ts, "skip", bar.symbol, deny))
                continue
            self._open(opp, bar)
        return closed

    def _opportunity(self, bar: Bar, coiled, coin, lag_why: str) -> Opportunity | None:
        scores = self.universe.scores_partial(bar.symbol, bar)
        z = self.sensors.volume_z(bar.symbol)
        kind = classify_ignition(bar, z)
        scores.ignition = ignition_score(kind, coin.score, z)
        venue = coiled.venue
        if coin.side == "short":
            venue = "futures_1x"
        if bar.is_alpha and coin.side == "long":
            venue = "alpha"
        hours = self.config.coiled_breakout_hours
        if "catalyst" in coin.families:
            hours = self.config.catalyst_hours
        if coin.side == "short":
            hours = self.config.dump_hours
        reason = lag_why or ",".join(coin.families)
        invalidation = coiled.invalidation_hint
        if coin.side == "long":
            invalidation = min(invalidation, bar.close * (1.0 - self.config.max_loss_frac * 1.8))
        else:
            invalidation = max(invalidation, bar.close * (1.0 + self.config.max_loss_frac * 1.8))
        return self.scorer.score(
            coin,
            scores,
            kind,
            venue,
            reason,
            invalidation,
            hours,
            precomputed=coiled.armed or coin.side == "short",
        )

    def _open(self, opp: Opportunity, bar: Bar) -> Thesis | None:
        mtm = self.book.unrealized(self.venue.marks)
        notional, moonshot = self.risk.size(self.account, opp, bar.ts, mtm)
        if notional < 15:
            self.skips.append((opp.symbol, "dust"))
            return None
        if not self.risk.leverage_ok(opp.venue, 1.0):
            return None
        is_buy = opp.side == "long"
        fill = self.venue.execute(opp.symbol, opp.venue, is_buy, notional, bar.ts, leverage=1.0)
        if fill is None:
            return None
        self.account.cash -= notional + fill.fee
        thesis = self.book.open_from(opp, fill.price, fill.qty, notional, bar.ts)
        if not self.risk.stop_price_ok(thesis, fill.price):
            # 失效价太远等于没有止损，拆掉
            self._reduce(thesis, "bad_stop", thesis.remaining_qty, fill.price, bar.ts)
            return None
        self.journal.append(
            JournalEvent(
                bar.ts,
                "open",
                opp.symbol,
                f"{opp.side} {opp.venue} notional={notional:.1f} moon={moonshot} {thesis.hypothesis}",
            )
        )
        return thesis

    def _reduce(self, thesis: Thesis, reason: str, qty: float, price: float, now: float) -> Thesis | None:
        if qty <= 0 or thesis.remaining_qty <= 0:
            return None
        notional_part = thesis.entry * qty
        is_buy = thesis.side == "short"  # 平空要买回
        fill = self.venue.execute(thesis.symbol, thesis.venue, is_buy, notional_part, now, leverage=1.0)
        fee = fill.fee if fill else 0.0
        px = fill.price if fill else price
        pnl = self.book.apply_fill(thesis, reason, qty, px, now, fee)
        # 释放占用名义 + 盈亏
        self.account.cash += notional_part + pnl
        # fee 已在 pnl 里减过；apply_fill 把 fee 从 pnl 扣了，cash 加的是 raw pnl+notional
        # apply_fill: pnl = _pnl - fee, so cash += notional + pnl = notional + raw_pnl - fee. Correct.
        if thesis.status == "closed":
            rec = self.memory.remember(thesis)
            self.scorer.learn(thesis.families, rec.fat_tail, rec.fakeout)
            win = thesis.realized_pnl > 0
            win_ret = thesis.realized_pnl / thesis.notional if thesis.notional else 0.0
            self.risk.register_pnl(self.account, thesis.realized_pnl, now, win, win_ret)
            self.journal.append(
                JournalEvent(
                    now,
                    "close",
                    thesis.symbol,
                    f"{reason} pnl={thesis.realized_pnl:.2f} ret={win_ret:.1%} {thesis.hypothesis[:80]}",
                )
            )
            return thesis
        return None

    def flatten_all(self, now: float) -> None:
        for thesis in list(self.book.open.values()):
            px = self.venue.marks.get(thesis.symbol, thesis.entry)
            self._reduce(thesis, "flatten", thesis.remaining_qty, px, now)


def run_paper(config: SniperConfig | None = None) -> AlphaSniperEngine:
    from .paper import PaperUniverse

    config = config or SniperConfig()
    world = PaperUniverse(config)
    engine = AlphaSniperEngine(config)
    engine.attach_profiles(world.profiles)
    step = config.paper_bar_seconds
    end = config.paper_days * 86400
    ts = 0.0
    while ts <= end:
        # 先更新 BTC 体制，再扫猎物
        ordered = ["BTCUSDT"] + [s for s in world.symbols if s != "BTCUSDT"]
        for symbol in ordered:
            engine.step(world.bar(symbol, ts))
        ts += step
    engine.flatten_all(end)
    return engine
