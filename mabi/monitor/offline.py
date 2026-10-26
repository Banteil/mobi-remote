"""게임 없이 화면 한 장으로 상황을 판정한다 — 상황 판정 시험(tests/test_screens.py)과 화면 분류 도구(tools/classify_shots.py).

패킷·CLI 가 없는 셈이라 판정은 화면(템플릿)으로만 한다. 실제로는 패킷이 먼저라 대화·로딩 같은 것은 여기와 다를 수 있다
(예: 작별 화면은 '패킷이 대화 끝' 이 있어야 FAREWELL, 화면만으로는 DIALOG).
"""
import tomllib
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from ..bot import Bot
from ..vision import Vision

ROOT = Path(__file__).resolve().parent.parent.parent


def read(path: Path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def config() -> dict:
    return tomllib.loads((ROOT / "config.default.toml").read_text(encoding="utf-8"))


_vision = None


def screen_bot(frame: np.ndarray, cfg: dict | None = None):
    """frame 만 보는 Bot 비슷한 것. 판정에 쓰는 Bot 메서드(skip_button·at_main 등)는 진짜를 쓴다."""
    global _vision
    cfg = cfg or config()
    if _vision is None:
        v = cfg["vision"]
        _vision = Vision(ROOT / "templates", v["threshold"], v["roi_margin"])
    b = mock.Mock()
    b.cfg, b.ui, b.vision = cfg, cfg["ui"], _vision
    b.frame.return_value = frame
    b._frame = frame
    b.cli.run_limited = False
    b.packets.ok = False
    b.packets.status = "off"
    b.packets.at_charselect.return_value = None
    b.map_loading.return_value = None
    b.state.available.return_value = False
    b.background, b.scene_skip = False, True
    b.input.dry_run = True
    b.attendance_date = None
    for name in ("skip_button", "cutscene_playing", "at_main", "exists", "find", "_act", "auto_traveling",
                 "dialogue_playing", "in_combat", "behind", "may_skip_scene"):
        setattr(b, name, getattr(Bot, name).__get__(b))
    b._require_template = lambda name: None
    return b


def judge(frame: np.ndarray, cfg: dict | None = None) -> str:
    from . import detect
    return detect.look(screen_bot(frame, cfg), frame).what
