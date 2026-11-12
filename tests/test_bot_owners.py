"""게임 조작 Bot 의 수명·주인 등록 (gui_app.daily_api.DailyApi._game_bot) — 멈추기와 '다른 일이 도는 중' 판단이 한 곳을 본다.
예전엔 큐 카드(캐릭터 맞추기·각인 강화·게임 다시 켜기)와 화면 설정 되돌리기가 만든 Bot 을 _busy_reason 이 몰라
그 사이에 다른 게임 조작이 시작될 수 있었다."""
import threading
import unittest
from unittest import mock

from gui_app.daily_api import DailyApi


class FakeBot:
    def __init__(self, cfg, paths, force_exit=True):
        self.stopper = mock.Mock()


class Api(DailyApi):
    def __init__(self):
        self.paths = mock.Mock()

    def _daily_hook_log(self):
        pass


class GameBotTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch("mabi.bot.Bot", FakeBot)
        p.start()
        self.addCleanup(p.stop)

    def test_registered_while_held(self):
        api = Api()
        self.assertIsNone(api._busy_reason())
        with api._game_bot("enhance", cfg={}) as bot:
            self.assertIs(api._bots["enhance"], bot)
            self.assertEqual(api._busy_reason(), "각인 강화 반복이 도는 중입니다")
            api._bot_stop("enhance", "먼저 할 카드에 밀림")
            bot.stopper.request.assert_called_once_with("먼저 할 카드에 밀림")
        self.assertEqual(api._bots, {})
        bot.stopper.close.assert_called_once()
        self.assertIsNone(api._busy_reason())
        api._bot_stop("enhance")  # 없으면 아무것도

    def test_closed_on_error_and_unregistered_check(self):
        api = Api()
        with self.assertRaises(ValueError):
            with api._game_bot("char", cfg={}) as bot:
                raise ValueError("x")
        bot.stopper.close.assert_called_once()
        self.assertEqual(api._bots, {})
        with api._game_bot(None, cfg={}):  # 잠깐 보는 확인은 다른 일을 막지 않는다
            self.assertIsNone(api._busy_reason())

    def test_display_restore_thread_is_busy(self):
        api = Api()
        ev = threading.Event()
        api._display_thread = threading.Thread(target=ev.wait, daemon=True)
        api._display_thread.start()
        with mock.patch.object(DailyApi, "_alive", staticmethod(lambda t: bool(t and t.is_alive()))):
            self.assertEqual(api._busy_reason(), "화면 설정 작업 중입니다")
        ev.set()
        api._display_thread.join()
        self.assertIsNone(api._busy_reason())

    def test_repeat_state_per_kind(self):
        api = Api()
        self.assertIsNot(api._rep("abyss"), api._rep("raid"))
        self.assertIs(api._rep("abyss"), api._rep("abyss"))
        with mock.patch.object(DailyApi, "_bot_stop") as stop:
            api.daily_raidStop("까닭")
        stop.assert_called_once_with("raid", "까닭")


class RepeatLaunchTest(unittest.TestCase):
    """어비스·레이드 반복 시작 — 비운 값은 config.default.toml 기본값으로 저장하고, 결과는 RepeatRun.result 에."""

    def setUp(self):
        import json
        import tempfile
        from pathlib import Path

        from mabi.paths import Paths
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.paths = Paths(data=Path(d.name) / "data", resources=Path(__file__).resolve().parent.parent)
        self.paths.data.mkdir(parents=True)
        self.paths.profile.write_text(json.dumps({"slots": [1], "names": {"1": "가"}}), encoding="utf-8")

        class A(DailyApi):
            def _emit(self, *a):
                pass

            def _daily_hook_log(self):
                pass
        self.api = A()
        self.api.paths = self.paths

    def test_defaults_saved_and_start_failure(self):
        from mabi import userconfig
        from mabi.runner import load_config
        with mock.patch("mabi.bot.Bot", side_effect=RuntimeError("창 없음")), mock.patch("gui_app.daily_api.log"):
            self.api._repeat_launch("raid", {"slot": 1, "runs": 2}).join()
        self.assertEqual(self.api._rep("raid").result, {"type": "failed", "message": "창 없음"})
        r = load_config(self.paths)["raid"]
        self.assertEqual((r["raid"], r["difficulty"], r["runs"]),
                         (userconfig.default(self.paths, "raid", "raid"), userconfig.default(self.paths, "raid", "difficulty"), 2))
        self.assertEqual(self.api._bots, {})

    def test_done_result(self):
        events = []
        fake_task = mock.Mock()
        fake_task.repeat.return_value = {"clears": 3}

        class Bot(FakeBot):
            window = mock.Mock(**{"find.return_value": True})
        with mock.patch("mabi.bot.Bot", Bot), mock.patch("importlib.import_module", return_value=fake_task), \
                mock.patch("mabi.queue_report.LootMeter"):
            self.api._repeat_launch("abyss", {"dungeon": "d", "difficulty": "x"}, events.append).join()
        self.assertEqual(self.api._rep("abyss").result, {"type": "done", "clears": 3})
        self.assertEqual([e["type"] for e in events], ["start", "done"])
        self.assertEqual(self.api._bots, {})


if __name__ == "__main__":
    unittest.main()
