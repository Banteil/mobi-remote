"""리모콘을 콘텐츠 안에서 켜 패킷이 아직 맵을 모를 때·이어 하기 때 지금 상태를 잘못 보지 않는지."""
import logging
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi.packet_monitor import PacketState
from mabi.tasks import abyss, content, display


def bot_with(state: PacketState, ok=True, act=None, space=""):
    return SimpleNamespace(
        packets=SimpleNamespace(ok=ok, state=state),
        map_loading=lambda: None if state.channel is None and not state.loading else state.loading,
        activity=lambda *a, **k: act,
        state=SimpleNamespace(available=lambda: act is not None, activity=lambda: act,
                              query=lambda name: {"ChannelDisplayName": "어비스", "GameSpaceDisplayName": space}),
        cfg={"black_hole": {"space_keyword": "검은 구멍"}}, ui={},
        log=logging.getLogger("test"), sleep=lambda *a: None)


class InsideTest(unittest.TestCase):
    def test_result_without_map_is_not_inside(self):
        bot = bot_with(PacketState(abyss_result=3))  # 어비스 안에서 켜 맵은 모르지만 결과는 옴
        self.assertFalse(abyss.inside(bot))
        self.assertTrue(abyss.at_reward(bot))

    def test_matching_without_map_is_not_inside(self):
        self.assertFalse(abyss.inside(bot_with(PacketState(abyss_matching=2))))

    def test_entered_since_needs_new_map(self):
        """'다시 하기' 뒤 지난 판 맵(보상 화면)은 결과를 놓쳐도 새 판이 아니다 (2026-11-03 19:26)."""
        st = PacketState(channel=1, channel_type="InstanceAbyssDungeon", loading=False, entered_at=100.0)
        bot = bot_with(st)
        self.assertTrue(abyss.inside(bot))  # 결과를 놓치면 판 안으로 보이지만
        self.assertFalse(abyss.entered_since(bot, 150.0))  # 다시 하기(150) 뒤에 들어온 맵이 아니다
        st.entered_at = 200.0
        self.assertTrue(abyss.entered_since(bot, 150.0))
        self.assertIsNone(abyss.entered_since(bot_with(PacketState()), 150.0))  # 패킷이 맵을 모름


class WaitDungeonTest(unittest.TestCase):
    def test_cli_failure_is_not_an_answer(self):
        bot = bot_with(PacketState(), act={})  # CLI 가 던전 상태를 못 줌
        with mock.patch("time.monotonic", side_effect=[0, 0, 1, 1, 5, 5, 9, 9]):
            self.assertEqual(content.wait_dungeon(bot, lambda s: s != "InProgress", 4), "")


class SpaceTest(unittest.TestCase):
    def test_unknown_space_counts_as_inside(self):
        self.assertTrue(content.inside_space(bot_with(PacketState(), act={}), "검은 구멍"))
        self.assertFalse(content.inside_space(bot_with(PacketState(), act={}, space="던바튼"), "검은 구멍"))


class BusyTest(unittest.TestCase):
    def test_busy_reasons(self):
        self.assertEqual(display.busy(bot_with(PacketState(abyss_matching=1))), "어비스 안·매칭 중")
        self.assertEqual(display.busy(bot_with(PacketState(dungeon_state="Cleared"))), "던전 안")
        self.assertEqual(display.busy(bot_with(PacketState(), act={"Battlefield": {"IsInBattleField": True}})), "사냥터 안")
        self.assertEqual(display.busy(bot_with(PacketState(), act={}, space="던바튼")), "")


if __name__ == "__main__":
    unittest.main()


class EatTest(unittest.TestCase):
    def _bot(self, came):
        from mabi.bot import Bot
        keys = []
        pk = SimpleNamespace(ok=True, mark=lambda: 0,
                             wait=lambda key, t, after=0: SimpleNamespace(vals={"satiety": 80}) if came else None)
        b = SimpleNamespace(ui={"food_b": "food_b"}, vision=SimpleNamespace(has=lambda n: True), character=None,
                            daily=None, cfg={"run": {}}, no_food=lambda look=True: False, exists=lambda n: True,
                            packets=pk, key=keys.append, log=logging.getLogger("test"), sleep=lambda *a: None)
        return b, keys, Bot.eat_if_hungry

    def test_failed_eat_waits_before_pressing_again(self):
        b, keys, eat = self._bot(came=False)
        self.assertFalse(eat(b))
        self.assertFalse(eat(b))  # 바로 다시 보면 누르지 않는다
        self.assertEqual(keys, ["b"])

    def test_eat_confirmed_by_packet(self):
        b, keys, eat = self._bot(came=True)
        self.assertTrue(eat(b))
        self.assertFalse(eat(b))
        self.assertEqual(keys, ["b"])


class SpearForegroundTest(unittest.TestCase):
    def test_scattered_waterway_runs_in_front(self):
        """흩어진 물길은 뒤에서 돌지 않는다 — 창을 가져오는 데 약 3초 걸려 틱택토가 늦었다 (11-03 사용자)."""
        for dungeon, behind in (("흩어진 물길", False), ("광기의 동굴", True)):
            cfg = {"abyss": {"dungeon": dungeon, "background": True}}
            r = abyss.AbyssRepeat(mock.MagicMock(), cfg)
            r.setup()
            self.assertIs(r.behind, behind)
