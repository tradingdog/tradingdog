"""Apple 登录后半段：验证码切密码 / 填密码 / Continue。

用 UIA 定位控件中心点 + win32 点击/粘贴（避免 UIA Click 与 Selenium Chrome 死锁）。
固定坐标已在 HK 1600x900 最大化实测可用。
"""
from __future__ import annotations

import ctypes
import sys
import time

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_A = 0x41
VK_V = 0x56
SW_RESTORE = 9

# 兜底坐标（1600x900 最大化 HK 实测）
XY = {
    "password_switch": (654, 601),
    "password": (800, 515),
    "password_submit": (1013, 525),
    "welcome_continue": (800, 600),  # 歡迎使用 Apple Music 红钮「繼續」
    "appleid_email": (800, 459),
    "appleid_arrow": (1013, 459),
    "modal_close": (442, 231),
}


def _log(msg: str) -> None:
    print(msg, flush=True)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def switch_to_english_ime() -> None:
    try:
        user32 = ctypes.windll.user32
        hkl = user32.LoadKeyboardLayoutW("00000409", 1)
        if hkl:
            user32.ActivateKeyboardLayout(hkl, 0)
    except Exception:
        pass


def click_xy(x: int, y: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.15)


def _chrome_client_origin() -> tuple[int, int] | None:
    """Chrome 客户区左上角屏幕坐标（Selenium 截图原点）。

    注意：部分环境下 ClientToScreen(0,0) 会错误返回 (0,0)；
    要用 WindowRect/ClientRect 推标题栏高度（实测约 +80~100）。
    """
    try:
        import win32gui
    except Exception:
        return None

    def _enum():
        out = []

        def cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd) or ""
            # 优先网页播放器标题
            if "Chrome" in title and (
                "Apple" in title
                or "music.apple.com" in title.lower()
                or "網頁播放器" in title
                or "Web Player" in title
            ):
                out.append(hwnd)
            return True

        win32gui.EnumWindows(cb, None)
        return out

    hwnds = _enum()
    if not hwnds:
        return None
    hwnd = hwnds[0]
    try:
        wr = win32gui.GetWindowRect(hwnd)  # screen LTRB
        cr = win32gui.GetClientRect(hwnd)  # client 0,0,w,h
        pt = win32gui.ClientToScreen(hwnd, (0, 0))
        client_w, client_h = cr[2] - cr[0], cr[3] - cr[1]
        win_w, win_h = wr[2] - wr[0], wr[3] - wr[1]
        # ClientToScreen 异常为 (0,0) 时，用非客户区高度推算
        if pt == (0, 0) and wr[1] <= 0:
            border_x = max(0, (win_w - client_w) // 2)
            border_y = max(0, win_h - client_h - border_x)
            return (wr[0] + border_x, wr[1] + border_y)
        return pt
    except Exception:
        return None


def click_sign_in_with_password_visual(driver=None) -> tuple[int, int] | None:
    """模板匹配「使用密碼登入 / Sign in with password」。

    优先用 Selenium 视口截图 + Chrome 客户区原点换算（调试图 1600×765 ≠ 全屏坐标）。
    """
    from pathlib import Path

    import numpy as np

    try:
        import cv2
    except Exception as e:
        _log(f"STEP visual_password_link no_cv2 {e}")
        return None

    assets = Path(__file__).resolve().parent / "apple_assets"
    tpl_paths = [
        assets / "tpl_sign_in_with_password_zh.png",
        assets / "tpl_sign_in_with_password.png",
    ]
    tpls = []
    for p in tpl_paths:
        if p.exists():
            t = cv2.imread(str(p))
            if t is not None:
                tpls.append((p.name, t))
    if not tpls:
        _log("STEP visual_password_link no_tpl")
        return None

    shot = None
    origin = None  # 视口原点；None 表示 shot 已是全屏
    if driver is not None:
        try:
            import base64

            png = driver.get_screenshot_as_png()
            arr = np.frombuffer(png, dtype=np.uint8)
            shot = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            origin = _chrome_client_origin()
        except Exception as e:
            _log(f"STEP visual_password_link driver_shot_fail {e}")
            shot = None
    if shot is None:
        try:
            import mss

            with mss.mss() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                shot = cv2.cvtColor(np.array(sct.grab(mon)), cv2.COLOR_BGRA2BGR)
            origin = (0, 0)
        except Exception as e:
            _log(f"STEP visual_password_link grab_fail {e}")
            return None

    best = None  # (score, cx, cy, name)
    for name, tpl in tpls:
        if shot.shape[0] < tpl.shape[0] or shot.shape[1] < tpl.shape[1]:
            continue
        res = cv2.matchTemplate(shot, tpl, cv2.TM_CCOEFF_NORMED)
        _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
        h, w = tpl.shape[:2]
        cx, cy = int(maxl[0] + w / 2), int(maxl[1] + h / 2)
        if best is None or maxv > best[0]:
            best = (maxv, cx, cy, name)
    if best is None or best[0] < 0.55:
        _log(f"STEP visual_password_link miss score={best[0] if best else 0:.3f}")
        return None
    maxv, cx, cy, name = best
    # 优先 CDP 视口点击（不受虚拟桌面/错误 ClientToScreen 影响）
    if driver is not None:
        try:
            for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
                driver.execute_cdp_cmd(
                    "Input.dispatchMouseEvent",
                    {
                        "type": typ,
                        "x": float(cx),
                        "y": float(cy),
                        "button": "left",
                        "clickCount": 1 if typ != "mouseMoved" else 0,
                    },
                )
            _log(
                f"STEP visual_password_link_cdp ({cx},{cy}) score={maxv:.3f} tpl={name}"
            )
            return (cx, cy)
        except Exception as e:
            _log(f"STEP visual_password_link_cdp_fail {e}")
    if origin and origin != (0, 0):
        sx, sy = origin[0] + cx, origin[1] + cy
    else:
        # ClientToScreen 常误报 (0,0)：用实测密码切换全屏坐标兜底
        sx, sy = XY["password_switch"]
    focus_apple_chrome()
    click_xy(sx, sy)
    _log(f"STEP visual_password_link ({sx},{sy}) score={maxv:.3f} tpl={name} origin={origin}")
    return (sx, sy)


def _key(vk: int, up: bool = False) -> None:
    flags = KEYEVENTF_KEYUP if up else 0
    ctypes.windll.user32.keybd_event(vk, 0, flags, 0)


def set_clipboard(text: str) -> None:
    try:
        import pyperclip
        pyperclip.copy(text)
        return
    except Exception:
        pass
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text)
        win32clipboard.CloseClipboard()
    except Exception:
        pass


