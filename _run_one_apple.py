# -*- coding: utf-8 -*-
"""Run Playlist main.py for a single Apple account email file (staggered multi-open)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import main as m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email-file", required=True, help="single-account apple email txt")
    ap.add_argument("--apple-login-mode", default="auto", choices=["auto", "manual"])
    ap.add_argument("--apple-max-albums", type=int, default=None)
    ap.add_argument("--Count", type=int, default=m.DEFAULT_ALBUM_COUNT)
    args = ap.parse_args()

    email_path = Path(args.email_file)
    if not email_path.is_absolute():
        email_path = ROOT / email_path
    if not email_path.exists():
        raise SystemExit(f"missing email file: {email_path}")

    m.APPLE_EMAIL_FILE = str(email_path)
    m.APPLE_LOGIN_MODE = args.apple_login_mode

    ns = argparse.Namespace(
        Platform="A",
        Count=args.Count,
        tidal=False,
        track_min=m.APPLE_TRACK_COUNT_MIN,
        track_max=m.APPLE_TRACK_COUNT_MAX,
        tidal_delete=False,
        tidal_login_mode="auto",
        apple_max_albums=args.apple_max_albums,
        apple_login_mode=args.apple_login_mode,
    )

    accounts = m.load_apple_accounts()
    print(f"single-run file={email_path.name} accounts={len(accounts)}")
    for i, acc in enumerate(accounts):
        sf = acc.get("storefront") or m.apple_region_to_storefront(acc.get("region"))
        print(f"  [{i+1}] {acc['email']} /{sf}/")
    if len(accounts) != 1:
        raise SystemExit("expected exactly 1 account in email file")

    ok = m.run_apple_for_single_account(accounts[0], 0, 1, ROOT, ns)
    print("SINGLE_DONE", accounts[0]["email"], "ok=" + str(bool(ok)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
