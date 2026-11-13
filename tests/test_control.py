"""제어 통로 (gui_app.control) — 명령 목록·인자 확인·예전 통로 글자·알림. 파이프(Qt)는 빼고 가짜 API 로 돌린다."""
import unittest
from unittest import mock

from gui_app import control

CHARS = [{"slot": 1, "name": "가"}, {"slot": 2, "name": "나"}]
ABYSS = {"solo": {"던전A": ["어려움", "매우 어려움"], "던전B": ["매우 어려움"]},
         "party": {"던전A": ["어려움"], "던전B": []}}


class FakeQueue:
    def __init__(self, items=(), running=False):
        self.items = [dict(x) for x in items]
        self.running = running
        self.calls = []
        self._seq = 100

    def snapshot(self):
        return {"items": [{**x, "view": {"now": "진행"}} for x in self.items], "running": self.running}

    def add(self, spec, where="end", replace_paused=False):
        it = {**spec, "id": self._seq, "status": "wait"}
        self._seq += 1
        self.items.append(it)
        self.calls.append(("add", where, replace_paused))
        return it

    def tick(self):
        self.calls.append(("tick",))

    def find(self, i):
        return next((x for x in self.items if x["id"] == i), None)

    def current(self):
        return next((x for x in self.items if x["status"] == "run"), None)

    def top_paused(self):
        return next((x for x in self.items if x["status"] == "pause"), None)

    def can_resume(self):
        return bool(self.top_paused())

    def resume_top(self):
        self.calls.append(("resume",))

    def skip_current(self):
        self.calls.append(("skip",))

    def clear(self):
        self.calls.append(("clear",))


class FakeApi:
    def __init__(self, queue=None):
        self.queue = queue or FakeQueue()
        self.paths = None
        self.cli = mock.Mock(run_limited=False)
        self._q_pending_ask = None
        self.halted = 0

    def queue_add(self, spec, where="end", replace_paused=False):
        return self.queue.add(spec, where, replace_paused)

    def queue_halt(self):
        self.halted += 1

    def daily_abyssSettings(self):  # noqa: N802
        return {"dungeon": "던전A", "difficulty": "매우 어려움", "mode": "solo", "slot": 1, "chars": CHARS}

    def daily_raidSettings(self):  # noqa: N802
        return {"raid": "레이드A", "difficulty": "어려움", "mode": "solo", "slot": 1,
                "difficulties": {"레이드A": ["보통", "어려움"]}}

    def plan_craft(self, name, target, opts=None):
        if name != "밥":
            return {"error": "not_found"}
        return {"kind": "alter", "name": "밥", "product": "밥", "displayName": "밥", "productName": "밥",
                "producedPerCraft": 3, "runs": 34, "have": 5,
                "blockers": [{"displayName": "물이 든 병", "lack": 4}]}


