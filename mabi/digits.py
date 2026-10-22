"""HUD 재화 숫자(예: 은동전 '17/100' 의 17) 판독.

현재값은 흰색 굵은 글씨, 최대값('/100')은 회색이라 밝기 임계값으로 현재값만 분리된다.
분리된 글자를 templates/digits/<숫자>_<번호>.png 샘플과 비교해 판독한다.
샘플은 tools/capture.py digits 로 추가한다.
"""
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

GLYPH_SIZE = (12, 18)  # (w, h) 비교용 정규화 크기


def _imread_gray(path: Path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


class DigitReader:
    def __init__(self, sample_dir: Path, white_threshold: int = 230, max_diff: float = 0.22):
        self.dir = Path(sample_dir)
        self.white_threshold = white_threshold
        self.max_diff = max_diff
        self.samples: list[tuple[str, np.ndarray]] = []
        self.reload()

    def reload(self) -> None:
        self.samples = []
        for p in sorted(self.dir.glob("*.png")):
            img = _imread_gray(p)
            if img is not None:
                self.samples.append((p.stem.split("_")[0], self._normalize(img)))

    def _normalize(self, glyph: np.ndarray) -> np.ndarray:
        g = cv2.resize(glyph, GLYPH_SIZE, interpolation=cv2.INTER_AREA)
        return (g > 127).astype(np.float32)

    def segment(self, frame: np.ndarray, region) -> list[np.ndarray]:
        """region 안의 흰색 글자를 왼쪽부터 잘라 이진 이미지 목록으로 반환."""
        x, y, w, h = region
        crop = frame[y:y + h, x:x + w]
        mask = (crop.min(axis=2) >= self.white_threshold).astype(np.uint8) * 255
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        comps = [s for s in stats[1:] if s[3] >= h * 0.35 and s[4] >= 15]
        if not comps:
            return []
        # 글자 높이가 비슷한 것만 (배경의 흰 잡티 제거)
        ref_h = max(s[3] for s in comps)
        comps = sorted((s for s in comps if s[3] >= ref_h * 0.8), key=lambda s: s[0])
        return [mask[sy:sy + sh, sx:sx + sw] for sx, sy, sw, sh, _ in comps]

    def classify(self, glyph: np.ndarray) -> tuple[str | None, float]:
        g = self._normalize(glyph)
        best, best_diff = None, 1.0
        for label, s in self.samples:
            diff = float(np.abs(g - s).mean())
            if diff < best_diff:
                best, best_diff = label, diff
        return (best if best_diff <= self.max_diff else None), best_diff

    def read(self, frame: np.ndarray, region) -> int | None:
        glyphs = self.segment(frame, region)
        if not glyphs:
            return None
        labels = [self.classify(g)[0] for g in glyphs]
        if None in labels:
            return None
        return int("".join(labels))

    def read_stable(self, grab, region, tries: int = 3) -> int | None:
        """여러 프레임을 읽어 다수결. 이펙트 등으로 순간적으로 틀리는 것을 막는다."""
        values = [self.read(grab(), region) for _ in range(tries)]
        values = [v for v in values if v is not None]
        if not values:
            return None
        value, count = Counter(values).most_common(1)[0]
        return value if count * 2 > tries else None
