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

    def menu_by_text(self, texts):
        b = fake_bot()
        b.exists.return_value = False  # 그림으로는 못 찾음
        ctx = monitor.Ctx("arbeit", "x", menus=True)
        clock = iter(range(0, 1000, 5))
        with mock.patch.object(handlers.sit, "clear_attendance", return_value=None),                 mock.patch("mabi.tasks.dialogue.menu_open", return_value=True),                 mock.patch("mabi.tasks.dialogue.lines_left", return_value=False),                 mock.patch.object(handlers.time, "monotonic", side_effect=lambda: next(clock)),                 mock.patch.object(handlers.ocr, "find_texts", return_value=[(t, 0, 0) for t in texts]):
            return b, handlers.dialog(b, ctx, Seen(d.DIALOG, frame=frame()))

    def test_menu_without_template_uses_button_text(self):
        """메뉴(패킷) + 넘길 대사 없음 + 그림이 안 맞음 → 버튼 글자 '수락' 이 보이면 Space (2026-10-28 09:07)."""
        b, did = self.menu_by_text(["Space", "수락", "나중에 한다"])
        self.assertEqual(did, "수락")
        b.key.assert_called_once_with("space")

    def test_menu_with_other_buttons_waits(self):
        b, did = self.menu_by_text(["Space", "상점", "대화 종료"])
        self.assertEqual(did, "메뉴 버튼 기다림")
        b.key.assert_not_called()

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

    def test_choose_reads_given_region(self):
        """대장간 '수리' 처럼 게시판이 아닌 선택지 줄도 읽는다 (choose_region)."""
        b = fake_bot()
        ctx = monitor.Ctx("repair", choose="수리", choose_region="npc_buttons")
        with mock.patch.object(handlers.ocr, "find_texts", return_value=[("수리", 600, 800)]) as ft,                 mock.patch.object(handlers.gd, "region", side_effect=lambda n: n):
            self.assertEqual(handlers._choose(b, ctx, True), "선택지 '수리'")
        self.assertEqual(ft.call_args[0][1], "npc_buttons")
        b.click.assert_called_once_with((600, 800))
        self.assertTrue(ctx.take("chosen"))


class DeadAfterResultTest(unittest.TestCase):
    def test_dead_with_abyss_result_is_not_dead(self):
        """쓰러진 채로 판이 끝나면(어비스 결과) 쓰러짐이 아니라 화면(클리어·보상)을 본다."""
        b = mock.Mock()
        b.cli.run_limited = False
        b.map_loading.return_value = False
        b.packets.at_charselect.return_value = False
        b.packets.ok = True
        b.packets.state.dead = True
        b.packets.state.abyss_result = 0
        self.assertEqual(d.look(b).what, d.DEAD)
        b.packets.state.abyss_result = 7
        from mabi.monitor import offline
        b.cfg = offline.config()
        b.ui = b.cfg["ui"]
        b.vision.has.return_value = False
        b.skip_button.return_value = None
        b.at_main.return_value = False
        with mock.patch("mabi.tasks.dialogue.in_dialog", return_value=False):
            self.assertNotEqual(d.look(b).what, d.DEAD)


class LeaveTest(unittest.TestCase):
    def leave(self, shown):
        b = fake_bot()
        ctx = monitor.Ctx("repair", leave=True)
        with mock.patch.object(handlers.sit, "clear_attendance", return_value=None),                 mock.patch("mabi.tasks.dialogue.menu_shown", return_value=shown),                 mock.patch("mabi.tasks.dialogue.wait_next", return_value=True),                 mock.patch("mabi.tasks.dialogue.next_line") as nl:
            return b, nl, handlers.dialog(b, ctx, Seen(d.DIALOG, frame=frame()))

    def test_menu_is_closed_with_esc(self):
        """대화를 마칠 때 메뉴는 고르지 않고 ESC('대화 종료')."""
        b, nl, did = self.leave(True)
        self.assertEqual(did, "대화 종료")
        b.key.assert_called_once_with("esc")
        nl.assert_not_called()

    def test_farewell_line_is_skipped(self):
        """작별 인사는 ESC 로 안 넘어간다 → 넘기기."""
        b, nl, did = self.leave(False)
        self.assertEqual(did, "대사 넘김")
        nl.assert_called_once()
        b.key.assert_not_called()

    def test_space_option_is_not_pressed_when_leaving(self):
        self.assertIs(handlers.pick(monitor.Ctx("t", menus=True, leave=True), d.ACCEPT), handlers.dialog)


