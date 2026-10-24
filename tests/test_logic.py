"""게임 없이 돌리는 판정 로직 테스트.  .venv\\Scripts\\python.exe -m unittest discover tests"""
import unittest
from pathlib import Path
from unittest import mock

from mabi import progress
from mabi.tasks import abyss, arbeit, content
from mabi.vision import Match


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        p = mock.patch.object(progress.time, "monotonic", self.clock)
        p.start()
        self.addCleanup(p.stop)

    def test_stalls_without_change(self):
        p = progress.Progress(stall=180)
        p.update(["은 광석 보유 10/100"])
        self.clock.t += 181
        self.assertTrue(p.stalled)

    def test_change_rewinds_clock(self):
        # 100개짜리 채집: 5분이 넘어도 개수가 늘고 있으면 끝나지 않는다 (2026-10-24 82/100 에서 끊긴 일)
        p = progress.Progress(stall=180)
        for n in range(10, 100, 10):
            self.assertTrue(p.update([f"은 광석 보유 {n}/100"]))
            self.clock.t += 120
            self.assertFalse(p.expired)

    def test_cap(self):
        p = progress.Progress(stall=180, cap=600)
        for n in range(20):
            p.update(n)
            self.clock.t += 60
        self.assertTrue(p.expired)
        self.assertFalse(p.stalled)


class QuestWindowTest(unittest.TestCase):
    def test_buttons_on_tab_bar_are_skipped(self):
        # 탭 줄(950)에 걸친 버튼은 누르면 '이벤트' 탭이 눌린다 → 빼고, 위에서부터 정렬
        bot = mock.Mock()
        bot.find_all.return_value = [Match("go", 1700, 900, 150, 60, 0.9),   # 걸침 (아래 끝 960)
                                     Match("go", 1700, 640, 150, 60, 0.9),
                                     Match("go", 1700, 300, 150, 60, 0.9)]
        self.assertEqual([b.y for b in content.questwin_buttons(bot, "go")], [300, 640])

    def test_text_ok(self):
        self.assertTrue(content.questwin_text_ok(671))
        self.assertFalse(content.questwin_text_ok(975))


class ArbeitTest(unittest.TestCase):
    def test_buttons_filter_keeps_titles(self):
        items = [("국경 수비대 물자 보급", 1400, 880), ("지원하기", 1756, 975), ("진행하기", 1756, 671)]
        with mock.patch.object(arbeit.ocr, "find_texts", return_value=items):
            got = arbeit._buttons(mock.Mock())
        self.assertIn(("국경 수비대 물자 보급", 1400, 880), got)  # 글자는 걸쳐도 남긴다 (카드 제목 짐작용)
        self.assertIn(("진행하기", 1756, 671), got)
        self.assertNotIn(("지원하기", 1756, 975), got)

    def test_card_title(self):
        # 카드: 제목 / NPC 위치·'n시간 남음' / 설명(두 줄) / 버튼
        items = [("국경 수비대 물자 보급", 1400, 300), ("가이레흐 언덕 · 1일 11시간 남음", 1450, 340),
                 ("설명 첫 줄", 1450, 380), ("설명 둘째 줄", 1450, 410), ("진행하기", 1756, 470)]
        self.assertEqual(arbeit._card_title(items, 1756, 470), "국경 수비대 물자 보급")

    def test_same_tolerates_ocr(self):
        self.assertTrue(arbeit._same("국경 수비대 물자 보급", "국경 수비대 물자보급"))
        self.assertTrue(arbeit._same("별과 돌이 빚은 광석", "별과 돌이 빛은 광석"))
        self.assertFalse(arbeit._same("일생일대의 위기", "국경 수비대 물자 보급"))

    def test_missing_items(self):
        job = {"title": "x", "objectives": [
            {"Description": "<b>은 광석</b> 보유 82/100", "IsCompleted": False},
            {"Description": "상급 생가죽 보유 20/20", "IsCompleted": True},
            {"Description": "아이던에게 납품", "IsCompleted": False}]}
        self.assertEqual(arbeit.missing_items(job), ["은 광석 보유 82/100"])
        self.assertEqual(arbeit._item_name("은 광석 보유 82/100"), "은 광석")


class AbyssTest(unittest.TestCase):
    def _left(self, texts):
        with mock.patch.object(abyss, "find_texts", return_value=[(t, 0, 0) for t in texts]):
            return abyss._revives_left(None, None)

    def test_revives_left(self):
        self.assertEqual(self._left(["행동불능", "남은 부활 횟수 2/3"]), 2)
        self.assertEqual(self._left(["남은 부활 횟수 0 / 3"]), 0)
        self.assertEqual(self._left(["전멸하였습니다"]), 0)  # 함께하기 전멸 — 버튼 자체가 없다
        self.assertIsNone(self._left(["행동불능"]))


class ShotTest(unittest.TestCase):
    """실제 캡처로 OCR 판정 확인. 캡처(logs/shots)는 화면에 캐릭터 이름이 보여 저장소에 올리지 않는다 → 없으면 건너뜀."""
    SHOTS = Path(__file__).resolve().parent.parent / "logs" / "shots"

    def frame(self, name):
        p = self.SHOTS / name
        if not p.exists():
            self.skipTest(f"캡처 없음: {name}")
        import cv2
        import numpy as np
        return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)

    def test_abyss_no_revives_left(self):  # 2026-10-24 실기: 부활 횟수 0/3 → 나가기
        self.assertEqual(abyss._revives_left(None, self.frame("20261024_143154_abyss_dead.png")), 0)

    def test_abyss_entry_solo_tab_far_away(self):
        # 2026-10-24: 혼자하기 탭 + 입구에서 먼 캐릭터('이동하기') — 탭 글자로 입장 화면을 알아보고 함께하기를 누를 수 있어야
        from mabi import gamedata as gd, ocr
        f = self.frame("20261024_212603_abyss.png")
        top = [t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_top"))]
        right = [t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_right"))]
        self.assertTrue(any(gd.text("abyss_together") in t for t in top))
        self.assertTrue(any(gd.text("abyss_move") in t for t in right))

    def test_arbeit_panel_button(self):  # 퀘스트 창 아르바이트 탭, 다 보이는 '진행하기' 하나
        bot = mock.Mock()
        bot.frame.return_value = self.frame("20261024_125340_questwin.png")
        got = [(t, y) for t, _, y in arbeit._buttons(bot) if arbeit._norm(t) == arbeit.PROGRESS]
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()
