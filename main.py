import argparse
import json
import secrets
import time
import re
import random
import logging
import sys
import os
import socket
import threading
import ctypes
import shutil
import subprocess
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Windows API 常量（用于激活窗口）
SW_RESTORE = 9
SW_SHOW = 5

# ===== 浏览器窗口保活功能 =====
class BrowserKeepAlive:
    """后台线程定期激活浏览器窗口，防止后台休眠"""
    
    def __init__(self, driver, interval=30):
        self.driver = driver
        self.interval = interval  # 激活间隔（秒）
        self.running = False
        self.thread = None
        self.hwnd = None
    
    def _find_chrome_window(self):
        """查找 Chrome 窗口句柄"""
        try:
            user32 = ctypes.windll.user32
            
            # 枚举窗口回调函数
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
            
            chrome_hwnd = None
            
            def callback(hwnd, lParam):
                nonlocal chrome_hwnd
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    # 查找包含 Chrome 或 Apple Music 或 Qobuz 的窗口
                    if user32.IsWindowVisible(hwnd) and ('Chrome' in title or 'Apple Music' in title or 'Qobuz' in title):
                        chrome_hwnd = hwnd
                        return False  # 停止枚举
                return True
            
            user32.EnumWindows(EnumWindowsProc(callback), 0)
            return chrome_hwnd
        except:
            return None
    
    def _activate_window(self):
        """激活浏览器窗口"""
        try:
            # 方法1: 通过 Selenium 激活
            self.driver.execute_script("window.focus();")
            
            # 方法2: 通过 Windows API 激活（更可靠）
            if not self.hwnd:
                self.hwnd = self._find_chrome_window()
            
            if self.hwnd:
                user32 = ctypes.windll.user32
                # 如果窗口最小化，先恢复
                if user32.IsIconic(self.hwnd):
                    user32.ShowWindow(self.hwnd, SW_RESTORE)
                else:
                    user32.ShowWindow(self.hwnd, SW_SHOW)
                # 将窗口置于前台
                user32.SetForegroundWindow(self.hwnd)
                time.sleep(0.1)
                # 立即失去焦点（让用户可以继续工作）
                # 模拟 Alt+Tab 或点击其他地方不太好，直接让窗口失去焦点
        except:
            pass
    
    def _keep_alive_loop(self):
        """保活循环"""
        while self.running:
            try:
                self._activate_window()
            except:
                pass
            # 等待下一次激活
            for _ in range(int(self.interval * 10)):
                if not self.running:
                    break
                time.sleep(0.1)
    
    def start(self):
        """启动保活线程"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._keep_alive_loop, daemon=True)
            self.thread.start()
    
    def stop(self):
        """停止保活线程"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

# 全局保活实例
_browser_keep_alive = None

def start_browser_keep_alive(driver, interval=30):
    """启动浏览器保活"""
    global _browser_keep_alive
    if _browser_keep_alive:
        _browser_keep_alive.stop()
    _browser_keep_alive = BrowserKeepAlive(driver, interval)
    _browser_keep_alive.start()
    print(f"  ✓ 已启动浏览器保活（每 {interval} 秒激活一次）")

def stop_browser_keep_alive():
    """停止浏览器保活"""
    global _browser_keep_alive
    if _browser_keep_alive:
        _browser_keep_alive.stop()
        _browser_keep_alive = None

# ===== 网络 / 代理 =====
_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)
_DIRECT_URL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _parse_proxy_endpoint(proxy_value: str) -> tuple[str, int] | None:
    if not proxy_value or proxy_value.strip().lower() in ("direct", "none", ""):
        return None
    value = proxy_value.strip()
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _proxy_endpoint_alive(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def sanitize_stale_process_proxy() -> list[str]:
    """
    清除当前进程内不可用的 HTTP 代理环境变量。
    常见于 VPN（如狗急加速/Clash）关闭后仍残留 http://127.0.0.1:17890，导致 Python 无法连网而浏览器正常。
    """
    dead_endpoints: set[tuple[str, int]] = set()
    seen_endpoints: set[tuple[str, int]] = set()

    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if not value:
            continue
        endpoint = _parse_proxy_endpoint(value)
        if endpoint is None or endpoint in seen_endpoints:
            continue
        seen_endpoints.add(endpoint)
        if not _proxy_endpoint_alive(*endpoint):
            dead_endpoints.add(endpoint)

    removed: list[str] = []
    if not dead_endpoints:
        return removed

    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if not value:
            continue
        endpoint = _parse_proxy_endpoint(value)
        if endpoint in dead_endpoints:
            os.environ.pop(key, None)
            removed.append(f"{key}={value}")

    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    return removed


def urlopen_direct(url: str, timeout: float):
    """urllib 直连，不受系统/VPN 残留代理影响。"""
    return _DIRECT_URL_OPENER.open(url, timeout=timeout)


def configure_tidal_session_network(session) -> None:
    """Tidal API 请求强制直连，并给每次请求加上超时，避免套接字一直挂起。"""
    req = getattr(session, "request_session", None)
    if req is None:
        return
    req.trust_env = False
    req.proxies = {}
    if getattr(req, "_playlist_timeout_wrapped", False):
        return
    original = req.request

    def request_with_timeout(*args, **kwargs):
        kwargs.setdefault("timeout", TIDAL_HTTP_TIMEOUT)
        return original(*args, **kwargs)

    req.request = request_with_timeout
    req._playlist_timeout_wrapped = True


# 进程启动时清除失效代理，避免 import 后首次 API 请求仍走 127.0.0.1
sanitize_stale_process_proxy()

# ===== 日志配置 =====
LOGS_DIR = "logs"
PLATFORM_LOG_NAMES = {"T": "tidal", "A": "apple", "Q": "qobuz"}
_CURRENT_LOG_FILE: str | None = None


def setup_logging(platform: str = "T") -> str:
    """每次运行写入 logs/{平台}_{时间}.txt，并同步更新 logs/run_latest.txt。"""
    global _CURRENT_LOG_FILE
    base_dir = Path(__file__).parent
    logs_dir = base_dir / LOGS_DIR
    logs_dir.mkdir(parents=True, exist_ok=True)

    platform_name = PLATFORM_LOG_NAMES.get((platform or "T").upper(), "run")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{platform_name}_{timestamp}.txt"

    log_format = logging.Formatter("%(asctime)s - %(message)s", datefmt="%H:%M:%S")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)

    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    tidal_request_logger = logging.getLogger("tidalapi.request")
    tidal_request_logger.setLevel(logging.CRITICAL)
    tidal_request_logger.propagate = False

    _CURRENT_LOG_FILE = str(log_path)
    finalize_run_log(str(log_path))
    return str(log_path)


def finalize_run_log(log_file: str | None = None) -> None:
    """将本次日志复制为 logs/run_latest.txt，便于快速查看最近一次运行。"""
    path = Path(log_file or _CURRENT_LOG_FILE or "")
    if not path.exists():
        return
    try:
        latest = Path(__file__).parent / LOGS_DIR / "run_latest.txt"
        shutil.copy2(path, latest)
    except Exception:
        pass

# 自定义 print 函数，同时输出到控制台和日志文件
_original_print = print
def print(*args, **kwargs):
    message = ' '.join(str(arg) for arg in args)
    logging.info(message)  # 写入日志文件
    kwargs.setdefault("flush", True)
    try:
        _original_print(*args, **kwargs)  # 输出到控制台
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe = message.encode(enc, errors="replace").decode(enc, errors="replace")
        _original_print(safe, **{k: v for k, v in kwargs.items() if k != "file"})

try:
    import tidalapi
    TIDAL_AVAILABLE = True
except ImportError:
    TIDAL_AVAILABLE = False

# Selenium 导入（Apple Music 需要）
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.action_chains import ActionChains
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# 自定义参数：修改这里即可调整默认行为
DEFAULT_PLATFORM = "A"           # 默认选择：A (Apple), T (Tidal), Q (Qobuz)
APP_VERSION = "0.1.71"  # 修复：按账号地区切店面（港hk/美us）；加歌失败则把 URL 改成目标店面再重试
# 更新内容：APPLE_REGION_STOREFRONT；登录后 ensure 目标店面；加歌 0 首时 URL 重写重试
DEFAULT_ALBUM_COUNT = 18         # 中间部分从主库抽取的专辑数量
HISTORY_FILE = ".album_history.json"
MAX_RECENT_COMBINATIONS = 50     # 记录最近生成的组合数量，用于避免重复
MIN_COMBINATION_DIFF = 0.85      # 最小组合差异度（0-1），低于此值会重新生成
RECENT_APPEARANCE_WINDOW = 10    # 检查最近N次生成中每个专辑的出现频率
MAX_RECENT_FREQUENCY = 0.3       # 如果专辑在最近N次中出现超过此比例，几乎完全排除
COOLDOWN_WINDOW = 8              # 冷却期：如果专辑在最近N次中出现，暂时大幅降低权重
WEIGHT_DECAY_POWER = 4           # 权重衰减的幂次

# Tidal 集成配置
TIDAL_MODE = 1                   # Tidal 模式：1=新增播放列表，2=删除指定艺人专辑歌曲
TIDAL_TRACK_COUNT_MIN = 12       # 每张专辑添加的最小歌曲数量
TIDAL_TRACK_COUNT_MAX = 16       # 每张专辑添加的最大歌曲数量
TIDAL_DELAY_MIN = 0.5            # 操作间隔最小延迟（秒）
TIDAL_DELAY_MAX = 1            # 操作间隔最大延迟（秒）
TIDAL_CREDENTIALS_FILE = ".tidal_credentials.json"  # Tidal 登录凭据保存文件
TIDAL_CHROME_PROFILE_DIR = "TidalChromeProfile"     # Tidal 专用 Chrome 配置（非无痕，绕风控）
TIDAL_SWITCH_ACCOUNT_TEMPLATE = "tidal_assets/switch_account_label.png"  # 「No, switch account」截图模板
TIDAL_SWITCH_ACCOUNT_MATCH_THRESHOLD = 0.9          # 登录历史页图像识别阈值
TIDAL_SWITCH_ACCOUNT_MATCH_SCALES = (0.65, 0.75, 0.85, 0.95, 1.0, 1.1, 1.2, 1.35, 1.5)
TIDAL_LOGIN_WITH_PASSWORD_TEMPLATE = "tidal_assets/login_with_password_label.png"  # 「Log in with password」模板
TIDAL_LOGIN_WITH_PASSWORD_MATCH_THRESHOLD = 0.9   # 验证码页图像识别阈值
TIDAL_OAUTH_PENDING_FILE = ".tidal_oauth_pending.json"  # mcp 模式待办（仅 Agent handoff 用）
TIDAL_LOGIN_MODE = "auto"         # Tidal 登录：auto=全自动浏览器, selenium=无痕, mcp=仅写待办等 Agent
TIDAL_MCP_LOGIN_TIMEOUT = 600     # mcp 模式最长等待（秒）
TIDAL_OAUTH_WAIT_TIMEOUT = 120    # 浏览器 OAuth 完成后等待 token 兑换（秒）
TIDAL_OAUTH_CHECK_INTERVAL = 2.0  # 设备码兑换 token 的轮询间隔（秒）
TIDAL_HTTP_TIMEOUT = 30          # Tidal HTTP 超时（秒）。auth 偶发二十多秒才返回，无超时则会一直挂住
TIDAL_OAUTH_API_RETRIES = 3                         # auth.tidal.com 请求失败重试次数
TIDAL_OAUTH_FAILURE_BROWSER_PAUSE = 20              # 登录失败时保留浏览器秒数，便于查看页面
TIDAL_EMAIL_FILE = "tidal_email.txt"                # Tidal 账号邮箱密码文件
TIDAL_DELETE_FILE = "tidal_delete_songs.txt"        # Tidal 删除歌曲列表文件
PLAYLIST_NAMES_FILE = "Playlist_name.txt"           # 播放列表名称文件
PLAYLIST_HISTORY_FILE = ".playlist_history.json"    # 已使用的播放列表名称历史
WEBDRIVER_STARTUP_RETRIES = 4  # 浏览器启动最大重试次数
WEBDRIVER_STARTUP_RETRY_DELAY = 2.0  # 启动失败后的重试间隔（秒）
WEBDRIVER_DOWNLOAD_TIMEOUT = 120  # chromedriver 下载超时（秒，约 19MB）
WEBDRIVER_META_TIMEOUT = 20  # chromedriver 版本查询超时（秒）
CHROMEDRIVER_PLATFORM = "win64"
CHROMEDRIVER_CACHE_DIR = ".webdriver_cache"

# Apple Music 集成配置
APPLE_TRACK_COUNT_MIN = 12       # 每张专辑添加的最小歌曲数量
APPLE_TRACK_COUNT_MAX = 18       # 每张专辑添加的最大歌曲数量
APPLE_DELAY_MIN = 0.3            # 一般操作间隔最小延迟（秒）
APPLE_DELAY_MAX = 0.6            # 一般操作间隔最大延迟（秒）
APPLE_SONG_INTERVAL_MIN = 2.2    # 歌与歌之间间隔最小（秒），约 2.5s
APPLE_SONG_INTERVAL_MAX = 2.8    # 歌与歌之间间隔最大（秒）
APPLE_LOGIN_MODE = "auto"        # Apple 登录：auto=读 apple_email.txt 全自动；manual=浏览器内手动登录后输入 y
APPLE_LOGIN_CONFIRM_TIMEOUT = 1800  # Apple Music 手动登录确认最长等待时间（秒）
APPLE_SEARCH_PANEL_WAIT_SECONDS = 10  # 点击左侧搜索入口后等待顶部搜索框出现（秒）
APPLE_EMAIL_FILE = "apple_email.txt"  # Apple 账号邮箱密码文件（格式同 tidal_email.txt）
APPLE_HOME_URL = "https://music.apple.com"
APPLE_LOGIN_TIMEOUT = 180        # 自动登录最长等待（秒）
APPLE_ASSETS_DIR = "apple_assets"  # 登录调试截图目录
APPLE_MAX_ALBUMS = None           # 每账号最多处理专辑数；None=全量（可用 --apple-max-albums 覆盖）
# 飞书「地区」/账号第三行 → Apple Music URL 店面码（港号 hk、美号 us …）
APPLE_REGION_STOREFRONT = {
    "香港": "hk", "港": "hk", "hk": "hk", "hongkong": "hk", "hong kong": "hk",
    "美国": "us", "美": "us", "us": "us", "usa": "us", "united states": "us",
    "英国": "gb", "uk": "gb", "gb": "gb",
    "日本": "jp", "jp": "jp",
    "台湾": "tw", "台灣": "tw", "tw": "tw",
    "新加坡": "sg", "sg": "sg",
    "澳洲": "au", "澳大利亚": "au", "au": "au",
    "加拿大": "ca", "ca": "ca",
}
APPLE_DEFAULT_STOREFRONT = "hk"  # 未指定地区时默认香港（本批 A24-A28 均为港号）


# Qobuz 集成配置
QOBUZ_TRACK_COUNT_MIN = 10       # 每张专辑添加的最小歌曲数量
QOBUZ_TRACK_COUNT_MAX = 14       # 每张专辑添加的最大歌曲数量
QOBUZ_DELAY_MIN = 0.3            # 操作间隔最小延迟（秒）
QOBUZ_DELAY_MAX = 0.8            # 操作间隔最大延迟（秒）
QOBUZ_LOGIN_URL = "https://play.qobuz.com/login"  # Qobuz 登录页

# Qobuz 多语言支持（英语、法语、德语）
QOBUZ_CREATE_BUTTON_TEXTS = ['Create', 'Créer', 'Erstellen', 'Anlegen']
QOBUZ_ADD_TO_PLAYLIST_TEXTS = ['Add to playlists', 'Ajouter aux playlists', 'Zu Playlists hinzufügen', 'Den Playlists hinzufügen', 'Add to playlist']
QOBUZ_ADD_BUTTON_TEXTS = ['Add', 'Ajouter', 'Hinzufügen']

