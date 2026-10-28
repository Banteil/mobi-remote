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


if __name__ == "__main__":
    unittest.main()