class QuickNavTabTest(unittest.TestCase):
    def test_selected_tab_has_blue_background(self):
        """퀵 내비게이터는 고른 탭만 진한 색 바탕 (탭마다 색이 다르다) — '주요' 가 아니면 눌러서 바꾼다 (repair.tab_on)."""
        from mabi.tasks.repair import tab_on
        for color in ((118, 179, 13), (219, 176, 29)):  # '주요' 초록 · '설비' 파랑
            f = np.full((400, 1400, 3), (59, 51, 46), np.uint8)
            self.assertFalse(tab_on(f, (786, 248)))
            f[230:268, 730:840] = color
            self.assertTrue(tab_on(f, (786, 248)))


class LoginPopupTest(unittest.TestCase):
    def test_popups_handled_in_any_task(self):
        """접속 직후 창(공지·새 이벤트·스텔라 픽)은 어느 일에서든 처리한다 — 오전 6시 뒤·캐릭터마다 뜰 수도 안 뜰 수도 있다."""
        for what in (d.NOTICE, d.EVENT_POPUP, d.STELLA):
            self.assertIsNotNone(handlers.pick(monitor.Ctx("abyss"), what))

    def test_notice_closed_with_esc(self):
        b = fake_bot()
        with mock.patch.object(d, "look", return_value=Seen(d.NOTICE, hit=(1, 1), frame=frame())):
            self.assertEqual(monitor.Monitor(b).check(monitor.Ctx("t"), guard=False).done, "공지 팝업 닫음")
        b.key.assert_called_with("esc")


class NpcVisitTest(unittest.TestCase):
    """기다리는 중 NPC 가 말을 걸어 옴 (주간 목표 첫 달성 뒤 에반 — 다시 하기 뒤 다음 판 안에서도): 넘기기 버튼이 안 잡혀도
    패킷이 대화 중·메뉴 없음이라면 대사를 넘긴다. 메뉴가 있거나 HUD 가 보이면 누르지 않는다."""
    def _bot(self, menu=False, hud=None):
        b = fake_bot()
        b.ui = {"main_hud": "hud"}
        b.skip_button.return_value = None
        b.behind.return_value = False
        b.packets.ok = True
        b.packets.state.fresh, b.packets.state.in_dialogue, b.packets.state.dialogue_menu = True, True, menu
        b.vision.find.return_value = hud
        return b

    def test_lines_advanced_by_packet(self):
        b = self._bot()
        with mock.patch("mabi.tasks.dialogue.next_line") as nl:
            self.assertEqual(handlers._dialog_blocker(b, Seen(d.DIALOG, frame=frame())), "대사 넘김")
        nl.assert_called_once()

    def test_menu_or_hud_left_alone(self):
        for b in (self._bot(menu=True), self._bot(hud=(1, 1))):
            with mock.patch("mabi.tasks.dialogue.next_line") as nl:
                self.assertIsNone(handlers._dialog_blocker(b, Seen(d.DIALOG, frame=frame())))
            nl.assert_not_called()


class LineReadyTest(unittest.TestCase):
    """대사 넘기기는 대화 창이 그려진 뒤에만 — 패킷은 창이 뜨기 전에 대화 중이라고 한다 (넘기기 칸이 생기기 전에 눌러
    진행이 안 됨, 제보 2026-10-27). '대화 넘기기' 가 보이거나 HUD 가 가려졌을 때 누른다."""
    def _bot(self, skip=None, hud=None):
        b = fake_bot()
        b.ui = {"main_hud": "hud"}
        b.frame.return_value = frame()
        b.skip_button.return_value = skip
        b.vision.find.return_value = hud
        return b

    def test_waits_for_dialog_window(self):
        from mabi.tasks import dialogue
        b = self._bot(hud=(1, 1))  # HUD 가 남음 = 창이 아직
        self.assertFalse(dialogue.next_line(b, ready_within=0))
        b.click.assert_not_called()

    def test_clicks_when_window_up(self):
        from mabi.tasks import dialogue
        for b in (self._bot(skip=("dialog", (1800, 45)), hud=(1, 1)), self._bot()):  # 넘기기 버튼 / HUD 가려짐 (한마디 대사)
            self.assertTrue(dialogue.next_line(b, wait=False))
            b.click.assert_called_once_with((1800, 45))


