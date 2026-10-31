"""콘텐츠 나가기 공통 틀 (mabi/tasks/exits.Exit)."""
import unittest
from unittest import mock

from mabi.tasks import exits


class Fake(exits.Exit):
    NAME = "테스트"

    def __init__(self, inside_seq, dialog_seq):
        self.inside_seq, self.dialog_seq = iter(inside_seq), iter(dialog_seq)

    def inside(self, bot):
        return next(self.inside_seq, False)

    def dialog(self, bot, timeout):
        return next(self.dialog_seq, None)


def make_bot(loading_after_space=True):
    b = mock.MagicMock()
    b.cfg = {"timing": {"loading": 30}}
    b.ui = {"abyss_exit": "exit"}
    b.exists.side_effect = lambda name, **k: name == "exit"
    b.map_loading.return_value = False
    b.at_main.return_value = True
    b.wait_packet.return_value = loading_after_space
    return b


class ExitTest(unittest.TestCase):
    def test_click_then_space(self):
        b = make_bot()
        self.assertTrue(Fake([True], [None, (10, 20)]).run(b))  # 창 없음 → 아이콘 → 창
        b.click.assert_called_once_with("exit")
        b.key.assert_called_with("space")

    def test_space_ignored_clicks_button(self):
        b = make_bot(loading_after_space=False)
        Fake([True], [(10, 20), (10, 20)]).run(b)  # 창이 떠 있는데 Space 가 안 먹음 → 그 자리 클릭
        b.click.assert_called_once_with((10, 20))

    def test_finished_before_does_not_leave(self):
        f = Fake([True], [])
        f.finished_before = lambda bot: True
        b = make_bot()
        self.assertFalse(f.run(b))
        b.click.assert_not_called()

    def test_outside_kind_does_nothing(self):
        with mock.patch("mabi.place.place", return_value=mock.Mock(kind="Field")):
            self.assertFalse(exits.leave_instance(mock.MagicMock()))


class HousingExitTest(unittest.TestCase):
    """여관 보관함 구역·마이 홈 — 오른쪽 위 나가기. 확인 창 없이 바로 로딩이면 Space 를 누르지 않는다."""

    def test_leaves_without_dialog(self):
        b = make_bot()
        b.ui = {"abyss_exit": "exit", "abyss_exit_dialog": "dlg"}
        inside = iter([True, False])
        with mock.patch.object(exits.HousingExit, "inside", lambda self, bot: next(inside, False)):
            b.map_loading.side_effect = [False, True] + [False] * 50   # 누르자 로딩 시작
            b.wait_loaded.return_value = None
            self.assertTrue(exits.HousingExit().run(b))
        b.click.assert_called_once_with("exit")
        b.key.assert_not_called()

    def test_leave_instance_picks_housing(self):
        for kind in ("HousingInn", "Housing"):
            with mock.patch("mabi.place.place", return_value=mock.Mock(kind=kind)),                     mock.patch.object(exits.HousingExit, "run") as run:
                self.assertTrue(exits.leave_instance(mock.MagicMock()))
                run.assert_called_once()


class HousingPlaceTest(unittest.TestCase):
    def test_cli_housing(self):
        # 패킷이 맵을 모를 때 CLI get_current_environment 의 Housing.IsInHousing 으로
        from mabi import place as P
        b = mock.MagicMock()
        b.map_loading.return_value = None
        b.activity.return_value = {"Dungeon": {"State": "NotInDungeon"}, "Battlefield": {"IsInBattleField": False}}
        b.environment.return_value = {"ChannelDisplayName": "", "Housing": {"IsInHousing": True}}
        self.assertEqual(P.place(b).kind, P.HOUSING)
        b.environment.return_value = {"ChannelDisplayName": "반호르", "Housing": {"IsInHousing": False}}
        self.assertIsNone(P.place(b).kind)


if __name__ == "__main__":
    unittest.main()
