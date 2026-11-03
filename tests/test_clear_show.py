"""클리어 뒤 연출 (mabi.tasks.content._clear_show) — 보상 메뉴가 늦게 떠도 빈 곳을 계속 누르지 않는다."""
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.monitor import detect as d
from mabi.tasks import content


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeBot:
    def __init__(self, clock):
        self.clock = clock
        self.task_id = "weekday_dungeon"
        self.cfg = {"dungeon": {}}
        self.packets = SimpleNamespace(ok=True, state=None)
        self.log = logging.getLogger("test")

    def sleep(self, a, b=None):
        self.clock.t += a

    def dialogue_playing(self):
        return False

    def cutscene_playing(self):
        return False


class FakeMon:
    def __init__(self, clock, menu_at):
        self.clock, self.menu_at = clock, menu_at

    def check(self, ctx, guard=False):
        fin = self.clock.t >= self.menu_at
        return SimpleNamespace(finish=fin, what=d.REWARD if fin else d.UNKNOWN, done=None, frame=None)


class ClearShowTest(unittest.TestCase):
    def run_show(self, prompt_visible=False):
        clock = Clock()
        bot = FakeBot(clock)
        touches = []
        with mock.patch.object(content, "clear_kind", return_value="dungeon"), \
                mock.patch.dict(content.CLEAR_KINDS, {"dungeon": (lambda st: True, lambda st: True)}), \
                mock.patch.object(content.time, "monotonic", clock), \
                mock.patch.object(content, "touch_prompt_visible", return_value=prompt_visible), \
                mock.patch.object(content, "handlers_touch", lambda *a: touches.append(clock.t)):
            content._clear_show(bot, FakeMon(clock, menu_at=40), d, end=1000)
        return touches

    def test_blind_touches_slow_down(self):
        """요일 던전은 보상 메뉴까지 40초 — 처음 3번 뒤로는 10초에 한 번만 (2026-11-04 빈 곳 연타)."""
        self.assertLessEqual(len(self.run_show()), 6)

    def test_touch_when_prompt_seen(self):
        self.assertGreater(len(self.run_show(prompt_visible=True)), 6)


if __name__ == "__main__":
    unittest.main()