CHROME_BINARY_CANDIDATES = [
    r"C:\Users\Lenovo\AppData\Local\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# 平台与文件映射
PLATFORM_FILES = {
    "A": "apple_artists.json",
    "T": "tidal_artists.json",
    "Q": "qobuz_artists.json"
}
OTHER_ARTISTS_FILE = "other_artists.json"


def _normalize_album_key(artist, album):
    return f"{(artist or '').strip()} - {(album or '').strip()}".lower()


def load_artist_album_source_index(platform_code: str, base_dir: Path = None):
    """加载「我们的艺人」与「其它艺人」索引，用于失败汇总标注来源。

    返回 dict:
      our_album_keys / other_album_keys: set('艺人 - 专辑'.lower())
      our_artists / other_artists: set(艺人名.lower())
      our_file / other_file: 文件名（展示用）
    """
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent
    our_file = PLATFORM_FILES.get(platform_code, "apple_artists.json")
    index = {
        "our_album_keys": set(),
        "other_album_keys": set(),
        "our_artists": set(),
        "other_artists": set(),
        "our_file": our_file,
        "other_file": OTHER_ARTISTS_FILE,
    }

    def _ingest(path: Path, album_keys: set, artist_names: set):
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        for entry in data or []:
            artist = (entry.get("artist") or "").strip()
            if artist:
                artist_names.add(artist.lower())
            for album in entry.get("albums") or []:
                album_keys.add(_normalize_album_key(artist, album))

    _ingest(base / our_file, index["our_album_keys"], index["our_artists"])
    _ingest(base / OTHER_ARTISTS_FILE, index["other_album_keys"], index["other_artists"])
    return index


def classify_album_source(artist, album, source_index: dict) -> str:
    """返回失败专辑来源标签：我们的艺人 / 其它艺人 / 未知来源。"""
    if not source_index:
        return "未知来源"
    key = _normalize_album_key(artist, album)
    artist_l = (artist or "").strip().lower()
    our_keys = source_index.get("our_album_keys") or set()
    other_keys = source_index.get("other_album_keys") or set()
    our_artists = source_index.get("our_artists") or set()
    other_artists = source_index.get("other_artists") or set()

    # 专辑级精确匹配优先
    if key in our_keys and key not in other_keys:
        return "我们的艺人"
    if key in other_keys and key not in our_keys:
        return "其它艺人"
    if key in our_keys and key in other_keys:
        return "我们的艺人"  # 两边都有时归入主库

    in_our = artist_l in our_artists
    in_other = artist_l in other_artists
    if in_our and not in_other:
        return "我们的艺人"
    if in_other and not in_our:
        return "其它艺人"
    if in_our and in_other:
        return "我们的艺人"
    return "未知来源"


def print_failed_albums_summary(failed_albums, platform_code: str, base_dir: Path = None, tip: str = None):
    """打印失败专辑明细，并标注来源（我们的艺人 / 其它艺人）。"""
    if not failed_albums:
        print("  失败专辑: 无")
        return

    source_index = load_artist_album_source_index(platform_code, base_dir)
    our_file = source_index.get("our_file", "*_artists.json")
    other_file = source_index.get("other_file", OTHER_ARTISTS_FILE)

    enriched = []
    for item in failed_albums:
        source = classify_album_source(item.get("artist"), item.get("album"), source_index)
        enriched.append({**item, "source": source})

    our_count = sum(1 for x in enriched if x["source"] == "我们的艺人")
    other_count = sum(1 for x in enriched if x["source"] == "其它艺人")
    unknown_count = sum(1 for x in enriched if x["source"] == "未知来源")

    parts = [f"我们的艺人 {our_count}", f"其它艺人 {other_count}"]
    if unknown_count:
        parts.append(f"未知来源 {unknown_count}")
    print(f"  失败专辑: {len(enriched)} 张（{' / '.join(parts)}）")
    print(f"  来源说明: 我们的艺人={our_file}；其它艺人={other_file}")
    print(f"  ---------- 失败明细 ----------")
    for idx, item in enumerate(enriched, 1):
        print(
            f"  [{idx}] {item.get('artist')} - {item.get('album')}"
            f"  | 来源: {item.get('source', '未知来源')}"
            f"  | 阶段: {item.get('stage', '?')}"
            f"  | 原因: {item.get('reason', '未知')}"
        )
    print(f"  ------------------------------")
    if tip:
        print(tip)


# ==================== Tidal 集成功能 ====================

def load_tidal_accounts() -> list[dict]:
    """从 tidal_email.txt 读取账号列表，返回 [{email, password}, ...]"""
    email_path = Path(TIDAL_EMAIL_FILE)
    if not email_path.exists():
        return []
    
    accounts = []
    content = email_path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    
    # 按空行分割不同账号
    blocks = content.split("\n\n")
    for block in blocks:
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if len(lines) >= 2:
            accounts.append({
                "email": lines[0],
                "password": lines[1]
            })
    
    return accounts


def load_apple_accounts() -> list[dict]:
    """从 apple_email.txt 读取账号列表。

    格式（空行分隔账号）：
      邮箱
      密码
      地区   # 可选：香港/美国/hk/us …；缺省用 APPLE_DEFAULT_STOREFRONT
    """
    email_path = Path(APPLE_EMAIL_FILE)
    if not email_path.exists():
        return []

    accounts = []
    content = email_path.read_text(encoding="utf-8").strip()
    if not content:
        return []

    blocks = content.split("\n\n")
    for block in blocks:
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if len(lines) >= 2:
            region = lines[2] if len(lines) >= 3 else ""
            accounts.append({
                "email": lines[0],
                "password": lines[1],
                "region": region,
                "storefront": apple_region_to_storefront(region),
            })
    return accounts


def apple_region_to_storefront(region: str | None) -> str:
    """把飞书/账号地区文案映射为 music.apple.com/{code}/ 店面码。"""
    key = (region or "").strip().lower().replace("區", "").replace("区", "")
    if not key:
        return APPLE_DEFAULT_STOREFRONT
    # 直接命中
    for name, code in APPLE_REGION_STOREFRONT.items():
        if key == name.lower() or key == code.lower():
            return code
    # 包含命中（如「美国区」）
    for name, code in APPLE_REGION_STOREFRONT.items():
        if name.lower() in key or code.lower() == key:
            return code
    # 已是两字母店面码
    if len(key) == 2 and key.isalpha():
        return key
    return APPLE_DEFAULT_STOREFRONT



def load_tidal_delete_list() -> list[dict]:
    """从 tidal_delete_songs.txt 读取要删除的艺人和专辑列表
    
    文件格式：
    艺人名
    专辑名
    （空行分隔不同条目）
    
    Returns:
        [{artist, album}, ...]
    """
    delete_path = Path(TIDAL_DELETE_FILE)
    if not delete_path.exists():
        return []
    
    delete_list = []
    content = delete_path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    
    # 按空行分割不同条目
    blocks = content.split("\n\n")
    for block in blocks:
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if len(lines) >= 2:
            delete_list.append({
                "artist": lines[0],
                "album": lines[1]
            })
    
    return delete_list


def resolve_chrome_binary_path() -> str | None:
    """在 Windows 常见路径中查找 Chrome 可执行文件。"""
    for candidate in CHROME_BINARY_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def detect_chrome_version(chrome_binary_path: str) -> str | None:
    """通过 chrome.exe --version 获取本机 Chrome 版本。"""
    try:
        result = subprocess.run(
            [chrome_binary_path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            check=False,
        )
        version_text = f"{result.stdout} {result.stderr}".strip()
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", version_text)
        if match:
            return match.group(1)
    except Exception:
        pass

    try:
        ps_command = f"(Get-Item '{chrome_binary_path}').VersionInfo.ProductVersion"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            check=False,
        )
        version_text = f"{result.stdout} {result.stderr}".strip()
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", version_text)
        if match:
            return match.group(1)
    except Exception:
        pass

    return None


def resolve_chromedriver_version(chrome_version: str) -> str | None:
    """根据 Chrome build 解析匹配的 chromedriver 版本。"""
    build_version = ".".join(chrome_version.split(".")[:3])
    metadata_url = "https://googlechromelabs.github.io/chrome-for-testing/latest-patch-versions-per-build.json"

    try:
        with urlopen_direct(metadata_url, WEBDRIVER_META_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        build_info = data.get("builds", {}).get(build_version)
        if build_info:
            return build_info.get("version")
    except Exception as e:
        print(f"  ! 查询 chromedriver 版本失败: {e}")

    return chrome_version


def _chromedriver_exe_candidates(version: str) -> list[Path]:
    return [
        Path.home() / ".cache" / "selenium" / "chromedriver" / CHROMEDRIVER_PLATFORM / version / "chromedriver.exe",
        Path(__file__).parent / CHROMEDRIVER_CACHE_DIR / version / f"chromedriver-{CHROMEDRIVER_PLATFORM}" / "chromedriver.exe",
    ]


def _scan_cached_chromedriver(prefix: str) -> tuple[str, str] | None:
    """在本地/Selenium 缓存中找以 prefix 开头且含 chromedriver.exe 的最新版本。"""
    best = None
    roots = [
        (Path(__file__).parent / CHROMEDRIVER_CACHE_DIR, f"chromedriver-{CHROMEDRIVER_PLATFORM}/chromedriver.exe"),
        (Path.home() / ".cache" / "selenium" / "chromedriver" / CHROMEDRIVER_PLATFORM, "chromedriver.exe"),
    ]
    for root, rel in roots:
        if not root.exists():
            continue
        for version_dir in root.iterdir():
            if not version_dir.is_dir():
                continue
            ver = version_dir.name
            if not ver.startswith(prefix):
                continue
            exe = version_dir / rel
            if exe.exists() and exe.stat().st_size > 0:
                if best is None or ver > best[0]:
                    best = (ver, str(exe))
    return best


def find_existing_chromedriver(driver_version: str) -> str | None:
    """优先复用已存在的 chromedriver，避免重复下载。
    精确版本 → 同 build → 同 major（如 150.x）逐级降级。"""
    for candidate in _chromedriver_exe_candidates(driver_version):
        if candidate.exists() and candidate.stat().st_size > 0:
            return str(candidate)

    build_prefix = ".".join(driver_version.split(".")[:3]) + "."  # 150.0.7871.
    major_prefix = driver_version.split(".", 1)[0] + "."         # 150.

    for prefix, label in ((build_prefix, "同 build"), (major_prefix, "同大版本")):
        best = _scan_cached_chromedriver(prefix)
        if best and best[0] != driver_version:
            print(f"  ! 未找到 chromedriver {driver_version}，{label}降级使用缓存 {best[0]}")
            return best[1]
        if best:
            return best[1]
    return None


def download_file(url: str, target_path: Path) -> bool:
    """下载文件并打印进度；失败时回退 PowerShell（均不走失效代理）。"""
    last_error = None
    try:
        with urlopen_direct(url, WEBDRIVER_DOWNLOAD_TIMEOUT) as response, open(target_path, "wb") as target:
            total = response.headers.get("Content-Length")
            total_n = int(total) if total and str(total).isdigit() else 0
            if total_n:
                print(f"  下载大小约 {total_n / 1024 / 1024:.1f} MB，最长等待 {WEBDRIVER_DOWNLOAD_TIMEOUT}s ...")
            copied = 0
            last_pct = -1
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                copied += len(chunk)
                if total_n:
                    pct = int(copied * 100 / total_n)
                    if pct >= last_pct + 10:
                        print(f"  下载进度 {pct}% ({copied / 1024 / 1024:.1f}/{total_n / 1024 / 1024:.1f} MB)")
                        last_pct = pct
        if target_path.exists() and target_path.stat().st_size > 0:
            print(f"  ✓ 下载完成 ({target_path.stat().st_size / 1024 / 1024:.1f} MB)")
            return True
    except Exception as e:
        last_error = e
        print(f"  ! urllib 下载失败，尝试 PowerShell: {e}")

    try:
        print(f"  PowerShell 下载中（最长 {WEBDRIVER_DOWNLOAD_TIMEOUT}s）...")
        ps_command = (
            f"$ProgressPreference='SilentlyContinue'; "
            f"Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile '{target_path}' -Proxy $null"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=WEBDRIVER_DOWNLOAD_TIMEOUT,
            check=False,
        )
        if result.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0:
            print(f"  ✓ PowerShell 下载完成 ({target_path.stat().st_size / 1024 / 1024:.1f} MB)")
            return True
        if result.stderr:
            last_error = result.stderr.strip()
    except Exception as e:
        last_error = e

    if last_error:
        print(f"  ! 下载失败: {last_error}")
    return False


def ensure_local_chromedriver(chrome_binary_path: str) -> str | None:
    """下载并缓存匹配当前 Chrome 的官方 chromedriver。"""
    chrome_version = detect_chrome_version(chrome_binary_path)
    if not chrome_version:
        print("  ! 无法识别 Chrome 版本")
        return None
    print(f"  本机 Chrome: {chrome_version}")

    driver_version = resolve_chromedriver_version(chrome_version)
    if not driver_version:
        print("  ! 无法解析 chromedriver 版本")
        return None

    existing_driver = find_existing_chromedriver(driver_version)
    if existing_driver:
        print(f"  使用已缓存 chromedriver: {Path(existing_driver).parent.parent.name if 'webdriver_cache' in existing_driver else driver_version}")
        print(f"  路径: {existing_driver}")
        return existing_driver

    cache_root = Path(__file__).parent / CHROMEDRIVER_CACHE_DIR / driver_version
    driver_dir = cache_root / f"chromedriver-{CHROMEDRIVER_PLATFORM}"
    driver_path = driver_dir / "chromedriver.exe"
    if driver_path.exists() and driver_path.stat().st_size > 0:
        return str(driver_path)

    cache_root.mkdir(parents=True, exist_ok=True)
    zip_path = cache_root / "chromedriver.zip"
    # 清理上次未完成的损坏 zip，避免文件锁/半截包
    if zip_path.exists() and zip_path.stat().st_size < 1_000_000:
        try:
            zip_path.unlink()
        except Exception:
            pass

    download_url = (
        f"https://storage.googleapis.com/chrome-for-testing-public/"
        f"{driver_version}/{CHROMEDRIVER_PLATFORM}/chromedriver-{CHROMEDRIVER_PLATFORM}.zip"
    )

    try:
        print(f"  本地无可用缓存，开始下载 chromedriver {driver_version} ...")
        if not download_file(download_url, zip_path):
            # 下载失败时再扫一次同大版本缓存
            fallback = find_existing_chromedriver(driver_version)
            if fallback:
                return fallback
            raise RuntimeError("下载结果为空或下载失败")

        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(cache_root)
        print(f"  ✓ 已解压到 {driver_dir}")
    except Exception as e:
        print(f"  ! 下载 chromedriver 失败: {e}")
        fallback = find_existing_chromedriver(driver_version)
        if fallback:
            return fallback
        return None
    finally:
        if zip_path.exists():
            try:
                zip_path.unlink(missing_ok=True)
            except Exception:
                pass

    if driver_path.exists() and driver_path.stat().st_size > 0:
        return str(driver_path)

    print("  ! chromedriver 解压后未找到可执行文件")
    return None


def build_chrome_options(*, incognito: bool = True, profile_dir: Path | None = None):
    """构建 Chrome 启动参数。Tidal 登录用 profile_dir（非无痕）。"""
    options = webdriver.ChromeOptions()
    if incognito:
        options.add_argument("--incognito")
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
        options.add_argument("--profile-directory=Default")

    chrome_binary = resolve_chrome_binary_path()
    if chrome_binary:
        options.binary_location = chrome_binary

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--start-maximized")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-hang-monitor")
    return options


def init_chrome_driver_with_retry(scene_name: str, *, incognito: bool = True, profile_dir: Path | None = None):
    """稳定启动 Chrome：本地缓存官方驱动 + 显式 Service + 重试。"""
    last_error = None
    chrome_binary = resolve_chrome_binary_path()
    if not chrome_binary:
        print(f"✗ {scene_name} 浏览器初始化失败：未找到 Chrome 安装路径")
        return None

    driver_path = ensure_local_chromedriver(chrome_binary)
    if not driver_path:
        print(f"✗ {scene_name} 浏览器初始化失败：无法准备 chromedriver")
        return None

    if profile_dir is not None:
        _cleanup_tidal_browser_leftovers()

    driver = None
    service = None
    for attempt in range(1, WEBDRIVER_STARTUP_RETRIES + 1):
        try:
            if attempt > 1:
                print(f"  第 {attempt}/{WEBDRIVER_STARTUP_RETRIES} 次重试启动浏览器...")
                if profile_dir is not None:
                    _cleanup_tidal_browser_leftovers()

            options = build_chrome_options(incognito=incognito, profile_dir=profile_dir)
            service = Service(executable_path=driver_path)
            driver = webdriver.Chrome(service=service, options=options)
            try:
                driver.set_page_load_timeout(30)
                driver.set_script_timeout(20)
            except Exception:
                pass
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                """
            })
            return driver
        except Exception as e:
            last_error = e
            print(f"  ! {scene_name} 浏览器启动失败（第 {attempt} 次）: {e}")
            _safely_dispose_chrome_attempt(driver, service)
            driver = None
            service = None
            if attempt < WEBDRIVER_STARTUP_RETRIES:
                time.sleep(WEBDRIVER_STARTUP_RETRY_DELAY)

    print(f"✗ {scene_name} 浏览器初始化失败，已重试 {WEBDRIVER_STARTUP_RETRIES} 次")
    if last_error:
        print(f"  最终错误: {last_error}")
    return None


def _cleanup_chrome_using_profile(profile_dir: Path) -> None:
    """关闭仍占用指定 user-data-dir 的孤儿 Chrome 进程（Windows）。"""
    if not profile_dir:
        return
    marker = profile_dir.name.replace("'", "''")
    ps_script = (
        f"$m='{marker}'; "
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*'+$m+'*')) } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception:
        pass
    time.sleep(0.4)


def _cleanup_webdriver_chrome_orphans() -> None:
    """关闭 Selenium/chromedriver 启动的孤儿 Chrome（含 profile 被占用时的空窗口）。"""
    ps_script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" -ErrorAction SilentlyContinue | "
        "Where-Object { "
        "  $_.CommandLine -and ("
        "    $_.CommandLine -like '*--enable-automation*' -or "
        "    $_.CommandLine -like '*--test-type=webdriver*' -or "
        "    $_.CommandLine -like '*--remote-debugging-port*'"
        "  ) "
        "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception:
        pass


def _cleanup_chromedriver_orphans() -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "chromedriver.exe"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:
        pass


def _cleanup_tidal_browser_leftovers() -> None:
    """登录前/后清理 Tidal 相关孤儿 Chrome 与 chromedriver。"""
    profile = Path(__file__).parent / TIDAL_CHROME_PROFILE_DIR
    _cleanup_chrome_using_profile(profile)
    _cleanup_webdriver_chrome_orphans()
    _cleanup_chromedriver_orphans()
    time.sleep(0.3)


def _safely_dispose_chrome_attempt(driver, service) -> None:
    """启动失败或重试前，清理本次尝试残留的 driver / chromedriver。"""
    _quit_chrome_driver(driver, "启动失败清理")
    try:
        if service and getattr(service, "process", None):
            service.process.kill()
    except Exception:
        pass


def _quit_chrome_driver(driver, label: str = "") -> None:
    """关闭 Selenium Chrome 实例，释放内存。"""
    if driver is None:
        return
    suffix = f" ({label})" if label else ""
    try:
        print(f"  关闭 Chrome{suffix}...")
        driver.quit()
    except Exception:
        try:
            driver.close()
        except Exception:
            pass
    try:
        if getattr(driver, "service", None):
            driver.service.stop()
    except Exception:
        pass


def init_tidal_browser(*, incognito: bool = False):
    """初始化 Tidal OAuth 浏览器。默认持久化配置；selenium 模式用无痕。"""
    if not SELENIUM_AVAILABLE:
        print("✗ 错误：未安装 selenium，请运行: pip install selenium")
        return None
    try:
        if incognito:
            print("  启动 Chrome（无痕模式，Tidal 登录）...")
            return init_chrome_driver_with_retry("Tidal", incognito=True)
        profile = Path(__file__).parent / TIDAL_CHROME_PROFILE_DIR
        print(f"  启动 Chrome（Tidal 专用配置: {TIDAL_CHROME_PROFILE_DIR}）...")
        return init_chrome_driver_with_retry("Tidal", incognito=False, profile_dir=profile)
    except Exception as e:
        print(f"✗ 浏览器初始化失败: {e}")
        return None


def _tidal_find_switch_account_button(driver):
    for btn in driver.find_elements(By.CSS_SELECTOR, "button.btn-secondary-outline"):
        try:
            if btn.is_displayed() and "switch account" in (btn.text or "").lower():
                return btn
        except Exception:
            continue
    try:
        return driver.find_element(
            By.XPATH,
            "//button[contains(@class,'btn-secondary-outline') and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'switch account')]",
        )
    except Exception:
        return None


def _tidal_has_email_input(driver) -> bool:
    try:
        for el in driver.find_elements(
            By.CSS_SELECTOR, "input#email, input[name='email'], input[type='email']"
        ):
            if el.is_displayed():
                return True
    except Exception:
        pass
    return False


def _tidal_match_template_in_png(
    png_bytes: bytes,
    template_path: Path,
    threshold: float,
    scales: tuple[float, ...] | None = None,
) -> tuple[tuple[int, int] | None, float, float | None]:
    """多尺度模板匹配，返回 (中心点, 最高分, 命中时的缩放比例)。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("    ⚠ 未安装 opencv-python，跳过登录历史图像识别")
        return None, 0.0, None

    haystack = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
    template = cv2.imread(str(template_path))
    if haystack is None or template is None:
        return None, 0.0, None

    hay_gray = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY)
    tpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    th0, tw0 = tpl_gray.shape[:2]
    h_h, h_w = hay_gray.shape[:2]

    best_val = 0.0
    best_center: tuple[int, int] | None = None
    best_scale: float | None = None
    scale_list = scales or TIDAL_SWITCH_ACCOUNT_MATCH_SCALES

    for scale in scale_list:
        tw = max(10, int(tw0 * scale))
        th = max(6, int(th0 * scale))
        if tw >= h_w or th >= h_h:
            continue
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        tpl = cv2.resize(tpl_gray, (tw, th), interpolation=interp)
        result = cv2.matchTemplate(hay_gray, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_val:
            best_val = float(max_val)
            best_center = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
            best_scale = scale

    if best_val < threshold:
        return None, best_val, best_scale
    return best_center, best_val, best_scale


def _tidal_dismiss_login_history_if_present(driver) -> bool:
    """
    OAuth 页若出现「记住上次账号」：
    等待切换按钮出现 → 多尺度图像匹配（阈值 0.9）→ 命中则点击 DOM 切换账号。
    """
    base = Path(__file__).parent
    template = base / TIDAL_SWITCH_ACCOUNT_TEMPLATE
    if not template.exists():
        return False

    # 等待：邮箱输入框 或 切换账号按钮
    try:
        WebDriverWait(driver, 15).until(
            lambda d: _tidal_has_email_input(d) or _tidal_find_switch_account_button(d) is not None
        )
    except Exception:
        pass

    switch_btn = _tidal_find_switch_account_button(driver)
    if not switch_btn:
        print("    · 无登录历史页")
        return False

    if _tidal_has_email_input(driver):
        # 同时有邮箱框则不是纯历史页，不处理
        print("    · 已是邮箱输入页")
        return False

    time.sleep(0.6)
    png = driver.get_screenshot_as_png()
    center, score, scale = _tidal_match_template_in_png(
        png,
        template,
        TIDAL_SWITCH_ACCOUNT_MATCH_THRESHOLD,
    )
    if center is None:
        try:
            debug = base / "tidal_assets" / "login_history_debug.png"
            Path(debug).write_bytes(png)
            print(
                f"    · 图像未达 {TIDAL_SWITCH_ACCOUNT_MATCH_THRESHOLD} "
                f"(best={score:.2f}, scale={scale})，已保存 {debug.name}"
            )
        except Exception:
            print(f"    · 图像未达阈值 (best={score:.2f})")
        return False

    print(
        f"    ✓ 检测到登录历史页 (match={score:.2f}, scale={scale})，点击切换账号"
    )
    try:
        switch_btn = _tidal_find_switch_account_button(driver) or switch_btn
        switch_btn.click()
        time.sleep(1.5)
        WebDriverWait(driver, 12).until(
            lambda d: _tidal_has_email_input(d)
        )
        print("    ✓ 已进入邮箱输入页")
        return True
    except Exception as e:
        print(f"    ⚠ 切换账号后未出现邮箱框: {e}")
        return False


def _tidal_has_password_input(driver) -> bool:
    try:
        for el in driver.find_elements(
            By.CSS_SELECTOR, "input#password, input[type='password']"
        ):
            if el.is_displayed():
                return True
    except Exception:
        pass
    return False


def _tidal_find_login_with_password_button(driver):
    for btn in driver.find_elements(
        By.CSS_SELECTOR, "button.login-with-password, button.plain-button.login-with-password"
    ):
        try:
            if btn.is_displayed() and "password" in (btn.text or "").lower():
                return btn
        except Exception:
            continue
    try:
        return driver.find_element(
            By.XPATH,
            "//button[contains(@class,'login-with-password')]",
        )
    except Exception:
        return None


def _tidal_try_switch_to_password_login(driver) -> bool:
    """
    邮箱 Continue 后若进入「Check your email」验证码页：
    用图3模板匹配（阈值 0.9），成功则点击「Log in with password」再输密码。
    """
    base = Path(__file__).parent
    template = base / TIDAL_LOGIN_WITH_PASSWORD_TEMPLATE
    if not template.exists():
        return False

    try:
        WebDriverWait(driver, 10).until(
            lambda d: _tidal_find_login_with_password_button(d) is not None
            or _tidal_has_password_input(d)
        )
    except Exception:
        pass

    if _tidal_has_password_input(driver):
        print("    · 已在密码输入页")
        return False

    pwd_link = _tidal_find_login_with_password_button(driver)
    if not pwd_link:
        print("    · 无验证码页 / Log in with password 入口")
        return False

    time.sleep(0.6)
    png = driver.get_screenshot_as_png()
    center, score, scale = _tidal_match_template_in_png(
        png,
        template,
        TIDAL_LOGIN_WITH_PASSWORD_MATCH_THRESHOLD,
    )
    if center is None:
        print(
            f"    · 图像未达 {TIDAL_LOGIN_WITH_PASSWORD_MATCH_THRESHOLD} "
            f"(best={score:.2f}, scale={scale})，按原流程继续"
        )
        return False

    print(
        f"    ✓ 检测到验证码页 (match={score:.2f}, scale={scale})，"
        f"点击 Log in with password"
    )
    try:
        pwd_link = _tidal_find_login_with_password_button(driver) or pwd_link
        pwd_link.click()
        time.sleep(1.5)
        WebDriverWait(driver, 12).until(
            lambda d: _tidal_has_password_input(d)
        )
        print("    ✓ 已进入密码输入页")
        return True
    except Exception as e:
        print(f"    ⚠ 点击 Log in with password 后未出现密码框: {e}")
        return False


def _tidal_page_blocked(driver) -> bool:
    try:
        text = driver.find_element(By.TAG_NAME, "body").text
        blocked_markers = ("访问暂时受限", "Access temporarily restricted", "Access Restricted")
        return any(m in text for m in blocked_markers)
    except Exception:
        return False


def _tidal_set_input_value(driver, element, value: str) -> None:
    driver.execute_script(
        """
        const el = arguments[0];
        const val = arguments[1];
        el.focus();
        el.value = val;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        """,
        element,
        value,
    )


def _tidal_click_primary_continue(driver, exclude_social: bool = True) -> bool:
    buttons = driver.find_elements(By.CSS_SELECTOR, "button")
    for btn in buttons:
        try:
            label = (btn.text or "").strip().lower()
            if exclude_social and ("google" in label or "apple" in label):
                continue
            if "continue" in label or label == "log in":
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    return True
        except Exception:
            continue
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button.btn-primary[type='submit']")
        if btn.is_enabled():
            btn.click()
            return True
    except Exception:
        pass
    return False


def _tidal_oauth_page_debug(driver) -> str:
    try:
        url = driver.current_url or "(空)"
        title = driver.title or "(无标题)"
        return f"url={url}, title={title}"
    except Exception as e:
        return f"无法读取页面: {e}"


def _start_tidal_oauth_session(session):
    """device authorization；网络/代理异常时重试。"""
    last_error = None
    for attempt in range(1, TIDAL_OAUTH_API_RETRIES + 1):
        try:
            configure_tidal_session_network(session)
            return session.get_link_login()
        except Exception as e:
            last_error = e
            err = str(e)
            if "Proxy" in err or "proxy" in err or "17890" in err:
                sanitize_stale_process_proxy()
                configure_tidal_session_network(session)
            retryable = any(
                token in err.lower()
                for token in ("ssl", "eof", "connection", "timeout", "timed out", "max retries", "proxy", "17890")
            )
            if retryable and attempt < TIDAL_OAUTH_API_RETRIES:
                wait_s = 2 * attempt
                print(f"  ! OAuth API 失败，{wait_s}s 后重试 ({attempt}/{TIDAL_OAUTH_API_RETRIES}): {e}")
                time.sleep(wait_s)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("OAuth API 请求失败")


def auto_complete_tidal_oauth(driver, auth_url: str, email: str, password: str) -> bool:
    """全自动完成 Tidal OAuth：打开链接、填邮箱/密码、Continue。"""
    try:
        print(f"  正在自动完成 OAuth 登录: {email}")
        driver.get(auth_url)
        time.sleep(3)

        if _tidal_page_blocked(driver):
            print("    ✗ Tidal 返回「访问受限」，请切换 VPN 节点后重试")
            try:
                driver.save_screenshot("vpn_assets/tidal_blocked.png")
            except Exception:
                pass
            return False

        _tidal_dismiss_login_history_if_present(driver)

        # 邮箱
        email_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "input#email, input[name='email'], input[type='email']",
            ))
        )
        email_input.click()
        time.sleep(0.3)
        _tidal_set_input_value(driver, email_input, email)
        email_input.send_keys(Keys.TAB)
        time.sleep(0.5)
        print("    ✓ 已输入邮箱")

        def _continue_ready(d):
            for btn in d.find_elements(By.CSS_SELECTOR, "button"):
                label = (btn.text or "").strip().lower()
                if "google" in label or "apple" in label:
                    continue
                if ("continue" in label or btn.get_attribute("type") == "submit") and btn.is_displayed():
                    return btn.is_enabled()
            return False

        WebDriverWait(driver, 15).until(_continue_ready)
        if not _tidal_click_primary_continue(driver):
            raise RuntimeError("Continue 按钮不可点击")
        print("    ✓ 已点击 Continue（邮箱）")
        time.sleep(2)

        if _tidal_page_blocked(driver):
            print("    ✗ 密码页前被风控拦截")
            return False

        _tidal_try_switch_to_password_login(driver)

        # 密码
        password_input = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input#password, input[type='password']"))
        )
        password_input.click()
        time.sleep(0.3)
        _tidal_set_input_value(driver, password_input, password)
        time.sleep(0.5)
        print("    ✓ 已输入密码")

        if not _tidal_click_primary_continue(driver):
            login_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((
                    By.CSS_SELECTOR,
                    "button[ui-test-id='login-user-login-button'], button[type='submit']",
                ))
            )
            login_btn.click()
        print("    ✓ 已点击 Log In")
        time.sleep(3)

        # 设备链接页 Continue
        try:
            WebDriverWait(driver, 15).until(
                lambda d: any(
                    "continue" in (b.text or "").lower()
                    for b in d.find_elements(By.CSS_SELECTOR, "button.btn-primary, button[type='button']")
                )
            )
            _tidal_click_primary_continue(driver)
            print("    ✓ 已点击 Continue（设备链接）")
        except Exception:
            print("    ⚠ 未检测到设备链接页，可能已自动完成")

        time.sleep(2)
        print("  ✓ OAuth 浏览器流程完成")
        return True

    except Exception as e:
        print(f"  ✗ OAuth 自动登录失败: {e}")
        try:
            driver.save_screenshot("vpn_assets/tidal_oauth_fail.png")
        except Exception:
            pass
        return False


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

def _normalize_tidal_oauth_url(url: str) -> str:
    if url and not url.startswith("http"):
        return "https://" + url
    return url


def _tidal_browser_oauth_linked(driver) -> bool:
    """浏览器是否已显示设备链接成功页。"""
    try:
        text = driver.find_element(By.TAG_NAME, "body").text.lower()
        markers = (
            "successfully linked",
            "device was successfully linked",
            "you can now enjoy",
        )
        return any(m in text for m in markers)
    except Exception:
        return False


def _exchange_tidal_device_token(session, link_login, deadline: float) -> bool:
    """用设备码兑换 access token。单次请求有超时，失败会重试到 deadline。"""
    url = session.config.api_oauth2_token
    payload = {
        "client_id": session.config.client_id,
        "device_code": link_login.device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "scope": "r_usr w_usr w_sub",
    }
    secret = getattr(session.config, "client_secret", None)
    if secret:
        payload["client_secret"] = secret

    interval = max(TIDAL_OAUTH_CHECK_INTERVAL, float(getattr(link_login, "interval", 2) or 2))
    last_note = 0.0
    print("    · 正在向 Tidal 兑换设备 token...")
    while time.time() < deadline:
        remain = max(0, int(deadline - time.time()))
        try:
            resp = session.request_session.post(url, data=payload, timeout=TIDAL_HTTP_TIMEOUT)
            try:
                body = resp.json()
            except Exception:
                body = {}
            if resp.ok and body.get("access_token"):
                last_exc = None
                for _ in range(3):
                    try:
                        session.process_auth_token(body, is_pkce_token=False)
                        return True
                    except Exception as e:
                        last_exc = e
                        print(f"    · 已拿到 token，拉取会话失败，将重试: {e}")
                        time.sleep(1.5)
                print(f"  ✗ 会话初始化失败: {last_exc}")
                return False

            err = str(body.get("error") or f"HTTP {resp.status_code}")
            if err == "expired_token":
                print("  ✗ 设备授权码已过期")
                return False
            if err == "slow_down":
                interval = min(interval + 2.0, 8.0)
            now = time.time()
            if now - last_note >= 8:
                print(f"    · 正在兑换设备 token（{err}，剩余 {remain}s）")
                last_note = now
        except Exception as e:
            now = time.time()
            if now - last_note >= 8:
                print(f"    · token 请求未完成，将重试（剩余 {remain}s）: {e}")
                last_note = now
        time.sleep(min(interval, max(0.2, deadline - time.time())))
    return False


def _wait_tidal_oauth_session_ready(session, link_login, driver) -> bool:
    """
    浏览器 OAuth 流程结束后，自己轮询设备码兑换 token。
    不再使用 tidalapi 后台 future：其 POST 没有超时，套接字挂起时终端会一直停在「设备链接成功」。
    """
    timeout = TIDAL_OAUTH_WAIT_TIMEOUT
    deadline = time.time() + timeout
    print(f"  等待 OAuth 验证完成（最长 {timeout} 秒，含重试）...")

    if driver:
        try:
            if _tidal_browser_oauth_linked(driver):
                print("    ✓ 浏览器已显示设备链接成功")
        except Exception as e:
            print(f"    · 读取浏览器结果失败，继续兑换 token: {e}")

    if not _exchange_tidal_device_token(session, link_login, deadline):
        return False

    for _ in range(3):
        try:
            if session.check_login():
                return True
        except Exception as e:
            print(f"  ⚠ 登录状态确认失败，将重试: {e}")
        time.sleep(1)

    user_id = getattr(getattr(session, "user", None), "id", None)
    if session.access_token and user_id:
        print("  ⚠ 订阅接口暂不可用，但 token 已就绪，继续后续操作")
        return True
    return False


