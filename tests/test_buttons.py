"""버튼 그림 시험 — tests/fixtures/buttons/<템플릿 이름>/yes/*.png 에서는 그 버튼을 찾고, no/*.png 에서는 찾지 않나.

그림으로 못 찾아 다른 방법(글자 등)으로 넘어간 화면은 logs/shots 에 missed_<템플릿>.png 로 남는다 →
tools/button_fixture.py 로 여기 담아 두고, 템플릿을 고치거나 그림을 더한(<이름>@2.png) 뒤 돌려 다른 화면이
깨지지 않았는지 본다. 캐릭터 이름이 보여 저장소에 올리지 않으므로 없으면 건너뛴다.
"""
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "tests" / "fixtures" / "buttons"


class ButtonTest(unittest.TestCase):
    def test_buttons(self):
        files = sorted(DIR.glob("*/*/*.png")) if DIR.exists() else []
        if not files:
            self.skipTest("버튼 시험 화면 없음 (tools/button_fixture.py)")
        from mabi.monitor import offline
        from mabi.vision import Vision
        v = offline.config()["vision"]
        vision = Vision(ROOT / "templates", v["threshold"], v["roi_margin"])
        wrong = []
        for p in files:
            name, want = p.parent.parent.name, p.parent.name == "yes"
            img = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)
            m = vision.best(img, name)
            got = m is not None and m.score >= vision.threshold_for(name, None)
            if got != want:
                wrong.append(f"{name}/{p.parent.name}/{p.name} 점수 {m.score if m else 0:.2f}")
        self.assertEqual(wrong, [], "버튼 판정이 폴더(yes/no)와 다른 화면")


if __name__ == "__main__":
    unittest.main()
