"""게임 단축키 (mabi.keys) — 옵션에서 바꾼 키, 기본값, 검사."""
import unittest
from types import SimpleNamespace
from unittest import mock

from mabi import keys


class KeysTest(unittest.TestCase):
    def test_default_and_override(self):
        self.assertEqual(keys.of(SimpleNamespace(cfg={"game": {}}), "camera"), "z")
        self.assertEqual(keys.of({"game": {"camera_key": "C"}}, "camera"), "c")
        self.assertEqual(keys.of(mock.MagicMock(), "storage"), "x")  # 가짜 봇 (cfg 가 dict 가 아님)
        self.assertEqual(keys.of({"game": {"fast_travel_key": ""}}, "fast_travel"), "")  # 비우면 안 씀

    def test_check(self):
        self.assertIsNone(keys.check("camera", "f5"))
        for k in ("end", "home", "pagedown", ",", "num3", "`"):  # 게임에서 쓰는 다른 키도 (사용자 11-03)
            self.assertIsNone(keys.check("camera", k), k)
        self.assertIsNone(keys.check("fast_travel", ""))
        self.assertIsNotNone(keys.check("camera", ""))
        self.assertIsNotNone(keys.check("camera", "ㅋ"))
        self.assertIsNotNone(keys.check("nope", "z"))

    def test_defaults_match_config_file(self):
        """config.default.toml 의 [game] 키와 GAME_KEYS 기본값이 같아야 옵션 창 '기본값으로' 가 맞다."""
        import tomllib
        from pathlib import Path
        g = tomllib.loads((Path(__file__).parent.parent / "config.default.toml").read_text(encoding="utf-8"))["game"]
        for name, (default, _) in keys.GAME_KEYS.items():
            self.assertEqual(g.get(f"{name}_key"), default, name)

    def test_navigation_keys_are_extended(self):
        """End·Home 등은 확장 키 표시를 붙여 보낸다 — 없으면 게임이 숫자 패드 키로 받는다."""
        from mabi import inputs
        self.assertTrue(inputs._key(inputs.vk_of("end"), up=False).ki.dwFlags & inputs.KEYEVENTF_EXTENDEDKEY)
        self.assertFalse(inputs._key(inputs.vk_of("z"), up=False).ki.dwFlags & inputs.KEYEVENTF_EXTENDEDKEY)


if __name__ == "__main__":
    unittest.main()
