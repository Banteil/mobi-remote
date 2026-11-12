"""템플릿 매칭.

templates/<name>.png 가 템플릿 이미지이고, templates/index.json 에는
템플릿을 잘라낸 원래 위치(roi)와 개별 임계값을 기록한다.
roi 가 있으면 그 주변(margin)만 탐색해서 빠르고 오탐이 적다.
자리가 조금씩 움직이는 템플릿(목록 속 버튼 등)은 roi 대신 area [x, y, w, h] 로 넉넉한 탐색 범위를 준다 —
화면 전체를 뒤지면 엉뚱한 곳(파티 플레이의 G 등)에 걸린다 (사용자 11-05).
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
        self._variants: dict[str, list[str]] = {}
        self._index = self._load_index()

    def _load_index(self) -> dict:
        path = self.dir / "index.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def has(self, name: str) -> bool:
        return (self.dir / f"{name}.png").exists()

    def variants(self, name: str) -> list[str]:
        """name 과 같은 버튼의 다른 그림들 (name@2.png, name@3.png …) — 배경·밝기에 따라 한 장으로는 문턱을 못 넘는
        버튼이 있다 (2026-10-28 아르바이트 '수락' 0.61~0.77). 판정 기준·탐색 자리(index.json)는 name 것을 같이 쓴다."""
        if name not in self._variants:
            extra = sorted(p.stem for p in self.dir.glob(f"{name}@*.png"))
            self._variants[name] = [name, *extra]
        return self._variants[name]

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
            entry = self._index.get(name, {})
            roi = entry.get("roi")
            if roi is not None:
                m = self.roi_margin
                region = (roi[0] - m, roi[1] - m, roi[2] + 2 * m, roi[3] + 2 * m)
            elif entry.get("area") is not None:
                region = entry["area"]
            else:
                return 0, 0, fw, fh
        x, y, w, h = region
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(fw, x + w), min(fh, y + h)
        return x0, y0, x1 - x0, y1 - y0

    def _score_map(self, name, frame, region, key=None):
        tpl = self.template(key or name)
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

    def best(self, frame: np.ndarray, name: str, region=None) -> Match | None:
        """그림들(variants) 중 가장 잘 맞는 자리와 점수 — 문턱과 상관없이 (시험·진단용)."""
        top = None
        for key in self.variants(name):
            res, (ox, oy), tpl = self._score_map(name, frame, region, key)
            if res is None:
                continue
            _, score, _, (mx, my) = cv2.minMaxLoc(res)
            if top is None or score > top.score:
                th, tw = tpl.shape[:2]
                top = Match(name, ox + mx, oy + my, tw, th, float(score))
        return top

    def find(self, frame: np.ndarray, name: str, region=None, threshold: float | None = None) -> Match | None:
        m = self.best(frame, name, region)
        if m is None:
            return None
        if m.score >= self.threshold_for(name, threshold):
            return m
        return m if self._assisted(frame, name, m.score, threshold) else None

    def _assisted(self, frame: np.ndarray, name: str, score: float, threshold: float | None) -> bool:
        """index.json 의 assist {min, all}: 문턱엔 못 미쳐도 min 이상이고 함께 보이는 표시(all)가 모두 보이면 찾은 것으로 본다.
        반투명한 표시는 뒤 배경이 밝으면 점수가 떨어진다 — 메인 화면 'ESC' 글자가 식당 흰 창틀 앞에서 0.844 로
        문턱(0.85)을 놓쳐 메인 화면을 못 알아봤다 (2026-11-09). 불투명한 K·I 키 표시는 배경을 타지 않는다.
        이 그림 이름으로 찾는 곳(at_main·wait_any·리모콘 화면)은 모두 여기를 거쳐 같은 기준을 쓴다.
        문턱을 직접 준 호출(threshold)은 그 값만 본다."""
        a = self._index.get(name, {}).get("assist")
        if not a or threshold is not None or score < a.get("min", 1.0):
            return False
        return all(self.has(n) and self.find(frame, n) is not None for n in a.get("all", ()))

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


# ---- 색 판정 (초록 체크·켜진 스위치)

def green(patch, g_min: int = 120, r_max: int = 120, b_max: int = 160) -> np.ndarray:
    """patch(BGR 화면 조각) 화소마다 초록인가. 기본 기준(G>120 · R<120 · B<160)은 콘텐츠 가이드 일일·주간 달성의 초록 체크.
    기준값은 자리마다 그 자리에서 재서 맞춘 값이라 인자로 남긴다 — '우연한 만남' 스위치는 G>150 · B<150 (tasks/entry).
    하나로 맞추려면 두 자리를 다시 재야 한다."""
    p = np.asarray(patch).reshape(-1, 3).astype(int)
    return (p[:, 1] > g_min) & (p[:, 2] < r_max) & (p[:, 0] < b_max)


def green_ratio(patch, **kw) -> float:
    """patch 중 초록 화소 비율 (0~1, 빈 조각은 0). 기준값은 green 과 같다."""
    m = green(patch, **kw)
    return float(m.mean()) if m.size else 0.0
