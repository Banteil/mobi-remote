"""드릴에서 쓰러지면 — 부활이 없고 못 깬 결과 패킷도 없으니 기다리지 않고 못 깬 것으로, 나가기는 쓰러진 화면의 오른쪽 아래 버튼."""
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.tasks import drill


class DrillDeadTest(unittest.TestCase):
    def test_dead_is_failed_zone(self):
        bot = mock.Mock()
        fight = SimpleNamespace(bot=bot)
        self.assertEqual(drill.ZoneFight.dead_end(fight, None), drill.DIED)

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


class DrillPlayEndTest(unittest.TestCase):
    """구역이 끝난 까닭과 구역 번호 — 쓰러짐/시간은 문구로 나누고, 번호를 못 읽은 클리어는 도전하던 구역으로."""

    def play(self, results, start=26, goal=20):
        bot = mock.MagicMock()
        bot.cfg = {"drill": {"goal": goal}}
        seq = iter(results)
        with mock.patch.object(drill, "BossSkills"), mock.patch.object(drill, "packet_best", return_value=None), \
                mock.patch.object(drill, "wait_zone", side_effect=lambda b, s: next(seq)), \
                mock.patch.object(drill, "leave") as leave:
            try:
                return drill.play(bot, start), leave
            except drill.CannotProceed as e:
                return str(e), leave

    def test_died(self):
        msg, leave = self.play([drill.DIED])
        self.assertEqual(msg, "26구역에서 쓰러짐 (최고 25구역)")
        leave.assert_called_once()

    def test_time_out(self):
        msg, _ = self.play([drill.FAILED])
        self.assertEqual(msg, "26구역에서 제한 시간 안에 못 깸 (최고 25구역)")

    def test_cleared_without_number_is_current_zone(self):
        msg, _ = self.play([drill.CLEARED, drill.DIED], start=19, goal=21)
        self.assertEqual(msg, "20구역에서 쓰러짐 (최고 19구역)")  # 19구역은 깬 것 — 실패로 나가지 않는다
        msg, _ = self.play([drill.CLEARED, 21], start=20, goal=21)
        self.assertEqual(msg, "21구역까지 클리어 (이번에 2구역)")


class DrillDeadAtLoginTest(unittest.TestCase):
    """접속 때 드릴 안에서 쓰러져 있으면 드릴 나가기로 나온다 (메인 화면으로 가려다 헛돌지 않게)."""

    def test_dead_in_drill_leaves(self):
        from mabi.tasks import login
        b = mock.MagicMock()
        b.is_dead.return_value = True
        with mock.patch("mabi.place.place", return_value=SimpleNamespace(kind=None)), \
                mock.patch.object(drill, "inside", return_value=True), mock.patch.object(drill, "leave") as leave:
            self.assertTrue(login._leave_dungeon(b))
        leave.assert_called_once_with(b)


if __name__ == "__main__":
    unittest.main()
