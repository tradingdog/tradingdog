# -*- coding: utf-8 -*-
"""Apple 加歌：单路 / 多路逐增（同地区多账号）。

用法示例：
  # 只跑一路（apple_email.txt 里全部账号串行）
  python run_apple_staggered.py --mode single

  # 多路逐增：先开第 1 路，确认已开始加歌后再开第 2 路，再开第 3 路…
  python run_apple_staggered.py --mode stagger --max-routes 3

  # 可调条数（烟测）
  python run_apple_staggered.py --mode stagger --max-routes 2 --apple-max-albums 3 --Count 3

铁律：
  - 同一地区账号才适合多路逐增（共用同一狗急节点 / 店面）。
  - 禁止一瞬间 ThreadPool 齐开；必须等上一路出现「开始加歌」证据后再开下一路。
  - 启动前清空 HTTP_PROXY/HTTPS_PROXY（否则 chromedriver 连 localhost 会 RemoteDisconnected）；
    狗急「全局」仍走系统代理，不影响 Chrome 上网。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 上一路「已开始加歌」判据（任一命中即可开下一路）
ADD_STARTED_PATTERNS = (
    re.compile(r"^\s*\[\d+/\d+\]\s*处理", re.M),
    re.compile(r"已添加第\s*\d+", re.M),
    re.compile(r"第一张专辑，创建播放列表"),
    re.compile(r"添加\s*\d+\s*首歌曲到播放列表"),
)


def clear_selenium_proxy_env() -> None:
    for k in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        os.environ.pop(k, None)
    os.environ["NO_PROXY"] = "*"
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")


def parse_accounts(email_file: Path) -> list[dict]:
    text = email_file.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip())
    accounts = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        accounts.append(
            {
                "email": lines[0],
                "password": lines[1],
                "region": lines[2] if len(lines) >= 3 else "",
            }
        )
    return accounts


def write_one_account_file(acc: dict, path: Path) -> Path:
    region = acc.get("region") or ""
    body = f"{acc['email']}\n{acc['password']}\n"
    if region:
        body += f"{region}\n"
    path.write_text(body, encoding="utf-8")
    return path


def build_one_cmd(email_file: Path, args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "_run_one_apple.py"),
        "--email-file",
        str(email_file),
        "--apple-login-mode",
        args.apple_login_mode,
        "--Count",
        str(args.Count),
    ]
    if args.apple_max_albums is not None:
        cmd += ["--apple-max-albums", str(args.apple_max_albums)]
    return cmd


def log_has_add_started(log_path: Path) -> bool:
    if not log_path.exists():
        return False
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(p.search(text) for p in ADD_STARTED_PATTERNS)


def run_single(args: argparse.Namespace, accounts: list[dict]) -> int:
    """单路：整份 apple_email.txt 交给 main.py 串行。"""
    clear_selenium_proxy_env()
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "main.py"),
        "--Platform",
        "A",
        "--apple-login-mode",
        args.apple_login_mode,
        "--Count",
        str(args.Count),
    ]
    if args.apple_max_albums is not None:
        cmd += ["--apple-max-albums", str(args.apple_max_albums)]
    print(f"[single] accounts={len(accounts)} cmd={' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def run_stagger(args: argparse.Namespace, accounts: list[dict]) -> int:
    """多路逐增：同地区多账号，一路确认加歌后再开下一路。"""
    clear_selenium_proxy_env()
    max_routes = max(1, min(args.max_routes, len(accounts)))
    jobs_dir = ROOT / ".stagger_jobs"
    jobs_dir.mkdir(exist_ok=True)
    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)

    procs: list[subprocess.Popen] = []
    log_paths: list[Path] = []
    stamp = time.strftime("%Y%m%d_%H%M%S")

    print(
        f"[stagger] total_accounts={len(accounts)} max_routes={max_routes} "
        f"Count={args.Count} apple_max_albums={args.apple_max_albums}",
        flush=True,
    )

    for i, acc in enumerate(accounts[:max_routes]):
        email_file = write_one_account_file(acc, jobs_dir / f"account_{i+1}.txt")
        log_path = logs_dir / f"stagger_{stamp}_r{i+1}_{acc['email'].split('@')[0]}.log"
        log_paths.append(log_path)
        cmd = build_one_cmd(email_file, args)
        print(f"\n>>> open route {i+1}/{max_routes}: {acc['email']}", flush=True)
        print(f"    log={log_path.name}", flush=True)
        lf = open(log_path, "w", encoding="utf-8", errors="replace")
        p = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=lf,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
        p._log_file = lf  # type: ignore[attr-defined]
        procs.append(p)

        if i + 1 >= max_routes:
            break

        # 等本路开始加歌，再开下一路
        deadline = time.time() + args.wait_add_sec
        started = False
        while time.time() < deadline:
            if p.poll() is not None:
                print(
                    f"!!! route {i+1} exited early code={p.returncode}；停止继续开路",
                    flush=True,
                )
                break
            if log_has_add_started(log_path):
                started = True
                print(f"✓ route {i+1} 已开始加歌 → 准备开下一路", flush=True)
                break
            time.sleep(args.poll_sec)
        else:
            print(
                f"!!! route {i+1} 等待 {args.wait_add_sec}s 仍未见加歌证据；停止继续开路",
                flush=True,
            )

        if not started:
            break

        time.sleep(args.gap_sec)

    print("\n[stagger] 等待已开各路结束…", flush=True)
    rc = 0
    for i, p in enumerate(procs):
        code = p.wait()
        try:
            p._log_file.close()  # type: ignore[attr-defined]
        except Exception:
            pass
        print(f"route {i+1} exit={code} log={log_paths[i].name}", flush=True)
        if code != 0:
            rc = code or 1

    # 若账号多于 max_routes，提示剩余需另开
    if len(accounts) > max_routes:
        left = [a["email"] for a in accounts[max_routes:]]
        print(f"[stagger] 未开的账号（超过 --max-routes）: {left}", flush=True)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="Apple 加歌：single / stagger 多路逐增")
    ap.add_argument(
        "--mode",
        choices=("single", "stagger"),
        default="stagger",
        help="single=main.py 串行一路；stagger=多路逐增（默认）",
    )
    ap.add_argument(
        "--email-file",
        default=str(ROOT / "apple_email.txt"),
        help="多账号文件（空行分隔；第三行地区）",
    )
    ap.add_argument(
        "--max-routes",
        type=int,
        default=3,
        help="stagger 最多同时开几路（逐增到此上限）",
    )
    ap.add_argument("--Count", type=int, default=18, help="主库抽取专辑数，默认 18")
    ap.add_argument(
        "--apple-max-albums",
        type=int,
        default=None,
        help="每账号最多处理专辑数；默认全量。烟测才设",
    )
    ap.add_argument("--apple-login-mode", choices=("auto", "manual"), default="auto")
    ap.add_argument(
        "--wait-add-sec",
        type=int,
        default=600,
        help="开下一路前，等待本路出现加歌证据的最长时间（秒）",
    )
    ap.add_argument("--poll-sec", type=int, default=8, help="轮询日志间隔（秒）")
    ap.add_argument(
        "--gap-sec",
        type=int,
        default=5,
        help="确认加歌后到开下一路的间隔（秒）",
    )
    args = ap.parse_args()

    email_file = Path(args.email_file)
    if not email_file.is_absolute():
        email_file = ROOT / email_file
    if not email_file.exists():
        print(f"缺少账号文件: {email_file}", file=sys.stderr)
        return 2

    accounts = parse_accounts(email_file)
    if not accounts:
        print("账号文件为空", file=sys.stderr)
        return 2

    regions = {a.get("region") or "" for a in accounts}
    if args.mode == "stagger" and len(regions) > 1:
        print(
            f"警告：账号地区不一致 {regions}；多路逐增只适用于同一地区。继续跑，但请确认 VPN。",
            flush=True,
        )

    if args.mode == "single":
        return run_single(args, accounts)
    return run_stagger(args, accounts)


if __name__ == "__main__":
    raise SystemExit(main())
