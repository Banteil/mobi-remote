"""게임 클라이언트 영역 캡처."""
import mss
import numpy as np

from .window import GameWindow


class Screen:
    def __init__(self, window: GameWindow):
        self.window = window
        self._sct = mss.mss()

    def grab(self) -> np.ndarray:
        """클라이언트 영역을 BGR ndarray 로 반환. 좌표는 클라이언트 기준."""
        r = self.window.client_rect()
        shot = self._sct.grab({"left": r.left, "top": r.top, "width": r.width, "height": r.height})
        return np.asarray(shot)[:, :, :3].copy()
