"""흩어진 물길 투창병 속성 패턴 — 패킷 상태(spear.SpearState)와 이동 키 고르기."""
import time
import unittest
from types import SimpleNamespace

from mabi.packet_monitor import PacketMonitor
from mabi.spear import SHAMAN_ATTR, SPEAR_ATTR, SPEAR_MARK, TARGET_MARK
from mabi.tasks.spear import SpearDodge

ME, OTHER, SPEAR = 100, 200, 300
LAYOUT = {"독": (-10, 142), "번개": (-10, 151), "얼음": (-10, 160), "불": (10, 142), "어둠": (10, 151), "빛": (10, 160)}
SH = {n: 1000 + i for i, n in enumerate(LAYOUT)}
BUFF = {v: k for k, v in SHAMAN_ATTR.items()}
SPEAR_BUFF = {v: k for k, v in SPEAR_ATTR.items()}


class SpearStateTest(unittest.TestCase):
    def setUp(self):
        self.m = PacketMonitor(None)
        self.m.status = "running"
        self.m.state.me = ME
        self.enter("흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)")

    def enter(self, name, kind="InstanceAbyssDungeon"):
        self.m.apply("channel.entering", {"channel": 1, "channel_type": kind, "channel_name": name})

    def feed(self, key, **v):
        self.m._spear(key, v)

    def summon(self):
        for n, (x, y) in LAYOUT.items():
            self.feed("spear.monster", actor=SH[n], x=float(x), y=float(y))
        self.feed("spear.monster", actor=SPEAR, x=0.0, y=0.0)  # 투창병은 이 칸이 위치가 아니다
        self.feed("spear.buff", actor=SPEAR, buff=SPEAR_MARK, caster=SPEAR)
        for n in LAYOUT:
            self.feed("spear.buff", actor=SH[n], buff=BUFF[n], caster=SH[n])

    def throw(self, attr=None, target=ME):
        if attr:
            self.feed("spear.buff", actor=SPEAR, buff=SPEAR_BUFF[attr], caster=SPEAR)
        self.feed("spear.buff", actor=target, buff=TARGET_MARK, caster=SPEAR)

    def test_only_in_scattered_waterway(self):
        self.assertTrue(self.m.spear.active)
        self.enter("다른 어비스")
        self.assertFalse(self.m.spear.active)
        self.enter("흩어진 물길", kind="Field")  # 같은 이름이라도 어비스 맵이 아니면
        self.assertFalse(self.m.spear.active)

    def test_target_me_goes_to_same_attr_shaman(self):
        self.summon()
        self.throw("불")
        st = self.m.spear
        self.assertTrue(st.due())
        job = st.take()
        self.assertEqual((job["attr"], job["x"], job["y"]), ("불", 10, 142))
        self.assertFalse(st.due())  # 한 번 맡으면 끝

    def test_other_character_target_ignored(self):
        """함께하기 — 다른 캐릭터에 걸리면 움직이지 않는다."""
        self.summon()
        self.throw("독", target=OTHER)
        self.assertFalse(self.m.spear.due())

    def test_repeat_same_attr_until_broken(self):
        """못 깨면 속성 버프 없이 대상 표시만 다시 온다 → 남은 속성으로."""
        self.summon()
        self.throw("어둠")
        self.m.spear.take()
        self.throw()
        self.assertEqual(self.m.spear.take()["attr"], "어둠")
        t = time.monotonic() - 1
        self.feed("spear.break", actor=SH["어둠"])
        self.assertTrue(self.m.spear.broken_since(SH["어둠"], t))
        self.assertIsNone(self.m.spear.pending)

    def test_unknown_layout_does_not_move(self):
        self.throw("빛")  # 소환을 못 봄 (판 도중에 켬)
        self.assertTrue(self.m.spear.due())
        self.assertIsNone(self.m.spear.take())

    def test_finished_when_shamans_die(self):
        """투창병이 쓰러지면 주술사도 모두 쓰러진다 → 이 맵의 패턴 끝 (사용자: 주술사가 죽었다 == 투창병이 죽었다)."""
        self.summon()
        for n in LAYOUT:
            self.assertFalse(self.m.spear.finished)
            self.m.apply("actor.dead", {"actor": SH[n], "dead": True})
        self.assertTrue(self.m.spear.finished)
        self.throw("불")
        self.assertFalse(self.m.spear.due())

    def test_new_map_resets(self):
        self.summon()
        self.enter("흩어진 물길 (어비스 시즌2 3구역 매우 어려움2 솔로)")
        self.assertEqual(self.m.spear.attr, {})

    def test_positions_and_spear_home(self):
        self.summon()
        self.feed("spear.move_update", actor=ME, x=1.5, y=160.0)
        self.assertEqual(self.m.spear.where(ME, 1.0), (1.5, 160.0))
        self.assertEqual(self.m.spear.spear_home(), (0.0, 163.0))  # 투창병 자리를 못 봤으면 제자리
        self.feed("spear.move_update", actor=SPEAR, x=3.1, y=0.0)  # 위치가 아닌 값 — 믿지 않는다
        self.assertEqual(self.m.spear.spear_home(), (0.0, 163.0))


class KeysTest(unittest.TestCase):
    def test_keys_toward(self):
        """11-02 실측 보정 (W = +Y, D = +X)."""
        sd = SpearDodge(None)
        sd.calib = ((0.0, 1.0), (1.0, 0.0))
        self.assertEqual(sd.keys_toward(0, -5), ["s"])
        self.assertEqual(sorted(sd.keys_toward(7, -10)), ["d", "s"])
        self.assertEqual(sd.keys_toward(-3, 0.2), ["a"])

    def test_wanted_only_when_active(self):
        m = PacketMonitor(None)
        sd = SpearDodge(SimpleNamespace(packets=m))
        sd.calib = ((0, 1), (1, 0))
        self.assertFalse(sd.wanted())  # 다른 맵
        m.state.me = ME
        m.apply("channel.entering", {"channel": 1, "channel_type": "InstanceAbyssDungeon", "channel_name": "흩어진 물길"})
        m._spear("spear.buff", {"actor": ME, "buff": TARGET_MARK, "caster": SPEAR})
        self.assertTrue(sd.wanted())


if __name__ == "__main__":
    unittest.main()
