"""드릴에서 쓰러지면 — 부활이 없고 못 깬 결과 패킷도 없으니 기다리지 않고 못 깬 것으로, 나가기는 쓰러진 화면의 오른쪽 아래 버튼."""
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.tasks import drill


class DrillDeadTest(unittest.TestCase):
    def test_dead_is_failed_zone(self):
        bot = mock.Mock()
        fight = SimpleNamespace(bot=bot)
        self.assertEqual(drill.ZoneFight.dead_end(fight, None), 0)

    def test_exit_falls_back_to_dead_screen_button(self):
        bot = mock.Mock()
        found = {"drill_result_buttons": None, "drill_dead_buttons": (1625, 1025)}
        region = {k: k for k in found}
        with mock.patch.object(drill.gd, "region", side_effect=lambda k: region[k]), \
             mock.patch.object(drill.ui_text, "wait", side_effect=lambda b, w, r, timeout: found[r]), \
             mock.patch.object(drill.ui_text, "find", side_effect=lambda b, w, r, exact=True: None if exact else found[r]):
            ex = drill.DrillExit()
            hit = ex.dialog(bot, 0)
            self.assertEqual(hit, (1625, 1025))
            ex.confirm(bot, hit)
        bot.click.assert_called_once_with((1625, 1025))
        bot.key.assert_not_called()  # 결과 창 나가기(ESC)가 아니라 버튼을 누른다


if __name__ == "__main__":
    unittest.main()
