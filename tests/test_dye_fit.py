"""염색 맞출 자리 계산 (mabi/dye/fit·autofit) — 합성 팔레트로 복원·측정·해 찾기."""
import math
import unittest

import numpy as np

from mabi.dye import autofit as AF
from mabi.dye import fit as FT


def texture(seed=0, block=6):
    """칸마다 다른 색인 254×254 그림 (행 아래부터) — 실제 팔레트처럼 같은 색 칸이 몇 텍셀씩."""
    rng = np.random.default_rng(seed)
    n = -(-FT.TEX // block)
    cells = rng.integers(0, 256, (n, n, 3), dtype=np.uint8)
    return np.kron(cells, np.ones((block, block, 1), np.uint8))[:FT.TEX, :FT.TEX]


def render(tex, S, pos, rot, scale):
    """게임 계산식대로 팔레트 안쪽 S×S 를 그린다."""
    a, b = FT.grid_ab(S)
    u, v = FT.uv_of(a, b, pos, rot, scale)
    iy, ix = FT._tex(u, v)
    return tex[iy, ix]


class FitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tex = texture()
        cls.S = 320
        cls.pal = FT.Palette(render(cls.tex, cls.S, (0, 0), 0, 1))

    def test_restore(self):
        # 시작 화면 한 장으로 팔레트 대부분이 원래 색 그대로 나온다
        k = self.pal.known
        self.assertGreater(k.mean(), 0.9)
        self.assertTrue((self.pal.bgr[k] == self.tex[k]).mean() > 0.97)

    def test_measure_moved(self):
        pos, rot, scale = (0.07, -0.04), 23.0, 1.0
        c = render(self.tex, self.S, pos, rot, scale)
        m = FT.measure(c, self.pal, scale=1.0)
        self.assertIsNotNone(m)
        m = FT.refine(c, self.pal, m)
        self.assertLess(abs(AF.wrap(m[1] - rot)), 0.2)
        # 위치는 무늬가 되풀이되는 만큼 달라도 같다 → 같은 화면을 그리는지로 본다
        self.assertGreater((render(self.tex, self.S, m[0], m[1], m[2]) == c).all(-1).mean(), 0.9)

    def test_solve_hits_targets(self):
        drops = [(0.3, 0.4), (0.62, 0.7), (0.75, 0.3)]
        rot, scale, pos = 40.0, 1.0, (0.1, 0.05)
        cols = FT.predicted(self.pal, drops, pos, rot, scale)
        tl = [FT.lab_of(np.array([[c]], np.uint8))[0, 0] for c in cols]
        found = FT.solve(self.pal, drops, tl, [3, 3, 3], scales=[1.0], margin_px=0.5, limit=3)
        self.assertTrue(found)
        g = found[0]
        m = (g[2], g[0], g[1])
        self.assertTrue(FT.colors_ok(self.pal, m, drops, tl, [3, 3, 3], margin_px=0.5))
        # 해 텍셀은 해 상태에서 스포이드 바로 위에 있다
        for (a, b), (pa, pb) in zip(drops, FT.goal_points(drops, g, m)):
            self.assertLess(math.hypot(pa - a, pb - b) * self.S, 0.5)


class GuideTest(unittest.TestCase):
    def test_no_goal(self):
        s = AF.Session.__new__(AF.Session)
        s.goal, s.use = None, []
        g = s.guide(((0, 0), 0, 1, 0, 1))
        self.assertFalse(g["done"])
        self.assertEqual(g["points"], [])

    def test_caught_wins(self):
        s = AF.Session.__new__(AF.Session)
        s.goal, s.use = (10.0, 1.0, (0, 0)), [0]
        self.assertTrue(s.guide(None, caught=True)["done"])

    def test_end_points_exact(self):
        # 회전 끝점은 정수 픽셀이어도 0.01° 안쪽으로 맞는다
        for deg in (0.1, -0.37, 5.0, -81.2):
            (sx, sy), (ex, ey), got = AF.end_points(deg, 340)
            self.assertLess(abs(got - deg), 0.01)
            self.assertAlmostEqual(AF.wrap(math.degrees(math.atan2(ey, ex) - math.atan2(sy, sx))), got, 6)

    def test_wheel_scales(self):
        sc = AF.wheel_scales()
        self.assertTrue(all(FT.SCALE_MIN <= s <= FT.SCALE_MAX for s in sc))
        self.assertIn(round(sc[0], 6), (round(1.01 ** 2, 6), round(1.01 ** -2, 6)))   # 1 에 가까운 것부터


class FakeGame:
    """자동 맞추기 상대 — 입력을 받아 상태를 바꾸고 그 상태의 화면을 그린다.
    실기처럼 회전은 처음 1° 가 먹히고, 화면 시계 방향이 rot 를 줄이며, 휠 한 칸은 ×1.01."""

    def __init__(self, tex, S):
        self.tex, self.S = tex, S
        self.pos, self.rot, self.scale = (0.0, 0.0), 0.0, 1.0

    def frame(self):
        return render(self.tex, self.S, self.pos, self.rot, self.scale)

    def rotate(self, cx, cy, deg, r):
        d = math.copysign(max(0.0, abs(deg) - 1.0), deg)
        q = math.radians(-d)
        x, y = self.pos           # 가운데를 축으로 무늬가 돈다
        self.pos = (x * math.cos(q) - y * math.sin(q), x * math.sin(q) + y * math.cos(q))
        self.rot -= d

    def wheel(self, x, y, n):
        k = min(FT.SCALE_MAX, max(FT.SCALE_MIN, self.scale * 1.01 ** n)) / self.scale
        self.scale *= k
        self.pos = (self.pos[0] * k, self.pos[1] * k)

    def drag(self, x1, y1, x2, y2):
        self.pos = (self.pos[0] + (x2 - x1) / self.S, self.pos[1] - (y2 - y1) / self.S)


class AutoDriverTest(unittest.TestCase):
    def test_reaches_goal(self):
        import threading
        from types import SimpleNamespace
        from mabi.dye import detect as D
        tex, S = texture(3), 320
        game = FakeGame(tex, S)
        box = D.Palette(0, 0, S, S)
        rings = [SimpleNamespace(x=round(a * S), y=round((1 - b) * S)) for a, b in ((0.3, 0.4), (0.62, 0.7), (0.75, 0.3))]
        sess = AF.Session(game.frame(), box, rings, [])
        cols = FT.predicted(sess.pal, sess.drops, (0.1, 0.05), 37.0, 1.0)
        tg = [D.target("#%02X%02X%02X" % tuple(int(v) for v in c[::-1]), 3) for c in cols]
        self.assertTrue(sess.solve(tg, budget=20))
        sess.last = ((0.0, 0.0), 0.0, 1.0, 0, 1.0)
        drv = AF.AutoDriver(sess, game.frame, game, threading.Event())
        ok, m = drv.run()
        self.assertTrue(ok)
        self.assertTrue(sess.guide(m)["done"])


class SlotTargetsTest(unittest.TestCase):
    def test_empty_slot_keeps_place(self):
        from mabi.dye.tracker import DyeTracker
        t = DyeTracker()
        t.set_targets(["#112233", "", "#445566"], [None, None, 9])
        st = t.slot_targets()
        self.assertEqual([x and x.hex for x in st], ["#112233", None, "#445566"])
        self.assertEqual(st[2].tol_or_default, 9)


class GuideDrawTest(unittest.TestCase):
    def test_guide_points_and_banner(self):
        from mabi.dye import draw
        from mabi.dye.tracker import DyeState
        st = DyeState("active", "x", "ok")
        gd = {"points": [(1, 100.0, 50.0, 80, 40)], "text": "돌리세요", "done": False}
        items = draw.overlay_items(st, guide=gd, slots=["#112233", "#445566", "#778899"])
        circles = [it for it in items if it.kind == "circle" and it.stroke and it.stroke.color == draw.rgba("#445566")]
        self.assertTrue(any((c.cx, c.cy) == (100, 50) for c in circles))
        self.assertTrue(any(it.kind == "text" and it.text == "돌리세요" for it in items))
        self.assertFalse(any(it.kind == "text" and it.text == "돌리세요"
                             for it in draw.overlay_items(st, slots=None)))


if __name__ == "__main__":
    unittest.main()
