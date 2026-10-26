import time
import unittest
from unittest import mock

from mabi.bot import StepTimeout
from mabi.tasks import content


class WithRetriesTest(unittest.TestCase):
    def test_retries_then_succeeds(self):
        bot = mock.Mock()
        fn = mock.Mock(side_effect=[StepTimeout("a"), RuntimeError("b"), "ok"])
        self.assertEqual(content.with_retries(bot, "x", fn), "ok")
        self.assertEqual(fn.call_count, 3)
        self.assertEqual(bot.to_main.call_count, 2)

    def test_gives_up_after_retries(self):
        bot = mock.Mock()
        fn = mock.Mock(side_effect=StepTimeout("a"))
        with self.assertRaises(StepTimeout):
            content.with_retries(bot, "x", fn)
        self.assertEqual(fn.call_count, content.STEP_RETRIES + 1)


class TravelStopTest(unittest.TestCase):
    def test_stopped_without_arrival_fails_fast(self):
        """이동이 끝났는데 도착 화면이 안 뜨면 상한(timeout)까지 기다리지 않는다."""
        bot = mock.Mock()
        bot.cfg = {"game": {}}
        bot.wait_packet.return_value = True
        bot.wait_any.side_effect = StepTimeout("x")
        bot.auto_traveling.return_value = False
        bot.map_loading.return_value = False
        t = time.monotonic()
        with mock.patch.object(content, "ARRIVE_GRACE", 0.05):
            with self.assertRaises(StepTimeout):
                content.travel(bot, ["a"], 600)
        self.assertLess(time.monotonic() - t, 5)


class ResumeAfterRestartTest(unittest.TestCase):
    def test_wait_card_starts(self):
        """다시 켜면 일시정지 카드가 대기가 된다 — F12(이어 하기)가 그 카드를 돌려야 한다."""
        import json
        import tempfile
        from pathlib import Path
        from mabi.workqueue import WorkQueue

        class Kind:
            own_loot = True
            ran = []

            def run(self, q, it):
                self.ran.append(it["id"])
                return True

            def view(self, it):
                return {}

            def where(self, it):
                return ""

            def stop(self, reason):
                pass

        d = Path(tempfile.mkdtemp())
        (d / "q.json").write_text(json.dumps({"items": [{"id": 1, "label": "x", "status": "pause", "kind": "daily"}]}),
                                  encoding="utf-8")
        kind = Kind()
        q = WorkQueue(d / "q.json", d / "h.jsonl", lambda *a: None, {"daily": kind})
        self.assertIsNone(q.top_paused())
        self.assertTrue(q.can_resume())
        q.resume_top()
        q._thread.join(5)
        self.assertEqual(kind.ran, [1])


class RunLimitTest(unittest.TestCase):
    def test_detects_code_or_message(self):
        from mabi.connector import is_run_limit
        self.assertTrue(is_run_limit("continuous_run_limit", None))
        self.assertTrue(is_run_limit("blocked", "Continuous run limit reached"))
        self.assertFalse(is_run_limit("loading", "Game is currently loading."))
        self.assertFalse(is_run_limit(None, None))


if __name__ == "__main__":
    unittest.main()
