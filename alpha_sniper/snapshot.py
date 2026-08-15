from __future__ import annotations

import time
from math import log

from .types import Thesis


FAMILY_ZH = {
    "microstructure": "成交",
    "catalyst": "消息",
    "positioning": "大单",
    "narrative": "板块",
    "calendar": "时间点",
}

SENSOR_ZH = {
    "volume_vacuum": "放量且盘口薄",
    "silence_break": "横盘后放量",
    "listing_catalyst": "上币/公告",
    "informed_flow": "大单方向",
    "exchange_inflow": "充币到交易所",
    "unlock_calendar": "解锁",
    "weekend_vacuum": "周末流动性差",
    "liquidity_hours": "薄流动性时段",
    "attention_burst": "成交突然爆发（近似关注度）",
    "alpha_new_listing": "Alpha 上新",
    "narrative_lag": "同板块还没涨的",
    "narrative_dump": "同板块一起跌",
    "aggressive_tape": "一边倒的成交",
}

SKIP_ZH = {
    "halted": "今天亏超限，只许平仓",
    "cooldown": "刚亏过，冷却中不开新仓",
    "max_concurrent": "同时持仓已满（最多 2 个）",
    "btc_stress": "BTC 大跌，不开山寨多单",
    "no_cash": "可用资金不足",
    "dust": "算出来的仓位太小，放弃",
}

EXIT_ZH = {
    "invalidation": "打到止损价，全部平掉",
    "time_stop": "超过持仓时限且涨跌不到 20%，判定不是妖币走势，时间止损",
    "trail": "已赚超过 20%，又从高/低点回撤 25%，跟踪止盈",
    "scale_40": "浮盈达到 40%，先减仓 25% 锁定一部分",
    "scale_100": "浮盈达到 100%，再减仓 25%",
    "flatten": "手动全部平仓",
    "手动全部平仓": "手动全部平仓",
    "手动平仓": "手动平仓",
    "bad_stop": "止损距离不合理，开完立刻撤掉",
}

VENUE_ZH = {"spot": "现货", "futures_1x": "1x 合约", "alpha": "Alpha"}
SIDE_ZH = {"long": "做多", "short": "做空"}
REGIME_ZH = {"risk_on": "偏多", "chop": "震荡", "btc_stress": "BTC 大跌"}
STATE_ZH = {"SQUAT": "空仓", "ARMED": "已盯上", "IN_THESIS": "持仓中"}
ORIGIN_ZH = {
    "startup_replay": "启动回放（K线当时的时间，不是程序那天在跑）",
    "live": "盯盘中记下",
}

PAPER_SCRIPT = [
    {"day": 5.0, "symbol": "COILUSDT", "title": "横盘后上币", "hint": "应提前盯住，放量后做多 Alpha"},
    {"day": 8.0, "symbol": "FAKEUSDT", "title": "单独放量", "hint": "只有一类信号，应忽略"},
    {"day": 12.0, "symbol": "DUMPUSDT", "title": "冲高后出货", "hint": "解锁+充币+卖盘，1x 空"},
    {"day": 18.4, "symbol": "LAGUSDT", "title": "同板块还没涨", "hint": "不追龙头，买还没动的"},
    {"day": 20.0, "symbol": "THINUSDT", "title": "盘口太薄", "hint": "退出流动性不够，应拒绝"},
    {"day": 24.2, "symbol": "STRESSUSDT", "title": "BTC 大跌日", "hint": "禁止新开山寨多单"},
]

FAMILIES = ("microstructure", "catalyst", "positioning", "narrative", "calendar")


