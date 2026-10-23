"""실행 리포트: 실행 한 번마다 logs/runs/<시작시각>.json 에 환경, 캐릭터별·숙제별 결과, 경고 이벤트를 남긴다.

다른 계정·PC 에서 돌렸을 때 무엇이 어디서 실패했는지 보기 위한 기록이다.
숙제가 끝날 때마다 파일을 다시 써서, 도중에 꺼져도 그때까지의 기록은 남는다.
요약과 내보내기는 tools/report.py 로 한다.
"""
import ctypes
import json
import logging
import platform
import time
from datetime import datetime
from pathlib import Path

from . import gamedata as gd

VERSION = "0.2.0"


class _EventHandler(logging.Handler):
    """WARNING 이상 로그를 지금 진행 중인 숙제의 이벤트로 모은다."""

    def __init__(self, report: "RunReport"):
        super().__init__(logging.WARNING)
        self.report = report

    def emit(self, record: logging.LogRecord) -> None:
        self.report.event(record.levelname, record.getMessage())


class RunReport:
    def __init__(self, runs_dir: Path, cfg: dict, bot, args: dict):
        self.dir = runs_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        started = datetime.now()
        self.path = self.dir / f"{started:%Y%m%d_%H%M%S}.json"
        self.bot = bot
        self.data = {
            "version": VERSION,
            "started": started.isoformat(timespec="seconds"),
            "finished": None,
            "args": args,
            "env": self._env(cfg, bot),
            "characters": [],
            "events": [],  # 숙제 밖에서 생긴 이벤트
        }
        self._char = None
        self._task = None
        logging.getLogger("mabi").addHandler(_EventHandler(self))
        self.save()

    @staticmethod
    def _env(cfg: dict, bot) -> dict:
        try:
            r = bot.window.client_rect()
            client = [r.width, r.height]
        except Exception:
            client = None
        return {
            "os": platform.platform(),
            "python": platform.python_version(),
            "admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
            "client_size": client,
            "cli": bot.state.available(refresh=True),
            "order": cfg["run"]["order"],
            "silver": cfg["silver"],
            }

    def _counters(self) -> dict:
        """은동전·공물·골드·가방 무게 (CLI). 실패한 값은 None."""
        st = self.bot.state
        if not st.available():
            return {}
        cur = {c.get("DisplayName"): c.get("Amount") for c in st.query("get_currencies", timeout=10) or []
               if isinstance(c, dict)}
        out = {k: cur.get(gd.currency(k)) for k in ("silver", "tribute", "gold")}
        inv = st.query("get_inventory", timeout=10) or {}
        if inv:
            out["weight"] = [round(inv.get("CurrentInventoryWeight", 0)), round(inv.get("MaxInventoryWeight", 0))]
        return out

    def character(self, ch: dict | None) -> None:
        self._char = {"slot": ch["slot"] if ch else None, "name": ch["name"] if ch else None, "tasks": []}
        self.data["characters"].append(self._char)
        self.save()

    def task_start(self, tid: str) -> None:
        self._task = {"id": tid, "start": datetime.now().isoformat(timespec="seconds"), "status": None,
                      "summary": None, "seconds": None, "before": self._counters() if tid != "login" else {},
                      "after": {}, "events": []}
        self._t0 = time.monotonic()
        if self._char is not None:
            self._char["tasks"].append(self._task)

    def task_end(self, status: str, summary: str) -> None:
        t = self._task
        if t is None:
            return
        t["status"], t["summary"] = status, summary
        t["seconds"] = round(time.monotonic() - self._t0)
        if status not in ("STOP",):
            t["after"] = self._counters()
        self._task = None
        self.save()

    def event(self, kind: str, message: str) -> None:
        e = {"time": datetime.now().strftime("%H:%M:%S"), "kind": kind, "message": message}
        (self._task["events"] if self._task else self.data["events"]).append(e)

    def finish(self, results: list) -> None:
        self.data["finished"] = datetime.now().isoformat(timespec="seconds")
        self.data["results"] = [{"label": l, "status": s, "summary": m} for l, s, m in results]
        self.save()

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass
