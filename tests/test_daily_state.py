"""하루 진행 기록 — 사람이 멈춘 숙제(STOP)는 실패가 아니다 (mabi.profile.DailyState)."""
import tempfile
import unittest
from pathlib import Path

from mabi.profile import DailyState


class FailedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = DailyState(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_stop_is_not_failed(self):
        # 실패로 치면 그 캐릭터가 '실패만 남음'으로 맨 뒤로 밀려 다음 캐릭터부터 했다
        self.st.set(1, "silver", "STOP: ")
        self.assertFalse(self.st.failed(1, "silver"))
        self.assertFalse(self.st.is_done(1, "silver"))

    def test_fail_and_check_are_failed(self):
        self.st.set(1, "tribute", "FAIL: 퀘스트 없음")
        self.st.set(1, "daily_mission", "CHECK: 남음")
        self.assertTrue(self.st.failed(1, "tribute"))
        self.assertTrue(self.st.failed(1, "daily_mission"))

    def test_done_and_untried(self):
        self.st.set(1, "weekday_dungeon", "done")
        self.assertFalse(self.st.failed(1, "weekday_dungeon"))
        self.assertFalse(self.st.failed(1, "arbeit"))


if __name__ == "__main__":
    unittest.main()