def login_tidal_with_mcp_handoff(email: str, password: str, timeout: int | None = None):
    """
    启动 Tidal OAuth，写出待登录信息，阻塞等待 Agent 用 Cursor MCP 浏览器完成登录。

    MCP 操作步骤（Agent 执行，非 Selenium）：
      1. browser_navigate -> auth_url（或 https://link.tidal.com）
      2. 填入邮箱 -> Continue
      3. 填入密码 -> Log In
      4. Link your device 页 -> Continue
    """
    if not TIDAL_AVAILABLE:
        print("✗ 错误：未安装 tidalapi，请运行: pip install tidalapi")
        return None

    wait_seconds = timeout or TIDAL_MCP_LOGIN_TIMEOUT
    session = tidalapi.Session()
    configure_tidal_session_network(session)

    cred_path = Path(TIDAL_CREDENTIALS_FILE)
    if cred_path.exists():
        cred_path.unlink()

    print(f"\n开始 Tidal OAuth（MCP 浏览器）: {email}")
    login_info, future = session.login_oauth()
    auth_url = _normalize_tidal_oauth_url(login_info.verification_uri_complete)

    pending = {
        "email": email,
        "password": password,
        "auth_url": auth_url,
        "verification_uri": login_info.verification_uri,
        "user_code": login_info.user_code,
        "login_mode": "mcp",
        "started_at": datetime.now().isoformat(),
        "mcp_steps": [
            f"browser_navigate {auth_url}",
            "browser_fill 邮箱 -> browser_press_key Tab（启用 Continue）",
            "browser_click Continue",
            "browser_fill 密码 -> browser_click Log In",
            "browser_click Continue（设备链接页）",
        ],
    }
    Path(TIDAL_OAUTH_PENDING_FILE).write_text(
        json.dumps(pending, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=" * 60)
    print("请在 Cursor MCP 浏览器中完成登录：")
    print(f"  OAuth URL: {auth_url}")
    print(f"  账号: {email}")
    print(f"  待登录信息: {TIDAL_OAUTH_PENDING_FILE}")
    print(f"  等待 OAuth 完成（最长 {wait_seconds} 秒）...")
    print("=" * 60)

    try:
        future.result(timeout=wait_seconds)
    except Exception as e:
        print(f"✗ OAuth 等待超时或失败: {e}")
        return None

    if session.check_login():
        print(f"✓ Tidal 登录成功！用户: {session.user.first_name} {session.user.last_name}")
        save_tidal_credentials(session)
        Path(TIDAL_OAUTH_PENDING_FILE).unlink(missing_ok=True)
        return session

    print("✗ Tidal 登录验证失败")
    return None


def login_tidal_account(email: str, password: str, login_mode: str | None = None):
    """登录 Tidal：auto/selenium=Python 全自动浏览器，mcp=Agent handoff。"""
    mode = (login_mode or TIDAL_LOGIN_MODE).lower()
    if mode == "mcp":
        session = login_tidal_with_mcp_handoff(email, password)
        return session, None
    incognito = mode == "selenium"
    return login_tidal_with_automation(email, password, incognito=incognito)


def login_tidal():
    """登录 Tidal，返回 session 对象（每次强制重新登录）"""
    if not TIDAL_AVAILABLE:
        print("✗ 错误：未安装 tidalapi，请运行: pip install tidalapi")
        return None
    
    session = tidalapi.Session()
    configure_tidal_session_network(session)
    
    # 删除旧的凭据文件（强制重新登录）
    cred_path = Path(TIDAL_CREDENTIALS_FILE)
    if cred_path.exists():
        cred_path.unlink()
        print("✓ 已清除旧的登录凭据")
    
    # 直接进行 OAuth 登录
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


def login_tidal_with_automation(email: str, password: str, *, incognito: bool = False):
    """
    使用自动化浏览器登录 Tidal
    
    Args:
        email: Tidal 账号邮箱
        password: Tidal 账号密码
    
    Returns:
        (session, driver) 元组，登录成功返回 session 和 driver，失败返回 (None, None)
    """
    if not TIDAL_AVAILABLE:
        print("✗ 错误：未安装 tidalapi，请运行: pip install tidalapi")
        return None, None
    
    if not SELENIUM_AVAILABLE:
        print("✗ 错误：未安装 selenium，请运行: pip install selenium")
        return None, None
    
    session = tidalapi.Session()
    configure_tidal_session_network(session)
    driver = None
    logged_in = False

    try:
        # 删除旧的凭据文件（强制重新登录）
        cred_path = Path(TIDAL_CREDENTIALS_FILE)
        if cred_path.exists():
            cred_path.unlink()

        # 先开浏览器，再请求 OAuth（API 失败时浏览器已打开，便于排查）
        print(f"\n开始 Tidal OAuth 验证: {email}")

        driver = init_tidal_browser(incognito=incognito)
        if not driver:
            print("✗ 无法启动浏览器")
            return None, None

        login_info = _start_tidal_oauth_session(session)
        auth_url = login_info.verification_uri_complete
        if auth_url and not auth_url.startswith("http"):
            auth_url = "https://" + auth_url
        print(f"  OAuth 链接: {auth_url}")

        success = auto_complete_tidal_oauth(driver, auth_url, email, password)
        if not success:
            print("✗ 自动 OAuth 登录失败")
            return None, None

        if not _wait_tidal_oauth_session_ready(session, login_info, driver):
            print("✗ Tidal 登录验证失败")
            return None, None

        print(f"✓ Tidal 登录成功！用户: {session.user.first_name} {session.user.last_name}")
        save_tidal_credentials(session)
        logged_in = True
        return session, None

    except Exception as e:
        print(f"✗ Tidal 自动登录过程出错: {e}")
        if driver:
            print(f"  调试: {_tidal_oauth_page_debug(driver)}")
        return None, None

    finally:
        if driver:
            if not logged_in:
                print(
                    f"  登录未成功，浏览器将保留 {TIDAL_OAUTH_FAILURE_BROWSER_PAUSE} 秒便于查看当前页面..."
                )
                time.sleep(TIDAL_OAUTH_FAILURE_BROWSER_PAUSE)
            _quit_chrome_driver(driver, "Tidal OAuth")
            if logged_in:
                _cleanup_tidal_browser_leftovers()
                print("  OAuth 浏览器已关闭，后续使用 API 操作")


def refresh_tidal_session(session):
    """刷新 Tidal session（当 token 过期时）"""
    try:
        # 尝试使用 refresh_token 刷新
        if hasattr(session, 'token_refresh') and session.refresh_token:
            session.token_refresh(session.refresh_token)
            if session.check_login():
                print("✓ Tidal token 刷新成功")
                save_tidal_credentials(session)
                return True
    except Exception as e:
        print(f"  Token 刷新失败: {e}")
    
    # 刷新失败，需要重新 OAuth 登录
    print("\n⚠ Token 已过期，需要重新登录...")
    print("请在浏览器中完成登录:")
    try:
        login_info, future = session.login_oauth()
        print(f">>> 链接: {login_info.verification_uri_complete}")
        print(f">>> 或访问 {login_info.verification_uri} 并输入代码: {login_info.user_code}")
        print("\n等待登录完成...")
        
        future.result()
        
        if session.check_login():
            print(f"✓ Tidal 重新登录成功！用户: {session.user.first_name} {session.user.last_name}")
            save_tidal_credentials(session)
            return True
    except Exception as e:
        print(f"✗ 重新登录失败: {e}")
    
    return False

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
    """标记播放列表名称为已使用（选定即写入，避免中途失败后重跑复用）。"""
    if not name:
        return
    used_names = load_playlist_history()
    if name not in used_names:
        used_names.append(name)
        save_playlist_history(used_names)
        print(f"  ✓ 已标记播放列表名称为已使用: {name}")


def claim_next_playlist_name(*, exclude: set[str] | None = None) -> str | None:
    """获取并立即占用下一个可用播放列表名称。"""
    exclude = exclude or set()
    all_names = load_available_playlist_names()
    used_names = load_playlist_history()
    blocked = set(used_names) | set(exclude)

    for name in all_names:
        if name not in blocked:
            mark_playlist_name_used(name)
            return name

    print("⚠ 所有播放列表名称都已使用，将重置历史记录")
    save_playlist_history([])
    if not all_names:
        return None
    for name in all_names:
        if name not in exclude:
            mark_playlist_name_used(name)
            return name
    name = all_names[0]
    mark_playlist_name_used(name)
    return name


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

def search_album_on_tidal(session, artist_name: str, album_name: str, retry_on_401=True):
    """在 Tidal 上搜索专辑（支持401错误自动重试，多种搜索策略）"""
    
    def do_search(query):
        """ 执行单次搜索"""
        try:
            results = session.search(query, models=[tidalapi.album.Album])
            albums = None
            if isinstance(results, dict):
                albums = results.get('albums', [])
            elif hasattr(results, 'albums'):
                albums = results.albums
            return albums if albums else []
        except Exception as e:
            error_str = str(e)
            if "401" in error_str and retry_on_401:
                return "401_ERROR"
            return []
    
    # 策略1: 完整搜索词（艺人名 + 专辑名）
    search_queries = [
        f"{artist_name} {album_name}",  # 完整搜索
        album_name,                       # 只搜专辑名
        artist_name,                      # 只搜艺人名
    ]
    
    for query in search_queries:
        albums = do_search(query)
        
        # 处理401错误
        if albums == "401_ERROR":
            print(f"  ⚠ 认证失效，尝试刷新session...")
            if refresh_tidal_session(session):
                return search_album_on_tidal(session, artist_name, album_name, retry_on_401=False)
            else:
                print(f"  ✗ 刷新session失败")
                return None
        
        if not albums:
            continue
        
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
            # 放宽匹配：专辑名包含关系（两个方向都检查）
            album_match = (
                album_name.lower() in album_name_attr.lower() or 
                album_name_attr.lower() in album_name.lower()
            ) if album_name_attr else False
            
            if artist_match and album_match:
                return album
        
        # 如果是第一个搜索词（完整搜索），返回第一个结果
        if query == search_queries[0] and albums:
            return albums[0]
    
    return None

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

def add_tracks_to_playlist_with_delay(session, playlist, tracks, track_count: int):
    """将歌曲添加到播放列表（优先批量添加，支持401/412重试与降级）"""
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
    
    track_ids = [track.id for track in tracks_to_add]
    added_count = 0
    retry_401_done = False

    def _refresh_playlist_ref(cur_playlist):
        """按 ID 重新获取播放列表实例，避免 session 刷新后继续使用旧对象。"""
        playlist_id = getattr(cur_playlist, "id", None)
        if not playlist_id:
            return cur_playlist
        try:
            for item in session.user.playlists():
                if getattr(item, "id", None) == playlist_id:
                    return item
        except Exception:
            pass
        return cur_playlist

    # 先尝试批量添加（更稳定，也能显著减少请求次数）
    try:
        playlist.add(track_ids)
        return len(track_ids)
    except Exception as e:
        error_str = str(e)

        if "401" in error_str and not retry_401_done:
            print("    ⚠ 认证状态失效，正在刷新 session 后重试批量添加...")
            if refresh_tidal_session(session):
                retry_401_done = True
                playlist = _refresh_playlist_ref(playlist)
                try:
                    playlist.add(track_ids)
                    return len(track_ids)
                except Exception as e2:
                    error_str = str(e2)
                    print(f"    ⚠ 批量重试仍失败，降级为逐首添加: {e2}")
            else:
                print("    ✗ 刷新 session 失败，跳过本专辑")
                return 0

        elif "412" in error_str:
            print("    ⚠ 批量添加返回 412，先刷新 session/凭证，再刷新播放列表后重试...")
            if refresh_tidal_session(session):
                retry_401_done = True
                playlist = _refresh_playlist_ref(playlist)
                try:
                    playlist.add(track_ids)
                    return len(track_ids)
                except Exception as e2:
                    print(f"    ⚠ 批量重试仍失败，降级为逐首添加: {e2}")
            else:
                print(f"    ⚠ session 刷新失败，降级为逐首添加: {e}")
        else:
            print(f"    ⚠ 批量添加失败，降级为逐首添加: {e}")

    # 降级方案：逐首添加，尽量保住部分成功率
    for track in tracks_to_add:
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                playlist.add([track.id])
                added_count += 1
                random_delay()
                break
            except Exception as e:
                error_str = str(e)
                if "401" in error_str and not retry_401_done:
                    print("    ⚠ 逐首添加遇到 401，尝试刷新 session...")
                    if refresh_tidal_session(session):
                        retry_401_done = True
                        playlist = _refresh_playlist_ref(playlist)
                        continue
                    else:
                        print("    ✗ 刷新 session 失败，停止本专辑添加")
                        return added_count
                if "412" in error_str and attempt < max_attempts - 1:
                    if not retry_401_done and refresh_tidal_session(session):
                        retry_401_done = True
                    playlist = _refresh_playlist_ref(playlist)
                    time.sleep(random.uniform(0.8, 1.5))
                    continue
                print(f"    ✗ 添加歌曲失败: {e}")
                break

    return added_count

def process_tidal_playlist(session, txt_path: Path, track_count_min: int, track_count_max: int, base_dir: Path = None):
    """处理 Tidal 播放列表添加流程（支持自动补充缺失歌曲）"""
    # 解析专辑列表
    albums = parse_album_list_from_txt(txt_path)
    if not albums:
        print("✗ 未从 txt 文件中解析到专辑信息")
        return False
    
    print(f"\n解析到 {len(albums)} 张专辑待添加")
    
    # 获取播放列表名称（选定即标记，避免中断后重跑复用）
    playlist_name = claim_next_playlist_name()
    if not playlist_name:
        print("✗ 无可用的播放列表名称")
        return False
    
    print(f"\n将使用播放列表名称: {playlist_name}")
    
    # 获取或创建播放列表
    playlist, is_new = get_or_create_playlist_on_tidal(session, playlist_name)
    if is_new:
        print(f"✓ 创建播放列表: {playlist.name}")
    else:
        print(f"✓ 找到播放列表: {playlist.name}")
    
    # 为每张专辑生成一个随机的歌曲数量（在范围内不重复）
    track_counts = list(range(track_count_min, track_count_max + 1))
    random.shuffle(track_counts)
    
    # 计算预期添加的总歌曲数
    expected_total = sum(track_counts[i % len(track_counts)] for i in range(len(albums)))
    
    # 记录已处理的专辑（用于排除重复）
    processed_albums = set()  # 格式: "艺人名 - 专辑名"
    # 失败专辑明细（Tidal 原因侧重 API 搜索/加歌）
    failed_albums = []  # [{artist, album, reason, stage}, ...]
    source_index = load_artist_album_source_index("T", base_dir)
    
    def _record_tidal_failed(artist, album, reason, stage="主流程"):
        source = classify_album_source(artist, album, source_index)
        failed_albums.append({
            "artist": artist,
            "album": album,
            "reason": reason,
            "stage": stage,
            "source": source,
        })
        print(f"  ! 失败已记录 [{stage}] [{source}]: {artist} - {album} | {reason}")
    
    # 处理每张专辑
    total_added = 0
    for i, album_info in enumerate(albums):
        artist_name = album_info["artist_name"]
        album_name = album_info["album_name"]
        # 循环使用歌曲数量
        track_count = track_counts[i % len(track_counts)]
        
        # 记录已处理的专辑
        processed_albums.add(f"{artist_name} - {album_name}".lower())
        
        print(f"\n[{i+1}/{len(albums)}] 搜索: {artist_name} - {album_name}")
        random_delay()  # 搜索前延迟
        
        try:
            album = search_album_on_tidal(session, artist_name, album_name)
        except Exception as e:
            _record_tidal_failed(
                artist_name, album_name,
                f"Tidal API 搜索异常: {e}",
                stage="主流程",
            )
            random_delay()
            continue
        
        if album:
            album_display = album.name if hasattr(album, 'name') else str(album)
            artist_display = album.artist.name if hasattr(album, 'artist') and album.artist else 'Unknown'
            print(f"  ✓ 找到: {album_display} - {artist_display}")
            
            try:
                random_delay()  # 获取歌曲前延迟
                tracks = album.tracks()
                if not tracks:
                    _record_tidal_failed(
                        artist_name, album_name,
                        "API 找到专辑但曲目列表为空",
                        stage="主流程",
                    )
                else:
                    actual_track_count = min(track_count, len(tracks))
                    print(f"  专辑共 {len(tracks)} 首歌，计划添加 {actual_track_count} 首")
                    
                    added = add_tracks_to_playlist_with_delay(session, playlist, tracks, actual_track_count)
                    total_added += added
                    if added > 0:
                        print(f"  ✓ 已添加 {added} 首歌曲")
                        if added < actual_track_count:
                            print(f"  ! 部分成功：计划 {actual_track_count} 首，实际 {added} 首")
                    else:
                        _record_tidal_failed(
                            artist_name, album_name,
                            "找到专辑但 API 添加歌曲返回 0（批量/逐首失败，可能 401/412/限流或播放列表异常）",
                            stage="主流程",
                        )
            except Exception as e:
                _record_tidal_failed(
                    artist_name, album_name,
                    f"获取曲目或 API 添加异常: {e}",
                    stage="主流程",
                )
        else:
            print(f"  ✗ 未找到专辑")
            _record_tidal_failed(
                artist_name, album_name,
                "Tidal API 搜索未找到匹配专辑（检索词无结果或艺人/专辑名未匹配）",
                stage="主流程",
            )
        
        random_delay()  # 处理下一个专辑前延迟
    
    # ===== 补充缺失歌曲逻辑 =====
    missing_count = expected_total - total_added
    if missing_count > 0 and base_dir:
        print(f"\n{'='*60}")
        print(f"⚠ 预期 {expected_total} 首，实际 {total_added} 首，缺少 {missing_count} 首")
        print(f"正在从 other_artists.json 补充...")
        print(f"{'='*60}")
        
        # 加载 other_artists.json
        other_path = base_dir / OTHER_ARTISTS_FILE
        if other_path.exists():
            try:
                other_data = json.loads(other_path.read_text(encoding="utf-8"))
                
                # 构建可用的补充专辑列表（排除已处理的）
                supplement_albums = []
                for entry in other_data:
                    artist = entry.get("artist", "")
                    for album in entry.get("albums", []):
                        album_key = f"{artist} - {album}".lower()
                        if album_key not in processed_albums:
                            supplement_albums.append({
                                "artist_name": artist,
                                "album_name": album
                            })
                
                # 随机打乱补充列表
                random.shuffle(supplement_albums)
                
                supplement_idx = 0
                while missing_count > 0 and supplement_idx < len(supplement_albums):
                    album_info = supplement_albums[supplement_idx]
                    artist_name = album_info["artist_name"]
                    album_name = album_info["album_name"]
                    supplement_idx += 1
                    
                    # 标记为已处理
                    processed_albums.add(f"{artist_name} - {album_name}".lower())
                    
                    print(f"\n[补充] 搜索: {artist_name} - {album_name}")
                    random_delay()
                    
                    album = search_album_on_tidal(session, artist_name, album_name)
                    
                    if album:
                        album_display = album.name if hasattr(album, 'name') else str(album)
                        artist_display = album.artist.name if hasattr(album, 'artist') and album.artist else 'Unknown'
                        print(f"  ✓ 找到: {album_display} - {artist_display}")
                        
                        random_delay()
                        tracks = album.tracks()
                        # 补充时，取需要的数量或专辑全部歌曲（取较小值）
                        supplement_track_count = min(missing_count, len(tracks), track_count_max)
                        print(f"  专辑共 {len(tracks)} 首歌，补充 {supplement_track_count} 首")
                        
                        added = add_tracks_to_playlist_with_delay(session, playlist, tracks, supplement_track_count)
                        total_added += added
                        missing_count -= added
                        print(f"  ✓ 已补充 {added} 首歌曲，还差 {missing_count} 首")
                    else:
                        print(f"  ✗ 未找到专辑")
                    
                    random_delay()
                
                if missing_count > 0:
                    print(f"\n⚠ 补充库已用尽，仍缺少 {missing_count} 首歌曲")
                else:
                    print(f"\n✓ 补充完成！")
                    
            except Exception as e:
                print(f"✗ 加载 other_artists.json 失败: {e}")
        else:
            print(f"✗ 找不到补充文件: {other_path}")
    
    print(f"\n{'='*60}")
    print(f"✓ Tidal 播放列表添加完成！")
    print(f"  播放列表: {playlist_name}")
    print(f"  预期添加: {expected_total} 首歌曲")
    print(f"  实际添加: {total_added} 首歌曲")
    if total_added >= expected_total:
        print(f"  状态: 已完成 ✓")
    else:
        print(f"  状态: 差 {expected_total - total_added} 首")
    print_failed_albums_summary(
        failed_albums,
        platform_code="T",
        base_dir=base_dir,
        tip="  说明：Tidal 失败多为 API 搜索无匹配、曲目为空，或加歌接口 401/412/限流。",
    )
    print(f"{'='*60}")
    
    return True


def run_tidal_for_single_account(account_info: dict, account_index: int, total_accounts: int, base_dir: Path, args):
    """
    为单个 Tidal 账号执行完整的播放列表添加流程
    
    Args:
        account_info: 账号信息 {email, password}
        account_index: 当前账号索引（从 0 开始）
        total_accounts: 账号总数
        base_dir: 基础目录
        args: 命令行参数
    
    Returns:
        bool: 是否成功
    """
    email = account_info["email"]
    password = account_info["password"]
    
    print(f"\n{'='*60}")
    print(f"处理账号 [{account_index + 1}/{total_accounts}]: {email}")
    print(f"{'='*60}")
    
    # 1. 登录（默认 auto 全自动浏览器）
    session, driver = login_tidal_account(
        email, password, getattr(args, "tidal_login_mode", None)
    )
    
    if not session:
        print(f"✗ 账号 {email} 登录失败，跳过")
        return False
    
    try:
        # 2. 生成播放列表文件
        # 加载数据
        platform_file = PLATFORM_FILES.get("T")
        main_artists_path = base_dir / platform_file
        other_artists_path = base_dir / OTHER_ARTISTS_FILE
        
        main_artists = load_json_data(main_artists_path)
        other_artists = load_json_data(other_artists_path)
        
        history = load_history()
        rng = secrets.SystemRandom()
        
        main_category = f"main_T"
        other_category = "other"
        
        main_history_counts, main_recent_combos = get_category_history_data(main_category, history)
        other_history_counts, other_recent_combos = get_category_history_data(other_category, history)
        
        # 随机抽取专辑
        other_items = flatten_albums(other_artists)
        main_items = flatten_albums(main_artists)
        
        part1 = weighted_sample(other_items, other_history_counts, 1, rng, other_recent_combos, unique_artist=True)
        part2 = weighted_sample(main_items, main_history_counts, args.Count, rng, main_recent_combos, unique_artist=True)
        
        # part3 排除 part1 中已选的艺人
        part1_artists = {item.split(" - ", 1)[0] for item in part1}
        other_items_filtered = [item for item in other_items if item.split(" - ", 1)[0] not in part1_artists]
        part3 = weighted_sample(other_items_filtered, other_history_counts, 4, rng, other_recent_combos, unique_artist=True)
        
        final_list = part1 + part2 + part3
        
        # 更新历史记录
        update_history(part2, main_category, history)
        update_history(part1 + part3, other_category, history)
        save_history(history)
        
        # 写入输出文件
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_filename = f"T+{timestamp}.txt"
        output_path = base_dir / output_filename
        
        output_lines = []
        for item in final_list:
            artist, album = split_artist_album(item)
            output_lines.append(format_output_item(artist, album))
        
        output_content = "\n".join(output_lines)
        output_path.write_text(output_content, encoding="utf-8")
        
        print(f"已生成播放列表文件：{output_filename}")
        print(f"  总计: {len(final_list)} 首")
        
        # 3. 添加歌曲到 Tidal 播放列表
        print(f"\n开始添加歌曲到 Tidal 播放列表...")
        process_tidal_playlist(
            session, 
            output_path, 
            args.track_min, 
            args.track_max,
            base_dir
        )
        
        print(f"\n✓ 账号 {email} 处理完成")
        return True
        
    except Exception as e:
        print(f"✗ 账号 {email} 处理出错: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        _quit_chrome_driver(driver, "Tidal OAuth")
        _cleanup_tidal_browser_leftovers()


# ==================== Tidal 删除歌曲功能 ====================

def delete_tracks_from_tidal_playlists(session, delete_list: list[dict]) -> dict:
    """
    从用户的所有播放列表中删除指定艺人专辑的歌曲
    
    Args:
        session: Tidal session
        delete_list: [{artist, album}, ...] 要删除的艺人专辑列表
    
    Returns:
        统计信息 {total_deleted, playlists_processed, errors}
    """
    stats = {
        "total_deleted": 0,
        "playlists_processed": 0,
        "errors": []
    }
    
    if not delete_list:
        print("✗ 删除列表为空")
        return stats
    
    # 构建要删除的艺人-专辑集合（用于快速匹配）
    delete_set = set()
    for item in delete_list:
        artist = item["artist"].lower().strip()
        album = item["album"].lower().strip()
        delete_set.add((artist, album))
    
    print(f"\n将从所有播放列表中删除以下专辑的歌曲：")
    for item in delete_list:
        print(f"  - {item['artist']} - {item['album']}")
    
    # 获取用户的所有播放列表
    try:
        user_playlists = session.user.playlists()
        print(f"\n找到 {len(user_playlists)} 个播放列表")
    except Exception as e:
        print(f"✗ 获取播放列表失败: {e}")
        stats["errors"].append(f"获取播放列表失败: {e}")
        return stats
    
    # 遍历每个播放列表
    for playlist in user_playlists:
        playlist_name = playlist.name if playlist.name else "(未命名)"
        print(f"\n{'='*50}")
        print(f"处理播放列表: {playlist_name}")
        print(f"{'='*50}")
        
        stats["playlists_processed"] += 1
        
        try:
            # 获取播放列表中的所有歌曲
            tracks = playlist.tracks()
            if not tracks:
                print("  (空播放列表)")
                continue
            
            print(f"  共 {len(tracks)} 首歌曲")
            
            # 找出需要删除的歌曲
            tracks_to_delete = []
            for track in tracks:
                try:
                    # 获取歌曲的艺人和专辑信息
                    track_artist = ""
                    track_album = ""
                    
                    if hasattr(track, 'artist') and track.artist:
                        track_artist = track.artist.name.lower() if hasattr(track.artist, 'name') else str(track.artist).lower()
                    
                    if hasattr(track, 'album') and track.album:
                        track_album = track.album.name.lower() if hasattr(track.album, 'name') else str(track.album).lower()
                    
                    # 检查是否匹配删除列表
                    for del_artist, del_album in delete_set:
                        # 模糊匹配：艺人名包含关系，专辑名包含关系
                        artist_match = del_artist in track_artist or track_artist in del_artist
                        album_match = del_album in track_album or track_album in del_album
                        
                        if artist_match and album_match:
                            tracks_to_delete.append(track)
                            break
                            
                except Exception as e:
                    # 忽略单个歌曲的错误
                    continue
            
            if not tracks_to_delete:
                print("  未找到需要删除的歌曲")
                continue
            
            print(f"  找到 {len(tracks_to_delete)} 首需要删除的歌曲")
            
            # 删除歌曲
            deleted_count = 0
            for track in tracks_to_delete:
                try:
                    track_name = track.name if hasattr(track, 'name') else str(track)
                    track_artist_name = track.artist.name if hasattr(track, 'artist') and track.artist else "Unknown"
                    
                    # 使用 playlist.remove_by_index 或 playlist.remove 方法
                    # tidalapi 的 playlist 对象有 remove_by_indices 方法
                    playlist.remove_by_id(track.id)
                    deleted_count += 1
                    print(f"    ✓ 已删除: {track_artist_name} - {track_name}")
                    random_delay()  # 延迟避免请求过快
                    
                except Exception as e:
                    print(f"    ✗ 删除失败: {e}")
                    stats["errors"].append(f"删除歌曲失败: {e}")
            
            stats["total_deleted"] += deleted_count
            print(f"  本播放列表删除了 {deleted_count} 首歌曲")
            
        except Exception as e:
            print(f"  ✗ 处理播放列表出错: {e}")
            stats["errors"].append(f"处理播放列表 {playlist_name} 失败: {e}")
    
    return stats


def run_tidal_delete_for_single_account(
    account_info: dict,
    account_index: int,
    total_accounts: int,
    delete_list: list[dict],
    login_mode: str | None = None,
):
    """
    为单个 Tidal 账号执行删除歌曲操作
    
    Args:
        account_info: 账号信息 {email, password}
        account_index: 当前账号索引（从 0 开始）
        total_accounts: 账号总数
        delete_list: 要删除的艺人专辑列表
    
    Returns:
        bool: 是否成功
    """
    email = account_info["email"]
    password = account_info["password"]
    
    print(f"\n{'='*60}")
    print(f"[删除模式] 处理账号 [{account_index + 1}/{total_accounts}]: {email}")
    print(f"{'='*60}")
    
    # 1. 登录（默认 MCP 浏览器）
    session, driver = login_tidal_account(email, password, login_mode)
    
    if not session:
        print(f"✗ 账号 {email} 登录失败，跳过")
        return False
    
    try:
        # 2. 执行删除操作
        stats = delete_tracks_from_tidal_playlists(session, delete_list)
        
        print(f"\n{'='*60}")
        print(f"✓ 账号 {email} 删除完成")
        print(f"  处理播放列表数: {stats['playlists_processed']}")
        print(f"  删除歌曲总数: {stats['total_deleted']}")
        if stats['errors']:
            print(f"  错误数: {len(stats['errors'])}")
        print(f"{'='*60}")
        
        return True
        
    except Exception as e:
        print(f"✗ 账号 {email} 删除操作出错: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        _quit_chrome_driver(driver, "Tidal OAuth")
        _cleanup_tidal_browser_leftovers()


# ==================== Apple Music 集成功能 ====================

def apple_human_delay(min_sec=None, max_sec=None):
    """模拟人类操作的随机延迟（默认用 APPLE_DELAY_*）"""
    lo = APPLE_DELAY_MIN if min_sec is None else min_sec
    hi = APPLE_DELAY_MAX if max_sec is None else max_sec
    time.sleep(random.uniform(lo, hi))


def apple_song_interval():
    """歌与歌之间的间隔（约 2.5 秒）"""
    time.sleep(random.uniform(APPLE_SONG_INTERVAL_MIN, APPLE_SONG_INTERVAL_MAX))


def apple_human_typing(element, text, min_delay=0.02, max_delay=0.08):
    """模拟人类打字速度"""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def apple_move_to_element(driver, element):
    """模拟人类鼠标移动到元素"""
    actions = ActionChains(driver)
    actions.move_to_element(element)
    actions.pause(random.uniform(0.2, 0.5))
    actions.perform()


def normalize_playlist_name(name: str) -> str:
    """统一各类撇号/引号，避免 Dawn's 与 Dawn's 匹配失败。"""
    if not name:
        return ""
    text = str(name).strip().casefold()
    for ch in ("\u2018", "\u2019", "\u201A", "\u2032", "\u0060", "\u00B4", '"', "\u201C", "\u201D"):
        text = text.replace(ch, "'")
    text = re.sub(r"\s+", " ", text)
    return text


def find_apple_playlist_menu_option(driver, playlist_name: str):
    """
    在「Add to Playlist」子菜单中查找目标播放列表。
    不用把名称直接拼进 XPath（名称含 ' 会截断字符串，如 Dawn's Whisper）。
    """
    target = normalize_playlist_name(playlist_name)
    if not target:
        return None

    candidates = []
    try:
        candidates = driver.find_elements(By.CSS_SELECTOR, "span.contextual-menu-item__option-text")
    except Exception:
        return None

    skip_labels = {
        normalize_playlist_name(x)
        for x in (
            "New Playlist", "新建播放列表", "新播放清單", "Neue Playlist",
            "Add to Playlist", "添加到播放列表", "加入播放清單",
        )
    }
    exact_hit = None
    contains_hit = None
    for el in candidates:
        try:
            if not el.is_displayed():
                continue
            label = normalize_playlist_name(el.text or "")
        except Exception:
            continue
        if not label or label in skip_labels:
            continue
        if label == target:
            exact_hit = el
            break
        if target in label or label in target:
            contains_hit = contains_hit or el
    return exact_hit or contains_hit


def init_apple_browser():
    """初始化 Chrome 浏览器（无痕模式）"""
    if not SELENIUM_AVAILABLE:
        print("✗ 错误：未安装 selenium，请运行: pip install selenium")
        return None
    
    try:
        print("  启动 Chrome 浏览器...")
        driver = init_chrome_driver_with_retry("Apple")
        if not driver:
            return None
        
        # 浏览器保活已禁用（用户反馈：妨碍手工登录工作）
        # start_browser_keep_alive(driver, interval=30)  # 已禁用
        
        print("  ✓ 浏览器初始化成功")
        return driver
        
    except Exception as e:
        print(f"✗ 浏览器初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def _apple_save_debug_shot(driver, name: str) -> None:
    try:
        out = Path(APPLE_ASSETS_DIR)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{time.strftime('%H%M%S')}_{name}.png"
        driver.save_screenshot(str(path))
        print(f"    · 调试截图: {path.name}", flush=True)
    except Exception as e:
        print(f"    · 截图失败({name}): {e}", flush=True)


def _apple_step(driver, name: str, detail: str = "") -> None:
    """每一步立刻打日志并截图，便于对照界面。"""
    msg = f"STEP {name}"
    if detail:
        msg += f" {detail}"
    print(msg, flush=True)
    try:
        safe = re.sub(r"[^\w\-]+", "_", name)[:48]
        _apple_save_debug_shot(driver, f"step_{safe}")
    except Exception:
        pass


def _apple_norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def _apple_text_matches(actual: str, keywords: list[str]) -> bool:
    norm = _apple_norm_text(actual)
    if not norm:
        return False
    for kw in keywords:
        if _apple_norm_text(kw) in norm:
            return True
    return False


def _apple_safe_click(driver, element) -> bool:
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});", element
        )
    except Exception:
        pass
    try:
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def _apple_set_input_value(driver, element, value: str) -> None:
    try:
        element.click()
    except Exception:
        pass
    try:
        element.clear()
    except Exception:
        pass
    try:
        driver.execute_script(
            """
            const el = arguments[0], val = arguments[1];
            el.focus();
            const proto = window.HTMLInputElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) {
              desc.set.call(el, '');
              el.dispatchEvent(new Event('input', {bubbles:true}));
              desc.set.call(el, val);
            } else {
              el.value = val;
            }
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            el.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true}));
            """,
            element,
            value,
        )
    except Exception:
        pass
    try:
        current = element.get_attribute("value") or ""
        if current != value:
            element.send_keys(Keys.CONTROL, "a")
            element.send_keys(Keys.BACKSPACE)
            for ch in value:
                element.send_keys(ch)
                time.sleep(0.02)
    except Exception:
        try:
            element.send_keys(value)
        except Exception:
            pass


def _apple_collect_frames(driver, max_depth: int = 3, max_frames: int = 16):
    """深度优先收集可切入的 frame 路径（限制深度/数量，避免卡死）。"""
    paths = [[]]
    seen = 0

    def walk(path, depth):
        nonlocal seen
        if depth >= max_depth or seen >= max_frames:
            return
        try:
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
        except Exception:
            return
        for idx in range(min(len(frames), 8)):
            if seen >= max_frames:
                return
            child = path + [idx]
            try:
                driver.switch_to.default_content()
                ok = True
                for i in child:
                    frames_now = driver.find_elements(By.CSS_SELECTOR, "iframe")
                    if i >= len(frames_now):
                        ok = False
                        break
                    driver.switch_to.frame(frames_now[i])
                if not ok:
                    continue
                paths.append(child)
                seen += 1
                walk(child, depth + 1)
            except Exception:
                continue
        try:
            driver.switch_to.default_content()
            for i in path:
                frames_now = driver.find_elements(By.CSS_SELECTOR, "iframe")
                driver.switch_to.frame(frames_now[i])
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    walk([], 0)
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return paths


def _apple_enter_frame_path(driver, path: list[int]) -> bool:
    try:
        driver.switch_to.default_content()
        for i in path:
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
            driver.switch_to.frame(frames[i])
        return True
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return False


def _apple_find_across_frames(driver, finder, *, prefer_auth: bool = False):
    """
    在主文档及嵌套 iframe 中查找元素。
    finder(driver) -> WebElement | None
    找到后停留在对应 frame；失败回到 default。
    """
    paths = _apple_collect_frames(driver)
    if prefer_auth:
        ranked = []
        for path in paths:
            score = 0
            try:
                if _apple_enter_frame_path(driver, path):
                    # 粗判：有邮箱/密码输入或认证相关文案优先
                    html = ""
                    try:
                        html = (driver.page_source or "")[:8000].lower()
                    except Exception:
                        pass
                    if any(k in html for k in ("password", "account", "sign-in", "email", "電郵", "密码", "密碼", "驗證")):
                        score += 5
                    if path:  # 子 frame 优先于主文档的误匹配
                        score += 1
            except Exception:
                pass
            ranked.append((score, path))
        paths = [p for _, p in sorted(ranked, key=lambda x: -x[0])]

    for path in paths:
        if not _apple_enter_frame_path(driver, path):
            continue
        try:
            el = finder(driver)
            if el is not None:
                return el, path
        except Exception:
            continue
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return None, None


def _apple_visible_elements(driver, css: str):
    out = []
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            try:
                if el.is_displayed():
                    out.append(el)
            except Exception:
                continue
    except Exception:
        pass
    return out


def _apple_find_clickable_by_texts(driver, texts: list[str], tags: str = "button,a,[role='button'],div,span"):
    for el in _apple_visible_elements(driver, tags):
        try:
            label = " ".join(
                filter(
                    None,
                    [
                        el.text,
                        el.get_attribute("aria-label"),
                        el.get_attribute("value"),
                        el.get_attribute("title"),
                    ],
                )
            )
            if _apple_text_matches(label, texts):
                return el
        except Exception:
            continue
    return None


def _apple_is_logged_in(driver) -> bool:
    """快速判定：无 Sign In，且侧栏出现资料库/账户（用 JS，避免扫全页按钮卡死）。"""
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    script = r"""
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const st = window.getComputedStyle(el);
      return r.width > 1 && r.height > 1 && st.visibility !== 'hidden' && st.display !== 'none';
    };
    const signIns = document.querySelectorAll("button[data-testid='sign-in-button']");
    for (const b of signIns) { if (visible(b)) return false; }
    // 侧栏文案：未登录通常没有「最近加入」
    const root = document.querySelector('nav') || document.body;
    const text = (root && root.innerText) ? root.innerText : '';
    if (/最近加入|Recently Added|所有歌單|All Playlists|我的帳户|我的账户|My Account/.test(text)) {
      return true;
    }
    // 账户按钮显示姓名时，页面上也常有资料库
    const btns = document.querySelectorAll('button');
    for (const b of btns) {
      if (!visible(b)) continue;
      const label = ((b.innerText||'') + ' ' + (b.getAttribute('aria-label')||'')).trim();
      if (!label || label.length > 40) continue;
      if (/^Sign In$|^登入$|^登录$/i.test(label)) return false;
      if (/我的帳户|我的账户|My Account/i.test(label)) return true;
    }
    return false;
    """
    try:
        return bool(driver.execute_script(script))
    except Exception:
        return False


def _apple_click_auth_continues(driver, max_clicks: int = 6) -> int:
    """登录后欢迎页 Continue——仅主文档，不扫 iframe。"""
    clicked = 0
    keywords = ["Continue", "繼續", "继续"]
    for _ in range(max_clicks):
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        el = _apple_find_clickable_by_texts(driver, keywords, tags="button")
        if not el:
            break
        label = _apple_norm_text(el.text or el.get_attribute("aria-label") or "")
        if any(x in label for x in ("try", "試用", "试用", "subscribe", "訂閱", "订阅")):
            break
        if _apple_safe_click(driver, el):
            clicked += 1
            print(f"    · 已点 Continue/繼續 ({clicked})", flush=True)
            apple_human_delay(1.0, 1.8)
        else:
            break
    return clicked


def _apple_geo_banner_present(driver) -> bool:
    """底部地区条：Choose another country / 香港 + Continue。"""
    try:
        driver.switch_to.default_content()
        body = (driver.execute_script("return document.body && document.body.innerText || ''") or "")
    except Exception:
        return False
    low = body.lower()
    has_hint = (
        "choose another country" in low
        or "content specific to your location" in low
        or "選擇其他國家" in body
        or "选择其他国家" in body
        or "查看特定於你所在位置" in body
        or "查看特定于你所在位置" in body
    )
    has_hk = "香港" in body or "hong kong" in low
    return bool(has_hint or (has_hk and ("continue" in low or "繼續" in body or "继续" in body)))


def _apple_dismiss_geo_banners(driver, max_clicks: int = 4) -> int:
    """点底部地区条红色 Continue（默认常为 us，需切到香港才有加歌菜单）。"""
    clicked = 0
    for _ in range(max_clicks):
        try:
            driver.switch_to.default_content()
            # 1) 官方 banner select-button
            btns = driver.find_elements(
                By.CSS_SELECTOR,
                "div[data-testid='banner-container'] button[data-testid='select-button'], "
                "div[data-testid='banner-container'] button",
            )
            visible = [b for b in btns if b.is_displayed()]
            target = None
            for b in visible:
                t = _apple_norm_text(b.text or "")
                if t in ("continue", "繼續", "继续") or "continue" in t:
                    target = b
                    break
            if target is None and visible:
                # banner 内唯一主按钮
                target = visible[0]

            # 2) JS：找含 country/香港 文案的底栏里的 Continue
            if target is None:
                target = driver.execute_script(
                    r"""
                    const needles = ['choose another country', 'content specific to your location',
                      '選擇其他國家', '选择其他国家', '香港', 'hong kong'];
                    const isVisible = (el) => {
                      const r = el.getBoundingClientRect();
                      const st = getComputedStyle(el);
                      return r.width > 2 && r.height > 2 && st.visibility !== 'hidden'
                        && st.display !== 'none' && st.opacity !== '0';
                    };
                    const nodes = Array.from(document.querySelectorAll('div,section,aside,footer'));
                    let bar = null;
                    for (const n of nodes) {
                      if (!isVisible(n)) continue;
                      const t = (n.innerText || '').toLowerCase();
                      if (!needles.some(k => t.includes(k.toLowerCase()))) continue;
                      const r = n.getBoundingClientRect();
                      // 偏底部的横条
                      if (r.top < window.innerHeight * 0.55) continue;
                      if (r.height > 220 || r.width < window.innerWidth * 0.35) continue;
                      bar = n;
                      break;
                    }
                    if (!bar) return null;
                    const buttons = Array.from(bar.querySelectorAll('button'));
                    for (const b of buttons) {
                      if (!isVisible(b)) continue;
                      const t = (b.innerText || '').trim().toLowerCase();
                      if (t === 'continue' || t === '繼續' || t === '继续' || t.includes('continue')) return b;
                    }
                    return buttons.find(isVisible) || null;
                    """
                )

            # 3) 文案兜底
            if target is None:
                fallback = _apple_find_clickable_by_texts(
                    driver, ["Continue", "繼續", "继续"], tags="button"
                )
                if fallback and "try" not in _apple_norm_text(fallback.text or ""):
                    parent_txt = ""
                    try:
                        parent_txt = (
                            fallback.find_element(By.XPATH, "./ancestor::div[contains(@data-testid,'banner') or position()=1]").text
                            or ""
                        )
                    except Exception:
                        try:
                            parent_txt = fallback.find_element(By.XPATH, "./ancestor::div[2]").text or ""
                        except Exception:
                            parent_txt = ""
                    blob = parent_txt.lower()
                    if (
                        "country" in blob
                        or "location" in blob
                        or "國家" in parent_txt
                        or "国家" in parent_txt
                        or "地區" in parent_txt
                        or "地区" in parent_txt
                        or "香港" in parent_txt
                        or _apple_geo_banner_present(driver)
                    ):
                        target = fallback

            if target is None:
                break
            if _apple_safe_click(driver, target):
                clicked += 1
                print("    · 已点击地区条 Continue（切到所选国家/地区）", flush=True)
                apple_human_delay(1.2, 2.0)
                # 点完后若仍有条再点；没有则结束
                if not _apple_geo_banner_present(driver):
                    break
                continue
            break
        except Exception:
            break
    return clicked


def _apple_ensure_storefront(driver, storefront: str = None) -> bool:
    """登录后确保目标店面：先点地区 Continue，必要时强制打开 /{code}/。

    港号 hk、美号 us；storefront 缺省用 APPLE_DEFAULT_STOREFRONT。
    """
    code = (storefront or APPLE_DEFAULT_STOREFRONT).strip().lower() or APPLE_DEFAULT_STOREFRONT
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    n = _apple_dismiss_geo_banners(driver, max_clicks=3)
    if n:
        apple_human_delay(1.5, 2.5)
    url = ""
    try:
        url = driver.current_url or ""
    except Exception:
        pass
    if f"/{code}/" in url or url.rstrip("/").endswith(f"/{code}"):
        print(f"    · 店面已是 {code}: {url}", flush=True)
        return True
    # 仍在其它店面：强制进目标首页
    try:
        target = f"https://music.apple.com/{code}"
        print(f"    · 当前店面非 {code}（{url or 'unknown'}），打开 {target}", flush=True)
        driver.get(target)
        apple_human_delay(2.0, 3.0)
        _apple_dismiss_geo_banners(driver, max_clicks=2)
        apple_human_delay(1.0, 1.5)
        url2 = driver.current_url or ""
        ok = f"/{code}/" in url2 or url2.rstrip("/").endswith(f"/{code}")
        print(f"    · 跳转后 URL: {url2} ({'OK' if ok else f'仍非 {code}'})", flush=True)
        return ok
    except Exception as e:
        print(f"    · 强制店面 {code} 失败: {e}", flush=True)
        return False


def _apple_ensure_hk_storefront(driver) -> bool:
    """兼容旧调用：默认香港。"""
    return _apple_ensure_storefront(driver, "hk")


def _apple_rewrite_url_storefront(url: str, storefront: str) -> str:
    """把 music.apple.com/{旧码}/... 改成目标店面码。"""
    code = (storefront or APPLE_DEFAULT_STOREFRONT).strip().lower()
    if not url:
        return f"https://music.apple.com/{code}"
    import re as _re
    new_url, n = _re.subn(
        r"(https?://music\.apple\.com/)([a-z]{2})(/|$)",
        rf"\1{code}\3",
        url,
        count=1,
        flags=_re.I,
    )
    if n:
        return new_url
    if "music.apple.com" in url:
        return f"https://music.apple.com/{code}/home"
    return url


def _apple_switch_url_to_storefront(driver, storefront: str) -> bool:
    """加歌报错（无添加菜单）时：把当前网址切到目标店面后刷新。"""
    code = (storefront or APPLE_DEFAULT_STOREFRONT).strip().lower()
    try:
        cur = driver.current_url or ""
    except Exception:
        cur = ""
    new_url = _apple_rewrite_url_storefront(cur, code)
    if new_url == cur and f"/{code}/" in (cur or ""):
        print(f"    · URL 已是 /{code}/，无需再切: {cur}", flush=True)
        return True
    try:
        print(f"    · 加歌失败疑似店面不对，切换 URL: {cur} → {new_url}", flush=True)
        driver.get(new_url)
        apple_human_delay(2.0, 3.0)
        _apple_dismiss_geo_banners(driver, max_clicks=2)
        apple_human_delay(1.0, 1.5)
        return True
    except Exception as e:
        print(f"    · 切换店面 URL 失败: {e}", flush=True)
        return False



def _apple_click_sign_in(driver) -> bool:
    try:
        driver.switch_to.default_content()
        btns = driver.find_elements(By.CSS_SELECTOR, "button[data-testid='sign-in-button']")
        for b in btns:
            if b.is_displayed() and _apple_safe_click(driver, b):
                print("    · 已点击 Sign In / 登入")
                return True
    except Exception:
        pass
    el = _apple_find_clickable_by_texts(
        driver, ["Sign In", "Sign in", "登入", "登录"], tags="button"
    )
    if el and _apple_safe_click(driver, el):
        print("    · 已点击 Sign In / 登入（文案匹配）")
        return True
    return False


def _apple_find_modal_close_button(driver):
    """网络抽风时空黑框左上角关闭按钮（主文档 + Shadow DOM）。"""
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    # JS 穿透 shadow，比纯 CSS 更稳
    script = r"""
    function allRoots(root, out) {
      out.push(root);
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of nodes) {
        if (el.shadowRoot) allRoots(el.shadowRoot, out);
      }
      return out;
    }
    const sels = [
      "button[data-test='modal-close-button']",
      "button.cc-modal__close-button",
      "button[aria-label='Close']",
      "button[aria-label='關閉']",
      "button[aria-label='关闭']",
      "#modal-header button",
    ];
    const roots = allRoots(document, []);
    for (const root of roots) {
      if (!root.querySelectorAll) continue;
      for (const sel of sels) {
        const list = root.querySelectorAll(sel);
        for (const el of list) {
          const r = el.getBoundingClientRect();
          const st = window.getComputedStyle(el);
          if (r.width > 2 && r.height > 2 && st.visibility !== 'hidden' && st.display !== 'none') {
            return el;
          }
        }
      }
    }
    return null;
    """
    try:
        el = driver.execute_script(script)
        if el is not None:
            return el
    except Exception:
        pass
    selectors = [
        "button[data-test='modal-close-button']",
        "button.cc-modal__close-button",
        "button[aria-label='Close']",
        "button[aria-label='關閉']",
        "button[aria-label='关闭']",
        "#modal-header button",
        ".cc-modal__close-button",
    ]
    for css in selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, css):
                try:
                    if el.is_displayed():
                        return el
                except Exception:
                    continue
        except Exception:
            continue
    return _apple_find_clickable_by_texts(
        driver, ["Close", "關閉", "关闭"], tags="button"
    )


def _apple_js_blank_auth_modal_state(driver) -> dict:
    """用 JS 判断空黑框：有模态壳/关闭钮，但没有可用登录表单。"""
    script = r"""
    function allRoots(root, out) {
      out.push(root);
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of nodes) {
        if (el.shadowRoot) allRoots(el.shadowRoot, out);
      }
      return out;
    }
    function visible(el) {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const st = window.getComputedStyle(el);
      return r.width > 2 && r.height > 2 && st.visibility !== 'hidden' && st.display !== 'none'
        && st.opacity !== '0';
    }
    const roots = allRoots(document, []);
    let hasClose = false;
    let hasModalShell = false;
    let hasAuthInput = false;
    let hasAuthText = false;
    let modalTextLen = 0;
    const closeSels = [
      "button[data-test='modal-close-button']",
      "button.cc-modal__close-button",
      "button[aria-label='Close']",
      "button[aria-label='關閉']",
      "button[aria-label='关闭']",
    ];
    const shellSels = [".cc-modal", ".cc-modal__modal", "[role='dialog']", "#modal-0", "#modal-header", ".cc-modal__body"];
    for (const root of roots) {
      if (!root.querySelectorAll) continue;
      for (const sel of closeSels) {
        root.querySelectorAll(sel).forEach(el => { if (visible(el)) hasClose = true; });
      }
      for (const sel of shellSels) {
        root.querySelectorAll(sel).forEach(el => {
          if (visible(el)) {
            hasModalShell = true;
            const t = (el.innerText || '').trim();
            modalTextLen = Math.max(modalTextLen, t.length);
          }
        });
      }
      root.querySelectorAll('input, textarea').forEach(el => {
        if (!visible(el)) return;
        const type = (el.getAttribute('type') || '').toLowerCase();
        const blob = [
          type, el.name||'', el.id||'', el.placeholder||'', el.getAttribute('aria-label')||''
        ].join(' ').toLowerCase();
        if (type === 'password' || type === 'email' || blob.includes('email') || blob.includes('password')
            || blob.includes('電郵') || blob.includes('密碼') || blob.includes('验证') || blob.includes('驗證')
            || blob.includes('account') || type === 'tel' || type === 'text' || type === '') {
          // 六位验证码也算
          hasAuthInput = true;
        }
      });
    }
    const bodyText = (document.body && document.body.innerText || '');
    const markers = ['以電郵繼續','Continue with Email','使用密碼登入','Sign In with Password',
      '請檢查電郵','Check Your Email','使用 Apple 帳户登入','Sign in with Apple',
      '重新傳送驗證碼','Resend','密碼','Password','電郵','Email','歡迎使用','Welcome to Apple',
      '驗證碼','Verification'];
    for (const m of markers) {
      if (bodyText.includes(m)) { hasAuthText = true; break; }
    }
    // 空黑框：有关闭钮或模态壳，但几乎没有正文/表单
    const blank = (hasClose || hasModalShell) && !hasAuthInput && (!hasAuthText || modalTextLen < 8);
    return {hasClose, hasModalShell, hasAuthInput, hasAuthText, modalTextLen, blank};
    """
    try:
        driver.switch_to.default_content()
        return driver.execute_script(script) or {}
    except Exception:
        return {}


def _apple_find_email_shallow(driver):
    """
    浅层找邮箱：主文档 + 第一层 iframe（不做深扫 / 不拉 page_source）。
    返回 (element, frame_path|None)；找不到 (None, None)。
    """
    try:
        driver.set_script_timeout(5)
    except Exception:
        pass
    try:
        driver.switch_to.default_content()
        el = _apple_find_email_input(driver)
        if el is not None:
            return el, []
    except Exception:
        pass
    try:
        driver.switch_to.default_content()
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe")
        for i, fr in enumerate(frames[:8]):
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(fr)
                el = _apple_find_email_input(driver)
                if el is not None:
                    return el, [i]
            except Exception:
                continue
        driver.switch_to.default_content()
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
    return None, None


def _apple_fill_email_fast(driver, email: str) -> bool:
    """邮箱一出现就填：浅层 Selenium → 失败则 UIA/坐标粘贴。"""
    _apple_step(driver, "fill_email_start")
    # 输入前查黑框（快速 JS，避免 UIA 拖慢）
    st = _apple_js_blank_auth_modal_state(driver)
    if st.get("blank") and not st.get("hasAuthText"):
        _apple_step(driver, "blank_before_fill", str(st))
        _apple_close_blank_auth_modal(driver)
        return False

    el, path = _apple_find_email_shallow(driver)
    if el is not None:
        if path is not None:
            _apple_enter_frame_path(driver, path)
        _apple_set_input_value(driver, el, email)
        got = ""
        try:
            got = el.get_attribute("value") or ""
        except Exception:
            pass
        if email.lower() in got.lower() or "@" in got:
            _apple_step(driver, "email_filled", f"selenium frame={path} value={got[:40]}")
            return True
        _apple_step(driver, "email_selenium_value_mismatch", repr(got[:40]))

    # 坐标/UIA 兜底（HK 实测邮箱框约 800,442）
    _apple_step(driver, "email_fill_coord_fallback")
    try:
        from apple_uia_login import paste_at, click_named, focus_apple_chrome, find_named_center
        focus_apple_chrome()
        pt = find_named_center(["電郵", "Email", "邮箱"], timeout=2.0) or (800, 442)
        paste_at(pt[0], pt[1], email)
        _apple_step(driver, "email_pasted_coord", str(pt))
        return True
    except Exception as e:
        _apple_step(driver, "email_coord_fail", str(e))
        return False


def _apple_has_auth_email_ready(driver) -> bool:
    """登录弹窗里是否已出现邮箱输入框（浅层查找，避免卡死）。"""
    el, _ = _apple_find_email_shallow(driver)
    if el is not None:
        return True
    # UIA 仅作短兜底
    try:
        from apple_uia_login import find_named_center
        if find_named_center(["電郵", "Email"], timeout=0.5):
            return True
    except Exception:
        pass
    return False


def _apple_has_auth_password_or_code_ready() -> bool:
    try:
        from apple_uia_login import find_named_center
        return bool(
            find_named_center(
                ["密碼", "Password", "使用密碼登入", "Sign In with Password", "驗證碼數字 1", "Verification Code"],
                timeout=1.0,
            )
        )
    except Exception:
        return False


def _apple_is_blank_auth_modal(driver) -> bool:
    """空黑框：有关闭/模态壳，但没有邮箱/密码/验证码表单。验证码页绝不是黑框。"""
    # 底部地区条（香港+Continue）绝不能当空黑框关掉，否则会卡在 /us/ 无加歌菜单
    if _apple_geo_banner_present(driver):
        return False
    # 验证码 / 密码切换页 → 绝对不要关
    try:
        from apple_uia_login import find_named_center
        if find_named_center(
            [
                "使用密碼登入",
                "Sign In with Password",
                "重新傳送驗證碼",
                "Resend",
                "驗證碼數字 1",
                "請檢查電郵",
                "密碼",
                "Password",
            ],
            timeout=0.6,
        ):
            return False
    except Exception:
        pass

    st = _apple_js_blank_auth_modal_state(driver)
    if st.get("hasAuthText") and st.get("modalTextLen", 0) >= 8:
        return False
    if st.get("blank"):
        try:
            from apple_uia_login import find_named_center
            if find_named_center(
                ["電郵", "Email", "以電郵繼續", "Continue with Email", "使用密碼登入"],
                timeout=0.6,
            ):
                return False
        except Exception:
            pass
        return True
    close_btn = _apple_find_modal_close_button(driver)
    if not close_btn and not st.get("hasClose") and not st.get("hasModalShell"):
        return False
    if _apple_has_auth_email_ready(driver):
        return False
    if _apple_has_auth_password_or_code_ready():
        return False
    return bool(close_btn or st.get("hasClose") or st.get("hasModalShell"))


def _apple_close_blank_auth_modal(driver) -> bool:
    """关闭空黑框：Selenium → UIA → 固定坐标。"""
    close_btn = _apple_find_modal_close_button(driver)
    if close_btn:
        if _apple_safe_click(driver, close_btn):
            print("    · 已关闭空黑框登录弹窗", flush=True)
            apple_human_delay(0.8, 1.2)
            return True
        try:
            driver.execute_script("arguments[0].click();", close_btn)
            print("    · 已关闭空黑框登录弹窗 (js)", flush=True)
            apple_human_delay(0.8, 1.2)
            return True
        except Exception:
            pass
    try:
        from apple_uia_login import click_named, click_xy
        if click_named(["關閉", "Close", "关闭"], fallback_xy=(442, 231), timeout=2.0):
            print("    · 已关闭空黑框登录弹窗 (uia/xy)", flush=True)
            apple_human_delay(0.8, 1.2)
            return True
        click_xy(442, 231)
        print("    · 已关闭空黑框登录弹窗 (xy)", flush=True)
        apple_human_delay(0.8, 1.2)
        return True
    except Exception as e:
        print(f"    · 关闭空黑框失败: {e}", flush=True)
        return False


def _apple_recover_blank_and_reopen_signin(driver, max_retries: int = 3) -> bool:
    """关掉空黑框后重新点 Sign In，直到邮箱框出现。"""
    print("STEP recover_blank_auth_modal", flush=True)
    _apple_save_debug_shot(driver, "apple_blank_modal")
    if not _apple_close_blank_auth_modal(driver):
        print("✗ 空黑框关闭失败", flush=True)
        return False
    apple_human_delay(1.0, 1.5)
    return _apple_open_sign_in_ready(driver, max_retries=max_retries)


def _apple_open_sign_in_ready(driver, max_retries: int = 3, wait_sec: float = 25.0) -> bool:
    """
    点 Sign In 后轮询（不要死等满 20 秒）：
    - 邮箱框一出现 → 立刻返回，马上填写
    - 空黑框出现 → 关闭并重点 Sign In
    """
    for attempt in range(1, max_retries + 1):
        if not _apple_click_sign_in(driver):
            print(f"✗ 第 {attempt} 次未找到 Sign In / 登入", flush=True)
            return False
        _apple_step(driver, "signin_clicked", f"attempt={attempt}")
        print(f"  轮询最多 {int(wait_sec)}s：邮箱出现就填；若变黑框则关闭重开...", flush=True)

        deadline = time.time() + wait_sec
        poll = 0
        while time.time() < deadline:
            poll += 1
            # 先认邮箱（优先级最高，别被黑框检测拖慢）
            if _apple_has_auth_email_ready(driver):
                _apple_step(driver, "auth_modal_ok_email_ready", f"poll={poll}")
                return True

            # 黑框只用 JS 快判，避免每秒 UIA 扫一遍
            st = _apple_js_blank_auth_modal_state(driver)
            if st.get("blank") and not st.get("hasAuthText"):
                _apple_step(driver, "blank_auth_modal", f"attempt={attempt} poll={poll} {st}")
                if not _apple_close_blank_auth_modal(driver):
                    print("✗ 空黑框关闭失败", flush=True)
                    return False
                apple_human_delay(0.8, 1.2)
                break

            if poll % 5 == 0:
                _apple_step(driver, "auth_poll", f"n={poll} {st}")
            time.sleep(0.5)
        else:
            st = _apple_js_blank_auth_modal_state(driver)
            _apple_step(driver, "auth_wait_timeout", str(st))
            if _apple_is_blank_auth_modal(driver):
                _apple_close_blank_auth_modal(driver)
                apple_human_delay(1.0, 1.5)
            continue
        continue

    print("✗ Sign In 多次仍未出现可用登录弹窗", flush=True)
    return False


def _apple_js_find_input(driver, kind: str):
    """
    穿透 Shadow DOM 查找输入框。
    kind: email | password
    """
    script = r"""
    const kind = arguments[0];
    function allRoots(root, out) {
      out.push(root);
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of nodes) {
        if (el.shadowRoot) allRoots(el.shadowRoot, out);
      }
      return out;
    }
    const roots = allRoots(document, []);
    const inputs = [];
    for (const root of roots) {
      if (!root.querySelectorAll) continue;
      root.querySelectorAll('input, textarea').forEach(el => inputs.push(el));
    }
    const visible = inputs.filter(el => {
      const r = el.getBoundingClientRect();
      const st = window.getComputedStyle(el);
      return r.width > 2 && r.height > 2 && st.visibility !== 'hidden' && st.display !== 'none';
    });
    const score = (el) => {
      const type = (el.getAttribute('type') || '').toLowerCase();
      const name = (el.getAttribute('name') || '').toLowerCase();
      const id = (el.id || '').toLowerCase();
      const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
      const ph = (el.getAttribute('placeholder') || '').toLowerCase();
      const aria = (el.getAttribute('aria-label') || '').toLowerCase();
      const blob = [type, name, id, ac, ph, aria].join(' ');
      let s = 0;
      if (kind === 'password') {
        if (type === 'password') s += 20;
        if (blob.includes('password') || blob.includes('密碼') || blob.includes('密码')) s += 10;
      } else {
        if (type === 'email') s += 20;
        if (type === 'password') s -= 50;
        if (blob.includes('email') || blob.includes('account') || blob.includes('user')
            || blob.includes('電郵') || blob.includes('邮箱') || blob.includes('郵箱')
            || blob.includes('phone') || blob.includes('電話') || blob.includes('电话')) s += 12;
        if (type === 'text' || type === 'tel' || type === '') s += 2;
      }
      return s;
    };
    let best = null, bestScore = 0;
    for (const el of visible) {
      const sc = score(el);
      if (sc > bestScore) { best = el; bestScore = sc; }
    }
    return bestScore > 0 ? best : null;
    """
    try:
        return driver.execute_script(script, kind)
    except Exception:
        return None


def _apple_find_email_input(driver):
    el = _apple_js_find_input(driver, "email")
    if el is not None:
        return el
    selectors = [
        "input[type='email']",
        "input[name='accountName']",
        "input#account_name_text_field",
        "input[autocomplete='username']",
        "input[type='text']",
    ]
    for css in selectors:
        for cand in _apple_visible_elements(driver, css):
            try:
                itype = (cand.get_attribute("type") or "").lower()
                name = (cand.get_attribute("name") or "").lower()
                autocomplete = (cand.get_attribute("autocomplete") or "").lower()
                placeholder = (cand.get_attribute("placeholder") or "").lower()
                aria = (cand.get_attribute("aria-label") or "").lower()
                blob = " ".join([itype, name, autocomplete, placeholder, aria])
                if any(k in blob for k in ("email", "account", "user", "電郵", "邮箱", "郵箱", "电话", "電話", "phone")):
                    return cand
                if itype in ("email", "text") and "password" not in blob:
                    return cand
            except Exception:
                continue
    return None


def _apple_find_password_input(driver):
    el = _apple_js_find_input(driver, "password")
    if el is not None:
        return el
    selectors = [
        "input[type='password']",
        "input#password_text_field",
        "input[name='password']",
        "input[autocomplete='current-password']",
    ]
    for css in selectors:
        els = _apple_visible_elements(driver, css)
        if els:
            return els[0]
    return None


def _apple_js_click_by_texts(driver, texts: list[str]) -> bool:
    """穿透 Shadow DOM 按文案点击按钮/链接。"""
    script = r"""
    const texts = arguments[0].map(t => (t || '').toLowerCase());
    function allRoots(root, out) {
      out.push(root);
      const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const el of nodes) {
        if (el.shadowRoot) allRoots(el.shadowRoot, out);
      }
      return out;
    }
    function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
    const roots = allRoots(document, []);
    const candidates = [];
    for (const root of roots) {
      if (!root.querySelectorAll) continue;
      root.querySelectorAll('button,a,[role="button"],input[type="submit"],div,span').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return;
        const label = norm([el.innerText, el.getAttribute('aria-label'), el.value, el.title].filter(Boolean).join(' '));
        if (!label || label.length > 80) return;
        for (const t of texts) {
          if (t && label.includes(t)) { candidates.push(el); return; }
        }
      });
    }
    if (!candidates.length) return false;
    // 优先较短文案（更像按钮本身）
    candidates.sort((a,b) => ((a.innerText||'').length) - ((b.innerText||'').length));
    const el = candidates[0];
    el.scrollIntoView({block:'center'});
    el.click();
    return true;
    """
    try:
        return bool(driver.execute_script(script, texts))
    except Exception:
        return False


def _apple_switch_to_password_login(driver) -> bool:
    keywords = [
        "使用密碼登入",
        "使用密码登录",
        "Sign In with Password",
        "Sign in with Password",
        "Use Password",
        "Log In with Password",
        "Login with Password",
    ]
    # 先全 frame + Shadow
    paths = _apple_collect_frames(driver)
    for path in paths:
        if not _apple_enter_frame_path(driver, path):
            continue
        if _apple_js_click_by_texts(driver, keywords):
            print("    · 已切换为密码登录")
            apple_human_delay(1.5, 2.5)
            return True
        el = _apple_find_clickable_by_texts(driver, keywords, tags="button,a,[role='button'],div,span")
        if el and _apple_safe_click(driver, el):
            print("    · 已切换为密码登录")
            apple_human_delay(1.5, 2.5)
            return True
    try:
        driver.switch_to.default_content()
    except Exception:
        pass
    return False


def _apple_submit_auth(driver) -> bool:
    keywords = ["Continue", "繼續", "继续", "Sign In", "Sign in", "登入", "登录", "Next", "下一步"]
    if _apple_js_click_by_texts(driver, keywords):
        return True
    el = _apple_find_clickable_by_texts(driver, keywords, tags="button")
    if el and _apple_safe_click(driver, el):
        return True
    try:
        for btn in _apple_visible_elements(driver, "button"):
            aria = (btn.get_attribute("aria-label") or "").lower()
            text = (btn.text or "").strip()
            if text:
                continue
            if any(k in aria for k in ("continue", "sign", "next", "submit", "登入", "继续", "繼續")):
                if _apple_safe_click(driver, btn):
                    return True
        pwd = _apple_find_password_input(driver)
        if pwd:
            try:
                parent = pwd.find_element(By.XPATH, "./ancestor::*[self::div or self::form][1]")
                for btn in parent.find_elements(By.CSS_SELECTOR, "button"):
                    if btn.is_displayed() and _apple_safe_click(driver, btn):
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def login_apple_music(
    driver,
    email: str | None = None,
    password: str | None = None,
    login_mode: str | None = None,
    storefront: str | None = None,
) -> bool:
    """
    登录 Apple Music。
    login_mode: auto=凭据自动登录；manual=浏览器内手动登录后输入 y。
    storefront: 目标店面码 hk/us/…；登录成功后切到该店面。
    默认读 APPLE_LOGIN_MODE；manual 或缺少凭据时走人工确认。
    """
    mode = (login_mode or APPLE_LOGIN_MODE or "auto").strip().lower()
    sf = (storefront or APPLE_DEFAULT_STOREFRONT).strip().lower()
    if mode == "manual" or not email or not password:
        print(f"Apple 登录模式: manual（请在浏览器完成登录后输入 y）", flush=True)
        ok = login_apple_music_manual(driver)
        if ok:
            _apple_ensure_storefront(driver, sf)
        return ok
    print(f"Apple 登录模式: auto（{email}，店面 {sf}）", flush=True)
    return login_apple_music_auto(driver, email, password, storefront=sf)


def login_apple_music_manual(driver) -> bool:
    """登录 Apple Music - 人工确认（旧模式）"""
    print("正在访问 Apple Music...")
    driver.get(APPLE_HOME_URL)
    apple_human_delay(1, 2)

    print("\n请在浏览器中完成登录。")
    print("完成后输入 y 并按回车继续，输入 n 取消。\n")

    deadline = time.time() + APPLE_LOGIN_CONFIRM_TIMEOUT

    while True:
        remaining = max(0, int(deadline - time.time()))
        if remaining <= 0:
            print("✗ Apple Music 登录等待超时")
            return False

        minutes, seconds = divmod(remaining, 60)
        user_input = input(
            f"是否已登录成功？(y/n) [剩余 {minutes:02d}:{seconds:02d}]: "
        ).strip().lower()

        if user_input == "y":
            print("✓ 登录成功")
            return True
        if user_input == "n":
            print("✗ 登录失败")
            return False
        print("请输入 y 或 n")


def _apple_uia_root_window(timeout: float = 8.0):
    """定位 Apple Music Chrome 窗口（uiautomation）。"""
    try:
        import uiautomation as auto
    except ImportError:
        print("    · 未安装 uiautomation，跳过 UIA 登录辅助")
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for win in auto.GetRootControl().GetChildren():
                try:
                    name = win.Name or ""
                except Exception:
                    continue
                if "Apple" in name and ("Music" in name or "音樂" in name or "音乐" in name):
                    try:
                        win.SetActive()
                    except Exception:
                        pass
                    return win
        except Exception:
            pass
        time.sleep(0.4)
    return None


def _apple_uia_find_control(root, control_type: str, names: list[str], timeout: float = 12.0):
    """在窗口内按名称查找控件（兼容中英）。"""
    try:
        import uiautomation as auto
    except ImportError:
        return None

    deadline = time.time() + timeout
    wanted = [_apple_norm_text(n) for n in names if n]
    while time.time() < deadline:
        try:
            if control_type == "edit":
                walker = root.GetChildren()
                # 深度搜索 Edit
                stack = list(walker)
                depth_guard = 0
                while stack and depth_guard < 4000:
                    depth_guard += 1
                    ctrl = stack.pop(0)
                    try:
                        children = ctrl.GetChildren()
                        stack.extend(children)
                    except Exception:
                        children = []
                    try:
                        ctype = ctrl.ControlTypeName
                        cname = ctrl.Name or ""
                    except Exception:
                        continue
                    if ctype != "EditControl":
                        continue
                    cn = _apple_norm_text(cname)
                    if any(w and (w in cn or cn in w) for w in wanted) or (not cn and "password" in " ".join(wanted)):
                        # 空名编辑框：若在找密码且 IsPassword
                        try:
                            if "password" in " ".join(wanted) or "密碼" in "".join(names) or "密码" in "".join(names):
                                if getattr(ctrl, "IsPassword", False) or "password" in cn or "密碼" in cname or "密码" in cname:
                                    return ctrl
                            if cn:
                                return ctrl
                        except Exception:
                            if cn:
                                return ctrl
                    if cn and any(w in cn for w in wanted):
                        return ctrl
            else:
                stack = list(root.GetChildren())
                depth_guard = 0
                while stack and depth_guard < 4000:
                    depth_guard += 1
                    ctrl = stack.pop(0)
                    try:
                        stack.extend(ctrl.GetChildren())
                    except Exception:
                        pass
                    try:
                        ctype = ctrl.ControlTypeName
                        cname = ctrl.Name or ""
                    except Exception:
                        continue
                    if control_type == "button" and ctype not in ("ButtonControl", "HyperlinkControl"):
                        # 也允许 Text/自定义被当成可点
                        if ctype not in ("ButtonControl", "HyperlinkControl", "TextControl", "ListItemControl"):
                            continue
                    cn = _apple_norm_text(cname)
                    if any(w and w == cn for w in wanted):
                        return ctrl
                    if any(w and w in cn and len(cn) < 40 for w in wanted):
                        return ctrl
        except Exception:
            pass
        time.sleep(0.35)
    return None


def _apple_uia_set_value(ctrl, value: str) -> bool:
    """用 UIA ValuePattern 写入，绕过五笔输入法。"""
    if ctrl is None:
        return False
    try:
        pattern = ctrl.GetValuePattern()
        if pattern:
            pattern.SetValue(value)
            return True
    except Exception:
        pass
    try:
        ctrl.Click()
        time.sleep(0.15)
        # 全选后粘贴
        try:
            import uiautomation as auto
            auto.SendKeys("{Ctrl}a")
            time.sleep(0.05)
        except Exception:
            pass
        try:
            import uiautomation as auto
            auto.SetClipboardText(value)
            auto.SendKeys("{Ctrl}v")
            return True
        except Exception:
            pass
    except Exception:
        pass
    return False


def _apple_uia_click(ctrl) -> bool:
    if ctrl is None:
        return False
    try:
        ctrl.Click()
        return True
    except Exception:
        try:
            rect = ctrl.BoundingRectangle
            x = (rect.left + rect.right) // 2
            y = (rect.top + rect.bottom) // 2
            import uiautomation as auto
            auto.Click(x, y)
            return True
        except Exception:
            return False


def _apple_uia_complete_login(email: str, password: str, timeout: float = 120.0) -> bool:
    """备用：全坐标登录。"""
    try:
        from apple_uia_login import complete_apple_login
    except Exception as e:
        print(f"STEP uia_import_fail: {e}", flush=True)
        return False
    return complete_apple_login(email, password, timeout=timeout)


def login_apple_music_auto(driver, email: str, password: str, storefront: str | None = None) -> bool:
    """全自动登录：Selenium 填邮箱（已验证可用）+ 坐标完成密码/Continue。"""
    sf = (storefront or APPLE_DEFAULT_STOREFRONT).strip().lower()
    print(f"正在自动登录 Apple Music: {email}", flush=True)
    try:
        try:
            driver.set_script_timeout(8)
        except Exception:
            pass

        driver.get(APPLE_HOME_URL)
        apple_human_delay(2, 3)

        geo_n = _apple_dismiss_geo_banners(driver)
        if geo_n:
            print(f"    · 已处理地区提示 {geo_n} 次", flush=True)

        if _apple_is_logged_in(driver):
            print("✓ 已处于登录状态", flush=True)
            _apple_ensure_storefront(driver, sf)
            return True

        # 全流程可重试：邮箱提交后 / 密码后若出空黑框，关闭并重开登录
        for round_i in range(1, 4):
            print(f"STEP login_round={round_i}", flush=True)
            if round_i > 1:
                if not _apple_open_sign_in_ready(driver, max_retries=3):
                    print("✗ 重开登录弹窗失败", flush=True)
                    _apple_save_debug_shot(driver, "apple_no_signin_retry")
                    return False

            if round_i == 1:
                if not _apple_open_sign_in_ready(driver, max_retries=3):
                    print("✗ 未打开可用的 Sign In / 登入 弹窗", flush=True)
                    _apple_save_debug_shot(driver, "apple_no_signin")
                    return False

            # 1) 邮箱出现后立刻浅层填写（禁止深扫 frame）
            email_ok = _apple_fill_email_fast(driver, email)
            if not email_ok:
                _apple_step(driver, "email_fill_failed_retry_round")
                if _apple_is_blank_auth_modal(driver):
                    _apple_close_blank_auth_modal(driver)
                if _apple_uia_complete_login(email, password):
                    _apple_step(driver, "uia_full_login_done")
                else:
                    _apple_step(driver, "uia_full_login_fail")
                    continue
            else:
                el, path = _apple_find_email_shallow(driver)
                if path is not None:
                    _apple_enter_frame_path(driver, path)
                if not _apple_submit_auth(driver):
                    _apple_step(driver, "email_submit_js_fail_try_coord")
                    try:
                        from apple_uia_login import click_named, click_xy
                        if not click_named(["繼續", "Continue"], fallback_xy=(800, 645), timeout=2.0):
                            click_xy(800, 645)
                        _apple_step(driver, "email_submit_coord")
                    except Exception as e:
                        _apple_step(driver, "email_submit_coord_fail", str(e))
                else:
                    _apple_step(driver, "email_submitted")
                # 邮箱提交后直接进密码阶段（验证码页点「使用密碼登入」），不做 UIA 预检以免卡死
                apple_human_delay(1.2, 1.8)
                try:
                    from apple_uia_login import complete_password_phase, focus_apple_chrome
                    focus_apple_chrome()
                    _apple_step(driver, "password_phase_start")
                    pwd_ok = complete_password_phase(password)
                    _apple_step(driver, "password_phase_end", f"ok={pwd_ok}")
                    if not pwd_ok:
                        apple_human_delay(1.0, 1.5)
                        continue
                except Exception as e:
                    _apple_step(driver, "password_phase_fail", str(e))
                    return False

                time.sleep(1.5)
                _apple_step(driver, "after_password_check")
                # 密码后若已登录，跳过黑框逻辑
                if _apple_is_logged_in(driver):
                    _apple_step(driver, "LOGIN_OK")
                    print("✓ Apple Music 自动登录成功（已出现账户入口）", flush=True)
                    _apple_ensure_storefront(driver, sf)
                    print("  等待 20 秒后继续原加歌流程...", flush=True)
                    time.sleep(20)
                    return True

            # 3) 检测左下角账户态；成功后固定等 20 秒（等同人工确认 Y）
            # 先处理地区条，再判断空黑框（避免把地区 Continue 误关）
            _apple_dismiss_geo_banners(driver, max_clicks=2)
            for i in range(20):
                if _apple_geo_banner_present(driver):
                    _apple_dismiss_geo_banners(driver, max_clicks=2)
                if _apple_is_blank_auth_modal(driver):
                    _apple_step(driver, "blank_modal_during_login_wait")
                    _apple_close_blank_auth_modal(driver)
                    break
                if _apple_is_logged_in(driver):
                    _apple_step(driver, "LOGIN_OK")
                    print("✓ Apple Music 自动登录成功（已出现账户入口）", flush=True)
                    _apple_ensure_storefront(driver, sf)
                    print("  等待 20 秒后继续原加歌流程...", flush=True)
                    time.sleep(20)
                    return True
                if i in (2, 5, 8):
                    try:
                        from apple_uia_login import click_named, XY as _XY, click_xy
                        if not click_named(["繼續", "Continue"], timeout=0.8):
                            click_xy(*_XY["welcome_continue"])
                    except Exception:
                        pass
                apple_human_delay(1.0, 1.3)

            if _apple_is_logged_in(driver):
                _apple_step(driver, "LOGIN_OK")
                print("✓ Apple Music 自动登录成功（已出现账户入口）", flush=True)
                _apple_ensure_storefront(driver, sf)
                print("  等待 20 秒后继续原加歌流程...", flush=True)
                time.sleep(20)
                return True

            _apple_step(driver, "login_round_fail", f"round={round_i}")
            if _apple_is_blank_auth_modal(driver):
                _apple_close_blank_auth_modal(driver)
            apple_human_delay(1.0, 1.5)

        print("✗ Apple Music 自动登录后未检测到登录态", flush=True)
        _apple_save_debug_shot(driver, "apple_login_not_detected")
        return False
    except Exception as e:
        print(f"✗ Apple Music 自动登录失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        _apple_save_debug_shot(driver, "apple_login_error")
        return False


# 可选：白名单直链（当前不用；需要时填专辑名 -> URL）
APPLE_DIRECT_ALBUM_URLS = {}

# 仅这几张搜索点标题易被遮挡：改点封面 product-lockup-link；失败再用原始 href（保留地区码）
APPLE_COVER_CLICK_ALBUMS = {
    "streetlamp after the last shift",
    "rooms that breathe in silence",
}


def _is_apple_cover_click_album(album_name: str) -> bool:
    return (album_name or "").strip().lower() in APPLE_COVER_CLICK_ALBUMS


def _is_apple_click_intercepted_error(msg):
    """判断是否为搜索结果点击被遮挡（element click intercepted）。"""
    text = str(msg or "").lower()
    return (
        "element click intercepted" in text
        or "elementclickintercepted" in text
        or "other element would receive the click" in text
        or "点击被其他元素遮挡" in text
        or "搜索结果链接点击被" in text
    )


def _format_apple_search_fail_reason(msg, album_name=""):
    """将搜索失败信息整理成收尾汇总可读的原因。"""
    text = str(msg or "").strip()
    album_key = (album_name or "").strip().lower()
    has_direct = album_key in APPLE_DIRECT_ALBUM_URLS
    cover_special = album_key in APPLE_COVER_CLICK_ALBUMS

    if _is_apple_click_intercepted_error(text):
        reason = (
            "【搜索点击被遮挡】搜索结果链接点击被其他页面元素拦截"
            "（element click intercepted），未能进入专辑页"
        )
        if has_direct:
            reason += "；该专辑已配置 APPLE_DIRECT_ALBUM_URLS 直链，但直链/回退搜索仍失败"
        elif cover_special:
            reason += "；该专辑已启用封面链点击，仍失败"
        else:
            reason += "；可将该专辑加入 APPLE_COVER_CLICK_ALBUMS（封面链）或 APPLE_DIRECT_ALBUM_URLS"
        if text and "element click intercepted" in text.lower():
            short = text.replace("\n", " ")
            if len(short) > 180:
                short = short[:180] + "..."
            reason += f"；原始错误: {short}"
        return reason

    if text:
        return f"搜索未能进入专辑页；详情: {text[:250]}"
    return "搜索未找到专辑或未能进入专辑页"


def _apple_wait_album_page(driver, album_name, href_fallback=""):
    """等待进入专辑页；必要时用原始 href 兜底（保留地区码）。"""
    apple_human_delay(2, 4)
    max_retries = 5
    for retry in range(max_retries):
        current_url = driver.current_url
        if "/album/" in current_url:
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']")
                    )
                )
                print(f"  ✓ 已成功进入专辑页面: {current_url}")
                return current_url, None
            except Exception:
                if retry < max_retries - 1:
                    print(f"  等待歌曲列表加载... (重试 {retry+1}/{max_retries})")
                    apple_human_delay(1, 2)
                continue
        else:
            if retry < max_retries - 1:
                print(f"  页面还在加载，等待中... (重试 {retry+1}/{max_retries})")
                apple_human_delay(1, 2)
            else:
                if href_fallback and navigate_to_album_url_apple(driver, href_fallback):
                    return driver.current_url or href_fallback, None
                print(f"  ✗ 进入的不是专辑页面: {current_url}")
                return None, _format_apple_search_fail_reason(
                    f"点击后未进入专辑页，当前URL: {current_url}", album_name
                )
    if href_fallback and navigate_to_album_url_apple(driver, href_fallback):
        return driver.current_url or href_fallback, None
    print("  ✗ 页面加载超时")
    return None, _format_apple_search_fail_reason("专辑页歌曲列表加载超时", album_name)


