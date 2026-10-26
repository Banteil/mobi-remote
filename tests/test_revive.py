"""'여기서 부활'(R) — 누르고 정해진 시간 안에 부활 신호가 오는지로 정한다 (mabi.tasks.abyss.revive_here)."""
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.tasks import abyss


class FakePackets:
    def __init__(self, ok=True, used=None, mx=None, revived_after=None):
        self.ok = ok
        self.state = SimpleNamespace(revives_used=used, revives_max=mx)
        self.revived_after = revived_after  # 몇 번째 확인에서 부활 신호가 오나 (None = 안 옴)
        self.checks = 0

    def mark(self):
        return 0

    def find(self, key, after, check=None):
        self.checks += 1
        return key == "revive.item_ok" and self.revived_after is not None and self.checks >= self.revived_after


class FakeBot:
    def __init__(self, packets):
        self.packets = packets
        self.keys = []
        self.cfg = {"abyss": {"revive_timeout": 10}}
        self.log = logging.getLogger("test")
        self.vision = SimpleNamespace(find=lambda frame, name: True)
        self.now = 0.0

    def frame(self):
        return None

    def key(self, k):
        self.keys.append(k)

    def sleep(self, a, b=None):
        self.now += a

    def is_dead(self):
        return True

    def snapshot(self, name):
        return SimpleNamespace(name=name)


def run(bot):
    with mock.patch.object(abyss.time, "monotonic", lambda: bot.now):
        return abyss.revive_here(bot)


class DeadThenClearTest(unittest.TestCase):
    """쓰러진 사이 파티가 보스를 잡아 판이 끝나면 나가지 않고 클리어로 잇는다 (2026-10-26 사용자 제보 —
    부활을 못 해 나가려다 판 밖이라 ESC 만 누르고 '어비스에서 나가지 못함' 으로 멈췄다)."""

    def test_revive_wait_stops_when_result_comes(self):
        p = FakePackets(used=0, mx=3)
        p.state.abyss_result = 7
        bot = FakeBot(p)
        self.assertFalse(run(bot))
        self.assertLess(bot.now, 10)  # 10초를 다 기다리지 않는다

    def test_leave_after_result_does_not_leave(self):
        bot = mock.Mock()
        with mock.patch.object(abyss, "after_clear", return_value=True),                 mock.patch.object(abyss, "inside", return_value=False):
            self.assertFalse(abyss.leave(bot))
        bot.key.assert_not_called()
        bot.click.assert_not_called()

    def test_dead_finish_after_result_is_clear(self):
        from mabi.monitor import detect as d
        from mabi.monitor.handlers import Finish
        bot = mock.Mock()
        bot.packets.mark.return_value = 0
        bot.packets.find.return_value = None
        bot.wait_packet.return_value = False
        bot.state.activity.return_value = {}
        seen = d.Seen(d.DEAD, src="packet", finish=Finish("dead"))
        with mock.patch.object(abyss, "watch", return_value=seen),                 mock.patch.object(abyss, "inside", return_value=False),                 mock.patch.object(abyss, "after_clear", return_value=True):
            self.assertEqual(abyss.play(bot, 60), "clear")


class ReviveTest(unittest.TestCase):
    def test_signal_comes(self):
        bot = FakeBot(FakePackets(used=1, mx=3, revived_after=2))
        self.assertTrue(run(bot))
        self.assertEqual(bot.keys, ["r"])

    def test_no_signal_means_blocked(self):
        # 전멸·아이템 없음: R 을 눌러도 아무 일 없음 → 한 번 더 눌러 보고 시간이 다 되면 나간다
        bot = FakeBot(FakePackets(used=0, mx=3))
        self.assertFalse(run(bot))
        self.assertEqual(bot.keys, ["r", "r"])

    def test_count_used_up_never_presses(self):
        bot = FakeBot(FakePackets(used=3, mx=3))
        self.assertFalse(run(bot))
        self.assertEqual(bot.keys, [])

    def test_without_packets_uses_is_dead(self):
        bot = FakeBot(FakePackets(ok=False))
        bot.is_dead = lambda: bot.now < 3  # 패킷이 없으면 CLI IsDead 가 풀리는 것으로
        self.assertTrue(run(bot))


if __name__ == "__main__":
    unittest.main()