class InterruptTest(unittest.TestCase):
    """무작위 이벤트 끼어들기 (monitor.interrupts): 패킷 신호 → 하던 일 멈추고 넘김 → 돌아감."""
    def _bot(self, dialog=True, menu=False, owned=False, attending=False):
        b = fake_bot()
        b.packets.ok = True
        s = b.packets.state
        s.in_dialogue, s.dialogue_menu = dialog, menu
        s.attending.return_value = attending
        b.npc_owned.return_value = owned
        b.task_id = "silver"
        return b

    def test_pending(self):
        from mabi.monitor import interrupts
        self.assertEqual(interrupts.pending(self._bot()), "dialog")
        self.assertIsNone(interrupts.pending(self._bot(menu=True)))    # 메뉴가 있는 대화는 태스크 몫
        self.assertIsNone(interrupts.pending(self._bot(owned=True)))   # NPC 대화를 다루는 일 (아르바이트 등)
        self.assertEqual(interrupts.pending(self._bot(dialog=False, attending=True)), "attendance")
        b = self._bot()
        b.packets.ok = False
        self.assertIsNone(interrupts.pending(b))

    def test_handle_until_signal_gone(self):
        from mabi.monitor import interrupts
        b = self._bot()
        mon = mock.Mock()
        calls = []

        def check(ctx, guard=False):
            calls.append(ctx.what)
            if len(calls) == 2:
                b.packets.state.in_dialogue = False  # 대사를 넘겨 대화가 끝남
            return Seen(d.DIALOG, frame=frame(), done="대사 넘김" if len(calls) <= 2 else None)
        mon.check.side_effect = check
        with mock.patch("mabi.monitor.of", return_value=mon):
            self.assertTrue(interrupts.handle(b, "dialog"))
        self.assertEqual(calls[0], "끼어들기 (dialog)")
        b.interrupt_cooldown.assert_not_called()

    def test_gives_up_and_cools_down(self):
        from mabi.monitor import interrupts
        b = self._bot()
        mon = mock.Mock()
        mon.check.return_value = Seen(d.DIALOG, frame=frame())  # 넘기지 못함 (HUD 가 남아 있는 등)
        with mock.patch("mabi.monitor.of", return_value=mon), mock.patch.object(interrupts, "IDLE", 0):
            interrupts.handle(b, "dialog")
        b.interrupt_cooldown.assert_called_once_with("dialog", interrupts.COOLDOWN)


class AttendanceTest(unittest.TestCase):
    """출석: 패킷이 출석 대화 시작을 알리면 '출석부 건너뛰기' 가 뜰 때까지 대사(한두 마디, 무작위)를 넘기고, 뜨면 그것만 누른다."""
    def _bot(self, skip):
        import time
        from mabi.packet_monitor import PacketState
        b = fake_bot()
        b.cfg["login"] = {"attendance_skip": "attendance_skip", "first_dialog_xy": [960, 540]}
        b.ui = {"main_hud": "hud"}
        b.packets.ok = True
        b.packets.state = PacketState(attendance_at=time.monotonic())
        b._attendance_clicked = 0
        b.vision.has.return_value = True
        b.vision.find.side_effect = lambda f, n: skip if n == "attendance_skip" else None
        return b

    def test_lines_then_skip(self):
        from mabi import situation
        b = self._bot(skip=None)
        self.assertEqual(situation.clear_attendance(b, frame()), "출석 대사 넘김")
        b.click.assert_called_with((960, 540))
        self.assertEqual(situation.clear_attendance(b, frame()), "출석 대사 기다림")  # 2초 안엔 다시 누르지 않는다
        b.vision.find.side_effect = lambda f, n: (1800, 45)
        self.assertEqual(situation.clear_attendance(b, frame()), "출석부 건너뛰기")
        b.click.assert_called_with((1800, 45))
        self.assertFalse(b.packets.state.attending())

    def test_detect_attending_before_screens(self):
        b = self._bot(skip=None)
        b.cli.run_limited = False
        b.map_loading.return_value = False
        b.packets.at_charselect.return_value = False
        b.frame.return_value = frame()
        self.assertEqual(d.look(b).what, d.ATTENDANCE)


if __name__ == "__main__":
    unittest.main()
