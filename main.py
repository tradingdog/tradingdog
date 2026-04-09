import argparse
import json
import secrets
import time
import re
import random
import logging
import sys
import threading
import ctypes
from datetime import datetime
from pathlib import Path

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

# ===== 日志配置 =====
def setup_logging():
    """配置日志，输出到文件"""
    log_filename = f"qobuz_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    # 创建日志格式
    log_format = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')
    
    # 创建文件处理器（只输出到文件，不输出到控制台）
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(log_format)
    file_handler.setLevel(logging.INFO)
    
    # 获取 root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    # 第三方库请求异常会重复输出原始HTTP错误，这里做降噪。
    tidal_request_logger = logging.getLogger("tidalapi.request")
    tidal_request_logger.setLevel(logging.CRITICAL)
    tidal_request_logger.propagate = False
    
    return log_filename

# 自定义 print 函数，同时输出到控制台和日志文件
_original_print = print
def print(*args, **kwargs):
    message = ' '.join(str(arg) for arg in args)
    logging.info(message)  # 写入日志文件
    _original_print(*args, **kwargs)  # 输出到控制台

try:
    import tidalapi
    TIDAL_AVAILABLE = True
except ImportError:
    TIDAL_AVAILABLE = False

# Selenium 导入（Apple Music 需要）
try:
    from selenium import webdriver
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
APP_VERSION = "0.1.19"
# 更新内容：简化 Apple 登录逻辑，禁用浏览器保活功能（用户反馈不影响手工登录流程】
DEFAULT_ALBUM_COUNT = 17         # 中间部分从主库抽取的专辑数量
HISTORY_FILE = ".album_history.json"
MAX_RECENT_COMBINATIONS = 50     # 记录最近生成的组合数量，用于避免重复
MIN_COMBINATION_DIFF = 0.85      # 最小组合差异度（0-1），低于此值会重新生成
RECENT_APPEARANCE_WINDOW = 10    # 检查最近N次生成中每个专辑的出现频率
MAX_RECENT_FREQUENCY = 0.3       # 如果专辑在最近N次中出现超过此比例，几乎完全排除
COOLDOWN_WINDOW = 8              # 冷却期：如果专辑在最近N次中出现，暂时大幅降低权重
WEIGHT_DECAY_POWER = 4           # 权重衰减的幂次

# Tidal 集成配置
TIDAL_MODE = 1                   # Tidal 模式：1=新增播放列表，2=删除指定艺人专辑歌曲
TIDAL_TRACK_COUNT_MIN = 10       # 每张专辑添加的最小歌曲数量
TIDAL_TRACK_COUNT_MAX = 13       # 每张专辑添加的最大歌曲数量
TIDAL_DELAY_MIN = 0.5            # 操作间隔最小延迟（秒）
TIDAL_DELAY_MAX = 1            # 操作间隔最大延迟（秒）
TIDAL_CREDENTIALS_FILE = ".tidal_credentials.json"  # Tidal 登录凭据保存文件
TIDAL_EMAIL_FILE = "tidal_email.txt"                # Tidal 账号邮箱密码文件
TIDAL_DELETE_FILE = "tidal_delete_songs.txt"        # Tidal 删除歌曲列表文件
PLAYLIST_NAMES_FILE = "Playlist_name.txt"           # 播放列表名称文件
PLAYLIST_HISTORY_FILE = ".playlist_history.json"    # 已使用的播放列表名称历史

# Apple Music 集成配置
APPLE_TRACK_COUNT_MIN = 10       # 每张专辑添加的最小歌曲数量
APPLE_TRACK_COUNT_MAX = 14       # 每张专辑添加的最大歌曲数量
APPLE_DELAY_MIN = 0.3           # 操作间隔最小延迟（秒）
APPLE_DELAY_MAX = 0.8            # 操作间隔最大延迟（秒）
APPLE_LOGIN_CONFIRM_TIMEOUT = 1800  # Apple Music 手动登录确认最长等待时间（秒）

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

