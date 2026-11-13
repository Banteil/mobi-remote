"""클리어 뒤에 멈춰도(F12) 숙제 카드가 완료로 사라지지 않는다 — 숙제는 OK, 실행은 멈춤으로 남는다."""
import unittest
from unittest import mock

from mabi.exceptions import StopRequested
from mabi.runner import RunOptions, Runner


def run_loop(task):
    r = Runner.__new__(Runner)
    r._emit = lambda *a, **k: None
    r._loot, r._iface = mock.MagicMock(), mock.MagicMock()
    r._iface.attempt.return_value = False
    bot = mock.MagicMock()
    bot.overweight.return_value = None
    bot.also_done = set()
    bot.stopper.reason.return_value = "사용자 중단"
    registry = {"weekday_dungeon": ("요일 던전", task), "arbeit": ("아르바이트", lambda b, c: "끝")}
    cfg = {"run": {"order": ["weekday_dungeon", "arbeit"], "task_timeout_min": 30}, "arbeit": {"slots": []}}
    results = []
    with mock.patch("mabi.runner.login.run", return_value="접속"):
        r._loop(cfg, RunOptions(only=["weekday_dungeon", "arbeit"]), registry, {}, [None], mock.MagicMock(), bot,
                mock.MagicMock(), results)
    return results


class StopAfterClearTest(unittest.TestCase):
    def test_stop_after_clear_keeps_run_stopped(self):
        def weekday(bot, cfg):
            bot.done_at_clear = True  # 클리어 신호를 받았다
            raise StopRequested("사용자 중단")  # 보상 화면 정리 중 F12

        results = run_loop(weekday)
        statuses = [(label, s) for label, s, _ in results]
        self.assertIn(("[현재 캐릭터] 요일 던전", "OK"), statuses)  # 숙제는 한 것
        self.assertEqual(statuses[-1], ("실행", "STOP"))  # 실행은 멈춤 — 큐가 일시정지로 둔다
        self.assertNotIn("[현재 캐릭터] 아르바이트", [label for label, _ in statuses])

    def test_plain_stop_not_doubled(self):
        def weekday(bot, cfg):
            raise StopRequested("사용자 중단")

        results = run_loop(weekday)
        self.assertEqual([s for _, s, _ in results].count("STOP"), 1)


class DailyCardPauseTest(unittest.TestCase):
    def test_paused_by_key_keeps_card(self):
        # F12(큐 일시정지)로 멈췄는데 결과가 모두 OK 여도 완료가 아니다
        from gui_app.queue_api import DailyKind
        api = mock.MagicMock()
        api._q_display.return_value = True
        api._busy_reason.return_value = None
        api._q_fit.return_value = None
        api._daily_result = ("done", [("[가] 접속", "OK", ""), ("[가] 공물 던전", "OK", " — 클리어 뒤 STOP, 숙제는 완료")])
        k = DailyKind.__new__(DailyKind)
        k.api = api
        q = mock.MagicMock(session={}, stop={"reason": "pause"})
        self.assertFalse(k.run(q, {"id": 1, "chars": [1, 2, 3]}))


if __name__ == "__main__":
    unittest.main()