def _apple_album_href_slug(album_name: str) -> str:
    """专辑名转 Apple Music URL slug，如 Streetlamp After the Last Shift -> streetlamp-after-the-last-shift。"""
    s = (album_name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _find_apple_cover_lockup_link(driver, artist_name, album_name):
    """遮挡白名单专辑：定位封面链 a[data-testid=product-lockup-link]。

    按最新 DOM：封面链常为 color:transparent 的绝对定位层，文本为空；
    以 href slug / aria-label 中的专辑名为准，不强制艺人名，也不要求 is_displayed。
    """
    slug = _apple_album_href_slug(album_name)
    album_l = (album_name or "").strip().lower()
    artist_l = (artist_name or "").strip().lower()

    # 等封面链出现（搜索结果专辑区）
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "a[data-testid='product-lockup-link'][href*='/album/'], a.product-lockup__link[href*='/album/']",
            ))
        )
    except Exception:
        print("  ⚠ 等待 product-lockup-link 超时，继续尝试查找...")

    # 优先用 slug 精确定位（与截图 href 一致）
    preferred = []
    if slug:
        preferred.extend([
            f"a[data-testid='product-lockup-link'][href*='/{slug}/']",
            f"a[data-testid='product-lockup-link'][href*='/{slug}?']",
            f"a.product-lockup__link[href*='/{slug}/']",
            f"a.product-lockup__link[href*='/{slug}?']",
        ])
    preferred.extend([
        "a[data-testid='product-lockup-link'][href*='/album/']",
        "a.product-lockup__link[href*='/album/']",
    ])

    seen = set()
    candidates = []
    for css in preferred:
        try:
            for link in driver.find_elements(By.CSS_SELECTOR, css):
                try:
                    href = link.get_attribute("href") or ""
                except Exception:
                    continue
                if "/album/" not in href or "/library/" in href:
                    continue
                key = href.split("?")[0]
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(link)
        except Exception:
            continue

    def _score(link):
        href = (link.get_attribute("href") or "").lower()
        aria = (link.get_attribute("aria-label") or "").lower()
        text = (link.text or "").lower()
        blob = f"{aria} {text} {href}"
        score = 0
        if slug and f"/{slug}/" in href.replace("?", "/"):
            score += 100
        elif slug and slug in href:
            score += 80
        if album_l and album_l in aria:
            score += 50
        elif album_l and album_l in blob:
            score += 30
        if artist_l and artist_l in blob:
            score += 10
        return score

    ranked = sorted(candidates, key=_score, reverse=True)
    for link in ranked:
        if _score(link) >= 50:  # slug 或 aria 专辑名命中即可
            print(
                f"  遮挡专辑：命中封面链 product-lockup-link"
                f" | href={link.get_attribute('href')}"
                f" | aria={link.get_attribute('aria-label')!r}"
            )
            return link

    # 调试：列出页面上已有的封面链，便于对照
    if candidates:
        print(f"  ⚠ 找到 {len(candidates)} 个 product-lockup-link，但无一匹配「{album_name}」:")
        for link in candidates[:8]:
            print(
                f"    - href={link.get_attribute('href')}"
                f" aria={link.get_attribute('aria-label')!r}"
            )
    else:
        print("  ⚠ 页面上未找到任何 a[data-testid=product-lockup-link]")
    return None


