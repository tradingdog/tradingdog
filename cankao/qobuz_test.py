#!/usr/bin/env python3
"""
Qobuz 自动化测试脚本
使用 Selenium 模拟人类操作，创建播放列表并添加歌曲
"""

import time
import random
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ==================== 配置 ====================
CHROME_PROFILE_PATH = str(Path(__file__).parent.parent / "ChromeProfile")

# 测试播放列表和专辑
TEST_PLAYLIST_NAME = ''.join([str(random.randint(0, 9)) for _ in range(10)])  # 随机10位数字
TEST_ALBUMS = [
    {"artist_name": "Olivier Deriviere", "album_name": "A Plague Tale: Requiem"},
    {"artist_name": "Enya", "album_name": "Shepherd Moons"},
    {"artist_name": "Hans Zimmer", "album_name": "Interstellar"},
]

# 每张专辑添加的歌曲数量
TRACK_COUNT_MIN = 10
TRACK_COUNT_MAX = 14

# Qobuz 登录页面
QOBUZ_LOGIN_URL = "https://play.qobuz.com/login"


# ==================== 人类模拟工具 ====================
def qobuz_human_delay(min_sec=1.0, max_sec=2.5):
    """模拟人类操作的随机延迟"""
    time.sleep(random.uniform(min_sec, max_sec))


def qobuz_human_typing(element, text, min_delay=0.08, max_delay=0.25):
    """模拟人类打字速度 - 更慢的随机延迟"""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def qobuz_move_to_element(driver, element):
    """模拟人类鼠标移动到元素"""
    actions = ActionChains(driver)
    actions.move_to_element(element)
    actions.pause(random.uniform(0.2, 0.5))
    actions.perform()