def paste_at(x: int, y: int, text: str) -> None:
    switch_to_english_ime()
    focus_apple_chrome()
    click_xy(x, y)
    time.sleep(0.3)
    set_clipboard(text)
    time.sleep(0.1)
    _key(VK_CONTROL, False)
    _key(VK_A, False)
    _key(VK_A, True)
    _key(VK_CONTROL, True)
    time.sleep(0.08)
    _key(VK_CONTROL, False)
    _key(VK_V, False)
    _key(VK_V, True)
    _key(VK_CONTROL, True)
    time.sleep(0.4)


def focus_apple_chrome(title_hint: str = "") -> bool:
    """把当前加歌用的 Chrome 提到前台。优先匹配 driver 标题，避免点到别的 Apple 窗。"""
    hint = (title_hint or "").strip().casefold()
    try:
        import uiautomation as auto
        user32 = ctypes.windll.user32
        root = auto.GetRootControl()
        scored: list[tuple[int, object]] = []
        for win in root.GetChildren():
            try:
                name = win.Name or ""
            except Exception:
                continue
            if "Chrome" not in name:
                continue
            nl = name.casefold()
            if not (
                "apple" in nl
                or "music.apple.com" in nl
                or "album" in nl
                or "playlist" in nl
                or (hint and hint[:24] and hint[:24] in nl)
            ):
                continue
            score = 0
            if hint and hint[:18] in nl:
                score += 10
            if "apple music" in nl:
                score += 2
            scored.append((score, win))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _score, win in scored:
            try:
                hwnd = win.NativeWindowHandle
                if not hwnd:
                    continue
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, SW_RESTORE)
                else:
                    user32.ShowWindow(hwnd, 5)  # SW_SHOW
                # AttachThreadInput 提高 SetForegroundWindow 成功率
                try:
                    fg = user32.GetForegroundWindow()
                    cur_tid = user32.GetWindowThreadProcessId(hwnd, None)
                    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
                    my_tid = ctypes.windll.kernel32.GetCurrentThreadId()
                    if fg_tid and fg_tid != my_tid:
                        user32.AttachThreadInput(my_tid, fg_tid, True)
                    if cur_tid and cur_tid != my_tid:
                        user32.AttachThreadInput(my_tid, cur_tid, True)
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                    if fg_tid and fg_tid != my_tid:
                        user32.AttachThreadInput(my_tid, fg_tid, False)
                    if cur_tid and cur_tid != my_tid:
                        user32.AttachThreadInput(my_tid, cur_tid, False)
                except Exception:
                    user32.SetForegroundWindow(hwnd)
                time.sleep(0.25)
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _control_center(ctrl) -> tuple[int, int] | None:
    try:
        r = ctrl.BoundingRectangle
        if r.width() <= 0 or r.height() <= 0:
            return None
        return (int((r.left + r.right) / 2), int((r.top + r.bottom) / 2))
    except Exception:
        return None


