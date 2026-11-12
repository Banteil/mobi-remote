"""실패를 숨기지 않는 장치 — 같은 실패 연달아 멈춤 (runner.FailStreak), 실패 있는 일일 카드는 완료로 치우지 않음."""
import itertools
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.runner import FailStreak


class FailStreakTest(unittest.TestCase):
    def test_same_failure_on_two_characters(self):
        s = FailStreak()
        self.assertFalse(s(1, "login", "FAIL", "클리어 후 화면 정리 실패 (연출) → 20261030_064720_settle.png"))
        self.assertTrue(s(2, "login", "FAIL", "클리어 후 화면 정리 실패 (연출) → 20261030_065026_settle.png"))

    def test_different_reason_or_success_resets(self):
        s = FailStreak()
        s(1, "arbeit", "FAIL", "막힘: 행운의 편지")
        self.assertFalse(s(2, "arbeit", "FAIL", "아르바이트는 진행 상태 확인에 CLI 가 필요함"))
        s(3, "arbeit", "OK", "1개 완료")
        self.assertFalse(s(4, "arbeit", "FAIL", "아르바이트는 진행 상태 확인에 CLI 가 필요함"))

    def test_same_character_twice_is_not_streak(self):
        s = FailStreak()  # 접속을 인터페이스를 맞춘 뒤 한 번 더 하는 경우 — 같은 캐릭터
        s(1, "login", "FAIL", "x")
        self.assertFalse(s(1, "login", "FAIL", "x"))


class DailyCardTest(unittest.TestCase):
    def _run(self, results):
        from gui_app.queue_api import DailyKind
        api = mock.MagicMock()
        api._q_display.return_value = True
        api._busy_reason.return_value = None
        api._q_fit.return_value = None
        api._daily_result = ("done", results)
        k = DailyKind.__new__(DailyKind)
        k.api = api
        q = mock.MagicMock(session={})
        return k.run(q, {"id": 1, "chars": [1]}), q

    def test_failures_keep_card(self):
        ok, q = self._run([("[가] 접속", "FAIL", "x"), ("[나] 접속", "OK", "")])
        self.assertFalse(ok)
        self.assertIn("1건", q.note.call_args[0][1])

    def test_all_ok_done(self):
        ok, _ = self._run([("[가] 접속", "OK", ""), ("[가] 아르바이트", "MANUAL", "가공 필요")])
        self.assertTrue(ok)


class SkippedClickTest(unittest.TestCase):
    """게임 창을 앞으로 못 가져와 누르지 못한 클릭은 조용히 넘기지 않는다 (연달아 5번이면 StepTimeout)."""

    def bot(self, background):
        from mabi.bot import Bot
        b = mock.MagicMock()
        b.background, b.input.dry_run, b._skipped_clicks, b.SKIP_LIMIT = background, False, 0, 5
        b.window.is_foreground.return_value = False
        b._click_skipped = lambda x, y: Bot._click_skipped(b, x, y)
        return b, Bot

    def test_front_task_raises_after_limit(self):
        from mabi.exceptions import StepTimeout
        b, Bot = self.bot(background=False)
        for _ in range(4):
            self.assertFalse(Bot.click_xy(b, 10, 10))
        with self.assertRaises(StepTimeout):
            Bot.click_xy(b, 10, 10)

    def test_background_repeat_keeps_waiting(self):
        b, Bot = self.bot(background=True)
        for _ in range(8):
            self.assertFalse(Bot.click_xy(b, 10, 10))


class DeadlineTest(unittest.TestCase):
    """숙제 하나가 시간 상한을 넘기면 check_stop 이 StepTimeout 을 낸다 (한 번만)."""

    def test_deadline(self):
        import time
        from mabi.bot import Bot
        from mabi.exceptions import StepTimeout
        b = mock.MagicMock()
        b.stopper.stopped.is_set.return_value = False
        b.deadline = time.monotonic() + 60
        Bot.check_stop(b)  # 아직 안 넘음
        b.deadline = time.monotonic() - 1
        with self.assertRaises(StepTimeout):
            Bot.check_stop(b)
        self.assertIsNone(b.deadline)
        Bot.check_stop(b)  # 정리 단계에서 또 터지지 않는다


class LinesLeftTest(unittest.TestCase):
    """'대화 넘기기' 그림이 안 맞아도 CLI 가 넘길 대사가 있다고 하면 대사가 남은 것 (2026-10-30 던컨 앞 7분 멈춤)."""

    def test_cli_when_picture_misses(self):
        from mabi.tasks.dialogue import lines_left
        b = mock.MagicMock()
        b.skip_button.return_value = None
        b.activity.return_value = {"IsDialogueNextAvailable": True, "IsWaitingForSelection": False}
        self.assertTrue(lines_left(b))
        b.activity.return_value = {"IsDialogueNextAvailable": True, "IsWaitingForSelection": True}
        self.assertFalse(lines_left(b))
        b.activity.return_value = None
        self.assertFalse(lines_left(b))


