"""보스전 궁극기·팔라딘 변신 (mabi.tasks.boss_skills) — 패킷 상태와 캐릭터별 설정으로 누를지 가르기."""
import logging
import time
import unittest
from unittest import mock

from mabi.packet_monitor import PacketMonitor
from mabi.tasks.abyss import AbyssRepeat
from mabi.tasks.boss_skills import BossSkills
from mabi.tasks.raid import RaidRepeat

ABYSS = "InstanceAbyssDungeon"


class FakeBot:
    def __init__(self):
        self.packets = PacketMonitor(None)
        self.packets.status = "running"
        self.packets.last_rx = time.monotonic()
        self.cfg = {"game": {"ultimate_key": "6", "paladin_key": "f5"},
                    "boss_skills": {"ultimate_slots": [1], "paladin_slots": [2]}}
        self.log = logging.getLogger("test")
        self.keys = []

    def key(self, k):
        self.keys.append(k)

    def enter(self, kind):
        self.packets.apply("channel.leaving", {})
        self.packets.apply("channel.entering", {"channel": 1, "channel_type": kind, "channel_name": ""})

    def gauge(self, v):  # abyss1 처럼 두 게이지가 같은 값으로 오르고 궁극기는 300 에서 멈춘다
        self.packets.apply("ultimate.resource", {"ult_max": 300.0, "ult": min(v, 300.0), "pal_max": 500.0, "pal": v})


def abyss_fight(s):
    return AbyssRepeat.boss_fight(None, s)


class BossSkillsTest(unittest.TestCase):
    def test_abyss_boss_after_campfire_in_combat(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(500)
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 모닥불 전 — 보스전 아님
        bot.packets.apply("abyss.campfire", {})
        self.assertFalse(sk.tick({"IsInCombat": False}))  # 모닥불 앞에서 쉬는 중
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])  # 팔라딘 먼저
        sk.pressed.clear()
        bot.gauge(300)  # 변신에 썼다 — 궁극기 게이지는 그대로 차 있어도
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])  # 변신 중엔 6 이 변신 해제 → 이 맵에서는 궁극기를 안 누른다
        bot.enter(ABYSS)  # 다음 판
        bot.packets.apply("abyss.campfire", {})
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5", "6"])
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 방금 눌렀다 — RETRY 동안 안 누른다

    def test_no_ultimate_while_transformed_by_packet(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("abyss.campfire", {})
        bot.gauge(300)
        sk = BossSkills(bot, True, False, abyss_fight)
        bot.packets.apply("transfigure.current", {"id": 7})  # 사람이 직접 변신
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("transfigure.current", {"id": 0})
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])

    def test_gauge_not_full(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("abyss.campfire", {})
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(350)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])  # 궁극기만 찼다

    def test_separate_switches(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("abyss.campfire", {})
        bot.gauge(500)
        sk = BossSkills(bot, False, True, abyss_fight)
        sk.tick({"IsInCombat": True})
        sk.pressed.clear()
        sk.tick({"IsInCombat": True})
        self.assertEqual(bot.keys, ["f5", "f5"])  # 궁극기는 꺼짐

    def test_no_paladin_here_or_cutscene_or_new_map(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("abyss.campfire", {})
        bot.gauge(500)
        bot.packets.apply("ultimate.can_paladin", {"on": False})
        sk = BossSkills(bot, False, True, abyss_fight)
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("ultimate.can_paladin", {"on": True})
        bot.packets.apply("cutscene.play", {})
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("cutscene.end", {})
        bot.enter(ABYSS)  # 다음 판 — 모닥불은 지워진다
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, [])

    def test_raid_boss_signal(self):
        bot = FakeBot()
        bot.enter("InstanceRaid")
        bot.packets.apply("abyss.campfire", {})  # 레이드는 맵 진입 때도 모닥불이 온다 — 그걸로 보지 않는다
        bot.gauge(300)
        sk = BossSkills(bot, True, False, lambda s: RaidRepeat.boss_fight(None, s))
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("raid.boss_begin", {})
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])

    def test_per_character(self):
        bot = FakeBot()
        one = BossSkills.for_character(bot, bot.cfg, 1, abyss_fight)
        two = BossSkills.for_character(bot, bot.cfg, 2, abyss_fight)
        nobody = BossSkills.for_character(bot, bot.cfg, None, abyss_fight)
        self.assertEqual(one.describe(), "궁극기")
        self.assertEqual(two.describe(), "팔라딘 변신")
        self.assertFalse(nobody.enabled)

    def test_repeat_round_passes_tick(self):
        rep = mock.Mock()
        rep.stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0}
        rep.a = {"run_timeout": 60}
        from mabi.tasks.repeat import Repeat
        play = mock.Mock(return_value="clear")
        self.assertEqual(Repeat.play_round(rep, play, "abyss_play"), "clear")
        self.assertIs(play.call_args.kwargs["tick"], rep.skills.tick)


if __name__ == "__main__":
    unittest.main()
