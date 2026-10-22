"""염색 도우미 — mobi-remote 의 dye.js / dyeTick / draw.js / dyeprefs.js 를 옮긴 것.

detect   순수 픽셀 계산 (팔레트·지시선·스포이드·색 찾기)
tracker  120ms 한 바퀴 상태 기계 (DyeTracker.tick)
draw     오버레이가 칠할 도형 목록
presets  dye-presets.json
"""
from .detect import Frame, target
from .tracker import DyeState, DyeTracker
from .draw import overlay_items
from .presets import PresetStore

__all__ = ["Frame", "target", "DyeState", "DyeTracker", "overlay_items", "PresetStore"]
