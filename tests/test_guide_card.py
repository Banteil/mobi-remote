"""콘텐츠 가이드에서 콘텐츠로 가기 (mabi.tasks.guide) — 위쪽 달성 칸의 글자가 먼저, 안 되면 카드 (뒤쪽 카드는 목록을 내려가며)."""
import types
import unittest
from unittest import mock

import numpy as np

from mabi.tasks import guide, ui_text


class FakeBot:
    """scrolls 번 내린 뒤에야 카드 제목이 보이는 가이드. 목록은 limit 번까지만 내려간다 (그 뒤로는 화면이 그대로)."""

    def __init__(self, shows_at=None, limit=3, button=True):
        self.shows_at, self.limit, self.button = shows_at, limit, button
        self.pos = 0
        self.clicked, self.mained = [], 0
        self.ui = {"guide_go": "guide_go"}

    def scroll(self, x, y, notches):
        if notches < 0:
            self.pos = min(self.limit, self.pos + 1)
        else:
            self.pos = 0

    def sleep(self, *a):
        pass

    def frame(self):
        return np.full((1080, 1920, 3), self.pos * 40, dtype=np.uint8)

    def visible(self):
        return self.shows_at is not None and self.pos >= self.shows_at

    def find_all(self, name):
        return [types.SimpleNamespace(x=900, y=900)] if self.visible() and self.button else []

    def click(self, at):
        self.clicked.append(at)

    def to_main(self):
        self.mained += 1


def fake_find(bot, want, region=None, exact=True):
    return (500, 700) if bot.visible() else None


class OpenGuideCardTest(unittest.TestCase):
    def open(self, bot):
        with mock.patch.object(guide, "open_guide"), mock.patch.object(guide, "guide_tab"), \
                mock.patch.object(ui_text, "find", fake_find):
            return guide.open_guide_card(bot, "뱅가드", weekly=True, text=True)

    def test_found_on_first_screen(self):
        bot = FakeBot(shows_at=0)
        self.assertTrue(self.open(bot))
        self.assertEqual(bot.pos, 0)
        self.assertEqual(len(bot.clicked), 1)

    def test_scrolls_down_to_later_card(self):
        # 주간 콘텐츠가 다 남은 캐릭터 — 뱅가드 브리치는 6번째 카드라 아래로 내려야 보인다
        bot = FakeBot(shows_at=2)
        self.assertTrue(self.open(bot))
        self.assertEqual(bot.pos, 2)
        self.assertEqual(len(bot.clicked), 1)

    def test_no_card_after_bottom(self):
        bot = FakeBot(shows_at=None, limit=2)
        self.assertFalse(self.open(bot))
        self.assertEqual(bot.clicked, [])
        self.assertEqual(bot.mained, 1)

    def test_title_without_button_keeps_scrolling(self):
        # 제목만 보이고 '바로 가기' 가 아래로 잘렸으면 누르지 않는다
        bot = FakeBot(shows_at=1, button=False)
        self.assertFalse(self.open(bot))
        self.assertEqual(bot.clicked, [])


class GoalBot:
    """위쪽 주간 달성 칸 글자 하나만 그린 화면. white: 하얀 글자(아니면 회색), check: 아이콘 모서리 초록 체크."""
    X, Y = 1549, 257

    def __init__(self, white, check):
        self.cfg = {"guide": {"daily_panel": [385, 125, 520, 180], "weekly_panel": [907, 125, 768, 180]}}
        f = np.full((1080, 1920, 3), 30, dtype=np.uint8)
        f[self.Y - 3:self.Y + 4, self.X - 30:self.X + 30] = 255 if white else 100
        if check:
            f[self.Y + 5:self.Y + 15, self.X - 60:self.X - 50] = (60, 200, 60)  # BGR 초록
        self.f = f

    def frame(self):
        return self.f


class GuideGoalTest(unittest.TestCase):
    def goal(self, bot):
        with mock.patch.object(ui_text, "find", lambda b, want, region=None, exact=True: (GoalBot.X, GoalBot.Y)):
            return guide.guide_goal(bot, "뱅가드 브리치", weekly=True)

    def test_white_is_not_done(self):
        self.assertIs(self.goal(GoalBot(white=True, check=False)).done, False)

    def test_grey_with_check_is_done(self):
        self.assertIs(self.goal(GoalBot(white=False, check=True)).done, True)

    def test_mismatch_is_unknown(self):
        self.assertIsNone(self.goal(GoalBot(white=True, check=True)).done)
        self.assertIsNone(self.goal(GoalBot(white=False, check=False)).done)

    def test_missing(self):
        with mock.patch.object(ui_text, "find", lambda *a, **k: None):
            self.assertIsNone(guide.guide_goal(GoalBot(True, False), "뱅가드 브리치", weekly=True))


class GoFromGuideTest(unittest.TestCase):
    def go(self, goal, closes=True, card=True):
        bot = mock.Mock()
        bot.ui = {"guide_title": "guide_title"}
        bot.exists.return_value = not closes  # 눌렀는데 가이드 제목이 그대로 = 안 넘어감
        with mock.patch.object(guide, "open_guide"), mock.patch.object(guide, "guide_goal", return_value=goal), \
                mock.patch.object(guide, "open_guide_card", return_value=card) as by_card:
            got = guide.go_from_guide(bot, "뱅가드 브리치", weekly=True, card="뱅가드", text=True)
        return got, bot, by_card

    def test_white_goal_clicked(self):
        got, bot, by_card = self.go(guide.Goal(1549, 257, False))
        self.assertTrue(got)
        bot.click.assert_called_once_with((1549, 257))
        by_card.assert_not_called()

    def test_done_goal(self):
        got, bot, by_card = self.go(guide.Goal(1549, 257, True))
        self.assertFalse(got)
        bot.click.assert_not_called()
        by_card.assert_not_called()

    def test_falls_back_to_card(self):
        # 달성 칸에서 못 읽음 · 색과 체크가 어긋남 · 눌러도 가이드가 그대로 → 아래 카드 (이미 열린 가이드에서)
        for goal, closes in ((None, True), (guide.Goal(1549, 257, None), True), (guide.Goal(1549, 257, False), False)):
            got, bot, by_card = self.go(goal, closes=closes)
            self.assertTrue(got)
            by_card.assert_called_once_with(bot, "뱅가드", opened=True, weekly=True, text=True)


if __name__ == "__main__":
    unittest.main()
