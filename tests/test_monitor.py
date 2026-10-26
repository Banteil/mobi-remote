"""점검자(mabi.monitor) — 헛돌기 방지, 모르는 상황, 동작 확인, 메뉴를 다루는 일과 기다리는 중의 정리의 차이."""
import unittest
from unittest import mock

import numpy as np

from mabi import monitor
from mabi.monitor import core, detect as d, handlers
from mabi.monitor.detect import Seen


def fake_bot():
    b = mock.Mock()
    b.cfg = {"arbeit": {"dialog_next_xy": [1800, 45], "report": "report", "accept": "accept"}, "monitor": {}}
    b.shot_dir = None
    b.snapshot.return_value.name = "shot.png"
    b.background = False
    b.packets.ok = False
    return b


def frame(v=0):
    return np.full((100, 100, 3), v, np.uint8)


class GuardTest(unittest.TestCase):
    def test_same_action_same_screen_is_stuck(self):
        """같은 처리를 했는데 화면이 그대로면 누른 게 안 먹은 것 — 끝없이 누르지 않는다."""
        b = fake_bot()
        mon = monitor.Monitor(b)
        ctx = monitor.Ctx("t", menus=True)
        with mock.patch.object(d, "look", return_value=Seen(d.FAREWELL, frame=frame())):
            with self.assertRaises(monitor.Stuck):
                for _ in range(mon.same_limit + 2):
                    mon.check(ctx)
        self.assertEqual(b.click.call_count, mon.same_limit + 1)

    def test_changing_screen_is_not_stuck(self):
        b = fake_bot()
        mon = monitor.Monitor(b)
        ctx = monitor.Ctx("t", menus=True)
        for i in range(mon.same_limit + 3):
            with mock.patch.object(d, "look", return_value=Seen(d.FAREWELL, frame=frame(i * 20 % 250))):
                mon.check(ctx)

    def test_waiting_is_not_stuck(self):
        b = fake_bot()
        b.may_skip_scene.return_value = False  # 던전 중의 연출은 기다린다
        mon = monitor.Monitor(b)
        with mock.patch.object(d, "look", return_value=Seen(d.SCENE, hit=(1, 1), frame=frame())):
            for _ in range(mon.same_limit + 3):
                self.assertEqual(mon.check(monitor.Ctx("t")).done, "연출 대기")
        b.click.assert_not_called()


class UnknownTest(unittest.TestCase):
    def test_unknown_goes_main_once_then_stuck(self):
        b = fake_bot()
        mon = monitor.Monitor(b)
        mon.unknown_limit = 10
        ctx = monitor.Ctx("t")
        clock = [0.0]
        with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())), \
                mock.patch.object(core.time, "monotonic", side_effect=lambda: clock[0]):
            mon.check(ctx)
            clock[0] = 11
            mon.check(ctx)  # 한 번은 메인 화면으로
            b.to_main.assert_called_once()
            clock[0] = 15
            mon.check(ctx)
            clock[0] = 22
            with self.assertRaises(monitor.Stuck):
                mon.check(ctx)

    def test_unknown_again_after_main_is_stuck(self):
        """메인으로 돌린 뒤 태스크가 같은 동작을 해 또 모르는 상황 — 같은 일에서 두 번째면 멈춘다 (2026-10-26 11:22)."""
        b = fake_bot()
        mon = monitor.Monitor(b)
        mon.unknown_limit = 10
        ctx = monitor.Ctx("t")
        clock = [0.0]
        with mock.patch.object(core.time, "monotonic", side_effect=lambda: clock[0]):
            with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())):
                mon.check(ctx)
                clock[0] = 11
                mon.check(ctx)
            with mock.patch.object(d, "look", return_value=Seen(d.MAIN, frame=frame(), idle=True)):
                mon.check(ctx)  # 메인 화면 — 태스크가 진행하기를 다시 누른다
            with mock.patch.object(d, "look", return_value=Seen(d.UNKNOWN, frame=frame())):
                clock[0] = 20
                mon.check(ctx)
                clock[0] = 31
                with self.assertRaises(monitor.Stuck):
                    mon.check(ctx)
        b.to_main.assert_called_once()

    def test_run_limit_raises(self):
        mon = monitor.Monitor(fake_bot())
        with mock.patch.object(d, "look", return_value=Seen(d.RUN_LIMIT, src="cli")):
            with self.assertRaises(RuntimeError):
                mon.check(monitor.Ctx("t"))

    def test_exit_question_untouched(self):
        b = fake_bot()
        with mock.patch.object(d, "look", return_value=Seen(d.EXIT_ASK, frame=frame())):
            self.assertIsNone(monitor.Monitor(b).clear())
        b.key.assert_not_called()
        b.click.assert_not_called()


