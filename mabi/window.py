"""게임 창 탐색, 포커스, 클라이언트 영역 좌표 계산."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32

# 좌표가 실제 픽셀과 일치하도록 Per-Monitor DPI Aware v2 로 설정
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    pass

SW_RESTORE = 9
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x2


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int


class GameWindow:
    def __init__(self, title: str):
        self.title = title
        self.hwnd = 0

    def find(self) -> bool:
        self.hwnd = user32.FindWindowW(None, self.title)
        return bool(self.hwnd)

    def require(self) -> None:
        if not self.hwnd or not user32.IsWindow(self.hwnd):
            if not self.find():
                raise RuntimeError(f"게임 창을 찾을 수 없습니다: {self.title!r}")

    def client_rect(self) -> Rect:
        """클라이언트 영역의 화면 기준 좌표."""
        self.require()
        rc = wintypes.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
        return Rect(pt.x, pt.y, rc.right, rc.bottom)

    def is_foreground(self) -> bool:
        return user32.GetForegroundWindow() == self.hwnd

    def focus(self) -> None:
        self.require()
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
        # 다른 프로세스가 포그라운드일 때 SetForegroundWindow 가 거부되는 것을 우회
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.SetForegroundWindow(self.hwnd)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
