"""패킷 상태 표(data\\packet-states.bin) 테스트. 본문 바이트는 실제 던전 캡처에서 가져왔다."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mabi import packet_diag, packet_table, paths
from mabi.packet_diag import PacketDiag
from mabi.packet_table import Table, seal, unseal


def bundled() -> Table:
    # 데이터 폴더의 덮어쓰기 판이 아니라 저장소에 든 판을 시험한다
    return Table(unseal((paths.resource_dir() / "data" / packet_table.FILE_NAME).read_bytes()))


# 키는 저장소에 없다 (개발 PC 에만) — 없으면 표를 쓰는 시험은 건너뛴다
needs_key = unittest.skipUnless(packet_table.key_file().exists(), "packet.key 없음")


@needs_key
class SealTest(unittest.TestCase):
    def test_round_trip(self):
        data = {"a": [1, 2, 3], "한글": "값"}
        self.assertEqual(unseal(seal(data)), data)

    def test_nonce_differs(self):
        self.assertNotEqual(seal({"a": 1}), seal({"a": 1}))

    def test_tamper_detected(self):
        blob = bytearray(seal({"a": 1}))
        blob[30] ^= 1
        with self.assertRaises(ValueError):
            unseal(bytes(blob))

    def test_not_a_table(self):
        with self.assertRaises(ValueError):
            unseal(b"{}" * 40)


@needs_key
class DecodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = bundled()

    def decode(self, key: str, hexbody: str):
        ev = self.t.by_key(key)
        self.assertIsNotNone(ev, key)
        got = self.t.decode(ev.proto, bytes.fromhex(hexbody))
        self.assertIsNotNone(got)
        return got[1]

    def test_dungeon_state(self):
        self.assertEqual(self.decode("dungeon.state", "02000000")["state_name"], "InProgress")
        self.assertEqual(self.decode("dungeon.state", "03000000")["state_name"], "Cleared")
        self.assertEqual(self.decode("dungeon.state", "00000000")["state_name"], "NotInDungeon")

    def test_entering_channel(self):
        v = self.decode("channel.entering", "ac78730b0040108272")
        self.assertEqual(v["channel"], 192116908)
        self.assertEqual(v["channel_type"], "InstanceDungeon")
        v = self.decode("channel.entering", "7b47393594750000")
        self.assertEqual(v["channel_type"], "Field")

    def test_unknown_channel_is_empty(self):
        v = self.decode("dungeon.current", "00000000")
        self.assertEqual((v["channel"], v["channel_name"], v["channel_type"]), (0, "", ""))

    def test_server_change_address(self):
        addr = "3.34.137.171:16000".encode("utf-16le")
        v = self.decode("channel.server_change", len(addr).to_bytes(4, "little").hex() + addr.hex())
        self.assertEqual(v["address"], "3.34.137.171:16000")

    def test_short_body_skips_field(self):
        self.assertEqual(self.decode("dungeon.state", "02"), {})

    def test_not_state_event(self):
        # 0x030d4b 는 게임에 있는 메시지(하트비트)지만 상태 이벤트는 아니다
        self.assertIn(0x030D4B, self.t.known)
        self.assertIsNone(self.t.decode(0x030D4B, b""))

    def test_channel_names_only_where_needed(self):
        self.assertEqual(self.t.channel(192116908)["name"], "북쪽 폐허 심층 던전 4-1 매우 어려움")
        self.assertTrue(all("name" not in c for c in self.t.channels.values() if c["type"] == "MiniGame"))

    def test_enum_fields_resolve(self):
        for ev in self.t.events():
            for f in ev.fields:
                if f.enum:
                    self.assertTrue(self.t.enum(f.enum), f"{ev.key}: {f.enum}")


@needs_key
class DiagTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.t = bundled()
        self.t.diag = PacketDiag(self.dir, self.t.meta)
        quiet = mock.patch.object(packet_diag.log, "warning")
        quiet.start()
        self.addCleanup(quiet.stop)

    def lines(self) -> list[dict]:
        out = []
        for f in self.dir.glob("packet-*.log"):
            out += [json.loads(s) for s in f.read_text(encoding="utf-8").splitlines()]
        return out

    def proto(self, key: str) -> int:
        return self.t.by_key(key).proto

    def test_problems_logged(self):
        self.t.decode(self.proto("dungeon.state"), bytes.fromhex("07000000"))   # 표에 없는 상태값
        self.t.decode(self.proto("dungeon.state"), b"\x02")                     # 본문 짧음
        self.t.decode(self.proto("channel.entering"), bytes.fromhex("01020304"))  # 처음 보는 맵
        self.t.decode(0xFFFFFF, b"\x01\x02")                                   # 이름표에 없는 번호
        kinds = {(r["kind"], r["key"]) for r in self.lines()}
        self.assertEqual(kinds, {
            ("unknown_enum", "dungeon.state.state=7"),
            ("short_body", "dungeon.state"),
            ("unknown_channel", str(0x04030201)),
            ("unknown_proto", "0xffffff"),
        })
        first = next(r for r in self.lines() if r["kind"] == "unknown_proto")
        self.assertEqual(first["sample"], "01 02")
        self.assertEqual(first["table"]["built_at"], self.t.meta["built_at"])

    def test_known_values_not_logged(self):
        self.t.decode(self.proto("dungeon.state"), bytes.fromhex("03000000"))
        self.t.decode(self.proto("dungeon.current"), bytes.fromhex("00000000"))  # 0 = 던전 없음
        self.assertEqual(self.lines(), [])

    def test_repeats_counted_not_written(self):
        for _ in range(packet_diag.EVERY):
            self.t.decode(0xFFFFFF, b"")
        rows = self.lines()
        self.assertEqual(len(rows), 2)  # 처음 한 번 + 100번째
        self.assertEqual(rows[-1]["count"], packet_diag.EVERY)
        self.t.diag.summary()
        self.assertEqual(self.lines()[-1]["problems"], [{"kind": "unknown_proto", "key": "0xffffff", "count": 100}])

    def test_missing_key_is_table_load_problem(self):
        packet_table._keys.cache_clear()
        self.addCleanup(packet_table._keys.cache_clear)
        with mock.patch.object(packet_table, "key_file", return_value=self.dir / "없음.key"):
            with self.assertRaises(FileNotFoundError):
                bundled()

    def test_table_load_failure(self):
        with mock.patch.object(packet_table, "load", side_effect=ValueError("손상")):
            table, diag = packet_diag.open_table(self.dir)
        self.assertIsNone(table)
        self.assertEqual(self.lines()[0]["kind"], "table_load")


if __name__ == "__main__":
    unittest.main()
