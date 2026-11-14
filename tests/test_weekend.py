"""주말 퀘스트 (mabi.tasks.weekend) — 주말 판정, 퀘스트 창 진행도로 판 수 정하기, 다 돌고도 남으면 더 돌기, 카드 설정 덮기."""
import datetime as dt
import unittest
from unittest import mock

from gui_app.queue_api import DailyKind, card_cfg
from mabi import runner, tasks
from mabi.exceptions import CannotProceed
from mabi.tasks import weekend
from mabi.tasks.weekend import Quest

CFG = {
    "abyss": {"dungeon": "가", "difficulty": "어려움", "mode": "solo", "runs": 0, "minutes": 0, "slot": 0,
              "run_timeout": 1200, "match_timeout": 600},
    "raid": {"raid": "나", "difficulty": "어려움", "mode": "solo", "runs": 0, "minutes": 0, "slot": 0},
    "weekend": {"task_timeout_min": 90,
                "abyss": {"dungeon": "허상의 정박지", "difficulty": "매우 어려움2", "mode": "party", "runs": 3},
                "raid": {"raid": "화이트 서큐버스", "difficulty": "매우 어려움", "mode": "party", "runs": 1}},
    "run": {"task_timeout_min": 45},
}


class NotNowTest(unittest.TestCase):
    def test_game_day_weekend(self):
        sat = dt.datetime(2026, 11, 14, 7)  # 토요일
        self.assertEqual(weekend.not_now(sat), "")
        self.assertTrue(weekend.not_now(sat.replace(hour=5)))  # 오전 6시 전은 아직 금요일
        self.assertEqual(weekend.not_now(dt.datetime(2026, 11, 16, 5)), "")  # 월요일 새벽은 아직 일요일
        self.assertTrue(weekend.not_now(dt.datetime(2026, 11, 16, 7)))

    def test_card_waits_but_does_not_cut_in(self):
        order = ["weekend_abyss", "weekend_raid"]
        with mock.patch.object(weekend, "not_now", return_value="주말 아님"), \
                mock.patch.dict(tasks.SEASON, {t: weekend.not_now for t in order}):
            self.assertEqual(tasks.not_ready(order), "주말 아님")
            self.assertEqual(DailyKind(None).ready({"only": order}), "주말 아님")
        self.assertFalse(tasks.timed(order))  # 주말이 와도 돌던 카드를 끊지 않는다
        self.assertFalse(DailyKind(None).timed({"only": order}))
        self.assertEqual(tasks.not_ready(order + ["silver"]), "")  # 섞이면 다른 숙제는 한다


class ProgressTest(unittest.TestCase):
    def test_reads_progress_under_title(self):
        items = [("주말에는 어비스!", 1500, 300), ("어비스 클리어 1/3", 1500, 360), ("다른 퀘스트 0/5", 1500, 700)]
        self.assertEqual(weekend._progress(items, 300), (1, 3))
        self.assertEqual(Quest(True, 1, 3).left(3), 2)
        self.assertEqual(Quest(True).left(3), 3)

    def test_ignores_far_or_odd_numbers(self):
        self.assertEqual(weekend._progress([("0/5", 1500, 700)], 300), (None, None))
        self.assertEqual(weekend._progress([("5/3", 1500, 330)], 300), (None, None))


class RunTest(unittest.TestCase):
    def setUp(self):
        self.bot = mock.Mock()
        self.runs = []
        for p in (mock.patch.object(weekend, "not_now", return_value=""),
                  mock.patch.object(weekend, "_repeat", side_effect=self._repeat)):
            p.start()
            self.addCleanup(p.stop)

    def _repeat(self, bot, cfg, kind, runs):
        self.runs.append((kind, runs))
        return {"clears": runs}

    def quests(self, *states):
        p = mock.patch.object(weekend, "quest_state", side_effect=list(states))
        p.start()
        self.addCleanup(p.stop)

    def test_skips_when_quest_gone(self):
        self.quests(Quest(False))
        self.assertIn("이미 깸", weekend.run(self.bot, CFG, "abyss"))
        self.assertEqual(self.runs, [])

    def test_runs_only_what_is_left(self):
        self.quests(Quest(True, 1, 3), Quest(False))
        r = weekend.run(self.bot, CFG, "abyss")
        self.assertEqual(self.runs, [("abyss", 2)])
        self.assertIn("퀘스트 깸", r)
        self.assertTrue(self.bot.verified)

    def test_runs_config_count_without_progress_and_more_if_left(self):
        self.quests(Quest(True), Quest(True), Quest(False))
        weekend.run(self.bot, CFG, "abyss")
        self.assertEqual(self.runs, [("abyss", 3), ("abyss", 1)])

    def test_fails_when_quest_stays(self):
        self.quests(*[Quest(True)] * (weekend.EXTRA + 2))
        with self.assertRaises(CannotProceed):
            weekend.run(self.bot, CFG, "raid")
        self.assertEqual(self.runs, [("raid", 1)] * (weekend.EXTRA + 1))

    def test_not_weekend(self):
        with mock.patch.object(weekend, "not_now", return_value="주말 아님"):
            with self.assertRaises(CannotProceed):
                weekend.run(self.bot, CFG, "abyss")


class ConfigTest(unittest.TestCase):
    def test_picked_overrides_repeat_section(self):
        a = weekend.picked(CFG, "abyss")
        self.assertEqual((a["dungeon"], a["difficulty"], a["mode"], a["runs"]), ("허상의 정박지", "매우 어려움2", "party", 3))
        self.assertEqual(a["run_timeout"], 1200)  # 매칭·시간 상한 등은 [abyss] 그대로
        self.assertEqual((a["slot"], a["minutes"]), (0, 0))  # 캐릭터는 실행기가 바꾼다

    def test_card_pick_keeps_runs(self):
        card = {"kind": "daily", "only": ["weekend_abyss", "weekend_raid"], "chars": [1, 2],
                "weekend": {"abyss": {"dungeon": "광기의 동굴", "difficulty": "어려움", "mode": "solo"},
                            "raid": {"raid": "에이렐", "difficulty": "어려움", "mode": "party"}}}
        cfg = runner._merged(CFG, card_cfg(card))
        self.assertEqual(cfg["weekend"]["abyss"], {"dungeon": "광기의 동굴", "difficulty": "어려움", "mode": "solo", "runs": 3})
        self.assertEqual(cfg["weekend"]["task_timeout_min"], 90)
        self.assertEqual(card_cfg({"fieldBoss": {"boss": "페리"}}), {"field_boss": {"boss": "페리"}})
        self.assertIn("광기의 동굴", DailyKind.detail(card))
        self.assertIn("에이렐", DailyKind.detail(card))

    def test_task_timeout(self):
        self.assertEqual(tasks.timeout_min("weekend_abyss", CFG), 90)
        self.assertEqual(tasks.timeout_min("silver", CFG), 45)

    def test_registered(self):
        for t in ("weekend_abyss", "weekend_raid"):
            self.assertIn(t, tasks.TASKS)
            self.assertIn(t, tasks.VERIFY)

    def test_default_config_has_section(self):
        import tomllib
        from pathlib import Path
        cfg = tomllib.loads((Path(__file__).resolve().parent.parent / "config.default.toml").read_text(encoding="utf-8"))
        self.assertEqual(cfg["weekend"]["abyss"]["runs"], 3)
        self.assertEqual(cfg["weekend"]["raid"]["runs"], 1)


if __name__ == "__main__":
    unittest.main()
