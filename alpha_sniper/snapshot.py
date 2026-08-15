from __future__ import annotations

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

VENUE_ZH = {"spot": "现货", "futures_1x": "1x 合约", "alpha": "Alpha"}
SIDE_ZH = {"long": "做多", "short": "做空"}
REGIME_ZH = {"risk_on": "偏多", "chop": "震荡", "btc_stress": "BTC 大跌"}
STATE_ZH = {"SQUAT": "空仓", "ARMED": "已盯上", "IN_THESIS": "持仓中"}

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
        "theses": [_thesis_view(t, marks, now) for t in open_theses],
        "closed": [_thesis_view(t, marks, now) for t in engine.book.closed[-12:]],
        "hunt": _hunt_rows(engine, now),
        "pulses": [_pulse_view(p) for p in engine.recent_pulses[-40:]],
        "journal": [
            {
                "ts": e.ts,
                "day": round(e.ts / 86400.0, 3),
                "kind": e.kind,
                "kind_zh": {"open": "开仓", "close": "平仓", "skip": "过滤"}.get(e.kind, e.kind),
                "symbol": e.symbol,
                "detail": e.detail,
            }
            for e in engine.journal[-50:]
        ],
        "near_misses": [
            {
                **m,
                "day": round(m["ts"] / 86400.0, 3),
                "side_zh": SIDE_ZH.get(m.get("side", ""), ""),
                "families_zh": [FAMILY_ZH.get(f, f) for f in m.get("families", [])],
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
    }


def _thesis_view(t: Thesis, marks: dict[str, float], now: float) -> dict:
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
    return {
        "id": t.id,
        "symbol": t.symbol,
        "side": t.side,
        "side_zh": SIDE_ZH[t.side],
        "venue": t.venue,
        "venue_zh": VENUE_ZH.get(t.venue, t.venue),
        "hypothesis": t.hypothesis,
        "plain": _plain_thesis(t),
        "entry": t.entry,
        "mark": px,
        "invalidation": t.invalidation,
        "notional": t.notional,
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
        "hours_left": round(remain_h, 2),
        "opened_day": round(t.opened_ts / 86400.0, 3),
    }


def _plain_thesis(t: Thesis) -> str:
    fams = "、".join(FAMILY_ZH.get(f, f) for f in t.families) or "未知证据"
    way = "大涨" if t.side == "long" else "大跌"
    ch = VENUE_ZH.get(t.venue, t.venue)
    return (
        f"{ch}{SIDE_ZH[t.side]} {t.symbol}，看{way}。"
        f"开仓理由：{fams} 同时出现。"
        f"跌破/升破 {t.invalidation:.6g} 或超时没走出幅度，就平掉。"
    )


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
            wait = "三类信号已齐，等风控放行"
        elif st.armed:
            wait = f"横盘缩量，还差 {gap} 类信号"
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
        names = "、".join(armed[:4])
        return head + f"正在盯 {names}。结构已经压缩，再出现两类以上信号才会开仓。"
    last_close = engine.book.closed[-1].exit_ts if engine.book.closed else 0.0
    quiet_h = max(0.0, (now - last_close) / 3600.0) if last_close else 0.0
    n_coil = sum(1 for s in engine.coiled.states.values() if s.armed)
    if quiet_h >= 1:
        wait = f"空仓已等 {quiet_h:.0f} 小时。"
    else:
        wait = "现在空仓。"
    return head + f"{wait}监控里有 {n_coil} 个横盘缩量的币。没有三类独立信号同时出现，就不开仓。"


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


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))
