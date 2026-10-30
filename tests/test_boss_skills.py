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
        self.packets.state.me = 14000001

    def key(self, k):
        self.keys.append(k)

    def enter(self, kind):
        self.packets.apply("channel.leaving", {})
        self.packets.apply("channel.entering", {"channel": 1, "channel_type": kind, "channel_name": ""})

    def boss(self):  # 모닥불 → 보스방 → 보스 등장 연출 (2026-10-30 실측)
        self.packets.apply("abyss.campfire", {})
        self.packets.apply("cutscene.play", {})
        self.packets.apply("cutscene.end", {})

    def transfigure(self):  # 변신 패킷 (시작·끝에 한 번씩, [0:4] 내 캐릭터 번호)
        self.packets.apply("transfigure.current", {"actor": self.packets.state.me})

    def gauge(self, v):  # abyss1 처럼 두 게이지가 같은 값으로 오르고 궁극기는 300 에서 멈춘다
        self.packets.apply("ultimate.resource", {"ult_max": 300.0, "ult": min(v, 300.0), "pal_max": 500.0, "pal": v})


def abyss_fight(s):
    return AbyssRepeat.boss_fight(None, s)


class BossSkillsTest(unittest.TestCase):
    def test_abyss_boss_is_after_campfire_scene(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(500)
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 모닥불 전
        bot.packets.apply("abyss.campfire", {})
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 모닥불 뒤 보스방 앞 잡몹 — 아직 (16:49:27 에 일찍 변신했다)
        bot.packets.apply("cutscene.play", {})
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 보스 등장 연출 중
        bot.packets.apply("cutscene.end", {})
        self.assertFalse(sk.tick({"IsInCombat": False}))
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])  # 팔라딘 먼저

    def test_weekly_entry_scene_is_not_boss(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("cutscene.play", {})  # 주마다 첫 입장 연출 (모닥불 전)
        bot.packets.apply("cutscene.end", {})
        self.assertFalse(abyss_fight(bot.packets.state))

    def test_started_mid_run(self):
        bot = FakeBot()  # 판 도중에 리모콘을 켬 — 맵 진입·모닥불을 못 봤다
        bot.packets.apply("cutscene.play", {})
        bot.packets.apply("cutscene.end", {})
        self.assertTrue(abyss_fight(bot.packets.state))

    def test_no_ultimate_while_transformed(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 시작 패킷 전 — 변신 중으로 본다
        bot.transfigure()  # 변신 시작
        bot.gauge(300)
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])  # 변신 중엔 6 이 변신 해제
        bot.transfigure()  # 20초 뒤 끝
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5", "6"])  # 끝나면 궁극기 (예전엔 패킷 앞 번호를 변신 번호로 읽어 판 내내 막혔다)
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 방금 눌렀다 — RETRY 동안 안 누른다

    def test_end_packet_missed(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, True, False, abyss_fight)
        bot.gauge(300)
        bot.transfigure()  # 사람이 직접 변신
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.state.transform_start -= 24  # 끝 패킷을 놓쳤다 — 변신 시간으로 끊는다
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])

    def test_transform_counts_when_me_unknown(self):
        bot = FakeBot()
        bot.packets.state.me = None  # 판 도중에 리모콘을 켬 — 내 등장 메시지를 못 봤다
        bot.packets.apply("transfigure.current", {"actor": 123})
        self.assertTrue(bot.packets.state.transform_start)

    def test_party_member_transform_ignored(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.packets.apply("transfigure.current", {"actor": 123})
        self.assertEqual(bot.packets.state.transform_start, 0.0)

    def test_paladin_once_per_dungeon_and_gauge_reset(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, False, True, abyss_fight)
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        bot.transfigure()
        bot.transfigure()
        sk.pressed["팔라딘 변신"] -= 30
        bot.gauge(500)  # 같은 던전에서 다시 차도 변신은 한 번뿐
        self.assertFalse(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["f5"])
        bot.enter(ABYSS)  # 다시 하기 — 게이지가 처음으로
        self.assertEqual((bot.packets.state.ult, bot.packets.state.pal), (0.0, 0.0))
        bot.boss()
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))  # 새 던전에선 다시 한 번
        self.assertEqual(bot.keys, ["f5", "f5"])

    def test_paladin_key_missed_retries_then_gives_up(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, False, True, abyss_fight)
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))  # F5 — 시작 패킷이 안 옴 (보스 연출 직후 · 2026-10-30 17:33)
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 기다리는 동안엔 다시 안 누른다
        for _ in range(2):
            sk.pressed["팔라딘 변신"] -= 9
            self.assertTrue(sk.tick({"IsInCombat": True}))
        sk.pressed["팔라딘 변신"] -= 9
        self.assertFalse(sk.tick({"IsInCombat": True}))  # 세 번 안 됨 → 이 맵에선 포기
        self.assertEqual(bot.keys, ["f5", "f5", "f5"])
        bot.enter(ABYSS)  # 다음 판엔 다시
        bot.boss()
        bot.gauge(500)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys[-1], "f5")

    def test_gauge_not_full(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        sk = BossSkills(bot, True, True, abyss_fight)
        bot.gauge(350)
        self.assertTrue(sk.tick({"IsInCombat": True}))
        self.assertEqual(bot.keys, ["6"])  # 궁극기는 300 에서 참

    def test_no_paladin_here_or_cutscene_or_new_map(self):
        bot = FakeBot()
        bot.enter(ABYSS)
        bot.boss()
        bot.gauge(500)
        bot.packets.apply("ultimate.can_paladin", {"on": False})
        sk = BossSkills(bot, False, True, abyss_fight)
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("ultimate.can_paladin", {"on": True})
        bot.packets.apply("cutscene.play", {})
        self.assertFalse(sk.tick({"IsInCombat": True}))
        bot.packets.apply("cutscene.end", {})
        bot.enter(ABYSS)  # 다음 판 — 보스 연출 표시는 지워진다
        bot.gauge(500)
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