def _open_apple_album_via_cover_link(driver, artist_name, album_name):
    """遮挡白名单专辑专用：JS 点击封面链；失败则用原始 href 导航（保留地区码）。"""
    cover = _find_apple_cover_lockup_link(driver, artist_name, album_name)
    if not cover:
        return None, _format_apple_search_fail_reason(
            "遮挡专辑未找到匹配的封面链 product-lockup-link"
            "（请确认搜索结果专辑区已加载，且 href/aria 含专辑名）",
            album_name,
        )

    href = cover.get_attribute("href") or ""
    print(f"  点击封面链打开专辑: {href}")

    # 封面链为绝对定位透明层：优先 JS click，比 Selenium 原生 click 更稳
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center'});", cover
        )
        apple_human_delay(0.3, 0.5)
        driver.execute_script("arguments[0].click();", cover)
        print("  ✓ 已用 JS 点击封面链 product-lockup-link")
    except Exception as js_err:
        print(f"  ! JS 点击失败，尝试原生点击: {str(js_err)[:100]}")
        try:
            apple_move_to_element(driver, cover)
            apple_human_delay(0.2, 0.4)
            cover.click()
        except Exception as click_err:
            print(f"  ! 原生点击也失败，改用原始 href 导航: {str(click_err)[:100]}")
            if href and navigate_to_album_url_apple(driver, href):
                return driver.current_url or href, None
            return None, _format_apple_search_fail_reason(click_err, album_name)

    result_url, fail = _apple_wait_album_page(driver, album_name, href_fallback=href)
    if result_url:
        return result_url, None
    # 等待失败再强制 href（保留 /us/ /hk/）
    if href and navigate_to_album_url_apple(driver, href):
        return driver.current_url or href, None
    return None, fail


