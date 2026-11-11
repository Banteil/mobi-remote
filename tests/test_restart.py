"""게임 다시 켜기 (mabi/restart) — 연속 실행 제한 창을 보면 큐 맨 위에 카드를 올리고, 끊는 자리에서 하던 카드를 밀어내
다시 켠 뒤 이어 한다. 큐 흐름은 가짜 카드로, 다시 켜는 순서는 가짜 봇으로 본다."""
import itertools
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from mabi import outcome, restart
from mabi.tasks.content import CannotProceed
from mabi.workqueue import Kind, WorkQueue
from gui_app.queue_api import QueueApi

CFG = {"restart": {"auto": True, "launch": "ngm://launch/ -mode:pluglaunch -game:106700", "exit_timeout": 4,
                   "start_timeout": 6}}


def wait_for(cond, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Work(Kind):
    """하던 일: 단계마다 끊는 자리를 지난다 (cutpoint.check → restart.watch → cut_for_timed). 밀리면 멈췄다 이어 한다."""

    def __init__(self, log, popup_at=3):
        self.log, self.popup_at, self.stop_ev = log, popup_at, threading.Event()
        self.popup = False

    def run(self, q, it):
        start = it.get("step", 0)
        self.log.append(f"일 {start}부터")
        for n in range(start, 8):
            if self.stop_ev.is_set():
                self.stop_ev.clear()
                q.set_stop("stopped")
                return False
            q.patch(it["id"], {"step": n}, quiet=True)
            if n == self.popup_at and not self.log.count("다시 켬"):
                self.popup = True  # 판 안에서 창이 뜸 — 이 단계는 끝까지 한다
            if self.popup:  # 끊는 자리: 창을 보면 맨 위에 다시 켜기 → 큐가 밀어낸다
                hook(q)("화면에 연속 실행 제한 창", False)
            q.cut_for_timed()
            time.sleep(0.005)
        self.log.append("일 끝")
        return True

    def stop(self, reason):
        self.stop_ev.set()


class Restart(Kind):
    def __init__(self, log, work):
        self.log, self.work = log, work

    def timed(self, it):
        return True

    def run(self, q, it):
        self.log.append("다시 켬")
        self.work.popup = False
        return True


def hook(q):
    api = mock.Mock()
    api.queue = q
    return lambda why, now: QueueApi._q_restart(api, why, now)


class QueueFlowTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.log = []
        self.work = Work(self.log)
        self.q = WorkQueue(Path(d.name) / "queue.json", Path(d.name) / "history.jsonl", lambda ch, v: None,
                           {"daily": self.work, "restart": Restart(self.log, self.work)})

    def test_restart_cuts_in_and_resumes(self):
        self.q.add({"kind": "daily", "label": "숙제"})
        self.q.add({"kind": "daily", "label": "다음 숙제"})
        self.q.tick()
        self.assertTrue(wait_for(lambda: not self.q.running and not self.q.items))
        # 3단계에서 창 → 그 자리에서 밀려남 → 다시 켬 → 3단계부터 이어 함 → 다음 카드
        self.assertEqual(self.log, ["일 0부터", "다시 켬", "일 3부터", "일 끝", "일 0부터", "일 끝"])

    def test_only_one_restart_card(self):
        q = self.q
        q.add({"kind": "daily", "label": "숙제"})
        with q.lock:
            q.running = True
            q.items[0]["status"] = "run"
        h = hook(q)
        self.assertTrue(h("창", False))
        self.assertTrue(h("창", False))
        self.assertEqual([x["kind"] for x in q.items], ["restart", "daily"])

    def test_idle_queue_is_left_alone(self):  # 큐가 쉬면 사람이 하는 중 — 건드리지 않는다
        self.q.add({"kind": "daily", "label": "숙제"})
        self.assertFalse(hook(self.q)("창", True))
        self.assertEqual([x["kind"] for x in self.q.items], ["daily"])

    def test_failed_restart_pauses_with_reason(self):
        q = self.q

        def fail(q_, it):
            q_.set_stop("stopped", {"note": "게임을 다시 켜지 못함 — x · 게임을 켠 뒤 ▶"})
            return False
        q.kinds["restart"].run = fail
        q.put_first({"kind": "restart", "label": "게임 다시 켜기"})
        q.add({"kind": "daily", "label": "숙제"})
        q.tick()
        self.assertTrue(wait_for(lambda: not q.running))
        self.assertEqual([(x["kind"], x["status"]) for x in q.items], [("restart", "pause"), ("daily", "wait")])
        self.assertIn("다시 켜지 못함", q.items[0]["note"])


class FakeBot:
    def __init__(self, popup=True, window=True, exits_after=1, opens_after=2, needs=1):
        self.cfg, self.ui = CFG, {"title_start": "t", "charselect_title": "c", "main_hud": "m"}
        self.popup, self.on = popup, window
        self.clicks, self.closes, self.calls = [], [], 0
        self.exits_after, self.opens_after, self.needs = exits_after, opens_after, needs
        self.window = mock.Mock()
        self.window.hwnd = 1
        self.window.find.side_effect = lambda: self.on
        self.log = mock.Mock()
        self.launched = False

    def run_limit_popup(self):
        return self.popup and self.on

    def click(self, xy):
        self.clicks.append(xy)

    def sleep(self, a, b=None):
        self.calls += 1
        if len(self.closes) >= self.needs and self.calls >= self.exits_after and not self.launched:
            self.on = False  # 닫기 신호(needs 번) 뒤 꺼짐
        if self.launched and self.calls >= self.opens_after:
            self.on = True

    def exists(self, name):
        return self.on

    def snapshot(self, tag):
        return Path(f"{tag}.png")


class RunTest(unittest.TestCase):
    def run_with(self, bot, character=None, pid=0, force=False):
        kept = []

        def start(link):
            bot.launched, bot.calls = True, 0
        with mock.patch("mabi.tasks.login.current_character", return_value={"slot": 2, "name": "둘"}), \
                mock.patch.object(restart, "_pid", return_value=pid), \
                mock.patch.object(restart, "_close", side_effect=bot.closes.append), \
                mock.patch.object(restart.os, "startfile", side_effect=start) as startfile, \
                mock.patch("mabi.tasks.login.run", return_value="접속 완료") as login:
            out = restart.run(bot, CFG, character, keep=kept.append, force=force)
        return out, kept, startfile, login

    def test_restart(self):
        bot = FakeBot()
        out, kept, startfile, login = self.run_with(bot)
        self.assertEqual(bot.closes, [1])  # 게임 창(hwnd)에 닫기 신호
        self.assertEqual(bot.clicks, [])  # 제한 창의 '종료' 는 누르지 않는다
        startfile.assert_called_once_with(CFG["restart"]["launch"])
        login.assert_called_once_with(bot, CFG, {"slot": 2, "name": "둘"})
        self.assertEqual(kept, [{"slot": 2, "name": "둘"}])
        self.assertIn("다시 켜고", out)

    def test_confirm_takes_second_signal(self):
        # 실제 게임: 첫 신호엔 '게임을 종료하시겠습니까?' 창, 두 번째 신호에 꺼진다 — 3초 뒤 바로 한 번 더
        bot = FakeBot(needs=2)
        with mock.patch.object(restart.time, "monotonic", side_effect=itertools.count()):
            out, kept, startfile, login = self.run_with(bot)
        self.assertEqual(bot.closes, [1, 1])
        startfile.assert_called_once()
        self.assertIn("다시 켜고", out)

    def test_no_popup_only_checks_login(self):
        bot = FakeBot(popup=False)
        out, kept, startfile, login = self.run_with(bot)
        self.assertEqual(bot.closes, [])
        startfile.assert_not_called()
        login.assert_called_once()
        self.assertIn("다시 켜지 않음", out)

    def test_force_without_popup(self):  # 명령(gui.py --restart-game) — 창이 없어도 끄고 다시 켠다 (다른 PC 에서 시험)
        bot = FakeBot(popup=False)
        out, kept, startfile, login = self.run_with(bot, force=True)
        self.assertEqual(bot.closes, [1])
        startfile.assert_called_once()
        login.assert_called_once_with(bot, CFG, {"slot": 2, "name": "둘"})

    def test_game_already_off(self):  # 켜다 실패한 뒤 ▶ — 기억해 둔 캐릭터로
        bot = FakeBot(window=False)
        out, kept, startfile, login = self.run_with(bot, character={"slot": 5, "name": "다섯"})
        self.assertEqual(bot.closes, [])
        startfile.assert_called_once()
        login.assert_called_once_with(bot, CFG, {"slot": 5, "name": "다섯"})

    def test_window_stays(self):
        bot = FakeBot(exits_after=10 ** 6)
        with mock.patch.object(restart.time, "monotonic", side_effect=itertools.count()), \
                self.assertRaisesRegex(CannotProceed, "창이 그대로"):
            self.run_with(bot)
        self.assertEqual(len(bot.closes), restart.CLOSE_TRIES)  # 다시 보내다 포기

    def test_process_lingers_after_window(self):
        # 창은 닫혔는데 프로세스가 늦게 끝남 — 다시 보내지 않고 끝나길 기다린다 (다 끝나기 전에 켜면 '이미 실행 중')
        bot = FakeBot()
        alive = iter([True] * 5 + [False])
        with mock.patch.object(restart, "_alive", side_effect=lambda pid: next(alive)):
            out, kept, startfile, login = self.run_with(bot, pid=7)
        self.assertEqual(bot.closes, [1])
        startfile.assert_called_once()
        self.assertIn("다시 켜고", out)

    def test_process_never_ends(self):
        bot = FakeBot()
        with mock.patch.object(restart, "_alive", return_value=True), \
                mock.patch.object(restart.time, "monotonic", side_effect=itertools.count()), \
                self.assertRaisesRegex(CannotProceed, "프로세스가 끝나지 않음"):
            self.run_with(bot, pid=7)
        self.assertEqual(bot.closes, [1])  # 창이 닫혔으면 다시 보내지 않는다

    def test_game_does_not_start(self):
        bot = FakeBot(window=False, opens_after=10 ** 6)
        with mock.patch.object(restart.os, "startfile", side_effect=lambda link: setattr(bot, "launched", True)), \
                mock.patch.object(restart.time, "monotonic", side_effect=[0, 0, 99]), \
                self.assertRaisesRegex(CannotProceed, "켜지지 않음"):
            restart.run(bot, CFG)


class WatchTest(unittest.TestCase):
    def bot(self, popup, auto=True):
        b = mock.Mock()
        b.cfg = {"restart": {"auto": auto}}
        b.run_limit_popup.return_value = popup
        b.server_down_popup.return_value = False
        return b

    def test_watch(self):
        asked = []
        with mock.patch.object(restart, "_hook", lambda why, now: asked.append(now) or True):
            self.assertFalse(restart.watch(self.bot(popup=False)))
            self.assertFalse(restart.watch(self.bot(popup=True, auto=False)))  # 옵션 창에서 끔
            self.assertTrue(restart.watch(self.bot(popup=True)))
        self.assertEqual(asked, [False])

    def test_escalate_hands_over(self):
        # 창이 떠 있는 채 실패 → 큐가 받으면 실패가 아니라 멈춤 (다시 켠 뒤 그 자리부터)
        b = self.bot(popup=True)
        b.window.find.return_value = True
        b.cli.run_limited = False
        with mock.patch.object(restart, "_hook", lambda why, now: now):
            status, summary = outcome.escalate(b, "FAIL", "x")
        self.assertEqual(status, "STOP")
        self.assertIn("다시 켠 뒤 이어 함", summary)
        with mock.patch.object(restart, "_hook", lambda why, now: False):  # 큐가 쉬는 중 등 — 메모만
            self.assertEqual(outcome.escalate(b, "FAIL", "x")[0], "FAIL")


class KindTest(unittest.TestCase):
    def test_force_only_once(self):
        # 명령 카드(force)는 한 번만 끈다 — 켜다 실패해 사람이 게임을 켜고 ▶ 면 다시 끄지 않고 접속만 확인
        from gui_app.queue_api import RestartKind
        api = mock.Mock()
        api._busy_reason.return_value = None
        it = {"id": 1, "kind": "restart", "force": True}
        q = mock.Mock()
        q.patch.side_effect = lambda id_, d, quiet=False: it.update(d)
        forced = []

        def run(bot, cfg, who, keep, force):
            forced.append(force)
            keep({"slot": 1, "name": "하나"})
            return "ok"
        with mock.patch("gui_app.queue_api.load_config", return_value={}), mock.patch("mabi.bot.Bot"), \
                mock.patch.object(restart, "run", side_effect=run):
            self.assertTrue(RestartKind(api).run(q, it))
            self.assertTrue(RestartKind(api).run(q, it))
        self.assertEqual(forced, [True, False])
        self.assertEqual(it["who"], {"slot": 1, "name": "하나"})


class CommandTest(unittest.TestCase):
    def test_command(self):  # 밖에서 부리기 (gui.py --restart-game) — 시험·원격으로 게임 다시 켜기
        from gui_app.web_main import _command
        self.assertEqual(_command(["gui.py", "--restart-game", "--no-elevate"]), b"restart")

    def test_command_forces(self):  # 명령은 제한 창이 없어도 끄고 다시 켠다 — 다른 PC 에서 시험
        from gui_app.web_main import _on_message
        win, conn = mock.Mock(), mock.Mock()
        conn.readAll.return_value = b"restart"
        _on_message(win, conn)
        spec, where = win.api.queue_add.call_args[0]
        self.assertEqual((spec["kind"], spec["force"], where), ("restart", True, "now"))


if __name__ == "__main__":
    unittest.main()
