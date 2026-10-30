"""인터페이스 PC·80% 맞추기 (display.InterfaceFit) — 일일 숙제·반복 공통. 맞췄을 때만 on_fit."""
import unittest
from unittest import mock

from mabi.tasks import display


class InterfaceFitTest(unittest.TestCase):
    def bot(self, in_game=True):
        b = mock.MagicMock()
        b.in_game.return_value = in_game
        return b

    def test_once_and_on_fit(self):
        fits = []
        f = display.InterfaceFit(mock.MagicMock(), on_fit=lambda: fits.append(1))
        with mock.patch.object(display, "busy", return_value=""), mock.patch.object(display, "prepare_interface", return_value="ok") as p:
            self.assertTrue(f.attempt(self.bot()))
            self.assertFalse(f.attempt(self.bot()))
        p.assert_called_once()
        self.assertEqual(fits, [1])

    def test_waits_outside_game_or_busy(self):
        f = display.InterfaceFit(mock.MagicMock())
        self.assertFalse(f.attempt(self.bot(in_game=False)))
        with mock.patch.object(display, "busy", return_value="어비스 안"):
            self.assertFalse(f.attempt(self.bot()))
        with mock.patch.object(display, "prepare_interface", return_value="ok"):
            self.assertTrue(f.attempt(self.bot(in_game=False), after_login=True))

    def test_failure_no_on_fit(self):
        fits = []
        f = display.InterfaceFit(mock.MagicMock(), on_fit=lambda: fits.append(1))
        with mock.patch.object(display, "busy", return_value=""), \
                mock.patch.object(display, "prepare_interface", side_effect=display.DisplayFixFailed("x")):
            self.assertTrue(f.attempt(self.bot()))
        self.assertEqual(fits, [])

    def test_disabled(self):
        self.assertFalse(display.InterfaceFit(mock.MagicMock(), enabled=False).attempt(self.bot(), after_login=True))


if __name__ == "__main__":
    unittest.main()