def _find_apple_normal_album_link(driver, artist_name, album_name):
    """普通专辑：沿用原搜索结果匹配（不优先封面链）。"""
    album_section_selectors = [
        "//h2[contains(text(), '專輯') or contains(text(), 'Albums') or contains(text(), '专辑')]/following::div[contains(@class, 'shelf-grid')][1]//a[contains(@href, '/album/')]",
        "//h3[contains(text(), '專輯') or contains(text(), 'Albums')]/following::div[contains(@class, 'top-search-lockup')][1]//a[contains(@href, '/album/')]",
        "//section[.//*[contains(text(), '專輯') or contains(text(), 'Albums')]]//a[contains(@href, '/album/')]",
    ]

    album_link = None
    for selector in album_section_selectors:
        try:
            album_links = driver.find_elements(By.XPATH, selector)
            for link in album_links:
                if not link.is_displayed():
                    continue
                parent_text = ""
                if link.find_elements(By.XPATH, "ancestor::div[contains(@class, 'lockup')]"):
                    parent_text = link.find_element(
                        By.XPATH, "ancestor::div[contains(@class, 'lockup')]"
                    ).text
                link_text = link.text or ""
                if artist_name.lower() in parent_text.lower() or artist_name.lower() in link_text.lower():
                    album_link = link
                    print("  找到匹配艺人的专辑链接")
                    break
            if album_link:
                break
        except Exception:
            continue

    if not album_link:
        try:
            for link in driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']"):
                if not link.is_displayed():
                    continue
                href = link.get_attribute("href") or ""
                if "/library/" in href:
                    continue
                try:
                    lockup = link.find_element(
                        By.XPATH,
                        "ancestor::div[contains(@class, 'lockup') or contains(@class, 'top-search-lockup')]",
                    )
                    lockup_text = lockup.text.lower()
                    if artist_name.lower() in lockup_text and album_name.lower() in lockup_text:
                        album_link = link
                        print("  找到匹配专辑和艺人的链接")
                        break
                except Exception:
                    continue
        except Exception:
            pass

    if not album_link:
        try:
            for link in driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']"):
                if not link.is_displayed():
                    continue
                href = link.get_attribute("href") or ""
                if "/album/" in href and "/library/" not in href and "/artist/" not in href:
                    # 排除歌曲深链 ?i=
                    if "?i=" in href:
                        continue
                    album_link = link
                    print(f"  使用第一个专辑链接: {href}")
                    break
        except Exception:
            pass
    return album_link


def _open_apple_album_normal_click(driver, album_link, album_name):
    """普通专辑：点击搜索结果链接进入专辑页。"""
    href = album_link.get_attribute("href") or ""
    print(f"  点击专辑链接: {href}")
    try:
        apple_move_to_element(driver, album_link)
        apple_human_delay(0.3, 0.5)
        album_link.click()
    except Exception as e:
        print(f"  ! 点击失败: {e}")
        return None, _format_apple_search_fail_reason(e, album_name)
    return _apple_wait_album_page(driver, album_name, href_fallback="")


def search_album_on_apple(driver, artist_name, album_name):
    """在 Apple Music 上搜索专辑。

    返回 (album_url, fail_reason)：
    - 成功: (url, None)
    - 失败: (None, 可读失败原因)
    仅 APPLE_COVER_CLICK_ALBUMS 中的专辑使用封面链；其余走原搜索点击。
    """
    print(f"搜索专辑: {album_name} (艺人: {artist_name})")

    direct_url = APPLE_DIRECT_ALBUM_URLS.get((album_name or "").strip().lower())
    if direct_url:
        print(f"  使用直链绕过搜索（避免点击被拦截）: {direct_url}")
        if navigate_to_album_url_apple(driver, direct_url):
            return (driver.current_url or direct_url), None
        print("  ✗ 直链导航失败，回退到搜索流程")

    try:
        click_apple_search(driver)

        search_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                "input#search-input__text-field, input.search-input__text-field, "
                "input[data-testid='search-input__text-field'], input[type='search'][role='searchbox']"
            ))
        )
        apple_move_to_element(driver, search_input)
        apple_human_delay(0.3, 0.5)
        search_input.click()
        apple_human_delay(0.3, 0.5)

        search_input.clear()
        apple_human_typing(search_input, album_name)
        apple_human_delay(0.3, 0.5)
        search_input.send_keys(Keys.RETURN)
        apple_human_delay(1, 2)

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    ".top-search-lockup, .shelf-grid, [data-testid='search-results'], "
                    "[data-testid='shelf-item-list']"
                ))
            )
        except Exception:
            print("  等待搜索结果加载...")
            apple_human_delay(1, 2)

        if _is_apple_cover_click_album(album_name):
            print("  该专辑启用「封面链」特殊进入方式（非全局）")
            return _open_apple_album_via_cover_link(driver, artist_name, album_name)

        album_link = _find_apple_normal_album_link(driver, artist_name, album_name)
        if album_link:
            return _open_apple_album_normal_click(driver, album_link, album_name)

        print("  ✗ 未找到专辑链接")
        return None, _format_apple_search_fail_reason("搜索结果中未找到专辑链接", album_name)

    except Exception as e:
        print(f"  ✗ 搜索失败: {e}")
        return None, _format_apple_search_fail_reason(e, album_name)

def navigate_to_album_url_apple(driver, album_url):
    """直接通过URL导航到专辑页面"""
    print(f"  直接导航到专辑: {album_url}")
    
    try:
        driver.get(album_url)
        apple_human_delay(2, 4)
        
        max_retries = 5
        for retry in range(max_retries):
            current_url = driver.current_url
            if "/album/" in current_url:
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']"))
                    )
                    print(f"  ✓ 已成功进入专辑页面")
                    return True
                except:
                    if retry < max_retries - 1:
                        print(f"  等待歌曲列表加载... (重试 {retry+1}/{max_retries})")
                        apple_human_delay(1, 2)
                    continue
            else:
                if retry < max_retries - 1:
                    print(f"  页面还在加载，等待中... (重试 {retry+1}/{max_retries})")
                    apple_human_delay(1, 2)
                else:
                    print(f"  ✗ 导航失败: {current_url}")
                    return False
        
        print(f"  ✗ 页面加载超时")
        return False
        
    except Exception as e:
        print(f"  ✗ 导航失败: {e}")
        return False


def click_apple_home(driver):
    """点击 Apple Music 首页按钮"""
    try:
        # 多语言支持: Home, 首页, Startseite, 首頁
        home_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'navigation-item__label') and (contains(text(), 'Home') or contains(text(), '首页') or contains(text(), 'Startseite') or contains(text(), '首頁'))]"))
        )
        apple_move_to_element(driver, home_btn)
        apple_human_delay(0.3, 0.6)
        home_btn.click()
        apple_human_delay(1, 2)
        print("  ✓ 已点击首页")
        return True
    except Exception as e:
        print(f"  ! 点击首页失败: {e}")
        # 尝试直接访问首页URL
        try:
            driver.get("https://music.apple.com")
            apple_human_delay(1, 2)
            return True
        except:
            return False


def click_apple_search(driver):
    """点击 Apple Music 左侧搜索入口，并等待新版顶部搜索框出现。"""
    search_selectors = [
        (By.XPATH, "//a[contains(@href, '/search') and (@data-testid='search' or .//span[contains(@class, 'navigation-item__label')]) ]"),
        (By.XPATH, "//span[contains(@class, 'navigation-item__label') and (contains(text(), 'Search') or contains(text(), '搜索') or contains(text(), '搜尋') or contains(text(), 'Suche'))]/ancestor::a[1]"),
        (By.XPATH, "//span[contains(@class, 'navigation-item__label') and (contains(text(), 'Search') or contains(text(), '搜索') or contains(text(), '搜尋') or contains(text(), 'Suche'))]"),
    ]

    last_error = None
    for by, selector in search_selectors:
        try:
            search_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((by, selector))
            )
            apple_move_to_element(driver, search_btn)
            apple_human_delay(0.3, 0.6)
            try:
                search_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", search_btn)

            print(f"  ✓ 已点击搜索入口，等待 {APPLE_SEARCH_PANEL_WAIT_SECONDS} 秒加载搜索框")
            time.sleep(APPLE_SEARCH_PANEL_WAIT_SECONDS)
            return True
        except Exception as e:
            last_error = e

    print(f"  ! 点击搜索入口失败: {last_error}")
    return False


def add_songs_to_apple_playlist(driver, playlist_name, track_count, is_first_album=False):
    """从当前专辑页面添加歌曲到播放列表"""
    if is_first_album:
        print(f"  第一张专辑，创建播放列表并添加 {track_count} 首歌曲...")
    else:
        print(f"  添加 {track_count} 首歌曲到播放列表 '{playlist_name}'...")
    
    try:
        # 获取专辑中的所有歌曲行
        songs = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']"))
        )
        
        total_songs = len(songs)
        print(f"  专辑共 {total_songs} 首歌曲")
        
        if total_songs == 0:
            print(f"  ✗ 未找到歌曲")
            return 0
        
        # 随机选择要添加的歌曲索引
        actual_count = min(track_count, total_songs)
        if total_songs <= track_count:
            selected_indices = list(range(total_songs))
            random.shuffle(selected_indices)
        else:
            selected_indices = random.sample(range(total_songs), actual_count)
        
        added_count = 0
        for i, idx in enumerate(selected_indices):
            song_added = False
            max_attempts = 2
            
            for attempt in range(max_attempts):
                if song_added:
                    break
                    
                try:
                    # 尝试关闭可能存在的弹窗
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                        apple_human_delay(0.3, 0.5)
                    except:
                        pass
                    
                    # 重新获取歌曲列表
                    songs = driver.find_elements(By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']")
                    if idx >= len(songs):
                        break
                    
                    song = songs[idx]
                    
                    # 滚动到歌曲位置
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", song)
                    apple_human_delay(0.8, 1.2)
                    
                    # 找到歌曲行的更多按钮
                    more_btn = None
                    try:
                        more_btn = song.find_element(By.CSS_SELECTOR, "span.more-button")
                    except:
                        try:
                            more_btn = song.find_element(By.CSS_SELECTOR, "button[aria-label*='更多'], button[aria-label*='more']")
                        except:
                            pass
                    
                    if not more_btn:
                        if attempt == max_attempts - 1:
                            print(f"    ! 歌曲 {idx+1} 未找到更多按钮")
                        apple_human_delay(0.3, 0.5)
                        continue
                    
                    # 点击更多按钮（处理后台窗口时元素不可交互的问题）
                    try:
                        # 强制滚动到按钮位置并确保可见
                        driver.execute_script("""
                            arguments[0].scrollIntoView({block: 'center'});
                            arguments[0].focus();
                        """, more_btn)
                        apple_human_delay(0.2, 0.4)
                        
                        # 先尝试原生点击
                        apple_move_to_element(driver, more_btn)
                        apple_human_delay(0.3, 0.6)
                        more_btn.click()
                    except Exception as click_err:
                        error_str = str(click_err).lower()
                        # 处理元素被遮挡或不可交互的情况
                        if "intercepted" in error_str or "not interactable" in error_str:
                            try:
                                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                apple_human_delay(0.3, 0.5)
                            except:
                                pass
                            # 使用 JavaScript 强制点击
                            driver.execute_script("arguments[0].click();", more_btn)
                        else:
                            raise click_err
                    
                    apple_human_delay(1, 2)
                    
                    # 如果是第一张专辑的第一首歌曲，需要创建播放列表
                    if is_first_album and i == 0:
                        # 新账号没有播放列表时，"New Playlist"直接在主菜单中
                        # 有播放列表时，需要先点击"Add to Playlist"再点击"New Playlist"
                        # 策略：先尝试直接点击主菜单中的"New Playlist"
                        new_playlist_clicked = False
                        
                        try:
                            # 先尝试直接点击主菜单中的"New Playlist"（新账号情况）
                            new_playlist = WebDriverWait(driver, 3).until(
                                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '新播放清單') or contains(text(), '新建播放列表') or contains(text(), '新增播放列表') or contains(text(), 'New Playlist') or contains(text(), 'Neue Playlist'))]"))
                            )
                            apple_move_to_element(driver, new_playlist)
                            apple_human_delay(0.3, 0.6)
                            new_playlist.click()
                            new_playlist_clicked = True
                            print("    直接点击 New Playlist")
                        except:
                            # 如果直接点击失败，尝试先点击"Add to Playlist"再点击"New Playlist"
                            try:
                                add_to_playlist = WebDriverWait(driver, 3).until(
                                    EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '加入播放清單') or contains(text(), '加入播放列表') or contains(text(), '添加到播放列表') or contains(text(), 'Add to Playlist') or contains(text(), 'Zur Playlist'))]"))
                                )
                                apple_move_to_element(driver, add_to_playlist)
                                apple_human_delay(0.3, 0.6)
                                add_to_playlist.click()
                                
                                apple_human_delay(1, 2)
                                
                                new_playlist = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '新播放清單') or contains(text(), '新建播放列表') or contains(text(), '新增播放列表') or contains(text(), 'New Playlist') or contains(text(), 'Neue Playlist'))]"))
                                )
                                apple_move_to_element(driver, new_playlist)
                                apple_human_delay(0.3, 0.6)
                                new_playlist.click()
                                new_playlist_clicked = True
                                print("    通过 Add to Playlist 点击 New Playlist")
                            except:
                                pass
                        
                        if not new_playlist_clicked:
                            print("    ! 未找到 New Playlist 选项")
                            continue
                        
                        apple_human_delay(1, 2)
                        
                        # 输入播放列表名称
                        name_input = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "input.playlist-title"))
                        )
                        name_input.clear()
                        apple_human_typing(name_input, playlist_name)
                        apple_human_delay(0.3, 0.5)
                        
                        # 勾选公开checkbox
                        try:
                            public_checkbox = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "input.public-checkbox"))
                            )
                            if not public_checkbox.is_selected():
                                driver.execute_script("arguments[0].click();", public_checkbox)
                                apple_human_delay(0.3, 0.5)
                                print("    ✓ 已勾选公开选项")
                        except Exception as e:
                            print(f"    ! 勾选公开选项失败: {e}")
                        
                        apple_human_delay(0.3, 0.5)
                        
                        # 点击"建立"按钮
                        create_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "dialog form button[type='submit']"))
                        )
                        apple_move_to_element(driver, create_btn)
                        apple_human_delay(0.3, 0.6)
                        create_btn.click()
                        print("    ✓ 已点击建立按钮")
                        
                        print(f"    ✓ 播放列表创建成功，已添加第 {idx+1} 首")
                        print("    等待15秒让页面跳转完成...")
                        apple_human_delay(14, 16)
                        
                        return -1  # 返回特殊值表示需要重新搜索专辑
                    else:
                        # 非第一首歌曲，需要先点击"Add to Playlist"再选择播放列表
                        try:
                            add_to_playlist = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '加入播放清單') or contains(text(), '加入播放列表') or contains(text(), '添加到播放列表') or contains(text(), 'Add to Playlist') or contains(text(), 'Zur Playlist'))]"))
                            )
                            apple_move_to_element(driver, add_to_playlist)
                            apple_human_delay(0.3, 0.6)
                            add_to_playlist.click()
                            apple_human_delay(0.35, 0.6)
                        except:
                            print("    ! 未找到 Add to Playlist 选项")
                            continue
                        
                        # 选择目标播放列表 - 不刷新页面，简单重试
                        playlist_found = False
                        max_retry_attempts = 3
                        
                        for retry_attempt in range(max_retry_attempts):
                            try:
                                playlist_option = None
                                deadline = time.time() + 5
                                while time.time() < deadline and playlist_option is None:
                                    playlist_option = find_apple_playlist_menu_option(driver, playlist_name)
                                    if playlist_option is None:
                                        time.sleep(0.25)
                                if playlist_option is None:
                                    raise TimeoutError(f"菜单中未找到播放列表: {playlist_name}")
                                apple_move_to_element(driver, playlist_option)
                                apple_human_delay(0.25, 0.45)
                                try:
                                    playlist_option.click()
                                except Exception:
                                    driver.execute_script("arguments[0].click();", playlist_option)
                                print(f"    ✓ 已添加第 {idx+1} 首")
                                playlist_found = True
                                break
                            except Exception as find_err:
                                if retry_attempt < max_retry_attempts - 1:
                                    # 关闭菜单，等待几秒后重试
                                    try:
                                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                        apple_human_delay(0.3, 0.5)
                                    except:
                                        pass
                                    print(f"    播放列表未找到，等待重试... (尝试 {retry_attempt+1}/{max_retry_attempts})")
                                    # 重新打开 Add to Playlist 菜单
                                    try:
                                        songs = driver.find_elements(By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']")
                                        if idx < len(songs):
                                            song = songs[idx]
                                            more_btn = None
                                            try:
                                                more_btn = song.find_element(By.CSS_SELECTOR, "span.more-button")
                                            except Exception:
                                                try:
                                                    more_btn = song.find_element(By.CSS_SELECTOR, "button[aria-label*='更多'], button[aria-label*='more']")
                                                except Exception:
                                                    pass
                                            if more_btn:
                                                try:
                                                    more_btn.click()
                                                except Exception:
                                                    driver.execute_script("arguments[0].click();", more_btn)
                                                apple_human_delay(0.35, 0.6)
                                                add_to_playlist = WebDriverWait(driver, 5).until(
                                                    EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '加入播放清單') or contains(text(), '加入播放列表') or contains(text(), '添加到播放列表') or contains(text(), 'Add to Playlist') or contains(text(), 'Zur Playlist'))]"))
                                                )
                                                add_to_playlist.click()
                                                apple_human_delay(0.35, 0.6)
                                    except Exception:
                                        pass
                                    apple_human_delay(0.5, 0.8)
                                else:
                                    print(f"    ! 播放列表未找到，跳过歌曲 {idx+1}")
                                    if retry_attempt == max_retry_attempts - 1:
                                        print(f"      调试: 目标={playlist_name!r}, 原因={find_err}")
                                        try:
                                            labels = [
                                                (el.text or "").strip()
                                                for el in driver.find_elements(By.CSS_SELECTOR, "span.contextual-menu-item__option-text")
                                                if (el.text or "").strip()
                                            ]
                                            if labels:
                                                print(f"      当前菜单项: {labels[:12]}")
                                        except Exception:
                                            pass
                        
                        if not playlist_found:
                            # 关闭菜单后继续下一首
                            try:
                                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                            except:
                                pass
                            continue
                    
                    added_count += 1
                    song_added = True
                    apple_song_interval()
                    
                except Exception as e:
                    error_msg = str(e)
                    if "intercepted" in error_msg.lower():
                        apple_human_delay(0.8, 1.2)
                        print(f"    ? 歌曲 {idx+1} 点击被拦截，可能已添加成功（计入统计）")
                        added_count += 1
                        song_added = True
                        apple_song_interval()
                    elif attempt == max_attempts - 1:
                        print(f"    ! 歌曲 {idx+1} 添加失败: {error_msg[:50]}")
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    except:
                        pass
                    apple_human_delay(0.4, 0.7)
        
        print(f"  ✓ 已添加 {added_count} 首歌曲")
        return added_count
        
    except Exception as e:
        print(f"  ✗ 添加歌曲失败: {e}")
        return 0


