"""일일 숙제 화면(web/daily.js)이 부르는 파이썬 쪽 (mm.daily.*). Api 가 이 클래스를 섞어 쓴다.

숙제 실행은 mabi.runner.Runner 를 작업 스레드에서 돌리고, 진행 이벤트(start/character/task_start/task_end/done)와
로그 줄을 화면 이벤트 'mm:daily' / 'mm:daily-log' 로 그대로 넘긴다. 설정은 profile.json(캐릭터)과
config.toml(숙제 설정, 주석을 살리려고 tomlkit)에 저장한다.
"""
import base64
import ctypes
import json
import logging
import os
import threading
import time

import tomlkit

from mabi import paths as mpaths
from mabi import profile as prof
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
        if self._abyss_thread and self._abyss_thread.is_alive():
            return {"error": "어비스 반복이 도는 중입니다"}
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
                msg = str(e) if isinstance(e, (ValueError, RuntimeError)) else f"{type(e).__name__}: {e}"
                self._emit("mm:daily", {"type": "failed", "message": msg})
                return
            # F12·일시정지 버튼으로 멈췄으면 '일시정지' — F12 를 다시 누르면 이어 한다 (진행 기록으로 끊긴 자리부터).
            # 큐에서 숙제 카드를 지워 멈춘 것(_daily_end)은 종료
            if any(s == "STOP" for _, s, _ in results or []) and not self._daily_end:
                log.info("일시정지 — F12 를 다시 누르면 이어 합니다")
                self._emit("mm:daily", {"type": "paused"})
                self._daily_wait_resume()
            elif not any(s == "STOP" for _, s, _ in results or []):
                self._bring_front()  # 끝까지 돌았다 → 결과 창(화면이 'done' 에 띄움)이 게임 위로 보이게
        self._daily_thread = threading.Thread(target=work, name="daily", daemon=True)
        self._daily_thread.start()
        return {"ok": True}

    def _bring_front(self) -> None:
        """리모콘 창을 게임 위로. 다른 프로세스(게임)가 맨 앞이면 Windows 가 SetForegroundWindow 를 막아 작업 표시줄만
        깜빡이므로, 게임 창을 앞으로 가져올 때(GameWindow.focus)와 같이 Alt 를 눌렀다 떼며 가져온다."""
        def go():
            w = self.win
            if w is None:
                return
            w.show_window()
            u = ctypes.windll.user32
            u.keybd_event(0x12, 0, 0, 0)  # VK_MENU
            u.SetForegroundWindow(int(w.winId()))
            u.keybd_event(0x12, 0, 2, 0)  # KEYEVENTF_KEYUP
        try:
            self._on_gui(go)
        except Exception:
            log.exception("결과 창을 앞으로 가져오지 못함")

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

    def daily_displayCheck(self, opts: dict | None = None) -> dict:  # noqa: N802
        """{ok, running, problems, target}. 게임 창 크기·화면 모드 (1초 안팎).
        고른 캐릭터·숙제가 오늘 다 끝났으면 화면을 보지 않고 ok (idle) — 숙제는 '오늘 완료' 만 알리고 게임을 건드리지 않는다."""
        from mabi.bot import Bot
        from mabi.tasks import display
        target = "테두리 없는 전체화면 · 16:9 (1280×720 이상) — 숙제 동안만 맞추고 끝나면 원래대로"
        try:
            o = opts or {}
            run_opts = RunOptions(chars=o.get("chars") or None, only=o.get("only") or None, force=bool(o.get("force")))
            if not Runner(self.paths, force_exit=False).has_work(run_opts):
                return {"ok": True, "idle": True, "running": True, "problems": [], "target": target}
            cfg = load_config(self.paths)
            bot = Bot(cfg, self.paths, force_exit=False)
            try:
                if not display.game_running(bot.window):
                    return {"ok": False, "running": False, "problems": ["게임이 꺼져 있음"], "target": target}
                return {**display.check(bot, interface=False), "target": target}
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
                msg = display.ensure(bot, cfg, self.paths.data / "backup", remember=self.paths.data / display.RESTORE_FILE)
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

    # ---- 어비스 반복 (mabi.tasks.abyss) ----
    _abyss_thread: threading.Thread | None = None
    _abyss_bot = None

    def daily_abyssSettings(self) -> dict:  # noqa: N802
        a = load_config(self.paths)["abyss"]
        from mabi.tasks import abyss
        profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
        return {"dungeon": a["dungeon"], "difficulty": a.get("difficulty") or "매우 어려움2", "runs": int(a.get("runs", 0)),
                "slot": int(a.get("slot", 0)), "chars": [{"slot": c["slot"], "name": c["name"]} for c in prof.characters(profile)],
                "minutes": float(a.get("minutes", 0)), "dungeons": ["허상의 정박지", "광기의 동굴", "흩어진 물길"],
                "difficulties": abyss.DIFFICULTIES,
                "running": bool(self._abyss_thread and self._abyss_thread.is_alive())}

    def daily_abyssStart(self, v: dict) -> dict:  # noqa: N802
        """고른 던전·난이도·횟수·시간을 config.toml [abyss] 에 저장하고 반복을 시작한다.
        진행은 'mm:abyss' {type: abyss|done|failed, clears, deaths, ...}, 로그는 일일 숙제 로그 칸으로."""
        if self._abyss_thread and self._abyss_thread.is_alive():
            return {"error": "이미 어비스 반복 중입니다"}
        if self._daily_thread and self._daily_thread.is_alive():
            return {"error": "일일 숙제가 도는 중입니다"}
        doc = self._doc()
        if "abyss" not in doc:
            doc["abyss"] = tomlkit.table()
        a = doc["abyss"]
        a["dungeon"] = str(v.get("dungeon") or "허상의 정박지")
        a["difficulty"] = str(v.get("difficulty") or "매우 어려움2")
        a["slot"] = max(0, int(v.get("slot") or 0))
        a["runs"] = max(0, int(v.get("runs") or 0))
        a["minutes"] = max(0, int(v.get("minutes") or 0))
        self.paths.config.write_text(tomlkit.dumps(doc), encoding="utf-8")

        def work():
            from mabi.bot import Bot, StopRequested
            from mabi.tasks import abyss
            bot = None
            try:
                self._daily_hook_log()
                cfg = load_config(self.paths)
                bot = self._abyss_bot = Bot(cfg, self.paths, force_exit=False)
                if not bot.window.find():
                    raise ValueError("게임이 꺼져 있습니다")
                # '게임 조작 감지' 일시정지는 쓰지 않는다 — 어비스 반복은 게임을 뒤에 두고 PC 를 계속 쓰는 기능인데,
                # 게임이 잠깐 앞에 있을 때 누른 키(Alt+Tab 등)로 매칭 중에 멈췄다 (2026-10-23). 멈추기는 F12·버튼으로
                a = cfg["abyss"]  # 게임은 입장할 때만 앞으로 가져온다 (abyss.repeat)
                profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
                ch = next((c for c in prof.characters(profile) if c["slot"] == int(a.get("slot", 0))), None)
                res = abyss.repeat(bot, cfg, int(a["runs"]), float(a["minutes"]),
                                   on_event=lambda e: self._emit("mm:abyss", e), character=ch)
                self._emit("mm:abyss", {"type": "done", **res})
            except StopRequested:
                log.info("어비스 반복: 사용자 중단")
                self._emit("mm:abyss", {"type": "done", "stopped": True})
            except Exception as e:
                log.exception("어비스 반복 실패")
                self._emit("mm:abyss", {"type": "failed", "message": str(e)})
            finally:
                self._abyss_bot = None
                if bot:
                    bot.stopper.close()
        self._abyss_thread = threading.Thread(target=work, name="abyss", daemon=True)
        self._abyss_thread.start()
        return {"ok": True}

    def daily_abyssStop(self) -> dict:  # noqa: N802
        if self._abyss_bot:
            self._abyss_bot.stopper.request()
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
        chars = prof.characters(profile)

        def follow(*keys) -> int:  # 이 기본값을 따르는 캐릭터 수 (그 항목을 캐릭터별로 따로 정하지 않음)
            return sum(not any(k in by.get(str(c["slot"]), {}) for k in keys) for c in chars)
        return {
            "chars": [{**c, **{k: v for k, v in dict(by.get(str(c["slot"]), {})).items()
                               if k in ("field_runs", "dungeon", "floor")}} for c in chars],
            "follow": {"field": follow("field", "field_runs"), "dungeon": follow("dungeon", "floor"),
                       "total": len(chars)},
            "silver": {"field_runs": int(s["field_runs"]), "dungeon": str(s["dungeon"]), "floor": int(s["floor"])},
            "dungeons": [n for n, p in doc["places"].items() if int(p["index"]) < 2],
            "fields": [n for n, p in doc["places"].items() if int(p["index"]) == 2],
            "field": str(s["field"]),
            "stop_key": str(doc["game"].get("stop_key", "f12")),
            "pause_on_touch": bool(doc["game"].get("pause_on_touch", True)),
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
        if v.get("stop_key"):
            k = str(v["stop_key"]).lower()
            if k not in [f"f{i}" for i in range(1, 13)]:  # 게임이 쓰는 글자·Home/End 키와 겹치지 않게 F 키만
                return {"error": f"일시정지 키는 F1~F12 중에서: {k}"}
            doc["game"]["stop_key"] = k
        if "pause_on_touch" in v:
            doc["game"]["pause_on_touch"] = bool(v["pause_on_touch"])
        self.paths.config.write_text(tomlkit.dumps(doc), encoding="utf-8")
        p = v.get("paths")
        if p is not None:
            mpaths.save_overrides(**{k: (p.get(k) or "").strip() for k in ("data", "logs", "shots")})
        return {"ok": True}

    def daily_shot(self, name: str) -> str | None:
        """스크린샷을 data URL 로 (페이지가 다른 폴더의 파일을 직접 못 읽는다 — CSP img-src 'self' data:)."""
        f = self.paths.shots / os.path.basename(name or "")
        if not f.is_file():
            return None
        return "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode("ascii")

    def daily_openFolder(self, kind: str = "logs") -> bool:  # noqa: N802
        d = {"logs": self.paths.logs, "shots": self.paths.shots, "data": self.paths.data}.get(kind, self.paths.logs)
        os.startfile(d)
        return True