# 平台与文件映射
PLATFORM_FILES = {
    "A": "apple_artists.json",
    "T": "tidal_artists.json",
    "Q": "qobuz_artists.json"
}
OTHER_ARTISTS_FILE = "other_artists.json"

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


def init_tidal_browser():
    """初始化用于 Tidal OAuth 自动化的 Chrome 浏览器（无痕模式）"""
    if not SELENIUM_AVAILABLE:
        print("✗ 错误：未安装 selenium，请运行: pip install selenium")
        return None
    
    try:
        print("  启动 Chrome 浏览器（用于 Tidal 登录）...")
        options = webdriver.ChromeOptions()
        options.add_argument("--incognito")
        
        # 显式指定 Chrome 可执行文件路径
        chrome_path = r"C:\Users\Lenovo\AppData\Local\Google\Chrome\Application\chrome.exe"
        options.binary_location = chrome_path
        
        # 反检测设置
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        
        # 禁用后台节流
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-hang-monitor")
        
        driver = webdriver.Chrome(options=options)
        
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
        return driver
        
    except Exception as e:
        print(f"✗ 浏览器初始化失败: {e}")
        return None


def auto_complete_tidal_oauth(driver, auth_url: str, email: str, password: str) -> bool:
    """
    使用 Selenium 自动完成 Tidal OAuth 登录流程
    
    流程：
    1. 访问 OAuth 链接
    2. 等待 5 秒
    3. 输入邮箱，点击 Continue
    4. 等待 2 秒
    5. 输入密码，点击 Log In
    6. 等待 5 秒
    7. 点击 Continue（Link your device 页面）
    """
    try:
        print(f"  正在自动完成 OAuth 登录: {email}")
        
        # 1. 访问 OAuth 链接
        driver.get(auth_url)
        time.sleep(5)
        
        # 2. 输入邮箱
        try:
            email_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input#email, input[name='email'], input[type='email']"))
            )
            email_input.clear()
            # 模拟人类输入
            for char in email:
                email_input.send_keys(char)
                time.sleep(random.uniform(0.02, 0.08))
            print(f"    ✓ 已输入邮箱")
        except Exception as e:
            print(f"    ✗ 输入邮箱失败: {e}")
            return False
        
        time.sleep(1)
        
        # 3. 点击 Continue 按钮（邮箱页面）
        try:
            continue_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit'], button[ui-test-id='check-user-continue-button']"))
            )
            continue_btn.click()
            print(f"    ✓ 已点击 Continue")
        except Exception as e:
            print(f"    ✗ 点击 Continue 失败: {e}")
            return False
        
        time.sleep(2)
        
        # 4. 输入密码
        try:
            # 等待密码输入框可交互
            password_input = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input#password"))
            )
            # 先点击输入框确保获得焦点
            password_input.click()
            time.sleep(0.5)
            password_input.clear()
            time.sleep(0.3)
            # 模拟人类输入
            for char in password:
                password_input.send_keys(char)
                time.sleep(random.uniform(0.02, 0.08))
            print(f"    ✓ 已输入密码")
        except Exception as e:
            print(f"    ✗ 输入密码失败: {e}")
            return False
        
        time.sleep(2)
        
        # 5. 点击 Log In 按钮
        try:
            login_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[ui-test-id='login-user-login-button'], button[type='submit']"))
            )
            login_btn.click()
            print(f"    ✓ 已点击 Log In")
        except Exception as e:
            print(f"    ✗ 点击 Log In 失败: {e}")
            return False
        
        time.sleep(5)
        
        # 6. 点击 Continue（Link your device 页面）
        try:
            # 等待页面变化，可能需要点击 "Continue" 来完成设备链接
            link_continue_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.btn-primary, button[type='button']"))
            )
            # 确认是 Continue 按钮
            btn_text = link_continue_btn.text.strip().lower()
            if "continue" in btn_text or btn_text == "":
                link_continue_btn.click()
                print(f"    ✓ 已点击 Continue（完成设备链接）")
            else:
                # 尝试其他选择器
                buttons = driver.find_elements(By.CSS_SELECTOR, "button")
                for btn in buttons:
                    if "continue" in btn.text.lower():
                        btn.click()
                        print(f"    ✓ 已点击 Continue（完成设备链接）")
                        break
        except Exception as e:
            print(f"    ⚠ 设备链接页面处理: {e}")
            # 可能已经自动完成，不一定失败
        
        time.sleep(3)
        print(f"  ✓ OAuth 登录流程完成")
        return True
        
    except Exception as e:
        print(f"  ✗ OAuth 自动登录失败: {e}")
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

