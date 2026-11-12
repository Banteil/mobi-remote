"""서버 연결 끊김 단서 (점검 등) — 로그로만 남긴다. 점검 때 무엇이 오는지 본 뒤 판단에 쓸지 정한다 (2026-11-12 사용자).
PacketMonitor 가 상속한다 (self._silent · _opened · _closed · last_rx · state 를 쓴다)."""
import logging
import time

from .stream import decompress

log = logging.getLogger("mabi")

SILENT_LOG = 30      # 게임 안인데 서버 패킷이 이만큼(초) 안 오면 로그 — 하트비트가 약 2초마다 와서 평소 최대 무수신 2.3초 (11월 캡처)


def _hms(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


class LinkWatch:
    def _server_notice(self, key: str, flag: int, body: bytes) -> None:
        """세션 강제 종료·접속 차단 같은 서버 알림 (표의 system.*). 평소엔 안 오는 것들이라(11월 캡처 17분·서버 이동
        12번에 0번) 오면 본문 앞부분까지 남긴다."""
        if flag:
            try:
                body = decompress(body)
            except Exception:  # noqa: BLE001 — 못 풀면 압축된 채로 남긴다
                pass
        log.warning("패킷: 서버 알림 %s — 본문 %d바이트 %s", key, len(body), body[:48].hex(" "))

    def _link(self, src: str, flags: int) -> None:
        """서버 패킷을 받을 때마다: 연결이 열리고(SYN) 닫힌(FIN·RST) 때를 적어 두고, 무수신 로그 뒤 다시 받았으면 한 줄."""
        if self._silent:
            self._silent = False
            log.info("패킷: 서버 패킷 다시 옴 (%.0f초 만)", time.monotonic() - self.last_rx)
        if flags & 0x02:
            self._opened = time.time()
        if flags & 0x05:
            self._closed = (time.time(), "RST" if flags & 0x04 else "FIN", src)

    def _watch_silence(self) -> None:
        """게임 안인데 서버 패킷이 SILENT_LOG 초 넘게 안 오면 한 번 남긴다 — 마지막 연결을 서버가 닫았는지, 열린 채인지와 함께.
        판단에는 아직 안 쓴다. 게임이 켜져 있는지는 여기서 모른다 — 사람이 게임을 꺼도 한 줄 남는다."""
        if self._silent or not self.last_rx or not self.state.in_game:
            return
        gap = time.monotonic() - self.last_rx
        if gap < SILENT_LOG:
            return
        self._silent = True
        if self._closed and self._closed[0] >= self._opened:
            at, how, src = self._closed
            last = f"서버가 {_hms(at)} 에 연결을 닫음 ({how} · {src}), 그 뒤 새 연결 없음"
        else:
            last = "연결은 열린 채" + (f" (마지막 새 연결 {_hms(self._opened)})" if self._opened else "")
        log.info("패킷: 게임 안인데 서버 패킷이 %.0f초째 안 옴%s — %s", gap, " · 맵 로딩 중" if self.state.loading else "", last)
