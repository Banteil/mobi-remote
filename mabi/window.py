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
        bring_front(self.hwnd)

    @staticmethod
    def give_back(hwnd: int) -> None:
        """잠깐 앞으로 가져왔던 게임 대신 원래 쓰던 창(hwnd)을 다시 앞으로 (백그라운드 클릭 뒤)."""
        if hwnd and user32.IsWindow(hwnd):
            bring_front(hwnd)


def bring_front(hwnd: int) -> None:
    """hwnd 를 맨 앞으로. 다른 프로세스가 맨 앞이면 Windows 가 SetForegroundWindow 를 막으므로 먼저 입력을 하나
    보내 '마지막 입력을 받은 프로세스'가 된다. 예전엔 Alt 를 눌렀다 뗐는데, 그 Alt 가 사람이 쓰는 창을 메뉴 모드로
    만들어 다음 ESC 를 먹고, 사람이 누르고 있던 Alt(Alt+Tab)를 떼 버렸다 → 아무 일도 안 하는 빈 마우스 입력으로."""
    from .inputs import INPUT, _send
    _send(INPUT(0))  # INPUT_MOUSE, 움직임·버튼 없음
    user32.SetForegroundWindow(hwnd)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return
    # 그래도 막히면 (사람이 PC 를 안 쓰는 동안 리모콘 키가 엉뚱한 창으로 가 확인 창이 그대로 남았다 2026-10-28)
    # 지금 맨 앞 창의 입력 스레드에 잠깐 붙어서 가져온다
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(other and other != me and user32.AttachThreadInput(me, other, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, other, False)