def login_tidal():
    """登录 Tidal，返回 session 对象（每次强制重新登录）"""
    if not TIDAL_AVAILABLE:
        print("✗ 错误：未安装 tidalapi，请运行: pip install tidalapi")
        return None
    
    session = tidalapi.Session()
    
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


def login_tidal_with_automation(email: str, password: str):
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
    driver = None
    
    try:
        # 删除旧的凭据文件（强制重新登录）
        cred_path = Path(TIDAL_CREDENTIALS_FILE)
        if cred_path.exists():
            cred_path.unlink()
        
        # 启动 OAuth 流程
        print(f"\n开始 Tidal OAuth 验证: {email}")
        login_info, future = session.login_oauth()
        auth_url = login_info.verification_uri_complete
        # 确保 URL 有协议前缀
        if auth_url and not auth_url.startswith("http"):
            auth_url = "https://" + auth_url
        print(f"  OAuth 链接: {auth_url}")
        
        # 初始化浏览器
        driver = init_tidal_browser()
        if not driver:
            print("✗ 无法启动浏览器")
            return None, None
        
        # 使用浏览器自动完成 OAuth 登录
        success = auto_complete_tidal_oauth(driver, auth_url, email, password)
        
        if not success:
            print("✗ 自动 OAuth 登录失败")
            if driver:
                driver.quit()
            return None, None
        
        # 等待 OAuth 流程完成
        print("  等待 OAuth 验证完成...")
        try:
            future.result(timeout=30)  # 最多等待 30 秒
        except Exception as e:
            print(f"  ⚠ OAuth 等待超时: {e}")
        
        # 检查登录状态
        if session.check_login():
            print(f"✓ Tidal 登录成功！用户: {session.user.first_name} {session.user.last_name}")
            save_tidal_credentials(session)
            return session, driver
        else:
            print("✗ Tidal 登录验证失败")
            if driver:
                driver.quit()
            return None, None
            
    except Exception as e:
        print(f"✗ Tidal 自动登录过程出错: {e}")
        if driver:
            driver.quit()
        return None, None


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
    
    # 获取播放列表名称
    playlist_name = get_next_playlist_name()
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
    
    # 标记播放列表名称为已使用
    mark_playlist_name_used(playlist_name)
    
    # 为每张专辑生成一个随机的歌曲数量（在范围内不重复）
    track_counts = list(range(track_count_min, track_count_max + 1))
    random.shuffle(track_counts)
    
    # 计算预期添加的总歌曲数
    expected_total = sum(track_counts[i % len(track_counts)] for i in range(len(albums)))
    
    # 记录已处理的专辑（用于排除重复）
    processed_albums = set()  # 格式: "艺人名 - 专辑名"
    
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
        
        album = search_album_on_tidal(session, artist_name, album_name)
        
        if album:
            album_display = album.name if hasattr(album, 'name') else str(album)
            artist_display = album.artist.name if hasattr(album, 'artist') and album.artist else 'Unknown'
            print(f"  ✓ 找到: {album_display} - {artist_display}")
            
            random_delay()  # 获取歌曲前延迟
            tracks = album.tracks()
            actual_track_count = min(track_count, len(tracks))
            print(f"  专辑共 {len(tracks)} 首歌，计划添加 {actual_track_count} 首")
            
            added = add_tracks_to_playlist_with_delay(session, playlist, tracks, actual_track_count)
            total_added += added
            print(f"  ✓ 已添加 {added} 首歌曲")
        else:
            print(f"  ✗ 未找到专辑")
        
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
    
    # 1. 使用自动化浏览器登录
    session, driver = login_tidal_with_automation(email, password)
    
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
        # 4. 关闭浏览器
        if driver:
            print("  关闭浏览器...")
            try:
                driver.quit()
            except:
                pass


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


