"""어비스 카드의 얻은 것은 그 캐릭터로 접속을 마친 뒤('ready')부터 잰다 — 카드 앞에서 재면 앞 카드의 캐릭터 가방과
빼서 다른 캐릭터 물품이 얻은 것으로 나왔다 (2026-10-30)."""
import threading
import unittest
from unittest import mock

from gui_app.queue_api import AbyssKind


class AbyssLootTest(unittest.TestCase):
    def test_measures_after_login(self):
        snaps = iter([{"items": {"룬의 파편": 100}, "cur": {}}, {"items": {"룬의 파편": 103}, "cur": {}}])
        q = mock.MagicMock(session={})
        q._snap.side_effect = lambda: next(snaps)
        api = mock.MagicMock()
        api._q_fit.return_value = False
        api._busy_reason.return_value = None
        api._abyss_result = {"type": "done"}

        def launch(v, on_event):
            on_event({"type": "start"})
            on_event({"type": "ready"})
            on_event({"type": "abyss", "clears": 1, "seconds": 60})
            t = threading.Thread(target=lambda: None)
            t.start()
            return t
        api._abyss_launch.side_effect = launch
        it = {"id": 1, "runs": 1, "slot": 2, "dungeon": "d", "difficulty": "x"}
        self.assertTrue(AbyssKind.own_loot)
        self.assertTrue(AbyssKind(api).run(q, it))
        q.report.add_loot.assert_called_once()
        self.assertEqual(q.report.add_loot.call_args[0][1]["gained"], {"룬의 파편": 3})


if __name__ == "__main__":
    unittest.main()
