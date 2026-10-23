"""게임 클라이언트 영역 캡처."""
import ctypes
import winreg
from ctypes import wintypes

import mss
import numpy as np

from .window import GameWindow


class _BIH(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def grab_window(hwnd: int) -> np.ndarray | None:
    """게임 창을 앞으로 가져오지 않고 그 창 내용만 찍는다 (PrintWindow, PW_RENDERFULLCONTENT).
    다른 창에 가려 있어도 된다 — 리모콘을 보고 있는 동안 지금 캐릭터 이름을 읽는 데 쓴다. 최소화 등으로 못 찍으면 None.
    숙제 중 판단에는 쓰지 않는다 (느리고, 숙제는 어차피 게임을 앞에 두고 화면을 찍는다)."""
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    r = wintypes.RECT()
    if not hwnd or not u.GetClientRect(hwnd, ctypes.byref(r)) or r.right <= 0 or r.bottom <= 0:
        return None
    w, h = r.right, r.bottom
    hdc = u.GetDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    old = g.SelectObject(mdc, bmp)
    try:
        if not u.PrintWindow(hwnd, mdc, 3):  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
            return None
        bi = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0):
            return None
        return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(hwnd, hdc)


# 판단 기준 화면 크기. 템플릿·좌표·영역은 전부 이 크기의 화면 기준이다
BASE_W, BASE_H = 1920, 1080


def is_16_9(w: int, h: int) -> bool:
    return w > 0 and h > 0 and abs(w * 9 - h * 16) <= w * 9 * 0.01


REG_KEYS = (r"Software\devCAT\마비노기 모바일", r"Software\devCAT\Mabinogi Mobile")


def screen_mode() -> tuple[int | None, int | None, int | None]:
    """게임 레지스트리의 지금 (화면 모드, 해상도 가로, 세로). 화면 모드는 Unity FullScreenMode — 0 전체화면(독점),
    1 테두리 없는 전체화면, 3 창모드. 게임이 적용할 때 바로 쓴다 (2026-10-23 확인). 단 '전체화면' 은 게임이 내려가 있는
    동안 창모드 값으로 바뀌므로 앞으로 가져온 뒤에 읽는다. 키가 없으면 None."""
    want = {"Screenmanager Fullscreen mode_h": 0, "Screenmanager Resolution Width_h": 1,
            "Screenmanager Resolution Height_h": 2}
    for sub in REG_KEYS:
        out: list[int | None] = [None, None, None]
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
                i = 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    for prefix, idx in want.items():
                        if n.startswith(prefix):
                            out[idx] = int(v)
                    i += 1
        except OSError:
            continue
        if out[0] is not None:
            return out[0], out[1], out[2]
    return None, None, None


def exclusive_fullscreen() -> bool:
    """게임이 '전체화면'(독점 전체화면) 인가. 이 모드에선 mss·PrintWindow 가 멈춘 옛 화면만 돌려준다
    (Windows 가 화면 합성을 거치지 않는다) → 화면을 볼 수 없다."""
    return screen_mode()[0] == 0


class Screen:
    """게임 화면을 늘 1920x1080 기준으로 다룬다.
    게임이 다른 16:9 해상도(1280x720, 2560x1440 …)면 찍은 화면을 1920x1080 으로 바꿔 돌려주고, 누를 자리(to_screen)는
    비율만큼 실제 화면 좌표로 바꾼다 — 템플릿·좌표를 해상도마다 따로 두지 않는다 (게임 UI 는 해상도에 비례한다)."""

    def __init__(self, window: GameWindow):
        self.window = window
        self._sct = mss.mss()

    def grab(self) -> np.ndarray:
        """클라이언트 영역을 1920x1080 BGR ndarray 로 반환. 좌표는 클라이언트(1920x1080 기준)."""
        r = self.window.client_rect()
        shot = self._sct.grab({"left": r.left, "top": r.top, "width": r.width, "height": r.height})
        img = np.asarray(shot)[:, :, :3]
        if (r.width, r.height) == (BASE_W, BASE_H):
            return img.copy()
        import cv2
        # 줄일 때는 AREA(계단 현상 없이), 늘릴 때는 CUBIC(글자 가장자리가 덜 뭉개짐)
        return cv2.resize(img, (BASE_W, BASE_H), interpolation=cv2.INTER_AREA if r.width > BASE_W else cv2.INTER_CUBIC)

    def grab_behind(self) -> np.ndarray | None:
        """게임이 다른 창에 가려 있어도 찍는다 (PrintWindow). 1920x1080 기준으로 바꿔 돌려준다. 내려가 있으면 None."""
        img = grab_window(self.window.hwnd)
        if img is None or img.shape[:2] == (BASE_H, BASE_W):
            return img
        import cv2
        return cv2.resize(img, (BASE_W, BASE_H), interpolation=cv2.INTER_AREA if img.shape[1] > BASE_W else cv2.INTER_CUBIC)

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """기준(1920x1080) 좌표 → 실제 화면 절대 좌표."""
        r = self.window.client_rect()
        return r.left + round(x * r.width / BASE_W), r.top + round(y * r.height / BASE_H)