def process_apple_music_playlist(
    txt_path: Path,
    playlist_name: str,
    track_count_min: int,
    track_count_max: int,
    base_dir: Path = None,
    *,
    email: str | None = None,
    password: str | None = None,
    max_albums: int | None = None,
    auto_close: bool = False,
    login_mode: str | None = None,
    storefront: str | None = None,
):
    """处理 Apple Music 播放列表添加流程 - 支持失败重试和自动补充"""
    sf = (storefront or APPLE_DEFAULT_STOREFRONT).strip().lower()
    # 解析专辑列表
    albums = parse_album_list_from_txt(txt_path)
    if not albums:
        print("✗ 未从 txt 文件中解析到专辑信息")
        return False

    if max_albums is not None and max_albums > 0:
        albums = albums[:max_albums]
        print(f"\n⚠ 验证模式：仅处理前 {len(albums)} 张专辑")
    
    print(f"\n解析到 {len(albums)} 张专辑待添加")
    print(f"将使用播放列表名称: {playlist_name}")
    print(f"目标店面: /{sf}/")
    # 选定后立即占用，避免进程中断/关浏览器异常导致下次仍复用同名
    mark_playlist_name_used(playlist_name)
    
    # 初始化浏览器
    print("\n初始化浏览器...")
    driver = init_apple_browser()
    if not driver:
        return False
    
    # 记录已使用的播放列表名称（用于抽风时创建新列表）
    used_playlist_names = [playlist_name]
    current_playlist_name = playlist_name
    
    # 记录失败的专辑（用于重试与收尾汇总）
    # 每项: {artist, album, track_count, reason, stage, source}
    failed_albums = []
    # 记录已处理的专辑（用于补充时排除）
    processed_albums = set()
    source_index = load_artist_album_source_index("A", base_dir)
    storefront_retried = False  # 加歌失败后是否已做过 URL 店面切换
    
    def _record_failed_album(artist, album, track_count, reason, stage="主流程"):
        source = classify_album_source(artist, album, source_index)
        failed_albums.append({
            "artist": artist,
            "album": album,
            "track_count": track_count,
            "reason": reason,
            "stage": stage,
            "source": source,
        })
        print(f"  ! 失败已记录 [{stage}] [{source}]: {artist} - {album} | {reason}")
    
    try:
        # 登录
        if not login_apple_music(
            driver, email=email, password=password, login_mode=login_mode, storefront=sf
        ):
            print("登录失败，退出")
            return False
        
        apple_human_delay(2, 3)
        
        # 为每张专辑生成一个随机的歌曲数量
        track_counts = list(range(track_count_min, track_count_max + 1))
        random.shuffle(track_counts)
        
        # 计算预期添加的总歌曲数
        expected_total = sum(track_counts[i % len(track_counts)] for i in range(len(albums)))
        
        # 处理每张专辑
        total_added = 0
        playlist_created = False  # 播放列表是否已创建
        i = 0
        
        while i < len(albums):
            album_info = albums[i]
            artist_name = album_info["artist_name"]
            album_name = album_info["album_name"]
            track_count = track_counts[i % len(track_counts)]
            
            # 标记为已处理
            processed_albums.add(f"{artist_name} - {album_name}".lower())
            
            print(f"\n[{i+1}/{len(albums)}] 处理: {artist_name} - {album_name}")
            
            # 搜索专辑，获取专辑URL
            album_url, search_fail_reason = search_album_on_apple(driver, artist_name, album_name)
            if album_url:
                # 添加歌曲
                is_first = not playlist_created
                added = add_songs_to_apple_playlist(driver, current_playlist_name, track_count, is_first_album=is_first)

                # 加歌 0 首且尚未切过店面：疑似店面不对 → URL 改成 /{sf}/ 后重搜重加本张
                if added == 0 and not storefront_retried:
                    cur_url = ""
                    try:
                        cur_url = driver.current_url or ""
                    except Exception:
                        pass
                    if f"/{sf}/" not in cur_url:
                        print(f"  ⚠ 加歌 0 首且 URL 非 /{sf}/（{cur_url}），切换店面后重试本张...", flush=True)
                        storefront_retried = True
                        if _apple_switch_url_to_storefront(driver, sf):
                            # 不计入失败，重搜本张
                            continue
                    else:
                        # 已在目标店面仍 0 首：也强制刷新一次目标首页再重试（用户图1路径）
                        print(f"  ⚠ 加歌 0 首，强制刷新 /{sf}/ 后重试本张...", flush=True)
                        storefront_retried = True
                        try:
                            driver.get(f"https://music.apple.com/{sf}/home")
                            apple_human_delay(2.0, 3.0)
                            _apple_dismiss_geo_banners(driver, max_clicks=2)
                        except Exception:
                            pass
                        continue
                
                # 如果返回-1，表示创建了播放列表并跳转了页面
                if added == -1:
                    playlist_created = True
                    # 重要！不要用URL导航，必须通过搜索来访问专辑，否则播放列表会消失
                    print(f"  通过搜索重新访问专辑（避免播放列表消失）...")
                    album_url_new, re_search_fail = search_album_on_apple(driver, artist_name, album_name)
                    if album_url_new:
                        remaining_count = track_count - 1
                        if remaining_count > 0:
                            added = add_songs_to_apple_playlist(driver, current_playlist_name, remaining_count, is_first_album=False)
                            if added > 0:
                                total_added += added
                        total_added += 1
                    else:
                        print(f"  ! 重新搜索专辑失败，跳过剩余歌曲")
                        if re_search_fail:
                            print(f"  ! 重新搜索失败原因: {re_search_fail}")
                        total_added += 1  # 第一首已添加
                
                # 如果返回-2，表示播放列表同步失败，需要重建
                elif added == -2:
                    print("\n  ⚠ 播放列表同步失败，尝试使用新名称重建...")
                    # 点击首页
                    click_apple_home(driver)
                    apple_human_delay(8, 10)
                    
                    # 获取下一个可用的播放列表名称（立即占用）
                    next_name = claim_next_playlist_name(exclude=set(used_playlist_names))
                    if next_name:
                        current_playlist_name = next_name
                        used_playlist_names.append(next_name)
                        print(f"  使用新播放列表名称: {current_playlist_name}")
                    else:
                        print("  ✗ 无更多可用播放列表名称")
                        return False
                    
                    playlist_created = False  # 需要重新创建
                    continue  # 重新处理当前专辑
                
                else:
                    if added > 0:
                        playlist_created = True
                        total_added += added
                    elif added == 0:
                        _record_failed_album(
                            artist_name, album_name, track_count,
                            "进入专辑页后未能添加任何歌曲（菜单/播放列表匹配或点击失败）",
                            stage="主流程",
                        )
            else:
                _record_failed_album(
                    artist_name, album_name, track_count,
                    search_fail_reason or "搜索未找到专辑或未能进入专辑页",
                    stage="主流程",
                )
            
            i += 1  # 移动到下一张专辑
            apple_human_delay(1, 2)
        
        # ===== 失败专辑重试逻辑（最多1次） =====
        if failed_albums and max_albums is None:
            print(f"\n{'='*60}")
            print(f"⚠ 有 {len(failed_albums)} 张专辑添加失败，尝试重试...")
            for idx, item in enumerate(failed_albums, 1):
                src = item.get("source") or classify_album_source(
                    item.get("artist"), item.get("album"), source_index
                )
                print(f"  [{idx}] [{src}] {item['artist']} - {item['album']} | {item['reason']}")
            print(f"{'='*60}")
            
            retry_failed = []
            for item in failed_albums:
                artist_name = item["artist"]
                album_name = item["album"]
                track_count = item["track_count"]
                print(f"\n[重试] {artist_name} - {album_name}")
                
                # 点击首页重置状态
                click_apple_home(driver)
                apple_human_delay(1, 2)
                
                album_url, search_fail_reason = search_album_on_apple(driver, artist_name, album_name)
                if album_url:
                    added = add_songs_to_apple_playlist(driver, current_playlist_name, track_count, is_first_album=False)
                    if added > 0:
                        total_added += added
                        print(f"  ✓ 重试成功，添加了 {added} 首")
                    else:
                        retry_failed.append({
                            **item,
                            "reason": f"重试后仍未能添加歌曲（原因：{item['reason']}）",
                            "stage": "重试",
                        })
                        print(f"  ✗ 重试仍然失败")
                else:
                    retry_reason = search_fail_reason or item.get("reason") or "重试仍搜索不到专辑"
                    if item.get("reason") and search_fail_reason and item["reason"] not in search_fail_reason:
                        retry_reason = f"{search_fail_reason}（首次：{item['reason']}）"
                    retry_failed.append({
                        **item,
                        "reason": retry_reason,
                        "stage": "重试",
                    })
                    print(f"  ✗ 重试仍然找不到专辑")
                    if search_fail_reason:
                        print(f"  ! 重试失败原因: {search_fail_reason}")
                
                apple_human_delay(1, 2)
            
            failed_albums = retry_failed
        
        # ===== 补充缺失歌曲逻辑 =====
        missing_count = expected_total - total_added
        if missing_count > 0 and base_dir and max_albums is None:
            print(f"\n{'='*60}")
            print(f"⚠ 预期 {expected_total} 首，实际 {total_added} 首，缺少 {missing_count} 首")
            print(f"正在从 other_artists.json 补充...")
            print(f"{'='*60}")
            
            # 加载 other_artists.json
            other_path = base_dir / OTHER_ARTISTS_FILE
            if other_path.exists():
                try:
                    other_data = json.loads(other_path.read_text(encoding="utf-8"))
                    
                    # 构建可用的补充专辑列表（排除已处理的）
                    supplement_albums = []
                    for entry in other_data:
                        artist = entry.get("artist", "")
                        for album in entry.get("albums", []):
                            album_key = f"{artist} - {album}".lower()
                            if album_key not in processed_albums:
                                supplement_albums.append({
                                    "artist_name": artist,
                                    "album_name": album
                                })
                    
                    # 随机打乱补充列表
                    random.shuffle(supplement_albums)
                    
                    supplement_idx = 0
                    while missing_count > 0 and supplement_idx < len(supplement_albums):
                        album_info = supplement_albums[supplement_idx]
                        artist_name = album_info["artist_name"]
                        album_name = album_info["album_name"]
                        supplement_idx += 1
                        
                        # 标记为已处理
                        processed_albums.add(f"{artist_name} - {album_name}".lower())
                        
                        print(f"\n[补充] 搜索: {artist_name} - {album_name}")
                        
                        # 点击首页重置状态
                        click_apple_home(driver)
                        apple_human_delay(1, 2)
                        
                        album_url, search_fail_reason = search_album_on_apple(driver, artist_name, album_name)
                        
                        if album_url:
                            # 补充时，取需要的数量或最大值（取较小值）
                            supplement_track_count = min(missing_count, track_count_max)
                            print(f"  ✓ 找到专辑，补充 {supplement_track_count} 首")
                            
                            added = add_songs_to_apple_playlist(driver, current_playlist_name, supplement_track_count, is_first_album=False)
                            if added > 0:
                                total_added += added
                                missing_count -= added
                                print(f"  ✓ 已补充 {added} 首歌曲，还差 {missing_count} 首")
                        else:
                            print(f"  ✗ 未找到专辑")
                            if search_fail_reason:
                                print(f"  ! 原因: {search_fail_reason}")
                        
                        apple_human_delay(1, 2)
                    
                    if missing_count > 0:
                        print(f"\n⚠ 补充库已用尽，仍缺少 {missing_count} 首歌曲")
                    else:
                        print(f"\n✓ 补充完成！")
                        
                except Exception as e:
                    print(f"✗ 加载 other_artists.json 失败: {e}")
            else:
                print(f"✗ 找不到补充文件: {other_path}")
        
        print(f"\n{'='*60}")
        print(f"✓ Apple Music 播放列表添加完成！")
        print(f"  最终播放列表: {current_playlist_name}")
        print(f"  预期添加: {expected_total} 首")
        print(f"  实际添加: {total_added} 首")
        tip_lines = []
        click_blocked = [
            item for item in failed_albums
            if _is_apple_click_intercepted_error(item.get("reason", ""))
        ]
        if failed_albums:
            if click_blocked:
                tip_lines.append(
                    f"  ⚠ 其中 {len(click_blocked)} 张属于「搜索结果点击被遮挡」类失败"
                    f"（element click intercepted，不是专辑不存在）："
                )
                for idx, item in enumerate(click_blocked, 1):
                    src = item.get("source") or classify_album_source(
                        item.get("artist"), item.get("album"), source_index
                    )
                    tip_lines.append(
                        f"    · [{idx}] {item['artist']} - {item['album']}（来源: {src}）"
                    )
                tip_lines.append(
                    "  处理建议：可将遮挡专辑加入 APPLE_COVER_CLICK_ALBUMS（点封面链），"
                    "或 APPLE_DIRECT_ALBUM_URLS（直链）；"
                    "Streetlamp / Rooms 已在封面链表中。"
                )
            else:
                tip_lines.append(
                    "  说明：本次失败专辑未检测到「搜索点击被遮挡」"
                    "（element click intercepted）类错误。"
                )
        print_failed_albums_summary(
            failed_albums,
            platform_code="A",
            base_dir=base_dir,
            tip="\n".join(tip_lines) if tip_lines else None,
        )
        if len(used_playlist_names) > 1:
            print(f"  尝试过的播放列表: {', '.join(used_playlist_names)}")
        print(f"{'='*60}")
        
        return current_playlist_name  # 返回最终使用的播放列表名称
        
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if driver:
            if auto_close:
                print("\n自动关闭浏览器...")
            else:
                print("\n浏览器保持打开状态...")
                try:
                    input("按 Enter 关闭浏览器...")
                except EOFError:
                    print("  (无交互输入，自动关闭浏览器)")
            try:
                stop_browser_keep_alive()
            except Exception:
                pass
            try:
                driver.quit()
            except Exception:
                pass


def run_apple_for_single_account(
    account_info: dict,
    account_index: int,
    total_accounts: int,
    base_dir: Path,
    args,
) -> bool:
    """为单个 Apple 账号执行完整播单添加：新开浏览器 → 自动登录 → 添加 → 关闭。"""
    email = account_info["email"]
    password = account_info["password"]
    storefront = account_info.get("storefront") or apple_region_to_storefront(
        account_info.get("region")
    )

    print(f"\n{'='*60}")
    print(f"处理 Apple 账号 [{account_index + 1}/{total_accounts}]: {email}（店面 /{storefront}/）")
    print(f"{'='*60}")

    try:
        platform_file = PLATFORM_FILES.get("A")
        main_artists_path = base_dir / platform_file
        other_artists_path = base_dir / OTHER_ARTISTS_FILE

        main_artists = load_json_data(main_artists_path)
        other_artists = load_json_data(other_artists_path)

        history = load_history()
        rng = secrets.SystemRandom()

        main_category = "A"
        other_category = "Other"

        main_history_counts, main_recent_combos = get_category_history_data(main_category, history)
        other_history_counts, other_recent_combos = get_category_history_data(other_category, history)

        other_items = flatten_albums(other_artists)
        main_items = flatten_albums(main_artists)

        part1 = weighted_sample(other_items, other_history_counts, 1, rng, other_recent_combos, unique_artist=True)
        part2 = weighted_sample(main_items, main_history_counts, args.Count, rng, main_recent_combos, unique_artist=True)

        part1_artists = {item.split(" - ", 1)[0] for item in part1}
        other_items_filtered = [item for item in other_items if item.split(" - ", 1)[0] not in part1_artists]
        part3 = weighted_sample(other_items_filtered, other_history_counts, 4, rng, other_recent_combos, unique_artist=True)

        final_list = part1 + part2 + part3

        update_history(part1 + part3, other_category, history)
        update_history(part2, main_category, history)
        save_history(history)

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_filename = f"A+{timestamp}.txt"
        output_path = base_dir / output_filename

        output_lines = []
        for item in final_list:
            artist, album = split_artist_album(item)
            output_lines.append(format_output_item(artist, album))
        output_path.write_text("\n".join(output_lines), encoding="utf-8")

        print(f"已生成播放列表文件：{output_filename}")
        print(f"  总计: {len(final_list)} 首")

        playlist_name = claim_next_playlist_name()
        if not playlist_name:
            print("✗ 无可用的播放列表名称")
            return False

        max_albums = getattr(args, "apple_max_albums", None)
        if max_albums is None:
            max_albums = APPLE_MAX_ALBUMS

        print(f"\n开始添加歌曲到 Apple Music 播放列表...")
        result = process_apple_music_playlist(
            output_path,
            playlist_name,
            APPLE_TRACK_COUNT_MIN,
            APPLE_TRACK_COUNT_MAX,
            base_dir,
            email=email,
            password=password,
            max_albums=max_albums,
            auto_close=True,
            login_mode=getattr(args, "apple_login_mode", None) or APPLE_LOGIN_MODE,
            storefront=storefront,
        )
        if result:
            print(f"\n✓ 账号 {email} 处理完成")
            return True
        print(f"\n✗ 账号 {email} 处理失败")
        return False
    except Exception as e:
        print(f"✗ 账号 {email} 处理出错: {e}")
        import traceback
        traceback.print_exc()
        return False


# ==================== Qobuz 集成功能 ====================

def qobuz_human_delay(min_sec=0.3, max_sec=0.8):
    """模拟人类操作的随机延迟"""
    time.sleep(random.uniform(min_sec, max_sec))


def qobuz_human_typing(element, text, min_delay=0.02, max_delay=0.08):
    """模拟人类打字速度"""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def qobuz_move_to_element(driver, element):
    """模拟人类鼠标移动到元素"""
    actions = ActionChains(driver)
    actions.move_to_element(element)
    actions.pause(random.uniform(0.2, 0.5))
    actions.perform()


def init_qobuz_browser():
    """初始化 Chrome 浏览器（无痕模式）"""
    if not SELENIUM_AVAILABLE:
        print("✗ 错误：未安装 selenium，请运行: pip install selenium")
        return None
    
    try:
        print("  启动 Chrome 浏览器...")
        driver = init_chrome_driver_with_retry("Qobuz")
        if not driver:
            return None
        
        # 浏览器保活已禁用（用户反馈：妨碍手工登录工作）
        # start_browser_keep_alive(driver, interval=30)  # 已禁用
        
        print("  ✓ 浏览器初始化成功")
        return driver
        
    except Exception as e:
        print(f"✗ 浏览器初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def login_qobuz(driver):
    """登录 Qobuz - 需要人工确认"""
    print("正在访问 Qobuz 登录页面...")
    driver.get(QOBUZ_LOGIN_URL)
    qobuz_human_delay(0.5, 1)

    print("\n请在浏览器中完成登录。")
    print("完成后输入 y 并按回车继续，输入 n 取消。\n")

    deadline = time.time() + APPLE_LOGIN_CONFIRM_TIMEOUT

    while True:
        remaining = max(0, int(deadline - time.time()))
        if remaining <= 0:
            print("✗ Qobuz 登录等待超时")
            return False

        minutes, seconds = divmod(remaining, 60)
        user_input = input(
            f"是否已登录成功？(y/n) [剩余 {minutes:02d}:{seconds:02d}]: "
        ).strip().lower()

        if user_input == 'y':
            print("✓ 登录成功")
            return True
        elif user_input == 'n':
            print("✗ 登录失败")
            return False
        else:
            print("请输入 y 或 n")
            continue


def search_album_on_qobuz(driver, artist_name, album_name):
    """在 Qobuz 上搜索专辑。

    返回 (album_url, fail_reason)：
    - 成功: (url, None)
    - 失败: (None, 可读原因)，便于收尾汇总
    """
    print(f"搜索专辑: {album_name} (艺人: {artist_name})")
    
    try:
        # ===== 先关闭可能存在的模态框 =====
        try:
            # 先按 ESC 关闭弹窗
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            qobuz_human_delay(0.5, 0.8)
        except:
            pass
        
        # 尝试关闭 modal-backdrop
        try:
            modal_backdrops = driver.find_elements(By.CSS_SELECTOR, "div.modal-backdrop, .modal.show, .modal-content")
            if modal_backdrops:
                print("  检测到模态框，尝试关闭...")
                # 再按一次 ESC
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                qobuz_human_delay(0.5, 0.8)
                # 尝试点击关闭按钮
                close_btns = driver.find_elements(By.CSS_SELECTOR, "button.close, button.btn-close, [aria-label='Close'], .modal-header button")
                for btn in close_btns:
                    try:
                        if btn.is_displayed():
                            driver.execute_script("arguments[0].click();", btn)
                            qobuz_human_delay(0.5, 0.8)
                            break
                    except:
                        continue
                # 再按一次 ESC 确保关闭
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                qobuz_human_delay(0.5, 0.8)
        except:
            pass
        
        # 点击搜索框
        search_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input.SearchBar__input"))
        )
        qobuz_move_to_element(driver, search_input)
        qobuz_human_delay(0.3, 0.5)
        
        # 尝试点击，如果被拦截则使用 JS 点击
        try:
            search_input.click()
        except Exception as click_err:
            if "intercepted" in str(click_err).lower():
                print("  搜索框点击被拦截，尝试 JS 点击...")
                # 再次尝试关闭模态框
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                qobuz_human_delay(0.5, 0.8)
                driver.execute_script("arguments[0].click();", search_input)
            else:
                raise click_err
        qobuz_human_delay(0.3, 0.5)
        
        # 清空并输入搜索词
        search_input.clear()
        search_query = f"{artist_name} {album_name}"
        qobuz_human_typing(search_input, search_query)
        qobuz_human_delay(0.3, 0.5)
        search_input.send_keys(Keys.RETURN)
        
        qobuz_human_delay(0.5, 1)  # 等待搜索结果加载
        
        # 等待搜索结果
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".album-item, .search-results, [class*='album']"))
            )
        except:
            print("  等待搜索结果加载...")
            qobuz_human_delay(0.5, 1)
        
        # 查找专辑链接
        album_link = None
        try:
            album_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']")
            for link in album_links:
                if not link.is_displayed():
                    continue
                link_text = link.text.lower() if link.text else ""
                try:
                    parent = link.find_element(By.XPATH, "./..")
                    parent_text = parent.text.lower() if parent.text else ""
                except:
                    parent_text = ""
                
                if (artist_name.lower() in link_text or artist_name.lower() in parent_text or
                    album_name.lower() in link_text or album_name.lower() in parent_text):
                    album_link = link
                    print(f"  找到匹配专辑链接")
                    break
            
            if not album_link and album_links:
                for link in album_links:
                    if link.is_displayed():
                        album_link = link
                        print(f"  使用第一个可见专辑链接")
                        break
        except Exception as e:
            print(f"  查找专辑链接出错: {e}")
        
        if album_link:
            href = album_link.get_attribute("href") or ""
            print(f"  点击专辑链接: {href}")
            
            # 先滚动到页面中央，避免被底部播放器进度条遮挡
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", album_link)
            qobuz_human_delay(0.3, 0.5)
            
            qobuz_move_to_element(driver, album_link)
            qobuz_human_delay(0.3, 0.5)
            
            # 尝试点击，如果被拦截则使用 JS 点击
            try:
                album_link.click()
            except Exception as click_err:
                if "intercepted" in str(click_err).lower():
                    print("  点击被拦截，使用 JS 点击...")
                    driver.execute_script("arguments[0].click();", album_link)
                else:
                    raise click_err
            
            qobuz_human_delay(5, 8)
            
            current_url = driver.current_url
            if "/album/" in current_url:
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".track-row, .track, [class*='track']"))
                    )
                    print(f"  ✓ 已成功进入专辑页面: {current_url}")
                    return current_url, None
                except:
                    print(f"  等待歌曲列表加载...")
                    qobuz_human_delay(0.5, 1)
                    return current_url, None
            else:
                print(f"  ✗ 进入的不是专辑页面: {current_url}")
                return None, f"点击后未进入专辑页，当前URL: {current_url}"
        else:
            print(f"  ✗ 未找到专辑链接")
            return None, "搜索结果中未找到专辑链接"
            
    except Exception as e:
        print(f"  ✗ 搜索失败: {e}")
        import traceback
        traceback.print_exc()
        err = str(e).replace("\n", " ")
        if len(err) > 220:
            err = err[:220] + "..."
        if "intercepted" in err.lower():
            return None, f"页面元素点击被拦截（可能被弹窗/播放条遮挡）: {err}"
        return None, f"Qobuz 页面搜索异常: {err}"


