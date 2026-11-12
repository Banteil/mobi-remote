"""여러 콘텐츠가 같이 쓰는 작은 부품 — 메뉴 열기·도착 기다리기·우연한 만남·버튼 기다리기."""
import unittest
from unittest import mock

from mabi.tasks import content, entry, ui_text


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def fake_bot(clock, **kw):
    bot = mock.Mock()
    bot.map_loading.return_value = False
    bot.sleep.side_effect = lambda *a: setattr(clock, "now", clock.now + (a[0] if a else 1))
    for k, v in kw.items():
        getattr(bot, k).return_value = v
    return bot


class WaitArrivalTest(unittest.TestCase):
    def run_wait(self, bot, clock, visible, **kw):
        with mock.patch.object(content.time, "monotonic", clock):
            return content.wait_arrival(bot, visible, 30, "shot", "못 감", **kw)

    def test_visible(self):
        c = Clock()
        bot = fake_bot(c)
        seen = iter([False, False, True])
        self.assertTrue(self.run_wait(bot, c, lambda: next(seen)))

    def test_stopped_without_window(self):
        c = Clock()
        bot = fake_bot(c, at_main=True, auto_traveling=False)
        self.assertFalse(self.run_wait(bot, c, lambda: False, still=3))
        self.assertEqual(bot.sleep.call_count, 2)  # 세 번째 멈춤에서 바로

    def test_timeout_raises(self):
        c = Clock()
        bot = fake_bot(c, at_main=False, fast_travel=False)
        with self.assertRaises(content.CannotProceed):
            self.run_wait(bot, c, lambda: False, retry_fast=True)
        self.assertGreater(bot.fast_travel.call_count, 1)  # 될 때까지 다시 해 본다

    def test_fast_travel_once(self):
        c = Clock()
        bot = fake_bot(c, fast_travel=True)
        with self.assertRaises(content.CannotProceed):
            self.run_wait(bot, c, lambda: False, retry_fast=True)
        bot.fast_travel.assert_called_once()


class OpenMenuTest(unittest.TestCase):
    def test_retries_until_item_shows(self):
        bot = mock.Mock()
        found = iter([None, (1700, 300), (1700, 300)])
        with mock.patch.object(ui_text, "find", lambda *a, **k: next(found)):
            ui_text.open_menu(bot, "abyss_menu", "메뉴의 어비스", "abyss")
        self.assertEqual([c.args for c in bot.key.call_args_list], [("esc",), ("esc",)])
        bot.clear_blockers.assert_called_once()
        bot.click.assert_called_once_with((1700, 300))

    def test_menu_open_clicks_at_once(self):
        bot = mock.Mock()
        with mock.patch.object(ui_text, "find", return_value=(1700, 300)):
            ui_text.open_menu(bot, "raid_menu", "메뉴의 레이드", "raid", menu_open=True)
        bot.key.assert_not_called()
        bot.click.assert_called_once_with((1700, 300))


class EntryPartsTest(unittest.TestCase):
    def test_chance_turned_on(self):
        bot = mock.Mock()
        states = iter([(False, (900, 800)), (True, (900, 800))])
        with mock.patch.object(entry, "chance", lambda b: next(states)):
            entry.ensure_chance(bot, "abyss")
        bot.click.assert_called_once_with((900, 800))

    def test_chance_missing(self):
        with mock.patch.object(entry, "chance", return_value=None), self.assertRaises(content.CannotProceed):
            entry.ensure_chance(mock.Mock(), "raid")

    def test_wait_button(self):
        bot = mock.Mock()
        got = iter(["", "", "move"])
        self.assertEqual(entry.wait_button(bot, lambda b: next(got)), "move")
        self.assertEqual(entry.wait_button(bot, lambda b: "", tries=2), "")


if __name__ == "__main__":
    unittest.main()
