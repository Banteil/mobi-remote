"""무거운 조회 응답을 데이터 폴더 cache\\ 에 캐시한다 (리모콘 src/cache.js).

get_craftable_items 는 수백 KB 라 매번 받으면 느리다. 신선도는 파일 수정 시각으로 본다.
같은 명령이 동시에 나가면 하나로 합친다(대시보드가 한 틱에 get_currencies 를 두 번 부르던 문제).
게임이 꺼진 걸 알면(offline) CLI 를 부르지 않는다 — 연결 실패 판정에만 약 5초가 걸린다.
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from .connector import Connector

# 명령별 기본 TTL(초). 자주 안 변하는 목록일수록 길게. 0 = 캐시 안 함
TTL = {
    "get_craftable_items": 600, "get_alterable_items": 600, "get_gatherable_items": 600,
    "get_items": 120, "get_music_scores": 3600, "get_instruments": 3600, "get_social_actions": 3600,
    "get_currencies": 60, "get_my_info": 30, "get_daily_missions": 60, "get_weekly_missions": 300,
    "get_quests": 60, "get_inventory": 30, "get_current_environment": 15, "get_activity": 5,
    "get_altering_works": 30,
    "get_near_npcs": 0, "get_near_pcs": 0,  # 움직이면 바로 바뀐다
}
DEFAULT_TTL = 60


class QueryCache:
    def __init__(self, connector: Connector, cache_dir: Path):
        self.cli = connector
        self.dir = cache_dir
        self._inflight: dict[str, threading.Event] = {}
        self._results: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _file(self, command: str) -> Path:
        return self.dir / f"{command}.json"

    def read(self, command: str, max_age: float | None = None) -> dict | None:
        ttl = TTL.get(command, DEFAULT_TTL) if max_age is None else max_age
        if ttl <= 0:
            return None
        f = self._file(command)
        try:
            age = time.time() - f.stat().st_mtime
            if age > ttl:
                return None
            return {"data": json.loads(f.read_text(encoding="utf-8"))["data"], "cached": True, "age": age}
        except (OSError, ValueError, KeyError):
            return None

    def write(self, command: str, data) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._file(command).write_text(json.dumps({"command": command, "savedAt": datetime.now().isoformat(),
                                                      "data": data}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # 캐시 실패는 치명적이지 않다

    def get(self, command: str, refresh: bool = False, max_age: float | None = None, offline: bool = False) -> dict:
        """{data, cached, age, stale?, error?, message?}. 실패하면 만료된 캐시라도 준다 (오프라인 열람)."""
        if not refresh:
            hit = self.read(command, max_age)
            if hit:
                return hit
        if offline:
            stale = self.read(command, float("inf"))
            return {**stale, "stale": True} if stale else {"data": None, "cached": False, "age": 0, "error": "disconnected"}

        with self._lock:
            ev = self._inflight.get(command)
            owner = ev is None
            if owner:
                ev = self._inflight[command] = threading.Event()
        if not owner:
            ev.wait(60)
            return self._results.get(command) or {"data": None, "cached": False, "age": 0, "error": "unknown"}
        try:
            r = self.cli.run(command)
            if r.ok:
                self.write(command, r.data)
                res = {"data": r.data, "cached": False, "age": 0}
            else:
                stale = self.read(command, float("inf"))
                # 옛 값을 주더라도 지금 실패한 이유는 남긴다 — 'not_in_game'(로그인·캐릭터 선택 화면)이면 화면이
                # 옛 캐릭터 정보를 접속 중인 것처럼 보이지 않게 (failed)
                res = {**stale, "stale": True, "failed": r.error} if stale else \
                    {"data": None, "cached": False, "age": 0, "error": r.error or "unknown", "message": r.message}
            self._results[command] = res
            return res
        finally:
            with self._lock:
                self._inflight.pop(command, None)
            ev.set()

    def clear(self, command: str | None = None) -> None:
        for f in ([self._file(command)] if command else list(self.dir.glob("*.json"))):
            try:
                f.unlink()
            except OSError:
                pass
