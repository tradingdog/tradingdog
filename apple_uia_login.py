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


def click_sign_in_with_password_visual() -> tuple[int, int] | None:
    """全屏模板匹配「Sign in with password」。UIA/iframe 常扫不到这条蓝字。"""
    from pathlib import Path

    import numpy as np

    try:
        import cv2
    except Exception as e:
        _log(f"STEP visual_password_link no_cv2 {e}")
        return None

    tpl_path = Path(__file__).resolve().parent / "apple_assets" / "tpl_sign_in_with_password.png"
    if not tpl_path.exists():
        _log("STEP visual_password_link no_tpl")
        return None
    tpl = cv2.imread(str(tpl_path))
    if tpl is None:
        return None
    shot = None
    try:
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = cv2.cvtColor(np.array(sct.grab(mon)), cv2.COLOR_BGRA2BGR)
    except Exception:
        try:
            import pyautogui
            shot = cv2.cvtColor(np.array(pyautogui.screenshot()), cv2.COLOR_RGB2BGR)
        except Exception as e:
            _log(f"STEP visual_password_link grab_fail {e}")
            return None
    res = cv2.matchTemplate(shot, tpl, cv2.TM_CCOEFF_NORMED)
    _minv, maxv, _minl, maxl = cv2.minMaxLoc(res)
    if maxv < 0.72:
        _log(f"STEP visual_password_link miss score={maxv:.3f}")
        return None
    h, w = tpl.shape[:2]
    cx, cy = int(maxl[0] + w / 2), int(maxl[1] + h / 2)
    click_xy(cx, cy)
    _log(f"STEP visual_password_link ({cx},{cy}) score={maxv:.3f}")
    return (cx, cy)


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


def focus_apple_chrome() -> bool:
    """把 Apple Music 的 Chrome 窗提到前台（避免后台时点击/菜单失效）。"""
    try:
        import uiautomation as auto
        user32 = ctypes.windll.user32
        root = auto.GetRootControl()
        for win in root.GetChildren():
            try:
                name = win.Name or ""
            except Exception:
                continue
            # 标题常见：Apple Music / music.apple.com + Google Chrome
            if "Chrome" not in name:
                continue
            if not ("Apple" in name or "music.apple.com" in name.lower()):
                continue
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


def complete_password_phase(password: str) -> bool:
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
                    click_xy(resend[0] + 28, resend[1] + 37)
                    _log(f"STEP coord_switch_password near_resend {resend} attempt={attempt}")
                    time.sleep(1.6)
                else:
                    vis = click_sign_in_with_password_visual()
                    if vis:
                        time.sleep(1.8)
                    else:
                        _log(f"STEP assume_password_xy attempt={attempt}")
                        time.sleep(0.4)

        focus_apple_chrome()
        switch_to_english_ime()
        # iframe 里 Password 控件 UIA 经常扫不到；蓝字消失后再用坐标粘贴
        pwd_pt = find_named_center(pwd_names, timeout=1.8)
        if not pwd_pt:
            still_code = find_named_center(code_page_names + switch_names, timeout=0.5)
            if still_code:
                _log(f"STEP password_field_missing retry={attempt}")
                continue
            pwd_pt = XY["password"]
            _log(f"STEP password_field_xy {pwd_pt} attempt={attempt}")
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
