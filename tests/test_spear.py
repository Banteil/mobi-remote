"""흩어진 물길 투창병 속성 패턴 — 패킷 상태(spear.SpearState)와 이동 키 고르기."""
import time
import unittest
from types import SimpleNamespace

from mabi.packet_monitor import PacketMonitor
from mabi.spear import SHAMAN_ATTR, SPEAR_ATTR, SPEAR_MARK, TARGET_MARK
from mabi.tasks.spear import SpearDodge
from mabi.tictactoe import FORECAST, choose

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


class TicTacToeTest(unittest.TestCase):
    """보스 틱택토 — 11-03 abyss_runs/boss2 순서 재생과 고르기 (사용자: 첫 X 상하좌우 → 귀퉁이 · 반대 귀퉁이 · 가운데)."""
    BOSS, C = 900, 400

    def setUp(self):
        SpearStateTest.setUp(self)

    enter, feed = SpearStateTest.enter, SpearStateTest.feed

    def walk(self, actor, x, y):
        self.feed("spear.path", actor=actor, points=2, x=x, y=y)

    def turn(self, drawer, x_at):
        self.walk(self.BOSS, *x_at)  # 보스가 칸 가운데로 걸어가 X
        self.feed("spear.timeline", actor=drawer, name=FORECAST)

    def draw(self, drawer, x, y):
        self.m.spear.ttt.turn_at -= 5  # 차례 시작 뒤 몇 초 지나 보스가 담당 자리로 출발
        self.walk(self.BOSS, x, y)

    def test_boss2_replay(self):
        ttt = self.m.spear.ttt
        self.walk(ME, -3.4, 363.3)  # 플레이어 경로 이동은 칸 가운데가 아니라 X 로 안 본다
        self.turn(ME, (0.0, 375.5))
        self.assertTrue(ttt.due())
        job = ttt.take()
        self.assertIn(job["cell"], [(0, 0), (2, 0)])  # X 가 아래 가운데 → 먼 쪽(위) 귀퉁이
        self.draw(ME, -9.6, 375.4)  # 실제로는 사람이 아래 왼쪽에 둠
        self.turn(ME, (9.0, 366.5))
        self.assertEqual(ttt.take()["cell"], (2, 0))  # 반대 귀퉁이 → 가운데가 남아 반드시 이김
        self.draw(ME, 9.4, 358.0)
        self.turn(self.C, (-9.0, 357.5))
        self.assertFalse(ttt.due())  # 다른 캐릭터가 담당
        self.draw(self.C, 0.3, 366.5)
        self.assertTrue(ttt.done)
        self.assertEqual(ttt.text(), "X.O/.OX/OX.")

    def test_boss3_replay(self):
        """11-03 01:32 — 차례 간격 5~6초, 첫 X 왼쪽 가운데."""
        ttt = self.m.spear.ttt
        self.turn(self.C, (-9.0, 366.5))
        self.assertEqual(ttt.board, {(0, 1): "X"})
        self.draw(self.C, -9.5, 375.1)
        self.turn(ME, (9.0, 366.5))
        self.assertEqual(ttt.take()["cell"], (2, 0))
        self.draw(ME, 8.3, 357.5)
        self.turn(ME, (9.0, 375.5))
        self.assertEqual(ttt.take()["cell"], (1, 1))
        self.draw(ME, 0.0, 366.8)
        self.assertTrue(ttt.done)

    def test_choose_plan(self):
        for x1 in [(1, 0), (0, 1), (2, 1), (1, 2)]:  # 첫 X 상하좌우 어디든
            b = {x1: "X"}
            o1 = choose(b)
            self.assertNotIn(o1, [(1, 1)] + [(c, r) for c, r in [(0, 0), (2, 0), (0, 2), (2, 2)] if x1[0] == c or x1[1] == r])
            b[o1] = "O"
            b[(1, 0) if (1, 0) not in b else (1, 2)] = "X"
            o2 = choose(b)
            self.assertEqual(o2, (2 - o1[0], 2 - o1[1]))
            b[o2] = "O"
            self.assertEqual(choose(b), (1, 1))


    def test_choose_messy_party(self):
        """함께하기 — 다른 사람이 가운데·상하좌우에 먼저 둬도 그 판에서 가장 나은 칸 (사용자 11-03)."""
        def pick(t):
            return choose({(c, r): ch for r, row in enumerate(t.split("/")) for c, ch in enumerate(row) if ch != "."})
        self.assertIn(pick(".X./.O./..."), [(0, 2), (2, 2)])  # 가운데 O 를 낀 대각선
        self.assertEqual(pick(".X./O../..."), (2, 1))          # 가운데만 남는 가로줄 → 다음에 반드시
        self.assertEqual(pick(".X./.O./X.O"), (0, 0))          # 바로 이김
        self.assertEqual(pick("X.O/.X./O.."), (2, 2))          # 두 줄 동시


class KeysTest(unittest.TestCase):
    def test_keys_toward(self):
        """11-02 실측 보정 (W = +Y, D = +X)."""
        sd = SpearDodge(None)
        sd.calib = ((0.0, 1.0), (1.0, 0.0))
        self.assertEqual(sd.keys_toward(0, -5), ["s"])
        self.assertEqual(sorted(sd.keys_toward(7, -10)), ["d", "s"])
        self.assertEqual(sd.keys_toward(-3, 0.2), ["a"])

    def test_fight_key_after_return(self):
        """투창병 쪽으로 돌아온 뒤 1 을 3번 — 바로 전투로 (사용자 11-03)."""
        from unittest import mock
        bot = mock.MagicMock()
        sd = SpearDodge(bot)
        sd.go = sd.hold = mock.MagicMock()
        st = mock.MagicMock()
        st.broken_since.return_value = True
        with mock.patch.object(SpearDodge, "st", st), mock.patch.object(SpearDodge, "ok", return_value=True),                 mock.patch("mabi.tasks.spear.time.sleep"):
            sd.dodge({"x": 10, "y": 142, "at": time.monotonic(), "shaman": 1, "attr": "불"})
        self.assertEqual([c.args for c in bot.key.call_args_list], [("1",)] * 3)

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
