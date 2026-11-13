"""공물 던전: 접속 직후 퀘스트가 아직 없으면 그 캐릭터의 다른 숙제 뒤로 미루고, 접속한 때를 알면 접속 뒤 몇 분까지 기다린다."""
import time
import unittest
from types import SimpleNamespace

from mabi import tasks
from mabi.runner import Runner
from mabi.tasks import tribute


class FakeState:
    def __init__(self, quests):
        self.quests = quests

    def available(self):
        return True

    def query(self, name):
        assert name == "get_quests"
        return self.quests


class FakeDaily:
    def __init__(self, steps=None):
        self.steps = steps or {}

    def last_step(self, slot, task):
        return self.steps.get(task)


def bot(quests, login_at=0.0, also_done=()):
    return SimpleNamespace(state=FakeState(quests), session=SimpleNamespace(login_at=login_at), also_done=set(also_done))


OTHER = [{"QuestTitle": "다른 퀘스트"}]
TRIBUTE = [{"QuestTitle": tribute.QUEST_TITLE}]
CFG = {"tribute": {"quest_wait": 180, "quest_login_wait": 600}}


class NotYet(unittest.TestCase):
    def test_quest_missing_defers(self):
        self.assertTrue(tribute.not_yet(bot(OTHER), CFG))

    def test_quest_present_runs_now(self):
        self.assertEqual(tribute.not_yet(bot(TRIBUTE), CFG), "")

    def test_empty_list_is_unknown_runs_now(self):
        # 목록이 통째로 비면 모르는 것 — run 이 퀘스트 창에서 직접 찾는다
        self.assertEqual(tribute.not_yet(bot([]), CFG), "")

    def test_cut_after_opening_quest_resumes_in_place(self):
        self.assertEqual(tribute.not_yet(bot(OTHER), CFG, {"step": "travel"}), "")
        self.assertTrue(tribute.not_yet(bot(OTHER), CFG, {"step": "tr_wait"}))
        self.assertTrue(tribute.not_yet(bot(OTHER), CFG, {"step": "end"}))


class WaitUntil(unittest.TestCase):
    def test_unknown_login_waits_quest_wait(self):
        end = tribute._wait_until(bot(OTHER), CFG["tribute"])
        self.assertAlmostEqual(end - time.monotonic(), 180, delta=2)

    def test_fresh_login_waits_until_login_plus(self):
        end = tribute._wait_until(bot(OTHER, login_at=time.monotonic() - 60), CFG["tribute"])
        self.assertAlmostEqual(end - time.monotonic(), 540, delta=2)

    def test_old_login_waits_quest_wait(self):
        end = tribute._wait_until(bot(OTHER, login_at=time.monotonic() - 3600), CFG["tribute"])
        self.assertAlmostEqual(end - time.monotonic(), 180, delta=2)


class RunnerLater(unittest.TestCase):
    def later(self, b, pending, later=(), steps=None):
        return Runner._later(b, CFG, FakeDaily(steps), 1, "tribute", list(pending), set(later))

    def test_registered(self):
        self.assertIs(tasks.LATER["tribute"], tribute.not_yet)

    def test_defers_when_other_tasks_remain(self):
        self.assertTrue(self.later(bot(OTHER), ["daily_mission", "arbeit"]))

    def test_last_task_is_not_deferred(self):
        self.assertEqual(self.later(bot(OTHER), []), "")

    def test_only_deferred_or_done_left_is_not_deferred(self):
        self.assertEqual(self.later(bot(OTHER, also_done=["black_hole"]), ["black_hole"]), "")

    def test_deferred_once(self):
        self.assertEqual(self.later(bot(OTHER), ["arbeit"], later=["tribute"]), "")

    def test_other_tasks_never_deferred(self):
        self.assertEqual(Runner._later(bot(OTHER), CFG, FakeDaily(), 1, "silver", ["arbeit"], set()), "")

    def test_query_error_runs_now(self):
        b = bot(OTHER)
        b.state.query = lambda name: (_ for _ in ()).throw(OSError("끊김"))
        self.assertEqual(self.later(b, ["arbeit"]), "")


if __name__ == "__main__":
    unittest.main()
