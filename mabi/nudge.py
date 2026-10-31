"""키보드로 마우스 커서를 1px 씩 옮긴다 (Ctrl+W/A/S/D). 염색 스포이드를 목표 색 점에 정확히 맞출 때 쓴다.

전역 단축키라 걸어 둔 동안은 다른 프로그램에서 이 조합이 안 듣는다 → 켜 두기만 해서는 걸지 않고
염색 팔레트가 떠 있는 동안만 건다 (DyeService.on_active, 2026-10-31 사용자 요청 — 예전엔 Ctrl+Alt 로 상시).

리모콘은 일반 권한 앱이라 관리자 게임 위에서 단축키가 안 불려(UIPI) 별도 관리자 PowerShell 헬퍼를 띄웠다.
이 프로그램은 처음부터 관리자로 돌기 때문에 같은 프로세스의 스레드에서 RegisterHotKey 로 바로 받는다.
누른 만큼만 움직이고 스스로 움직이지는 않는다. 키를 누르고 있으면 윈도우 키 반복으로 계속 움직인다.
"""
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
MOD_CONTROL = 0x0002
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
KEYS = {ord("W"): (0, -1), ord("S"): (0, 1), ord("A"): (-1, 0), ord("D"): (1, 0)}


class CursorNudge:
    def __init__(self, on_error=None):
        self._thread: threading.Thread | None = None
        self._tid = 0
        self.on_error = on_error
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(ready,), name="cursor-nudge", daemon=True)
        self._thread.start()
        ready.wait(2)

    def stop(self) -> None:
        if self.running and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
        self.running = False

    def _loop(self, ready: threading.Event) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        ok = []
        for i, vk in enumerate(KEYS, start=1):
            # 핫키는 등록한 스레드의 메시지 큐로 온다 (창 없이 hWnd=None)
            if user32.RegisterHotKey(None, i, MOD_CONTROL, vk):
                ok.append(i)
        self.running = bool(ok)
        if len(ok) < len(KEYS) and self.on_error:
            self.on_error("다른 프로그램이 Ctrl+W/A/S/D 를 쓰고 있어 일부 키를 등록하지 못했습니다")
        ready.set()
        msg = wintypes.MSG()
        vks = list(KEYS)
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and 1 <= msg.wParam <= len(vks):
                dx, dy = KEYS[vks[msg.wParam - 1]]
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                user32.SetCursorPos(pt.x + dx, pt.y + dy)
        for i in ok:
            user32.UnregisterHotKey(None, i)
        self.running = False
