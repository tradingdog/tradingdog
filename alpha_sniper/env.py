from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path | None = None) -> None:
    """把 .env 读进 os.environ。已存在的环境变量不覆盖。"""
    path = path or Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def binance_keys() -> tuple[str, str]:
    load_env()
    return os.environ.get("BINANCE_API_KEY", "").strip(), os.environ.get("BINANCE_API_SECRET", "").strip()


def keys_configured() -> bool:
    key, secret = binance_keys()
    return bool(key and secret)
