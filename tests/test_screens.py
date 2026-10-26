"""상황 판정 시험 — tests/fixtures/screens/<상황>/*.png 를 점검자(mabi.monitor.detect)가 그 상황으로 보나.

화면은 tools/classify_shots.py 로 실패 화면(logs/shots)에서 나눠 담고, 틀린 것은 맞는 폴더로 옮긴다 (폴더 이름이 정답).
캐릭터 이름이 보여 저장소에 올리지 않으므로 없으면 건너뛴다. 패킷·CLI 없이 화면만으로 본다 (offline).
템플릿·기준값을 고친 뒤 돌리면 다른 화면의 판정이 바뀌었는지 바로 보인다.
"""
import unittest
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fixtures" / "screens"


class ScreenJudgeTest(unittest.TestCase):
    def test_screens(self):
        files = sorted(DIR.glob("*/*.png")) if DIR.exists() else []
        if not files:
            self.skipTest("상황 판정 화면 없음 (tools/classify_shots.py --copy)")
        from mabi.monitor import offline
        cfg = offline.config()
        wrong = []
        for p in files:
            got = offline.judge(offline.read(p), cfg)
            if got != p.parent.name:
                wrong.append(f"{p.parent.name}/{p.name} → {got}")
        self.assertEqual(wrong, [], "판정이 폴더(정답)와 다른 화면")


if __name__ == "__main__":
    unittest.main()
