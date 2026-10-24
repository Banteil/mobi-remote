"""작업 큐의 '한 번 하는 행동' 카드 (gui_app.queue_api.ActionKind) — 가짜 API 로 돌린다."""
import unittest

from gui_app.queue_api import ActionKind, QueueApi


class FakeQ:
    def __init__(self):
        self.stop = None
        self.notes = []

    def note(self, it, text):
        self.notes.append(text)


class FakeApi(QueueApi):
    def __init__(self, results, facilities=(), dialogue_until=0):
        self.results = list(results)
        self.calls = []
        self.events = []
        self.facilities = list(facilities)
        self.dialogue_left = dialogue_until  # activity 를 이만큼 물을 때까지 확인 창이 떠 있다

    def exec(self, command, body=None, origin=None):
        self.calls.append((command, (body or {}).get("displayName"), origin))
        return self.results.pop(0) if self.results else {"ok": True}

    def query(self, name, opts=None):
        if name == "alteringWorks":
            return {"facilities": [{"facility": f, "completed": [{"name": f + " 물건"}]} for f in self.facilities]}
        if name == "activity":
            self.dialogue_left -= 1
            return {"dialogue": self.dialogue_left >= 0}
        return {}

    def _emit(self, ch, v=None):
        self.events.append((ch, v))


class ActionKindTest(unittest.TestCase):
    def test_single_action_ok(self):
        api, q = FakeApi([{"ok": True}]), FakeQ()
        ok = ActionKind(api).run(q, {"id": 1, "act": "play", "command": "play_music_score", "body": {"title": "x"}, "label": "연주: x"})
        self.assertTrue(ok)
        self.assertEqual(api.calls[0][2], {"label": "연주: x", "act": "play"})  # 화면이 결과를 알리게 표시

    def test_single_action_fail_note(self):
        api, q = FakeApi([{"ok": False, "error": "x", "ko": {"text": "재료가 부족합니다"}}]), FakeQ()
        ok = ActionKind(api).run(q, {"id": 1, "act": "craft", "command": "execute_crafting", "body": {}, "label": "못"})
        self.assertFalse(ok)
        self.assertEqual(q.notes[-1], "실패 — 재료가 부족합니다")

    def test_collect_all_with_blocked_retry(self):
        # 둘째 시설이 'blocked' → 확인 창이 닫히길 기다렸다가 한 번 더
        api = FakeApi([{"ok": True}, {"ok": False, "error": "blocked"}, {"ok": True}], facilities=["가죽", "금속"])
        q = FakeQ()
        ok = ActionKind(api).run(q, {"id": 1, "act": "collectAll", "label": "전체 수령"})
        self.assertTrue(ok)
        self.assertEqual([c[1] for c in api.calls], ["가죽 물건", "금속 물건", "금속 물건"])
        self.assertIn("재시도", api.calls[2][2]["label"])
        self.assertEqual(q.notes[-1], "완료 2곳")

    def test_collect_all_nothing(self):
        api, q = FakeApi([]), FakeQ()
        self.assertTrue(ActionKind(api).run(q, {"id": 1, "act": "collectAll"}))
        self.assertEqual(api.calls, [])

    def test_collect_all_stops_with_queue(self):
        api, q = FakeApi([], facilities=["가죽", "금속", "목재"]), FakeQ()
        orig = api.exec

        def exec_then_stop(*a, **k):
            r = orig(*a, **k)
            q.stop = {"reason": "pause"}  # 첫 시설을 받는 사이 ⏸
            return r
        api.exec = exec_then_stop
        ok = ActionKind(api).run(q, {"id": 1, "act": "collectAll"})
        self.assertFalse(ok)  # 다 못 했으니 일시정지로 남는다
        self.assertEqual(len(api.calls), 1)


class StopKeyTest(unittest.TestCase):
    """F12 하나로 작업 큐 전체 — 돌고 있으면 무엇이든 일시정지, 쉬고 있으면 맨 위 일시정지 카드 이어 하기."""

    def api(self, running, paused):
        class Cli:
            canceled = 0

            def cancel(self):
                Cli.canceled += 1

        class Q:
            def __init__(self):
                self.running, self.calls = running, []

            def request_stop(self, r):
                self.calls.append(("stop", r))

            def top_paused(self):
                return {"id": 1} if paused else None

            def resume_top(self):
                self.calls.append(("resume",))
        a = FakeApi([])
        a.queue, a.cli = Q(), Cli()
        return a

    def test_running_pauses_anything(self):
        a = self.api(running=True, paused=False)
        a._q_stop_key()
        self.assertEqual(a.queue.calls, [("stop", "pause")])
        self.assertEqual(a.cli.canceled, 1)  # 행동·목표의 지금 명령도 끊는다

    def test_idle_resumes_top(self):
        a = self.api(running=False, paused=True)
        a._q_stop_key()
        self.assertEqual(a.queue.calls, [("resume",)])

    def test_idle_nothing(self):
        a = self.api(running=False, paused=False)
        a._q_stop_key()
        self.assertEqual(a.queue.calls, [])


if __name__ == "__main__":
    unittest.main()
