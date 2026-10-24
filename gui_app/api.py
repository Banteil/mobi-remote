"""웹 화면(web/app.js)이 window.mm.* 로 부르는 파이썬 쪽 (레거시 app/main.js 의 ipcMain.handle 들을 옮긴 것).

메서드 이름은 bridge.js 의 호출 이름에서 '.' 을 '_' 로 바꾼 것이다 ('kn.setLevel' → kn_setLevel).
web_shell.Backend 가 **작업 스레드**에서 부르고 돌려준 값을 JSON 으로 보낸다. 그래서
- 돌려주는 모양은 레거시와 같아야 한다 (화면 코드가 그대로라서). 조회 결과 모양은 legacy_shapes 가 맞춘다.
- Qt 창(파일 고르기 등)은 화면 스레드에서만 열 수 있다 → _GuiCall 로 화면 스레드에 넘겨 끝날 때까지 기다린다.
- 이벤트(mm:exec-start 등)는 win.backend.emit_event 로 보낸다 (어느 스레드에서 불러도 된다).

daily.* 는 DailyApi(daily_api.py)를 섞어 붙인다. 염색 캡처(dye.start/stop)는 DyeService(dye_service.py)가 한다.
"""
import base64
import copy
import json
import logging
import os
import re
import shutil
import threading
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from mabi import craft, errors, gamedata
from mabi.cache import QueryCache
from mabi.calllog import CallLog
from mabi.compat import LEVELS, Compat, cli_version, semver
from mabi.connector import ACTION_COMMANDS, EXE_NAME, Connector
from mabi.craft import goal, plan
from mabi.craft import queue as craft_queue
from mabi.craft.execute import execute
from mabi.dye.presets import PresetStore
from mabi.nudge import CursorNudge
from mabi.store import Favorites, Playlists

from .chars_api import CharsApi
from .daily_api import DailyApi
from .queue_api import QueueApi
from .dye_service import DyeService
from .dye_tab import exclude_from_capture
from .legacy_shapes import Shapes

log = logging.getLogger("mabi")

APP_NAME = "모비 커넥터 리모콘"
APP_VERSION = "3.2.1"