def run_tidal_delete_for_single_account(account_info: dict, account_index: int, total_accounts: int, delete_list: list[dict]):
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
    
    # 1. 使用自动化浏览器登录
    session, driver = login_tidal_with_automation(email, password)
    
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
        # 3. 关闭浏览器
        if driver:
            print("  关闭浏览器...")
            try:
                driver.quit()
            except:
                pass


# ==================== Apple Music 集成功能 ====================

def apple_human_delay(min_sec=0.3, max_sec=0.8):
    """模拟人类操作的随机延迟"""
    time.sleep(random.uniform(min_sec, max_sec))


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


def init_apple_browser():
    """初始化 Chrome 浏览器（无痕模式）"""
    if not SELENIUM_AVAILABLE:
        print("✗ 错误：未安装 selenium，请运行: pip install selenium")
        return None
    
    try:
        print("  配置 Chrome 选项...")
        options = webdriver.ChromeOptions()
        options.add_argument("--incognito")
        
        # 反检测设置
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        
        # ===== 关键：禁用后台节流，确保窗口在后台时仍能正常渲染和交互 =====
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-hang-monitor")
        
        print("  启动 Chrome 浏览器...")
        driver = webdriver.Chrome(options=options)
        
        print("  设置反检测属性...")
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
        # 浏览器保活已禁用（用户反馈：妨碍手工登录工作）
        # start_browser_keep_alive(driver, interval=30)  # 已禁用
        
        print("  ✓ 浏览器初始化成功")
        return driver
        
    except Exception as e:
        print(f"✗ 浏览器初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def login_apple_music(driver):
    """登录 Apple Music - 需要人工确认"""
    print("正在访问 Apple Music...")
    driver.get("https://music.apple.com")
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

        if user_input == 'y':
            print("✓ 登录成功")
            return True
        elif user_input == 'n':
            print("✗ 登录失败")
            return False
        else:
            print("请输入 y 或 n")
            continue


def search_album_on_apple(driver, artist_name, album_name):
    """在 Apple Music 上搜索专辑，返回专辑URL"""
    print(f"搜索专辑: {album_name} (艺人: {artist_name})")
    
    try:
        # 点击搜索框
        search_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input.search-input__text-field"))
        )
        apple_move_to_element(driver, search_input)
        apple_human_delay(0.3, 0.5)
        search_input.click()
        apple_human_delay(0.3, 0.5)
        
        # 清空并输入专辑名
        search_input.clear()
        apple_human_typing(search_input, album_name)
        apple_human_delay(0.3, 0.5)
        search_input.send_keys(Keys.RETURN)
        
        apple_human_delay(1, 2)
        
        # 等待搜索结果加载
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".top-search-lockup, .shelf-grid, [data-testid='search-results']"))
            )
        except:
            print("  等待搜索结果加载...")
            apple_human_delay(1, 2)
        
        # 查找专辑链接
        album_section_selectors = [
            "//h2[contains(text(), '專輯') or contains(text(), 'Albums') or contains(text(), '专辑')]/following::div[contains(@class, 'shelf-grid')][1]//a[contains(@href, '/album/')]",
            "//h3[contains(text(), '專輯') or contains(text(), 'Albums')]/following::div[contains(@class, 'top-search-lockup')][1]//a[contains(@href, '/album/')]",
            "//section[.//*[contains(text(), '專輯') or contains(text(), 'Albums')]]//a[contains(@href, '/album/')]",
        ]
        
        album_link = None
        
        # 先尝试在专辑区域内查找匹配艺人的专辑
        for selector in album_section_selectors:
            try:
                album_links = driver.find_elements(By.XPATH, selector)
                for link in album_links:
                    if not link.is_displayed():
                        continue
                    parent_text = link.find_element(By.XPATH, "ancestor::div[contains(@class, 'lockup')]").text if link.find_elements(By.XPATH, "ancestor::div[contains(@class, 'lockup')]") else ""
                    link_text = link.text or ""
                    
                    if artist_name.lower() in parent_text.lower() or artist_name.lower() in link_text.lower():
                        album_link = link
                        print(f"  找到匹配艺人的专辑链接")
                        break
                if album_link:
                    break
            except:
                continue
        
        # 如果没找到匹配的，尝试直接找包含专辑名和艺人名的链接
        if not album_link:
            try:
                all_album_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']")
                for link in all_album_links:
                    if not link.is_displayed():
                        continue
                    href = link.get_attribute("href") or ""
                    if "/library/" in href:
                        continue
                    try:
                        lockup = link.find_element(By.XPATH, "ancestor::div[contains(@class, 'lockup') or contains(@class, 'top-search-lockup')]")
                        lockup_text = lockup.text.lower()
                        if artist_name.lower() in lockup_text and album_name.lower() in lockup_text:
                            album_link = link
                            print(f"  找到匹配专辑和艺人的链接")
                            break
                    except:
                        continue
            except:
                pass
        
        # 如果还是没找到，点击第一个专辑链接
        if not album_link:
            try:
                all_album_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']")
                for link in all_album_links:
                    if link.is_displayed():
                        href = link.get_attribute("href") or ""
                        if "/album/" in href and "/library/" not in href and "/artist/" not in href:
                            album_link = link
                            print(f"  使用第一个专辑链接: {href}")
                            break
            except:
                pass
        
        if album_link:
            href = album_link.get_attribute("href") or ""
            print(f"  点击专辑链接: {href}")
            
            apple_move_to_element(driver, album_link)
            apple_human_delay(0.3, 0.5)
            album_link.click()
            
            apple_human_delay(2, 4)
            
            # 确认机制：等待页面完全加载
            max_retries = 5
            for retry in range(max_retries):
                current_url = driver.current_url
                if "/album/" in current_url:
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']"))
                        )
                        print(f"  ✓ 已成功进入专辑页面: {current_url}")
                        return current_url
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
                        print(f"  ✗ 进入的不是专辑页面: {current_url}")
                        return None
            
            print(f"  ✗ 页面加载超时")
            return None
        else:
            print(f"  ✗ 未找到专辑链接")
            return None
            
    except Exception as e:
        print(f"  ✗ 搜索失败: {e}")
        return None


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
                                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '新播放清單') or contains(text(), '新建播放列表') or contains(text(), 'New Playlist') or contains(text(), 'Neue Playlist'))]"))
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
                                    EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '加入播放清單') or contains(text(), '添加到播放列表') or contains(text(), 'Add to Playlist') or contains(text(), 'Zur Playlist'))]"))
                                )
                                apple_move_to_element(driver, add_to_playlist)
                                apple_human_delay(0.3, 0.6)
                                add_to_playlist.click()
                                
                                apple_human_delay(1, 2)
                                
                                new_playlist = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '新播放清單') or contains(text(), '新建播放列表') or contains(text(), 'New Playlist') or contains(text(), 'Neue Playlist'))]"))
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
                                EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and (contains(text(), '加入播放清單') or contains(text(), '添加到播放列表') or contains(text(), 'Add to Playlist') or contains(text(), 'Zur Playlist'))]"))
                            )
                            apple_move_to_element(driver, add_to_playlist)
                            apple_human_delay(0.3, 0.6)
                            add_to_playlist.click()
                            apple_human_delay(1, 2)
                        except:
                            print("    ! 未找到 Add to Playlist 选项")
                            continue
                        
                        # 选择目标播放列表 - 不刷新页面，简单重试
                        playlist_found = False
                        max_retry_attempts = 3
                        
                        for retry_attempt in range(max_retry_attempts):
                            try:
                                playlist_option = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, f"//span[contains(@class, 'contextual-menu-item__option-text') and contains(text(), '{playlist_name}')]"))
                                )
                                apple_move_to_element(driver, playlist_option)
                                apple_human_delay(0.3, 0.6)
                                playlist_option.click()
                                print(f"    ✓ 已添加第 {idx+1} 首")
                                playlist_found = True
                                break
                            except:
                                if retry_attempt < max_retry_attempts - 1:
                                    # 关闭菜单，等待几秒后重试
                                    try:
                                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                        apple_human_delay(0.3, 0.5)
                                    except:
                                        pass
                                    print(f"    播放列表未找到，等待重试... (尝试 {retry_attempt+1}/{max_retry_attempts})")
                                    apple_human_delay(2, 3)
                                else:
                                    print(f"    ! 播放列表未找到，跳过歌曲 {idx+1}")
                        
                        if not playlist_found:
                            # 关闭菜单后继续下一首
                            try:
                                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                            except:
                                pass
                            continue
                    
                    added_count += 1
                    song_added = True
                    apple_human_delay(2, 4)
                    
                except Exception as e:
                    error_msg = str(e)
                    if "intercepted" in error_msg.lower():
                        apple_human_delay(2, 3)
                        print(f"    ? 歌曲 {idx+1} 点击被拦截，可能已添加成功（计入统计）")
                        added_count += 1
                        song_added = True
                    elif attempt == max_attempts - 1:
                        print(f"    ! 歌曲 {idx+1} 添加失败: {error_msg[:50]}")
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    except:
                        pass
                    apple_human_delay(1, 2)
        
        print(f"  ✓ 已添加 {added_count} 首歌曲")
        return added_count
        
    except Exception as e:
        print(f"  ✗ 添加歌曲失败: {e}")
        return 0


