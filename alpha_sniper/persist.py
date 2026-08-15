from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, fields
from pathlib import Path

from .engine import JournalEvent
from .thesis import Thesis, set_id_counter
from .types import Account, FourScores

STATE_DIR = Path(__file__).resolve().parent / "data"
STATE_PATH = STATE_DIR / "live_state.json"


def clear_state() -> None:
    try:
        STATE_PATH.unlink(missing_ok=True)
    except TypeError:
        if STATE_PATH.exists():
            STATE_PATH.unlink()


def load_state() -> dict | None:
    if not STATE_PATH.is_file():
        return None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_state(session) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    engine = session.engine
    payload = {
        "version": 1,
        "saved_at": time.time(),
        "allow_new": bool(session.allow_new),
        "running": bool(session.running),
        "blocked": sorted(session.blocked),
        "watch": list(session.watch),
        "last_bar_ts": {k: float(v) for k, v in session._last_bar_ts.items()},
        "account": asdict(engine.account),
        "journal": [asdict(e) for e in engine.journal[-240:]],
        "near_misses": list(engine.near_misses[-80:]),
        "skips": list(engine.skips[-240:]),
        "equity_curve": list(session.equity_curve[-400:]),
        "open": [_thesis_dump(t) for t in engine.book.open.values()],
        "closed": [_thesis_dump(t) for t in engine.book.closed[-80:]],
        "scan": dict(getattr(engine, "scan", {}) or {}),
        "marks": {k: float(v) for k, v in engine.venue.marks.items()},
        "health": dict(getattr(session, "health", {}) or {}),
    }
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def apply_state(session, payload: dict) -> None:
    engine = session.engine
    acc = payload.get("account") or {}
    allowed = {f.name for f in fields(Account)}
    engine.account = Account(**{k: acc[k] for k in allowed if k in acc})
    engine.journal = [
        JournalEvent(float(e["ts"]), str(e["kind"]), str(e["symbol"]), str(e.get("detail") or ""))
        for e in payload.get("journal") or []
        if isinstance(e, dict) and "ts" in e
    ]
    engine.near_misses = [m for m in (payload.get("near_misses") or []) if isinstance(m, dict)]
    engine.skips = []
    for item in payload.get("skips") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            engine.skips.append((str(item[0]), str(item[1])))
    engine.scan = dict(payload.get("scan") or engine.scan)
    engine.book.open.clear()
    engine.book.closed = []
    max_id = 1
    for raw in payload.get("closed") or []:
        t = _thesis_load(raw)
        if t is None:
            continue
        engine.book.closed.append(t)
        max_id = max(max_id, _id_num(t.id) + 1)
    for raw in payload.get("open") or []:
        t = _thesis_load(raw)
        if t is None:
            continue
        engine.book.open[t.id] = t
        max_id = max(max_id, _id_num(t.id) + 1)
    set_id_counter(max_id)
    marks = payload.get("marks") or {}
    if isinstance(marks, dict):
        for sym, px in marks.items():
            try:
                engine.venue.on_price(str(sym), float(px))
            except (TypeError, ValueError):
                continue
    session.equity_curve = [p for p in (payload.get("equity_curve") or []) if isinstance(p, dict)]
    session.blocked = {str(s).upper() for s in (payload.get("blocked") or []) if s}
    session.saved_at = float(payload.get("saved_at") or time.time())
    if "allow_new" in payload:
        session.allow_new = bool(payload.get("allow_new"))
    if "running" in payload:
        session.running = bool(payload.get("running"))


def _thesis_dump(t: Thesis) -> dict:
    return asdict(t)


def _thesis_load(raw) -> Thesis | None:
    if not isinstance(raw, dict):
        return None
    data = dict(raw)
    scores = data.get("scores")
    if isinstance(scores, dict):
        try:
            data["scores"] = FourScores(
                possibility=float(scores.get("possibility") or 0),
                ignition=float(scores.get("ignition") or 0),
                crowding=float(scores.get("crowding") or 0),
                exit_liquidity=float(scores.get("exit_liquidity") or 0),
            )
        except (TypeError, ValueError):
            data["scores"] = None
    fams = data.get("families")
    if isinstance(fams, list):
        data["families"] = tuple(fams)
    allowed = {f.name for f in fields(Thesis)}
    try:
        return Thesis(**{k: data[k] for k in allowed if k in data})
    except TypeError:
        return None


def _id_num(thesis_id: str) -> int:
    raw = str(thesis_id or "").lstrip("T")
    try:
        return int(raw)
    except ValueError:
        return 0
