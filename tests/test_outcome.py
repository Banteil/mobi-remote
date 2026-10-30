"""작업 결과 가르기 (mabi/outcome) — 일일 숙제·어비스·레이드 반복 공통."""
import unittest
from unittest import mock

from mabi import outcome
from mabi.bot import Overweight, StepTimeout, StopRequested
from mabi.tasks.content import CannotProceed


class OutcomeTest(unittest.TestCase):
    def bot(self, window=True, limited=False):
        b = mock.MagicMock()
        b.window.find.return_value = window
        b.run_limited.return_value = limited
        b.snapshot.return_value.name = "s.png"
        b.dump_box.return_value = None
        return b

    def test_classify(self):
        b = self.bot()
        self.assertEqual(outcome.classify(b, "t", "l", StopRequested())[0], "STOP")
        self.assertEqual(outcome.classify(b, "t", "l", Overweight("가방 무게 1/1"))[:2], ("HEAVY", "가방 무게 1/1"))
        self.assertEqual(outcome.classify(b, "t", "l", CannotProceed("x")), ("FAIL", "x", True))
        st, summary, messy = outcome.classify(b, "t", "l", StepTimeout("y"))
        self.assertEqual((st, messy), ("FAIL", True))
        self.assertIn("s.png", summary)
        self.assertEqual(outcome.classify(b, "t", "l", ValueError("z"))[0], "ERROR")

    def test_escalate(self):
        self.assertEqual(outcome.escalate(self.bot(), "FAIL", "x"), ("FAIL", "x"))
        self.assertEqual(outcome.escalate(self.bot(window=False), "FAIL", "x")[0], "STOP")
        self.assertEqual(outcome.escalate(self.bot(limited=True), "ERROR", "x")[0], "STOP")
        self.assertEqual(outcome.escalate(self.bot(window=False), "HEAVY", "x"), ("HEAVY", "x"))

    def test_overweight(self):
        b = mock.MagicMock()
        b.packets.ok, b.packets.state.weight, b.packets.state.max_weight = True, 300, 300
        from mabi.bot import Bot
        self.assertEqual(Bot.overweight(b), "가방 무게 300/300")
        b.packets.state.weight = 100
        self.assertIsNone(Bot.overweight(b))


if __name__ == "__main__":
    unittest.main()