def build_snapshot(session) -> dict:
    engine = session.engine
    now = engine.now
    marks = engine.venue.marks
    equity = engine.equity()
    starting = engine.account.starting
    target = engine.config.target_usdt
    regime = engine.universe.regime()
    open_theses = [t for t in engine.book.open.values() if t.status == "open"]
    armed = [
        s.symbol
        for s in engine.coiled.states.values()
        if s.armed and engine.universe.in_hunting_ground(s.symbol)
    ]
    if open_theses:
        state = "IN_THESIS"
    elif armed:
        state = "ARMED"
    else:
        state = "SQUAT"

    skip_counts: dict[str, int] = {}
    for _sym, why in engine.skips:
        skip_counts[why] = skip_counts.get(why, 0) + 1

    return {
        "mode": getattr(session, "mode", "paper"),
        "live": False,
        "clock_mode": "unix" if getattr(session, "mode", "") == "binance_sim" else "sim",
        "allow_new": getattr(session, "allow_new", True),
        "blocked": sorted(getattr(session, "blocked", set()) or []),
        "ready": getattr(session, "ready", True),
        "boot_error": getattr(session, "boot_error", ""),
        "running": session.running,
        "finished": session.finished,
        "speed": session.speed,
        "now": now,
        "day": round(now / 86400.0, 3),
        "horizon_days": engine.config.horizon_days,
        "state": state,
        "state_zh": STATE_ZH[state],
        "narration": _narrate(state, open_theses, armed, regime, engine, now, marks),
        "account": {
            "starting": starting,
            "equity": round(equity, 2),
            "cash": round(engine.account.cash, 2),
            "vault": round(engine.account.vault, 2),
            "unrealized": round(engine.book.unrealized(marks), 2),
            "high_watermark": round(engine.account.high_watermark, 2),
            "daily_pnl": round(engine.account.daily_pnl, 2),
            "weekly_pnl": round(engine.account.weekly_pnl, 2),
            "target": target,
            "progress_linear": _clamp((equity - starting) / (target - starting)),
            "progress_log": _clamp(log(max(equity, 1.0) / starting) / log(target / starting)),
            "multiple": round(equity / starting, 3) if starting else 0.0,
            "stepping_stones": _stones(equity, starting),
        },
        "risk": {
            "regime": regime,
            "regime_zh": REGIME_ZH.get(regime, regime),
            "btc_ret_24h": round(engine.universe.btc_ret_24h, 4),
            "halted": now < engine.account.halted_until,
            "cooldown": now < engine.account.cooldown_until,
            "moonshot_ban": now < engine.account.moonshot_ban_until,
            "open_slots_used": engine.book.open_count(),
            "max_concurrent": engine.config.max_concurrent,
            "max_leverage": engine.config.max_leverage,
            "gates": _gates(engine, now, regime),
        },
        "theses": [_thesis_view(t, marks, now, engine) for t in open_theses],
        "closed": [_thesis_view(t, marks, now, engine) for t in engine.book.closed[-12:]],
        "hunt": _hunt_rows(engine, now),
        "discoveries": _discoveries(engine, now, getattr(session, "quotes", {}) or {}),
        "performance": _performance(engine, equity, starting),
        "rules": _rules(engine, now, regime),
        "pulses": [_pulse_view(p) for p in engine.recent_pulses[-40:]],
        "journal": [
            {
                "ts": e.ts,
                "day": round(e.ts / 86400.0, 3),
                "kind": e.kind,
                "kind_zh": {"open": "开仓", "close": "平仓", "skip": "过滤"}.get(e.kind, e.kind),
                "symbol": e.symbol,
                "detail": SKIP_ZH.get(e.detail, e.detail),
            }
            for e in engine.journal[-50:]
        ],
        "near_misses": [
            {
                **m,
                "day": round(m["ts"] / 86400.0, 3),
                "side_zh": SIDE_ZH.get(m.get("side", ""), ""),
                "families_zh": [FAMILY_ZH.get(f, f) for f in m.get("families", [])],
                "origin": _miss_origin(m, session),
                "origin_zh": ORIGIN_ZH.get(_miss_origin(m, session), ORIGIN_ZH["live"]),
            }
            for m in engine.near_misses[-16:]
        ],
        "skips": [{"why": k, "why_zh": SKIP_ZH.get(k, k), "count": v} for k, v in skip_counts.items()],
        "script": [
            {**ev, "status": "done" if now / 86400.0 >= ev["day"] else "upcoming"}
            for ev in PAPER_SCRIPT
        ],
        "equity_curve": session.equity_curve[-400:],
        "prices": session.price_tails,
        "health": getattr(session, "health", {}) or {},
        "loop_error": getattr(session, "loop_error", "") or "",
        "runtime": _runtime(session),
        "wall_now": time.time(),
    }


