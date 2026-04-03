"""
播放列表生成与历史记录的共享逻辑
"""

import json
import random
import re
import secrets
from datetime import datetime
from pathlib import Path

from config import (
    HISTORY_FILE,
    HISTORY_TX_LOG_FILE,
    MAX_RECENT_COMBINATIONS,
    MIN_COMBINATION_DIFF,
    RECENT_APPEARANCE_WINDOW,
    MAX_RECENT_FREQUENCY,
    COOLDOWN_WINDOW,
    WEIGHT_DECAY_POWER,
    PLAYLIST_NAMES_FILE,
    PLAYLIST_HISTORY_FILE,
    OTHER_ARTISTS_FILE,
    PLATFORM_FILES,
)


def load_json_data(path: Path) -> list[dict]:
    """读取 JSON 数据，返回包含 artist 和 albums 的列表。"""
    if not path.exists():
        raise FileNotFoundError(f"未找到文件：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def flatten_albums(data: list[dict]) -> list[str]:
    """将数据展平为 艺人 - 专辑 格式。"""
    flat_list = []
    for entry in data:
        artist = entry.get("artist", "Unknown")
        for album in entry.get("albums", []):
            flat_list.append(f"{artist} - {album}")
    return flat_list


def split_artist_album(item: str) -> tuple[str, str]:
    """将 艺人 - 专辑 拆分为艺人和专辑名。"""
    parts = item.split(" - ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "Unknown", item


def format_output_item(artist: str, album: str) -> str:
    """格式化输出项。"""
    return f'"艺人名={artist}", "专辑名={album}"'


def parse_album_list_from_txt(txt_path: Path) -> list[dict]:
    """从生成的 txt 文件中解析专辑列表。"""
    if not txt_path.exists():
        return []

    albums = []
    content = txt_path.read_text(encoding="utf-8")
    pattern = r'"艺人名=([^"]+)"\s*,\s*"专辑名=([^"]+)"'
    matches = re.findall(pattern, content)

    for artist, album in matches:
        albums.append({
            "artist_name": artist.strip(),
            "album_name": album.strip(),
        })

    return albums


def load_history() -> dict:
    history_path = Path(HISTORY_FILE)
    if not history_path.exists():
        return {}
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(history: dict) -> None:
    Path(HISTORY_FILE).write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def combination_similarity(comb1: set[str], comb2: set[str]) -> float:
    """计算两个组合的 Jaccard 相似度。"""
    if not comb1 or not comb2:
        return 0.0
    intersection = len(comb1 & comb2)
    union = len(comb1 | comb2)
    return intersection / union if union > 0 else 0.0


def calculate_recent_frequency(item: str, recent_combinations: list[set[str]]) -> float:
    """计算专辑在最近组合中的出现频率。"""
    if not recent_combinations:
        return 0.0
    window = (
        recent_combinations[-RECENT_APPEARANCE_WINDOW:]
        if len(recent_combinations) > RECENT_APPEARANCE_WINDOW
        else recent_combinations
    )
    appearances = sum(1 for combo in window if item in combo)
    return appearances / len(window) if window else 0.0


def is_in_cooldown(item: str, recent_combinations: list[set[str]]) -> bool:
    """检查专辑是否在冷却期内。"""
    if not recent_combinations:
        return False
    cooldown_window = (
        recent_combinations[-COOLDOWN_WINDOW:]
        if len(recent_combinations) > COOLDOWN_WINDOW
        else recent_combinations
    )
    return any(item in combo for combo in cooldown_window)


def weighted_sample(
    items: list[str],
    counts: dict[str, int],
    k: int,
    rng: secrets.SystemRandom,
    recent_combinations: list[set[str]] | None = None,
    unique_artist: bool = False,
) -> list[str]:
    """使用历史权重、冷却机制和艺人去重进行抽样。"""
    if recent_combinations is None:
        recent_combinations = []

    if unique_artist:
        artist_albums = {}
        for item in items:
            artist = item.split(" - ", 1)[0]
            artist_albums.setdefault(artist, []).append(item)
        items = [rng.choice(albums) for albums in artist_albums.values()]

    if len(items) <= k:
        return list(dict.fromkeys(items))

    picked = []
    all_counts = [counts.get(item, 0) for item in items]
    min_count = min(all_counts) if all_counts else 0
    max_count = max(all_counts) if all_counts else 0

    for _ in range(500):
        weights = []
        for item in items:
            count = counts.get(item, 0)
            base_weight = 1.0 / ((1 + count) ** WEIGHT_DECAY_POWER)

            if is_in_cooldown(item, recent_combinations):
                base_weight *= 0.001

            recent_freq = calculate_recent_frequency(item, recent_combinations)
            if recent_freq > MAX_RECENT_FREQUENCY:
                base_weight *= 0.001
            elif recent_freq > 0.2:
                base_weight *= 0.01
            elif recent_freq > 0.1:
                base_weight *= 0.1

            if max_count > 0 and count > min_count:
                relative_count = (count - min_count) / (max_count - min_count + 1)
                base_weight *= (1.0 - relative_count * 0.7)

            weights.append(max(base_weight, 1e-12))

        try:
            picked = []
            available = items.copy()
            for _ in range(k):
                if not available:
                    break
                available_weights = [weights[idx] for idx, value in enumerate(items) if value in available]
                total_weight = sum(available_weights)
                if total_weight < 1e-10:
                    picked.append(available.pop(rng.randrange(len(available))))
                else:
                    pick_index = rng.choices(range(len(available)), weights=available_weights, k=1)[0]
                    picked.append(available.pop(pick_index))

            picked = list(dict.fromkeys(picked))
            if len(picked) < k:
                remaining = [value for value in items if value not in picked]
                needed = k - len(picked)
                if len(remaining) >= needed:
                    picked += rng.sample(remaining, needed)
                else:
                    picked += remaining
        except (ValueError, IndexError):
            picked = rng.sample(items, k=min(k, len(items)))

        picked_set = set(picked)
        is_similar = False
        for recent in recent_combinations:
            similarity = combination_similarity(picked_set, recent)
            if similarity > (1.0 - MIN_COMBINATION_DIFF):
                is_similar = True
                break

        if not is_similar and len(recent_combinations) >= 3:
            recent_3 = recent_combinations[-3:]
            avg_similarity = sum(combination_similarity(picked_set, recent) for recent in recent_3) / len(recent_3)
            if avg_similarity > 0.5:
                is_similar = True

        if not is_similar:
            return picked

    return picked


def update_history(items: list[str], category: str, history: dict) -> None:
    """更新历史记录中的计数和组合。"""
    data = history.get(category, {"counts": {}, "all_combinations": []})
    if isinstance(data, dict) and "counts" not in data:
        data = {"counts": data, "all_combinations": []}
        history[category] = data

    counts = data.get("counts", {})
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    data["counts"] = counts

    all_combinations = data.get("all_combinations", [])
    all_combinations.append(list(set(items)))
    if len(all_combinations) > MAX_RECENT_COMBINATIONS:
        all_combinations = all_combinations[-MAX_RECENT_COMBINATIONS:]
    data["all_combinations"] = all_combinations
    history[category] = data


def get_category_history_data(category: str, history: dict) -> tuple[dict[str, int], list[set[str]]]:
    """获取指定分类的历史数据。"""
    data = history.get(category, {"counts": {}, "all_combinations": []})
    if isinstance(data, dict) and "counts" not in data:
        data = {"counts": data, "all_combinations": []}
    counts = data.get("counts", {})
    recent_combinations = [set(combo) for combo in data.get("all_combinations", [])]
    return counts, recent_combinations


def load_playlist_history() -> list[str]:
    """读取已使用的播放列表名称历史。"""
    history_path = Path(PLAYLIST_HISTORY_FILE)
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data.get("used_names", [])
    except Exception:
        return []


def save_playlist_history(used_names: list[str]) -> None:
    """保存播放列表名称历史。"""
    Path(PLAYLIST_HISTORY_FILE).write_text(
        json.dumps({"used_names": used_names}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_available_playlist_names() -> list[str]:
    """从 Playlist_name.txt 加载可用播放列表名称。"""
    names_path = Path(PLAYLIST_NAMES_FILE)
    if not names_path.exists():
        print(f"✗ 找不到播放列表名称文件: {PLAYLIST_NAMES_FILE}")
        return []

    names = []
    for line in names_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            match = re.match(r'^\d+\.\s*(.+)$', line)
            if match:
                names.append(match.group(1).strip())
            else:
                names.append(line)
    return names


def get_next_playlist_name() -> str | None:
    """获取下一个未使用的播放列表名称。"""
    all_names = load_available_playlist_names()
    used_names = load_playlist_history()
    for name in all_names:
        if name not in used_names:
            return name
    if all_names:
        print("⚠ 所有播放列表名称都已使用，将重置历史记录")
        save_playlist_history([])
        return all_names[0]
    return None


def mark_playlist_name_used(name: str) -> None:
    """标记播放列表名称已使用。"""
    used_names = load_playlist_history()
    if name not in used_names:
        used_names.append(name)
        save_playlist_history(used_names)


def generate_playlist_output(base_dir: Path, platform: str, count: int) -> tuple[Path, list[str]]:
    """生成输出 txt 文件并更新历史。"""
    main_artists_path = Path(PLATFORM_FILES[platform])
    other_artists_path = Path(OTHER_ARTISTS_FILE)

    main_items = flatten_albums(load_json_data(main_artists_path))
    other_items = flatten_albums(load_json_data(other_artists_path))

    history = load_history()
    rng = secrets.SystemRandom()

    other_counts, other_recent = get_category_history_data("Other", history)
    main_counts, main_recent = get_category_history_data(platform, history)

    part1 = weighted_sample(other_items, other_counts, 1, rng, other_recent, unique_artist=True)
    part2 = weighted_sample(main_items, main_counts, count, rng, main_recent, unique_artist=True)

    part1_artists = {item.split(" - ", 1)[0] for item in part1}
    remaining_other = [item for item in other_items if item.split(" - ", 1)[0] not in part1_artists]
    part3 = weighted_sample(remaining_other, other_counts, 4, rng, other_recent, unique_artist=True)

    final_list = part1 + part2 + part3

    update_history(part1 + part3, "Other", history)
    update_history(part2, platform, history)
    save_history(history)

    timestamp_suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    output_name = f"{platform}+{timestamp_suffix}.txt"
    output_path = base_dir / output_name

    output_lines = []
    for item in final_list:
        artist, album = split_artist_album(item)
        output_lines.append(format_output_item(artist, album))

    output_path.write_text("\n".join(output_lines), encoding="utf-8")
    return output_path, final_list


def prepare_playlist_output(base_dir: Path, platform: str, count: int) -> tuple[Path, list[str], dict]:
    """生成输出文件并返回待提交的历史变更，不立即写入历史。"""
    main_artists_path = Path(PLATFORM_FILES[platform])
    other_artists_path = Path(OTHER_ARTISTS_FILE)

    main_items = flatten_albums(load_json_data(main_artists_path))
    other_items = flatten_albums(load_json_data(other_artists_path))

    history = load_history()
    rng = secrets.SystemRandom()

    other_counts, other_recent = get_category_history_data("Other", history)
    main_counts, main_recent = get_category_history_data(platform, history)

    part1 = weighted_sample(other_items, other_counts, 1, rng, other_recent, unique_artist=True)
    part2 = weighted_sample(main_items, main_counts, count, rng, main_recent, unique_artist=True)

    part1_artists = {item.split(" - ", 1)[0] for item in part1}
    remaining_other = [item for item in other_items if item.split(" - ", 1)[0] not in part1_artists]
    part3 = weighted_sample(remaining_other, other_counts, 4, rng, other_recent, unique_artist=True)

    final_list = part1 + part2 + part3

    timestamp_suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    output_name = f"{platform}+{timestamp_suffix}.txt"
    output_path = base_dir / output_name

    output_lines = []
    for item in final_list:
        artist, album = split_artist_album(item)
        output_lines.append(format_output_item(artist, album))

    output_path.write_text("\n".join(output_lines), encoding="utf-8")

    pending_history = {
        "platform": platform,
        "other_items": part1 + part3,
        "main_items": part2,
    }
    return output_path, final_list, pending_history


def commit_prepared_history(pending_history: dict) -> None:
    """提交 prepare_playlist_output 返回的历史变更。"""
    platform = pending_history.get("platform")
    other_items = pending_history.get("other_items", [])
    main_items = pending_history.get("main_items", [])

    if not platform:
        return

    history = load_history()
    update_history(other_items, "Other", history)
    update_history(main_items, platform, history)
    save_history(history)


def append_history_tx_log(
    action: str,
    platform: str,
    account: str | None = None,
    txt_file: str | None = None,
    status: str = "ok",
    note: str | None = None,
) -> None:
    """追加写入历史事务日志（JSONL）。"""
    record = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "platform": platform,
        "account": account or "",
        "txt_file": txt_file or "",
        "status": status,
        "note": note or "",
    }
    log_path = Path(HISTORY_TX_LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
