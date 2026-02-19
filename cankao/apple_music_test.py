#!/usr/bin/env python3
"""
Apple Music 自动化测试脚本
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
    {"artist_name": "Mark Orton", "album_name": "Nebraska"},
    {"artist_name": "Orisonne Solum", "album_name": "Streetlamp After the Last Shift"},
    {"artist_name": "Kira Kong", "album_name": "Maple Mosaic of Vows"},
]

# 每张专辑添加的歌曲数量
TRACK_COUNT_MIN = 10
TRACK_COUNT_MAX = 14

# 是否跳过登录验证（测试阶段设为True）
SKIP_LOGIN = False


# ==================== 人类模拟工具 ====================
def human_delay(min_sec=1.0, max_sec=2.5):
    """模拟人类操作的随机延迟"""
    time.sleep(random.uniform(min_sec, max_sec))


def human_typing(element, text, min_delay=0.08, max_delay=0.25):
    """模拟人类打字速度 - 更慢的随机延迟"""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def move_to_element_human(driver, element):
    """模拟人类鼠标移动到元素"""
    actions = ActionChains(driver)
    actions.move_to_element(element)
    actions.pause(random.uniform(0.2, 0.5))
    actions.perform()


# ==================== 浏览器初始化 ====================
def init_browser(incognito=True):
    """初始化 Chrome 浏览器"""
    options = webdriver.ChromeOptions()
    
    if incognito:
        options.add_argument("--incognito")
    else:
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_PATH}")
    
    # 反检测设置
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # 其他设置
    options.add_argument("--start-maximized")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    
    driver = webdriver.Chrome(options=options)
    
    # 修改 navigator.webdriver 属性
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """
    })
    
    return driver


# ==================== 登录功能 ====================
def login_apple_music(driver):
    """登录 Apple Music"""
    if SKIP_LOGIN:
        print("跳过登录验证（测试模式）")
        driver.get("https://music.apple.com")
        human_delay(3, 5)
        return True
    
    print("正在访问 Apple Music...")
    
    driver.get("https://music.apple.com")
    human_delay(3, 5)
    
    print("\n请在浏览器中完成登录，登录成功后输入 y 继续...")
    user_input = input("是否已登录成功？(y/n): ").strip().lower()
    
    if user_input == 'y':
        print("✓ 登录成功")
        return True
    else:
        print("✗ 登录失败")
        return False


