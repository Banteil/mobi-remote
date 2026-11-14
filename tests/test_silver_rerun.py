"""은동전: 도는 동안 저절로 찬 은동전으로 한 판 더 할 만큼 남으면 한 번 더 돈다."""
import unittest
from unittest import mock

from mabi.exceptions import CannotProceed
from mabi.tasks import silver

CFG = {"silver": {"unit": 20}}


class RerunTest(unittest.TestCase):
    def test_runs_again_when_enough_left(self):
        with mock.patch.object(silver, "_run_round", side_effect=[("첫 판", 20), ("둘째 판", 0)]) as r:
            note = silver.run(mock.Mock(), CFG)
        self.assertEqual(r.call_count, 2)
        self.assertIn("더: 둘째 판", note)

    def test_stops_when_below_unit(self):
        with mock.patch.object(silver, "_run_round", return_value=("첫 판", 19)) as r:
            self.assertEqual(silver.run(mock.Mock(), CFG), "첫 판")
        self.assertEqual(r.call_count, 1)

    def test_only_one_extra_round(self):
        with mock.patch.object(silver, "_run_round", return_value=("판", 40)) as r:
            silver.run(mock.Mock(), CFG)
        self.assertEqual(r.call_count, 2)

    def test_extra_round_blocked_keeps_first(self):
        # 첫 판은 했다 — 더 도는 판만 막히면 실패로 뒤집지 않고 한 만큼 남긴다
        with mock.patch.object(silver, "_run_round", side_effect=[("첫 판", 20), CannotProceed("막힘")]):
            note = silver.run(mock.Mock(), CFG)
        self.assertIn("첫 판", note)
        self.assertIn("더: 진행 불가 (막힘)", note)


class Daily:
    def __init__(self):
        self.data = {}

    def get(self, slot, key):
        return self.data.get(key)

    def set(self, slot, key, value):
        self.data[key] = value


ROUND_CFG = {"silver": {"unit": 20, "min_units_for_field": 1, "field_runs": 1, "dungeon": "피오드 던전",
                        "dungeon_cost": 20, "by_slot": {}}}


def make_bot(coins=73):
    bot = mock.MagicMock()
    bot.on_clear = None
    bot.character = {"slot": 4}
    bot.daily = Daily()
    bot.read_counter.return_value = coins
    bot.state.currency.return_value = None
    return bot


class BlockedTest(unittest.TestCase):
    """한 판도 못 들어가면(지도에서 장소를 못 고름 등) '남음' 이 아니라 실패 — 한 번 더 돌지도 않는다 (2026-11-14)."""

    def test_nothing_entered_is_failure(self):
        blocked = mock.Mock(side_effect=CannotProceed("지역 맵에서 '창백한 산' 을 고르지 못함"))
        dungeon = mock.Mock(side_effect=CannotProceed("지역 맵에서 '피오드 던전' 을 고르지 못함"))
        with mock.patch.object(silver, "field_once", blocked), mock.patch.object(silver, "dungeon_once", dungeon):
            with self.assertRaises(CannotProceed) as cm:
                silver.run(make_bot(), ROUND_CFG)
        msg = str(cm.exception)
        self.assertIn("은동전 73개 그대로", msg)
        self.assertIn("창백한 산", msg)
        self.assertIn("피오드 던전", msg)
        self.assertEqual((blocked.call_count, dungeon.call_count), (1, 1))  # 같은 실패를 한 바퀴 더 돌지 않는다

    def test_partly_blocked_is_not_failure(self):
        # 사냥터는 막혔지만 던전은 했다 → 실패가 아니다 (남은 건 완료 확인이 본다)
        bot = make_bot(coins=40)
        field = mock.Mock(side_effect=CannotProceed("못 고름"))
        dungeon = mock.Mock(return_value="clear")
        bot.read_counter.side_effect = [40, 0]
        with mock.patch.object(silver, "field_once", field), mock.patch.object(silver, "dungeon_once", dungeon):
            note = silver.run(bot, ROUND_CFG)
        self.assertIn("사냥터 진행 불가", note)
        self.assertIn("던전 클리어 1/1", note)


if __name__ == "__main__":
    unittest.main()
