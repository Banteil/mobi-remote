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

    def test_no_double_defaults_for_config_keys(self):
        # 설정에서 바로 꺼낸 구역 dict 로 config.default.toml 에 있는 키를 .get("키", 값) 으로 읽지 않는다:
        # cfg["구역"].get("키", 값) · 같은 파일에서 x = cfg["구역"] 로 받아 둔 x.get("키", 값).
        # 구역별 by_slot 같은 선택 칸은 config 에 없으니 걸리지 않는다
        conf = tomllib.loads((ROOT / "config.default.toml").read_text(encoding="utf-8"))
        has = lambda sec, key: isinstance(conf.get(sec), dict) and key in conf[sec]  # noqa: E731
        direct = re.compile(r"\[[\"'](\w+)[\"']\]\.get\(\s*[\"'](\w+)[\"']\s*,")
        alias = re.compile(r"((?:self\.)?\w+)\s*=\s*(?:self\.)?(?:bot\.)?(?:cfg|load_config\([^)]*\))\[[\"'](\w+)[\"']\]\s*(?:#.*)?$")
        files = sorted((ROOT / "mabi").rglob("*.py")) + sorted((ROOT / "gui_app").rglob("*.py"))
        bad = []
        for f in files:
            lines = list(_lines([f]))
            names = {}
            for _, _, line in lines:
                if (m := alias.search(line)) and isinstance(conf.get(m[2]), dict):
                    names.setdefault(m[1], set()).add(m[2])
            got = [re.compile(re.escape(n) + r"\.get\(\s*[\"'](\w+)[\"']\s*,") for n in names]
            for _, i, line in lines:
                hit = any(has(m[1], m[2]) for m in direct.finditer(line))
                hit = hit or any(has(s, m[1]) for p, secs in zip(got, names.values()) for m in p.finditer(line) for s in secs)
                if hit:
                    bad.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()}")
        self.assertEqual(bad, [], "config.default.toml 에 있는 키는 cfg[구역][키] 로 읽는다 (기본값은 설정 파일 하나)")

    def test_web_has_no_local_storage(self):
        bad = [f"{f.relative_to(ROOT)}:{i}" for f, i, line in _lines(sorted((ROOT / "web").rglob("*.js")))
               if "localStorage" in line and not line.lstrip().startswith(("//", "*", "/*"))]
        self.assertEqual(bad, [], "화면이 기억하는 값은 pref()/setPref() (settings.json) 로")


if __name__ == "__main__":
    unittest.main()
