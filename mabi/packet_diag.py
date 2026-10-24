"""패킷 상태 표가 게임과 안 맞을 때의 기록 (게임 패치 뒤 표를 다시 묶을 때 여기부터 본다).

logs\\packet-YYYY-MM-DD.log 한 줄씩 (calllog 와 같은 규칙: 14일 지나면 지우고, 5MB 를 넘으면 .1.log 로 돌린다).
같은 문제(kind + key)는 처음 한 번만 본문 일부까지 자세히 쓰고, 그 뒤엔 횟수만 센다 — 100번째마다 한 줄, 끝낼 때 summary().
줄마다 표를 묶은 시각·게임 메타데이터 해시(table)를 붙여, 어느 표로 돌다가 어긋났는지 알 수 있게 한다.

kind:
  table_load       표 파일이 없거나 손상·판 번호 다름
  unknown_proto    이름표에 없는 메시지 번호 (패치로 번호가 바뀌었을 가능성)
  short_body       상태 메시지 본문이 읽을 자리보다 짧음 (구조가 바뀜)
  unknown_enum     표에 없는 상태값 (게임에 새 상태)
  unknown_channel  표에 없는 맵 ID (새 던전·맵)
  그 밖            감시 모듈이 record() 로 남기는 것 (expected_missing, stream_desync 등)
"""
import json
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

KEEP_DAYS = 14
MAX_BYTES = 5 * 1024 * 1024
SAMPLE_BYTES = 64
EVERY = 100

log = logging.getLogger("mabi")


class PacketDiag:
    def __init__(self, logs_dir: Path, table_meta: dict | None = None):
        self.dir = logs_dir
        self.table = {k: (table_meta or {}).get(k, "") for k in ("built_at", "game_metadata_sha256")}
        self.counts: Counter = Counter()
        self._lock = threading.Lock()
        self._prune()

    def _file(self) -> Path:
        return self.dir / f"packet-{datetime.now():%Y-%m-%d}.log"

    def _prune(self) -> None:
        cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for f in self.dir.glob("packet-*.log"):
            if f.stem.split("packet-")[-1][:10] < cutoff:
                f.unlink(missing_ok=True)

    def record(self, kind: str, key: str = "", body: bytes | None = None, **info) -> None:
        """문제 하나. key 는 같은 문제를 묶는 이름 (이벤트 키, 메시지 번호 등)."""
        sig = (kind, key)
        with self._lock:
            self.counts[sig] += 1
            n = self.counts[sig]
        if n == 1:
            line = {"kind": kind, "key": key, **info}
            if body is not None:
                line["len"] = len(body)
                line["sample"] = body[:SAMPLE_BYTES].hex(" ")
            log.warning("패킷 표 어긋남: %s %s %s", kind, key, info or "")
            self._write(line)
        elif n % EVERY == 0:
            self._write({"kind": kind, "key": key, "count": n})

    def summary(self) -> None:
        """이번 실행에서 센 문제 전부 (끝낼 때 부른다)."""
        with self._lock:
            rows = [{"kind": k, "key": key, "count": n} for (k, key), n in self.counts.items()]
        if rows:
            self._write({"kind": "summary", "problems": rows})

    def _write(self, line: dict) -> None:
        line = {"t": datetime.now().strftime("%H:%M:%S"), **line, "table": self.table}
        text = json.dumps(line, ensure_ascii=False)
        with self._lock:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                f = self._file()
                if f.exists() and f.stat().st_size > MAX_BYTES:
                    f.replace(f.with_suffix(".1.log"))
                with f.open("a", encoding="utf-8") as fp:
                    fp.write(text + "\n")
            except OSError:
                pass


def open_table(logs_dir: Path):
    """(표 또는 None, 기록기). 표를 못 열면 table_load 로 남기고 None — 패킷 신호 없이 화면 인식만으로 돈다."""
    from . import packet_table
    try:
        table = packet_table.load()
    except (OSError, ValueError) as e:
        diag = PacketDiag(logs_dir)
        diag.record("table_load", type(e).__name__, error=str(e))
        return None, diag
    diag = PacketDiag(logs_dir, table.meta)
    table.diag = diag
    return table, diag