class CommandsTest(unittest.TestCase):
    def setUp(self):
        for target, value in (("mabi.profile.chars", CHARS),):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("mabi.gamedata.abysses", side_effect=lambda now=None, mode="solo": ABYSS[mode])
        p.start()
        self.addCleanup(p.stop)
        self.api = FakeApi()
        self.c = control.Commands(self.api)

    def test_goal_card_like_screen_button(self):
        r = self.c.run("goal", {"name": "밥", "target": 100})
        self.assertTrue(r["ok"], r)
        spec = self.api.queue.items[-1]
        self.assertIn(("add", "end", False), self.api.queue.calls)
        self.assertIn(("tick",), self.api.queue.calls)  # 쉬고 있으면 바로 돈다
        self.assertEqual((spec["kind"], spec["via"], spec["name"], spec["target"], spec["startHave"]),
                         ("goal", "가공", "밥", 100, 5))
        self.assertNotIn("slot", spec)  # 비우면 처음 시작할 때 접속해 있는 캐릭터
        self.assertIn("물이 든 병 4개", r["data"]["blocked"])

    def test_goal_bad_args(self):
        self.assertEqual(self.c.run("goal", {"name": "없는것", "target": 3})["error"], "bad_args")
        self.assertEqual(self.c.run("goal", {"name": "밥", "target": 0})["error"], "bad_args")
        self.assertEqual(self.c.run("goal", {"target": 3})["error"], "bad_args")
        self.assertEqual(self.c.run("goal", {"name": "밥", "target": 3, "slot": 9})["error"], "bad_args")

    def test_catalog_describes_every_command(self):
        names = {x["name"] for x in self.c.catalog()}
        self.assertTrue({"hello", "status", "pause", "resume", "abyss", "daily"} <= names)
        self.assertTrue(all(x["summary"] for x in self.c.catalog()))
        self.assertFalse(self.c.table["status"].act)
        self.assertTrue(self.c.table["pause"].act)

    def test_unknown_command(self):
        r = self.c.run("dance")
        self.assertEqual((r["ok"], r["error"]), (False, "unknown_command"))

    def test_status_shape(self):
        self.api.queue = FakeQueue([{"id": 1, "kind": "abyss", "label": "어비스", "status": "run", "note": "3판"},
                                    {"id": 2, "kind": "daily", "label": "숙제", "status": "wait"}], running=True)
        with mock.patch.object(control.Commands, "_game_window", return_value=True):
            d = self.c.run("status")["data"]
        self.assertEqual(d["queue"]["current"]["id"], 1)
        self.assertEqual(d["queue"]["current"]["now"], "진행")  # 화면 진행 줄도 준다
        self.assertEqual([x["id"] for x in d["queue"]["waiting"]], [2])
        self.assertTrue(d["game"]["window"])

    def test_abyss_defaults_and_starts_idle_queue(self):
        r = self.c.run("abyss", {"slot": 2, "dungeon": "던전A", "runs": 3})
        self.assertTrue(r["ok"], r)
        it = self.api.queue.items[-1]
        self.assertEqual((it["slot"], it["dungeon"], it["difficulty"], it["runs"]), (2, "던전A", "매우 어려움", 3))
        self.assertEqual(it["label"], "어비스 · 나")
        self.assertIn(("tick",), self.api.queue.calls)

    def test_abyss_rejects_unknown_values(self):
        r = self.c.run("abyss", {"slot": 1, "dungeon": "없는던전"})
        self.assertEqual(r["error"], "bad_args")
        self.assertIn("던전A", r["message"])  # 고를 수 있는 것을 같이 알려 준다
        self.assertEqual(self.c.run("abyss", {"slot": 9, "dungeon": "던전A"})["error"], "bad_args")
        r = self.c.run("abyss", {"slot": 1, "dungeon": "던전A", "mode": "party"})  # 설정 난이도가 함께하기엔 없다
        self.assertEqual(r["error"], "bad_args")
        self.assertEqual(self.api.queue.items, [])

    def test_raid_running_queue_does_not_tick(self):
        self.api.queue.running = True
        r = self.c.run("raid", {"slot": 1, "raid": "레이드A", "difficulty": "보통"})
        self.assertTrue(r["ok"], r)
        self.assertNotIn(("tick",), self.api.queue.calls)

    def test_daily_names_and_all_chars(self):
        r = self.c.run("daily", {"only": ["검은 구멍", "silver"]})
        self.assertTrue(r["ok"], r)
        it = self.api.queue.items[-1]
        self.assertEqual((it["chars"], it["only"]), ([1, 2], ["black_hole", "silver"]))
        self.assertIn(("add", "end", True), self.api.queue.calls)
        self.assertEqual(self.c.run("daily", {"only": ["낚시"]})["error"], "bad_args")

    def test_resume_and_enhance_refuse(self):
        self.assertEqual(self.c.run("resume")["error"], "refused")  # 일시정지 카드 없음
        self.api.queue.running = True
        self.assertEqual(self.c.run("enhance")["error"], "refused")

    def test_pause_uses_halt(self):
        self.assertTrue(self.c.run("pause")["ok"])
        self.assertEqual(self.api.halted, 1)

    def test_handler_error_does_not_escape(self):
        self.api.queue.snapshot = lambda: 1 / 0
        r = self.c.run("queue")
        self.assertEqual(r["error"], "failed")


class LegacyTest(unittest.TestCase):
    def test_words(self):
        self.assertEqual(control.legacy(b"halt"), ("pause", {}))
        self.assertEqual(control.legacy(b"resume"), ("resume", {}))
        self.assertEqual(control.legacy(b"restart"), ("restart_game", {}))
        self.assertIsNone(control.legacy(b"???"))

    def test_daily_and_abyss(self):
        self.assertEqual(control.legacy("daily:1,2:silver:force".encode()),
                         ("daily", {"slots": [1, 2], "only": ["silver"], "force": True}))
        self.assertEqual(control.legacy("abyss:1:던전A:5::party".encode()),
                         ("abyss", {"slot": "1", "dungeon": "던전A", "runs": "5", "mode": "party"}))
        self.assertEqual(control.legacy(b"raid:2:x")[1], {"slot": "2", "raid": "x"})


class EventsTest(unittest.TestCase):
    def test_only_status_changes(self):
        got = []
        ev = control.Events(lambda n, d: got.append((n, d)))
        snap = lambda st, running=True: {"running": running, "items": [{"id": 1, "label": "a", "status": st}]}  # noqa: E731
        ev.on_emit("mm:queue", snap("wait", False))
        self.assertEqual(got, [])  # 처음 본 대기 카드는 알리지 않는다
        ev.on_emit("mm:queue", snap("run"))
        ev.on_emit("mm:queue", snap("run"))  # 진행 줄만 바뀜 → 조용
        ev.on_emit("mm:queue", snap("done", False))
        self.assertEqual([(n, d.get("status", d.get("running"))) for n, d in got],
                         [("card", "run"), ("queue", True), ("card", "done"), ("queue", False)])
        self.assertEqual(got[2][1]["from"], "run")

    def test_report_and_ask(self):
        got = []
        ev = control.Events(lambda n, d: got.append(n))
        ev.on_emit("mm:queue-report", {"cards": [{"label": "a", "status": "done"}]})
        ev.on_emit("mm:queue-ask", {"id": 1})
        ev.on_emit("mm:exec-start", {})
        self.assertEqual(got, ["queue_done", "ask"])


if __name__ == "__main__":
    unittest.main()
