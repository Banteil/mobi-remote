"""커넥터 호출 기록 (리모콘 src/log.js). 날개가 어디로 갔는지 되짚을 때 여기부터 본다.

logs\\connector-YYYY-MM-DD.log 한 줄씩. 14일 지나면 지우고, 5MB 를 넘으면 .1.log 로 돌린다.
응답 본문은 실패했거나 비용이 나갔을 때만 남긴다 (조회 응답은 수백 KB 라 통째로 쓰면 금방 찬다).
"""
import json
import threading
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

KEEP_DAYS = 14
MAX_BYTES = 5 * 1024 * 1024


class CallLog:
    def __init__(self, logs_dir: Path):
        self.dir = logs_dir
        self.recent: deque = deque(maxlen=200)   # 이번 실행분 (옵션 창에 보여 준다)
        self._lock = threading.Lock()
        self._prune()

    def _file(self) -> Path:
        return self.dir / f"connector-{datetime.now():%Y-%m-%d}.log"

    def _prune(self) -> None:
        cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for f in self.dir.glob("connector-*.log"):
            if f.stem.split("connector-")[-1][:10] < cutoff:
                f.unlink(missing_ok=True)

    def record(self, command: str, body, r) -> None:
        cost = (r.data or {}).get("cost") if isinstance(r.data, dict) else None
        line = {"t": datetime.now().strftime("%H:%M:%S"), "cmd": command, "ok": r.ok, "ms": r.ms}
        if body not in (None, ""):
            line["body"] = body
        if not r.ok:
            line["error"] = r.error
        if cost:
            line["cost"] = cost
        self.recent.append(line)
        text = json.dumps(line, ensure_ascii=False)
        if (not r.ok or cost) and r.data is not None:
            text += " " + json.dumps(r.data, ensure_ascii=False)[:2000]
        with self._lock:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                f = self._file()
                if f.exists() and f.stat().st_size > MAX_BYTES:
                    f.replace(f.with_suffix(".1.log"))
                with f.open("a", encoding="utf-8") as fh:
                    fh.write(text + "\n")
            except OSError:
                pass

    def tail(self, n: int = 300) -> list[str]:
        try:
            return self._file().read_text(encoding="utf-8").splitlines()[-n:]
        except OSError:
            return []