def process_apple_music_playlist(txt_path: Path, playlist_name: str, track_count_min: int, track_count_max: int, base_dir: Path = None):
    """处理 Apple Music 播放列表添加流程 - 支持失败重试和自动补充"""
    # 解析专辑列表
    albums = parse_album_list_from_txt(txt_path)
    if not albums:
        print("✗ 未从 txt 文件中解析到专辑信息")
        return False
    
    print(f"\n解析到 {len(albums)} 张专辑待添加")
    print(f"将使用播放列表名称: {playlist_name}")
    
    # 初始化浏览器
    print("\n初始化浏览器...")
    driver = init_apple_browser()
    if not driver:
        return False
    
    # 记录已使用的播放列表名称（用于抽风时创建新列表）
    used_playlist_names = [playlist_name]
    current_playlist_name = playlist_name
    
    # 记录失败的专辑（用于重试）
    failed_albums = []  # [(artist_name, album_name, track_count), ...]
    # 记录已处理的专辑（用于补充时排除）
    processed_albums = set()
    
    try:
        # 登录
        if not login_apple_music(driver):
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
            album_url = search_album_on_apple(driver, artist_name, album_name)
            if album_url:
                # 添加歌曲
                is_first = not playlist_created
                added = add_songs_to_apple_playlist(driver, current_playlist_name, track_count, is_first_album=is_first)
                
                # 如果返回-1，表示创建了播放列表并跳转了页面
                if added == -1:
                    playlist_created = True
                    # 重要！不要用URL导航，必须通过搜索来访问专辑，否则播放列表会消失
                    print(f"  通过搜索重新访问专辑（避免播放列表消失）...")
                    album_url_new = search_album_on_apple(driver, artist_name, album_name)
                    if album_url_new:
                        remaining_count = track_count - 1
                        if remaining_count > 0:
                            added = add_songs_to_apple_playlist(driver, current_playlist_name, remaining_count, is_first_album=False)
                            if added > 0:
                                total_added += added
                        total_added += 1
                    else:
                        print(f"  ! 重新搜索专辑失败，跳过剩余歌曲")
                        total_added += 1  # 第一首已添加
                
                # 如果返回-2，表示播放列表同步失败，需要重建
                elif added == -2:
                    print("\n  ⚠ 播放列表同步失败，尝试使用新名称重建...")
                    # 点击首页
                    click_apple_home(driver)
                    apple_human_delay(8, 10)
                    
                    # 获取下一个可用的播放列表名称
                    all_names = load_available_playlist_names()
                    used_names = load_playlist_history()
                    for name in all_names:
                        if name not in used_names and name not in used_playlist_names:
                            current_playlist_name = name
                            used_playlist_names.append(name)
                            print(f"  使用新播放列表名称: {current_playlist_name}")
                            break
                    
                    playlist_created = False  # 需要重新创建
                    continue  # 重新处理当前专辑
                
                else:
                    if added > 0:
                        playlist_created = True
                        total_added += added
                    elif added == 0:
                        # 记录失败的专辑（用于后续重试）
                        failed_albums.append((artist_name, album_name, track_count))
                        print(f"  ! 添加失败，已记录待重试")
            else:
                # 未找到专辑，也记录为失败
                failed_albums.append((artist_name, album_name, track_count))
            
            i += 1  # 移动到下一张专辑
            apple_human_delay(1, 2)
        
        # ===== 失败专辑重试逻辑（最多1次） =====
        if failed_albums:
            print(f"\n{'='*60}")
            print(f"⚠ 有 {len(failed_albums)} 张专辑添加失败，尝试重试...")
            print(f"{'='*60}")
            
            retry_failed = []
            for artist_name, album_name, track_count in failed_albums:
                print(f"\n[重试] {artist_name} - {album_name}")
                
                # 点击首页重置状态
                click_apple_home(driver)
                apple_human_delay(1, 2)
                
                album_url = search_album_on_apple(driver, artist_name, album_name)
                if album_url:
                    added = add_songs_to_apple_playlist(driver, current_playlist_name, track_count, is_first_album=False)
                    if added > 0:
                        total_added += added
                        print(f"  ✓ 重试成功，添加了 {added} 首")
                    else:
                        retry_failed.append((artist_name, album_name, track_count))
                        print(f"  ✗ 重试仍然失败")
                else:
                    retry_failed.append((artist_name, album_name, track_count))
                    print(f"  ✗ 重试仍然找不到专辑")
                
                apple_human_delay(1, 2)
            
            failed_albums = retry_failed
        
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
                        
                        # 点击首页重置状态
                        click_apple_home(driver)
                        apple_human_delay(1, 2)
                        
                        album_url = search_album_on_apple(driver, artist_name, album_name)
                        
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
        if failed_albums:
            print(f"  失败专辑: {len(failed_albums)} 张")
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
            print("\n浏览器保持打开状态...")
            input("按 Enter 关闭浏览器...")
            stop_browser_keep_alive()
            driver.quit()

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
        print("  配置 Chrome 选项...")
        options = webdriver.ChromeOptions()
        options.add_argument("--incognito")
        
        # 反检测设置
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        
        # ===== 关键：禁用后台节流，确保窗口在后台时仍能正常渲染和交互 =====
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-hang-monitor")
        
        print("  启动 Chrome 浏览器...")
        driver = webdriver.Chrome(options=options)
        
        print("  设置反检测属性...")
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
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
    
    print("\n请在浏览器中完成登录，登录成功后输入 y 继续...")
    user_input = input("是否已登录成功？(y/n): ").strip().lower()
    
    if user_input == 'y':
        print("✓ 登录成功")
        return True
    else:
        print("✗ 登录失败")
        return False


