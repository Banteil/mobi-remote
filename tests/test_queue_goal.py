"""작업 큐의 제작 목표 카드 (gui_app.queue_api.GoalKind) — 가짜 판단 엔진·가짜 명령으로 돌린다."""
import unittest

from gui_app.queue_api import GoalKind, QueueApi


class FakeQ:
    def __init__(self):
        self.stop = None
        self.notes = []

    def note(self, it, text):
        it["note"] = text
        self.notes.append(text)

    def patch(self, item_id, fields, quiet=False):
        self.item.update(fields)

    def set_stop(self, reason, extra=None):
        self.stop = {"reason": reason, **(extra or {})}


class FakeApi(QueueApi):
    """steps: goal_next 가 차례로 돌려줄 걸음 (have 포함). exec_results: 명령 결과."""

    def __init__(self, steps, exec_results=(), answers=(), base_have=0):
        self.steps = list(steps)
        self.exec_results = list(exec_results)
        self.answers = list(answers)
        self.base_have = base_have
        self.calls, self.asks, self.toasts = [], [], []

    def goal_next(self, name, target):
        if target == 0:
            return {"have": self.base_have}
        have, step = self.steps.pop(0)
        return {"have": have, "step": step}

    def exec(self, command, body=None, origin=None):
        self.calls.append((command, body))
        return self.exec_results.pop(0) if self.exec_results else {"ok": True, "wingsSpent": 5}

    def _q_ask(self, q, it, payload):
        self.asks.append(payload)
        return self.answers.pop(0) if self.answers else False

    def _q_wait_dialog_closed(self, q, label, limit=120):
        return True

    def _q_toast(self, title, text="", kind="ok"):
        self.toasts.append(title)


def card(**kw):
    return {"id": 1, "name": "못", "label": "못", "target": 10, **kw}


class GoalKindTest(unittest.TestCase):
    def run_goal(self, api, it=None):
        q = FakeQ()
        q.item = it or card()
        return GoalKind(api).run(q, q.item), q

    def test_gather_craft_done(self):
        api = FakeApi([(3, {"kind": "gather", "name": "철광석", "why": "철광석 채집"}),
                       (3, {"kind": "craft", "name": "못", "batch": 2, "why": "못 제작"}),
                       (13, {"kind": "done"})], base_have=3)
        ok, q = self.run_goal(api)
        self.assertTrue(ok)
        self.assertEqual([c[0] for c in api.calls], ["execute_gathering", "execute_crafting"])
        self.assertEqual(api.calls[1][1], {"displayName": "못", "craftCount": 2})
        self.assertEqual(q.item["base"], 3)
        self.assertEqual(q.item["made"], 10)
        self.assertEqual(q.item["spent"], 10)
        self.assertTrue(q.notes[-1].startswith("달성"))

    def test_blocked_asks_then_continues(self):
        api = FakeApi([(0, {"kind": "blocked", "name": "마법의 호박", "message": "상점에서만"}),
                       (10, {"kind": "done"})], answers=[True])
        ok, q = self.run_goal(api)
        self.assertTrue(ok)
        self.assertEqual(api.asks[0]["kind"], "goal_blocked")

    def test_blocked_declined_stops(self):
        api = FakeApi([(0, {"kind": "blocked", "name": "마법의 호박"})], answers=[False])
        ok, q = self.run_goal(api)
        self.assertFalse(ok)
        self.assertEqual(api.calls, [])

    def test_stuck_repeat_stops(self):
        # 같은 걸음이 4번 넘게 거푸 나오면 헛도는 것 — 날개를 더 태우지 않는다
        api = FakeApi([(0, {"kind": "gather", "name": "철광석"})] * 10)
        ok, q = self.run_goal(api)
        self.assertFalse(ok)
        self.assertEqual(len(api.calls), 4)
        self.assertIn("진전이 없어", q.notes[-1])

    def test_learn_once(self):
        api = FakeApi([(0, {"kind": "learn", "name": "못", "via": "제작"})] * 3)
        ok, q = self.run_goal(api)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(api.calls[0][1]["craftCount"], 1)

    def test_skill_level_stops_queue(self):
        api = FakeApi([(0, {"kind": "gather", "name": "은 광석"})],
                      exec_results=[{"ok": False, "error": "insufficient_living_skill_level", "data": {"requiredLevel": 5}}])
        ok, q = self.run_goal(api)
        self.assertFalse(ok)
        self.assertEqual(q.stop, {"reason": "skill", "what": "은 광석", "level": 5})

    def test_invalid_count_keeps_going(self):
        api = FakeApi([(0, {"kind": "craft", "name": "못", "batch": 99}), (0, {"kind": "craft", "name": "못", "batch": 10}),
                       (10, {"kind": "done"})], exec_results=[{"ok": False, "error": "invalid_count"}, {"ok": True}])
        ok, q = self.run_goal(api)
        self.assertTrue(ok)

    def test_stop_between_steps(self):
        api = FakeApi([(0, {"kind": "gather", "name": "철광석"}), (5, {"kind": "gather", "name": "구리"})])
        q = FakeQ()
        q.item = card()
        orig = api.exec

        def exec_then_pause(*a, **k):
            q.stop = {"reason": "pause"}  # F12
            return orig(*a, **k)
        api.exec = exec_then_pause
        ok = GoalKind(api).run(q, q.item)
        self.assertFalse(ok)
        self.assertEqual(len(api.calls), 1)

    def test_resume_keeps_base(self):
        api = FakeApi([(8, {"kind": "done"})], base_have=99)
        ok, q = self.run_goal(api, card(base=3, target=5))
        self.assertTrue(ok)
        self.assertEqual(q.item["base"], 3)  # 이어 갈 때 기준점을 다시 잡지 않는다


class AskTest(unittest.TestCase):
    """돌던 카드가 사람에게 묻고(mm:queue-ask) 답을 기다린다 (QueueApi._q_ask · queue_answer)."""

    def api(self):
        class A(QueueApi):
            def __init__(self):
                self.events = []
                self._q_pending_ask = None

            def _emit(self, ch, v=None):
                self.events.append((ch, v))
        return A()

    def test_answer_yes(self):
        import threading
        a, q = self.api(), FakeQ()
        threading.Timer(0.1, lambda: a.queue_answer(1, True)).start()
        self.assertTrue(a._q_ask(q, card(), {"kind": "goal_blocked"}))
        self.assertEqual(a.events[0][0], "mm:queue-ask")
        self.assertEqual(a.events[-1], ("mm:queue-ask", None))  # 끝나면 창을 닫으라고

    def test_stop_gives_up(self):
        import threading
        a, q = self.api(), FakeQ()
        threading.Timer(0.1, lambda: setattr(q, "stop", {"reason": "pause"})).start()  # F12
        self.assertFalse(a._q_ask(q, card(), {"kind": "goal_blocked"}))
        self.assertIsNone(a._q_pending_ask)

    def test_wrong_id_ignored(self):
        a = self.api()
        self.assertEqual(a.queue_answer(5, True), {"ok": False})


if __name__ == "__main__":
    unittest.main()