# ==================== 浏览器初始化 ====================
def init_qobuz_browser():
    """初始化 Chrome 浏览器（无痕模式）"""
    try:
        print("  配置 Chrome 选项...")
        options = webdriver.ChromeOptions()
        options.add_argument("--incognito")
        
        # 反检测设置
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        # 其他设置
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        
        print("  启动 Chrome 浏览器...")
        driver = webdriver.Chrome(options=options)
        
        # 修改 navigator.webdriver 属性
        print("  设置反检测属性...")
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """
        })
        
        print("  ✓ 浏览器初始化成功")
        return driver
        
    except Exception as e:
        print(f"✗ 浏览器初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return None


# ==================== 登录功能 ====================
def login_qobuz(driver):
    """登录 Qobuz"""
    print("正在访问 Qobuz 登录页面...")
    
    driver.get(QOBUZ_LOGIN_URL)
    qobuz_human_delay(3, 5)
    
    print("\n请在浏览器中完成登录，登录成功后输入 y 继续...")
    user_input = input("是否已登录成功？(y/n): ").strip().lower()
    
    if user_input == 'y':
        print("✓ 登录成功")
        return True
    else:
        print("✗ 登录失败")
        return False


# ==================== 搜索功能 ====================
def search_album_on_qobuz(driver, artist_name, album_name):
    """搜索专辑
    返回: 专辑URL（成功）或 None（失败）
    """
    print(f"搜索专辑: {album_name} (艺人: {artist_name})")
    
    try:
        # 点击搜索框
        search_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input.SearchBar__input"))
        )
        qobuz_move_to_element(driver, search_input)
        qobuz_human_delay(0.5, 1)
        search_input.click()
        qobuz_human_delay(0.5, 1)
        
        # 清空并输入搜索词（艺人名 + 专辑名）
        search_input.clear()
        search_query = f"{artist_name} {album_name}"
        qobuz_human_typing(search_input, search_query)
        qobuz_human_delay(0.5, 1)
        search_input.send_keys(Keys.RETURN)
        
        qobuz_human_delay(5, 7)  # 等待搜索结果加载
        
        # 等待搜索结果加载
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".album-item, .search-results, [class*='album']"))
            )
        except:
            print("  等待搜索结果加载...")
            qobuz_human_delay(3, 5)
        
        # 查找专辑链接
        album_link = None
        
        # 尝试找到包含专辑名的链接
        try:
            # Qobuz专辑链接格式：/album/xxx
            album_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']")
            for link in album_links:
                if not link.is_displayed():
                    continue
                href = link.get_attribute("href") or ""
                link_text = link.text.lower() if link.text else ""
                
                # 检查链接文本或周围元素是否包含艺人名
                try:
                    parent = link.find_element(By.XPATH, "./..")
                    parent_text = parent.text.lower() if parent.text else ""
                except:
                    parent_text = ""
                
                # 匹配艺人名或专辑名
                if (artist_name.lower() in link_text or artist_name.lower() in parent_text or
                    album_name.lower() in link_text or album_name.lower() in parent_text):
                    album_link = link
                    print(f"  找到匹配专辑链接")
                    break
            
            # 如果没找到精确匹配，使用第一个专辑链接
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
            
            qobuz_move_to_element(driver, album_link)
            qobuz_human_delay(0.5, 1)
            album_link.click()
            
            qobuz_human_delay(5, 8)  # 等待专辑页面加载
            
            # 确认已进入专辑页面
            current_url = driver.current_url
            if "/album/" in current_url:
                # 等待歌曲列表加载
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".track-row, .track, [class*='track']"))
                    )
                    print(f"  ✓ 已成功进入专辑页面: {current_url}")
                    return current_url
                except:
                    print(f"  等待歌曲列表加载...")
                    qobuz_human_delay(3, 5)
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


# ==================== 多语言支持 ====================
# 创建按钮文本（英语、法语、德语）
CREATE_BUTTON_TEXTS = ['Create', 'Créer', 'Erstellen', 'Anlegen']
# 添加到播放列表菜单项文本
ADD_TO_PLAYLIST_TEXTS = ['Add to playlists', 'Ajouter aux playlists', 'Zu Playlists hinzufügen', 'Add to playlist']
# Add 按钮文本
ADD_BUTTON_TEXTS = ['Add', 'Ajouter', 'Hinzufügen']


# ==================== 创建播放列表 ====================
def create_qobuz_playlist(driver, playlist_name):
    """在Qobuz上创建播放列表（先进入播放列表页面创建，支持多语言）"""
    print(f"\n创建播放列表: {playlist_name}")
    
    try:
        # 直接访问播放列表管理页
        driver.get("https://play.qobuz.com/user/library/playlists")
        qobuz_human_delay(3, 5)
        
        # 点击"Create a playlist"按钮 - 使用CSS选择器，不依赖文本
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
        qobuz_human_delay(0.5, 1)
        create_btn.click()
        qobuz_human_delay(1, 2)
        
        # 等待弹窗出现，输入播放列表名称 - 使用多种选择器
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
        qobuz_human_delay(0.5, 1)
        
        # 点击Create按钮 - 支持多语言（Create/Créer/Erstellen）
        create_confirm_btn = None
        
        # 方法1: 通过button[type='submit']找到确认按钮
        try:
            create_confirm_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']:not([disabled])"))
            )
        except:
            pass
        
        # 方法2: 通过多语言文本查找
        if not create_confirm_btn:
            for text in CREATE_BUTTON_TEXTS:
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
        qobuz_human_delay(0.5, 1)
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


# ==================== 添加歌曲到播放列表 ====================
def add_songs_to_qobuz_playlist(driver, playlist_name, track_count):
    """从当前专辑页面添加歌曲到已存在的播放列表"""
    print(f"  添加 {track_count} 首歌曲到播放列表 '{playlist_name}'...")
    
    try:
        # 等待歌曲列表加载
        qobuz_human_delay(2, 3)
        
        # 获取专辑中的所有歌曲行
        track_selectors = [
            "div[role='gridcell']",
            "div.ListItem__titleWithArtist",
            "[class*='ListItem']",
        ]
        
        songs = []
        for selector in track_selectors:
            songs = driver.find_elements(By.CSS_SELECTOR, selector)
            songs = [s for s in songs if s.is_displayed()]
            if len(songs) > 2:
                break
        
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
                        qobuz_human_delay(0.3, 0.5)
                    except:
                        pass
                    
                    # 重新获取歌曲列表
                    for selector in track_selectors:
                        songs = driver.find_elements(By.CSS_SELECTOR, selector)
                        songs = [s for s in songs if s.is_displayed()]
                        if len(songs) > 2:
                            break
                    
                    if idx >= len(songs):
                        break
                    
                    song = songs[idx]
                    
                    # 滚动到歌曲位置
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", song)
                    qobuz_human_delay(0.8, 1.2)
                    
                    # 悬停在歌曲上以显示更多按钮
                    qobuz_move_to_element(driver, song)
                    qobuz_human_delay(0.5, 1)
                    
                    # 找到更多按钮（三个点）
                    more_btn = None
                    more_selectors = [
                        "button[aria-label='More actions']",
                        "button.ListItem__actions",
                        "button.ButtonIconPrimary.icon-more-vertical",
                        "button[class*='icon-more-vertical']",
                        "button[class*='ListItem__actions']",
                    ]
                    
                    for selector in more_selectors:
                        try:
                            more_btn = song.find_element(By.CSS_SELECTOR, selector)
                            if more_btn.is_displayed():
                                break
                            more_btn = None
                        except:
                            continue
                    
                    # 如果在歌曲行内找不到，尝试查找所有更多按钮
                    if not more_btn:
                        try:
                            all_more_btns = driver.find_elements(By.CSS_SELECTOR, "button[aria-label='More actions'], button.ListItem__actions")
                            for btn in all_more_btns:
                                if btn.is_displayed():
                                    more_btn = btn
                                    break
                        except:
                            pass
                    
                    if not more_btn:
                        if attempt == max_attempts - 1:
                            print(f"    ! 歌曲 {idx+1} 未找到更多按钮")
                        qobuz_human_delay(0.5, 1)
                        continue
                    
                    # 点击更多按钮
                    try:
                        qobuz_move_to_element(driver, more_btn)
                        qobuz_human_delay(0.3, 0.6)
                        more_btn.click()
                    except:
                        driver.execute_script("arguments[0].click();", more_btn)
                    
                    qobuz_human_delay(1.5, 2.5)  # 等待菜单弹出
                    
                    # 点击"Add to playlists" - 支持多语言（英/法/德）
                    # 根据截图，是 ul.menu-list 里的 <a role="button">
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
                                    # 检查是否匹配任一语言的添加到播放列表文本
                                    for add_text in ADD_TO_PLAYLIST_TEXTS:
                                        if add_text.lower() in link_text.lower():
                                            add_to_playlist_btn = link
                                            break
                                    if add_to_playlist_btn:
                                        break
                            if add_to_playlist_btn:
                                break
                        except:
                            continue
                    
                    # 备选：使用多语言XPath
                    if not add_to_playlist_btn:
                        for add_text in ADD_TO_PLAYLIST_TEXTS:
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
                    
                    qobuz_human_delay(1.5, 2.5)  # 等待播放列表弹窗
                    
                    # 在弹窗中找到已创建的播放列表的 Add 按钮
                    # 根据截图，Add 按钮类名是 button.global__button--add-to-playlist
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
                                    # 检查按钮是否在包含播放列表名称的容器内
                                    try:
                                        parent = btn.find_element(By.XPATH, "./ancestor::li[contains(@class, 'add-playlist')]")
                                        parent_text = parent.text if parent else ""
                                        if playlist_name in parent_text:
                                            playlist_add_btn = btn
                                            break
                                    except:
                                        # 如果找不到父元素，直接使用第一个可见按钮
                                        playlist_add_btn = btn
                                        break
                            if playlist_add_btn:
                                break
                        except:
                            continue
                    
                    # 如果还没找到，尝试用多语言文本查找 Add 按钮
                    if not playlist_add_btn:
                        for add_text in ADD_BUTTON_TEXTS:
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
                    
                    print(f"    ✓ 已添加第 {idx+1} 首")
                    
                    added_count += 1
                    song_added = True
                    qobuz_human_delay(2, 4)
                    
                except Exception as e:
                    error_msg = str(e)
                    if attempt == max_attempts - 1:
                        print(f"    ! 歌曲 {idx+1} 添加失败: {error_msg[:80]}")
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    except:
                        pass
                    qobuz_human_delay(1, 2)
        
        print(f"  ✓ 已添加 {added_count} 首歌曲")
        return added_count
        
    except Exception as e:
        print(f"  ✗ 添加歌曲失败: {e}")
        import traceback
        traceback.print_exc()
        return 0


# ==================== 主流程 ====================
def main():
    print("="*60)
    print("Qobuz 自动化测试")
    print(f"播放列表名称: {TEST_PLAYLIST_NAME}")
    print("="*60)
    
    driver = None
    try:
        # 初始化浏览器
        print("\n初始化浏览器...")
        driver = init_qobuz_browser()
        if not driver:
            print("✗ 浏览器初始化失败")
            return
        
        # 登录
        if not login_qobuz(driver):
            print("登录失败，退出")
            return
        
        qobuz_human_delay(2, 3)
        
        # ===== 先创建播放列表 =====
        if not create_qobuz_playlist(driver, TEST_PLAYLIST_NAME):
            print("创建播放列表失败，退出")
            return
        
        # 处理每张专辑
        total_added = 0
        track_counts = list(range(TRACK_COUNT_MIN, TRACK_COUNT_MAX + 1))
        random.shuffle(track_counts)
        
        for i, album_info in enumerate(TEST_ALBUMS):
            artist_name = album_info["artist_name"]
            album_name = album_info["album_name"]
            track_count = track_counts[i % len(track_counts)]
            
            print(f"\n[{i+1}/{len(TEST_ALBUMS)}] 处理: {artist_name} - {album_name}")
            
            # 搜索专辑
            album_url = search_album_on_qobuz(driver, artist_name, album_name)
            if album_url:
                # 添加歌曲到已创建的播放列表
                added = add_songs_to_qobuz_playlist(driver, TEST_PLAYLIST_NAME, track_count)
                total_added += added
            
            qobuz_human_delay(3, 5)
        
        print(f"\n{'='*60}")
        print(f"✓ 测试完成！")
        print(f"  播放列表: {TEST_PLAYLIST_NAME}")
        print(f"  总计添加: {total_added} 首歌曲")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        if driver:
            print("\n测试完成，浏览器保持打开状态...")
            input("按 Enter 关闭浏览器...")
            driver.quit()


if __name__ == "__main__":
    main()