def create_qobuz_playlist(driver, playlist_name):
    """在 Qobuz 上创建播放列表（支持多语言）"""
    print(f"\n创建播放列表: {playlist_name}")
    
    try:
        # 直接访问播放列表管理页
        driver.get("https://play.qobuz.com/user/library/playlists")
        qobuz_human_delay(0.5, 1)
        
        # 点击"Create a playlist"按钮
        create_btn_selectors = [
            "span.pct.pct-add.global__button.global__button--playlist",
            "[class*='global__button--playlist']",
            ".user_library-buttons span.pct-add",
        ]
        
        create_btn = None
        for selector in create_btn_selectors:
            try:
                create_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if create_btn:
                    break
            except:
                continue
        
        if not create_btn:
            raise Exception("未找到 Create a playlist 按钮")
        
        qobuz_move_to_element(driver, create_btn)
        qobuz_human_delay(0.3, 0.5)
        create_btn.click()
        qobuz_human_delay(0.5, 1)
        
        # 等待弹窗出现，输入播放列表名称
        name_input_selectors = [
            "input#playlist-name-input",
            "input.playlist-name__input",
            ".modal-playlist input[type='text']",
            "form.modal-form input[type='text']",
            ".modal-body input[type='text']",
        ]
        
        name_input = None
        for selector in name_input_selectors:
            try:
                name_input = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if name_input:
                    break
            except:
                continue
        
        if not name_input:
            raise Exception("未找到播放列表名称输入框")
        
        name_input.clear()
        qobuz_human_typing(name_input, playlist_name)
        qobuz_human_delay(0.3, 0.5)
        
        # 点击Create按钮 - 支持多语言
        create_confirm_btn = None
        
        try:
            create_confirm_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']:not([disabled])"))
            )
        except:
            pass
        
        if not create_confirm_btn:
            for text in QOBUZ_CREATE_BUTTON_TEXTS:
                try:
                    create_confirm_btn = WebDriverWait(driver, 2).until(
                        EC.element_to_be_clickable((By.XPATH, f"//button[contains(text(), '{text}')]"))
                    )
                    if create_confirm_btn:
                        break
                except:
                    continue
        
        if not create_confirm_btn:
            raise Exception("未找到创建确认按钮")
        
        qobuz_move_to_element(driver, create_confirm_btn)
        qobuz_human_delay(0.3, 0.5)
        try:
            create_confirm_btn.click()
        except:
            driver.execute_script("arguments[0].click();", create_confirm_btn)
        
        qobuz_human_delay(2, 3)
        print(f"✓ 播放列表创建成功: {playlist_name}")
        return True
        
    except Exception as e:
        print(f"✗ 创建播放列表失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def add_songs_to_qobuz_playlist(driver, playlist_name, track_count):
    """从当前专辑页面添加歌曲到播放列表"""
    print(f"  添加 {track_count} 首歌曲到播放列表 '{playlist_name}'...")
    
    try:
        qobuz_human_delay(2, 3)
        
        # ===== 先滚动页面确保所有歌曲加载 =====
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        qobuz_human_delay(0.5, 0.8)
        driver.execute_script("window.scrollTo(0, 0);")
        qobuz_human_delay(0.5, 0.8)
        
        # ===== 获取歌曲总数：通过统计可见的"更多"按钮数量 =====
        # 使用 class 选择器（不依赖语言）
        all_more_btns = driver.find_elements(By.CSS_SELECTOR, "button.ListItem__actions")
        all_more_btns = [btn for btn in all_more_btns if btn.is_displayed()]
        
        if len(all_more_btns) < 2:
            # fallback: 尝试其他选择器
            all_more_btns = driver.find_elements(By.CSS_SELECTOR, "button.icon-more-vertical")
            all_more_btns = [btn for btn in all_more_btns if btn.is_displayed()]
        
        total_songs = len(all_more_btns)
        print(f"  专辑共 {total_songs} 首歌曲")
        
        if total_songs == 0:
            print(f"  ✗ 未找到歌曲")
            return 0
        
        # ===== 获取所有可见的行号，确定有效的行号范围 =====
        track_number_elements = driver.find_elements(By.CSS_SELECTOR, "span.ListItem__number")
        track_numbers = []
        for elem in track_number_elements:
            if elem.is_displayed():
                try:
                    num = int(elem.text.strip())
                    track_numbers.append(num)
                except:
                    pass
        
        # 确定有效行号：如果行号数量与按钮数量一致，使用行号；否则使用1-based索引
        if len(track_numbers) == total_songs:
            valid_track_nums = sorted(track_numbers)
        else:
            # 行号不匹配，使用1到total_songs的索引
            valid_track_nums = list(range(1, total_songs + 1))
        
        # 随机选择要添加的歌曲行号（1-based）
        actual_count = min(track_count, total_songs)
        if total_songs <= track_count:
            selected_track_nums = valid_track_nums.copy()
            random.shuffle(selected_track_nums)
        else:
            selected_track_nums = random.sample(valid_track_nums, actual_count)
        
        # ===== 按行号从小到大排序处理，避免虚拟滚动导致元素丢失 =====
        selected_track_nums.sort()
        
        added_count = 0
        added_tracks = set()  # 记录已添加的行号
        
        for track_num in selected_track_nums:
            if track_num in added_tracks:
                continue
                
            song_added = False
            max_attempts = 2
            
            for attempt in range(max_attempts):
                if song_added:
                    break
                    
                try:
                    # 尝试关闭可能存在的弹窗
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                        qobuz_human_delay(0.3, 0.5)
                    except:
                        pass
                    
                    # ===== 通过行号查找对应的歌曲行，然后找到其"更多"按钮 =====
                    more_btn = None
                    
                    # 方法1: 通过行号元素找到对应的更多按钮
                    try:
                        # 找到显示指定行号的 span 元素
                        track_num_xpath = f"//span[contains(@class, 'ListItem__number') and normalize-space(text())='{track_num}']"
                        track_num_elem = driver.find_element(By.XPATH, track_num_xpath)
                        
                        # 滚动到该元素位置
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", track_num_elem)
                        qobuz_human_delay(0.8, 1.2)
                        
                        # 找到同一行的"更多"按钮 - 使用 class 选择器（不依赖语言）
                        parent_row = track_num_elem.find_element(By.XPATH, "./ancestor::div[contains(@class, 'ListItem')]")
                        try:
                            more_btn = parent_row.find_element(By.CSS_SELECTOR, "button.ListItem__actions")
                        except:
                            try:
                                more_btn = parent_row.find_element(By.CSS_SELECTOR, "button.icon-more-vertical")
                            except:
                                more_btn = None
                    except:
                        pass
                    
                    # 方法2: 如果方法1失败，通过位置匹配
                    if not more_btn:
                        try:
                            # 再次滚动到大概位置
                            scroll_ratio = (track_num - 1) / max(total_songs - 1, 1)
                            scroll_height = driver.execute_script("return document.body.scrollHeight")
                            driver.execute_script(f"window.scrollTo(0, {int(scroll_height * scroll_ratio * 0.7)});")
                            qobuz_human_delay(0.8, 1.2)
                            
                            # 获取当前可见的行号元素
                            track_num_elements = driver.find_elements(By.CSS_SELECTOR, "span.ListItem__number")
                            for elem in track_num_elements:
                                if elem.is_displayed():
                                    try:
                                        if int(elem.text.strip()) == track_num:
                                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                                            qobuz_human_delay(0.5, 0.8)
                                            parent_row = elem.find_element(By.XPATH, "./ancestor::div[contains(@class, 'ListItem')]")
                                            try:
                                                more_btn = parent_row.find_element(By.CSS_SELECTOR, "button.ListItem__actions")
                                            except:
                                                try:
                                                    more_btn = parent_row.find_element(By.CSS_SELECTOR, "button.icon-more-vertical")
                                                except:
                                                    pass
                                            if more_btn:
                                                break
                                    except:
                                        continue
                        except:
                            pass
                    
                    if not more_btn:
                        if attempt == max_attempts - 1:
                            print(f"    ! 第 {track_num} 首未找到更多按钮")
                        qobuz_human_delay(0.3, 0.5)
                        continue
                    
                    # 悬停并点击更多按钮（处理后台窗口时元素不可交互的问题）
                    try:
                        # 强制滚动到按钮位置并确保可见
                        driver.execute_script("""
                            arguments[0].scrollIntoView({block: 'center'});
                            arguments[0].focus();
                        """, more_btn)
                        qobuz_human_delay(0.2, 0.4)
                        
                        qobuz_move_to_element(driver, more_btn)
                        qobuz_human_delay(0.3, 0.5)
                        more_btn.click()
                    except Exception as click_err:
                        error_str = str(click_err).lower()
                        if "intercepted" in error_str or "not interactable" in error_str:
                            # 使用 JavaScript 强制点击
                            driver.execute_script("arguments[0].click();", more_btn)
                        else:
                            raise click_err
                    
                    qobuz_human_delay(1.5, 2.5)
                    
                    # 点击"Add to playlists" - 支持多语言
                    add_to_playlist_selectors = [
                        "ul.menu-list a[role='button']",
                        "ul.menu-list li a",
                    ]
                    
                    add_to_playlist_btn = None
                    for css_selector in add_to_playlist_selectors:
                        try:
                            menu_links = driver.find_elements(By.CSS_SELECTOR, css_selector)
                            for link in menu_links:
                                if link.is_displayed():
                                    link_text = link.text.strip()
                                    for add_text in QOBUZ_ADD_TO_PLAYLIST_TEXTS:
                                        if add_text.lower() in link_text.lower():
                                            add_to_playlist_btn = link
                                            break
                                    if add_to_playlist_btn:
                                        break
                            if add_to_playlist_btn:
                                break
                        except:
                            continue
                    
                    if not add_to_playlist_btn:
                        for add_text in QOBUZ_ADD_TO_PLAYLIST_TEXTS:
                            try:
                                add_to_playlist_btn = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.XPATH, f"//ul[contains(@class, 'menu-list')]//a[contains(text(), '{add_text}')]"))
                                )
                                if add_to_playlist_btn:
                                    break
                            except:
                                continue
                    
                    if not add_to_playlist_btn:
                        raise Exception("未找到 Add to playlists 菜单项")
                    
                    qobuz_move_to_element(driver, add_to_playlist_btn)
                    qobuz_human_delay(0.3, 0.6)
                    try:
                        add_to_playlist_btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", add_to_playlist_btn)
                    
                    qobuz_human_delay(1.5, 2.5)
                    
                    # 在弹窗中找到已创建的播放列表的 Add 按钮
                    playlist_add_selectors = [
                        "button.global__button--add-to-playlist",
                        "button[class*='global__button--add-to-playlist']",
                        "button[class*='pct-add-playlist']",
                        ".add-playlist button",
                    ]
                    
                    playlist_add_btn = None
                    for css_selector in playlist_add_selectors:
                        try:
                            btns = driver.find_elements(By.CSS_SELECTOR, css_selector)
                            for btn in btns:
                                if btn.is_displayed():
                                    try:
                                        parent = btn.find_element(By.XPATH, "./ancestor::li[contains(@class, 'add-playlist')]")
                                        parent_text = parent.text if parent else ""
                                        if playlist_name in parent_text:
                                            playlist_add_btn = btn
                                            break
                                    except:
                                        playlist_add_btn = btn
                                        break
                            if playlist_add_btn:
                                break
                        except:
                            continue
                    
                    if not playlist_add_btn:
                        for add_text in QOBUZ_ADD_BUTTON_TEXTS:
                            try:
                                playlist_add_btn = WebDriverWait(driver, 2).until(
                                    EC.element_to_be_clickable((By.XPATH, f"//div[contains(., '{playlist_name}')]//button[contains(text(), '{add_text}')]"))
                                )
                                if playlist_add_btn:
                                    break
                            except:
                                continue
                    
                    if not playlist_add_btn:
                        raise Exception(f"未找到播放列表 '{playlist_name}' 的 Add 按钮")
                    
                    qobuz_move_to_element(driver, playlist_add_btn)
                    qobuz_human_delay(0.3, 0.6)
                    try:
                        playlist_add_btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", playlist_add_btn)
                    
                    print(f"    ✓ 已添加第 {track_num} 首")
                    
                    added_count += 1
                    song_added = True
                    added_tracks.add(track_num)  # 记录已添加的行号
                    
                    # ===== 等待提示条消失 =====
                    qobuz_human_delay(3.5, 4.5)
                    
                except Exception as e:
                    error_msg = str(e)
                    if attempt == max_attempts - 1:
                        print(f"    ! 歌曲 {track_num} 添加失败: {error_msg[:80]}")
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    except:
                        pass
                    qobuz_human_delay(0.5, 1)
        
        print(f"  ✓ 已添加 {added_count} 首歌曲")
        return added_count
        
    except Exception as e:
        print(f"  ✗ 添加歌曲失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


def process_qobuz_playlist(txt_path: Path, playlist_name: str, track_count_min: int, track_count_max: int):
    """处理 Qobuz 播放列表添加流程"""
    # 解析专辑列表
    albums = parse_album_list_from_txt(txt_path)
    if not albums:
        print("✗ 未从 txt 文件中解析到专辑信息")
        return False
    
    print(f"\n解析到 {len(albums)} 张专辑待添加")
    print(f"将使用播放列表名称: {playlist_name}")
    
    # 初始化浏览器
    print("\n初始化浏览器...")
    driver = init_qobuz_browser()
    if not driver:
        return False
    
    try:
        # 登录
        if not login_qobuz(driver):
            print("登录失败，退出")
            return False
        
        qobuz_human_delay(2, 3)
        
        # 创建播放列表
        if not create_qobuz_playlist(driver, playlist_name):
            print("创建播放列表失败，退出")
            return False
        
        # 为每张专辑生成一个随机的歌曲数量
        track_counts = list(range(track_count_min, track_count_max + 1))
        random.shuffle(track_counts)
        expected_total = sum(track_counts[i % len(track_counts)] for i in range(len(albums)))
        
        # 失败专辑明细（Qobuz 原因侧重页面搜索/菜单加歌）
        failed_albums = []
        qobuz_base_dir = Path(txt_path).resolve().parent if txt_path else Path(__file__).resolve().parent
        source_index = load_artist_album_source_index("Q", qobuz_base_dir)
        
        def _record_qobuz_failed(artist, album, reason, stage="主流程"):
            source = classify_album_source(artist, album, source_index)
            failed_albums.append({
                "artist": artist,
                "album": album,
                "reason": reason,
                "stage": stage,
                "source": source,
            })
            print(f"  ! 失败已记录 [{stage}] [{source}]: {artist} - {album} | {reason}")
        
        # 处理每张专辑
        total_added = 0
        for i, album_info in enumerate(albums):
            artist_name = album_info["artist_name"]
            album_name = album_info["album_name"]
            track_count = track_counts[i % len(track_counts)]
            
            print(f"\n[{i+1}/{len(albums)}] 处理: {artist_name} - {album_name}")
            
            # 搜索专辑
            album_url, search_fail_reason = search_album_on_qobuz(driver, artist_name, album_name)
            if album_url:
                # 添加歌曲到已创建的播放列表
                added = add_songs_to_qobuz_playlist(driver, playlist_name, track_count)
                total_added += added
                if added == 0:
                    _record_qobuz_failed(
                        artist_name, album_name,
                        "进入专辑页后未能添加任何歌曲（更多菜单/加入播放列表匹配或点击失败）",
                        stage="主流程",
                    )
            else:
                _record_qobuz_failed(
                    artist_name, album_name,
                    search_fail_reason or "搜索未找到专辑或未能进入专辑页",
                    stage="主流程",
                )
            
            qobuz_human_delay(0.5, 1)
        
        print(f"\n{'='*60}")
        print(f"✓ Qobuz 播放列表添加完成！")
        print(f"  播放列表: {playlist_name}")
        print(f"  预期添加: {expected_total} 首歌曲")
        print(f"  实际添加: {total_added} 首歌曲")
        print_failed_albums_summary(
            failed_albums,
            platform_code="Q",
            base_dir=qobuz_base_dir,
            tip="  说明：Qobuz 失败多为页面搜索无结果、点击被遮挡，或专辑页菜单加歌失败。",
        )
        print(f"{'='*60}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if driver:
            print("\n浏览器保持打开状态...")
            try:
                input("按 Enter 关闭浏览器...")
            except EOFError:
                print("  (无交互输入，自动关闭浏览器)")
            try:
                stop_browser_keep_alive()
            except Exception:
                pass
            try:
                driver.quit()
            except Exception:
                pass

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
    # ===== 记录程序开始时间 =====
    start_time = time.time()
    removed_proxies = sanitize_stale_process_proxy()

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
    parser.add_argument(
        "--tidal-delete",
        action="store_true",
        help="启用 Tidal 删除模式：从所有播放列表中删除指定专辑的歌曲"
    )
    parser.add_argument(
        "--tidal-login-mode",
        choices=["auto", "mcp", "selenium"],
        default=None,
        help=f"Tidal 登录方式，默认 {TIDAL_LOGIN_MODE}（auto=全自动浏览器）"
    )
    parser.add_argument(
        "--apple-max-albums",
        type=int,
        default=None,
        help="Apple 每个账号最多处理专辑数（验证用，例如 2）；默认全量",
    )
    parser.add_argument(
        "--apple-login-mode",
        choices=["auto", "manual"],
        default=None,
        help=f"Apple 登录方式，默认 {APPLE_LOGIN_MODE}（auto=读 apple_email.txt 自动登录；manual=浏览器手动登录后输入 y）",
    )
    args = parser.parse_args()

    log_file = setup_logging(args.Platform)
    print(f"v{APP_VERSION} Playlist 自动化工具")
    print(f"日志文件: {log_file}")
    if removed_proxies:
        print("⚠ 检测到本地 VPN/代理未运行，已改为直连（避免 127.0.0.1 代理拒绝连接）：")
        for item in removed_proxies:
            print(f"  - 已忽略 {item}")
        print("  提示：若需走 VPN 测试 Tidal，请先启动狗急加速/代理客户端。")

    # 当平台为 Tidal 时，默认启用 Tidal 添加功能
    if args.Platform == "T" and not args.tidal:
        args.tidal = True
    
    # 根据配置文件的 TIDAL_MODE 设置删除模式
    if args.Platform == "T" and TIDAL_MODE == 2:
        args.tidal_delete = True
    
    # 当平台为 Apple 时，默认启用 Apple Music 添加功能
    apple_enabled = (args.Platform == "A")
    
    # 当平台为 Qobuz 时，默认启用 Qobuz 添加功能
    qobuz_enabled = (args.Platform == "Q")

    # ===== Tidal 多账号自动化处理（如果启用） =====
    tidal_session = None
    tidal_accounts = []
    if args.tidal and not args.tidal_delete:
        if args.Platform != "T":
            print("⚠ Tidal 添加功能仅支持 Tidal 平台 (--Platform T)")
            args.Platform = "T"
        
        print("="*60)
        print("Tidal 播放列表自动添加工具（多账号自动化）")
        print("="*60)
        
        # 检查 tidal_email.txt 文件
        tidal_accounts = load_tidal_accounts()
        
        if not tidal_accounts:
            print(f"\n✗ 未找到 Tidal 账号数据！")
            print(f"  请在 {TIDAL_EMAIL_FILE} 文件中添加账号信息，格式如下：")
            print(f"  邮箱")
            print(f"  密码")
            print(f"  （空行分隔不同账号）")
            return
        
        print(f"\n✓ 找到 {len(tidal_accounts)} 个 Tidal 账号")
        for i, acc in enumerate(tidal_accounts):
            print(f"  [{i+1}] {acc['email']}")
        
        print()
    
    # ===== Apple Music 预检查（如果启用） =====
    apple_accounts = []
    if apple_enabled:
        if not SELENIUM_AVAILABLE:
            print("✗ 错误：未安装 selenium，请运行: pip install selenium")
            return

        apple_login_mode = (getattr(args, "apple_login_mode", None) or APPLE_LOGIN_MODE or "auto").strip().lower()
        print("="*60)
        if apple_login_mode == "manual":
            print("Apple Music 播放列表添加工具（手动登录模式）")
        else:
            print("Apple Music 播放列表自动添加工具（多账号自动化）")
        print("="*60)
        print(f"登录模式: {apple_login_mode}")

        if apple_login_mode == "manual":
            # 手动登录：不读账号文件，单次跑列表后人工确认 y
            platform_file = PLATFORM_FILES.get("A")
            main_artists_path = base_dir / platform_file
            other_artists_path = base_dir / OTHER_ARTISTS_FILE
            main_artists = load_json_data(main_artists_path)
            other_artists = load_json_data(other_artists_path)
            history = load_history()
            rng = secrets.SystemRandom()
            main_history_counts, main_recent_combos = get_category_history_data("A", history)
            other_history_counts, other_recent_combos = get_category_history_data("Other", history)
            other_items = flatten_albums(other_artists)
            main_items = flatten_albums(main_artists)
            part1 = weighted_sample(other_items, other_history_counts, 1, rng, other_recent_combos, unique_artist=True)
            part2 = weighted_sample(main_items, main_history_counts, args.Count, rng, main_recent_combos, unique_artist=True)
            part1_artists = {item.split(" - ", 1)[0] for item in part1}
            other_items_filtered = [item for item in other_items if item.split(" - ", 1)[0] not in part1_artists]
            part3 = weighted_sample(other_items_filtered, other_history_counts, 4, rng, other_recent_combos, unique_artist=True)
            final_list = part1 + part2 + part3
            update_history(part1 + part3, "Other", history)
            update_history(part2, "A", history)
            save_history(history)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            output_filename = f"A+{timestamp}.txt"
            output_path = base_dir / output_filename
            output_lines = []
            for item in final_list:
                artist, album = split_artist_album(item)
                output_lines.append(format_output_item(artist, album))
            output_path.write_text("\n".join(output_lines), encoding="utf-8")
            print(f"已生成播放列表文件：{output_filename}")
            print(f"  总计: {len(final_list)} 首")
            playlist_name = claim_next_playlist_name()
            if not playlist_name:
                print("✗ 无可用的播放列表名称")
                return
            max_albums = getattr(args, "apple_max_albums", None)
            if max_albums is None:
                max_albums = APPLE_MAX_ALBUMS
            print(f"\n开始添加歌曲到 Apple Music 播放列表...")
            ok = process_apple_music_playlist(
                output_path,
                playlist_name,
                APPLE_TRACK_COUNT_MIN,
                APPLE_TRACK_COUNT_MAX,
                base_dir,
                email=None,
                password=None,
                max_albums=max_albums,
                auto_close=False,
                login_mode="manual",
            )
            if ok:
                print("\n✓ Apple Music（手动登录）处理完成")
            else:
                print("\n✗ Apple Music（手动登录）处理失败")
            return

        apple_accounts = load_apple_accounts()
        if not apple_accounts:
            print(f"\n✗ 未找到 Apple 账号数据！")
            print(f"  请在 {APPLE_EMAIL_FILE} 文件中添加账号信息，格式如下：")
            print(f"  邮箱")
            print(f"  密码")
            print(f"  （空行分隔不同账号）")
            print(f"  或将 APPLE_LOGIN_MODE / --apple-login-mode 设为 manual 使用手动登录")
            return

        print(f"\n✓ 找到 {len(apple_accounts)} 个 Apple 账号")
        for i, acc in enumerate(apple_accounts):
            sf = acc.get("storefront") or apple_region_to_storefront(acc.get("region"))
            print(f"  [{i+1}] {acc['email']}  /{sf}/")
        if getattr(args, "apple_max_albums", None):
            print(f"  验证限制：每个账号最多处理 {args.apple_max_albums} 张专辑")
        print()

        print(f"\n{'='*60}")
        print(f"开始 Apple 多账号自动化处理（共 {len(apple_accounts)} 个账号）")
        print(f"{'='*60}")

        success_count = 0
        success_accounts = []
        failed_accounts = []
        for i, account in enumerate(apple_accounts):
            success = run_apple_for_single_account(
                account, i, len(apple_accounts), base_dir, args
            )
            if success:
                success_count += 1
                success_accounts.append(account["email"])
            else:
                failed_accounts.append(account["email"])

            if i < len(apple_accounts) - 1:
                print(f"\n等待 3 秒后处理下一个账号...")
                time.sleep(3)

        print(f"\n{'='*60}")
        print(f"Apple 多账号处理完成！")
        print(f"  成功: {success_count}/{len(apple_accounts)} 个账号")
        print(f"  成功账号: {', '.join(success_accounts) if success_accounts else '无'}")
        print(f"  失败账号: {', '.join(failed_accounts) if failed_accounts else '无'}")
        print(f"{'='*60}")

        elapsed_time = time.time() - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        print(f"\n{'='*60}")
        print(f"程序运行完成！")
        if hours > 0:
            print(f"总耗时: {hours}小时 {minutes}分钟 {seconds}秒")
        elif minutes > 0:
            print(f"总耗时: {minutes}分钟 {seconds}秒")
        else:
            print(f"总耗时: {seconds}秒")
        print(f"日志已保存: {log_file}")
        finalize_run_log(log_file)
        print(f"{'='*60}")
        return

    # ===== Qobuz 预检查（如果启用） =====
    if qobuz_enabled:
        if not SELENIUM_AVAILABLE:
            print("✗ 错误：未安装 selenium，请运行: pip install selenium")
            return
        
        print("="*60)
        print("Qobuz 播放列表自动添加工具")
        print(f"日志文件: {log_file}")
        print("="*60)
        print()

    # ===== Tidal 删除模式：删除指定专辑的歌曲 =====
    if args.tidal_delete:
        print("="*60)
        print("Tidal 删除模式（多账号自动化）")
        print("="*60)
        
        # 检查账号
        tidal_accounts = load_tidal_accounts()
        if not tidal_accounts:
            print(f"\n✗ 未找到 Tidal 账号数据！")
            print(f"  请在 {TIDAL_EMAIL_FILE} 文件中添加账号信息")
            return
        
        # 检查删除列表
        delete_list = load_tidal_delete_list()
        if not delete_list:
            print(f"\n✗ 未找到删除列表！")
            print(f"  请在 {TIDAL_DELETE_FILE} 文件中添加要删除的艺人和专辑，格式如下：")
            print(f"  艺人名")
            print(f"  专辑名")
            print(f"  （空行分隔不同条目）")
            return
        
        print(f"\n✓ 找到 {len(tidal_accounts)} 个 Tidal 账号")
        print(f"✓ 找到 {len(delete_list)} 条删除记录")
        
        print(f"\n{'='*60}")
        print(f"开始 Tidal 多账号删除处理（共 {len(tidal_accounts)} 个账号）")
        print(f"{'='*60}")
        
        success_count = 0
        success_accounts = []
        failed_accounts = []
        for i, account in enumerate(tidal_accounts):
            success = run_tidal_delete_for_single_account(
                account, i, len(tidal_accounts), delete_list, args.tidal_login_mode
            )
            if success:
                success_count += 1
                success_accounts.append(account["email"])
            else:
                failed_accounts.append(account["email"])
            
            # 账号之间等待一下
            if i < len(tidal_accounts) - 1:
                print(f"\n等待 3 秒后处理下一个账号...")
                time.sleep(3)
        
        print(f"\n{'='*60}")
        print(f"Tidal 多账号删除处理完成！")
        print(f"  成功: {success_count}/{len(tidal_accounts)} 个账号")
        print(f"  成功账号: {', '.join(success_accounts) if success_accounts else '无'}")
        print(f"  失败账号: {', '.join(failed_accounts) if failed_accounts else '无'}")
        print(f"{'='*60}")
        
        # ===== 输出程序总耗时 =====
        elapsed_time = time.time() - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        
        print(f"\n{'='*60}")
        print(f"程序运行完成！")
        if hours > 0:
            print(f"总耗时: {hours}小时 {minutes}分钟 {seconds}秒")
        elif minutes > 0:
            print(f"总耗时: {minutes}分钟 {seconds}秒")
        else:
            print(f"总耗时: {seconds}秒")
        print(f"{'='*60}")
        
        return  # 删除模式完成后直接退出

    # ===== Tidal 多账号模式：直接进入多账号处理流程 =====
    if args.tidal and tidal_accounts:
        print(f"\n{'='*60}")
        print(f"开始 Tidal 多账号自动化处理（共 {len(tidal_accounts)} 个账号）")
        print(f"{'='*60}")
        
        success_count = 0
        success_accounts = []
        failed_accounts = []
        for i, account in enumerate(tidal_accounts):
            success = run_tidal_for_single_account(
                account, i, len(tidal_accounts), base_dir, args
            )
            if success:
                success_count += 1
                success_accounts.append(account["email"])
            else:
                failed_accounts.append(account["email"])
            
            # 账号之间等待一下
            if i < len(tidal_accounts) - 1:
                print(f"\n等待 3 秒后处理下一个账号...")
                time.sleep(3)
        
        print(f"\n{'='*60}")
        print(f"Tidal 多账号处理完成！")
        print(f"  成功: {success_count}/{len(tidal_accounts)} 个账号")
        print(f"  成功账号: {', '.join(success_accounts) if success_accounts else '无'}")
        print(f"  失败账号: {', '.join(failed_accounts) if failed_accounts else '无'}")
        print(f"{'='*60}")
        
        # ===== 输出程序总耗时 =====
        elapsed_time = time.time() - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        
        print(f"\n{'='*60}")
        print(f"程序运行完成！")
        if hours > 0:
            print(f"总耗时: {hours}小时 {minutes}分钟 {seconds}秒")
        elif minutes > 0:
            print(f"总耗时: {minutes}分钟 {seconds}秒")
        else:
            print(f"总耗时: {seconds}秒")
        print(f"{'='*60}")
        
        return  # Tidal 多账号模式完成后直接退出

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
    
    # ===== 10. Qobuz 播放列表添加（如果启用） =====
    if qobuz_enabled:
        # 获取播放列表名称（选定即标记已用）
        playlist_name = claim_next_playlist_name()
        if not playlist_name:
            print("✗ 无可用的播放列表名称")
            return
        
        print(f"\n{'='*60}")
        print("开始添加歌曲到 Qobuz 播放列表...")
        print(f"{'='*60}")
        
        process_qobuz_playlist(
            output_path,
            playlist_name,
            QOBUZ_TRACK_COUNT_MIN,
            QOBUZ_TRACK_COUNT_MAX
        )
    
    # ===== 输出程序总耗时 =====
    elapsed_time = time.time() - start_time
    hours = int(elapsed_time // 3600)
    minutes = int((elapsed_time % 3600) // 60)
    seconds = int(elapsed_time % 60)
    
    print(f"\n{'='*60}")
    print(f"程序运行完成！")
    if hours > 0:
        print(f"总耗时: {hours}小时 {minutes}分钟 {seconds}秒")
    elif minutes > 0:
        print(f"总耗时: {minutes}分钟 {seconds}秒")
    else:
        print(f"总耗时: {seconds}秒")
    print(f"日志已保存: {log_file}")
    finalize_run_log(log_file)
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
