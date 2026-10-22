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
        self._closed = threading.Event()
        threading.Thread(target=self._run, name="stop-watcher", daemon=True).start()

    def request(self) -> None:
        self.stopped.set()

    def close(self) -> None:
        self._closed.set()

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