def find_password_edit_center(timeout: float = 4.0) -> tuple[int, int] | None:
    """UIA 找密码 Edit 控件中心（屏幕坐标）。优先 IsPassword / 名稱含密碼。"""
    try:
        import uiautomation as auto
    except Exception:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            root = auto.GetRootControl()
            for win in root.GetChildren():
                try:
                    wname = win.Name or ""
                except Exception:
                    continue
                if "Chrome" not in wname:
                    continue
                if not (
                    "Apple" in wname
                    or "music.apple.com" in wname.lower()
                    or "網頁播放器" in wname
                    or "Web Player" in wname
                ):
                    continue
                try:
                    for ctrl, _depth in auto.WalkControl(win, maxDepth=22):
                        if time.time() >= deadline:
                            return None
                        try:
                            if (ctrl.ControlTypeName or "") != "EditControl":
                                continue
                            cname = (ctrl.Name or "").strip()
                            is_pwd = False
                            try:
                                is_pwd = bool(ctrl.GetPattern(auto.PatternId.ValuePattern) and False)
                            except Exception:
                                pass
                            try:
                                # uiautomation: IsPassword 属性
                                is_pwd = bool(getattr(ctrl, "IsPassword", False)) or is_pwd
                            except Exception:
                                pass
                            try:
                                aa = ctrl.GetLegacyIAccessiblePattern()
                                if aa and "password" in (
                                    (aa.CurrentDescription or "") + (aa.CurrentName or "")
                                ).lower():
                                    is_pwd = True
                            except Exception:
                                pass
                            cl = cname.lower()
                            if (
                                is_pwd
                                or "密碼" in cname
                                or "密码" in cname
                                or "password" in cl
                            ):
                                pt = _control_center(ctrl)
                                if pt and pt[0] > 300:
                                    _log(f"STEP uia_password_edit {pt} name={cname!r}")
                                    return pt
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.2)
    return None


def find_named_center(names: list[str], timeout: float = 3.0) -> tuple[int, int] | None:
    try:
        import uiautomation as auto
    except Exception:
        return None

    deadline = time.time() + timeout
    names_l = [n.lower() for n in names if n]
    while time.time() < deadline:
        try:
            root = auto.GetRootControl()
            for win in root.GetChildren():
                if time.time() >= deadline:
                    return None
                try:
                    wname = win.Name or ""
                except Exception:
                    continue
                if "Chrome" not in wname:
                    continue
                if not ("Apple" in wname or "music.apple.com" in wname.lower()):
                    continue
                # 精确 Name 匹配
                for want in names:
                    if time.time() >= deadline:
                        return None
                    for ctype in ("ButtonControl", "HyperlinkControl", "EditControl", "TextControl"):
                        if time.time() >= deadline:
                            return None
                        try:
                            factory = getattr(auto, ctype)
                            ctrl = factory(searchFromControl=win, Name=want, searchDepth=18)
                            if ctrl.Exists(0.05, 0.02):
                                pt = _control_center(ctrl)
                                if pt:
                                    return pt
                        except Exception:
                            continue
                # 兜底：遍历按钮/链接，包含匹配（解决「Sign in with password」搜不到）
                try:
                    for ctrl, _depth in auto.WalkControl(win, maxDepth=18):
                        if time.time() >= deadline:
                            return None
                        try:
                            ctype = ctrl.ControlTypeName or ""
                            if ctype not in ("ButtonControl", "HyperlinkControl", "EditControl"):
                                continue
                            cname = (ctrl.Name or "").strip()
                            if not cname:
                                continue
                            cl = cname.lower()
                            for want in names_l:
                                if cl == want or want in cl:
                                    pt = _control_center(ctrl)
                                    if pt:
                                        return pt
                        except Exception:
                            continue
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.25)
    return None


def wait_named(names: list[str], timeout: float = 8.0) -> bool:
    return find_named_center(names, timeout=timeout) is not None


def click_named(names: list[str], fallback_xy: tuple[int, int] | None = None, timeout: float = 3.0) -> bool:
    pt = find_named_center(names, timeout=timeout)
    if pt:
        click_xy(*pt)
        return True
    if fallback_xy:
        click_xy(*fallback_xy)
        return True
    return False


