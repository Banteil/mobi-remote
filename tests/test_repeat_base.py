"""반복 콘텐츠 공통 틀 (mabi/tasks/repeat.py) — 캐릭터 확인·판 수/시간·수리."""
import unittest
from unittest import mock

from mabi.tasks import repeat as rp


class Fake(rp.Repeat):
    KIND, TITLE, INSIDE = "abyss", "테스트", ("play",)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.left = []

    def target(self):
        return "t"

    def where(self):
        return "main"

    def leave_for_switch(self, at):
        self.left.append(at)

    def loop(self, at):
        pass


def make(character=None, **kw):
    bot = mock.MagicMock()
    with mock.patch.object(rp.ctypes.windll.user32, "GetForegroundWindow", return_value=0):
        return Fake(bot, {"abyss": {"repair_below": 0.05, "run_timeout": 60}}, character=character, **kw)


class RepeatBaseTest(unittest.TestCase):
    def test_same_character_stays(self):
        r = make({"name": "가"})
        with mock.patch.object(rp, "current_name", return_value="가"), mock.patch.object(rp.login, "run") as login:
            self.assertEqual(r.ensure_character("play"), "play")
        login.assert_not_called()

    def test_unknown_name_inside_continues_then_rechecks(self):
        r = make({"name": "가"})
        with mock.patch.object(rp, "current_name", return_value=""), mock.patch.object(rp.login, "run") as login:
            self.assertEqual(r.ensure_character("play"), "play")
        login.assert_not_called()
        self.assertTrue(r.unchecked)
        with mock.patch.object(rp, "current_name", return_value="나"), mock.patch.object(rp.login, "run") as login:
            self.assertTrue(r.recheck("play"))  # 알고 보니 다른 캐릭터 → 나가서 바꿈
        self.assertEqual(r.left, ["play"])
        login.assert_called_once()

    def test_other_character_switches(self):
        r = make({"name": "가"})
        with mock.patch.object(rp, "current_name", return_value="나"), mock.patch.object(rp.login, "run"):
            r.ensure_character("play")
        self.assertEqual(r.left, ["play"])

    def test_done_by_runs(self):
        r = make(runs=2)
        self.assertFalse(r.done())
        r.stat["clears"] = 2
        self.assertTrue(r.done())

    def test_no_repair_after_last_run(self):
        r = make(runs=1)
        r.stat["clears"] = 1
        with mock.patch.object(rp.repair, "due", return_value=True), mock.patch.object(rp.repair, "run") as fix:
            self.assertFalse(r.repair_between(lambda: None))
        fix.assert_not_called()


if __name__ == "__main__":
    unittest.main()
