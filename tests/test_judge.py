"""여러 신호로 판단하기 (judge.decide) 와 어비스 단계 판단 (abyss.phase)."""
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi import judge
from mabi.bot import Bot
from mabi.packet_monitor import PacketState
from mabi.tasks import abyss

UI = {"reward_exit": "reward_exit", "dungeon_retry": "dungeon_retry", "dungeon_touch": "dungeon_touch",
      "abyss_exit": "abyss_exit"}


def make_bot(state: PacketState, seen=(), act=None):
    log = mock.MagicMock(spec=logging.Logger)
    return SimpleNamespace(
        packets=SimpleNamespace(ok=True, state=state),
        map_loading=lambda: None if state.channel is None and not state.loading else state.loading,
        activity=lambda *a, **k: act, frame=lambda: "frame", ui=UI,
        vision=SimpleNamespace(has=lambda n: True, find=lambda f, n: n in seen),
        state=SimpleNamespace(available=lambda: False), log=log)


def in_abyss(**kw):
    return PacketState(channel=1, channel_type="InstanceAbyssDungeon", loading=False, **kw)


class DecideTest(unittest.TestCase):
    def test_first_known_by_priority_and_conflict_logged_once(self):
        bot = make_bot(PacketState())
        checks = [("A", lambda: None), ("B", lambda: "x"), ("C", lambda: "y")]
        v = judge.decide(bot, "시험", checks)
        self.assertEqual((v.value, v.by.src), ("x", "B"))
        self.assertEqual(bot.log.info.call_count, 1)  # C 가 어긋남
        judge.decide(bot, "시험", checks)
        self.assertEqual(bot.log.info.call_count, 1)  # 같은 어긋남은 한 번

    def test_failing_sign_is_unknown(self):
        bot = make_bot(PacketState())
        v = judge.decide(bot, "시험", [("A", lambda: 1 / 0), ("B", lambda: "x")])
        self.assertEqual(v.value, "x")


class AbyssPhaseTest(unittest.TestCase):
    def test_reward_screen_beats_packet_map(self):
        """패킷이 결과를 놓쳐도 보상 화면이 보이면 보상 화면 (2026-11-03 19:26)."""
        bot = make_bot(in_abyss(), seen={"reward_exit"})
        self.assertEqual(abyss.phase(bot), "reward")
        self.assertFalse(abyss.inside(bot))
        self.assertTrue(abyss.after_clear(bot))
        bot.log.info.assert_called()  # 패킷 맵(판 안)과 어긋났다고 남긴다

    def test_play_when_nothing_else(self):
        bot = make_bot(in_abyss())  # 나가기 버튼이 창에 가려져도 패킷 맵으로 판 안
        self.assertEqual(abyss.phase(bot), "play")

    def test_result_beats_exit_button(self):
        bot = make_bot(in_abyss(abyss_result=3), seen={"abyss_exit"})  # 결과 연출 중엔 나가기 버튼이 남는다
        self.assertEqual(abyss.phase(bot), "reward")

    def test_cli_result_sequence(self):
        bot = make_bot(in_abyss(abyss_result=3), act={"IsAbyssResultSequencePlaying": True}, seen={"abyss_exit"})
        self.assertEqual(abyss.phase(bot), "reward")
        bot.log.info.assert_not_called()  # 결과 연출 동안 나가기 버튼이 남는 건 어긋남이 아니다
        bot = make_bot(in_abyss(), act={"IsAbyssResultSequencePlaying": True})
        self.assertEqual(abyss.phase(bot), "reward")
        bot.log.info.assert_called()  # 패킷이 결과를 놓침 (패킷 맵=판 안) — 이건 남긴다

    def test_matching_on_reward_screen_is_not_conflict(self):
        bot = make_bot(in_abyss(abyss_matching=2, abyss_result=3), seen={"reward_exit"})
        self.assertEqual(abyss.phase(bot), "matching")
        bot.log.info.assert_not_called()

    def test_field_with_lookalike_exit_button(self):
        st = PacketState(channel=1, channel_type="Field", loading=False)
        bot = make_bot(st, seen={"abyss_exit"})  # 사냥터에도 비슷한 나가기 버튼 (2026-10-26)
        self.assertEqual(abyss.phase(bot), "out")

    def test_expected_overlaps_are_not_conflicts(self):
        """다음 판으로 넘어가는 로딩엔 매칭·보상 신호가 남는다 — 어긋남으로 남기지 않는다 (11-03 로그 소음)."""
        bot = make_bot(PacketState(channel=1, loading=True, abyss_matching=3, abyss_result=3), seen={"reward_exit"},
                       act={"IsAbyssResultSequencePlaying": True})
        self.assertEqual(abyss.phase(bot), "loading")
        bot.log.info.assert_not_called()

    def test_matching_from_field_is_not_conflict(self):
        bot = make_bot(PacketState(channel=1, channel_type="Field", loading=False, abyss_matching=2))
        self.assertEqual(abyss.phase(bot), "matching")
        bot.log.info.assert_not_called()

    def test_loading_first(self):
        bot = make_bot(PacketState(channel=1, loading=True), seen={"reward_exit"})
        self.assertEqual(abyss.phase(bot), "loading")


class DeadTest(unittest.TestCase):
    def bot(self, state, act, seen=False, ok=True):
        return SimpleNamespace(packets=SimpleNamespace(ok=ok, state=state), activity=lambda *a, **k: act,
                               ui={"revive": "revive_here"}, frame=lambda: "f",
                               vision=SimpleNamespace(has=lambda n: True, find=lambda f, n: seen),
                               log=mock.MagicMock())

    def test_cli_beats_old_packet(self):
        st = PacketState(dead=True)  # 오래전에 쓰러졌다는 패킷 (일어난 신호를 놓침)
        b = self.bot(st, {"IsDead": False})
        self.assertFalse(Bot.is_dead(b))
        b.log.info.assert_called()

    def test_fresh_packet_beats_cli(self):
        import time
        st = PacketState(dead=True)
        st.changed_at["dead"] = time.monotonic()  # 부활 창 신호가 CLI 보다 약 3초 빠르다
        self.assertTrue(Bot.is_dead(self.bot(st, {"IsDead": False})))

    def test_screen_only_when_both_unknown(self):
        self.assertTrue(Bot.is_dead(self.bot(PacketState(), None, seen=True, ok=False)))
        self.assertFalse(Bot.is_dead(self.bot(PacketState(dead=False), {"IsDead": False}, seen=True)))


if __name__ == "__main__":
    unittest.main()
