"""게임이 위에 띄우는 창(ui.json covers — 연속 실행 제한 창)이 가리는 자리를 판단에 쓰지 않는가.

새 글자 영역·그림 ROI·설정 영역을 그 자리에 두면 CoversTest 가 걸린다 — 그 자리 밖의 신호를 찾거나, 판단에 안 쓰는 것이면
ui.json covered_ok 에 까닭을 적는다. 나머지는 그 자리 대신 쓰는 신호(입장 창·전멸·결과 창)가 맞게 읽히는지와
창 감지(run_limit_shown — 게임 다시 켜기의 신호)를 본다.
"""
import json
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from mabi import gamedata as gd
from mabi.tasks import entry
from mabi.exceptions import CannotProceed

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


class ResultConfirmTest(unittest.TestCase):
    """레이드·필드 보스 결과 창은 위쪽 '처치 완료'(창 자리 y 약 216) 대신 아래 가운데 '확인' 으로 본다 (content.confirm_text).
    2026-11-11 화이트 서큐버스 결과 창 — 버튼 띠만 남긴 그림."""

    def test_raid_result(self):
        from mabi.tasks.content import confirm_text
        x, y = confirm_text(_frame("raid_result_confirm.png"))
        self.assertTrue(abs(x - 959) < 15 and abs(y - 1009) < 15)


class RunLimitShownTest(unittest.TestCase):
    """제한 창 감지는 '종료' 버튼 색을 먼저 본다 — 끊는 자리마다 부르므로 창이 없으면 글자를 읽지 않는다."""

    def test_popup(self):
        from mabi.bot import run_limit_shown
        self.assertTrue(run_limit_shown(_frame("abyss_entry_run_limit.png")))

    def test_no_popup_skips_ocr(self):
        from mabi.bot import run_limit_shown
        with mock.patch("mabi.ocr.find_texts") as ocr:
            for name in ("abyss_entry_together.png", "raid_entry_scas.png", "raid_result_confirm.png"):
                self.assertFalse(run_limit_shown(_frame(name)), name)
        ocr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
