import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from mabi.vision import Vision


def save(path: Path, img) -> None:
    ok, buf = cv2.imencode(".png", img)
    buf.tofile(str(path))


class VariantTest(unittest.TestCase):
    def test_second_picture_matches(self):
        """버튼 그림이 여러 장(name@2.png)이면 가장 잘 맞는 것으로 찾는다."""
        rng = np.random.default_rng(0)
        a = rng.integers(0, 255, (20, 30, 3), np.uint8)
        b = rng.integers(0, 255, (20, 30, 3), np.uint8)
        frame = np.zeros((200, 200, 3), np.uint8)
        frame[50:70, 60:90] = b
        with tempfile.TemporaryDirectory() as t:
            save(Path(t) / "btn.png", a)
            self.assertIsNone(Vision(Path(t)).find(frame, "btn"))
            save(Path(t) / "btn@2.png", b)
            m = Vision(Path(t)).find(frame, "btn")
            self.assertIsNotNone(m)
            self.assertEqual((m.name, m.x, m.y), ("btn", 60, 50))


class AssistTest(unittest.TestCase):
    def test_weak_match_needs_all_assist_marks(self):
        """index.json 의 assist: 문턱엔 못 미쳐도 min 이상이고 함께 보이는 표시가 모두 있으면 찾은 것 (메인 화면 ESC, 11-09)."""
        import json
        rng = np.random.default_rng(2)
        main = rng.integers(0, 255, (16, 38, 3), np.uint8)
        k = rng.integers(0, 255, (20, 20, 3), np.uint8)
        frame = np.zeros((300, 300, 3), np.uint8)
        noisy = main.astype(np.int16) + rng.integers(-90, 90, main.shape)  # 밝은 배경에 가려 점수가 떨어진 꼴
        frame[20:36, 20:58] = np.clip(noisy, 0, 255).astype(np.uint8)
        with tempfile.TemporaryDirectory() as t:
            save(Path(t) / "main.png", main)
            save(Path(t) / "k.png", k)
            (Path(t) / "index.json").write_text(json.dumps({"main": {"assist": {"min": 0.3, "all": ["k"]}}}), encoding="utf-8")
            v = Vision(Path(t))
            score = v.best(frame, "main").score
            self.assertTrue(0.3 <= score < 0.85, score)
            self.assertIsNone(v.find(frame, "main"))  # 함께 보일 표시가 없다
            frame[200:220, 200:220] = k
            self.assertIsNotNone(Vision(Path(t)).find(frame, "main"))
            self.assertIsNone(Vision(Path(t)).find(frame, "main", threshold=0.85))  # 문턱을 직접 주면 그 값만


class AreaTest(unittest.TestCase):
    def test_area_limits_search(self):
        """index.json 의 area 가 있으면 그 범위 밖의 같은 그림은 무시한다 (파티 플레이 G 오탐, 11-05)."""
        import json
        rng = np.random.default_rng(1)
        a = rng.integers(0, 255, (20, 30, 3), np.uint8)
        frame = np.zeros((200, 200, 3), np.uint8)
        frame[10:30, 10:40] = a  # 범위 밖
        with tempfile.TemporaryDirectory() as t:
            save(Path(t) / "btn.png", a)
            (Path(t) / "index.json").write_text(json.dumps({"btn": {"area": [100, 100, 100, 100]}}), encoding="utf-8")
            self.assertIsNone(Vision(Path(t)).find(frame, "btn"))
            frame[150:170, 120:150] = a  # 범위 안
            m = Vision(Path(t)).find(frame, "btn")
            self.assertEqual((m.x, m.y), (120, 150))

    def test_real_index_areas_fit_screen(self):
        """templates/index.json 의 area 는 1920x1080 안이고 템플릿보다 커야 한다."""
        import json
        root = Path(__file__).parent.parent / "templates"
        for name, e in json.loads((root / "index.json").read_text(encoding="utf-8")).items():
            if "area" not in e:
                continue
            x, y, w, h = e["area"]
            self.assertTrue(x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080, name)
            th, tw = Vision(root).template(name).shape[:2]
            self.assertTrue(w >= tw and h >= th, name)

if __name__ == "__main__":
    unittest.main()