# ==================== 搜索功能 ====================
def search_album(driver, artist_name, album_name):
    """搜索专辑 - 只搜索专辑名，然后匹配艺人，确保进入专辑页面
    返回: 专辑URL（成功）或 None（失败）
    """
    print(f"搜索专辑: {album_name} (艺人: {artist_name})")
    
    try:
        # 点击搜索框
        search_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input.search-input__text-field"))
        )
        move_to_element_human(driver, search_input)
        human_delay(0.5, 1)
        search_input.click()
        human_delay(0.5, 1)
        
        # 清空并输入专辑名（只搜索专辑名）
        search_input.clear()
        human_typing(search_input, album_name)
        human_delay(0.5, 1)
        search_input.send_keys(Keys.RETURN)
        
        human_delay(5, 7)  # 增加等待时间，确保搜索结果加载
        
        # 等待搜索结果加载
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".top-search-lockup, .shelf-grid, [data-testid='search-results']"))
            )
        except:
            print("  等待搜索结果加载...")
            human_delay(3, 5)
        
        # 查找"專輯"或"Albums"区域，然后找到其中的专辑链接
        # 策略：先找到包含"專輯"或"Albums"标题的section，然后找其中的专辑链接
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
                    # 获取链接周围的文本，检查是否包含艺人名
                    parent_text = link.find_element(By.XPATH, "ancestor::div[contains(@class, 'lockup')]").text if link.find_elements(By.XPATH, "ancestor::div[contains(@class, 'lockup')]") else ""
                    link_text = link.text or ""
                    
                    if artist_name.lower() in parent_text.lower() or artist_name.lower() in link_text.lower():
                        album_link = link
                        print(f"  找到匹配艺人的专辑链接")
                        break
                if album_link:
                    break
            except Exception as e:
                continue
        
        # 如果没找到匹配的，尝试直接找包含专辑名和艺人名的链接
        if not album_link:
            try:
                all_album_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']")
                for link in all_album_links:
                    if not link.is_displayed():
                        continue
                    href = link.get_attribute("href") or ""
                    # 确保是真正的专辑页面链接
                    if "/library/" in href:
                        continue
                    try:
                        # 获取锁定的父元素文本
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
        
        # 如果还是没找到，点击第一个专辑链接（确保是真正的专辑页面链接）
        if not album_link:
            try:
                all_album_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/album/']")
                for link in all_album_links:
                    if link.is_displayed():
                        href = link.get_attribute("href") or ""
                        # 确保是真正的专辑页面（包含 /album/ 而不是 /library/albums）
                        if "/album/" in href and "/library/" not in href and "/artist/" not in href:
                            album_link = link
                            print(f"  使用第一个专辑链接: {href}")
                            break
            except:
                pass
        
        if album_link:
            # 获取链接地址用于验证
            href = album_link.get_attribute("href") or ""
            print(f"  点击专辑链接: {href}")
            
            move_to_element_human(driver, album_link)
            human_delay(0.5, 1)
            album_link.click()
            
            # 增加等待时间，网络慢时需要更多时间
            human_delay(8, 12)  # 原来是3-5秒，现在增加到10-12秒
            
            # 确认机制：等待页面完全加载（检查URL和歌曲列表）
            max_retries = 5
            for retry in range(max_retries):
                current_url = driver.current_url
                if "/album/" in current_url:
                    # 进一步确认：等待歌曲列表加载
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']"))
                        )
                        print(f"  ✓ 已成功进入专辑页面: {current_url}")
                        return current_url  # 返回专辑URL
                    except:
                        if retry < max_retries - 1:
                            print(f"  等待歌曲列表加载... (重试 {retry+1}/{max_retries})")
                            human_delay(3, 5)
                        continue
                else:
                    if retry < max_retries - 1:
                        print(f"  页面还在加载，等待中... (重试 {retry+1}/{max_retries})")
                        human_delay(3, 5)
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
        import traceback
        traceback.print_exc()
        return None


def navigate_to_album_url(driver, album_url):
    """直接通过URL导航到专辑页面（不需要重新搜索）"""
    print(f"  直接导航到专辑: {album_url}")
    
    try:
        driver.get(album_url)
        human_delay(8, 12)  # 等待页面加载
        
        # 确认机制：等待页面完全加载
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
                        human_delay(3, 5)
                    continue
            else:
                if retry < max_retries - 1:
                    print(f"  页面还在加载，等待中... (重试 {retry+1}/{max_retries})")
                    human_delay(3, 5)
                else:
                    print(f"  ✗ 导航失败: {current_url}")
                    return False
        
        print(f"  ✗ 页面加载超时")
        return False
        
    except Exception as e:
        print(f"  ✗ 导航失败: {e}")
        return False


