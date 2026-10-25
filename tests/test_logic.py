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


class SceneSkipTest(unittest.TestCase):
    """뒤에서 도는 동안 '장면 넘기기' 는 누르지 않는다 (클릭하면 게임이 앞으로 나온다). 앞에서는 바로 누른다."""

    def bot(self, background, foreground=False):
        b = mock.Mock()
        b.ui = {"scene_skip": "scene_skip", "dialog_skip": "dialog_skip"}
        b.background = background
        b.window.is_foreground.return_value = foreground
        b.vision.has.return_value = True
        b.vision.find.side_effect = lambda f, n: Match(n, 0, 0, 10, 10, 0.9) if n == "scene_skip" else None
        return b

    def test_front_clicks_right_away(self):
        b = self.bot(background=False)
        self.assertEqual(content.clear_blockers(b), "장면 넘기기")
        b.click.assert_called_once()

    def test_behind_never_grabs(self):
        b = self.bot(background=True)
        for _ in range(5):
            self.assertIsNone(content.clear_blockers(b))
        b.click.assert_not_called()

    def test_background_task_but_game_in_front_clicks(self):
        b = self.bot(background=True, foreground=True)  # 사람이 게임을 앞에 두고 보고 있으면 눌러도 된다
        self.assertEqual(content.clear_blockers(b), "장면 넘기기")


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


class ShotTest(unittest.TestCase):
    """실제 캡처로 OCR 판정 확인. 그림은 tests/fixtures — tools/make_fixture.py 로 시험이 읽는 영역만 남기고
    나머지를 검게 지운 것 (캡처 원본은 캐릭터 이름이 보여 captures/ 에만 둔다). 없으면 건너뜀.
    예전엔 logs/shots 의 캡처를 그대로 읽어, 스크린샷을 정리하다 캡처가 지워졌다 (2026-10-25) — 다시 찍어 넣었다.
    '진행하기' 가 보이는 아르바이트 목록만 아직 없다 (그날 아르바이트를 다 한 캐릭터뿐이었다)."""
    FIXTURES = Path(__file__).resolve().parent / "fixtures"

    def frame(self, name):
        p = self.FIXTURES / name
        if not p.exists():
            self.skipTest(f"시험 그림 없음: {name}")
        import cv2
        import numpy as np
        return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)

    def entry_texts(self, name):
        from mabi import gamedata as gd, ocr
        f = self.frame(name)
        top = [t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_top"))]
        right = [t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_right"))]
        return top, right

    def test_abyss_dead_screen(self):  # 2026-10-25 실기: 혼자 쓰러짐, 남은 부활 횟수 3/3 + '여기서 부활' 버튼
        from mabi.vision import Vision
        from mabi import paths as P
        f = self.frame("abyss_dead_revives3.png")
        self.assertIsNotNone(Vision(P.load().templates).find(f, "revive_here"))

    def test_abyss_entry_together(self):  # 2026-10-25 실기: 함께하기 탭, 입구 근처 → '입장하기'
        from mabi import gamedata as gd
        top, right = self.entry_texts("abyss_entry_together.png")
        self.assertTrue(any(gd.text("abyss_together") in t for t in top))
        self.assertTrue(any(gd.text("abyss_enter") in t for t in right))

    def test_arbeit_closed(self):  # 2026-10-25 실기: 오늘 아르바이트를 다 함 — '구인 마감', 누를 버튼 없음
        from mabi import gamedata as gd
        bot = mock.Mock()
        bot.frame.return_value = self.frame("questwin_arbeit_closed.png")
        items = arbeit._buttons(bot)
        self.assertTrue(any(w in arbeit._norm(t) for t, _, _ in items for w in gd.words("arbeit_closed")))
        self.assertFalse([t for t, _, _ in items if arbeit._norm(t) in (arbeit.PROGRESS, arbeit.APPLY)])

    def test_arbeit_panel_button(self):  # 퀘스트 창 아르바이트 탭, 다 보이는 '진행하기' 하나 (아르바이트가 남은 날 찍을 것)
        bot = mock.Mock()
        bot.frame.return_value = self.frame("questwin_arbeit.png")
        got = [(t, y) for t, _, y in arbeit._buttons(bot) if arbeit._norm(t) == arbeit.PROGRESS]
        self.assertEqual(len(got), 1)


class RevivesLeftTest(unittest.TestCase):
    def test_packet_first(self):
        from mabi.packet_monitor import PacketMonitor
        import time
        m = PacketMonitor(None)
        m.status, m.last_rx = "running", time.monotonic()
        bot = mock.Mock(packets=m)
        self.assertIsNone(abyss.revives_left(bot))  # 모름 → 화면 글자로
        m.apply("revive.count", {"used": 1, "max": 3})
        self.assertEqual(abyss.revives_left(bot), 2)
        m.apply("revive.count", {"used": 3, "max": 3})
        self.assertEqual(abyss.revives_left(bot), 0)  # 다 씀 → 나가기
        m.apply("revive.count", {"used": 1, "max": 6})  # 최대는 판마다 다르다 (파티 보스전 6)
        self.assertEqual(abyss.revives_left(bot), 5)


if __name__ == "__main__":
    unittest.main()
