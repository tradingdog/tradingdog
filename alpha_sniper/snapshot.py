from __future__ import annotations

from math import log

from .types import Thesis


FAMILY_ZH = {
    "microstructure": "微观",
    "catalyst": "催化剂",
    "positioning": "持仓",
    "narrative": "叙事",
    "calendar": "日历",
}

SENSOR_ZH = {
    "volume_vacuum": "量能真空",
    "silence_break": "沉寂打破",
    "listing_catalyst": "上币",
    "informed_flow": "知情流",
    "exchange_inflow": "兑所充币",
    "unlock_calendar": "解锁",
    "weekend_vacuum": "周末真空",
    "alpha_new_listing": "Alpha 上币",
    "narrative_lag": "叙事滞后",
    "narrative_dump": "板块同崩",
    "aggressive_tape": "单边磁带",
}

SKIP_ZH = {
    "halted": "日亏熔断，今日只许平仓",
    "cooldown": "刚亏过，冷却中，禁止报复",
    "max_concurrent": "命题名额已满，先管好手里的",
    "btc_stress": "BTC 大跌，禁止新开山寨多",
    "no_cash": "可交易现金不够",
    "dust": "算出来的仓位太小，放弃",
}

VENUE_ZH = {"spot": "现货", "futures_1x": "1x 合约", "alpha": "Alpha"}
SIDE_ZH = {"long": "做多", "short": "做空"}
REGIME_ZH = {"risk_on": "风险开", "chop": "震荡", "btc_stress": "BTC 承压"}
STATE_ZH = {"SQUAT": "蹲点", "ARMED": "埋伏就绪", "IN_THESIS": "命题中"}

PAPER_SCRIPT = [
    {"day": 5.0, "symbol": "COILUSDT", "title": "缩簧后上币", "hint": "应预先埋伏，点火做多 Alpha"},
    {"day": 8.0, "symbol": "FAKEUSDT", "title": "单独放量", "hint": "不足三族，应忽略"},
    {"day": 12.0, "symbol": "DUMPUSDT", "title": "抛物线出货", "hint": "解锁+充币+卖盘，1x 空"},
    {"day": 18.4, "symbol": "LAGUSDT", "title": "叙事滞后", "hint": "不追龙头，买还没动的"},
    {"day": 20.0, "symbol": "THINUSDT", "title": "薄盘幻象", "hint": "没退出通道，应拒绝"},
    {"day": 24.2, "symbol": "STRESSUSDT", "title": "BTC 压力日", "hint": "禁止新开多"},
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
        "mode": "paper",
        "live": False,
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
                "kind_zh": {"open": "开火", "close": "离场", "skip": "拒绝"}.get(e.kind, e.kind),
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
        f"赌 {t.symbol} 走出非对称{way}（{ch}）。"
        f"依据：{fams} 在沉寂后同时亮起。"
        f"若价格回到 {t.invalidation:.6g}，或时间耗尽仍无推进，假说死亡，立刻走。"
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
            wait = "三族已齐，看门控"
        elif st.armed:
            wait = f"弹簧已压紧，还差 {gap} 族"
        elif st.coiled_score >= 0.28:
            wait = "正在压缩，继续蹲"
        else:
            wait = "还没进入埋伏表"
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
            "label": "杠杆硬顶 1x",
            "detail": "不会用 5x 去赌倍数",
        },
        {
            "id": "btc",
            "ok": regime != "btc_stress",
            "label": "BTC 体制",
            "detail": "大跌时关掉山寨新多" if regime == "btc_stress" else "允许打猎",
        },
        {
            "id": "halt",
            "ok": now >= acc.halted_until,
            "label": "日亏熔断",
            "detail": "已触发，停机" if now < acc.halted_until else "未触发",
        },
        {
            "id": "cool",
            "ok": now >= acc.cooldown_until,
            "label": "亏损冷却",
            "detail": "冷却中" if now < acc.cooldown_until else "可开火",
        },
        {
            "id": "slots",
            "ok": engine.book.open_count() < engine.config.max_concurrent,
            "label": f"命题名额 {engine.book.open_count()}/{engine.config.max_concurrent}",
            "detail": "空出来才开下一枪",
        },
        {
            "id": "moon",
            "ok": now >= acc.moonshot_ban_until,
            "label": "月亮仓",
            "detail": "大赢后 48h 禁止放大" if now < acc.moonshot_ban_until else "极强共振才允许放大",
        },
    ]


def _narrate(state, open_theses, armed, regime, engine, now, marks) -> str:
    day = now / 86400.0
    if regime == "btc_stress":
        head = "BTC 正在深跌，新的山寨多单被锁死。"
    else:
        head = ""
    if state == "IN_THESIS":
        bits = []
        for t in open_theses:
            px = marks.get(t.symbol, t.entry)
            raw = (px / t.entry - 1.0) if t.entry else 0.0
            ret = raw if t.side == "long" else -raw
            bits.append(f"{t.symbol} {SIDE_ZH[t.side]} {ret:+.0%}")
        return head + "命题进行中：" + "；".join(bits) + "。假说没死就让它跑，死了立刻走。"
    if state == "ARMED":
        names = "、".join(armed[:4])
        return head + f"埋伏已锁定 {names}。预计算单写好了，点火后不会现场改主意。"
    last_close = engine.book.closed[-1].exit_ts if engine.book.closed else 0.0
    quiet_h = max(0.0, (now - last_close) / 3600.0) if last_close else day * 24.0
    n_coil = sum(1 for s in engine.coiled.states.values() if s.armed)
    return head + f"空仓蹲点约 {quiet_h:.0f} 小时。猎场里 {n_coil} 只缩簧在表上。没有三族共振，就什么都不做。"


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