# ==================== 添加歌曲到播放列表 ====================
def add_songs_to_playlist(driver, playlist_name, track_count, is_first_album=False):
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
            max_attempts = 2  # 每首歌最多尝试2次
            
            for attempt in range(max_attempts):
                if song_added:
                    break
                    
                try:
                    # 尝试关闭可能存在的弹窗/遮罩层
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                        human_delay(0.3, 0.5)
                    except:
                        pass
                    
                    # 重新获取歌曲列表
                    songs = driver.find_elements(By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']")
                    if idx >= len(songs):
                        break  # 索引超出范围，跳过这首歌
                    
                    song = songs[idx]
                    
                    # 滚动到歌曲位置
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", song)
                    human_delay(0.8, 1.2)
                    
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
                        human_delay(0.5, 1)
                        continue  # 重试
                    
                    # 点击更多按钮
                    try:
                        move_to_element_human(driver, more_btn)
                        human_delay(0.3, 0.6)
                        more_btn.click()
                    except Exception as click_err:
                        if "intercepted" in str(click_err).lower():
                            try:
                                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                human_delay(0.5, 1)
                            except:
                                pass
                            driver.execute_script("arguments[0].click();", more_btn)
                        else:
                            raise click_err
                    
                    human_delay(1, 2)
                    
                    # 点击"加入播放清單"
                    add_to_playlist = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and contains(text(), '加入播放清單')]"))
                    )
                    move_to_element_human(driver, add_to_playlist)
                    human_delay(0.3, 0.6)
                    add_to_playlist.click()
                    
                    human_delay(1, 2)
                    
                    # 如果是第一张专辑的第一首歌曲，需要创建播放列表
                    if is_first_album and i == 0:
                        # 点击"新播放清單"
                        new_playlist = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and contains(text(), '新播放清單')]"))
                        )
                        move_to_element_human(driver, new_playlist)
                        human_delay(0.3, 0.6)
                        new_playlist.click()
                        
                        human_delay(1, 2)
                        
                        # 输入播放列表名称
                        name_input = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "input.playlist-title"))
                        )
                        name_input.clear()
                        human_typing(name_input, playlist_name)
                        human_delay(0.5, 1)
                        
                        # 勾选公开checkbox
                        try:
                            public_checkbox = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "input.public-checkbox"))
                            )
                            if not public_checkbox.is_selected():
                                driver.execute_script("arguments[0].click();", public_checkbox)
                                human_delay(0.3, 0.5)
                                print("    ✓ 已勾选公开选项")
                        except Exception as e:
                            print(f"    ! 勾选公开选项失败: {e}")
                        
                        human_delay(0.5, 1)
                        
                        # 点击"建立"按钮
                        create_btn = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "dialog form button[type='submit']"))
                        )
                        move_to_element_human(driver, create_btn)
                        human_delay(0.3, 0.6)
                        create_btn.click()
                        print("    ✓ 已点击建立按钮")
                        
                        print(f"    ✓ 播放列表创建成功，已添加第 {idx+1} 首")
                        print("    等待15秒让页面跳转完成...")
                        human_delay(14, 16)
                        
                        return -1  # 返回特殊值表示需要重新搜索专辑
                    else:
                        # 选择目标播放列表 - 如果找不到则刷新重试（苹果音乐同步有延迟）
                        playlist_found = False
                        max_refresh_attempts = 6  # 最多刷新6次，约等待1分钟
                        
                        for refresh_attempt in range(max_refresh_attempts):
                            try:
                                playlist_option = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, f"//span[contains(@class, 'contextual-menu-item__option-text') and contains(text(), '{playlist_name}')]"))
                                )
                                move_to_element_human(driver, playlist_option)
                                human_delay(0.3, 0.6)
                                playlist_option.click()
                                print(f"    ✓ 已添加第 {idx+1} 首")
                                playlist_found = True
                                break
                            except:
                                if refresh_attempt < max_refresh_attempts - 1:
                                    # 关闭菜单
                                    try:
                                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                                        human_delay(0.5, 1)
                                    except:
                                        pass
                                    
                                    print(f"    播放列表尚未同步，刷新页面等待... (尝试 {refresh_attempt+1}/{max_refresh_attempts})")
                                    driver.refresh()
                                    human_delay(9, 11)  # 等待10秒
                                    
                                    # 重新获取歌曲列表并点击更多按钮
                                    songs = driver.find_elements(By.CSS_SELECTOR, ".songs-list-row, [data-testid='track-cell']")
                                    if idx < len(songs):
                                        song = songs[idx]
                                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", song)
                                        human_delay(0.8, 1.2)
                                        
                                        more_btn = None
                                        try:
                                            more_btn = song.find_element(By.CSS_SELECTOR, "span.more-button")
                                        except:
                                            try:
                                                more_btn = song.find_element(By.CSS_SELECTOR, "button[aria-label*='更多'], button[aria-label*='more']")
                                            except:
                                                pass
                                        
                                        if more_btn:
                                            try:
                                                move_to_element_human(driver, more_btn)
                                                human_delay(0.3, 0.6)
                                                more_btn.click()
                                            except:
                                                driver.execute_script("arguments[0].click();", more_btn)
                                            
                                            human_delay(1, 2)
                                            
                                            # 点击"加入播放清單"
                                            try:
                                                add_to_playlist = WebDriverWait(driver, 5).until(
                                                    EC.element_to_be_clickable((By.XPATH, "//span[contains(@class, 'contextual-menu-item__option-text') and contains(text(), '加入播放清單')]"))
                                                )
                                                move_to_element_human(driver, add_to_playlist)
                                                human_delay(0.3, 0.6)
                                                add_to_playlist.click()
                                                human_delay(1, 2)
                                            except:
                                                pass
                                else:
                                    print(f"    ! 播放列表同步超时，歌曲 {idx+1} 添加失败")
                        
                        if not playlist_found:
                            continue  # 跳过这首歌
                    
                    added_count += 1
                    song_added = True
                    human_delay(2, 4)
                    
                except Exception as e:
                    error_msg = str(e)
                    if "intercepted" in error_msg.lower():
                        human_delay(2, 3)
                        print(f"    ? 歌曲 {idx+1} 点击被拦截，可能已添加成功（计入统计）")
                        added_count += 1
                        song_added = True
                    elif attempt == max_attempts - 1:
                        print(f"    ! 歌曲 {idx+1} 添加失败: {error_msg[:50]}")
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    except:
                        pass
                    human_delay(1, 2)
        
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
    print("Apple Music 自动化测试")
    print("="*60)
    
    driver = None
    try:
        # 初始化浏览器
        print("\n初始化浏览器...")
        driver = init_browser()
        
        # 登录
        if not login_apple_music(driver):
            print("登录失败，退出")
            return
        
        human_delay(2, 3)
        
        # 处理每张专辑
        total_added = 0
        track_counts = list(range(TRACK_COUNT_MIN, TRACK_COUNT_MAX + 1))
        random.shuffle(track_counts)
        
        for i, album_info in enumerate(TEST_ALBUMS):
            artist_name = album_info["artist_name"]
            album_name = album_info["album_name"]
            track_count = track_counts[i % len(track_counts)]
            
            print(f"\n[{i+1}/{len(TEST_ALBUMS)}] 处理: {artist_name} - {album_name}")
            
            # 搜索专辑，获取专辑URL
            album_url = search_album(driver, artist_name, album_name)
            if album_url:
                # 添加歌曲（第一张专辑时创建播放列表）
                is_first = (i == 0)
                added = add_songs_to_playlist(driver, TEST_PLAYLIST_NAME, track_count, is_first_album=is_first)
                
                # 如果返回-1，表示创建了播放列表并跳转了页面，直接用URL导航回专辑页面
                if added == -1:
                    print(f"  直接用URL导航回专辑页面...")
                    if navigate_to_album_url(driver, album_url):
                        # 重新添加，这次不是第一张专辑了（播放列表已创建）
                        # 第一首已经在创建播放列表时添加，所以只需添加 track_count-1 首
                        remaining_count = track_count - 1
                        if remaining_count > 0:
                            added = add_songs_to_playlist(driver, TEST_PLAYLIST_NAME, remaining_count, is_first_album=False)
                            if added > 0:
                                total_added += added
                        total_added += 1  # 加上创建播放列表时添加的第一首
                else:
                    total_added += added
            
            human_delay(3, 5)
        
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
            # 测试阶段不关闭浏览器，方便调试
            print("\n测试完成，浏览器保持打开状态...")
            input("按 Enter 关闭浏览器...")
            driver.quit()


if __name__ == "__main__":
    main()