class LeaveDungeonTest(unittest.TestCase):
    """실패한 숙제 뒤 콘텐츠 안에 남지 않는다 (2026-10-30 공물 던전 끼임 뒤 채집 실패) — exits.leave_instance."""

    def test_outside_does_nothing(self):
        from mabi.tasks import exits
        b = mock.MagicMock()
        with mock.patch("mabi.place.place", return_value=SimpleNamespace(kind=None)):
            self.assertFalse(exits.leave_instance(b))
        b.click.assert_not_called()

    def test_inside_exits(self):
        from mabi.place import DUNGEON
        from mabi.tasks import exits
        b = mock.MagicMock()
        b.cfg = {"timing": {"loading": 60}}
        b.map_loading.return_value = False
        b.at_main.return_value = True
        b.ui = {"abyss_exit": "exit", "abyss_exit_dialog": "dialog"}
        b.exists.side_effect = lambda name, **k: name == "exit"  # 나가기 버튼만 보이고 확인 창은 누른 뒤에
        kinds = itertools.chain([DUNGEON, DUNGEON], itertools.repeat(None))  # 자리 보기 → 안 → 나옴
        with mock.patch("mabi.place.place", side_effect=lambda _: SimpleNamespace(kind=next(kinds))):
            self.assertTrue(exits.leave_instance(b))
        b.click.assert_called_once()
        b.key.assert_called_with("space")


class FieldAtLoginTest(unittest.TestCase):
    """접속 때 사냥터 안이면 사냥 퀘스트가 있을 때만 클리어를 기다린다 — 채집이나 사냥터 안 던전을 마치고 나와 있는
    사냥터는 판이 아니다 (2026-11-03 페카 공물 던전에서 나와 센마이 평원에 남은 채 다음 캐릭터 접속 → 40분씩 기다림)."""

    def leave(self, hunt, task=None):
        from mabi.tasks import login
        b = mock.MagicMock()
        b.cfg = {"black_hole": {"space_keyword": "검은 구멍"}, "silver": {"field_timeout": 2400},
                 "weekday_dungeon": {}}
        b.character = {"slot": 1}
        b.daily.progress.return_value = {"task": task, "slot": 1}
        b.exists.return_value = False
        here = SimpleNamespace(kind=None, in_field=True)
        with mock.patch("mabi.place.place", return_value=here),                 mock.patch("mabi.tasks.space.game_space", return_value="센마이 평원"),                 mock.patch("mabi.tasks.space.hunt_quest", return_value=hunt),                 mock.patch("mabi.tasks.space.dungeon_state", return_value="NotInDungeon"),                 mock.patch("mabi.tasks.dungeon.wait_field") as wf:
            login._leave_dungeon(b)
        return wf.called

    def test_gathering_in_field_does_not_wait(self):
        self.assertFalse(self.leave(""))
        self.assertFalse(self.leave("", task="silver"))  # 퀘스트가 없다고 확실히 나오면 판이 아니다

    def test_hunt_quest_waits(self):
        self.assertTrue(self.leave("센마이 평원 사냥 (0/1)"))

    def test_unknown_quest_waits_only_for_cut_silver(self):
        self.assertTrue(self.leave(None, task="silver"))
        self.assertFalse(self.leave(None, task="daily_mission"))


class RecheckDailyTest(unittest.TestCase):
    """일일 미션 중에 음식을 먹어 '꼬르륵' 이 막 끝나 선물이 남은 채 확인 → '아직 남음'. 마지막 선물 받기로
    다 받았으면 완료로 고친다 (2026-11-03 일일 카드 실패)."""

    def recheck(self, status, verified):
        from mabi.runner import Runner
        r = Runner.__new__(Runner)
        r._emit = mock.MagicMock()
        state = mock.MagicMock()
        results = [("[가] 일일 미션", status, "선물 10개, 미완료: 꼬르륵(음식 2개 먹기 1/2) — 확인 결과 아직 남음")]
        with mock.patch.dict("mabi.tasks.VERIFY", {"daily_mission": lambda b, c: verified}):
            r._recheck_daily(None, {}, state, 3, results, {"daily_mission": (0, status)})
        return results[0][1], state

    def test_fixed_after_leftover_gifts(self):
        status, state = self.recheck("CHECK", True)
        self.assertEqual(status, "OK")
        state.set.assert_called_once_with(3, "daily_mission", "done")

    def test_still_left_or_other_status(self):
        self.assertEqual(self.recheck("CHECK", False)[0], "CHECK")
        self.assertEqual(self.recheck("FAIL", True)[0], "FAIL")  # 실패는 선물로 고치지 않는다


if __name__ == "__main__":
    unittest.main()
