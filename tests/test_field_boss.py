"""필드 보스 — 열린 시간 계산과, 열린 시간이 아닌 카드를 작업 큐가 비켜 두는 것."""
import datetime as dt
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

from mabi import cutpoint, tasks
from mabi.tasks import field_boss as fb
from mabi.workqueue import Kind, WorkQueue


def at(h, m=0):
    return dt.datetime(2026, 11, 9, h, m)


class WindowTest(unittest.TestCase):
    def test_open_and_left(self):
        self.assertEqual(fb.window(at(12, 0))[0], 30 * 60)
        self.assertEqual(fb.window(at(18, 26))[0], 4 * 60)
        self.assertEqual(fb.window(at(22, 29))[0], 60)

    def test_closed_gives_next(self):
        self.assertEqual(fb.window(at(12, 30)), (0, at(18)))
        self.assertEqual(fb.window(at(9, 0)), (0, at(12)))
        self.assertEqual(fb.window(at(23, 0)), (0, dt.datetime(2026, 11, 10, 12)))

    def test_not_ready(self):
        self.assertEqual(fb.not_ready(at(20, 5)), "")
        self.assertIn("18:00", fb.not_ready(at(13, 0)))
        self.assertIn("곧 닫힘", fb.not_ready(at(20, 27)))  # 4분 안 남음 — 새 캐릭터는 시작하지 않는다
        self.assertIn("22:00", fb.not_ready(at(20, 27)))

    def test_only_field_boss_cards_wait(self):
        # 다른 숙제가 섞여 있으면 그 숙제는 한다 (필드 보스 몫만 그 안에서 넘긴다)
        orig = tasks.READY["field_boss"]
        tasks.READY["field_boss"] = lambda: "닫힘"
        try:
            self.assertEqual(tasks.not_ready(["field_boss"]), "닫힘")
            self.assertEqual(tasks.not_ready(["drill", "field_boss"]), "")
            self.assertEqual(tasks.not_ready(["drill"]), "")
        finally:
            tasks.READY["field_boss"] = orig
        self.assertTrue(tasks.timed(["field_boss"]))
        self.assertFalse(tasks.timed(["drill", "field_boss"]))
        self.assertFalse(tasks.timed(None))


class SafeTest(unittest.TestCase):
    """끊어도 되는 곳 — 마을·일반 필드만. 따로 들어가는 곳·로딩·매칭·쓰러짐·모름은 아님."""

    def bot(self, ok=True, **st):
        s = types.SimpleNamespace(**{"loading": False, "channel_type": "Field", "abyss_matching": 0, "dead": False, **st})
        return types.SimpleNamespace(packets=types.SimpleNamespace(ok=ok, state=s))

    def test_safe(self):
        self.assertTrue(cutpoint.safe(self.bot()))
        for t in ("BattleField", "FieldBoss", "InstanceDungeon", "InstanceAbyssDungeon", "InstanceDimension",
                  "InstanceRaidLobby", None):
            self.assertFalse(cutpoint.safe(self.bot(channel_type=t)), t)
        self.assertFalse(cutpoint.safe(self.bot(loading=True)))
        self.assertFalse(cutpoint.safe(self.bot(abyss_matching=2)))
        self.assertFalse(cutpoint.safe(self.bot(dead=True)))
        self.assertFalse(cutpoint.safe(self.bot(ok=False)))

    def test_check_calls_hook_only_when_safe(self):
        calls = []
        cutpoint.set_hook(lambda: calls.append(1) or "")
        try:
            cutpoint.check(self.bot(), "arbeit_go")
            cutpoint.check(self.bot(channel_type="InstanceDungeon"), "dungeon_reward")
            cutpoint.check(self.bot(), "abyss_match")  # 입장을 누른 뒤 단계
            self.assertEqual(calls, [1])
        finally:
            cutpoint.set_hook(None)


class Timed(Kind):
    """open 이 False 면 준비 안 됨. 돌면 이름을 적는다."""

    def __init__(self):
        self.open, self.ran = False, []

    def ready(self, it):
        return "" if self.open or it.get("label") != "필보" else "열린 시간이 아님"

    def run(self, q, it):
        self.ran.append(it["label"])
        return True


class QueueSkipTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.k = Timed()
        self.q = WorkQueue(Path(d.name) / "q.json", Path(d.name) / "h.jsonl", lambda ch, v: None, {"daily": self.k})

    def wait_for(self, cond, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_closed_card_steps_aside_then_runs(self):
        self.q.add({"kind": "daily", "label": "필보"})
        self.q.add({"kind": "daily", "label": "어비스"})
        self.q.tick()
        self.assertTrue(self.wait_for(lambda: self.k.ran == ["어비스"]))  # 위 카드가 닫혀 있어 아래부터
        self.assertEqual(self.q.items[0]["note"], "열린 시간이 아님")
        self.assertTrue(self.q.running)  # 열리길 기다린다
        self.k.open = True
        self.assertTrue(self.wait_for(lambda: self.k.ran == ["어비스", "필보"], timeout=35))
        self.assertTrue(self.wait_for(lambda: not self.q.running))

    def test_timed_card_cuts_in_at_safe_point(self):
        # 긴 카드가 도는 중 시간 정해진 카드가 열리면, 긴 카드가 끊어도 되는 자리(cut_for_timed 를 부름)에서 밀려나고
        # 그 카드를 먼저 한 뒤 긴 카드를 이어 한다
        k, q = self.k, self.q
        k.timed = lambda it: it.get("label") == "필보"
        stop = threading.Event()
        steps = []

        def run(q_, it):
            if it["label"] != "긴 일":
                k.ran.append(it["label"])
                return True
            for n in range(200):
                if stop.is_set():
                    stop.clear()
                    q_.set_stop("stopped")
                    return False
                steps.append(n)
                if n == 3:
                    k.open = True
                q_.cut_for_timed()  # 단계마다 (cutpoint.check)
                time.sleep(0.01)
            k.ran.append("긴 일")
            return True
        k.run = run
        k.stop = lambda reason: stop.set()
        q.add({"kind": "daily", "label": "긴 일"})
        q.add({"kind": "daily", "label": "필보"})
        q.tick()
        self.assertTrue(self.wait_for(lambda: k.ran == ["필보", "긴 일"]))
        self.assertTrue(self.wait_for(lambda: not q.running))

    def test_not_cut_by_itself_or_closed(self):
        k, q = self.k, self.q
        k.timed = lambda it: it.get("label") == "필보"
        cut = []

        def run(q_, it):
            cut.append(q_.cut_for_timed())
            k.ran.append(it["label"])
            return True
        k.run = run
        q.add({"kind": "daily", "label": "긴 일"})
        q.add({"kind": "daily", "label": "필보"})
        q.tick()  # 필보는 닫혀 있음 → 긴 일이 끊기지 않는다
        self.assertTrue(self.wait_for(lambda: k.ran == ["긴 일"]))
        k.open = True  # 열리면 필보가 돌고, 필보는 저 자신을 끊지 않는다
        self.assertTrue(self.wait_for(lambda: k.ran == ["긴 일", "필보"], timeout=35))
        self.assertEqual(cut, ["", ""])

    def test_pause_while_waiting(self):
        self.q.add({"kind": "daily", "label": "필보"})
        self.q.tick()
        self.assertTrue(self.wait_for(lambda: self.q.items[0]["note"] == "열린 시간이 아님"))
        self.q.pause()
        self.assertTrue(self.wait_for(lambda: not self.q.running, timeout=3))
        self.assertEqual(self.k.ran, [])


if __name__ == "__main__":
    unittest.main()
