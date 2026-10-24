"""작업 큐(mabi.workqueue) 상태 기계 — 가짜 카드 종류로 돌린다."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from mabi.workqueue import Kind, RemoteKind, WorkQueue


class FakeLong(Kind):
    """숙제 흉내: stop() 이 오면 스스로 멈춘다 (STOP). finish() 로 끝까지 간 것으로."""

    def __init__(self):
        self.started = []
        self.stops = []
        self.removed_items = []
        self._ev = threading.Event()
        self._ok = False

    def run(self, q, it):
        self.started.append(it["id"])
        self._ev.clear()
        self._ev.wait(5)
        if self._ok:
            self._ok = False
            return True
        q.set_stop("stopped")
        return False

    def stop(self, reason):
        self.stops.append(reason)
        self._ev.set()

    def finish(self):
        self._ok = True
        self._ev.set()

    def f12(self):  # 숙제가 스스로 멈춤
        self._ev.set()

    def removed(self, it):
        self.removed_items.append(it["id"])


class FakeQuick(Kind):
    def __init__(self):
        self.ran = []

    def run(self, q, it):
        self.ran.append(it["label"])
        time.sleep(0.02)
        return True


def wait_for(cond, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class WorkQueueTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.events = []
        self.long, self.quick = FakeLong(), FakeQuick()
        self.drained = 0
        self.q = self.make()

    def make(self):
        def drained(q):
            self.drained += 1
        return WorkQueue(self.dir / "queue.json", self.dir / "history.jsonl", lambda ch, v: self.events.append((ch, v)),
                         {"daily": self.long, "action": self.quick, "goal": self.quick}, on_drained=drained)

    def status(self):
        return [(x["label"], x["status"]) for x in self.q.items]

    def test_now_preempts_and_resumes(self):
        # 지금 바로: 돌던 숙제는 대기로, 행동 먼저, 그다음 숙제를 이어서
        self.q.add({"kind": "daily", "label": "숙제"}, "now")
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.q.add({"kind": "action", "label": "채집"}, "now")
        self.assertTrue(wait_for(lambda: self.quick.ran == ["채집"]))
        self.assertEqual(self.long.stops, ["preempt"])
        self.assertTrue(wait_for(lambda: self.long.started == [1, 1]))  # 숙제 다시
        self.long.finish()
        self.assertTrue(wait_for(lambda: not self.q.running and not self.q.items))
        self.assertEqual(self.drained, 1)

    def test_self_stop_pauses_queue(self):
        # F12 로 숙제가 스스로 멈춤 → 일시정지, 뒤 카드는 안 돈다, 큐가 끝난 것도 아니다 (화면 설정 안 되돌림)
        self.q.add({"kind": "daily", "label": "숙제"})
        self.q.add({"kind": "action", "label": "채집"})
        self.q.tick()
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.long.f12()
        self.assertTrue(wait_for(lambda: not self.q.running))
        self.assertEqual(self.status(), [("숙제", "pause"), ("채집", "wait")])
        self.assertEqual(self.quick.ran, [])
        self.assertEqual(self.drained, 0)

    def test_play_all_resumes_paused_first(self):
        self.q.add({"kind": "daily", "label": "숙제"})
        self.q.add({"kind": "action", "label": "채집"})
        self.q.items[0]["status"] = "pause"
        self.q.play_all()
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.assertEqual(self.quick.ran, [])  # 숙제가 먼저
        self.long.finish()
        self.assertTrue(wait_for(lambda: self.quick.ran == ["채집"] and not self.q.running))
        self.assertEqual(self.q.items, [])

    def test_remove_running_card_stops_queue(self):
        self.q.add({"kind": "daily", "label": "숙제"})
        self.q.add({"kind": "action", "label": "채집"})
        self.q.tick()
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.q.remove(1)
        self.assertTrue(wait_for(lambda: not self.q.running))
        self.assertEqual(self.long.stops, ["remove"])
        self.assertEqual(self.quick.ran, [])
        self.assertIn('"result": "removed"', (self.dir / "history.jsonl").read_text(encoding="utf-8"))

    def test_pause_button(self):
        self.q.add({"kind": "daily", "label": "숙제"}, "now")
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.q.pause()
        self.assertTrue(wait_for(lambda: not self.q.running))
        self.assertEqual(self.status(), [("숙제", "pause")])

    def test_preempt_beats_self_stop(self):
        # 밀리는 숙제는 STOP 으로 끝나도(set_stop('stopped')) 일시정지가 아니라 대기 → 이어서
        self.q.add({"kind": "daily", "label": "숙제"}, "now")
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.q.add({"kind": "action", "label": "수령"}, "now")
        self.assertTrue(wait_for(lambda: self.long.started == [1, 1]))
        self.assertEqual(self.q.items[0]["status"], "run")

    def test_replace_paused_and_removed_hook(self):
        self.q.add({"kind": "daily", "label": "옛 숙제"})
        self.q.items[0]["status"] = "pause"
        self.q.add({"kind": "daily", "label": "새 숙제"}, "end", replace_paused=True)
        self.assertEqual([x["label"] for x in self.q.items], ["새 숙제"])
        self.assertEqual(self.long.removed_items, [1])

    def test_saved_and_reloaded(self):
        self.q.add({"kind": "action", "label": "채집", "detail": "1회"})
        self.q.items[0]["status"] = "run"  # 꺼질 때 돌던 것
        self.q._changed()
        q2 = self.make()
        self.assertEqual([(x["label"], x["status"]) for x in q2.items], [("채집", "wait")])
        self.assertEqual(q2.add({"kind": "action", "label": "또"})["id"], 2)

    def test_remote_kind(self):
        sent = []
        remote = RemoteKind(lambda ch, v: sent.append((ch, v)))
        self.q.kinds["goal"] = remote
        self.q.add({"label": "못 10개", "target": 10}, "now")
        self.assertTrue(wait_for(lambda: sent and sent[0][0] == "mm:queue-run"))
        self.q.ui_done(sent[0][1]["id"], {"ok": False, "patch": {"made": 3}, "stop": {"reason": "skill", "what": "은 광석", "level": 5}})
        self.assertTrue(wait_for(lambda: not self.q.running))
        self.assertEqual(self.q.items[0]["status"], "fail")
        self.assertEqual(self.q.items[0]["made"], 3)
        self.assertIn("은 광석", self.q.items[0]["note"])

    def test_remote_abandoned_on_ui_reload(self):
        remote = RemoteKind(lambda ch, v: None)
        self.q.kinds["goal"] = remote
        self.q.add({"label": "못"}, "now")
        self.assertTrue(wait_for(lambda: remote.current is not None))
        self.q.ui_reset()
        self.assertTrue(wait_for(lambda: not self.q.running))
        self.assertEqual(self.q.items[0]["status"], "pause")


if __name__ == "__main__":
    unittest.main()
