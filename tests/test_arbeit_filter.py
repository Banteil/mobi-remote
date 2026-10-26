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


if __name__ == "__main__":
    unittest.main()
