"""실패를 숨기지 않는 장치 — 같은 실패 연달아 멈춤 (runner.FailStreak), 실패 있는 일일 카드는 완료로 치우지 않음."""
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.runner import FailStreak


class FailStreakTest(unittest.TestCase):
    def test_same_failure_on_two_characters(self):
        s = FailStreak()
        self.assertFalse(s(1, "login", "FAIL", "클리어 후 화면 정리 실패 (연출) → 20261030_064720_settle.png"))
        self.assertTrue(s(2, "login", "FAIL", "클리어 후 화면 정리 실패 (연출) → 20261030_065026_settle.png"))

    def test_different_reason_or_success_resets(self):
        s = FailStreak()
        s(1, "arbeit", "FAIL", "막힘: 행운의 편지")
        self.assertFalse(s(2, "arbeit", "FAIL", "아르바이트는 진행 상태 확인에 CLI 가 필요함"))
        s(3, "arbeit", "OK", "1개 완료")
        self.assertFalse(s(4, "arbeit", "FAIL", "아르바이트는 진행 상태 확인에 CLI 가 필요함"))

    def test_same_character_twice_is_not_streak(self):
        s = FailStreak()  # 접속을 인터페이스를 맞춘 뒤 한 번 더 하는 경우 — 같은 캐릭터
        s(1, "login", "FAIL", "x")
        self.assertFalse(s(1, "login", "FAIL", "x"))


class DailyCardTest(unittest.TestCase):
    def _run(self, results):
        from gui_app.queue_api import DailyKind
        api = mock.MagicMock()
        api._q_display.return_value = True
        api._busy_reason.return_value = None
        api._q_fit.return_value = None
        api._daily_result = ("done", results)
        k = DailyKind.__new__(DailyKind)
        k.api = api
        q = mock.MagicMock(session={})
        return k.run(q, {"id": 1, "chars": [1]}), q

    def test_failures_keep_card(self):
        ok, q = self._run([("[가] 접속", "FAIL", "x"), ("[나] 접속", "OK", "")])
        self.assertFalse(ok)
        self.assertIn("1건", q.note.call_args[0][1])

    def test_all_ok_done(self):
        ok, _ = self._run([("[가] 접속", "OK", ""), ("[가] 아르바이트", "MANUAL", "가공 필요")])
        self.assertTrue(ok)


class SkippedClickTest(unittest.TestCase):
    """게임 창을 앞으로 못 가져와 누르지 못한 클릭은 조용히 넘기지 않는다 (연달아 5번이면 StepTimeout)."""

    def bot(self, background):
        from mabi.bot import Bot
        b = mock.MagicMock()
        b.background, b.input.dry_run, b._skipped_clicks, b.SKIP_LIMIT = background, False, 0, 5
        b.window.is_foreground.return_value = False
        b._click_skipped = lambda x, y: Bot._click_skipped(b, x, y)
        return b, Bot

    def test_front_task_raises_after_limit(self):
        from mabi.bot import StepTimeout
        b, Bot = self.bot(background=False)
        for _ in range(4):
            self.assertFalse(Bot.click_xy(b, 10, 10))
        with self.assertRaises(StepTimeout):
            Bot.click_xy(b, 10, 10)

    def test_background_repeat_keeps_waiting(self):
        b, Bot = self.bot(background=True)
        for _ in range(8):
            self.assertFalse(Bot.click_xy(b, 10, 10))


class DeadlineTest(unittest.TestCase):
    """숙제 하나가 시간 상한을 넘기면 check_stop 이 StepTimeout 을 낸다 (한 번만)."""

    def test_deadline(self):
        import time
        from mabi.bot import Bot, StepTimeout
        b = mock.MagicMock()
        b.stopper.stopped.is_set.return_value = False
        b.deadline = time.monotonic() + 60
        Bot.check_stop(b)  # 아직 안 넘음
        b.deadline = time.monotonic() - 1
        with self.assertRaises(StepTimeout):
            Bot.check_stop(b)
        self.assertIsNone(b.deadline)
        Bot.check_stop(b)  # 정리 단계에서 또 터지지 않는다


class LinesLeftTest(unittest.TestCase):
    """'대화 넘기기' 그림이 안 맞아도 CLI 가 넘길 대사가 있다고 하면 대사가 남은 것 (2026-10-30 던컨 앞 7분 멈춤)."""

    def test_cli_when_picture_misses(self):
        from mabi.tasks.dialogue import lines_left
        b = mock.MagicMock()
        b.skip_button.return_value = None
        b.activity.return_value = {"IsDialogueNextAvailable": True, "IsWaitingForSelection": False}
        self.assertTrue(lines_left(b))
        b.activity.return_value = {"IsDialogueNextAvailable": True, "IsWaitingForSelection": True}
        self.assertFalse(lines_left(b))
        b.activity.return_value = None
        self.assertFalse(lines_left(b))


if __name__ == "__main__":
    unittest.main()