def search_album_on_qobuz(driver, artist_name, album_name):
    """在 Qobuz 上搜索专辑，返回专辑URL"""
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
                    return current_url
                except:
                    print(f"  等待歌曲列表加载...")
                    qobuz_human_delay(0.5, 1)
                    return current_url
            else:
                print(f"  ✗ 进入的不是专辑页面: {current_url}")
                return None
        else:
            print(f"  ✗ 未找到专辑链接")
            return None
            
    except Exception as e:
        print(f"  ✗ 搜索失败: {e}")
        import traceback
        traceback.print_exc()
        return None


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
        
        # 处理每张专辑
        total_added = 0
        for i, album_info in enumerate(albums):
            artist_name = album_info["artist_name"]
            album_name = album_info["album_name"]
            track_count = track_counts[i % len(track_counts)]
            
            print(f"\n[{i+1}/{len(albums)}] 处理: {artist_name} - {album_name}")
            
            # 搜索专辑
            album_url = search_album_on_qobuz(driver, artist_name, album_name)
            if album_url:
                # 添加歌曲到已创建的播放列表
                added = add_songs_to_qobuz_playlist(driver, playlist_name, track_count)
                total_added += added
            
            qobuz_human_delay(0.5, 1)
        
        print(f"\n{'='*60}")
        print(f"✓ Qobuz 播放列表添加完成！")
        print(f"  播放列表: {playlist_name}")
        print(f"  总计添加: {total_added} 首歌曲")
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
            input("按 Enter 关闭浏览器...")
            stop_browser_keep_alive()
            driver.quit()

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
    print(f"Playlist 自动化工具 v{APP_VERSION}")
    
    # ===== 初始化日志 =====
    log_file = setup_logging()
    
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
    args = parser.parse_args()

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
    if apple_enabled:
        if not SELENIUM_AVAILABLE:
            print("✗ 错误：未安装 selenium，请运行: pip install selenium")
            return
        
        print("="*60)
        print("Apple Music 播放列表自动添加工具")
        print("="*60)
        print()

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
                account, i, len(tidal_accounts), delete_list
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
    
    # ===== 9. Apple Music 播放列表添加（如果启用） =====
    if apple_enabled:
        # 获取播放列表名称
        playlist_name = get_next_playlist_name()
        if not playlist_name:
            print("✗ 无可用的播放列表名称")
            return
        
        print(f"\n{'='*60}")
        print("开始添加歌曲到 Apple Music 播放列表...")
        print(f"{'='*60}")
        
        success = process_apple_music_playlist(
            output_path,
            playlist_name,
            APPLE_TRACK_COUNT_MIN,
            APPLE_TRACK_COUNT_MAX,
            base_dir
        )
        
        # 标记播放列表名称为已使用
        if success:
            mark_playlist_name_used(playlist_name)
    
    # ===== 10. Qobuz 播放列表添加（如果启用） =====
    if qobuz_enabled:
        # 获取播放列表名称
        playlist_name = get_next_playlist_name()
        if not playlist_name:
            print("✗ 无可用的播放列表名称")
            return
        
        print(f"\n{'='*60}")
        print("开始添加歌曲到 Qobuz 播放列表...")
        print(f"{'='*60}")
        
        success = process_qobuz_playlist(
            output_path,
            playlist_name,
            QOBUZ_TRACK_COUNT_MIN,
            QOBUZ_TRACK_COUNT_MAX
        )
        
        # 标记播放列表名称为已使用
        if success:
            mark_playlist_name_used(playlist_name)
    
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


if __name__ == "__main__":
    main()
