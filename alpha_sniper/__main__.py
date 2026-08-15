from __future__ import annotations

import argparse
import json
import sys

from .config import SniperConfig
from .engine import run_paper


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alpha Sniper：币安非对称机会猎手（默认纸上）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("design", help="打印框架要点")
    p = sub.add_parser("paper", help="跑纸上宇宙（种有大涨大跌事件）")
    p.add_argument("--days", type=int, default=40)
    p.add_argument("--seed", type=int, default=42)
    ui = sub.add_parser("ui", help="打开人类观察台（纸上演练，实时看板）")
    ui.add_argument("--host", default="0.0.0.0")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--days", type=int, default=36)
    ui.add_argument("--seed", type=int, default=42)
    sub.add_parser("export", help="导出纸上重放，供任意浏览器打开观察台")
    args = parser.parse_args(argv)

    if args.cmd == "export":
        from .export_replay import export_replay

        path = export_replay()
        print(f"已写入 {path} ({path.stat().st_size} bytes)")
        return 0

    if args.cmd == "ui":
        from .web import run_ui

        run_ui(host=args.host, port=args.port, days=args.days, seed=args.seed)
        return 0

    if args.cmd == "design":
        from pathlib import Path

        text = Path(__file__).with_name("DESIGN.md").read_text(encoding="utf-8")
        sys.stdout.write(text[:4000] + "\n… 全文见 alpha_sniper/DESIGN.md\n")
        return 0

    cfg = SniperConfig(paper_days=args.days, seed=args.seed)
    eng = run_paper(cfg)
    closed = [
        {
            "symbol": t.symbol,
            "side": t.side,
            "venue": t.venue,
            "pnl": round(t.realized_pnl, 2),
            "ret": round(t.realized_pnl / t.notional, 4) if t.notional else 0,
            "reason": t.exit_reason,
            "families": list(t.families),
        }
        for t in eng.book.closed
    ]
    skip_reasons = {}
    for _sym, why in eng.skips:
        skip_reasons[why] = skip_reasons.get(why, 0) + 1
    out = {
        "starting": cfg.starting_usdt,
        "ending_equity": round(eng.equity(), 2),
        "cash": round(eng.account.cash, 2),
        "vault": round(eng.account.vault, 2),
        "theses": closed,
        "opens": [e.detail[:120] for e in eng.journal if e.kind == "open"],
        "skip_reasons": skip_reasons,
        "note": "纸上结果只验证门控逻辑，不是 100x 承诺。",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
