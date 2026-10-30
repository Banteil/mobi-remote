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

import tomlkit

from mabi import paths as mpaths
from mabi import profile as prof
from mabi import userconfig
from mabi import tasks
from mabi.runner import RunOptions, Runner, load_config
from mabi.tasks.weekday import SUNDAY_CHOICES

from .chars_api import CharsApi

log = logging.getLogger("mabi")


class _LogToScreen(logging.Handler):
    """로그 줄을 화면으로. ch 로 어느 탭 로그인지 알린다 — 'daily' 숙제 · 'abyss' 어비스 · 'all' 둘 다 (공통)."""

    def __init__(self, emit, channel_of):
        super().__init__(logging.INFO)
        self.emit_fn, self.channel_of = emit, channel_of
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record):  # noqa: A003
        try:
            self.emit_fn("mm:daily-log", {"level": record.levelname, "text": self.format(record), "ch": self.channel_of(record)})
        except Exception:
            pass


class DailyApi:
    """self.paths, self._emit(채널, 값) 이 있는 클래스에 섞는다."""

    _daily_runner: Runner | None = None
    _daily_thread: threading.Thread | None = None
    _daily_log_hooked = False

    def _daily_hook_log(self) -> None:
        if not self._daily_log_hooked:
            log.addHandler(_LogToScreen(self._emit, self._log_channel))
            self._daily_log_hooked = True

    def _log_channel(self, record) -> str:
        """이 로그 줄이 어느 탭 것인가. 남긴 스레드로 본다 — 숙제·어비스 스레드는 그대로, 작업 큐 스레드는 그때 돌던 카드
        (화면 설정 맞추기 등). 그 밖(F12 감시, 화면 설정 되돌리기 …)은 둘 다."""
        name = record.threadName or ""
        if name in ("daily", "abyss", "raid"):
            return "abyss" if name == "raid" else name  # 레이드는 어비스 탭에 같이 있다
        q = getattr(self, "queue", None)
        if name == "work-queue" and q:
            cur = q.current()
            if cur and cur.get("kind") in ("daily", "abyss", "raid"):
                return "abyss" if cur["kind"] == "raid" else cur["kind"]
        return "all"

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
    @staticmethod
    def _alive(t: threading.Thread | None) -> bool:
        """돌고 있나. 작업 큐가 앞 작업의 끝 이벤트를 받자마자 다음 것을 시작하면 앞 스레드가 정리 중이라
        아직 살아 있다 → 잠깐 기다려 본다."""
        if t and t.is_alive():
            t.join(5)
        return bool(t and t.is_alive())

    def _busy_reason(self) -> str | None:
        """숙제·어비스·캐릭터 자동 설정 중 하나가 돌고 있으면 그 이유 (게임 조작이 겹치면 안 된다)."""
        if self._alive(self._daily_thread):
            return "일일 숙제가 도는 중입니다"
        if getattr(self, "_scan_thread", None) and self._scan_thread.is_alive():
            return "캐릭터 자동 설정이 도는 중입니다"
        if self._alive(self._abyss_thread):
            return "어비스 반복이 도는 중입니다"
        if self._alive(self._raid_thread):
            return "레이드 반복이 도는 중입니다"
        return None

    _daily_result: tuple = ("failed", "")

    def _daily_launch(self, run_opts: RunOptions, on_event=None) -> threading.Thread:
        """숙제를 작업 스레드에서 돌리고 그 스레드를 돌려준다 (작업 큐가 join 으로 기다린다).
        결과는 self._daily_result = ('done', results) | ('failed', 메시지). 진행은 'mm:daily' 로 화면에.
        F12 로 멈춘 뒤 이어 하기는 작업 큐가 한다 (queue_api — 진행 기록으로 끊긴 자리부터)."""
        self._daily_hook_log()
        on_event = on_event or (lambda e: None)

        def event(e):
            self._emit("mm:daily", e)
            on_event(e)
        runner = Runner(self.paths, on_event=event, force_exit=False)
        self._daily_runner = runner
        self._daily_end = False

        def work():
            try:
                results = runner.run(run_opts)
            except Exception as e:  # 설정 오류, 게임 창 없음 등
                log.exception("일일 숙제 실행 실패")
                msg = str(e) if isinstance(e, (ValueError, RuntimeError)) else f"{type(e).__name__}: {e}"
                self._daily_result = ("failed", msg)
                self._emit("mm:daily", {"type": "failed", "message": msg})
                return
            self._daily_result = ("done", results)
            # F12·일시정지 버튼으로 멈췄으면 '일시정지' — F12 를 다시 누르면 이어 한다 (작업 큐).
            # 큐에서 숙제 카드를 지워 멈춘 것(_daily_end)은 종료
            if any(s == "STOP" for _, s, _ in results or []) and not self._daily_end:
                log.info("일시정지 — F12 를 다시 누르면 이어 합니다")
                self._emit("mm:daily", {"type": "paused"})
            # 결과 창은 작업 큐가 다 끝났을 때 큐 전체 결과로 띄운다 (queue_api._q_report)
        self._daily_thread = threading.Thread(target=work, name="daily", daemon=True)
        self._daily_thread.start()
        return self._daily_thread

    def _bring_front(self) -> None:
        """리모콘 창을 게임 위로. 다른 프로세스(게임)가 맨 앞이면 Windows 가 SetForegroundWindow 를 막아 작업 표시줄만
        깜빡이므로, 게임 창을 앞으로 가져올 때(GameWindow.focus)와 같은 방법(window.bring_front)으로 가져온다."""
        from mabi.window import bring_front

        def go():
            w = self.win
            if w is None:
                return
            w.show_window()
            bring_front(int(w.winId()))
        try:
            self._on_gui(go)
        except Exception:
            log.exception("결과 창을 앞으로 가져오지 못함")

    def daily_stop(self, end: bool = False) -> dict:
        """end=False: 일시정지 (F12 로 이어 함), True: 종료 (큐에서 카드를 지움)."""
        self._daily_end = bool(end)
        if self._daily_runner:
            self._daily_runner.stop()
        return {"ok": True}

    # ---- 게임 화면 설정 (숙제·어비스 시작 전에 작업 큐가 확인·맞춤 — queue_api._q_display) ----
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

    def _display_fix_sync(self) -> dict:
        """화면 설정 맞추기 (막는다). {ok, message, running}."""
        from mabi.bot import Bot
        from mabi.tasks import display
        bot = None
        try:
            self._daily_hook_log()
            cfg = load_config(self.paths)
            bot = Bot(cfg, self.paths, force_exit=False)
            msg = display.ensure(bot, cfg, self.paths.data / "backup", remember=self.paths.data / display.RESTORE_FILE)
            log.info(f"화면 설정: {msg}")
            return {"ok": True, "message": msg, "running": display.game_running(bot.window)}
        except Exception as e:
            log.exception("화면 설정 맞추기 실패")
            return {"ok": False, "message": f"{e}"}
        finally:
            if bot:
                bot.stopper.close()

    def daily_displayRestore(self) -> dict:  # noqa: N802
        """작업 큐가 다 끝났을 때 한 번: 숙제·어비스 동안 맞춰 둔 인터페이스와 화면 모드·해상도를 원래대로.
        기억해 둔 게 없으면 아무것도 안 한다. 끝나면 'mm:display' {restored, message}."""
        if self._display_thread and self._display_thread.is_alive():
            return {"error": "화면 설정 작업 중입니다"}
        if self._alive(self._daily_thread) or self._alive(self._abyss_thread):
            return {"error": "숙제·어비스가 도는 중입니다"}

        def work():
            from mabi.bot import Bot
            from mabi.tasks import display
            bot, msgs = None, []
            try:
                self._daily_hook_log()
                cfg = load_config(self.paths)
                bot = Bot(cfg, self.paths, force_exit=False)
                state = prof.DailyState(self.paths.state)
                if state.data.get(display.RESTORE_KEY) and bot.window.find():
                    msgs.append(display.restore_interface(bot, state))
                if (self.paths.data / display.RESTORE_FILE).is_file():
                    msgs.append(display.restore_screen(bot, self.paths.data / display.RESTORE_FILE))
                msg = " · ".join(m for m in msgs if m)
                if msg:
                    log.info(f"작업 큐 끝 → {msg}")
                self._emit("mm:display", {"restored": True, "ok": True, "message": msg})
            except Exception as e:
                log.warning(f"화면 설정을 되돌리지 못함 — 다음 큐가 끝날 때 다시 시도: {e}")
                self._emit("mm:display", {"restored": True, "ok": False, "message": str(e)})
            finally:
                if bot:
                    bot.stopper.close()
        self._display_thread = threading.Thread(target=work, name="display-restore", daemon=True)
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
                "minutes": float(a.get("minutes", 0)), "dungeons": abyss.DUNGEONS,
                "revive": bool(a.get("revive", True)),
                "difficulties": abyss.DIFFICULTIES,
                "running": bool(self._abyss_thread and self._abyss_thread.is_alive())}

    _abyss_result: dict = {}

    def _abyss_launch(self, v: dict, on_event=None) -> threading.Thread:
        """고른 던전·난이도·횟수·시간을 config.toml [abyss] 에 저장하고 반복을 작업 스레드에서 시작한다 (작업 큐가 join).
        진행은 'mm:abyss' {type: start|abyss|done|failed, clears, deaths, ...}, 결과는 self._abyss_result (끝 이벤트와 같은 값)."""
        def save(a):
            a["dungeon"] = str(v.get("dungeon") or "허상의 정박지")
            a["difficulty"] = str(v.get("difficulty") or "매우 어려움2")
        return self._repeat_launch("abyss", "어비스", v, save, on_event)

    # ---- 레이드 반복 (mabi.tasks.raid) — 어비스와 같은 틀 ----
    _raid_thread: threading.Thread | None = None
    _raid_bot = None
    _raid_result: dict = {}

    def daily_raidSettings(self) -> dict:  # noqa: N802
        from mabi.tasks import raid
        r = load_config(self.paths)["raid"]
        return {"raid": r["raid"], "difficulty": r.get("difficulty") or "어려움", "slot": int(r.get("slot", 0)),
                "runs": int(r.get("runs", 0)), "minutes": float(r.get("minutes", 0)), "revive": bool(r.get("revive", True)),
                "raids": raid.RAIDS, "difficulties": raid.DIFFICULTIES,
                "running": bool(self._raid_thread and self._raid_thread.is_alive())}

    def _raid_launch(self, v: dict, on_event=None) -> threading.Thread:
        """레이드 반복 — [raid] 에 저장하고 시작 ('mm:raid', self._raid_result). 나머지는 _abyss_launch 와 같다."""
        def save(a):
            a["raid"] = str(v.get("raid") or "카브락")
            a["difficulty"] = str(v.get("difficulty") or "어려움")
        return self._repeat_launch("raid", "레이드", v, save, on_event)

    def daily_raidStop(self) -> dict:  # noqa: N802
        if self._raid_bot:
            self._raid_bot.stopper.request()
        return {"ok": True}

    def _repeat_launch(self, kind: str, title: str, v: dict, save, on_event=None) -> threading.Thread:
        """어비스·레이드 반복 공통: config.toml [kind] 에 저장하고 mabi.tasks.<kind>.repeat 를 작업 스레드에서."""
        on_event = on_event or (lambda e: None)

        def event(e):
            self._emit(f"mm:{kind}", e)
            on_event(e)
            if e.get("type") in ("done", "failed"):
                setattr(self, f"_{kind}_result", e)
        setattr(self, f"_{kind}_result", {"type": "failed", "message": "시작하지 못함"})
        doc = self._doc()
        if kind not in doc:
            doc[kind] = tomlkit.table()
        a = doc[kind]
        save(a)
        a["slot"] = max(0, int(v.get("slot") or 0))
        a["runs"] = max(0, int(v.get("runs") or 0))
        a["minutes"] = max(0, int(v.get("minutes") or 0))
        a["revive"] = v.get("revive") is not False
        userconfig.save(self.paths, doc)
        event({"type": "start"})

        def work():
            import importlib
            from mabi.bot import Bot, StopRequested
            task = importlib.import_module(f"mabi.tasks.{kind}")
            bot = None
            from mabi.queue_report import LootMeter
            meter = LootMeter(lambda x: event({"type": "loot", **x}))
            try:
                self._daily_hook_log()
                cfg = load_config(self.paths)
                bot = Bot(cfg, self.paths, force_exit=False)
                setattr(self, f"_{kind}_bot", bot)
                if not bot.window.find():
                    raise ValueError("게임이 꺼져 있습니다")
                # '게임 조작 감지' 일시정지는 쓰지 않는다 — 어비스 반복은 게임을 뒤에 두고 PC 를 계속 쓰는 기능인데,
                # 게임이 잠깐 앞에 있을 때 누른 키(Alt+Tab 등)로 매칭 중에 멈췄다 (2026-10-23). 멈추기는 F12·버튼으로
                a = cfg[kind]  # 게임은 입장할 때만 앞으로 가져온다 (abyss.repeat)
                profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
                ch = next((c for c in prof.characters(profile) if c["slot"] == int(a.get("slot", 0))), None)
                from mabi.tasks import display
                if v.get("interface") and (why := display.busy(bot)):  # 어비스 안·매칭 중 — ESC 가 나가기·매칭 취소가 된다
                    log.info(f"{why} → 인터페이스 맞추기는 건너뜀")
                elif v.get("interface"):  # 화면 설정 맞추기 — 인터페이스 PC·80% (큐에서 이번 처음일 때만, 되돌리기는 큐 끝)
                    try:
                        log.info(display.prepare_interface(bot, prof.DailyState(self.paths.state)))
                    except Exception as e:
                        log.warning(f"인터페이스 PC·80% 로 맞추지 못함 — 그대로 진행: {e}")
                res = task.repeat(bot, cfg, int(a["runs"]), float(a["minutes"]), on_event=event, character=ch, loot=meter)
                event({"type": "done", **res})
            except StopRequested:
                log.info(f"{title} 반복: 사용자 중단")
                event({"type": "done", "stopped": True})
            except Exception as e:
                log.exception(f"{title} 반복 실패")
                event({"type": "failed", "message": str(e)})
            finally:
                setattr(self, f"_{kind}_bot", None)
                if bot:
                    try:
                        meter.close(bot)  # 멈췄어도 그때까지 얻은 것
                    except Exception:  # noqa: BLE001 — 못 재도 끝맺음은 한다
                        log.exception(f"{title} 반복: 얻은 것 재기 실패")
                    bot.stopper.close()
        t = threading.Thread(target=work, name=kind, daemon=True)
        setattr(self, f"_{kind}_thread", t)
        t.start()
        return t

    def daily_abyssStop(self) -> dict:  # noqa: N802
        if self._abyss_bot:
            self._abyss_bot.stopper.request()
        return {"ok": True}

    # ---- 캐릭터·숙제 설정 ----
    def _doc(self):
        return userconfig.doc(self.paths)

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
        sun_by = doc["weekday_dungeon"].get("sunday_by_slot", {})
        return {
            "chars": [{**c, **{k: v for k, v in dict(by.get(str(c["slot"]), {})).items()
                               if k in ("field_runs", "dungeon", "floor")}} for c in chars],
            "follow": {"field": follow("field", "field_runs"), "dungeon": follow("dungeon", "floor"),
                       "sunday": sum(str(c["slot"]) not in sun_by for c in chars), "total": len(chars)},
            "sunday": CharsApi._sunday(doc), "sundays": list(SUNDAY_CHOICES),
            "silver": {"field_runs": int(s["field_runs"]), "dungeon": str(s["dungeon"]), "floor": int(s["floor"])},
            "dungeons": [n for n, p in doc["places"].items() if int(p["index"]) < 2],
            "fields": [n for n, p in doc["places"].items() if int(p["index"]) == 2],
            "field": str(s["field"]),
            "stop_key": str(doc["game"].get("stop_key", "f12")),
            "pause_on_touch": bool(doc["game"].get("pause_on_touch", True)),
            "fit_display": bool(doc["run"].get("fit_display", True)),
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
        if v.get("sunday") in SUNDAY_CHOICES:
            doc["weekday_dungeon"]["sunday"] = v["sunday"]
        if v.get("stop_key"):
            k = str(v["stop_key"]).lower()
            if k not in [f"f{i}" for i in range(1, 13)]:  # 게임이 쓰는 글자·Home/End 키와 겹치지 않게 F 키만
                return {"error": f"일시정지 키는 F1~F12 중에서: {k}"}
            doc["game"]["stop_key"] = k
        if "pause_on_touch" in v:
            doc["game"]["pause_on_touch"] = bool(v["pause_on_touch"])
        if "fit_display" in v:
            doc["run"]["fit_display"] = bool(v["fit_display"])
        userconfig.save(self.paths, doc)
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
