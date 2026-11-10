"""작업 결과 가르기 (mabi/outcome) — 일일 숙제·어비스·레이드 반복 공통."""
import unittest
from unittest import mock

from mabi import outcome
from mabi.bot import Overweight, StepTimeout, StopRequested
from mabi.tasks.content import CannotProceed


class OutcomeTest(unittest.TestCase):
    def bot(self, window=True, limited=False, popup=False):
        b = mock.MagicMock()
        b.window.find.return_value = window
        b.cli.run_limited = limited
        b.run_limit_popup.return_value = popup
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
        # 연속 실행 제한(CLI 오류)이 걸려 있어도 멈추지 않고 메모만 (2026-11-10 사용자)
        status, summary = outcome.escalate(self.bot(limited=True), "ERROR", "x")
        self.assertEqual(status, "ERROR")
        self.assertIn("연속 실행 제한", summary)
        self.assertEqual(outcome.escalate(self.bot(window=False), "HEAVY", "x"), ("HEAVY", "x"))
        # 화면에 제한 창만 떠 있으면 (CLI 는 안 막힘) 멈추지 않고 실패에 메모만 붙인다
        status, summary = outcome.escalate(self.bot(popup=True), "FAIL", "x")
        self.assertEqual(status, "FAIL")
        self.assertIn("연속 실행 제한 창", summary)

    def test_overweight(self):
        b = mock.MagicMock()
        b.packets.ok, b.packets.state.weight, b.packets.state.max_weight = True, 300, 300
        from mabi.bot import Bot
        self.assertEqual(Bot.overweight(b), "가방 무게 300/300")
        b.packets.state.weight = 100
        self.assertIsNone(Bot.overweight(b))



class StopReasonTest(unittest.TestCase):
    """멈춘 까닭 — 사람이 멈춘 게 아니면 로그에 '사용자 중단' 대신 그 까닭 (작업 큐가 먼저 할 카드에 밀어냄 등)."""

    def test_reason(self):
        from mabi.inputs import StopWatcher
        w = StopWatcher(0x87, force_exit=False)  # F24 — 아무도 누르지 않는 키
        try:
            self.assertEqual(w.reason(), "사용자 중단")
            w.request("먼저 할 카드에 밀림")
            self.assertTrue(w.stopped.is_set())
            self.assertEqual(w.reason(), "먼저 할 카드에 밀림")
        finally:
            w.close()

    def test_queue_preempt_carries_reason(self):
        from gui_app.queue_api import AbyssKind, DailyKind, RaidKind
        from mabi.workqueue import STOP_WHY
        api = mock.MagicMock()
        AbyssKind(api).stop("preempt")
        api.daily_abyssStop.assert_called_once_with(STOP_WHY["preempt"])
        RaidKind(api).stop("pause")  # 사람이 멈춤 → 까닭 없음
        api.daily_raidStop.assert_called_once_with("")
        DailyKind(api).stop("preempt")
        api.daily_stop.assert_called_once_with(False, STOP_WHY["preempt"])


if __name__ == "__main__":
    unittest.main()


class FastTravelTest(unittest.TestCase):
    def test_waits_for_start_then_presses(self):
        from mabi.bot import Bot
        b = mock.MagicMock()
        b.cfg = {"game": {"fast_travel_key": "t"}}
        b.wait_packet.return_value = True
        b.fast_travel_ok.return_value = True
        self.assertTrue(Bot.fast_travel(b, wait=5))
        b.wait_packet.assert_called_once()
        b.key.assert_called_once_with("t")
        b.cfg = {"game": {"fast_travel_key": ""}}  # 옵션에서 비우면 안 씀
        b.key.reset_mock()
        self.assertFalse(Bot.fast_travel(b))
        b.key.assert_not_called()
