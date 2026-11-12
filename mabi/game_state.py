"""MabinogiMobile_CLI 의 읽기 전용 조회 명령으로 게임 상태를 얻는다.

화면 판독보다 정확해서 재화 개수, 던전/사망/자동전투 상태, 일일 미션 진행도 판단에 쓴다.
조작(클릭)에는 쓰지 않는다. 게임 설정의 'MM AI 에이전트 활성화'가 꺼져 있거나
(7일마다 만료) CLI 가 없으면 available() 이 False 이고, 호출부는 화면 판독으로 대체한다.
"""
import logging
from dataclasses import dataclass

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


NOT_IN_DUNGEON = "NotInDungeon"  # CLI Dungeon.State — 던전 밖 (안이면 Entering / InProgress / Cleared)


@dataclass(frozen=True)
class Activity:
    """CLI get_activity 답을 읽은 것. 키 이름과 중첩(Dungeon.State·Battlefield.IsInBattleField·Mode …)은 여기서만 안다 —
    던전·사냥터 안팎과 '바쁨' 을 패킷 감시·자리·점검자·태스크가 저마다 다르게 읽던 것을 하나로 (2026-11-12).
    답이 없으면(None) 모든 값이 '아님'(False·None) 이다 — 모름과 가르려면 답이 있는지를 따로 본다."""
    dungeon: str | None = None       # Dungeon.State (없으면 None)
    boss_battle: bool = False        # Dungeon.IsBossBattleInProgress
    in_field: bool = False           # Battlefield.IsInBattleField — 사냥터 안 (클리어 뒤 채널 옮김 대기 포함)
    dead: bool = False               # IsDead
    traveling: bool = False          # IsAutoTraveling
    travel_left: int = 0             # AutoTravelRemainingPositionCount — 남은 경로 점
    combat: bool = False             # IsInCombat
    dialogue: bool = False           # IsDialoguePlaying
    dialogue_next: bool = False      # IsDialogueNextAvailable — 넘길 대사가 있음
    selecting: bool = False          # IsWaitingForSelection — 선택지 기다림
    auto_playing: bool = False       # IsAutoPlaying
    minigame: bool = False           # Mode.IsPlayingMiniGame
    abyss_result: bool = False       # IsAbyssResultSequencePlaying

    # '바쁨' 을 이루는 것 (이름, 칸) — 점검자의 멈춰 있음 판단(detect.idle·busy_why·cli_idle)
    BUSY = (("자동 진행", "auto_playing"), ("자동 이동", "traveling"), ("대화", "dialogue"), ("전투", "combat"))

    @classmethod
    def of(cls, act: dict | None) -> "Activity":
        if not act:
            return cls()
        dun = act.get("Dungeon") or {}
        return cls(
            dungeon=dun.get("State") or None,
            boss_battle=bool(dun.get("IsBossBattleInProgress")),
            in_field=bool((act.get("Battlefield") or {}).get("IsInBattleField")),
            dead=bool(act.get("IsDead")),
            traveling=bool(act.get("IsAutoTraveling")),
            travel_left=act.get("AutoTravelRemainingPositionCount") or 0,
            combat=bool(act.get("IsInCombat")),
            dialogue=bool(act.get("IsDialoguePlaying")),
            dialogue_next=bool(act.get("IsDialogueNextAvailable")),
            selecting=bool(act.get("IsWaitingForSelection")),
            auto_playing=bool(act.get("IsAutoPlaying")),
            minigame=bool((act.get("Mode") or {}).get("IsPlayingMiniGame")),
            abyss_result=bool(act.get("IsAbyssResultSequencePlaying")),
        )

    @property
    def in_dungeon(self) -> bool:
        """던전 안 (들어가는 중·진행 중·클리어 뒤 포함)."""
        return self.dungeon not in (None, NOT_IN_DUNGEON)

    @property
    def busy(self) -> bool:
        """자동 진행·자동 이동·대화·전투 중 하나라도."""
        return any(getattr(self, f) for _, f in self.BUSY)
