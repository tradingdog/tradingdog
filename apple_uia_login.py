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
                if "Apple" not in wname or "Chrome" not in wname:
                    continue
                for want in names:
                    if time.time() >= deadline:
                        return None
                    for ctype in ("ButtonControl", "HyperlinkControl", "EditControl"):
                        if time.time() >= deadline:
                            return None
                        try:
                            factory = getattr(auto, ctype)
                            # searchDepth 过大在 Chrome 上会卡死级慢
                            ctrl = factory(searchFromControl=win, Name=want, searchDepth=12)
                            if ctrl.Exists(0.05, 0.02):
                                pt = _control_center(ctrl)
                                if pt:
                                    return pt
                        except Exception:
                            continue
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
    """
    _log("STEP coord_password_phase")
    switch_to_english_ime()
    focus_apple_chrome()
    time.sleep(1.2)

    switch_names = ["使用密碼登入", "Sign In with Password"]
    pwd_names = ["密碼", "Password"]

    for attempt in range(1, 4):
        focus_apple_chrome()
        switch_to_english_ime()
        if find_named_center(pwd_names, timeout=0.8):
            _log(f"STEP already_on_password_page attempt={attempt}")
        else:
            pt = find_named_center(switch_names, timeout=2.0)
            if pt:
                click_xy(*pt)
                _log(f"STEP coord_switch_password uia {pt} attempt={attempt}")
            else:
                click_xy(*XY["password_switch"])
                _log(f"STEP coord_switch_password xy attempt={attempt}")
            time.sleep(2.0)

        focus_apple_chrome()
        switch_to_english_ime()
        pwd_pt = find_named_center(pwd_names, timeout=2.5) or XY["password"]
        paste_at(pwd_pt[0], pwd_pt[1], password)
        _log(f"STEP coord_password_pasted {pwd_pt} attempt={attempt}")
        time.sleep(0.35)

        submit_pt = find_named_center(["登入", "Sign In"], timeout=1.0)
        if submit_pt and abs(submit_pt[1] - pwd_pt[1]) < 80 and submit_pt[0] > pwd_pt[0]:
            click_xy(*submit_pt)
            _log(f"STEP coord_password_submit uia {submit_pt}")
        else:
            click_xy(*XY["password_submit"])
            _log("STEP coord_password_submit xy")
        time.sleep(3.0)

        # 仍停在验证码页说明密码未生效，重试切换
        if find_named_center(switch_names, timeout=0.8):
            _log(f"STEP password_still_on_code_page retry={attempt}")
            continue
        break

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
