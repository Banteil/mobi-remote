"""MabinogiMobile_CLI 의 읽기 전용 조회 명령으로 게임 상태를 얻는다.

화면 판독보다 정확해서 재화 개수, 던전/사망/자동전투 상태, 일일 미션 진행도 판단에 쓴다.
조작(클릭)에는 쓰지 않는다. 게임 설정의 'MM AI 에이전트 활성화'가 꺼져 있거나
(7일마다 만료) CLI 가 없으면 available() 이 False 이고, 호출부는 화면 판독으로 대체한다.
"""
import logging

from .connector import Connector


class GameState:
    def __init__(self, cli: Connector, log: logging.Logger | None = None):
        self.cli = cli
        self.log = log or logging.getLogger("mabi")
        self._ok: bool | None = None

    def query(self, command: str, timeout: float = 30):
        """명령 실행 결과(JSON)를 반환. 연결 실패나 오류 응답이면 None."""
        r = self.cli.run(command, timeout=timeout)
        if not r.ok:
            self.log.debug(f"CLI {command} 실패: {r.error} {str(r.data)[:200]}")
            return None
        return r.data

    def available(self, refresh: bool = False) -> bool:
        if self._ok is None or refresh:
            status = self.query("status", timeout=10)
            self._ok = isinstance(status, dict) and status.get("pipe") == "connected"
        return self._ok

    def currency(self, display_name: str) -> int | None:
        data = self.query("get_currencies")
        if not isinstance(data, list):
            return None
        for c in data:
            if c.get("DisplayName") == display_name:
                return int(c.get("Amount", 0))
        return None

    def activity(self) -> dict | None:
        data = self.query("get_activity")
        return data if isinstance(data, dict) else None
