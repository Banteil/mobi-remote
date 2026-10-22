"""템플릿 매칭.

templates/<name>.png 가 템플릿 이미지이고, templates/index.json 에는
템플릿을 잘라낸 원래 위치(roi)와 개별 임계값을 기록한다.
roi 가 있으면 그 주변(margin)만 탐색해서 빠르고 오탐이 적다.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Match:
    name: str
    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2


class Vision:
    def __init__(self, template_dir: Path, threshold: float = 0.85, roi_margin: int = 80):
        self.dir = Path(template_dir)
        self.threshold = threshold
        self.roi_margin = roi_margin
        self._cache: dict[str, np.ndarray] = {}
        self._index = self._load_index()

    def _load_index(self) -> dict:
        path = self.dir / "index.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def has(self, name: str) -> bool:
        return (self.dir / f"{name}.png").exists()

    def template(self, name: str) -> np.ndarray:
        if name not in self._cache:
            path = self.dir / f"{name}.png"
            # cv2.imread 는 비ASCII 경로를 못 읽으므로 imdecode 사용
            img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR) if path.exists() else None
            if img is None:
                raise FileNotFoundError(f"템플릿 없음: {path}")
            self._cache[name] = img
        return self._cache[name]

    def _search_area(self, name: str, frame: np.ndarray, region) -> tuple[int, int, int, int]:
        fh, fw = frame.shape[:2]
        if region is None:
            roi = self._index.get(name, {}).get("roi")
            if roi is None:
                return 0, 0, fw, fh
            m = self.roi_margin
            region = (roi[0] - m, roi[1] - m, roi[2] + 2 * m, roi[3] + 2 * m)
        x, y, w, h = region
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(fw, x + w), min(fh, y + h)
        return x0, y0, x1 - x0, y1 - y0

    def _score_map(self, name, frame, region):
        tpl = self.template(name)
        x, y, w, h = self._search_area(name, frame, region)
        th, tw = tpl.shape[:2]
        if w < tw or h < th:
            return None, (x, y), tpl
        res = cv2.matchTemplate(frame[y:y + h, x:x + w], tpl, cv2.TM_CCOEFF_NORMED)
        return res, (x, y), tpl

    def threshold_for(self, name: str, threshold: float | None) -> float:
        if threshold is not None:
            return threshold
        return self._index.get(name, {}).get("threshold", self.threshold)

    def find(self, frame: np.ndarray, name: str, region=None, threshold: float | None = None) -> Match | None:
        res, (ox, oy), tpl = self._score_map(name, frame, region)
        if res is None:
            return None
        _, score, _, (mx, my) = cv2.minMaxLoc(res)
        if score < self.threshold_for(name, threshold):
            return None
        th, tw = tpl.shape[:2]
        return Match(name, ox + mx, oy + my, tw, th, float(score))

    def find_all(self, frame: np.ndarray, name: str, region=None, threshold: float | None = None) -> list[Match]:
        """같은 템플릿이 여러 개 있을 때 (예: 미션 '받기' 버튼). 위에서 아래 순서로 반환."""
        res, (ox, oy), tpl = self._score_map(name, frame, region)
        if res is None:
            return []
        th, tw = tpl.shape[:2]
        ys, xs = np.where(res >= self.threshold_for(name, threshold))
        cands = sorted(zip(res[ys, xs], xs, ys), reverse=True)
        picked: list[Match] = []
        for score, x, y in cands:
            if all(abs(x - (p.x - ox)) > tw // 2 or abs(y - (p.y - oy)) > th // 2 for p in picked):
                picked.append(Match(name, ox + int(x), oy + int(y), tw, th, float(score)))
        return sorted(picked, key=lambda m: (m.y, m.x))
