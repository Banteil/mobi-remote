"""일요일 요일 던전 — 임무 게시판에서 던전 고르기 (mabi.tasks.weekday). 화면·CLI 는 가짜로 돌린다."""
import unittest
from unittest import mock

import numpy as np

from mabi.monitor import detect as d
from mabi.monitor.detect import Seen
from mabi.tasks import weekday
from mabi.tasks.content import CannotProceed

CHOICES = [("빛나는 동굴(골드)", 667, 996), ("눈부신 저택(보석)", 891, 997), ("찬란한 유적(연금술 재연소 촉매)", 1183, 996)]
C = {"board_timeout": 5}


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


def board_bot(acts):
    """acts: 점검자가 볼 때마다 차례로 쓰는 get_activity. 다 쓰면 대화가 끝난 메인 화면."""
    b = mock.Mock()
    b.cfg = {"arbeit": {"dialog_next_xy": [1800, 45]}, "monitor": {}}
    b.shot_dir, b.packets.ok, b.character = None, False, None
    seq, now = list(acts), {"act": {}}

    def look(bot, frame=None, skip=(), ocr=False):
        now["act"] = seq.pop(0) if seq else {}
        return Seen(d.DIALOG if now["act"] else d.MAIN, frame=np.zeros((10, 10, 3), np.uint8))

    b._act.side_effect = lambda a: now["act"]
    b.dialogue_playing.side_effect = lambda a=None: bool(now["act"])
    b.clicks = lambda: [c.args[0] for c in b.click.call_args_list]
    return b, look


NEXT = (1800, 45)


@mock.patch.object(weekday, "in_dialog", lambda bot: False)
@mock.patch("mabi.tasks.dialogue.menu_shown", lambda bot: None)  # 패킷 없음 → CLI 선택 대기로
@mock.patch("mabi.ocr.find_texts", lambda frame, region: CHOICES)
@mock.patch("mabi.situation.clear_attendance", lambda bot, frame=None: None)
class BoardTest(unittest.TestCase):
    """게시판 고르기는 점검자(Ctx.choose)가 한다 — 대사는 넘기고, 원하는 선택지만 누른다."""

    def board(self, acts, want):
        b, look = board_bot(acts)
        with mock.patch.object(d, "look", side_effect=look):
            weekday.choose_on_board(b, C, want)
        return b.clicks()

    def test_talk_select_then_close(self):
        # 대사 → (선택 대기) → 촉매 고름 → 마지막 대사 → 대화 끝
        self.assertEqual(self.board([TALK, SELECT, TALK], "촉매"), [NEXT, (1183, 996), NEXT])

    def test_picks_gold(self):
        self.assertEqual(self.board([SELECT], "골드"), [(667, 996)])

    def test_closed_before_pick_fails(self):
        with self.assertRaises(CannotProceed):
            self.board([TALK], "보석")

    def test_never_clicks_other_choice(self):
        # 원하는 낱말이 선택지에 없으면 아무것도 누르지 않고 시간이 다 되면 멈춘다
        b, look = board_bot([SELECT] * 1000)
        clock = iter(range(0, 10000))
        with mock.patch.object(d, "look", side_effect=look),                 mock.patch.object(weekday.time, "monotonic", side_effect=lambda: next(clock)):
            with self.assertRaises(CannotProceed):
                weekday.choose_on_board(b, C, "다이아")
        self.assertEqual(b.clicks(), [])


if __name__ == "__main__":
    unittest.main()
