"""값을 둘 자리 규칙이 지켜지는가 (CLAUDE.md '값을 둘 자리').

- 화면 좌표는 data/ui.json (또는 그 기능의 설정 구역) — 태스크 코드에 숫자 좌표를 박아 누르지 않는다
- 조절값은 config.default.toml — 설정에 있는 구역을 cfg.get(구역, {}) 로 감싸 기본값을 또 들지 않는다
- 웹 화면이 기억하는 값은 settings(pref/setPref) — localStorage 를 쓰지 않는다
"""
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _lines(files):
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("#"):
                yield f, i, line


class ValueHomesTest(unittest.TestCase):
    def test_no_literal_coordinates_in_tasks(self):
        # 숫자로 시작하는 좌표 인자: click_xy(130, …) · click((960, …)) · drag(900, …) · long_press(960, …)
        pat = re.compile(r"\b(click_xy|drag|long_press)\(\s*\d|\bclick\(\(\s*\d")
        bad = [f"{f.relative_to(ROOT)}:{i}: {line.strip()}"
               for f, i, line in _lines(sorted((ROOT / "mabi" / "tasks").glob("*.py"))) if pat.search(line)]
        self.assertEqual(bad, [], "좌표는 data/ui.json points/regions 나 설정 구역에 두고 이름으로 읽는다")

    def test_no_double_defaults_for_config_sections(self):
        sections = set(tomllib.loads((ROOT / "config.default.toml").read_text(encoding="utf-8")))
        pat = re.compile(r"cfg\.get\(\"(\w+)\",\s*\{\}\)")
        files = sorted((ROOT / "mabi").rglob("*.py")) + sorted((ROOT / "gui_app").rglob("*.py"))
        bad = [f"{f.relative_to(ROOT)}:{i}: {line.strip()}"
               for f, i, line in _lines(files) for m in pat.finditer(line) if m[1] in sections]
        self.assertEqual(bad, [], "config.default.toml 에 있는 구역은 cfg[구역][키] 로 읽는다 (기본값은 설정 파일 하나)")

    def test_web_has_no_local_storage(self):
        bad = [f"{f.relative_to(ROOT)}:{i}" for f, i, line in _lines(sorted((ROOT / "web").rglob("*.js")))
               if "localStorage" in line and not line.lstrip().startswith(("//", "*", "/*"))]
        self.assertEqual(bad, [], "화면이 기억하는 값은 pref()/setPref() (settings.json) 로")


if __name__ == "__main__":
    unittest.main()
