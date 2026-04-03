"""
项目全局配置文件
包含所有常量、文件路径、参数设置
"""

from pathlib import Path

# ==================== 版本信息 ====================
APP_VERSION = "0.1.19"
APP_NAME = "Playlist Multi-Platform Manager"
UPDATE_NOTES = "日志命名规范化，统一写入 logs 子目录"

# ==================== 项目路径 ====================
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT  # 数据目录（当前为新目录自身）

# ==================== 日志配置 ====================
LOG_DIR = DATA_DIR / "logs"
LOG_FILE_BASENAME = "playlist_run"

# ==================== 文件配置 ====================
TIDAL_CREDENTIALS_FILE = DATA_DIR / ".tidal_credentials.json"
TIDAL_EMAIL_FILE = DATA_DIR / "tidal_email.txt"
TIDAL_DELETE_FILE = DATA_DIR / "tidal_delete_songs.txt"
PLAYLIST_NAMES_FILE = DATA_DIR / "Playlist_name.txt"
PLAYLIST_HISTORY_FILE = DATA_DIR / ".playlist_history.json"
HISTORY_FILE = DATA_DIR / ".album_history.json"
HISTORY_TX_LOG_FILE = DATA_DIR / ".history_tx.log"

# 平台数据文件
APPLE_ARTISTS_FILE = DATA_DIR / "apple_artists.json"
TIDAL_ARTISTS_FILE = DATA_DIR / "tidal_artists.json"
QOBUZ_ARTISTS_FILE = DATA_DIR / "qobuz_artists.json"
OTHER_ARTISTS_FILE = DATA_DIR / "other_artists.json"

# ==================== 浏览器配置 ====================
CHROME_PATH = r"C:\Users\Lenovo\AppData\Local\Google\Chrome\Application\chrome.exe"
BROWSER_KEEP_ALIVE_INTERVAL = 30  # 浏览器保活间隔（秒）

# Windows API 常量
SW_RESTORE = 9
SW_SHOW = 5

# ==================== 默认参数 ====================
DEFAULT_PLATFORM = "T"  # 默认选择：A (Apple), T (Tidal), Q (Qobuz)
DEFAULT_ALBUM_COUNT = 17  # 中间部分从主库抽取的专辑数量

# ==================== 专辑选择算法参数 ====================
MAX_RECENT_COMBINATIONS = 50  # 记录最近生成的组合数量，用于避免重复
MIN_COMBINATION_DIFF = 0.85  # 最小组合差异度（0-1），低于此值会重新生成
RECENT_APPEARANCE_WINDOW = 10  # 检查最近N次生成中每个专辑的出现频率
MAX_RECENT_FREQUENCY = 0.3  # 如果专辑在最近N次中出现超过此比例，几乎完全排除
COOLDOWN_WINDOW = 8  # 冷却期：如果专辑在最近N次中出现，暂时大幅降低权重
WEIGHT_DECAY_POWER = 4  # 权重衰减的幂次

# ==================== Tidal 配置 ====================
TIDAL_MODE = 1  # Tidal 模式：1=新增播放列表，2=删除指定艺人专辑歌曲
TIDAL_TRACK_COUNT_MIN = 10  # 每张专辑添加的最小歌曲数量
TIDAL_TRACK_COUNT_MAX = 13  # 每张专辑添加的最大歌曲数量
TIDAL_DELAY_MIN = 0.5  # 操作间隔最小延迟（秒）
TIDAL_DELAY_MAX = 1.0  # 操作间隔最大延迟（秒）

# ==================== Apple Music 配置 ====================
APPLE_TRACK_COUNT_MIN = 10  # 每张专辑添加的最小歌曲数量
APPLE_TRACK_COUNT_MAX = 14  # 每张专辑添加的最大歌曲数量
APPLE_DELAY_MIN = 0.3  # 操作间隔最小延迟（秒）
APPLE_DELAY_MAX = 0.8  # 操作间隔最大延迟（秒）

# ==================== Qobuz 配置 ====================
QOBUZ_TRACK_COUNT_MIN = 10  # 每张专辑添加的最小歌曲数量
QOBUZ_TRACK_COUNT_MAX = 14  # 每张专辑添加的最大歌曲数量
QOBUZ_DELAY_MIN = 0.3  # 操作间隔最小延迟（秒）
QOBUZ_DELAY_MAX = 0.8  # 操作间隔最大延迟（秒）
QOBUZ_LOGIN_URL = "https://play.qobuz.com/login"  # Qobuz登录页

# Qobuz多语言支持
QOBUZ_CREATE_BUTTON_TEXTS = ['Create', 'Créer', 'Erstellen', 'Anlegen']
QOBUZ_ADD_TO_PLAYLIST_TEXTS = [
    'Add to playlists', 'Ajouter aux playlists', 'Zu Playlists hinzufügen',
    'Den Playlists hinzufügen', 'Add to playlist'
]
QOBUZ_ADD_BUTTON_TEXTS = ['Add', 'Ajouter', 'Hinzufügen']

# ==================== 平台文件映射 ====================
PLATFORM_FILES = {
    "A": APPLE_ARTISTS_FILE,
    "T": TIDAL_ARTISTS_FILE,
    "Q": QOBUZ_ARTISTS_FILE
}
