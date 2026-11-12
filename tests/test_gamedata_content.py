"""data/content.json 로더 (mabi.gamedata) — 이번 주 계산."""
import datetime as dt
import unittest
from unittest import mock

from mabi import gamedata

KST = dt.timezone(dt.timedelta(hours=9))

FAKE = {
    "fieldBoss": {"tz": "KST", "hours": [12, 18], "openMinutes": 30,
                  "bosses": [{"name": "보스A", "difficulties": ["일반", "어려움"]}]},
    "raid": {
        "raids": {"R1": ["입문", "어려움", "매우 어려움"], "R2": ["어려움", "매우 어려움"]},
        "schedule": [
            {"tz": "UTC", "start": "2026-11-01 21:00:00", "end": "2026-11-08 21:00:00", "raids": [["R1", "입문"]]},
            {"tz": "UTC", "start": "2026-11-08 21:00:00", "end": "2026-11-15 21:00:00",
             "raids": [["R1", "어려움"], ["R2", "매우 어려움"]]},
        ],
    },
    "abyss": {
        "dungeons": {"D1": {"season": "S", "difficulties": [
            {"name": "입문", "raw": "Normal", "solo": True, "party": True},
            {"name": "매우 어려움2", "raw": "VeryHard_2", "solo": True, "party": True},
            {"name": "지옥1", "raw": "Hell_1", "solo": False, "party": True}]}},
        "schedule": [
            {"tz": "KST", "start": "2026-11-09 06:00:00", "end": "2026-11-16 06:00:00", "dungeons": [["D1", "Normal,Hell_1"]]},
            {"tz": "KST", "start": "2026-11-16 06:00:00", "end": "", "dungeons": [["D1", "Normal,VeryHard_2,Hell_1"]]},
        ],
    },
}


class ContentTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(gamedata, "content", return_value=FAKE)
        p.start()
        self.addCleanup(p.stop)

    def test_raid_week_boundary(self):
        # UTC 21시 = KST 다음 날 06시에 바뀐다
        self.assertEqual(gamedata.raids(dt.datetime(2026, 11, 9, 5, 59, tzinfo=KST)), {"R1": ["입문"]})
        self.assertEqual(gamedata.raids(dt.datetime(2026, 11, 9, 6, 0, tzinfo=KST)),
                         {"R1": ["입문", "어려움"], "R2": ["어려움", "매우 어려움"]})

    def test_naive_time_is_kst(self):
        self.assertEqual(gamedata.raids(dt.datetime(2026, 11, 9, 6, 0)), gamedata.raids(dt.datetime(2026, 11, 9, 6, 0, tzinfo=KST)))

    def test_after_table_ends_keeps_last(self):
        self.assertEqual(list(gamedata.raids(dt.datetime(2027, 3, 1, tzinfo=KST))), ["R1", "R2"])

    def test_abyss_mode_and_open(self):
        t = dt.datetime(2026, 11, 10, tzinfo=KST)
        self.assertEqual(gamedata.abysses(t), {"D1": ["입문"]})
        self.assertEqual(gamedata.abysses(t, "party"), {"D1": ["입문", "지옥1"]})
        # 끝이 빈 칸은 계속 열림
        self.assertEqual(gamedata.abysses(dt.datetime(2030, 1, 1, tzinfo=KST)), {"D1": ["입문", "매우 어려움2"]})

    def test_field_boss(self):
        self.assertEqual(gamedata.field_bosses(), {"보스A": ["일반", "어려움"]})
        self.assertEqual(gamedata.field_boss_hours(), ((12, 18), 30))


class RealFileTest(unittest.TestCase):
    def test_bundled_file_loads(self):
        self.assertTrue(gamedata.field_bosses())
        self.assertTrue(gamedata.raids())
        self.assertTrue(gamedata.abysses())


if __name__ == "__main__":
    unittest.main()
