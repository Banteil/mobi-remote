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
