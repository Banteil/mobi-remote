"""작업 큐 제작·채집·가공 카드의 캐릭터 고르기 (gui_app.queue_api.card_character)."""
import unittest

from gui_app.queue_api import card_character

CHARS = [{"slot": 1, "name": "가나다"}, {"slot": 2, "name": "라마바"}]


class CardCharacterTest(unittest.TestCase):
    def test_slot_wants_that_character(self):
        self.assertEqual(card_character({"kind": "goal", "slot": 2}, CHARS), ("want", CHARS[1]))
        self.assertEqual(card_character({"kind": "action", "slot": 1}, CHARS), ("want", CHARS[0]))

    def test_slot_not_in_profile(self):
        self.assertEqual(card_character({"kind": "goal", "slot": 5}, CHARS), ("missing", None))

    def test_slot_wins_over_pin(self):
        # 기억해 둔 뒤에 사람이 캐릭터를 골랐으면 고른 것을 따른다
        self.assertEqual(card_character({"kind": "goal", "slot": 1, "pin": CHARS[1]}, CHARS), ("want", CHARS[0]))

    def test_goal_remembers_then_returns(self):
        # 처음엔 지금 캐릭터를 기억하고, 밀렸다 돌아오면 그 캐릭터로
        self.assertEqual(card_character({"kind": "goal"}, CHARS), ("remember", None))
        self.assertEqual(card_character({"kind": "goal", "slot": 0, "pin": CHARS[0]}, CHARS), ("want", CHARS[0]))

    def test_old_card_without_kind_is_goal(self):
        self.assertEqual(card_character({}, CHARS), ("remember", None))

    def test_action_current_character_runs_as_is(self):
        self.assertEqual(card_character({"kind": "action"}, CHARS), ("any", None))


if __name__ == "__main__":
    unittest.main()
