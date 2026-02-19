import argparse
import json
import secrets
import time
import re
import random
from datetime import datetime
from pathlib import Path

try:
    import tidalapi
    TIDAL_AVAILABLE = True
except ImportError:
    TIDAL_AVAILABLE = False

# 自定义参数：修改这里即可调整默认行为
DEFAULT_PLATFORM = "T"           # 默认选择：A (Apple), T (Tidal), Q (Qobuz)
DEFAULT_ALBUM_COUNT = 17         # 中间部分从主库抽取的专辑数量
HISTORY_FILE = ".album_history.json"
MAX_RECENT_COMBINATIONS = 50     # 记录最近生成的组合数量，用于避免重复
MIN_COMBINATION_DIFF = 0.85      # 最小组合差异度（0-1），低于此值会重新生成
RECENT_APPEARANCE_WINDOW = 10    # 检查最近N次生成中每个专辑的出现频率
MAX_RECENT_FREQUENCY = 0.3       # 如果专辑在最近N次中出现超过此比例，几乎完全排除
COOLDOWN_WINDOW = 8              # 冷却期：如果专辑在最近N次中出现，暂时大幅降低权重
WEIGHT_DECAY_POWER = 4           # 权重衰减的幂次

# Tidal 集成配置
TIDAL_TRACK_COUNT_MIN = 10       # 每张专辑添加的最小歌曲数量
TIDAL_TRACK_COUNT_MAX = 14       # 每张专辑添加的最大歌曲数量
TIDAL_DELAY_MIN = 1.5            # 操作间隔最小延迟（秒）
TIDAL_DELAY_MAX = 3.5            # 操作间隔最大延迟（秒）
TIDAL_CREDENTIALS_FILE = ".tidal_credentials.json"  # Tidal 登录凭据保存文件
PLAYLIST_NAMES_FILE = "Playlist_name.txt"           # 播放列表名称文件
PLAYLIST_HISTORY_FILE = ".playlist_history.json"    # 已使用的播放列表名称历史

# 平台与文件映射
PLATFORM_FILES = {
    "A": "apple_artists.json",
    "T": "tidal_artists.json",
    "Q": "qobuz_artists.json"
}
OTHER_ARTISTS_FILE = "other_artists.json"

# ==================== Tidal 集成功能 ====================

