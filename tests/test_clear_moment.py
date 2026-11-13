"""클리어 신호가 온 순간 클리어로 친다 — 보상 화면 정리 중 끊겨도 그 판은 한 것 (2026-11-06)."""
import unittest
from unittest import mock

from mabi.tasks import clear, silver


class Daily:
    def __init__(self):
        self.data = {}

    def get(self, slot, key):
        return self.data.get(key)

    def set(self, slot, key, value):
        self.data[key] = value


def make_bot(coins=40):
    bot = mock.MagicMock()
    bot.on_clear = None
    bot.character = {"slot": 3}
    bot.daily = Daily()
    bot.read_counter.return_value = coins
    bot.state.currency.return_value = None
    return bot


CFG = {"silver": {"unit": 20, "min_units_for_field": 1, "field_runs": 1, "dungeon": False,
                  "dungeon_cost": 20, "by_slot": {}}}


class ClearMomentTest(unittest.TestCase):
    def test_cleared_now_calls_hook(self):
        bot = make_bot()
        seen = []
        bot.on_clear = lambda: seen.append(1)
        clear.cleared_now(bot, "던전")
        self.assertEqual(seen, [1])

    def test_field_counted_even_if_reward_screen_fails(self):
        bot = make_bot()

        def field_once(b, c, again=False, more=False):
            clear.cleared_now(b, "사냥터")  # 클리어 신호
            raise RuntimeError("보상 화면 정리 실패")  # 그 뒤 정리 중 끊김

        with mock.patch.object(silver, "field_once", field_once):
            with self.assertRaises(RuntimeError):
                silver.run(bot, CFG)
        self.assertEqual(bot.daily.data.get("silver_fields"), 1)
        self.assertIsNone(bot.daily.data.get("silver_pending"))
        self.assertIsNone(bot.on_clear)

    def test_field_counted_once(self):
        bot = make_bot()

        def field_once(b, c, again=False, more=False):
            clear.cleared_now(b, "사냥터")
            return "clear"

        with mock.patch.object(silver, "field_once", field_once):
            silver.run(bot, CFG)
        self.assertEqual(bot.daily.data.get("silver_fields"), 1)

    def test_one_clear_tasks_done_at_clear(self):
        for tid, done in (("weekday_dungeon", True), ("tribute", True), ("silver", False)):
            bot = make_bot()
            bot.task_id, bot.done_at_clear = tid, False
            clear.cleared_now(bot, "던전")
            self.assertEqual(bot.done_at_clear, done, tid)

    def test_black_hole_in_field_does_not_finish_silver(self):
        # 사냥터 안에서 부른 검은 구멍 클리어가 은동전 숙제의 '클리어로 완료' 를 켜면, 던전 직전에 멈춰도 완료로 남았다
        from mabi.tasks import black_hole
        cfg = {"black_hole": {"space_keyword": "검은 구멍", "clear_timeout": 60}}
        for tid, done in (("silver", False), ("black_hole", True)):
            bot = make_bot()
            bot.task_id, bot.done_at_clear = tid, False
            with mock.patch.object(black_hole, "game_space", return_value="지하로 뚫린 검은 구멍"), \
                    mock.patch.object(black_hole, "inside_space", return_value=False), \
                    mock.patch("mabi.monitor.of"):
                black_hole.run(bot, cfg)
            self.assertEqual(bot.done_at_clear, done, tid)

    def test_silver_done_at_last_run_clear(self):
        bot = make_bot()
        bot.task_id, bot.done_at_clear = "silver", False

        def field_once(b, c, again=False, more=False):
            clear.cleared_now(b, "사냥터")
            raise RuntimeError("보상 화면 정리 중 멈춤")

        with mock.patch.object(silver, "field_once", field_once):
            with self.assertRaises(RuntimeError):
                silver.run(bot, CFG)
        self.assertTrue(bot.done_at_clear)


if __name__ == "__main__":
    unittest.main()
