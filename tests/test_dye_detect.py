"""염색 도우미 팔레트 자리·색 찾기 (mabi.dye.detect · tracker) — 합성 화면으로.

실제 화면 (2026-10-31, 1920x1080): 팔레트 틀은 늘 같은 자리, 어두운 테두리 13px, 안쪽 모서리 둥긂,
틀 바깥에도 같은 무늬가 흐리게 깔려 있다.
"""
import unittest

import cv2
import numpy as np

from mabi.dye import detect as D
from mabi.dye.tracker import DyeTracker


def screen(w=1920, h=1080, border=True, seed=1):
    """BGR 합성 화면. 전체에 무늬(어둡지 않은 색), 팔레트 자리에 어두운 테두리와 둥근 안쪽 모서리."""
    rng = np.random.default_rng(seed)
    small = rng.integers(90, 256, (h // 8, w // 8, 3), dtype=np.uint8)
    img = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    f = D.Frame(img)
    b = D.palette_rect(f)
    img[: b.y - 40] //= 2  # 틀 바깥은 흐리게 (실제처럼 어둡진 않다)
    if border:
        t = round(D.BORDER_W * h)
        dark = (34, 34, 34)
        keep = img[b.y:b.y + b.h, b.x:b.x + b.w].copy()
        img[b.y - t:b.y + b.h + t, b.x - t:b.x + b.w + t] = dark  # 테두리는 안쪽에 바로 붙는다
        img[b.y:b.y + b.h, b.x:b.x + b.w] = keep
        r = b.corner
        mask = np.zeros((h, w), np.uint8)
        cv2.rectangle(mask, (b.x, b.y), (b.x + b.w - 1, b.y + b.h - 1), 255, -1)
        inner = np.zeros_like(mask)
        cv2.rectangle(inner, (b.x + r, b.y), (b.x + b.w - 1 - r, b.y + b.h - 1), 255, -1)
        cv2.rectangle(inner, (b.x, b.y + r), (b.x + b.w - 1, b.y + b.h - 1 - r), 255, -1)
        for cx, cy in ((b.x + r, b.y + r), (b.x + b.w - 1 - r, b.y + r),
                       (b.x + r, b.y + b.h - 1 - r), (b.x + b.w - 1 - r, b.y + b.h - 1 - r)):
            cv2.circle(inner, (cx, cy), r, 255, -1)
        img[(mask > 0) & (inner == 0)] = dark  # 둥근 모서리 바깥은 테두리 색
    return img, b


class PaletteAtTest(unittest.TestCase):
    def test_found_at_fixed_spot(self):
        img, b = screen()
        got = D.palette_at(D.Frame(img))
        self.assertIsNotNone(got)
        self.assertEqual((got.x, got.y, got.w, got.h), (1075, 283, 749, 749))

    def test_scales_with_resolution(self):
        img, b = screen(1280, 720)
        got = D.palette_at(D.Frame(img))
        self.assertIsNotNone(got)
        self.assertEqual((got.x, got.y), (b.x, b.y))

    def test_no_border_no_palette(self):
        img, _ = screen(border=False)
        self.assertIsNone(D.palette_at(D.Frame(img)))  # 무늬만으로는 팔레트가 아니다 (틀 바깥에도 무늬가 있다)

    def test_dark_screen_is_not_palette(self):
        # 화면 전환 중엔 테두리 자리도 어둡다 — 안쪽까지 어두우면 아니다 (실측 오탐 3장)
        self.assertIsNone(D.palette_at(D.Frame(np.full((1080, 1920, 3), 20, np.uint8))))

    def test_moved_spot_by_ratio(self):
        img, _ = screen()
        at = (0.1, 0.1, 0.3, 0.3)
        self.assertIsNone(D.palette_at(D.Frame(img), at))


class FrameSkipTest(unittest.TestCase):
    def test_black_target_not_on_border(self):
        # 목표가 검정이면 예전엔 테두리에 찍혔다 — 안쪽에 없으면 '없음' 이어야 한다
        img, b = screen()
        f = D.Frame(img)
        box = D.palette_at(f)
        hit = D.find_colors(f, box, [D.target("#222222", 5)], skip=[D.frame_skip(box)])[0]
        self.assertFalse(hit.found)
        self.assertTrue(box.x + box.inset <= hit.x < box.x + box.w - box.inset)
        self.assertTrue(box.y + box.inset <= hit.y < box.y + box.h - box.inset)
        spots = D.find_spots(f, box, [D.target("#222222", 5)], skip=[D.frame_skip(box)])[0]
        self.assertEqual(len(spots), 0)

    def test_black_inside_is_found(self):
        img, b = screen()
        img[600:620, 1400:1420] = (34, 34, 34)
        f = D.Frame(img)
        box = D.palette_at(f)
        hit = D.find_colors(f, box, [D.target("#222222", 5)], skip=[D.frame_skip(box)])[0]
        self.assertTrue(hit.found)
        self.assertTrue(1400 <= hit.x < 1420 and 600 <= hit.y < 620)

    def test_rounded_corner_skipped(self):
        b = D.Palette(100, 100, 200, 200, corner=30, inset=2)
        s = D.frame_skip(b)
        xs, ys = np.array([103, 140, 103]), np.array([103, 103, 200])
        m = D.skip_mask([s], xs, ys)
        self.assertTrue(m[0, 0])       # 모서리 구석 — 뺀다
        self.assertFalse(m[0, 1])      # 위 변 가운데 쪽 — 쓴다
        self.assertFalse(m[2, 0])      # 왼 변 가운데 — 쓴다
        self.assertTrue(D.skip_mask([s], np.array([101]), np.array([200]))[0, 0])  # 섞인 가장자리


class TrackerTest(unittest.TestCase):
    def test_appears_and_disappears_at_once(self):
        t = DyeTracker()
        t.set_targets(["#ffffff"], [5])
        img, _ = screen()
        self.assertEqual(t.tick(img).status, "active")
        # 창을 닫으면 다음 바퀴에 바로 대기 (예전엔 화면이 바뀐 바퀴 25번째에야 다시 봤다)
        self.assertEqual(t.tick(screen(border=False)[0]).status, "waiting")
        self.assertEqual(t.tick(img).status, "active")

    def test_custom_spot(self):
        img, b = screen()
        h, w = img.shape[:2]
        t = DyeTracker(at=(b.x / w, b.y / h, b.w / w, b.h / h))
        self.assertEqual(t.tick(img).status, "active")
        self.assertEqual(DyeTracker(at=(0.1, 0.1, 0.3, 0.3)).tick(img).status, "waiting")


class ViewTest(unittest.TestCase):
    def test_highlight_keeps_only_matches(self):
        img, b = screen()
        img[600:640, 1400:1440] = (40, 200, 60)   # BGR — 목표 #3CC828
        f = D.Frame(img)
        box = D.palette_at(f)
        out = D.highlight(f, box, [D.target("#3CC828", 3)], [D.frame_skip(box)], light=0.3)
        s = D.SHADE_STEP
        self.assertEqual(out.shape, ((box.h + s - 1) // s, (box.w + s - 1) // s, 3))
        y, x = (620 - box.y) // s, (1420 - box.x) // s
        self.assertEqual(tuple(out[y, x]), (60, 200, 40))   # 맞는 자리는 제 색 (RGB)
        far = out[5, 5]
        self.assertTrue(far[0] == far[1] == far[2])          # 나머지는 흑백
        self.assertIsNone(D.highlight(f, box, []))

    def test_tracker_shade_only_when_on(self):
        img, _ = screen()
        t = DyeTracker()
        t.set_targets(["#ffffff"], [5])
        self.assertIsNone(t.tick(img).shade)
        t.set_view(gray=True, light=0.4)
        self.assertIsNotNone(t.tick(img).shade)

    def test_snap_area_to_border(self):
        img, b = screen()
        f = D.Frame(img)
        for drawn in (D.Rect(b.x - 7, b.y + 6, b.w + 10, b.h - 12), D.Rect(b.x + 9, b.y - 8, b.w - 15, b.h + 14)):
            got = D.snap_area(f, drawn)
            self.assertEqual((got.x, got.y, got.w, got.h), (b.x, b.y, b.w, b.h))

    def test_snap_area_without_border_keeps_drawing(self):
        img, _ = screen(border=False)
        r = D.Rect(500, 300, 400, 400)
        self.assertEqual(D.snap_area(D.Frame(img), r), r)


class CleanViewTest(unittest.TestCase):
    def test_defaults_and_limits(self):
        from gui_app.dye_service import clean_view
        self.assertEqual(clean_view(None), {"gray": False, "light": 35, "area": None})
        self.assertEqual(clean_view({"gray": True, "light": 500})["light"], 90)
        self.assertIsNone(clean_view({"area": [0.5, 0.2, 0.01, 0.5]})["area"])   # 너무 작다
        self.assertIsNone(clean_view({"area": [0.5, 0.2, "x", 0.5]})["area"])
        self.assertEqual(clean_view({"area": [0.56, 0.26, 0.39, 0.69]})["area"], [0.56, 0.26, 0.39, 0.69])


if __name__ == "__main__":
    unittest.main()
