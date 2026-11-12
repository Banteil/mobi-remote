"""CLI get_activity 읽기 (game_state.Activity) — 키 이름·중첩을 읽는 곳은 여기 하나."""
import unittest

from mabi.game_state import Activity
from mabi.packet_monitor import map_contradicts


class ActivityTest(unittest.TestCase):
    def test_no_answer_is_all_false(self):
        a = Activity.of(None)
        self.assertIsNone(a.dungeon)
        self.assertFalse(a.in_dungeon or a.in_field or a.dead or a.busy)

    def test_dungeon_and_field(self):
        self.assertTrue(Activity.of({"Dungeon": {"State": "Cleared"}}).in_dungeon)
        self.assertFalse(Activity.of({"Dungeon": {"State": "NotInDungeon"}}).in_dungeon)
        self.assertIsNone(Activity.of({"Dungeon": None}).dungeon)
        self.assertTrue(Activity.of({"Battlefield": {"IsInBattleField": True}}).in_field)

    def test_busy(self):
        for key in ("IsAutoPlaying", "IsAutoTraveling", "IsDialoguePlaying", "IsInCombat"):
            self.assertTrue(Activity.of({key: True}).busy, key)
        self.assertFalse(Activity.of({"IsDead": True}).busy)

    def test_map_contradicts(self):
        self.assertTrue(map_contradicts("Field", {"Dungeon": {"State": "InProgress"}}))
        self.assertTrue(map_contradicts("BattleField", {}))
        self.assertFalse(map_contradicts("BattleField", {"Battlefield": {"IsInBattleField": True}}))
        self.assertFalse(map_contradicts("InstanceAbyssDungeon", {}))


if __name__ == "__main__":
    unittest.main()