def load_tidal_credentials() -> dict:
    """加载保存的 Tidal 登录凭据"""
    cred_path = Path(TIDAL_CREDENTIALS_FILE)
    if not cred_path.exists():
        return {}
    try:
        return json.loads(cred_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_tidal_credentials(session) -> None:
    """保存 Tidal 登录凭据"""
    credentials = {
        "token_type": session.token_type,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expiry_time": str(session.expiry_time)
    }
    Path(TIDAL_CREDENTIALS_FILE).write_text(
        json.dumps(credentials, ensure_ascii=False, indent=2), 
        encoding="utf-8"
    )
    print("✓ Tidal 登录凭据已保存")

def login_tidal():
    """登录 Tidal，返回 session 对象"""
    if not TIDAL_AVAILABLE:
        print("✗ 错误：未安装 tidalapi，请运行: pip install tidalapi")
        return None
    
    session = tidalapi.Session()
    credentials = load_tidal_credentials()
    
    # 尝试使用保存的凭据登录
    if credentials.get("access_token"):
        print("正在使用保存的凭据登录 Tidal...")
        try:
            expiry_time = datetime.fromisoformat(credentials["expiry_time"]) if credentials.get("expiry_time") else None
            success = session.load_oauth_session(
                credentials.get("token_type", "Bearer"),
                credentials["access_token"],
                credentials.get("refresh_token", ""),
                expiry_time
            )
            if success and session.check_login():
                print(f"✓ Tidal 自动登录成功！用户: {session.user.first_name} {session.user.last_name}")
                # 更新凭据（可能已刷新）
                save_tidal_credentials(session)
                return session
            else:
                print("✗ 保存的凭据已过期，需要重新验证")
        except Exception as e:
            print(f"✗ 使用保存的凭据登录失败: {e}")
    
    # OAuth 登录
    print("\n需要进行 Tidal OAuth 验证，请在浏览器中完成登录:")
    login_info, future = session.login_oauth()
    print(f">>> 链接: {login_info.verification_uri_complete}")
    print(f">>> 或访问 {login_info.verification_uri} 并输入代码: {login_info.user_code}")
    print("\n等待登录完成...")
    
    future.result()  # 等待登录完成
    
    if session.check_login():
        print(f"✓ Tidal OAuth 验证成功！用户: {session.user.first_name} {session.user.last_name}")
        save_tidal_credentials(session)
        return session
    else:
        print("✗ Tidal 登录失败")
        return None

def load_playlist_history() -> list[str]:
    """加载已使用的播放列表名称历史"""
    history_path = Path(PLAYLIST_HISTORY_FILE)
    if not history_path.exists():
        return []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
        return data.get("used_names", [])
    except Exception:
        return []

def save_playlist_history(used_names: list[str]) -> None:
    """保存已使用的播放列表名称历史"""
    Path(PLAYLIST_HISTORY_FILE).write_text(
        json.dumps({"used_names": used_names}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def load_available_playlist_names() -> list[str]:
    """从 Playlist_name.txt 加载可用的播放列表名称"""
    names_path = Path(PLAYLIST_NAMES_FILE)
    if not names_path.exists():
        print(f"✗ 找不到播放列表名称文件: {PLAYLIST_NAMES_FILE}")
        return []
    
    names = []
    for line in names_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            # 移除行首的序号（如 "1. ", "2. " 等）
            match = re.match(r'^\d+\.\s*(.+)$', line)
            if match:
                names.append(match.group(1).strip())
            else:
                names.append(line)
    return names

def get_next_playlist_name() -> str | None:
    """获取下一个可用的播放列表名称（避免重复）"""
    all_names = load_available_playlist_names()
    used_names = load_playlist_history()
    
    # 找到第一个未使用的名称
    for name in all_names:
        if name not in used_names:
            return name
    
    # 所有名称都已使用
    print("⚠ 所有播放列表名称都已使用，将重置历史记录")
    save_playlist_history([])
    return all_names[0] if all_names else None

def mark_playlist_name_used(name: str) -> None:
    """标记播放列表名称为已使用"""
    used_names = load_playlist_history()
    if name not in used_names:
        used_names.append(name)
        save_playlist_history(used_names)

def parse_album_list_from_txt(txt_path: Path) -> list[dict]:
    """从生成的 txt 文件中解析专辑列表"""
    if not txt_path.exists():
        return []
    
    albums = []
    content = txt_path.read_text(encoding="utf-8")
    
    # 匹配 "艺人名=xxx", "专辑名=xxx" 格式
    pattern = r'"艺人名=([^"]+)"\s*,\s*"专辑名=([^"]+)"'
    matches = re.findall(pattern, content)
    
    for artist, album in matches:
        albums.append({
            "artist_name": artist.strip(),
            "album_name": album.strip()
        })
    
    return albums

def search_album_on_tidal(session, artist_name: str, album_name: str):
    """在 Tidal 上搜索专辑"""
    search_query = f"{artist_name} {album_name}"
    results = session.search(search_query, models=[tidalapi.album.Album])
    
    albums = None
    if isinstance(results, dict):
        albums = results.get('albums', [])
    elif hasattr(results, 'albums'):
        albums = results.albums
    
    if not albums:
        return None
    
    # 查找匹配的专辑
    for album in albums:
        album_artists = []
        if hasattr(album, 'artists') and album.artists:
            album_artists = [a.name.lower() for a in album.artists]
        if hasattr(album, 'artist') and album.artist:
            album_artists.append(album.artist.name.lower())
        
        artist_match = artist_name.lower() in album_artists or any(
            artist_name.lower() in a for a in album_artists
        )
        album_name_attr = album.name if hasattr(album, 'name') else str(album)
        album_match = album_name.lower() in album_name_attr.lower() if album_name_attr else False
        
        if artist_match and album_match:
            return album
    
    # 返回第一个结果
    return albums[0] if albums else None

def get_or_create_playlist_on_tidal(session, playlist_name: str, description: str = ""):
    """获取或创建 Tidal 播放列表"""
    # 获取用户的所有播放列表
    user_playlists = session.user.playlists()
    
    # 查找是否已存在
    for playlist in user_playlists:
        if playlist.name and playlist.name.lower() == playlist_name.lower():
            return playlist, False
    
    # 创建新播放列表
    playlist = session.user.create_playlist(playlist_name, description)
    return playlist, True

def random_delay():
    """随机延迟，避免操作过快"""
    delay = random.uniform(TIDAL_DELAY_MIN, TIDAL_DELAY_MAX)
    time.sleep(delay)

def add_tracks_to_playlist_with_delay(playlist, tracks, track_count: int):
    """将歌曲添加到播放列表（带延迟，随机选择歌曲）"""
    if not tracks:
        return 0
    
    # 随机选择指定数量的歌曲（而不是按顺序取前N首）
    if len(tracks) <= track_count:
        # 歌曲数量不足，全部添加但打乱顺序
        tracks_to_add = list(tracks)
        random.shuffle(tracks_to_add)
    else:
        # 从专辑中随机抽取指定数量的歌曲
        tracks_to_add = random.sample(list(tracks), track_count)
    
    added_count = 0
    
    for track in tracks_to_add:
        try:
            playlist.add([track.id])
            added_count += 1
            random_delay()  # 每添加一首歌后延迟
        except Exception as e:
            print(f"    ✗ 添加歌曲失败: {e}")
    
    return added_count

def process_tidal_playlist(session, txt_path: Path, track_count_min: int, track_count_max: int):
    """处理 Tidal 播放列表添加流程"""
    # 解析专辑列表
    albums = parse_album_list_from_txt(txt_path)
    if not albums:
        print("✗ 未从 txt 文件中解析到专辑信息")
        return False
    
    print(f"\n解析到 {len(albums)} 张专辑待添加")
    
    # 获取播放列表名称
    playlist_name = get_next_playlist_name()
    if not playlist_name:
        print("✗ 无可用的播放列表名称")
        return False
    
    print(f"\n将使用播放列表名称: {playlist_name}")
    
    # 获取或创建播放列表
    playlist, is_new = get_or_create_playlist_on_tidal(session, playlist_name, "自动创建的播放列表")
    if is_new:
        print(f"✓ 创建播放列表: {playlist.name}")
    else:
        print(f"✓ 找到播放列表: {playlist.name}")
    
    # 标记播放列表名称为已使用
    mark_playlist_name_used(playlist_name)
    
    # 为每张专辑生成一个随机的歌曲数量（在范围内不重复）
    track_counts = list(range(track_count_min, track_count_max + 1))
    random.shuffle(track_counts)
    
    # 处理每张专辑
    total_added = 0
    for i, album_info in enumerate(albums):
        artist_name = album_info["artist_name"]
        album_name = album_info["album_name"]
        # 循环使用歌曲数量
        track_count = track_counts[i % len(track_counts)]
        
        print(f"\n[{i+1}/{len(albums)}] 搜索: {artist_name} - {album_name}")
        random_delay()  # 搜索前延迟
        
        album = search_album_on_tidal(session, artist_name, album_name)
        
        if album:
            album_display = album.name if hasattr(album, 'name') else str(album)
            artist_display = album.artist.name if hasattr(album, 'artist') and album.artist else 'Unknown'
            print(f"  ✓ 找到: {album_display} - {artist_display}")
            
            random_delay()  # 获取歌曲前延迟
            tracks = album.tracks()
            actual_track_count = min(track_count, len(tracks))
            print(f"  专辑共 {len(tracks)} 首歌，计划添加 {actual_track_count} 首")
            
            added = add_tracks_to_playlist_with_delay(playlist, tracks, actual_track_count)
            total_added += added
            print(f"  ✓ 已添加 {added} 首歌曲")
        else:
            print(f"  ✗ 未找到专辑")
        
        random_delay()  # 处理下一个专辑前延迟
    
    print(f"\n{'='*60}")
    print(f"✓ Tidal 播放列表添加完成！")
    print(f"  播放列表: {playlist_name}")
    print(f"  总计添加: {total_added} 首歌曲")
    print(f"{'='*60}")
    
    return True

# ==================== 原有功能 ====================

def load_json_data(path: Path) -> list[dict]:
    """读取JSON数据，返回包含 'artist' 和 'albums' 的列表"""
    if not path.exists():
        raise FileNotFoundError(f"未找到文件：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

def flatten_albums(data: list[dict]) -> list[str]:
    """将数据展平为 '艺人 - 专辑' 格式的字符串列表（用于历史记录）"""
    flat_list = []
    for entry in data:
        artist = entry.get("artist", "Unknown")
        for album in entry.get("albums", []):
            flat_list.append(f"{artist} - {album}")
    return flat_list

def split_artist_album(item: str) -> tuple[str, str]:
    """将 '艺人 - 专辑' 格式的字符串拆分为艺人和专辑名"""
    parts = item.split(" - ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "Unknown", item

def format_output_item(artist: str, album: str) -> str:
    """格式化为 '艺人名=xxx', '专辑名=xxx' 的格式"""
    return f'"艺人名={artist}", "专辑名={album}"'

def load_history() -> dict:
    if not Path(HISTORY_FILE).exists():
        return {}
    try:
        return json.loads(Path(HISTORY_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_history(history: dict) -> None:
    Path(HISTORY_FILE).write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def combination_similarity(comb1: set[str], comb2: set[str]) -> float:
    """计算两个组合的相似度（Jaccard相似度）。"""
    if not comb1 or not comb2:
        return 0.0
    intersection = len(comb1 & comb2)
    union = len(comb1 | comb2)
    return intersection / union if union > 0 else 0.0

def calculate_recent_frequency(item: str, recent_combinations: list[set[str]]) -> float:
    """计算专辑在最近组合中的出现频率。"""
    if not recent_combinations:
        return 0.0
    window = recent_combinations[-RECENT_APPEARANCE_WINDOW:] if len(recent_combinations) > RECENT_APPEARANCE_WINDOW else recent_combinations
    appearances = sum(1 for combo in window if item in combo)
    return appearances / len(window) if window else 0.0

def is_in_cooldown(item: str, recent_combinations: list[set[str]]) -> bool:
    """检查专辑是否在冷却期内。"""
    if not recent_combinations:
        return False
    cooldown_window = recent_combinations[-COOLDOWN_WINDOW:] if len(recent_combinations) > COOLDOWN_WINDOW else recent_combinations
    return any(item in combo for combo in cooldown_window)

def weighted_sample(items: list[str], counts: dict[str, int], k: int, rng: secrets.SystemRandom, 
                    recent_combinations: list[set[str]] = None, unique_artist: bool = False) -> list[str]:
    """使用极强化权重算法、冷却机制和去重逻辑进行抽样。
    
    Args:
        unique_artist: 如果为 True，确保每个艺人只选一个专辑
    """
    if recent_combinations is None:
        recent_combinations = []
    
    # 如果需要艺人去重，先按艺人分组
    if unique_artist:
        artist_albums = {}  # {artist: [album_items]}
        for item in items:
            artist = item.split(" - ", 1)[0]
            if artist not in artist_albums:
                artist_albums[artist] = []
            artist_albums[artist].append(item)
        
        # 为每个艺人随机选择一个专辑，形成新的候选列表
        items = [rng.choice(albums) for albums in artist_albums.values()]
    
    # 如果可用项目少于需求数量，直接返回所有（去重后）
    if len(items) <= k:
        return list(set(items))

    max_attempts = 500
    picked = []
    
    all_counts = [counts.get(i, 0) for i in items]
    min_count = min(all_counts) if all_counts else 0
    max_count = max(all_counts) if all_counts else 0
    
    for attempt in range(max_attempts):
        weights = []
        for item in items:
            c = counts.get(item, 0)
            
            # 权重计算逻辑与原脚本一致
            base_weight = 1.0 / ((1 + c) ** WEIGHT_DECAY_POWER)
            
            if is_in_cooldown(item, recent_combinations):
                base_weight *= 0.001
            
            recent_freq = calculate_recent_frequency(item, recent_combinations)
            if recent_freq > MAX_RECENT_FREQUENCY:
                base_weight *= 0.001
            elif recent_freq > 0.2:
                base_weight *= 0.01
            elif recent_freq > 0.1:
                base_weight *= 0.1
            
            if max_count > 0 and c > min_count:
                relative_count = (c - min_count) / (max_count - min_count + 1)
                base_weight *= (1.0 - relative_count * 0.7)
            
            weights.append(max(base_weight, 1e-12))
        
        try:
            # 抽样逻辑
            picked = []
            available = items.copy()
            temp_weights = weights.copy()
            
            for _ in range(k):
                if not available:
                    break
                
                # 重新计算可用项的权重总和，避免 sum=0
                # 这里简单起见，如果权重太小，使用随机抽取
                available_weights = []
                for idx, val in enumerate(items):
                    if val in available:
                         available_weights.append(weights[idx])
                
                total_weight = sum(available_weights)
                
                if total_weight < 1e-10:
                    picked.append(available.pop(rng.randrange(len(available))))
                else:
                    # 使用对应的权重
                    idx = rng.choices(range(len(available)), weights=available_weights, k=1)[0]
                    picked.append(available.pop(idx))
            
            # 确保数量足够
            picked = list(dict.fromkeys(picked))
            if len(picked) < k:
                remaining = [x for x in items if x not in picked]
                needed = k - len(picked)
                if len(remaining) >= needed:
                    picked += rng.sample(remaining, needed)
                else:
                    picked += remaining

        except (ValueError, IndexError):
             picked = rng.sample(items, k=min(k, len(items)))
        
        picked_set = set(picked)
        
        # 相似度检查
        is_similar = False
        for recent in recent_combinations:
            similarity = combination_similarity(picked_set, recent)
            if similarity > (1.0 - MIN_COMBINATION_DIFF):
                is_similar = True
                break
        
        if not is_similar and len(recent_combinations) >= 3:
            recent_3 = recent_combinations[-3:]
            avg_similarity = sum(combination_similarity(picked_set, r) for r in recent_3) / len(recent_3)
            if avg_similarity > 0.5:
                is_similar = True
        
        if not is_similar:
            return picked
            
    return picked

def update_history(items: list[str], category: str, history: dict):
    """更新历史记录（计数和组合）"""
    data = history.get(category, {"counts": {}, "all_combinations": []})
    
    # 兼容旧格式
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

def get_category_history_data(category: str, history: dict):
    """获取指定分类的历史数据，用于抽样"""
    data = history.get(category, {"counts": {}, "all_combinations": []})
    if isinstance(data, dict) and "counts" not in data:
        data = {"counts": data, "all_combinations": []}
    
    counts = data.get("counts", {})
    recent_combinations = [set(combo) for combo in data.get("all_combinations", [])]
    return counts, recent_combinations

def main():
    base_dir = Path(__file__).parent
    
    parser = argparse.ArgumentParser(description="随机生成播放列表")
    parser.add_argument(
        "--Platform",
        choices=["A", "T", "Q"],
        default=DEFAULT_PLATFORM,
        help="选择平台: A=Apple, T=Tidal, Q=Qobuz"
    )
    parser.add_argument(
        "--Count",
        type=int,
        default=DEFAULT_ALBUM_COUNT,
        help=f"主库抽取的专辑数量，默认 {DEFAULT_ALBUM_COUNT}"
    )
    # Tidal 集成参数
    parser.add_argument(
        "--tidal",
        action="store_true",
        help="启用 Tidal 播放列表自动添加功能"
    )
    parser.add_argument(
        "--track-min",
        type=int,
        default=TIDAL_TRACK_COUNT_MIN,
        help=f"每张专辑添加的最小歌曲数，默认 {TIDAL_TRACK_COUNT_MIN}"
    )
    parser.add_argument(
        "--track-max",
        type=int,
        default=TIDAL_TRACK_COUNT_MAX,
        help=f"每张专辑添加的最大歌曲数，默认 {TIDAL_TRACK_COUNT_MAX}"
    )
    args = parser.parse_args()

    # 当平台为 Tidal 时，默认启用 Tidal 添加功能
    if args.Platform == "T" and not args.tidal:
        args.tidal = True

    # ===== Tidal 登录验证（如果启用） =====
    tidal_session = None
    if args.tidal:
        if args.Platform != "T":
            print("⚠ Tidal 添加功能仅支持 Tidal 平台 (--Platform T)")
            args.Platform = "T"
        
        print("="*60)
        print("Tidal 播放列表自动添加工具")
        print("="*60)
        
        tidal_session = login_tidal()
        if not tidal_session:
            print("✗ Tidal 登录失败，退出程序")
            return
        
        print()

    # ===== 1. 加载数据 =====
    platform_file = PLATFORM_FILES.get(args.Platform)
    main_artists_path = base_dir / platform_file
    other_artists_path = base_dir / OTHER_ARTISTS_FILE
    
    if not main_artists_path.exists():
        print(f"错误：找不到主库文件 {main_artists_path}")
        return
    if not other_artists_path.exists():
        print(f"错误：找不到Other文件 {other_artists_path}")
        return

    main_items = flatten_albums(load_json_data(main_artists_path))
    other_items = flatten_albums(load_json_data(other_artists_path))
    
    history = load_history()
    rng = secrets.SystemRandom()

    # ===== 2. 生成第一部分：Other库随机1张 =====
    other_counts, other_recent = get_category_history_data("Other", history)
    part1 = weighted_sample(other_items, other_counts, 1, rng, other_recent, unique_artist=True)
    
    # ===== 3. 生成第二部分：主库随机N张（每个艺人只选一张专辑） =====
    main_counts, main_recent = get_category_history_data(args.Platform, history)
    part2 = weighted_sample(main_items, main_counts, args.Count, rng, main_recent, unique_artist=True)
    
    # ===== 4. 生成第三部分：Other库随机4张（排除part1的艺人） =====
    part1_artists = {item.split(" - ", 1)[0] for item in part1}
    remaining_other = [x for x in other_items if x.split(" - ", 1)[0] not in part1_artists]
    part3 = weighted_sample(remaining_other, other_counts, 4, rng, other_recent, unique_artist=True)
    
    # ===== 5. 组合结果 =====
    final_list = part1 + part2 + part3
    
    # ===== 6. 更新历史记录 =====
    update_history(part1 + part3, "Other", history)
    update_history(part2, args.Platform, history)
    save_history(history)

    # ===== 7. 输出文件 =====
    timestamp_suffix = datetime.now().strftime("%Y%m%d%H%M%S")
    output_name = f"{args.Platform}+{timestamp_suffix}.txt"
    output_path = base_dir / output_name
    
    # 直接输出艺人专辑列表（无 AI 提示词）
    output_lines = []
    for item in final_list:
        artist, album = split_artist_album(item)
        output_lines.append(format_output_item(artist, album))
    
    output_content = "\n".join(output_lines)
    output_path.write_text(output_content, encoding="utf-8")
    
    print(f"已生成播放列表：")
    print(f"1. Other (1首): {part1[0]}")
    print(f"2. {args.Platform} ({len(part2)}首)")
    print(f"3. Other (4首)")
    print(f"总计: {len(final_list)} 首")
    print(f"输出文件：{output_path.name}")

    # ===== 8. Tidal 播放列表添加（如果启用） =====
    if args.tidal and tidal_session:
        print(f"\n{'='*60}")
        print("开始添加歌曲到 Tidal 播放列表...")
        print(f"{'='*60}")
        process_tidal_playlist(
            tidal_session, 
            output_path, 
            args.track_min, 
            args.track_max
        )


if __name__ == "__main__":
    main()