def close_blank_modal_xy() -> bool:
    pt = find_named_center(["關閉", "Close", "关闭"], timeout=1.0)
    if pt:
        click_xy(*pt)
        _log(f"STEP coord_close_blank uia {pt}")
        time.sleep(0.8)
        return True
    click_xy(*XY["modal_close"])
    _log("STEP coord_close_blank xy")
    time.sleep(0.8)
    return True


def complete_password_phase(password: str, driver=None) -> bool:
    """邮箱提交后：验证码页 → 点「使用密碼登入」→ 填密码 → 提交。

    注意：验证码页也有关闭钮，绝不能当黑框关掉。
    美区实测文案：「Sign in with password」（password 全小写）。
    """
    _log("STEP coord_password_phase")
    switch_to_english_ime()
    focus_apple_chrome()
    time.sleep(1.2)

    switch_names = [
        "使用密碼登入",
        "使用密码登录",
        "Sign In with Password",
        "Sign in with Password",
        "Sign in with password",
    ]
    code_page_names = ["Resend code", "Resend", "重新发送", "重新傳送"]
    pwd_names = ["密碼", "Password", "密码"]

    for attempt in range(1, 4):
        vis = None
        focus_apple_chrome()
        switch_to_english_ime()
        on_pwd = find_named_center(pwd_names, timeout=0.8) is not None
        # 验证码页：有 Resend / Sign in with password，尚无真正密码框
        on_code = find_named_center(code_page_names + switch_names, timeout=0.8) is not None
        if on_pwd and not on_code:
            _log(f"STEP already_on_password_page attempt={attempt}")
        else:
            pt = find_named_center(switch_names, timeout=1.2)
            if pt:
                click_xy(*pt)
                _log(f"STEP coord_switch_password uia {pt} attempt={attempt}")
                time.sleep(1.6)
            else:
                resend = find_named_center(code_page_names, timeout=0.8)
                if resend:
                    # 「使用密碼登入」在「重新傳送驗證碼」正下方（港繁实测约 +38px）
                    click_xy(resend[0], resend[1] + 38)
                    _log(f"STEP coord_switch_password near_resend {resend} attempt={attempt}")
                    time.sleep(1.6)
                else:
                    vis = click_sign_in_with_password_visual(driver)
                    if vis:
                        time.sleep(1.8)
                    else:
                        pt2 = find_named_center(switch_names, timeout=2.0)
                        if pt2:
                            click_xy(*pt2)
                            _log(f"STEP coord_switch_password uia_retry {pt2} attempt={attempt}")
                            time.sleep(1.6)
                        else:
                            # 视口坐标：origin 无效时禁止把视口坐标当屏幕坐标点；改 CDP
                            origin = _chrome_client_origin()
                            if origin and origin != (0, 0):
                                sx, sy = origin[0] + 650, origin[1] + 515
                                click_xy(sx, sy)
                                _log(
                                    f"STEP coord_switch_password viewport_xy ({sx},{sy}) "
                                    f"origin={origin} attempt={attempt}"
                                )
                            elif driver is not None:
                                try:
                                    for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
                                        driver.execute_cdp_cmd(
                                            "Input.dispatchMouseEvent",
                                            {
                                                "type": typ,
                                                "x": 650.0,
                                                "y": 515.0,
                                                "button": "left",
                                                "clickCount": 1 if typ != "mouseMoved" else 0,
                                            },
                                        )
                                    _log(
                                        f"STEP coord_switch_password cdp_xy (650,515) "
                                        f"attempt={attempt}"
                                    )
                                except Exception as e:
                                    click_xy(*XY["password_switch"])
                                    _log(
                                        f"STEP coord_switch_password fallback_xy "
                                        f"{XY['password_switch']} err={e} attempt={attempt}"
                                    )
                            else:
                                click_xy(*XY["password_switch"])
                                _log(
                                    f"STEP coord_switch_password fallback_xy {XY['password_switch']} "
                                    f"attempt={attempt}"
                                )
                            time.sleep(1.8)

        focus_apple_chrome()
        switch_to_english_ime()
        # 优先 UIA 密码 Edit（屏幕坐标），避免把视口坐标当桌面坐标
        pwd_pt = find_password_edit_center(timeout=2.0) or find_named_center(pwd_names, timeout=1.2)
        if not pwd_pt:
            still_code = find_named_center(code_page_names + switch_names, timeout=0.5)
            if still_code:
                _log(f"STEP password_field_missing retry={attempt}")
                continue
            origin = _chrome_client_origin()
            if driver is not None and (not origin or origin == (0, 0)):
                try:
                    for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
                        driver.execute_cdp_cmd(
                            "Input.dispatchMouseEvent",
                            {
                                "type": typ,
                                "x": 800.0,
                                "y": 515.0,
                                "button": "left",
                                "clickCount": 1 if typ != "mouseMoved" else 0,
                            },
                        )
                    time.sleep(0.25)
                    set_clipboard(password)
                    time.sleep(0.1)
                    _key(VK_CONTROL, False)
                    _key(VK_A, False)
                    _key(VK_A, True)
                    _key(VK_CONTROL, True)
                    time.sleep(0.08)
                    _key(VK_CONTROL, False)
                    _key(VK_V, False)
                    _key(VK_V, True)
                    _key(VK_CONTROL, True)
                    _log(f"STEP coord_password_pasted_cdp (800,515) attempt={attempt}")
                    pwd_pt = (800, 515)
                except Exception as e:
                    pwd_pt = XY["password"]
                    paste_at(pwd_pt[0], pwd_pt[1], password)
                    _log(f"STEP coord_password_pasted {pwd_pt} cdp_fail={e} attempt={attempt}")
            else:
                if origin and origin != (0, 0):
                    pwd_pt = (origin[0] + 800, origin[1] + 515)
                else:
                    pwd_pt = XY["password"]
                _log(f"STEP password_field_xy {pwd_pt} attempt={attempt}")
                paste_at(pwd_pt[0], pwd_pt[1], password)
                _log(f"STEP coord_password_pasted {pwd_pt} attempt={attempt}")
        else:
            paste_at(pwd_pt[0], pwd_pt[1], password)
            _log(f"STEP coord_password_pasted {pwd_pt} attempt={attempt}")
        time.sleep(0.35)

        submit_pt = find_named_center(["登入", "Sign In", "Continue", "繼續", "继续"], timeout=1.2)
        # 左侧栏红色 Sign In（x 很小）不是弹窗提交钮
        if submit_pt and submit_pt[0] < 280:
            _log(f"STEP ignore_sidebar_signin {submit_pt}")
            submit_pt = None
        if submit_pt and abs(submit_pt[1] - pwd_pt[1]) < 100 and submit_pt[0] > pwd_pt[0] - 20:
            click_xy(*submit_pt)
            _log(f"STEP coord_password_submit uia {submit_pt}")
        elif driver is not None:
            try:
                for typ in ("mousePressed", "mouseReleased"):
                    driver.execute_cdp_cmd(
                        "Input.dispatchMouseEvent",
                        {
                            "type": typ,
                            "x": 1010.0,
                            "y": 520.0,
                            "button": "left",
                            "clickCount": 1,
                        },
                    )
                _log("STEP coord_password_submit cdp")
            except Exception:
                click_xy(*XY["password_submit"])
                _log("STEP coord_password_submit xy")
        else:
            click_xy(*XY["password_submit"])
            _log("STEP coord_password_submit xy")
        time.sleep(3.0)

        # 仍停在验证码页说明密码未生效，重试切换
        if find_named_center(code_page_names + switch_names, timeout=0.8):
            _log(f"STEP password_still_on_code_page retry={attempt}")
            continue
        break
    else:
        _log("STEP coord_password_phase_fail still_on_code")
        return False

    for i in range(3):
        if wait_named(["我的帳户", "我的账户", "My Account"], timeout=0.6):
            _log("STEP coord_logged_in_visible")
            break
        cont = find_named_center(["繼續", "Continue"], timeout=0.5)
        if cont and 400 < cont[1] < 700:
            click_xy(*cont)
            _log(f"STEP coord_post_continue {i+1} uia {cont}")
            time.sleep(1.0)
        else:
            _log(f"STEP coord_post_continue_skip {i+1}")
            break

    _log("STEP coord_password_phase_done")
    # 若仍停在邮箱验证码页，判失败（禁止假成功）
    if find_named_center(code_page_names + switch_names, timeout=0.6):
        _log("STEP coord_password_phase_still_code")
        return False
    return True


def complete_apple_login(email: str, password: str, timeout: float = 120.0) -> bool:
    _log("STEP coord_full_login_start")
    switch_to_english_ime()
    focus_apple_chrome()
    paste_at(800, 442, email)
    _log("STEP coord_email_pasted")
    time.sleep(0.5)
    click_named(["繼續", "Continue"], fallback_xy=(800, 645), timeout=3.0)
    _log("STEP coord_email_continue")
    time.sleep(2.5)
    return complete_password_phase(password)
