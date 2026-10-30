"""얻은 것은 캐릭터 접속을 마친 뒤부터 잰다 (queue_report.LootMeter — 일일 숙제·어비스·레이드 공통).
카드 앞뒤로 재면 캐릭터를 바꾼 카드는 다른 캐릭터 가방끼리 뺐다 (2026-10-30 결과 창에 룬의 파편 +16만 등)."""
import threading
import unittest
from unittest import mock

from gui_app.queue_api import AbyssKind
from mabi import queue_report


class LootMeterTest(unittest.TestCase):
    def test_open_close(self):
        got = []
        bot = mock.MagicMock()
        bot.state.available.return_value = True
        answers = iter([[{"DisplayName": "룬의 파편", "Count": 100}], [], [{"DisplayName": "룬의 파편", "Count": 103}], []])
        bot.state.query.side_effect = lambda cmd: next(answers)
        m = queue_report.LootMeter(got.append)
        m.close(bot)  # 열지 않았으면 아무것도
        with mock.patch.object(queue_report, "item_totals", side_effect=lambda xs: {x["DisplayName"]: x["Count"] for x in xs}):
            m.open(bot, "A")
            m.close(bot)
        self.assertEqual(got, [{"who": "A", "gained": {"룬의 파편": 3}, "used": {}, "cur": {}}])


class AbyssKindLootTest(unittest.TestCase):
    def test_loot_event_and_no_card_snapshot(self):
        q = mock.MagicMock(session={})
        api = mock.MagicMock()
        api._q_fit.return_value = False
        api._busy_reason.return_value = None
        api._abyss_result = {"type": "done"}

        def launch(v, on_event):
            on_event({"type": "loot", "who": "B", "gained": {"석탄": 2}, "used": {}, "cur": {}})
            t = threading.Thread(target=lambda: None)
            t.start()
            return t
        api._abyss_launch.side_effect = launch
        self.assertTrue(AbyssKind.own_loot)  # 큐가 카드 앞뒤로 재지 않는다
        self.assertTrue(AbyssKind(api).run(q, {"id": 1, "runs": 1, "slot": 2, "dungeon": "d", "difficulty": "x"}))
        q.report.add_loot.assert_called_once()
        self.assertEqual(q.report.add_loot.call_args[0][1]["gained"], {"석탄": 2})


if __name__ == "__main__":
    unittest.main()
