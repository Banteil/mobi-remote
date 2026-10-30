import unittest
from pathlib import Path
from unittest import mock

from mabi import craft
from mabi.tasks import arbeit

ROOT = Path(__file__).resolve().parent.parent


def quest(title, *objectives):
    return {"QuestTitle": title, "Source": "pinned_sub",
            "Objectives": [{"Description": d, "IsCompleted": done} for d, done in objectives]}


class AcceptedTest(unittest.TestCase):
    def test_pinned_side_quest_is_not_arbeit(self):
        """고정해 둔 사이드 퀘스트도 pinned_sub — 아르바이트 탭에서 본 제목만 아르바이트로 본다."""
        bot = mock.Mock()
        bot.state.query.return_value = [quest("[긴급 의뢰] 사이드"), quest("튼튼한 나무가 필요해")]
        bot._arb_titles = {"튼튼한 나무가 필요해"}
        self.assertEqual([j["title"] for j in arbeit.accepted(bot)], ["튼튼한 나무가 필요해"])
        self.assertEqual(len(arbeit.accepted(bot, raw=True)), 2)

    def test_unfiltered_before_panel_seen(self):
        bot = mock.Mock(spec=["state"])
        bot.state.query.return_value = [quest("[긴급 의뢰] 사이드")]
        self.assertEqual(len(arbeit.accepted(bot)), 1)


class AlterMissingTest(unittest.TestCase):
    def test_alter_products_only(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        job = {"title": "x", "objectives": [
            {"Description": f"두유 {arbeit.HAVE} 0/3", "IsCompleted": False},       # 식재료 가공
            {"Description": f"찻잎 {arbeit.HAVE} 2/30", "IsCompleted": False},      # 채집품
            {"Description": f"말린 찻잎 {arbeit.HAVE} 3/3", "IsCompleted": True},   # 다 모음
        ]}
        self.assertEqual(arbeit.alter_missing(job), ["두유"])
        # 가공품이어도 채집으로 구할 수 있으면 건너뛰지 않는다 (2026-10-30 멀리 다녀오실 분 — 깔끔 버섯 포자)
        self.assertEqual(arbeit.alter_missing(job, {"두유"}), [])


class QuickAlterTest(unittest.TestCase):
    """가공이 2분(alter_max_sec) 미만인 가공품만 아르바이트에서 가공한다 (사용자 규칙 2026-10-30)."""

    def test_limit(self):
        craft.configure(ROOT / "state", ROOT / "data", None)
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"alter_max_sec": 120}}
        self.assertTrue(arbeit.quick_alter(bot, ["옷감"]))            # 45초
        self.assertFalse(arbeit.quick_alter(bot, ["깔끔 버섯 포자"]))  # 1500초
        self.assertFalse(arbeit.quick_alter(bot, ["옷감", "깔끔 버섯 포자"]))


class HowtoRowTest(unittest.TestCase):
    """'구하는 방법' 에서 가공 시설 줄보다 채집 줄을 고른다 (가공 시설이 맨 위여도)."""

    def pick(self, texts):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"howto_area": [1200, 240, 720, 700]}}
        ctx = mock.MagicMock(n={}, alter=())
        with mock.patch.object(handlers.ocr, "find_texts", return_value=texts),                 mock.patch.object(handlers, "fast_travel"):
            handlers.howto(bot, ctx, SimpleNamespace(frame=None))
        return bot.click.call_args[0][0]

    def test_gather_row_over_facility(self):
        rows = [("구하는 방법", 1290, 160), ("약품", 1340, 275), ("가공 시설", 1420, 275),
                ("깔끔 버섯", 1360, 369), ("977m", 1790, 369), ("얼음 협곡 임무 전리품", 1420, 463)]
        self.assertEqual(self.pick(rows), (1360, 369))

    def test_alter_job_takes_facility(self):
        from types import SimpleNamespace
        from mabi.monitor import handlers
        bot = mock.MagicMock()
        bot.cfg = {"arbeit": {"howto_area": [1200, 240, 720, 700]}}
        ctx = mock.MagicMock(n={}, alter=("옷감",))
        rows = [("양털 깎기", 1360, 275), ("옷감", 1340, 369), ("가공 시설", 1420, 369)]
        with mock.patch.object(handlers.ocr, "find_texts", return_value=rows):
            handlers.howto(bot, ctx, SimpleNamespace(frame=None))
        self.assertEqual(bot.click.call_args[0][0][1], 369)

    def test_facility_only(self):
        self.assertEqual(self.pick([("약품 가공 시설", 1390, 369)]), (1390, 369))


if __name__ == "__main__":
    unittest.main()
