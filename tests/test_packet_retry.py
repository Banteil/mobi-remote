"""Npcap 없이 켜진 패킷 감시를, Npcap 을 깐 뒤 리모콘을 다시 켜지 않고 다시 켤 수 있는지 (packet_monitor.start 재호출)."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from mabi import packet_monitor


class FakeCap:
    """첫 번째는 Npcap 이 없는 것처럼, 그다음부터는 열리고 멈추라고 할 때까지 빈 프레임만 준다."""
    made = 0

    def __init__(self):
        FakeCap.made += 1
        if FakeCap.made == 1:
            raise OSError("Npcap 이 설치돼 있지 않음")
        self.device, self.link = "fake", 1

    def next(self):
        time.sleep(0.01)
        return None

    def close(self):
        pass


class RetryTest(unittest.TestCase):
    def test_start_again_after_no_npcap(self):
        FakeCap.made = 0
        table, diag = mock.Mock(), mock.Mock()
        with mock.patch.object(packet_monitor, "_Capture", FakeCap), \
                mock.patch.object(packet_monitor.packet_diag, "open_table", return_value=(table, diag)):
            pm = packet_monitor.PacketMonitor(Path(tempfile.mkdtemp()))
            pm.start()
            pm._thread.join(timeout=2)
            self.assertEqual(pm.status, "no_npcap")
            pm.status = "off"  # api.version_packetRetry 와 같은 순서
            pm.start()
            for _ in range(50):
                if pm.status != "off":
                    break
                time.sleep(0.02)
            self.assertEqual(pm.status, "running")
            pm.stop()
            self.assertFalse(any(t.name == "packet-monitor" and t.is_alive() for t in threading.enumerate()))


if __name__ == "__main__":
    unittest.main()