class ActTest(unittest.TestCase):
    def mon(self):
        m = monitor.Monitor(fake_bot())
        m.settle = mock.Mock(return_value=None)
        return m

    def test_ok(self):
        self.assertTrue(self.mon().act(monitor.Ctx("t"), "x", lambda: True, lambda: True, within=1))

    def test_cannot(self):
        do = mock.Mock(return_value=False)
        self.assertIs(self.mon().act(monitor.Ctx("t"), "x", do, lambda: True, within=1), False)
        do.assert_called_once()  # 할 수 없는 건 다시 하지 않는다

    def test_no_change_retries_then_none(self):
        do = mock.Mock(return_value=True)
        clock = iter(range(0, 1000, 5))
        with mock.patch.object(core.time, "monotonic", side_effect=lambda: next(clock)):
            self.assertIsNone(self.mon().act(monitor.Ctx("t"), "x", do, lambda: False, within=6, tries=2))
        self.assertEqual(do.call_count, 2)


class DialogTest(unittest.TestCase):
    def test_job_presses_accept_when_menu_comes_late(self):
        """메뉴가 늦게 떠도 '수락' 이 보이면 Space — 넘기기를 눌러 수락을 놓치지 않는다 (2026-10-26 10:34)."""
        b = fake_bot()
        b.packets.ok = False
        b.exists.side_effect = lambda n: n == "accept"
        ctx = monitor.Ctx("arbeit", "x", menus=True)
        with mock.patch.object(handlers.sit, "clear_attendance", return_value=None), \
                mock.patch("mabi.tasks.dialogue.menu_open", return_value=True):
            self.assertEqual(handlers.dialog(b, ctx, Seen(d.DIALOG, frame=frame())), "수락")
        b.key.assert_called_once_with("space")

    def test_blocker_does_not_touch_menus(self):
        """기다리는 중의 정리는 NPC 메뉴(수락·결과 보고)를 누르지 않는다."""
        b = fake_bot()
        with mock.patch.object(d, "look", return_value=Seen(d.ACCEPT, hit=(1, 1), frame=frame())):
            self.assertIsNone(monitor.Monitor(b).clear())
        b.key.assert_not_called()

    def test_dungeon_window_finishes_job(self):
        b = fake_bot()
        ctx = monitor.Ctx("arbeit", "x", job=True, finish_on={d.DUNGEON_WINDOW: "dungeon"})
        with mock.patch.object(d, "look", return_value=Seen(d.DUNGEON_WINDOW, frame=frame(), info={"tab": "weekday"})):
            seen = monitor.Monitor(b).check(ctx)
        self.assertEqual(seen.finish.result, "dungeon")


class DeadTest(unittest.TestCase):
    def dead(self, revive, ok):
        b = fake_bot()
        with mock.patch.object(d, "look", return_value=Seen(d.DEAD, src="packet")),                 mock.patch("mabi.tasks.abyss.revive_here", return_value=ok),                 mock.patch("mabi.tasks.content.ensure_auto"):
            return monitor.Monitor(b).check(monitor.Ctx("t", revive=revive), guard=False)

    def test_revives_here(self):
        self.assertEqual(self.dead(True, True).done, "여기서 부활")

    def test_cannot_revive_finishes(self):
        self.assertEqual(self.dead(True, False).finish.result, "dead")

    def test_without_revive_left_to_task(self):
        seen = self.dead(False, True)
        self.assertIsNone(seen.done)
        self.assertIsNone(seen.finish)


class FinishOnTest(unittest.TestCase):
    def test_waited_screen_finishes_without_pressing(self):
        """태스크가 기다리던 화면(어비스 보상 화면)이면 누르지 않고 끝 — 다시 하기·나가기는 태스크가 정한다."""
        b = fake_bot()
        ctx = monitor.Ctx("abyss", finish_on={d.REWARD: "reward"})
        with mock.patch.object(d, "look", return_value=Seen(d.REWARD, hit=(1, 1), frame=frame())):
            self.assertEqual(monitor.Monitor(b).check(ctx).finish.result, "reward")
        b.key.assert_not_called()
        b.click.assert_not_called()


class ChooseTest(unittest.TestCase):
    def test_space_option_is_not_pressed_when_choosing(self):
        """고를 선택지가 따로 있으면 Space(기본 선택지)를 누르지 않는다 — 게시판 선택지가 메뉴 버튼처럼 보여도."""
        self.assertIs(handlers.pick(monitor.Ctx("t", menus=True, choose="골드"), d.REPORT), handlers.dialog)
        self.assertIs(handlers.pick(monitor.Ctx("t", menus=True), d.REPORT), handlers.menu_space)


if __name__ == "__main__":
    unittest.main()
