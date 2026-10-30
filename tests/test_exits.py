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


if __name__ == "__main__":
    unittest.main()
