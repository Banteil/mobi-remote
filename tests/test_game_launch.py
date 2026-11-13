"""'게임이 실행되어 있지 않습니다' 알림의 '게임 켜기' (Api.game_launch) — 다시 켜기와 같은 링크만 연다."""
import unittest
from unittest import mock

from gui_app import control
from gui_app.api import Api

CFG = {"restart": {"launch": "ngm://launch/ -mode:pluglaunch -game:106700"}}


class GameLaunchTest(unittest.TestCase):
    def setUp(self):
        self.api = Api.__new__(Api)
        self.api.paths = None
        p = mock.patch("mabi.runner.load_config", return_value=CFG)
        p.start()
        self.addCleanup(p.stop)

    def test_opens_launch_link_when_game_off(self):
        with mock.patch.object(Api, "game_window", return_value=False), \
                mock.patch("mabi.restart.os.startfile") as start:
            self.assertEqual(self.api.game_launch(), {"ok": True})
        start.assert_called_once_with(CFG["restart"]["launch"])

    def test_does_not_open_twice(self):
        with mock.patch.object(Api, "game_window", return_value=True), \
                mock.patch("mabi.restart.os.startfile") as start:
            self.assertEqual(self.api.game_launch(), {"ok": True, "already": True})
        start.assert_not_called()

    def test_launch_error_is_reported(self):
        with mock.patch.object(Api, "game_window", return_value=False), \
                mock.patch("mabi.restart.os.startfile", side_effect=OSError("링크 없음")):
            r = self.api.game_launch()
        self.assertFalse(r["ok"])
        self.assertIn("링크 없음", r["message"])


class CardKindTest(unittest.TestCase):
    def test_screen_goal_card_has_kind(self):
        # 화면의 목표 버튼으로 만든 카드는 kind 칸이 없다 — 큐와 같은 기본 종류로 알린다
        self.assertEqual(control._card({"id": 1, "label": "밥", "status": "wait"})["kind"], "goal")
        self.assertEqual(control._card({"id": 2, "kind": "abyss"})["kind"], "abyss")


if __name__ == "__main__":
    unittest.main()
