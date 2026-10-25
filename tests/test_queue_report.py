"""작업 큐 결과 보고 — 큐가 다 비는 순간(다 끝남·전체 중단·지금 카드 중단 뒤 끝) 한 번 뜨고, 얻은 것을 앞뒤 비교로 잰다."""
import tempfile
import unittest
from pathlib import Path

from mabi import queue_report as qr
from mabi.workqueue import WorkQueue
from test_workqueue import FakeLong, FakeQuick, wait_for


class LootTest(unittest.TestCase):
    def test_gained_used_and_currency(self):
        before = {"items": {"양털": 3, "빵": 5}, "cur": {"골드": 100, "은동전": 10}}
        after = {"items": {"양털": 10, "빵": 4, "거미줄": 2}, "cur": {"골드": 150, "은동전": 10}}
        x = qr.loot(before, after, "가")
        self.assertEqual(x, {"who": "가", "gained": {"양털": 7, "거미줄": 2}, "used": {"빵": 1}, "cur": {"골드": 50}})

    def test_no_change_or_unknown(self):
        s = {"items": {"양털": 3}, "cur": {}}
        self.assertIsNone(qr.loot(s, s))
        self.assertIsNone(qr.loot(None, s))

    def test_total_adds_up(self):
        t = qr.total([{"gained": {"양털": 2}, "cur": {"골드": 5}}, {"gained": {"양털": 3}, "cur": {"골드": -5}}])
        self.assertEqual(t, {"gained": {"양털": 5}, "used": {}, "cur": {}})

    def test_resumed_daily_keeps_earlier_result(self):
        # 이어 한 실행은 앞서 끝낸 숙제를 DONE(오늘 이미 끝남)으로 넘긴다 — 앞 결과 OK 를 남긴다
        rows = qr.merge_tasks([["[가] 은동전", "OK", "끝"], ["[가] 공물", "STOP", ""]],
                              [["[가] 은동전", "DONE", "오늘 완료"], ["[가] 공물", "OK", "끝"]])
        self.assertEqual(rows, [["[가] 은동전", "OK", "끝"], ["[가] 공물", "OK", "끝"]])


class QueueReportFlowTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = Path(d.name)
        self.long, self.quick = FakeLong(), FakeQuick()
        self.reports = []
        self.bag = {"items": {"양털": 0}, "cur": {}}

        def snap():
            self.bag = {"items": {"양털": self.bag["items"]["양털"] + 1}, "cur": {}}  # 찍을 때마다 하나씩 는다
            return self.bag
        self.q = WorkQueue(self.dir / "queue.json", self.dir / "history.jsonl", lambda ch, v: None,
                           {"daily": self.long, "action": self.quick, "goal": self.quick},
                           snap=snap, on_report=self.reports.append)

    def test_report_once_when_all_done(self):
        self.q.add({"kind": "action", "label": "채집"})
        self.q.add({"kind": "action", "label": "제작"})
        self.q.tick()
        self.assertTrue(wait_for(lambda: self.reports))
        r = self.reports[0]
        self.assertEqual(r["why"], "done")
        self.assertEqual([(c["label"], c["result"]) for c in r["cards"]], [("채집", "done"), ("제작", "done")])
        self.assertEqual(r["total"]["gained"], {"양털": 2})
        self.assertEqual(len(self.reports), 1)

    def test_pause_does_not_report_but_clear_does(self):
        self.q.add({"kind": "daily", "label": "숙제"})
        self.q.add({"kind": "action", "label": "채집"})
        self.q.tick()
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.long.f12()  # 일시정지 — 아직 한 번 도는 중
        self.assertTrue(wait_for(lambda: not self.q.running))
        self.assertEqual(self.reports, [])
        self.q.clear()  # 전체 중단 (Ctrl+F12)
        self.assertEqual(len(self.reports), 1)
        self.assertEqual(self.reports[0]["why"], "stopped")
        self.assertEqual([c["result"] for c in self.reports[0]["cards"]], ["stop"])

    def test_skip_moves_on_to_next(self):
        self.q.add({"kind": "daily", "label": "숙제"})
        self.q.add({"kind": "action", "label": "채집"})
        self.q.tick()
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.q.skip_current()  # Shift+F12
        self.assertTrue(wait_for(lambda: self.reports))
        self.assertEqual(self.long.stops, ["skip"])
        self.assertEqual(self.quick.ran, ["채집"])
        self.assertEqual([(c["label"], c["result"]) for c in self.reports[0]["cards"]], [("숙제", "stop"), ("채집", "done")])
        self.assertEqual(self.q.items, [])

    def test_skip_paused_card_resumes_rest(self):
        self.q.add({"kind": "daily", "label": "숙제"})
        self.q.add({"kind": "action", "label": "채집"})
        self.q.tick()
        self.assertTrue(wait_for(lambda: self.long.started == [1]))
        self.long.f12()
        self.assertTrue(wait_for(lambda: not self.q.running))
        self.q.skip_current()
        self.assertTrue(wait_for(lambda: self.reports))
        self.assertEqual(self.quick.ran, ["채집"])


if __name__ == "__main__":
    unittest.main()
