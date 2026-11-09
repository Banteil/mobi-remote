"""콘텐츠 가이드 카드 찾기 (mabi.tasks.content.open_guide_card) — 뒤쪽 카드는 목록을 내려가며 글자로 찾는다."""
import types
import unittest
from unittest import mock

import numpy as np

from mabi.tasks import content, ui_text


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
        with mock.patch.object(content, "open_guide"), mock.patch.object(content, "guide_tab"), \
                mock.patch.object(ui_text, "find", fake_find):
            return content.open_guide_card(bot, "뱅가드", weekly=True, text=True)

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


if __name__ == "__main__":
    unittest.main()
