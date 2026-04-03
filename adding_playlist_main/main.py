"""
Playlist 多平台主入口（新架构）
历史写入采用成功后提交策略，失败或中断不写入。
"""

import argparse
import time
from pathlib import Path

from config import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_ALBUM_COUNT,
    DEFAULT_PLATFORM,
    TIDAL_MODE,
    UPDATE_NOTES,
)
from platforms import (
    load_tidal_accounts,
    process_apple_music_playlist,
    process_qobuz_playlist,
    run_tidal_delete_for_single_account,
    run_tidal_for_single_account,
)
from utils import mark_playlist_name_used, setup_logging
from utils.logging_setup import print
from utils.playlist_core import append_history_tx_log, commit_prepared_history, prepare_playlist_output


def build_parser():
    parser = argparse.ArgumentParser(description="随机生成播放列表")
    parser.add_argument(
        "--Platform",
        choices=["A", "T", "Q"],
        default=DEFAULT_PLATFORM,
        help="选择平台: A=Apple, T=Tidal, Q=Qobuz",
    )
    parser.add_argument(
        "--Count",
        type=int,
        default=DEFAULT_ALBUM_COUNT,
        help=f"主库抽取的专辑数量，默认 {DEFAULT_ALBUM_COUNT}",
    )
    parser.add_argument(
        "--tidal",
        action="store_true",
        help="启用 Tidal 播放列表自动添加功能",
    )
    parser.add_argument(
        "--tidal-delete",
        action="store_true",
        help="启用 Tidal 删除模式：从所有播放列表中删除指定专辑歌曲",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Playlist 自动化工具 v{APP_VERSION}",
    )
    return parser


def print_banner():
    print(f"Playlist 自动化工具 v{APP_VERSION}")
    print(f"更新内容：{UPDATE_NOTES}")
    print("-" * 50)


def run_single_platform(platform: str, count: int, base_dir: Path):
    txt_path, final_list, pending_history = prepare_playlist_output(base_dir, platform, count)
    print(f"✓ 已生成专辑清单: {txt_path.name}")
    print(f"✓ 本次共生成 {len(final_list)} 项")
    append_history_tx_log("prepare", platform, txt_file=txt_path.name, note=f"items={len(final_list)}")

    if platform == "A":
        try:
            success, playlist_name = process_apple_music_playlist(txt_path)
        except KeyboardInterrupt:
            append_history_tx_log("discard", platform, txt_file=txt_path.name, status="interrupted", note="user_interrupt")
            raise
        if success:
            commit_prepared_history(pending_history)
            append_history_tx_log("commit", platform, txt_file=txt_path.name, note="apple_success")
            if playlist_name:
                mark_playlist_name_used(playlist_name)
        else:
            append_history_tx_log("discard", platform, txt_file=txt_path.name, status="failed", note="apple_failed")
        return success

    if platform == "Q":
        try:
            success, playlist_name = process_qobuz_playlist(txt_path)
        except KeyboardInterrupt:
            append_history_tx_log("discard", platform, txt_file=txt_path.name, status="interrupted", note="user_interrupt")
            raise
        if success:
            commit_prepared_history(pending_history)
            append_history_tx_log("commit", platform, txt_file=txt_path.name, note="qobuz_success")
            if playlist_name:
                mark_playlist_name_used(playlist_name)
        else:
            append_history_tx_log("discard", platform, txt_file=txt_path.name, status="failed", note="qobuz_failed")
        return success

    return False


def run_tidal_multi_accounts(count: int, base_dir: Path, delete_mode: bool):
    accounts = load_tidal_accounts()
    if not accounts:
        print("✗ 未找到 Tidal 账号")
        return False

    print(f"✓ 找到 {len(accounts)} 个 Tidal 账号")
    for idx, account in enumerate(accounts, start=1):
        print(f"  [{idx}] {account}")

    if delete_mode:
        success_count = 0
        for idx, account in enumerate(accounts, start=1):
            print(f"\n处理账号 [{idx}/{len(accounts)}]: {account}")
            success = run_tidal_delete_for_single_account(account)
            if success:
                success_count += 1
            if idx < len(accounts):
                time.sleep(3)

        print(f"\nTidal 多账号删除处理完成：成功 {success_count}/{len(accounts)}")
        return success_count > 0

    success_count = 0
    for idx, account in enumerate(accounts, start=1):
        print(f"\n处理账号 [{idx}/{len(accounts)}]: {account}")
        txt_path, final_list, pending_history = prepare_playlist_output(base_dir, "T", count)
        print(f"✓ 账号专用清单: {txt_path.name}，共 {len(final_list)} 项")
        append_history_tx_log("prepare", "T", account=account, txt_file=txt_path.name, note=f"items={len(final_list)}")

        try:
            success = run_tidal_for_single_account(account, txt_path)
        except KeyboardInterrupt:
            append_history_tx_log("discard", "T", account=account, txt_file=txt_path.name, status="interrupted", note="user_interrupt")
            raise

        if success:
            commit_prepared_history(pending_history)
            append_history_tx_log("commit", "T", account=account, txt_file=txt_path.name, note="tidal_account_success")
            success_count += 1
        else:
            print(f"⚠ 账号 {account} 失败，本账号历史不写入")
            append_history_tx_log("discard", "T", account=account, txt_file=txt_path.name, status="failed", note="tidal_account_failed")

        if idx < len(accounts):
            time.sleep(3)

    print(f"\nTidal 多账号处理完成：成功 {success_count}/{len(accounts)}")
    return success_count > 0


def main():
    parser = build_parser()
    args = parser.parse_args()

    log_mode = "tidal_delete" if args.tidal_delete else "run"
    log_file = setup_logging(platform=args.Platform, mode=log_mode)

    print_banner()
    print(f"日志文件: {Path(log_file).name}")
    start_time = time.time()
    base_dir = Path(__file__).parent

    if args.Platform == "T" and not args.tidal and not args.tidal_delete:
        args.tidal = True
    if args.Platform == "T" and TIDAL_MODE == 2:
        args.tidal_delete = True

    success = False
    try:
        if args.Platform == "T" and (args.tidal or args.tidal_delete):
            success = run_tidal_multi_accounts(args.Count, base_dir, args.tidal_delete)
        else:
            success = run_single_platform(args.Platform, args.Count, base_dir)
    except KeyboardInterrupt:
        append_history_tx_log("discard", args.Platform, status="interrupted", note="main_interrupt")
        print("\n用户中断执行，当前未完成平台历史不会写入")
    except Exception as exc:
        print(f"程序执行异常: {exc}")
        raise
    finally:
        elapsed = time.time() - start_time
        if success:
            print(f"✓ 全部流程完成，耗时 {elapsed:.1f} 秒")
        else:
            print(f"✗ 流程未完全成功，耗时 {elapsed:.1f} 秒")


if __name__ == "__main__":
    main()