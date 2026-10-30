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


if __name__ == "__main__":
    unittest.main()
