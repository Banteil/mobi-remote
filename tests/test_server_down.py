"""게임 서버 연결 끊김 (점검 등) — 창을 알아보고(bot.server_down_shown) 게임을 끈 뒤 작업 큐를 일시정지한다
(restart.server_down · 점검자 처리기 · outcome.escalate). 창 화면은 tests/fixtures/screens/server_down 에도 있다 (저장소 밖)."""
import contextlib
import itertools
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from mabi import bot as botmod, restart
from mabi.exceptions import StopRequested
from mabi.monitor import detect as d, handlers
from mabi.workqueue import Kind, WorkQueue

TEXTS = ("게임 서버와 연결이 끊어졌습니다.", "잠시 후 다시 접속해주세요.", "(ERROR 83)")  # 2026-11-12 06:13 화면을 읽은 그대로


def popup_frame(green=True, panel=True):
    """1920x1080 화면에 끊김 창 모양 (2026-11-12 캡처의 자리·색)."""
    f = np.zeros((1080, 1920, 3), np.uint8)
    f[:] = (90, 120, 60)
    if panel:
        f[357:722, 653:1266] = (51, 39, 34)  # 어두운 창 바탕
    if green:
        f[609:685, 694:1226] = (121, 180, 18)  # 넓은 초록 '확인'
    return f


class ShownTest(unittest.TestCase):
    def shown(self, frame, texts=TEXTS):
        with mock.patch("mabi.ocr.find_texts", return_value=[(t, 960, 450) for t in texts]) as ocr:
            return botmod.server_down_shown(frame), ocr.called

    def test_popup(self):
        self.assertEqual(self.shown(popup_frame()), (True, True))

    def test_other_text(self):  # 같은 꼴이라도 글자가 다르면 아니다
        self.assertEqual(self.shown(popup_frame(), ("퀘스트 완료",)), (False, True))

    def test_colors_first(self):  # 색이 안 맞으면 글자는 읽지도 않는다 — 점검자가 상황마다 부른다
        self.assertEqual(self.shown(popup_frame(green=False)), (False, False))
        self.assertEqual(self.shown(popup_frame(panel=False)), (False, False))  # 다른 화면의 넓은 초록 버튼

    def test_look_sees_it_before_main(self):  # HUD 가 보인 채로 떠도 메인 화면보다 먼저
        b = mock.MagicMock()
        b.map_loading.return_value = None
        b.packets.at_charselect.return_value = None
        b.packets.ok = False
        with mock.patch.object(botmod, "server_down_shown", return_value=True):
            self.assertEqual(d.look(b, popup_frame()).what, d.SERVER_DOWN)


class FakeBot:
    """닫기 신호를 needs 번 받으면 꺼지는 게임. space_closes 면 '확인'(Space)에 꺼진다."""

    def __init__(self, needs=1, space_closes=False):
        self.cfg = {"restart": {"exit_timeout": 4}}
        self.on, self.closes, self.keys = True, [], []
        self.needs, self.space_closes = needs, space_closes
        self.window = mock.Mock(hwnd=1)
        self.window.find.side_effect = lambda: self.on
        self.log, self.stopper = mock.Mock(), mock.Mock()

    def key(self, k):
        self.keys.append(k)

    def sleep(self, a, b=None):
        if len(self.closes) >= self.needs or (self.space_closes and self.keys):
            self.on = False

    def snapshot(self, tag):
        return Path(f"{tag}.png")


def patched(bot):
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(restart, "_pid", return_value=0))
    stack.enter_context(mock.patch.object(restart, "_close", side_effect=bot.closes.append))
    stack.enter_context(mock.patch.object(restart.time, "monotonic", side_effect=itertools.count()))
    return stack


class ServerDownTest(unittest.TestCase):
    def down(self, bot):
        notes = []
        with patched(bot), mock.patch.object(restart, "_pause", notes.append):
            out = restart.server_down(bot)
        return out, notes

    def test_closes_and_pauses(self):
        bot = FakeBot(needs=2)  # 실제 게임: 첫 신호엔 '게임을 종료하시겠습니까?', 두 번째에 꺼짐
        out, notes = self.down(bot)
        self.assertEqual(bot.closes, [1, 1])
        self.assertEqual(bot.keys, [])  # 창의 '확인' 은 먼저 누르지 않는다
        self.assertEqual((out, notes), (restart.DOWN_NOTE, [restart.DOWN_NOTE]))
        bot.stopper.request.assert_called_once_with(restart.DOWN_NOTE)  # 뒤이어 무엇을 하려 해도 멈춘다

    def test_confirm_when_signal_ignored(self):  # 닫기 신호로 안 닫히면 '확인'(Space) 뒤 다시
        bot = FakeBot(needs=10 ** 6, space_closes=True)
        out, notes = self.down(bot)
        self.assertEqual(len(bot.closes), restart.CLOSE_TRIES)
        self.assertEqual(bot.keys, ["space"])
        self.assertEqual(notes, [restart.DOWN_NOTE])

    def test_cannot_close(self):  # 그래도 안 꺼지면 메모를 남기고 멈추기는 한다
        bot = FakeBot(needs=10 ** 6)
        out, notes = self.down(bot)
        self.assertEqual(len(bot.closes), 2 * restart.CLOSE_TRIES)
        self.assertIn("끄지 못함", out)
        self.assertEqual(notes, [out])
        bot.stopper.request.assert_called_once_with(out)

    def test_handler_stops_the_task(self):
        ctx = mock.Mock(choose=None, leave=False)
        with mock.patch.object(restart, "server_down", return_value="메모") as down, self.assertRaises(StopRequested):
            handlers.pick(ctx, d.SERVER_DOWN)(mock.Mock(), ctx, None)
        down.assert_called_once()


class QueueTest(unittest.TestCase):
    def test_card_pauses_with_note(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bot = FakeBot()

        class Work(Kind):
            def run(self, q, it):
                try:
                    handlers.server_down(bot, None, None)
                except StopRequested:
                    q.set_stop("stopped")  # 카드가 멈춤(STOP)을 받으면 하는 것 — 앞서 남긴 메모를 덮지 않는다
                return False

        q = WorkQueue(Path(tmp.name) / "queue.json", Path(tmp.name) / "history.jsonl", lambda ch, v: None, {"daily": Work()})
        q.add({"kind": "daily", "label": "어비스"})
        q.add({"kind": "daily", "label": "다음 카드"})
        # gui_app/queue_api 가 거는 것과 같은 일시정지 고리
        with patched(bot), mock.patch.object(restart, "_pause", lambda note: q.set_stop("stopped", {"note": note})):
            q.tick()
            end = time.time() + 5
            while q.running and time.time() < end:
                time.sleep(0.01)
        self.assertEqual([(x["label"], x["status"]) for x in q.items], [("어비스", "pause"), ("다음 카드", "wait")])
        self.assertEqual(q.items[0]["note"], restart.DOWN_NOTE)


if __name__ == "__main__":
    unittest.main()
