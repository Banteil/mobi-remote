"""게임이 위에 띄우는 창(ui.json covers — 연속 실행 제한 창)이 가리는 자리를 판단에 쓰지 않는가.

새 글자 영역·그림 ROI·설정 영역을 그 자리에 두면 CoversTest 가 걸린다 — 그 자리 밖의 신호를 찾거나, 판단에 안 쓰는 것이면
ui.json covered_ok 에 까닭을 적는다. 나머지는 그 자리 대신 쓰는 신호(입장 창·전멸·재료 부족)가 맞게 읽히는지 본다.
"""
import json
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mabi import gamedata as gd
from mabi.monitor import handlers
from mabi.tasks import entry
from mabi.tasks.content import CannotProceed

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
RELATIVE = ("charselect.", "daily_mission.card_title_offset")  # 카드·버튼 기준 상대 좌표 — 화면 자리가 아니다


def _config_rects() -> dict:
    def walk(d, pre=""):
        for k, v in d.items():
            if isinstance(v, dict):
                yield from walk(v, f"{pre}{k}.")
            elif isinstance(v, list) and len(v) == 4 and all(isinstance(i, int) for i in v):
                yield f"{pre}{k}", v
    cfg = tomllib.loads((ROOT / "config.default.toml").read_text(encoding="utf-8"))
    return {f"config/{k}": v for k, v in walk(cfg) if not k.startswith(RELATIVE)}


def _rects() -> dict:
    """화면 자리 이름 → [x, y, 너비, 높이]: ui.json regions(덮는 창 자신 빼고) · 그림 ROI · 설정 영역."""
    ui = json.loads((ROOT / "data" / "ui.json").read_text(encoding="utf-8"))
    out = {k: v for k, v in ui["regions"].items() if k not in gd.covers()}
    index = json.loads((ROOT / "templates" / "index.json").read_text(encoding="utf-8"))
    out.update({f"templates/{k}": v["roi"] for k, v in index.items() if isinstance(v, dict) and v.get("roi")})
    out.update(_config_rects())
    return out


def _frame(name):
    import cv2
    import numpy as np
    p = FIXTURES / name
    if not p.exists():
        raise unittest.SkipTest(f"시험 그림 없음: {name}")
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)


class CoversTest(unittest.TestCase):
    def test_run_limit_popup_is_a_cover(self):
        self.assertIn("run_limit_popup", gd.covers())  # 2026-11-10 친구 스샷으로 잰 자리 (x 701~1218, y 39~236)

    def test_no_unlisted_overlap(self):
        ok = gd.covered_ok()
        bad = {k: (r, gd.covering(r)) for k, r in _rects().items() if gd.covering(r) and k not in ok}
        self.assertEqual(bad, {}, "덮는 창 자리와 겹친다 — 그 자리 밖의 신호로 판단하거나, 판단에 안 쓰면 "
                                  "data/ui.json covered_ok 에 까닭을 적는다")

    def test_allowlist_is_current(self):
        rects = _rects()
        for k in gd.covered_ok():
            with self.subTest(k):
                self.assertIn(k, rects, "없는 영역 — covered_ok 에서 지운다")
                self.assertTrue(gd.covering(rects[k]), "이제 안 겹친다 — covered_ok 에서 지운다")

    def test_covering(self):
        self.assertEqual(gd.covering((960, 100, 10, 10)), ["run_limit_popup"])
        self.assertEqual(gd.covering((960, 300, 10, 10)), [])