def _ver(v: str) -> tuple:
    """'v3.10.0' → (3, 10, 0). 문자열로 견주면 3.10 이 3.9 보다 작아진다."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])

# 예전(Electron) 리모콘의 호환성 기준선 — 개발 PC 에서 처음 한 번만 가져온다 (프로젝트 옆 폴더). 배포판에는 없다
LEGACY_SEED = Path(__file__).resolve().parent.parent.parent / "mobi-remote-legacy" / "compat.json"
# write_chat 은 2026-10-15 판부터 게임 안 확인 창에서 사람이 '보내기'를 누를 때까지 멈춘다 (몇 분까지)
CONFIRM_WAIT = 300

# 레거시 src/settings.js 의 기본값. 파이썬 설정 창이 쓰던 키(cli_path 등)도 같은 파일에 같이 산다
DEFAULTS = {
    "cliPath": "",                    # 자동 탐색이 실패했을 때 사용자가 직접 지정한 커넥터 경로
    "sort": {},                       # 표별 정렬 기준. 기본은 CLI 순서 = 게임 화면 순서
    "theme": "dark",
    "askFacilityLevelMismatch": True,  # 정해 둔 시설 레벨이 실제와 어긋날 때 물어볼지
}
# 화면이 바꿀 수 있는 설정. 아무 키나 받으면 무엇이 어디서 바뀌는지 알 수 없게 된다
CFG_KEYS = {"askFacilityLevelMismatch": bool, "alterWorksFolded": bool, "queueFolded": bool,
            "dyeNudge": bool, "closeToTray": bool}
# 별표를 달 수 있는 목록 (레거시 favorites.js). 악보는 재생목록이 곧 즐겨찾기라 없다
FAV_LISTS = ("craft", "alter", "gather", "items", "facial", "behaviour")


class _GuiCall(QObject):
    """작업 스레드 → 화면 스레드로 함수를 넘겨 실행하고 끝날 때까지 기다린다 (BlockingQueuedConnection).
    화면 스레드에서 만들어야 한다 (QObject 는 만든 스레드에 산다)."""
    sig = Signal(object)

    def __init__(self):
        super().__init__()
        self.sig.connect(self._run, Qt.BlockingQueuedConnection)

    @Slot(object)
    def _run(self, box):
        try:
            box["out"] = box["fn"]()
        except Exception as e:  # 부른 쪽 스레드에서 다시 던진다
            box["err"] = e

    def call(self, fn):
        if QThread.currentThread() is self.thread():
            return fn()  # 화면 스레드에서 막는 연결로 자기에게 보내면 영영 안 끝난다
        box = {"fn": fn}
        self.sig.emit(box)
        if "err" in box:
            raise box["err"]
        return box.get("out")


def _opts_kw(opts) -> dict:
    """레거시 조회 opts → QueryCache.get 인자."""
    o = opts if isinstance(opts, dict) else {}
    kw = {"refresh": bool(o.get("refresh")), "offline": bool(o.get("offline"))}
    if isinstance(o.get("maxAgeMs"), (int, float)):
        kw["max_age"] = o["maxAgeMs"] / 1000
    return kw


class Api(DailyApi, CharsApi, QueueApi):
    def __init__(self, paths):
        self.paths = paths
        self.win = None
        self._gui: _GuiCall | None = None
        self._lock = threading.RLock()       # 설정·작은 저장소의 읽고-고치고-쓰기
        self._exec_lock = threading.Lock()   # 레거시 currentAction: exec 는 한 번에 하나
        self.settings = self._load_settings()
        self.cli = Connector(lambda: self.settings.get("cliPath") or self.settings.get("cli_path") or None, log)
        self.calllog = CallLog(paths.logs)
        self.cli.on_call = self.calllog.record
        self.qc = QueryCache(self.cli, paths.data / "cache")
        self.cd = craft.configure(paths.data, paths.resources / "data")
        self._init_queue()  # 작업 큐 (queue_api) — 카드 목록을 읽어 둔다
        self.shapes = Shapes(self.qc, self.cd)
        self.compat = Compat(self.cli, paths.data / "compat.json", LEGACY_SEED if LEGACY_SEED.exists() else None)
        self.playlists = Playlists(paths.data / "playlists.json")
        self.favorites = Favorites(paths.data / "favorites.json")
        self.dye = PresetStore(paths.data)
        self.dyes: DyeService | None = None  # QObject 라 화면 스레드에서 만든다 (attach)
        self._nudge_err: str | None = None
        self.nudge = CursorNudge(on_error=self._on_nudge_error)

    # ---------------------------------------------------------------- 창
    def attach(self, win) -> None:
        """WebWindow 가 화면 스레드에서 부른다."""
        self.win = win
        self._gui = _GuiCall()
        self.dyes = DyeService(self.dye, self._emit)
        self.dyes.win = win

    def initial(self) -> dict:
        """첫 페인트 전에 페이지에 심을 값 (window.__MM_INIT__). 테마가 늦게 오면 화면이 번쩍인다."""
        return {"theme": "light" if self.settings.get("theme") == "light" else "dark",
                "app": {"name": APP_NAME, "version": APP_VERSION}, "labels": gamedata.labels()}

    def close(self) -> None:
        """앱을 끝낼 때. 단축키 스레드와 진행 중인 게임 행동을 정리한다."""
        try:
            self.nudge.stop()
        except Exception:
            pass
        if self.dyes:
            self.dyes.stop()
        if self._daily_runner:
            self._daily_runner.stop()
        if self._scan_bot:
            self._scan_bot.stopper.request()
        self.cli.cancel()

    def _emit(self, channel: str, payload=None) -> None:
        if self.win is not None:
            self.win.backend.emit_event(channel, payload)

    def _on_gui(self, fn):
        if self._gui is None:
            raise RuntimeError("창이 아직 없습니다")
        return self._gui.call(fn)

    # ---------------------------------------------------------------- 설정
    def _load_settings(self) -> dict:
        s = copy.deepcopy(DEFAULTS)
        try:
            d = json.loads(self.paths.settings.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                s.update(d)
        except (OSError, ValueError):
            pass
        return s

    def _save_settings(self, patch: dict) -> dict:
        with self._lock:
            self.settings = {**self._load_settings(), **patch}
            try:
                self.paths.settings.parent.mkdir(parents=True, exist_ok=True)
                self.paths.settings.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass  # 저장에 실패해도 화면은 계속 동작해야 한다
            return dict(self.settings)

    def cfg_get(self):
        with self._lock:
            self.settings = self._load_settings()
            return dict(self.settings)

    def cfg_theme(self, v):
        return self._save_settings({"theme": "light" if v == "light" else "dark"})

    def cfg_set(self, key, value):
        t = CFG_KEYS.get(key)
        if t is None or type(value) is not t:
            return self.cfg_get()
        patch = {key: value}
        if key == "closeToTray":
            patch["close_to_tray"] = value  # 파이썬 창(main.py)이 읽는 이름
        return self._save_settings(patch)

    def cfg_sort(self, tab, key):
        cur = self.cfg_get()
        return self._save_settings({"sort": {**(cur.get("sort") or {}), str(tab): key}})

    # ---------------------------------------------------------------- 연결·조회
    def status(self):
        try:
            return self.cli.status()
        except Exception as e:
            return {"connected": False, "pipe": "error", "reason": None, "message": str(e)}

    def query(self, name, opts=None):
        try:
            return self.shapes.run(name, opts or {})
        except Exception as e:
            log.exception(f"조회 실패 {name}")
            return {"error": "query_failed", "message": str(e)}

    def queryMany(self, names, opts=None):  # noqa: N802
        """여러 조회를 한 번에 (대시보드 새로고침). 레거시처럼 동시에 돌린다 — 같은 명령은 캐시가 하나로 합친다."""
        names = [n for n in (names or []) if isinstance(n, str)]
        opts = opts if isinstance(opts, dict) else {}
        out: dict = {}

        def one(n):
            if n not in Shapes.NAMES:
                out[n] = {"error": "unknown_query"}
                return
            out[n] = self.query(n, opts.get(n) or {})
        ts = [threading.Thread(target=one, args=(n,), daemon=True) for n in names]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return {n: out.get(n) for n in names}

    # ---------------------------------------------------------------- 명령 실행
    def exec(self, command, body=None, origin: dict | None = None):
        """게임 행동 명령 하나. 비용 있는 명령은 화면이 미리 사용자 확인을 받은 뒤 부른다.
        사전 차단(칸 없음)·레시피 학습은 mabi.craft.execute 가 한다.
        origin: 작업 큐가 부를 때 {label, act} — 시작·끝 이벤트에 실어 화면이 결과를 알리게 한다
        (화면이 부른 명령은 화면이 직접 알리므로 origin 이 없다)."""
        origin = origin if isinstance(origin, dict) else None
        if not self._exec_lock.acquire(blocking=False):
            return {"ok": False, "error": "busy", "message": "다른 명령이 실행 중입니다."}
        try:
            cost = self.cli.cost_of(command)
            self._emit("mm:exec-start", {"command": command, "body": body, "costed": bool(cost), "origin": origin})
            r = execute(self.cd, self.cli, self.qc, command, body,
                        timeout=CONFIRM_WAIT if command == "write_chat" else None,
                        on_facility_level=lambda ch: self._emit("mm:facility-level", ch))
            payload = {"ok": r.ok, "code": r.code, "error": r.error, "message": r.message, "data": r.data,
                       "durationMs": r.duration_ms,
                       # 게임이 알려 준 실제 소모량을 우선한다. blocked 로 끝나도 비용은 나갈 수 있다
                       "wingsSpent": r.wings_spent, "costInfo": r.cost_info,
                       "ko": None if r.ok else (r.ko or errors.describe(command, r.error, r.message or "", r.data))}
            if r.ok and cost:
                self.qc.clear("get_currencies")  # 날개 잔량이 바뀌었다
            self._emit("mm:exec-done", {"command": command, **payload, "origin": origin})
            return payload
        finally:
            self._exec_lock.release()

    def cancel(self):
        if not self._exec_lock.locked():
            return {"ok": False, "error": "idle"}
        self.cli.cancel()
        return {"ok": True}

    def costOf(self, command, times=1):  # noqa: N802
        """확인 문구용. 재화 이름으로 잔량을 찾아서 비용 재화가 바뀌어도 따라간다."""
        try:
            n = max(1, int(times or 1))
        except (TypeError, ValueError):
            n = 1
        cost = self.cli.cost_of(command)
        if not cost:
            return {"costed": False, "perCall": 0, "total": 0, "currency": None, "balance": 0, "enough": True}
        total = cost["amount"] * n
        cur = self.query("currencies", {"search": cost["currency"], "refresh": True})
        items = cur.get("items") or []
        row = next((x for x in items if x.get("name") == cost["currency"]), items[0] if items else None)
        balance = row["amount"] if row else 0
        return {"costed": True, "perCall": cost["amount"], "total": total, "currency": cost["currency"],
                "balance": balance, "enough": (balance or 0) >= total}

    def capabilities(self, refresh=False):
        cmds = self.cli.capabilities(refresh=bool(refresh))
        if refresh:
            self.cli._costs = None  # 명령 목록을 새로 받았으니 비용표도 다시 읽는다
        return [{"command": x.get("Command"), "description": x.get("Description"), "bodyExample": x.get("BodyExample"),
                 "note": x.get("Note") or "", "action": x.get("Command") in ACTION_COMMANDS,
                 "cost": self.cli.cost_of(x.get("Command")), "costed": bool(self.cli.cost_of(x.get("Command")))}
                for x in cmds]

    # ---------------------------------------------------------------- 로그
    def log_tail(self, n=200):
        return self.calllog.tail(int(n or 200))

    def log_files(self):
        out = []
        try:
            for f in self.paths.logs.glob("connector-*.log"):
                st = f.stat()
                out.append({"name": f.name, "sizeKB": round(st.st_size / 1024),
                            "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(st.st_mtime)) + "Z"})
        except OSError:
            pass
        return sorted(out, key=lambda x: x["name"], reverse=True)

    def log_open(self):
        try:
            os.startfile(str(self.paths.logs))
        except OSError:
            pass
        return None

    # ---------------------------------------------------------------- 학습된 지식 (CLI 가 주지 않는 것)
    def kn_get(self):
        return self.cd.knowledge.load()

    def kn_setLevel(self, facility, level):  # noqa: N802
        return self.cd.knowledge.set_facility_level(facility, level)

    def kn_rules(self):
        """레벨별 칸 수 표. 화면이 레벨 선택지를 만들 때 쓴다."""
        return {"altering": self.cd.rules.altering_facility(), "fallback": self.cd.rules.is_fallback()}

    # ---------------------------------------------------------------- 목표·계획 (전부 무료 조회)
    def goal_next(self, name, target):
        """다음 한 걸음. 작업 큐(queue_api.GoalKind)가 실행하고, 화면은 담기 전에 견적으로 부른다.
        한 걸음 돌린 뒤의 캐시는 옛것이라 매번 새로 읽는다."""
        return goal.next_for(self.cd, self.qc, name, target, refresh=True)

    def plan_craft(self, name, target, opts=None):
        try:
            return plan.make_plan(self.cd, self.qc, name, target, **_opts_kw(opts))
        except Exception as e:
            log.exception("제작 계획 실패")
            return {"error": "plan_failed", "message": str(e)}

    def plan_needs(self, target, count, opts=None):
        """가공 목표를 사슬 끝까지 — 무엇을 몇 번 가공하고 몇 번 캐야 하는지."""
        try:
            return plan.deep_plan(self.cd, self.qc, target, count, **_opts_kw(opts))
        except Exception as e:
            log.exception("가공 계획 실패")
            return {"ok": False, "error": "plan_failed", "message": str(e)}

    # ---------------------------------------------------------------- 재생목록 (레거시 playlist.js 모양)
    # 커넥터는 캐릭터 식별자를 안 주므로 목록은 캐릭터와 무관하게 두고, 재생할 때 가진 곡만 추린다
    def _pl_state(self) -> dict:
        d = self.playlists.load()
        return d if isinstance(d.get("lists"), list) else {"lists": []}

    def _pl_find(self, d, pid):
        return next((x for x in d["lists"] if x.get("id") == pid), None)

    def pl_list(self):
        return self._pl_state()["lists"]

    def pl_create(self, name=None):
        with self._lock:
            d = self._pl_state()
            item = {"id": "pl" + _base36(int(time.time() * 1000)), "name": str(name or "새 재생목록")[:40],
                    "tracks": [], "loop": False, "shuffle": False,
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"}
            d["lists"].append(item)
            self.playlists.save(d)
            return item

    def pl_update(self, pid, patch):
        with self._lock:
            d = self._pl_state()
            item = self._pl_find(d, pid)
            if item is None:
                return None
            p = patch if isinstance(patch, dict) else {}
            if "name" in p:
                item["name"] = str(p["name"])[:40]
            if "tracks" in p and isinstance(p["tracks"], list):
                item["tracks"] = p["tracks"][:300]
            if "loop" in p:
                item["loop"] = bool(p["loop"])
            if "shuffle" in p:
                item["shuffle"] = bool(p["shuffle"])
            self.playlists.save(d)
            return item

    def pl_remove(self, pid):
        with self._lock:
            d = self._pl_state()
            before = len(d["lists"])
            d["lists"] = [x for x in d["lists"] if x.get("id") != pid]
            self.playlists.save(d)
            return len(d["lists"]) < before

    def pl_addTrack(self, pid, title):  # noqa: N802
        item = self._pl_find(self._pl_state(), pid)
        if item is None:
            return None
        tracks = list(item.get("tracks") or [])
        if title not in tracks:
            tracks.append(title)
        return self.pl_update(pid, {"tracks": tracks})

    def pl_removeTrack(self, pid, i):  # noqa: N802
        item = self._pl_find(self._pl_state(), pid)
        tracks = list((item or {}).get("tracks") or [])
        if item is None or not isinstance(i, int) or not 0 <= i < len(tracks):
            return item
        tracks.pop(i)
        return self.pl_update(pid, {"tracks": tracks})

    def pl_moveTrack(self, pid, i, delta):  # noqa: N802
        item = self._pl_find(self._pl_state(), pid)
        if item is None:
            return None
        tracks = list(item.get("tracks") or [])
        to = (i or 0) + (delta or 0)
        if not isinstance(i, int) or not 0 <= i < len(tracks) or not 0 <= to < len(tracks):
            return item
        t = tracks.pop(i)
        tracks.insert(to, t)
        return self.pl_update(pid, {"tracks": tracks})

    # ---------------------------------------------------------------- 커넥터 경로
    def _loc(self, force=False) -> dict:
        r = self.cli.locate(bool(force))
        return {"path": r.path, "source": r.source, "found": r.found, "tried": list(r.tried)}

    def cli_locate(self, force=False):
        return self._loc(force)

    def cli_choose(self):
        """자동 탐색이 실패한 환경에서 사용자가 직접 고른다. 파일 창은 화면 스레드에서만 열린다."""
        from PySide6.QtWidgets import QFileDialog

        def pick():
            f, _ = QFileDialog.getOpenFileName(self.win, f"{EXE_NAME} 위치를 선택하세요", "",
                                               "마비노기 모바일 커넥터 (*.exe)")
            return f
        picked = self._on_gui(pick)
        if not picked:
            return {"canceled": True}
        picked = str(Path(picked))
        if Path(picked).name.lower() != EXE_NAME.lower():
            return {"canceled": False, "ok": False, "error": "wrong_file", "expected": EXE_NAME}
        self._save_settings({"cliPath": picked, "cli_path": picked})
        r = self._loc(True)
        return {"canceled": False, "ok": r["found"], "path": r["path"], "source": r["source"]}

    # ---------------------------------------------------------------- 염색 도우미 (CLI 와 무관 — 화면 픽셀만 읽는다)
    def dye_prefs(self):
        return self.dye.load()

    def dye_add(self, name, colors):
        return self.dye.add(name, colors)

    def dye_update(self, pid, patch):
        p = patch if isinstance(patch, dict) else {}
        return self._retarget(self.dye.update(pid, name=p.get("name"), colors=p.get("colors"), tol=p.get("tol")))

    def dye_remove(self, pid):
        return self._retarget(self.dye.remove(pid))

    def dye_select(self, pid):
        return self._retarget(self.dye.select(pid))

    def _retarget(self, out):
        if self.dyes:
            self.dyes.retarget()
        return out

    def dye_start(self):
        return self.dyes.start() if self.dyes else {"error": "창이 아직 없습니다"}

    def dye_stop(self):
        return self.dyes.stop() if self.dyes else {"ok": True}

    def _grab(self, with_overlay: bool):
        """주 모니터 한 장. 레거시는 리모콘 창을 잠깐 숨겼지만(Electron 캡처는 제외가 안 들었다) mss(BitBlt)에는
        캡처 제외가 들으므로 창을 숨기지 않고 제외만 건다 — 창이 깜빡이지 않는다."""
        import mss
        import mss.tools
        ov = self.dyes.overlay if self.dyes else None
        running = bool(self.dyes and self.dyes.running)

        def guard(on):
            exclude_from_capture(self.win, on or running)
            if ov is not None and ov.isVisible():
                exclude_from_capture(ov, not with_overlay if on else True)
        self._on_gui(lambda: guard(True))
        try:
            time.sleep(0.05)
            with mss.mss() as sct:
                mon = sct.monitors[1]
                img = sct.grab(mon)
                return mss.tools.to_png(img.rgb, img.size), {"x": mon["left"], "y": mon["top"],
                                                             "width": mon["width"], "height": mon["height"]}
        finally:
            self._on_gui(lambda: guard(False))

    def dye_shot(self):
        """게임 위에 무엇이 그려지는지 보여 주려는 것이라 표시 창은 찍히고 리모콘 창만 빠진다."""
        png, _ = self._grab(True)
        t = time.localtime()
        d = Path(os.path.expanduser("~")) / "Pictures" / APP_NAME
        d.mkdir(parents=True, exist_ok=True)
        f = d / time.strftime("염색 %Y%m%d-%H%M%S.png", t)
        f.write_bytes(png)

        def clip():
            from PySide6.QtGui import QGuiApplication, QImage
            QGuiApplication.clipboard().setImage(QImage.fromData(png, "PNG"))
            return True
        try:
            copied = bool(self._on_gui(clip))
        except Exception:
            copied = False
        # 레거시는 png 바이트를 돌려주고 화면이 클립보드에 넣었다. 여기선 파이썬이 넣고 결과만 알린다
        return {"path": str(f), "copied": copied}

    def dye_snap(self):
        """스포이드: 게임 색을 집으려는 것이라 우리 표시가 섞이면 안 된다."""
        png, bounds = self._grab(False)
        return {"dataUrl": "data:image/png;base64," + base64.b64encode(png).decode("ascii"), "bounds": bounds}

    # ---------------------------------------------------------------- 커서 1px (Ctrl+Alt+WASD)
    def _on_nudge_error(self, msg):
        self._nudge_err = msg

    def cursor_nudge(self, on):
        """전역 단축키라 켜 둔 동안 다른 프로그램에서도 이 조합을 못 쓴다 — 켜고 끄는 건 사람이 쥔다."""
        if not on:
            self.nudge.stop()
            return {"ok": True}
        self._nudge_err = None
        try:
            self.nudge.start()
        except Exception as e:
            return {"ok": False, "error": f"준비하지 못했습니다: {e}"}
        if not self.nudge.running:
            return {"ok": False, "error": self._nudge_err or "단축키를 등록하지 못했습니다"}
        return {"ok": True, **({"warning": self._nudge_err} if self._nudge_err else {})}

    # ---------------------------------------------------------------- 창
    def win_narrow(self, px=0):
        """작업 큐를 접고 펼 때 창 폭도 그만큼. 왼쪽 위 모서리는 그대로 둬서 창이 튀어 다니지 않는다."""
        if self.win is None:
            return None

        def go():
            w = self.win
            nxt = w.width() - round(px or 0)
            if nxt != w.width():
                w.resize(max(nxt, w.minimumWidth()), w.height())
            return w.width()
        return self._on_gui(go)

    # ---------------------------------------------------------------- 작업 큐 기록 (큐 자체는 queue_api)
    def queue_history(self, limit=300):
        return craft_queue.history(self.cd.history_file, int(limit or 300))

    # ---------------------------------------------------------------- 즐겨찾기 (키는 태그 붙은 원문 nameRaw)
    def _fav_load(self) -> dict:
        d = self.favorites.load()
        return {k: [str(x) for x in d[k]] if isinstance(d.get(k), list) else [] for k in FAV_LISTS}

    def fav_all(self):
        return self._fav_load()

    def fav_toggle(self, lst, name):
        key = str(name or "")
        if lst not in FAV_LISTS or not key:
            return {"ok": False, "on": False, "list": lst, "name": key, "favorites": self._fav_load()}
        with self._lock:
            st = self._fav_load()
            on = key not in st[lst]
            if on:
                st[lst].append(key)
            else:
                st[lst].remove(key)
            self.favorites.save(st)
        return {"ok": True, "on": on, "list": lst, "name": key, "favorites": st}

    def fav_clear(self, lst):
        if lst not in FAV_LISTS:
            return self._fav_load()
        with self._lock:
            st = self._fav_load()
            st[lst] = []
            self.favorites.save(st)
            return st

    # ---------------------------------------------------------------- 버전·호환성
    def version_info(self):
        loc = self._loc()
        pv = cli_version(loc["path"]).get("productVersion")
        # 화면에는 0.1.0 만. 빌드 해시(+0487c3…)는 넥슨이 재빌드할 때마다 바뀌어 사용자에게는 잡음이다
        return {"app": APP_VERSION, "cliVersion": semver(pv) if pv else None, "cliFull": pv, "cliPath": loc}

    def version_check(self, refresh=False):
        """레거시 version.check() 모양 {level(숫자), levelName, ok, firstRun, changes, baseline, current}.
        판단은 mabi.compat (설명·출력 형식 지문까지 본다 — 2026-10-15 판 변화는 명령|본문 지문으로 안 잡혔다)."""
        try:
            res = self.compat.check(refresh=bool(refresh))
        except Exception:
            # 게임이 꺼져 있으면 받아오기만 실패한다 → 캐시된 명령 목록으로 검사
            res = self.compat.check(refresh=False)
        # 기준선이 옛 리모콘 것(seed)뿐이고 문제가 없으면 이 판 형식으로 한 번 저장한다 — 안 그러면 '설명·응답 형식은
        # 비교하지 못했습니다' 참고 알림이 켤 때마다 뜬다 (2026-10-24)
        if not res.get("first_run") and not self.compat.file.exists() and res["level"] in ("ok", "info"):
            try:
                self.compat.save(note="옛 리모콘 기준선과 차이 없음 — 이 판 형식으로 옮김")
                res = {**res, "level": "ok", "changes": []}
            except Exception:
                pass
        lv = LEVELS.index(res["level"]) if res["level"] in LEVELS else 1
        return {"level": lv, "levelName": LEVELS[lv], "ok": lv < 2, "firstRun": bool(res.get("first_run")),
                "changes": res.get("changes") or [], "baseline": self.compat.baseline() if not res.get("first_run") else None,
                "current": res.get("current")}

    def version_accept(self, note=""):
        try:
            self.cli.capabilities(refresh=True)
        except Exception:
            pass  # 오프라인이면 캐시본으로 기준선을 잡는다
        return {"ok": True, "baseline": self.compat.save(note=note or "")}

    # ---------------------------------------------------------------- 새 판 확인 (GitHub 최신 릴리스)
    # 예전 판(src/update.js)과 같은 방식: 최신 릴리스에서 '...setup.exe' 를 받아, 사람이 누르면 실행하고 끈다.
    # 런타임 구성(설치 폴더 runtime.txt)이 같은 '...-patch-<구성>.zip' 이 있으면 그것(수 MB)만 받아 app\ 을 바꾸고
    # 다시 켠다 (적용은 다음 실행 때 gui.py 가, 구성 값은 tools/build.py).
    # 몰래 받아서 몰래 바꾸지 않는다 — 게임을 켜 둔 채 쓰는 프로그램이라 언제 꺼질지는 사람이 정한다
    UPDATE_API = "https://api.github.com/repos/Banteil/mobi-remote/releases/latest"
    UPDATE_PAGE = "https://github.com/Banteil/mobi-remote/releases/latest"

    @staticmethod
    def _http(url: str, timeout: float = 20):
        import urllib.request
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mobi-remote-updater"}),
                                      timeout=timeout)

    @staticmethod
    def _install_home() -> Path | None:
        """패치를 받을 수 있는 설치판이면 설치 폴더 (exe 이고 app\\ 에서 코드를 읽는 판)."""
        import sys
        if not getattr(sys, "frozen", False):
            return None
        home = Path(sys.executable).resolve().parent
        return home if (home / "runtime.txt").is_file() and (home / "app" / "version.json").is_file() else None

    def _runtime(self) -> str:
        home = self._install_home()
        return (home / "runtime.txt").read_text(encoding="utf-8").strip() if home else ""

    def update_check(self):
        try:
            with self._http(self.UPDATE_API) as r:
                rel = json.loads(r.read().decode("utf-8"))
            ver = str(rel.get("tag_name") or "").lstrip("vV")
            if not ver:
                return {"ok": False, "newer": False, "page": self.UPDATE_PAGE, "error": "릴리스가 아직 없습니다"}
            assets = rel.get("assets") or []
            setup = next((a for a in assets if re.search(r"setup\.exe$", a.get("name", ""), re.I)), None)
            rt = self._runtime()
            patch = rt and next((a for a in assets if a.get("name", "").endswith(f"-patch-{rt}.zip")), None)
            pick = patch or setup
            return {"ok": True, "newer": _ver(ver) > _ver(APP_VERSION), "version": ver, "notes": rel.get("body") or "",
                    "url": rel.get("html_url") or self.UPDATE_PAGE, "page": self.UPDATE_PAGE,
                    "asset": {"name": pick["name"], "url": pick["browser_download_url"], "size": pick.get("size", 0),
                              "kind": "patch" if patch else "setup"} if pick else None}
        except Exception as e:  # 오프라인 등 — 조용히 넘긴다
            return {"ok": False, "newer": False, "page": self.UPDATE_PAGE, "error": str(e)}

    def update_download(self, asset=None):
        """설치 파일은 임시 폴더, 패치는 설치 폴더 update\\ 에 받는다 (다 받은 뒤에 제 이름으로 — 받다 만 파일을 쓰지 않게)."""
        import tempfile
        if not asset or not asset.get("url"):
            return {"ok": False, "error": "받을 파일이 없습니다"}
        home = self._install_home() if asset.get("kind") == "patch" else None
        if asset.get("kind") == "patch" and not home:
            return {"ok": False, "error": "패치를 넣을 수 없는 판입니다"}
        d = home / "update" if home else Path(tempfile.gettempdir()) / "mobi-remote-update"
        d.mkdir(parents=True, exist_ok=True)
        f = d / os.path.basename(asset.get("name") or "setup.exe")
        part = f.with_suffix(f.suffix + ".part")
        try:
            with self._http(asset["url"], timeout=60) as r, open(part, "wb") as out:
                total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
                got, last = 0, -1
                while chunk := r.read(1 << 16):
                    out.write(chunk)
                    got += len(chunk)
                    pct = int(got * 100 / total) if total else 0
                    if pct != last:
                        last = pct
                        self._emit("mm:update-progress", {"pct": pct, "got": got, "total": total})
            if total and got != total:
                part.unlink(missing_ok=True)
                return {"ok": False, "error": f"받다가 끊겼습니다 ({got}/{total})"}
            if home:  # 패치가 이 설치의 구성용인지 미리 본다 (아니면 켜는 쪽에서 버리고 지금 판으로 켜진다)
                import zipfile
                with zipfile.ZipFile(part) as z:
                    meta = json.loads(z.read("version.json").decode("utf-8"))
                if meta.get("runtime") != self._runtime():
                    part.unlink(missing_ok=True)
                    return {"ok": False, "error": "이 설치에 맞지 않는 패치입니다 — 설치 파일로 받아 주세요"}
            f.unlink(missing_ok=True)
            part.rename(f)
            return {"ok": True, "file": str(f), "kind": "patch" if home else "setup"}
        except Exception as e:
            part.unlink(missing_ok=True)
            return {"ok": False, "error": str(e)}

    def update_install(self, file=None):
        """설치 파일은 실행하고 이 프로그램은 끈다 (덮어쓰기가 막히지 않게).
        패치는 update\\patch.zip 으로 두고 새 프로그램을 띄운 뒤 끈다 — 새 프로그램이 이쪽이 꺼지길 기다렸다가 적용한다."""
        if not file or not Path(file).is_file():
            return {"ok": False, "error": "설치 파일이 없습니다"}
        home = self._install_home()
        if file.endswith(".zip"):
            if not home:
                return {"ok": False, "error": "패치를 넣을 수 없는 판입니다"}
            import ctypes
            import sys
            os.replace(file, home / "update" / "patch.zip")
            # 관리자 exe 라 ShellExecute 로 띄운다 (권한이 같으면 묻지 않는다)
            ctypes.windll.shell32.ShellExecuteW(None, "open", sys.executable, f"--wait-pid {os.getpid()}",
                                                str(home), 1)
        else:
            os.startfile(file)
        from PySide6.QtWidgets import QApplication
        self._on_gui(lambda: QApplication.instance().quit())
        return {"ok": True}

    def update_page(self):
        webbrowser.open(self.UPDATE_PAGE)
        return None

    # ---------------------------------------------------------------- 루틴 (화면이 쓰지 않는 레거시 기능)
    # ---------------------------------------------------------------- 캐시
    def cache_list(self):
        out = []
        try:
            for f in self.qc.dir.iterdir():
                st = f.stat()
                out.append({"command": re.sub(r"\.json$", "", f.name), "sizeKB": round(st.st_size / 1024),
                            "ageSec": round(time.time() - st.st_mtime)})
        except OSError:
            return []
        return out

    def cache_clear(self, command=None):
        try:
            if command:
                (self.qc.dir / f"{command}.json").unlink()
            else:
                shutil.rmtree(self.qc.dir, ignore_errors=True)
            return True
        except OSError:
            return False


def _base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = digits[r] + s
    return s or "0"