def _thesis_view(t: Thesis, marks: dict[str, float], now: float, engine=None) -> dict:
    px = marks.get(t.symbol, t.exit_price or t.entry)
    if t.entry > 0:
        raw = px / t.entry - 1.0
        ret = raw if t.side == "long" else -raw
    else:
        ret = 0.0
    if t.status == "open":
        upl = (px - t.entry) * t.remaining_qty if t.side == "long" else (t.entry - px) * t.remaining_qty
        pnl = t.realized_pnl + upl
    else:
        pnl = t.realized_pnl
        ret = t.realized_pnl / t.notional if t.notional else ret
    remain_h = max(0.0, (t.time_stop_ts - now) / 3600.0) if t.status == "open" else 0.0
    hold_h = (t.time_stop_ts - t.opened_ts) / 3600.0 if t.time_stop_ts and t.opened_ts else 0.0
    stop_pct = abs(t.entry - t.invalidation) / t.entry if t.entry else 0.0
    if t.side == "long":
        tp1 = t.entry * 1.40
        tp2 = t.entry * 2.00
    else:
        tp1 = t.entry * 0.60
        tp2 = t.entry * 0.00
    eq = engine.account.starting if engine is None else max(engine.equity(), 1.0)
    return {
        "id": t.id,
        "symbol": t.symbol,
        "binance_url": _binance_url(t.symbol),
        "side": t.side,
        "side_zh": SIDE_ZH[t.side],
        "venue": t.venue,
        "venue_zh": VENUE_ZH.get(t.venue, t.venue),
        "hypothesis": t.hypothesis,
        "plain": _plain_thesis(t),
        "why_side": _why_side(t.side, t.families),
        "entry": t.entry,
        "mark": px,
        "exit_price": t.exit_price,
        "invalidation": t.invalidation,
        "stop_pct": round(stop_pct, 4),
        "tp1": tp1,
        "tp2": tp2,
        "notional": round(t.notional, 2),
        "qty": t.qty,
        "remaining_qty": t.remaining_qty,
        "size_pct": round(t.notional / eq, 4) if eq else 0.0,
        "remaining_frac": (t.remaining_qty / t.qty) if t.qty else 0.0,
        "ret": round(ret, 4),
        "pnl": round(pnl, 2),
        "peak": t.peak,
        "scaled_40": t.scaled_40,
        "scaled_100": t.scaled_100,
        "families": list(t.families),
        "families_zh": [FAMILY_ZH.get(f, f) for f in t.families],
        "status": t.status,
        "exit_reason": t.exit_reason,
        "exit_reason_zh": EXIT_ZH.get(t.exit_reason or "", t.exit_reason or ""),
        "hours_left": round(remain_h, 2),
        "hold_hours": round(hold_h, 2),
        "opened_ts": t.opened_ts,
        "exit_ts": t.exit_ts,
        "opened_day": round(t.opened_ts / 86400.0, 3),
    }


def _plain_thesis(t: Thesis) -> str:
    fams = "、".join(FAMILY_ZH.get(f, f) for f in t.families) or "未知信号"
    ch = VENUE_ZH.get(t.venue, t.venue)
    stop_pct = abs(t.entry - t.invalidation) / t.entry if t.entry else 0.0
    return (
        f"{ch}{SIDE_ZH[t.side]} {t.symbol}。"
        f"入场理由：{fams} 三类以上独立信号，并且 K 线是箱体突破（必要时等回踩）。"
        f"用了 {t.notional:.1f} USDT。"
        f"止损 {t.invalidation:.8g}（距入场 {stop_pct:.1%}）。"
        f"涨/跌 40% 先减 25%，涨/跌 100% 再减 25%；"
        f"从极值回撤 25% 且已赚 20% 则跟踪止盈；超时没走出 20% 则判定不是妖、平掉。"
    )


def _why_side(side: str, families) -> str:
    fams = set(families or [])
    if side == "short":
        extra = "、".join(FAMILY_ZH.get(f, f) for f in fams) or "出货信号"
        return f"做空：{extra} 指向下跌/出货，而不是反弹。"
    extra = "、".join(FAMILY_ZH.get(f, f) for f in fams) or "横盘后启动"
    return f"做多：{extra} 指向向上突破，且没有解锁+急涨的出货结构。"


def _binance_url(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return f"https://www.binance.com/zh-CN/trade/{base}_USDT?type=spot"


def _quote_of(quotes, symbol: str):
    if isinstance(quotes, dict):
        q = quotes.get(symbol)
        if q is None:
            return None
        if hasattr(q, "price"):
            return q
        if isinstance(q, dict):
            return q
    return None


def _discoveries(engine, now: float, quotes) -> list[dict]:
    rows = []
    cfg = engine.config
    eq = max(engine.equity(), 1.0)
    planned = min(eq * cfg.base_risk_frac, engine.account.cash * 0.95)
    planned_moon = min(eq * cfg.moonshot_frac, engine.account.cash * 0.95)
    for row in _hunt_rows(engine, now):
        q = _quote_of(quotes, row["symbol"])
        px = row["mark"] or (getattr(q, "price", None) if q is not None else None) or 0.0
        chg = getattr(q, "change24h", None) if q is not None else None
        if chg is None and isinstance(q, dict):
            chg = q.get("change24h")
        if chg is None:
            chg = row["moved"]
        vol = getattr(q, "quote_volume", None) if q is not None else None
        if vol is None and isinstance(q, dict):
            vol = q.get("quote_volume")
        st = engine.coiled.states.get(row["symbol"])
        stop = st.invalidation_hint if st else 0.0
        if row["side"] == "long":
            tp1 = px * (1.0 + cfg.scale_40) if px else 0.0
            tp2 = px * (1.0 + cfg.scale_100) if px else 0.0
            stop_pct = (px - stop) / px if px else 0.0
        else:
            tp1 = px * (1.0 - cfg.scale_40) if px else 0.0
            tp2 = px * (1.0 - cfg.scale_100) if px else 0.0
            stop_pct = (stop - px) / px if px else 0.0
        how = []
        if row["armed"]:
            how.append(
                f"用币安 1 小时 K 线算出来的：波动收窄、成交萎缩"
                f"（横盘缩量 {row['coiled']:.2f}，安静度 {row['silence']:.2f}）"
            )
        if row.get("ignited"):
            how.append("已经出现突破箱体的大实体 K 线")
        if row.get("pullback_ready"):
            how.append("突破后回踩箱沿，符合启动后再确认的形态")
        if row.get("extended"):
            how.append("已经离开箱体较远，若没有上币导火线会等回踩，不追第一根大阳")
        if row["votes"]:
            seen = set()
            parts = []
            for v in row["votes"]:
                key = (v.get("sensor_zh"), v.get("family_zh"), v.get("side"))
                if key in seen:
                    continue
                seen.add(key)
                side = "做多" if v.get("side") == "long" else "做空" if v.get("side") == "short" else ""
                parts.append(f"{v.get('sensor_zh')}（{v.get('family_zh')}{('，' + side) if side else ''}）")
            if parts:
                how.append("已经出现的信号：" + "、".join(parts))
        if not how:
            if row["coiled"] >= 0.28:
                how.append(f"1 小时波动在收窄（缩量 {row['coiled']:.2f}），还没到可开仓的横盘标准")
            else:
                how.append("还在扫币安 1 小时 K 线和盘口，尚未形成可交易结构")
        if row["gap"] == 0 and row["armed"]:
            status = "独立信号已齐，还要过 K 线形态和空间/拥挤/退出流动性才能开仓"
        elif row["armed"]:
            status = f"已盯上横盘箱体。还差 {row['gap']} 类独立信号（成交/消息/大单/板块/时间点里再凑）"
        else:
            status = row["wait"]
        interesting = row["armed"] or bool(row["votes"]) or row["coiled"] >= 0.28
        rows.append(
            {
                **row,
                "interesting": interesting,
                "binance_url": _binance_url(row["symbol"]),
                "price": px,
                "change24h": chg,
                "quote_volume": vol,
                "how_found": how,
                "why_side": _why_side(row["side"], row["families"]),
                "status": status,
                "planned_usdt": round(planned, 2),
                "planned_moon_usdt": round(planned_moon, 2),
                "stop": stop,
                "stop_pct": round(stop_pct, 4),
                "tp1": tp1,
                "tp2": tp2,
                "time_stop_hours": cfg.coiled_breakout_hours,
                "trail_pct": cfg.trail_drawdown,
                "scale_frac": cfg.scale_frac,
            }
        )
    rows.sort(key=lambda r: (not r["armed"], not r["votes"], -r["coiled"], r["gap"]))
    return rows


def _performance(engine, equity: float, starting: float) -> dict:
    closed = list(engine.book.closed)
    pnls = [t.realized_pnl for t in closed]
    rets = [(t.realized_pnl / t.notional) if t.notional else 0.0 for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    best = max(closed, key=lambda t: t.realized_pnl, default=None)
    worst = min(closed, key=lambda t: t.realized_pnl, default=None)
    return {
        "trades": len(closed),
        "open": engine.book.open_count(),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(closed)) if closed else 0.0,
        "realized_pnl": round(sum(pnls), 2),
        "unrealized": round(engine.book.unrealized(engine.venue.marks), 2),
        "equity": round(equity, 2),
        "starting": starting,
        "total_ret": round((equity - starting) / starting, 4) if starting else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "best_symbol": best.symbol if best else "",
        "best_pnl": round(best.realized_pnl, 2) if best else 0.0,
        "worst_symbol": worst.symbol if worst else "",
        "worst_pnl": round(worst.realized_pnl, 2) if worst else 0.0,
        "avg_ret": round(sum(rets) / len(rets), 4) if rets else 0.0,
        "daily_pnl": round(engine.account.daily_pnl, 2),
        "weekly_pnl": round(engine.account.weekly_pnl, 2),
    }


def _rules(engine, now: float, regime: str) -> list[dict]:
    cfg = engine.config
    acc = engine.account
    return [
        {
            "title": "仓位",
            "text": f"普通一笔约权益的 {cfg.base_risk_frac:.0%}（现在约 {acc.tradable_equity() * cfg.base_risk_frac:.0f} USDT）。信号极强才用 {cfg.moonshot_frac:.0%}。杠杆硬顶 {cfg.max_leverage:.0f}x，同时最多 {cfg.max_concurrent} 笔。",
        },
        {
            "title": "止损",
            "text": f"开仓前就算好止损价。止损距离不超过入场价 35%。单笔最大亏损按权益 {cfg.max_loss_frac:.0%} 约束。打到止损价就全平。",
        },
        {
            "title": "止盈",
            "text": f"浮盈 {cfg.scale_40:.0%} 先减仓 {cfg.scale_frac:.0%}；浮盈 {cfg.scale_100:.0%} 再减 {cfg.scale_frac:.0%}。已赚 20% 后又从高/低点回撤 {cfg.trail_drawdown:.0%}，跟踪止盈全平。",
        },
        {
            "title": "时间",
            "text": f"横盘突破单最多拿 {cfg.coiled_breakout_hours:.0f} 小时，消息单 {cfg.catalyst_hours:.0f} 小时，空头 {cfg.dump_hours:.0f} 小时。超时且涨跌不到 {cfg.time_stop_min_move:.0%} 就判定不是妖、平掉。",
        },
        {
            "title": "熔断",
            "text": f"当天亏超过起始资金的 {cfg.daily_kill_frac:.0%} 停止开新仓。当周亏超过 {cfg.weekly_kill_frac:.0%} 停更久。亏一笔后冷却 {cfg.post_loss_cooldown_hours:.0f} 小时。",
        },
        {
            "title": "BTC",
            "text": f"BTC 24 小时跌超过 {abs(cfg.btc_stress_24h):.0%} 时，禁止新开山寨多单。现在 BTC 24h {engine.universe.btc_ret_24h:+.2%}，环境：{REGIME_ZH.get(regime, regime)}。",
        },
    ]


def _hunt_rows(engine, now: float) -> list[dict]:
    rows = []
    for profile in engine.universe.profiles.values():
        if not engine.universe.in_hunting_ground(profile.symbol):
            continue
        st = engine.coiled.states.get(profile.symbol)
        scores = engine.universe.scores_partial(profile.symbol)
        votes = engine.coincidence.votes(profile.symbol, now)
        fams = sorted({v["family"] for v in votes})
        gap = max(0, engine.config.min_independent_families - len(fams))
        mark = engine.venue.marks.get(profile.symbol)
        if st is None:
            continue
        if gap == 0 and st.armed:
            wait = "三类信号已齐，等 K 线突破或回踩确认"
        elif st.armed:
            wait = f"横盘缩量箱体已形成，还差 {gap} 类信号"
        elif st.coiled_score >= 0.28:
            wait = "波动在收窄，继续看"
        else:
            wait = "还没形成可交易结构"
        rows.append(
            {
                "symbol": profile.symbol,
                "tier": profile.listing_tier,
                "narrative": profile.narrative,
                "is_alpha": profile.is_alpha,
                "mark": mark,
                "coiled": round(st.coiled_score, 3),
                "silence": round(st.silence, 3),
                "vacuum": round(st.vacuum, 3),
                "exhaustion": round(st.exhaustion, 3),
                "armed": st.armed,
                "ignited": st.ignited,
                "pullback_ready": st.pullback_ready,
                "extended": st.extended,
                "side": st.preferred_side,
                "side_zh": SIDE_ZH[st.preferred_side],
                "venue_zh": VENUE_ZH.get(st.venue, st.venue),
                "possibility": round(scores.possibility, 3),
                "crowding": round(scores.crowding, 3),
                "exit_liquidity": round(scores.exit_liquidity, 3),
                "moved": round(engine.universe.already_moved(profile.symbol), 3),
                "families": fams,
                "family_lamps": [
                    {
                        "id": f,
                        "zh": FAMILY_ZH[f],
                        "on": f in fams,
                    }
                    for f in FAMILIES
                ],
                "votes": [
                    {**v, "family_zh": FAMILY_ZH.get(v["family"], v["family"]), "sensor_zh": SENSOR_ZH.get(v["sensor"], v["sensor"])}
                    for v in votes
                ],
                "gap": gap,
                "wait": wait,
            }
        )
    rows.sort(key=lambda r: (not r["armed"], -r["coiled"], r["gap"]))
    return rows


def _pulse_view(p) -> dict:
    return {
        "ts": p.ts,
        "day": round(p.ts / 86400.0, 3),
        "symbol": p.symbol,
        "side": p.side,
        "side_zh": SIDE_ZH[p.side],
        "family": p.family,
        "family_zh": FAMILY_ZH.get(p.family, p.family),
        "sensor": p.sensor_id,
        "sensor_zh": SENSOR_ZH.get(p.sensor_id, p.sensor_id),
        "strength": round(p.strength, 3),
    }


def _gates(engine, now: float, regime: str) -> list[dict]:
    acc = engine.account
    return [
        {
            "id": "leverage",
            "ok": True,
            "label": "杠杆上限 1x",
            "detail": "不用 5x/10x，爆一次就没了",
        },
        {
            "id": "btc",
            "ok": regime != "btc_stress",
            "label": "BTC 环境",
            "detail": "BTC 大跌，暂停山寨多单" if regime == "btc_stress" else "可以找山寨机会",
        },
        {
            "id": "halt",
            "ok": now >= acc.halted_until,
            "label": "当日亏损限制",
            "detail": "已触发，停止开新仓" if now < acc.halted_until else "未触发",
        },
        {
            "id": "cool",
            "ok": now >= acc.cooldown_until,
            "label": "亏损后冷却",
            "detail": "冷却中" if now < acc.cooldown_until else "可以开新仓",
        },
        {
            "id": "slots",
            "ok": engine.book.open_count() < engine.config.max_concurrent,
            "label": f"持仓数 {engine.book.open_count()}/{engine.config.max_concurrent}",
            "detail": "有空位才开下一笔",
        },
        {
            "id": "moon",
            "ok": now >= acc.moonshot_ban_until,
            "label": "加大仓位",
            "detail": "刚大赚过，48 小时内不加仓" if now < acc.moonshot_ban_until else "只有信号特别强才加仓",
        },
    ]


def _narrate(state, open_theses, armed, regime, engine, now, marks) -> str:
    day = now / 86400.0
    if regime == "btc_stress":
        head = "BTC 跌得急，系统暂停新的山寨多单。"
    else:
        head = ""
    if state == "IN_THESIS":
        bits = []
        for t in open_theses:
            px = marks.get(t.symbol, t.entry)
            raw = (px / t.entry - 1.0) if t.entry else 0.0
            ret = raw if t.side == "long" else -raw
            bits.append(f"{t.symbol} {SIDE_ZH[t.side]} {ret:+.0%}")
        return head + "当前持仓：" + "；".join(bits) + "。止损没打就拿着，打了就平。"
    if state == "ARMED":
        bits = []
        for sym in armed[:3]:
            st = engine.coiled.states.get(sym)
            px = marks.get(sym)
            if st and px:
                bits.append(
                    f"{sym} 现价 {px:.8g}，预案{SIDE_ZH[st.preferred_side]}，"
                    f"止损 {st.invalidation_hint:.8g}"
                )
            else:
                bits.append(sym)
        return (
            head
            + "发现："
            + "；".join(bits)
            + "。这是币安 1 小时 K 线算出的横盘缩量箱体。还要突破大实体、并出现消息/板块/解锁导火线才开仓。"
        )
    last_close = engine.book.closed[-1].exit_ts if engine.book.closed else 0.0
    quiet_h = max(0.0, (now - last_close) / 3600.0) if last_close else 0.0
    n_coil = sum(1 for s in engine.coiled.states.values() if s.armed)
    if quiet_h >= 1:
        wait = f"空仓已等 {quiet_h:.0f} 小时。"
    else:
        wait = "现在空仓。"
    return head + f"{wait}监控里有 {n_coil} 个横盘缩量的币。没有箱体突破加导火线，就不开仓。抓的是少而精的妖币，不是小波动。"


def _stones(equity: float, starting: float) -> list[dict]:
    marks = [starting]
    x = starting
    while x * 2 <= 100_000:
        x *= 2
        marks.append(x)
    if marks[-1] != 100_000:
        marks.append(100_000)
    return [{"at": m, "hit": equity >= m, "label": _money(m)} for m in marks]


def _money(x: float) -> str:
    if x >= 1000:
        return f"{x/1000:.0f}k" if x >= 10000 or x % 1000 == 0 else f"{x/1000:.1f}k"
    return f"{x:.0f}"


def _miss_origin(m: dict, session) -> str:
    origin = str(m.get("origin") or "")
    if origin in ORIGIN_ZH:
        return origin
    ts = float(m.get("ts") or 0)
    started = float(getattr(session, "process_started_at", 0) or 0)
    if getattr(session, "mode", "") == "binance_sim" and ts and started and ts < started - 7200:
        return "startup_replay"
    return "live"


def _runtime(session) -> dict:
    wall = time.time()
    started = float(getattr(session, "process_started_at", 0) or 0)
    boot = float(getattr(session, "boot_started_at", 0) or 0)
    ready = float(getattr(session, "ready_at", 0) or 0)
    last_poll = float(getattr(session, "last_poll", 0) or 0)
    last_bars = getattr(session, "_last_bar_ts", {}) or {}
    last_bar = max(last_bars.values()) if last_bars else 0.0
    mode = getattr(session, "mode", "")
    bar_sec = 3600.0 if mode == "binance_sim" else float(getattr(getattr(session, "config", None), "bar_seconds", 3600) or 3600)
    next_eta = None
    if mode == "binance_sim" and last_bar:
        next_eta = max(0.0, float(last_bar) + bar_sec - wall)
    saved_at = float(getattr(session, "saved_at", 0) or 0)
    health = getattr(session, "health", {}) or {}
    return {
        "process_started_at": started,
        "boot_started_at": boot,
        "ready_at": ready,
        "uptime_sec": max(0.0, wall - started) if started else 0.0,
        "ready_sec": max(0.0, wall - ready) if ready else 0.0,
        "last_poll_at": last_poll,
        "last_poll_ago_sec": max(0.0, wall - last_poll) if last_poll else None,
        "last_closed_bar_at": float(last_bar or 0),
        "next_bar_eta_sec": next_eta,
        "universe_at": float(getattr(session, "universe_ts", 0) or 0),
        "saved_at": saved_at,
        "restored": bool(health.get("restored")),
        "wall_now": wall,
        "bar_seconds": bar_sec,
        "mode": mode,
    }


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
