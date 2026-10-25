"""일요일 요일 던전 — 임무 게시판에서 던전 고르기 (mabi.tasks.weekday). 화면·CLI 는 가짜로 돌린다."""
import logging
import unittest
from unittest import mock

from mabi.tasks import weekday
from mabi.tasks.content import CannotProceed

CHOICES = [("빛나는 동굴(골드)", 667, 996), ("눈부신 저택(보석)", 891, 997), ("찬란한 유적(연금술 재연소 촉매)", 1183, 996)]
C = {"board_next_xy": [960, 900], "board_timeout": 5}


class FakeBot:
    """acts: 차례로 돌려줄 get_activity. 다 쓰면 대화가 끝난 것으로 본다."""

    def __init__(self, acts):
        self.acts = list(acts)
        self.clicks = []
        self.log = logging.getLogger("test")

    def _act(self, act):
        return self.acts.pop(0) if self.acts else {}

    def dialogue_playing(self, act=None):
        return bool((act or {}).get("IsDialoguePlaying"))

    def frame(self):
        return None

    def click(self, xy):
        self.clicks.append(tuple(xy))

    def sleep(self, *a):
        pass

    def snapshot(self, name):
        return mock.Mock(name=name)

    def to_main(self):
        pass


TALK = {"IsDialoguePlaying": True}
SELECT = {"IsDialoguePlaying": True, "IsWaitingForSelection": True}


class SundayChoiceTest(unittest.TestCase):
    def test_slot_overrides_common(self):
        cfg = {"weekday_dungeon": {"sunday": "보석", "sunday_by_slot": {"3": "골드"}}}
        self.assertEqual(weekday.sunday_choice(cfg, 3), "골드")
        self.assertEqual(weekday.sunday_choice(cfg, 1), "보석")
        self.assertEqual(weekday.sunday_choice(cfg, None), "보석")

    def test_unknown_falls_back_to_catalyst(self):
        self.assertEqual(weekday.sunday_choice({"weekday_dungeon": {"sunday": "다이아"}}, 1), "촉매")
        self.assertEqual(weekday.sunday_choice({"weekday_dungeon": {}}, 1), "촉매")


@mock.patch.object(weekday, "in_dialog", lambda bot: False)
@mock.patch("mabi.ocr.find_texts", lambda frame, region: CHOICES)
class BoardTest(unittest.TestCase):
    def test_talk_select_then_close(self):
        # 대사 → (선택 대기) → 촉매 고름 → 마지막 대사 → 대화 끝
        bot = FakeBot([TALK, SELECT, TALK])
        weekday.choose_on_board(bot, C, "촉매")
        self.assertEqual(bot.clicks, [(960, 900), (1183, 996), (960, 900)])

    def test_picks_gold(self):
        bot = FakeBot([SELECT])
        weekday.choose_on_board(bot, C, "골드")
        self.assertEqual(bot.clicks, [(667, 996)])

    def test_closed_before_pick_fails(self):
        with self.assertRaises(CannotProceed):
            weekday.choose_on_board(FakeBot([TALK]), C, "보석")

    def test_never_clicks_other_choice(self):
        # 원하는 낱말이 선택지에 없으면 아무것도 누르지 않고 시간이 다 되면 멈춘다
        bot = FakeBot([SELECT] * 1000)
        with mock.patch.object(weekday.time, "monotonic", side_effect=[0] + [1] * 3 + [99] * 10):
            with self.assertRaises(CannotProceed):
                weekday.choose_on_board(bot, C, "다이아")
        self.assertEqual(bot.clicks, [])


if __name__ == "__main__":
    unittest.main()
