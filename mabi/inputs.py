"""SendInput 기반 마우스/키보드 입력."""
import ctypes
import random
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


VK = {"esc": 0x1B, "enter": 0x0D, "space": 0x20, "tab": 0x09, "backspace": 0x08,
      "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "alt": 0x12, "ctrl": 0x11, "shift": 0x10,
      "/": 0xBF}
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})


def vk_of(key: str) -> int:
    key = key.lower()
    if key in VK:
        return VK[key]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    raise ValueError(f"알 수 없는 키: {key}")


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags: int, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, data, flags, 0, 0))


def _key(vk: int, up: bool) -> INPUT:
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(0, scan, flags, 0, 0))


class Input:
    def __init__(self, jitter_px: int = 4, dry_run: bool = False, log=None):
        self.jitter_px = jitter_px
        self.dry_run = dry_run
        self.log = log

    def click(self, sx: int, sy: int) -> None:
        """화면 절대좌표 클릭. 좌표와 누름 시간에 약간의 무작위성을 준다."""
        j = self.jitter_px
        sx += random.randint(-j, j)
        sy += random.randint(-j, j)
        if self.dry_run:
            self.log and self.log.info(f"[dry-run] click ({sx}, {sy})")
            return
        user32.SetCursorPos(sx, sy)
        time.sleep(random.uniform(0.03, 0.08))
        _send(_mouse(MOUSEEVENTF_LEFTDOWN))
        time.sleep(random.uniform(0.05, 0.12))
        _send(_mouse(MOUSEEVENTF_LEFTUP))

    def drag(self, sx: int, sy: int, ex: int, ey: int, steps: int = 20) -> None:
        """화면 절대좌표 (sx, sy) 에서 (ex, ey) 로 왼쪽 버튼을 누른 채 끈다 (지도 이동 등)."""
        if self.dry_run:
            self.log and self.log.info(f"[dry-run] drag ({sx}, {sy}) → ({ex}, {ey})")
            return
        user32.SetCursorPos(sx, sy)
        time.sleep(random.uniform(0.05, 0.1))
        _send(_mouse(MOUSEEVENTF_LEFTDOWN))
        for i in range(1, steps + 1):
            user32.SetCursorPos(sx + (ex - sx) * i // steps, sy + (ey - sy) * i // steps)
            time.sleep(random.uniform(0.01, 0.02))
        time.sleep(random.uniform(0.05, 0.1))
        _send(_mouse(MOUSEEVENTF_LEFTUP))

    def scroll(self, sx: int, sy: int, notches: int) -> None:
        """notches > 0 이면 위로, < 0 이면 아래로."""
        if self.dry_run:
            self.log and self.log.info(f"[dry-run] scroll ({sx}, {sy}) {notches}")
            return
        user32.SetCursorPos(sx, sy)
        for _ in range(abs(notches)):
            _send(_mouse(MOUSEEVENTF_WHEEL, 120 if notches > 0 else -120 & 0xFFFFFFFF))
            time.sleep(random.uniform(0.04, 0.09))

    def key(self, key: str) -> None:
        vk = vk_of(key)
        if self.dry_run:
            self.log and self.log.info(f"[dry-run] key {key}")
            return
        _send(_key(vk, up=False))
        time.sleep(random.uniform(0.05, 0.11))
        _send(_key(vk, up=True))

    def hotkey(self, mod: str, key: str) -> None:
        """mod 를 누른 채 key (예: alt + enter)."""
        if self.dry_run:
            self.log and self.log.info(f"[dry-run] hotkey {mod}+{key}")
            return
        m = vk_of(mod)
        _send(_key(m, up=False))
        time.sleep(random.uniform(0.04, 0.08))
        self.key(key)
        time.sleep(random.uniform(0.04, 0.08))
        _send(_key(m, up=True))


def post_key(hwnd: int, key: str) -> None:
    """게임 창이 앞에 없어도 키를 보낸다 (PostMessage). 게임은 자기가 활성 창일 때만 키를 받으므로 활성·포커스
    메시지로 잠깐 활성인 척하게 한 뒤 누르고, 끝나면 비활성으로 되돌린다 (2026-10-23 확인 — 뒤에 둔 채 M 으로 지도 열림).
    클릭은 이렇게 해도 좌표대로 들어가지 않는다 (게임이 실제 커서 자리로 받는다)."""
    vk = vk_of(key)
    scan = user32.MapVirtualKeyW(vk, 0)
    user32.SendMessageW(hwnd, 0x001C, 1, 0)  # WM_ACTIVATEAPP
    user32.SendMessageW(hwnd, 0x0006, 1, 0)  # WM_ACTIVATE (WA_ACTIVE)
    user32.SendMessageW(hwnd, 0x0007, 0, 0)  # WM_SETFOCUS
    time.sleep(0.1)
    user32.PostMessageW(hwnd, 0x0100, vk, 1 | (scan << 16))  # WM_KEYDOWN
    time.sleep(random.uniform(0.06, 0.1))
    user32.PostMessageW(hwnd, 0x0101, vk, 1 | (scan << 16) | (0xC0 << 24))  # WM_KEYUP
    time.sleep(0.3)  # 게임이 다음 프레임에 읽을 때까지 활성으로 둔다
    user32.SendMessageW(hwnd, 0x0008, 0, 0)  # WM_KILLFOCUS
    user32.SendMessageW(hwnd, 0x0006, 0, 0)  # WM_ACTIVATE (WA_INACTIVE)
    user32.SendMessageW(hwnd, 0x001C, 0, 0)


def key_pressed(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class StopWatcher:
    """중단 키를 백그라운드에서 30ms 마다 감시한다. 짧게 눌러도 놓치지 않도록 별도 스레드에서 본다.
    눌리면 stopped 가 켜지고 봇은 다음 대기/캡처 시점에 멈춘다. force_exit 이면 OCR·CLI 호출 등으로
    grace 초 안에 멈추지 못할 때 프로세스를 강제로 끝낸다 (콘솔 실행용. GUI 는 창까지 꺼지므로 끈다).
    request() 로 키 대신 코드에서 중단을 요청할 수 있다 (GUI 의 중단 버튼)."""

    def __init__(self, vk: int, grace: float = 5.0, log=None, force_exit: bool = True):
        import threading
        self.vk, self.grace, self.log, self.force_exit = vk, grace, log, force_exit
        self.stopped = threading.Event()
        self.by_key = False  # 키로 멈췄나 (버튼·코드 요청이 아니라)
        self.touched = False  # 사람이 게임을 만져서 멈췄나 (watch_manual)
        self._closed = threading.Event()
        threading.Thread(target=self._run, name="stop-watcher", daemon=True).start()

    def request(self) -> None:
        self.stopped.set()

    def close(self) -> None:
        self._closed.set()
        if getattr(self, "_manual", None):
            self._manual.close()

    def watch_manual(self, game_hwnd) -> None:
        """사람이 게임을 직접 만지면 (게임 창 클릭·휠, 게임이 맨 앞일 때 키) 멈춘다 — 중단 키와 같은 일시정지.
        숙제 중에 지도를 여는 등 손이 가면 화면 판단이 어긋나므로 (2026-10-23: 지도에 가려 사냥터 클리어로 오판)
        아예 멈추고 사람에게 넘긴다. game_hwnd: 게임 창 핸들을 돌려주는 함수."""
        def hit(what: str) -> None:
            if self.stopped.is_set():
                return
            self.by_key = True  # 사람이 멈춘 것 → 일시정지 (F12 로 이어 함)
            self.touched = True
            self.log and self.log.warning(f"게임 조작 감지({what}) → 멈춥니다. F{self.vk - 0x6F} 로 이어 합니다"
                                          if 0x70 <= self.vk <= 0x7B else f"게임 조작 감지({what}) → 멈춥니다")
            self.stopped.set()
        self._manual = ManualInputWatcher(game_hwnd, hit, ignore_vk=self.vk)

    def _run(self) -> None:
        import os
        # 일시정지 중 F12 로 이어 하면 그 F12 가 아직 눌린 채로 새 실행이 시작된다 → 뗄 때까지 기다렸다가 감시
        # (2026-10-22: 이어 하자마자 같은 키로 다시 멈춤)
        while user32.GetAsyncKeyState(self.vk) & 0x8000 and not self._closed.is_set():
            time.sleep(0.03)
        user32.GetAsyncKeyState(self.vk)  # '이전 호출 이후 눌림' 비트 초기화
        while not (user32.GetAsyncKeyState(self.vk) & 0x8001):
            if self._closed.is_set():
                return
            if self.stopped.is_set():  # 버튼으로 중단
                break
            time.sleep(0.03)
        else:
            self.by_key = True
        self.stopped.set()
        if not self.touched:  # 게임 조작으로 멈춘 건 그쪽에서 이미 알렸다
            self.log and self.log.warning("중단 키 입력 → 멈춥니다" if self.by_key else "중단 요청 → 멈춥니다")
        try:
            import winsound
            winsound.MessageBeep()
        except Exception:
            pass
        if not self.force_exit:
            return
        time.sleep(self.grace)
        if self._closed.is_set():
            return
        self.log and self.log.warning(f"{self.grace:.0f}초 안에 멈추지 않아 강제 종료")
        os._exit(130)


class _KBDLL(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MSLL(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
# 훅용 함수는 형식을 따로 정한 별도 인스턴스로 부른다 (ctypes.windll.user32 는 모든 모듈이 같이 쓴다)
_u32 = ctypes.WinDLL("user32")
_u32.SetWindowsHookExW.argtypes = (ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
_u32.SetWindowsHookExW.restype = wintypes.HANDLE
_u32.CallNextHookEx.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_u32.CallNextHookEx.restype = ctypes.c_ssize_t
_u32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
_u32.WindowFromPoint.argtypes = (wintypes.POINT,)
_u32.WindowFromPoint.restype = wintypes.HWND
_u32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
_u32.GetAncestor.restype = wintypes.HWND
_u32.GetForegroundWindow.restype = wintypes.HWND
_k32 = ctypes.WinDLL("kernel32")
_k32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_k32.GetModuleHandleW.restype = wintypes.HMODULE


class ManualInputWatcher:
    """실제 장치(사람)의 입력만 골라 on_hit 을 부른다. 이 프로그램이 SendInput 으로 보낸 입력은 Windows 가
    '주입됨' 표시(LLKHF_INJECTED / LLMHF_INJECTED)를 붙여 주므로 걸러진다.
    - 마우스: 게임 창 위에서 누른 버튼·휠 (커서 이동은 보지 않는다)
    - 키보드: 게임 창이 맨 앞일 때 누른 키 (ignore_vk = 중단 키는 StopWatcher 몫)
    저수준 훅은 메시지 루프가 있는 스레드에서만 불리므로 전용 스레드를 띄운다."""

    WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
    KEYDOWN = (0x100, 0x104)  # WM_KEYDOWN, WM_SYSKEYDOWN
    MOUSE = {0x201: "왼쪽 클릭", 0x204: "오른쪽 클릭", 0x207: "가운데 클릭", 0x20A: "휠", 0x20B: "옆 버튼"}

    def __init__(self, game_hwnd, on_hit, ignore_vk: int = 0):
        import threading
        self.game_hwnd, self.on_hit, self.ignore_vk = game_hwnd, on_hit, ignore_vk
        self._tid = 0
        self._ready = threading.Event()
        threading.Thread(target=self._run, name="manual-input", daemon=True).start()
        self._ready.wait(2)

    def close(self) -> None:
        if self._tid:
            user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT

    def _game(self) -> int:
        try:
            return int(self.game_hwnd() or 0)
        except Exception:
            return 0

    def _run(self) -> None:

        def on_key(code, wparam, lparam):
            if code == 0 and wparam in self.KEYDOWN:
                k = ctypes.cast(lparam, ctypes.POINTER(_KBDLL)).contents
                g = self._game()
                if not k.flags & 0x10 and k.vkCode != self.ignore_vk and g and _u32.GetForegroundWindow() == g:
                    self.on_hit("키보드")
            return _u32.CallNextHookEx(None, code, wparam, lparam)

        def on_mouse(code, wparam, lparam):
            if code == 0 and wparam in self.MOUSE:
                m = ctypes.cast(lparam, ctypes.POINTER(_MSLL)).contents
                g = self._game()
                if not m.flags & 0x1 and g:
                    w = _u32.WindowFromPoint(m.pt)
                    if w and _u32.GetAncestor(w, 2) == g:  # GA_ROOT
                        self.on_hit(self.MOUSE[wparam])
            return _u32.CallNextHookEx(None, code, wparam, lparam)

        # 콜백 객체가 GC 되면 훅이 죽은 함수를 부른다 → self 에 잡아 둔다
        self._procs = (_HOOKPROC(on_key), _HOOKPROC(on_mouse))
        self._tid = _k32.GetCurrentThreadId()
        mod = _k32.GetModuleHandleW(None)
        hooks = [_u32.SetWindowsHookExW(self.WH_KEYBOARD_LL, self._procs[0], mod, 0),
                 _u32.SetWindowsHookExW(self.WH_MOUSE_LL, self._procs[1], mod, 0)]
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for h in hooks:
                if h:
                    _u32.UnhookWindowsHookEx(h)

