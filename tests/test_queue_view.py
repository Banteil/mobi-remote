"""작업 큐 카드의 진행 줄(view)과 오버레이 글 — 숙제 이벤트로 진행 기록을 쌓고, 카드·오버레이가 같은 말을 하는지."""
import unittest

from gui_app.queue_api import AbyssKind, DailyKind, daily_progress
from gui_app.queue_overlay import clean, lines


def feed(events):
    p = None
    for e in events:
        n = daily_progress(p, e)
        if n is not None:
            p = n
    return p


START = {"type": "start", "characters": [{"slot": 1, "name": "가"}, {"slot": 2, "name": "나"}],
         "order": ["weekday_dungeon", "silver"], "labels": {"weekday_dungeon": "요일 던전", "silver": "은동전"}}


class DailyProgressTest(unittest.TestCase):
    def test_counts_and_now(self):
        p = feed([START,
                  {"type": "character", "slot": 1, "name": "가"},
                  {"type": "task_start", "slot": 1, "task": "login", "label": "[가] 접속"},
                  {"type": "task_end", "slot": 1, "task": "login", "status": "OK"},
                  {"type": "task_start", "slot": 1, "task": "weekday_dungeon", "label": "[가] 요일 던전"},
                  {"type": "task_end", "slot": 1, "task": "weekday_dungeon", "status": "FAIL"},
                  {"type": "task_start", "slot": 1, "task": "silver", "label": "[가] 은동전"},
                  {"type": "step", "slot": 1, "task": "silver", "text": "던전 1/2회 입장"}])
        v = DailyKind(None).view({"chars": [1, 2], "prog": p})
        self.assertEqual(v["now"], "[1/2] 가 · 은동전 (2/2)")
        self.assertEqual(v["step"], "던전 1/2회 입장")
        self.assertEqual(v["bar"], [1, 4])
        self.assertEqual(v["stat"], "실패 1")

    def test_skipped_character_counts_toward_position(self):
        # 오늘 다 한 캐릭터는 'character' 없이 task_end 만 온다 — 다음 캐릭터는 2번째여야 한다
        p = feed([START,
                  {"type": "task_end", "slot": 1, "task": "weekday_dungeon", "status": "DONE"},
                  {"type": "task_end", "slot": 1, "task": "silver", "status": "DONE"},
                  {"type": "character", "slot": 2, "name": "나"}])
        self.assertEqual((p["i"], p["done"], p["fail"]), (2, 2, 0))

    def test_no_start_no_progress(self):
        self.assertIsNone(daily_progress(None, {"type": "step", "text": "x"}))


class AbyssViewTest(unittest.TestCase):
    def test_runs_include_earlier(self):
        v = AbyssKind(None).view({"dungeon": "D", "difficulty": "어려움", "runs": 10, "doneRuns": 2,
                                  "prog": {"stage": "play", "clears": 1, "secs": 300}})
        self.assertEqual(v["now"], "진행 중 · 3/10판 · 5분")
        self.assertEqual(v["bar"], [3, 10])


class OverlayLinesTest(unittest.TestCase):
    SNAP = {"running": True, "items": [
        {"id": 1, "kind": "daily", "label": "일일 숙제", "status": "run", "startedAt": 1000,
         "view": {"goal": "2명 · 전체", "now": "[1/2] 가 · 은동전", "step": "", "stat": "", "bar": [1, 4]}},
        {"id": 2, "kind": "abyss", "label": "어비스", "status": "wait", "view": {}},
    ]}

    def test_running_card_and_next(self):
        rows = lines(self.SNAP, clean({"on": True}), now_ms=66_000)
        self.assertEqual(rows[0], ("head:run", "작업 큐 · 진행 중 · 대기 1\t1:05"))
        self.assertIn(("text", "[1/2] 가 · 은동전"), rows)
        self.assertIn(("bar", "1/4|1/4 · 25%"), rows)
        self.assertEqual(rows[-1], ("next", "다음  어비스"))

    def test_idle_queue_hidden_unless_always(self):
        idle = {"running": False, "items": [{"id": 2, "label": "어비스", "status": "wait", "view": {}}]}
        self.assertEqual(lines(idle, clean({"on": True})), [])
        self.assertTrue(lines(idle, clean({"on": True, "when": "always"})))

    def test_clean_rejects_bad_values(self):
        c = clean({"on": "yes", "bg": "rainbow", "alpha": 500, "dx": -3, "next": True})
        self.assertEqual((c["on"], c["bg"], c["alpha"], c["dx"], c["next"]), (True, "panel", 100, 0, 2))


if __name__ == "__main__":
    unittest.main()
