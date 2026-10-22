"""일일 숙제 화면(web/daily.js)이 부르는 파이썬 쪽 (mm.daily.*). Api 가 이 클래스를 섞어 쓴다.

숙제 실행은 mabi.runner.Runner 를 작업 스레드에서 돌리고, 진행 이벤트(start/character/task_start/task_end/done)와
로그 줄을 화면 이벤트 'mm:daily' / 'mm:daily-log' 로 그대로 넘긴다. 설정은 profile.json(캐릭터)과
config.toml(숙제 설정, 주석을 살리려고 tomlkit)에 저장한다.
"""
import base64
import json
import logging
import os
import threading
import time

import tomlkit

from mabi import paths as mpaths
from mabi import profile as prof
from mabi import report_tools as rt
from mabi import tasks
from mabi.runner import RunOptions, Runner, load_config

log = logging.getLogger("mabi")


class _LogToScreen(logging.Handler):
    def __init__(self, emit):
        super().__init__(logging.INFO)
        self.emit_fn = emit
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record):  # noqa: A003
        try:
            self.emit_fn("mm:daily-log", {"level": record.levelname, "text": self.format(record)})
        except Exception:
            pass


class DailyApi:
    """self.paths, self._emit(채널, 값) 이 있는 클래스에 섞는다."""

    _daily_runner: Runner | None = None
    _daily_thread: threading.Thread | None = None
    _daily_log_hooked = False

    def _daily_hook_log(self) -> None:
        if not self._daily_log_hooked:
            log.addHandler(_LogToScreen(self._emit))
            self._daily_log_hooked = True

    # ---- 상태 ----
    def daily_state(self) -> dict:
        cfg = load_config(self.paths)
        reg = tasks.build(cfg)
        profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
        st = prof.DailyState(self.paths.state)
        chars = prof.characters(profile)
        by_slot = {int(k): v for k, v in cfg["run"].get("tasks_by_slot", {}).items()}
        return {"chars": chars, "order": cfg["run"]["order"], "labels": {"login": "접속", **{t: l for t, (l, _) in reg.items()}},
                "today": {str(c["slot"]): st.data.get(str(c["slot"]), {}) for c in chars}, "date": st.date,
                "skip": {k: list(v) for k, v in cfg["run"].get("skip_by_slot", {}).items()},
                # 캐릭터마다 실제로 도는 숙제 (끈 숙제·아르바이트 안 켠 캐릭터는 빠짐) — '결과 보기' 가 쓴다
                "orders": {str(c["slot"]): Runner._order(cfg, RunOptions(), by_slot, c) for c in chars},
                "running": bool(self._daily_thread and self._daily_thread.is_alive())}

    # ---- 실행 ----
    def daily_start(self, opts: dict | None = None) -> dict:
        if self._daily_thread and self._daily_thread.is_alive():
            return {"error": "이미 실행 중입니다"}
        if getattr(self, "_scan_thread", None) and self._scan_thread.is_alive():
            return {"error": "캐릭터 자동 설정이 도는 중입니다"}
        o = opts or {}
        self._daily_hook_log()
        run_opts = RunOptions(chars=o.get("chars") or None, only=o.get("only") or None, force=bool(o.get("force")),
                              extra={"from": "web"})
        self.daily_pauseCancel()
        runner = Runner(self.paths, on_event=lambda e: self._emit("mm:daily", e), force_exit=False)
        self._daily_runner = runner
        self._daily_end = False

        def work():
            try:
                results = runner.run(run_opts)
            except Exception as e:  # 설정 오류, 게임 창 없음 등
                log.exception("일일 숙제 실행 실패")
                self._emit("mm:daily", {"type": "failed", "message": f"{type(e).__name__}: {e}"})
                return
            # F12·일시정지 버튼으로 멈췄으면 '일시정지' — F12 를 다시 누르면 이어 한다 (진행 기록으로 끊긴 자리부터).
            # 큐에서 숙제 카드를 지워 멈춘 것(_daily_end)은 종료
            if any(s == "STOP" for _, s, _ in results or []) and not self._daily_end:
                log.info("일시정지 — F12 를 다시 누르면 이어 합니다")
                self._emit("mm:daily", {"type": "paused"})
                self._daily_wait_resume()
        self._daily_thread = threading.Thread(target=work, name="daily", daemon=True)
        self._daily_thread.start()
        return {"ok": True}

    def daily_stop(self, end: bool = False) -> dict:
        """end=False: 일시정지 (F12 로 이어 함), True: 종료 (큐에서 카드를 지움)."""
        self._daily_end = bool(end)
        if end:
            self.daily_pauseCancel()
        if self._daily_runner:
            self._daily_runner.stop()
        return {"ok": True}

    # ---- 일시정지 중 F12 → 이어 하기 ----
    _pause_wait: threading.Event | None = None

    def _daily_wait_resume(self) -> None:
        from mabi.inputs import key_pressed, vk_of
        self.daily_pauseCancel()
        stop = self._pause_wait = threading.Event()
        vk = vk_of(load_config(self.paths)["game"]["stop_key"])

        def work():
            while key_pressed(vk) and not stop.is_set():  # 멈출 때 누른 F12 를 뗄 때까지
                time.sleep(0.05)
            while not stop.is_set():
                if key_pressed(vk):
                    stop.set()
                    log.info("F12 → 이어 하기")
                    self._emit("mm:daily", {"type": "resume"})
                    return
                time.sleep(0.05)
        threading.Thread(target=work, name="daily-resume", daemon=True).start()

    def daily_pauseCancel(self) -> dict:  # noqa: N802
        if self._pause_wait:
            self._pause_wait.set()
        return {"ok": True}

    # ---- 게임 화면 설정 (숙제 시작 전에 화면이 확인한다) ----
    _display_thread: threading.Thread | None = None

    def daily_displayCheck(self) -> dict:  # noqa: N802
        """{ok, running, problems, target}. 게임 창 크기·화면 배율, 메인 화면이면 HUD 모양까지 (1초 안팎)."""
        from mabi.bot import Bot
        from mabi.tasks import display
        target = "테두리 없는 전체화면 · 해상도 1920×1080 · 인터페이스 스타일 PC · 스케일 80%"
        try:
            cfg = load_config(self.paths)
            bot = Bot(cfg, self.paths, force_exit=False)
            try:
                if not display.game_running(bot.window):
                    return {"ok": False, "running": False, "problems": ["게임이 꺼져 있음"], "target": target}
                return {**display.check(bot), "target": target}
            finally:
                bot.stopper.close()
        except Exception as e:
            log.exception("화면 설정 확인 실패")
            return {"ok": False, "running": False, "problems": [f"확인 실패: {e}"], "target": target}

    _display_wait: threading.Event | None = None

    def daily_displayWait(self) -> dict:  # noqa: N802
        """사람이 직접 맞추는 동안 기다린다. 중단 키(F12)를 누르면 'mm:display' {resume} — 화면이 다시 확인하고 시작한다.
        숙제 시작 버튼을 눌러도 같다 (그때는 이 기다림을 끝낸다). 15분이 지나면 그만 기다린다."""
        from mabi.inputs import key_pressed, vk_of
        self.daily_displayWaitCancel()
        stop = self._display_wait = threading.Event()
        vk = vk_of(load_config(self.paths)["game"]["stop_key"])

        def work():
            key_pressed(vk)  # '이전 호출 이후 눌림' 비트 초기화
            end = time.monotonic() + 15 * 60
            while not stop.is_set() and time.monotonic() < end:
                if key_pressed(vk):
                    stop.set()
                    self._emit("mm:display", {"resume": True})
                    return
                time.sleep(0.05)
        threading.Thread(target=work, name="display-wait", daemon=True).start()
        return {"ok": True}

    def daily_displayWaitCancel(self) -> dict:  # noqa: N802
        if self._display_wait:
            self._display_wait.set()
        return {"ok": True}

    def daily_displayFix(self) -> dict:  # noqa: N802
        """게임이 켜져 있으면 게임 안 환경 설정에서, 실패하면 게임을 끄고 설정 파일로, 꺼져 있으면 파일로 맞춘다.
        끝나면 'mm:display' {done, ok, message, running}."""
        if self._display_thread and self._display_thread.is_alive():
            return {"error": "이미 맞추는 중입니다"}
        if self._daily_thread and self._daily_thread.is_alive():
            return {"error": "일일 숙제가 도는 중입니다"}

        def work():
            from mabi.bot import Bot
            from mabi.tasks import display
            bot = None
            try:
                self._daily_hook_log()
                cfg = load_config(self.paths)
                bot = Bot(cfg, self.paths, force_exit=False)
                msg = display.ensure(bot, cfg, self.paths.data / "backup")
                log.info(f"화면 설정: {msg}")
                running = display.game_running(bot.window)
                self._emit("mm:display", {"done": True, "ok": True, "message": msg, "running": running})
            except Exception as e:
                log.exception("화면 설정 맞추기 실패")
                self._emit("mm:display", {"done": True, "ok": False, "message": f"{e}"})
            finally:
                if bot:
                    bot.stopper.close()
        self._display_thread = threading.Thread(target=work, name="display", daemon=True)
        self._display_thread.start()
        return {"ok": True}

    # ---- 캐릭터·숙제 설정 ----
    def _doc(self):
        return tomlkit.parse(self.paths.config.read_text(encoding="utf-8"))

    def daily_settings(self) -> dict:
        doc = self._doc()
        s = doc["silver"]
        profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
        over = {}
        f = mpaths.default_data_dir() / "paths.json"
        try:
            over = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except ValueError:
            pass
        by = s.get("by_slot", {})
        return {
            "chars": [{**c, **{k: v for k, v in dict(by.get(str(c["slot"]), {})).items()
                               if k in ("field_runs", "dungeon", "floor")}} for c in prof.characters(profile)],
            "silver": {"field_runs": int(s["field_runs"]), "dungeon": str(s["dungeon"]), "floor": int(s["floor"])},
            "weight": float(doc["run"].get("max_weight_ratio", 1.0)),
            "dungeons": [n for n, p in doc["places"].items() if int(p["index"]) < 2],
            "fields": [n for n, p in doc["places"].items() if int(p["index"]) == 2],
            "field": str(s["field"]),
            "stop_key": str(doc["game"].get("stop_key", "f12")),
            "paths": {k: over.get(k, "") for k in ("data", "logs", "shots")},
            "current": {"data": str(self.paths.data), "logs": str(self.paths.logs), "shots": str(self.paths.shots)},
        }

    def daily_saveSettings(self, v: dict) -> dict:  # noqa: N802 (화면 이름 그대로)
        """숙제 공통 설정. 캐릭터별 설정은 캐릭터 탭이 chars_save 로 저장한다."""
        doc = self._doc()
        s = doc["silver"]
        sv = v.get("silver") or {}
        for k in ("field_runs", "floor"):
            if k in sv:
                s[k] = int(sv[k])
        if sv.get("dungeon"):
            s["dungeon"] = sv["dungeon"]
        if v.get("field"):
            s["field"] = v["field"]
        if v.get("weight"):
            doc["run"]["max_weight_ratio"] = round(float(v["weight"]), 2)
        if v.get("stop_key"):
            k = str(v["stop_key"]).lower()
            if k not in [f"f{i}" for i in range(1, 13)]:  # 게임이 쓰는 글자·Home/End 키와 겹치지 않게 F 키만
                return {"error": f"일시정지 키는 F1~F12 중에서: {k}"}
            doc["game"]["stop_key"] = k
        self.paths.config.write_text(tomlkit.dumps(doc), encoding="utf-8")
        p = v.get("paths")
        if p is not None:
            mpaths.save_overrides(**{k: (p.get(k) or "").strip() for k in ("data", "logs", "shots")})
        return {"ok": True}

    # ---- 기록 ----
    def daily_runs(self) -> list:
        rt.use(self.paths)
        out = []
        for r in reversed(rt.load_runs(None)):
            tasks_ = [t for c in r["characters"] for t in c["tasks"]]
            out.append({"file": r["_file"].name, "started": r["started"], "finished": r.get("finished"),
                        "names": [c["name"] or "현재 캐릭터" for c in r["characters"]], "total": len(tasks_),
                        "ok": sum(1 for t in tasks_ if t.get("status") in ("OK", "DONE"))})
        return out

    def daily_run(self, file: str) -> dict | None:
        f = self.paths.runs / os.path.basename(file)
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def daily_shot(self, name: str) -> str | None:
        """스크린샷을 data URL 로 (페이지가 다른 폴더의 파일을 직접 못 읽는다 — CSP img-src 'self' data:)."""
        f = self.paths.shots / os.path.basename(name or "")
        if not f.is_file():
            return None
        return "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode("ascii")

    def daily_export(self, anon: bool = False) -> dict:
        rt.use(self.paths)
        runs = rt.load_runs(None)[-5:]
        if not runs:
            return {"error": "기록이 없습니다"}
        out = rt.export(runs, bool(anon))
        os.startfile(out.parent)
        return {"ok": True, "file": str(out)}

    def daily_openFolder(self, kind: str = "logs") -> bool:  # noqa: N802
        d = {"logs": self.paths.logs, "shots": self.paths.shots, "data": self.paths.data}.get(kind, self.paths.logs)
        os.startfile(d)
        return True
