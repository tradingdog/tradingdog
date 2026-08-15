from __future__ import annotations

import json
from pathlib import Path

from .config import SniperConfig
from .session import LiveSession
from .snapshot import build_snapshot


KEEP_HUNT = (
    "symbol",
    "tier",
    "narrative",
    "is_alpha",
    "venue_zh",
    "coiled",
    "silence",
    "armed",
    "possibility",
    "crowding",
    "exit_liquidity",
    "family_lamps",
    "wait",
)


def compact(snap: dict) -> dict:
    return {
        "day": snap["day"],
        "horizon_days": snap["horizon_days"],
        "state": snap["state"],
        "state_zh": snap["state_zh"],
        "narration": snap["narration"],
        "finished": snap["finished"],
        "running": False,
        "speed": 8,
        "live": False,
        "mode": "replay",
        "account": snap["account"],
        "risk": {
            "regime_zh": snap["risk"]["regime_zh"],
            "btc_ret_24h": snap["risk"]["btc_ret_24h"],
            "gates": snap["risk"]["gates"],
            "open_slots_used": snap["risk"]["open_slots_used"],
            "max_concurrent": snap["risk"]["max_concurrent"],
        },
        "theses": [
            {k: t[k] for k in t if k not in {"hypothesis"}}
            for t in snap["theses"]
        ],
        "closed": [
            {k: t[k] for k in ("symbol", "side", "side_zh", "ret", "pnl", "exit_reason", "families_zh")}
            for t in snap["closed"][-8:]
        ],
        "hunt": [{k: r[k] for k in KEEP_HUNT} for r in snap["hunt"]],
        "journal": [
            {k: e[k] for k in ("day", "kind_zh", "symbol", "detail")}
            for e in snap["journal"][-16:]
        ],
        "near_misses": snap["near_misses"][-8:],
        "skips": snap["skips"],
        "script": snap["script"],
        "eq": {"t": snap["day"], "e": snap["account"]["equity"], "c": snap["account"]["cash"], "v": snap["account"]["vault"]},
    }


def export_replay(path: Path | None = None, days: int = 36, seed: int = 42, every: int = 12) -> Path:
    path = path or Path(__file__).resolve().parent / "webui" / "replay.json"
    session = LiveSession(SniperConfig(paper_days=days, seed=seed))
    frames: list[dict] = []
    last_journal = 0
    last_open = ()
    ticks = 0
    while not session.finished:
        session.tick(every)
        ticks += 1
        snap = build_snapshot(session)
        sig = (len(session.engine.journal), tuple(sorted(session.engine.book.open)))
        interesting = sig[0] != last_journal or sig[1] != last_open
        last_journal, last_open = sig
        if interesting or ticks == 1 or session.finished or ticks % 4 == 0:
            frames.append(compact(snap))
    payload = {
        "version": 1,
        "note": "纸上重放。任意浏览器打开即可，不需要本机跑服务。",
        "frames": frames,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


if __name__ == "__main__":
    out = export_replay()
    print(out, out.stat().st_size)