class EntryScreenTest(unittest.TestCase):
    """어비스·레이드 입장 창 — 위쪽 탭 대신 오른쪽 아래로 본다 (tasks/entry.py)."""

    def test_entry_under_run_limit_popup(self):
        # 2026-11-10 친구 PC: 전멸 뒤 뜬 입장 창 위에 연속 실행 제한 창 — 탭 글자가 가려 74분 멈췄다
        from mabi import ocr
        from mabi.bot import run_limit_shown
        f = _frame("abyss_entry_run_limit.png")
        self.assertTrue(run_limit_shown(f))
        top = "".join(t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_top")))
        self.assertNotIn(gd.text("abyss_together"), top.replace(" ", ""))  # 탭은 못 읽는다
        self.assertEqual(entry.parse(f), entry.Entry("enter", (True, (1850, 610))))  # 그래도 입장 창 · 함께하기 · 켜짐
        self.assertEqual([t for t, *_ in ocr.find_texts(f, gd.region("abyss_entry_title"))], ["허상의 정박지"])

    def test_abyss_and_raid_entry(self):
        from mabi.bot import run_limit_shown
        f = _frame("abyss_entry_together.png")
        self.assertEqual(entry.parse(f).button, "enter")
        self.assertTrue(entry.parse(f).together)
        self.assertFalse(run_limit_shown(f))
        r = entry.parse(_frame("raid_entry_scas.png"))
        self.assertEqual((r.button, r.together), ("sail", True))

    def test_not_entry(self):
        import numpy as np
        self.assertIsNone(entry.parse(np.zeros((1080, 1920, 3), np.uint8)))


class SetTabTest(unittest.TestCase):
    TOGETHER, SOLO = entry.Entry("enter", (True, (1850, 610))), entry.Entry("enter", None)

    def bot(self, popup=True):
        b = mock.Mock()
        b.run_limit_popup.return_value = popup
        b.snapshot.return_value = Path("x.png")
        return b

    def test_hidden_tab_already_right(self):
        bot = self.bot()
        with mock.patch.object(entry.ui_text, "find", return_value=None), \
                mock.patch.object(entry, "read", return_value=self.TOGETHER):
            entry.set_tab(bot, solo=False, shot="t")
        bot.click.assert_not_called()

    def test_hidden_tab_wrong(self):
        bot = self.bot()
        with mock.patch.object(entry.ui_text, "find", return_value=None), \
                mock.patch.object(entry, "read", return_value=self.SOLO), \
                self.assertRaisesRegex(CannotProceed, "가림"):
            entry.set_tab(bot, solo=False, shot="t")

    def test_visible_tab_is_clicked_and_checked(self):
        bot = self.bot(popup=False)
        with mock.patch.object(entry.ui_text, "find", return_value=(830, 57)), \
                mock.patch.object(entry, "read", return_value=self.SOLO):
            entry.set_tab(bot, solo=True, shot="t")
        bot.click.assert_called_once_with((830, 57))


class WipeTest(unittest.TestCase):
    """전멸은 첫 줄('전멸하였습니다' — 가려지는 자리) 대신 그 아래 '재도전' 줄로 본다."""

    def texts(self, name):
        from mabi import ocr
        return "".join(t for t, *_ in ocr.find_texts(_frame(name), gd.region("abyss_wiped"))).replace(" ", "")

    def test_wiped(self):
        self.assertIn(gd.text("abyss_wiped"), self.texts("abyss_wiped.png"))

    def test_down_is_not_wiped(self):  # 혼자 쓰러짐 — '행동불능 · 부활 제한 구역입니다'
        self.assertNotIn(gd.text("abyss_wiped"), self.texts("abyss_dead_revives3.png"))


class MaterialShortTest(unittest.TestCase):
    """제작·가공 Space 뒤 재료 부족 — 알림(가려질 수 있다)이 아니라 누른 뒤 일이 일어났나로."""

    def run_case(self, looks, toast_at=None, travel=False):
        clock, polls = [0.0], [0]
        bot = mock.Mock()
        bot.cfg = {"arbeit": {"craft_short_toast": "toast"}}
        bot.input_mark = 1
        bot.packets.ok = False
        bot.auto_traveling.return_value = travel
        bot.sleep.side_effect = lambda a, b=None: clock.__setitem__(0, clock[0] + a)
        bot.vision.find.side_effect = lambda frame, name: toast_at is not None and polls[0] >= toast_at
        seq = iter(looks)

        def look(b, frame=None):
            polls[0] += 1
            return SimpleNamespace(what=next(seq, looks[-1]))
        with mock.patch.object(handlers.time, "monotonic", lambda: clock[0]), mock.patch.object(handlers.d, "look", look):
            return handlers.material_short(bot, "craft_go"), bot.key.call_count

    def test_toast_seen(self):
        self.assertEqual(self.run_case(["craft_go"], toast_at=0), (True, 0))

    def test_window_changed(self):
        self.assertEqual(self.run_case(["craft_go", "craft_transfer"]), (False, 0))

    def test_travel_started(self):
        self.assertEqual(self.run_case(["craft_go"], travel=True), (False, 0))

    def test_nothing_happens_twice(self):  # 알림이 가려져도 — 한 번 더 눌러 보고 그래도 그대로면 모자람
        self.assertEqual(self.run_case(["craft_go"]), (True, 1))


if __name__ == "__main__":
    unittest.main()
