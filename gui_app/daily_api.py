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
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field

import tomlkit

from mabi import keys as gkeys
from mabi import paths as mpaths
from mabi import profile as prof
from mabi import userconfig
from mabi import tasks
from mabi.runner import RunOptions, Runner, load_config, task_order, tasks_by_slot
from mabi.tasks.weekday import SUNDAY_CHOICES

from .chars_api import CharsApi

log = logging.getLogger("mabi")

# 게임을 조작하는 일(스레드·Bot 주인) → 다른 일을 시작하지 못하는 까닭 (_busy_reason)
BUSY = {"daily": "일일 숙제가 도는 중입니다", "scan": "캐릭터 자동 설정이 도는 중입니다",
        "abyss": "어비스 반복이 도는 중입니다", "raid": "레이드 반복이 도는 중입니다",
        "display": "화면 설정 작업 중입니다", "enhance": "각인 강화 반복이 도는 중입니다",
        "restart": "게임을 다시 켜는 중입니다", "char": "카드 캐릭터를 맞추는 중입니다"}

# 반복 종류 → (제목, 장소 칸 = config [종류] 의 키·카드 칸). 둘 다 mabi.tasks.<종류>.repeat 를 같은 틀로 돌린다
REPEATS = {"abyss": ("어비스", "dungeon"), "raid": ("레이드", "raid")}


@dataclass
class RepeatRun:
    """어비스·레이드 반복 한 종류의 상태. Bot 은 다른 게임 조작과 같이 주인 이름(종류)으로 등록한다 (DailyApi._bots)."""
    thread: threading.Thread | None = None
    result: dict = field(default_factory=dict)  # 끝 이벤트 {type: done|failed, stopped?, message?, ...}


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
        st = prof.DailyState(self.paths.state)
        chars = prof.chars(self.paths)
        by_slot = tasks_by_slot(cfg)
        return {"chars": chars, "order": cfg["run"]["order"], "labels": {"login": "접속", **{t: l for t, (l, _) in reg.items()}},
                "today": {str(c["slot"]): st.data.get(str(c["slot"]), {}) for c in chars}, "date": st.date,
                "skip": {k: list(v) for k, v in cfg["run"].get("skip_by_slot", {}).items()},
                # 캐릭터마다 실제로 도는 숙제 (끈 숙제·아르바이트 안 켠 캐릭터는 빠짐) — '결과 보기' 가 쓴다
                "orders": {str(c["slot"]): task_order(cfg, c, by_slot=by_slot) for c in chars},
                "running": bool(self._daily_thread and self._daily_thread.is_alive())}

    # ---- 실행 ----
    @staticmethod
    def _alive(t: threading.Thread | None) -> bool:
        """돌고 있나. 작업 큐가 앞 작업의 끝 이벤트를 받자마자 다음 것을 시작하면 앞 스레드가 정리 중이라
        아직 살아 있다 → 잠깐 기다려 본다."""
        if t and t.is_alive():
            t.join(5)
        return bool(t and t.is_alive())

    @property
    def _bots(self) -> dict:
        """지금 게임을 조작하는 Bot {주인: Bot} — _game_bot 이 넣고 뺀다. 멈추기(_bot_stop)·_busy_reason 이 여기 하나만 본다."""
        return self.__dict__.setdefault("_bot_owners", {})

    @contextmanager
    def _game_bot(self, owner: str | None, cfg: dict | None = None):
        """게임 조작용 Bot 하나의 수명: 만들기 → 주인 이름으로 등록 → 끝나면 빼고 닫기 (키 감시 정리).
        owner=None 은 등록하지 않는다 (잠깐 화면만 보는 확인 — 다른 일을 막지 않게). 만들다 실패하면 예외가 그대로 나간다
        (부르는 쪽이 `bot = None` … `with … as bot` 이면 except 에서 bot 이 None 인지로 '시작 실패' 를 가른다)."""
        from mabi.bot import Bot
        self._daily_hook_log()
        bot = Bot(cfg if cfg is not None else load_config(self.paths), self.paths, force_exit=False)
        if owner:
            self._bots[owner] = bot
        try:
            yield bot
        finally:
            if owner and self._bots.get(owner) is bot:
                del self._bots[owner]
            bot.stopper.close()

    def _bot_stop(self, owner: str, why: str = "") -> dict:
        """그 주인의 Bot 에 멈춤을 요청한다 (돌고 있지 않으면 아무것도). why: 사람이 아닌 까닭 (로그에)."""
        bot = self._bots.get(owner)
        if bot:
            bot.stopper.request(why)
        return {"ok": True}

    def _busy_reason(self) -> str | None:
        """게임을 조작하는 일이 돌고 있으면 그 까닭 (게임 조작이 겹치면 안 된다). 작업 스레드(숙제·어비스·레이드·
        캐릭터 자동 설정·화면 설정 되돌리기)와 등록된 Bot(큐 카드의 캐릭터 맞추기·각인 강화·게임 다시 켜기·화면 설정)을
        모두 본다. 큐 카드는 자기 Bot 을 만들기 전에 부르므로 자기 때문에 막히지 않는다."""
        if self._alive(self._daily_thread):
            return BUSY["daily"]
        if self._alive_now(getattr(self, "_scan_thread", None)):
            return BUSY["scan"]
        for owner in ("abyss", "raid"):
            if self._alive(self._rep(owner).thread):
                return BUSY[owner]
        if self._alive(self._display_thread):  # 큐 끝의 화면 설정 되돌리기 — 잠깐 기다려 본다
            return BUSY["display"]
        for owner in list(self._bots):
            return BUSY.get(owner, "게임 조작이 도는 중입니다")
        return None

    @staticmethod
    def _alive_now(t: threading.Thread | None) -> bool:
        return bool(t and t.is_alive())

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

    def daily_stop(self, end: bool = False, why: str = "") -> dict:
        """end=False: 일시정지 (F12 로 이어 함), True: 종료 (큐에서 카드를 지움). why: 사람이 아닌 까닭 (로그에)."""
        self._daily_end = bool(end)
        if self._daily_runner:
            self._daily_runner.stop(why)
        return {"ok": True}

    # ---- 게임 화면 설정 (숙제·어비스 시작 전에 작업 큐가 확인·맞춤 — queue_api._q_display) ----
    _display_thread: threading.Thread | None = None

    def daily_displayCheck(self, opts: dict | None = None) -> dict:  # noqa: N802
        """{ok, running, problems, target}. 게임 창 크기·화면 모드 (1초 안팎).
        고른 캐릭터·숙제가 오늘 다 끝났으면 화면을 보지 않고 ok (idle) — 숙제는 '오늘 완료' 만 알리고 게임을 건드리지 않는다."""
        from mabi.tasks import display
        target = "테두리 없는 전체화면 · 16:9 (1280×720 이상) — 숙제 동안만 맞추고 끝나면 원래대로"
        try:
            o = opts or {}
            run_opts = RunOptions(chars=o.get("chars") or None, only=o.get("only") or None, force=bool(o.get("force")))
            # 어비스·레이드 카드는 숙제가 다 끝난 날에도 화면을 본다 (always) — 예전엔 숙제 기준으로 건너뛰어 한 번도 안 봤다
            if not o.get("always") and not Runner(self.paths, force_exit=False).has_work(run_opts):
                return {"ok": True, "idle": True, "running": True, "problems": [], "target": target}
            with self._game_bot(None) as bot:  # 화면만 잠깐 본다 — 등록하지 않는다
                if not display.game_running(bot.window):
                    return {"ok": False, "running": False, "problems": ["게임이 꺼져 있음"], "target": target}
                return {**display.check(bot, interface=False), "target": target}
        except Exception as e:
            log.exception("화면 설정 확인 실패")
            return {"ok": False, "running": False, "problems": [f"확인 실패: {e}"], "target": target}

    def _display_fix_sync(self) -> dict:
        """화면 설정 맞추기 (막는다). {ok, message, running}."""
        from mabi.tasks import display
        try:
            cfg = load_config(self.paths)
            with self._game_bot("display", cfg) as bot:
                msg = display.ensure(bot, cfg, self.paths.data / "backup", remember=self.paths.data / display.RESTORE_FILE)
                log.info(f"화면 설정: {msg}")
                return {"ok": True, "message": msg, "running": display.game_running(bot.window)}
        except Exception as e:
            log.exception("화면 설정 맞추기 실패")
            return {"ok": False, "message": f"{e}"}

    def daily_displayRestore(self) -> dict:  # noqa: N802
        """작업 큐가 다 끝났을 때 한 번: 숙제·어비스 동안 맞춰 둔 인터페이스와 화면 모드·해상도를 원래대로.
        기억해 둔 게 없으면 아무것도 안 한다. 끝나면 'mm:display' {restored, message}."""
        if self._display_thread and self._display_thread.is_alive():
            return {"error": "화면 설정 작업 중입니다"}
        if (why := self._busy_reason()):  # 숙제·어비스·레이드 중 무엇이든 (예전엔 레이드를 빠뜨렸다)
            return {"error": why}

        def work():
            from mabi.tasks import display
            msgs = []
            try:
                with self._game_bot("display") as bot:
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
        self._display_thread = threading.Thread(target=work, name="display-restore", daemon=True)
        self._display_thread.start()
        return {"ok": True}

    # ---- 어비스·레이드 반복 (mabi.tasks.abyss · raid) — 종류마다 RepeatRun 하나 ----
    def _rep(self, kind: str) -> RepeatRun:
        return self.__dict__.setdefault("_repeat", {}).setdefault(kind, RepeatRun())

    def _rep_default(self, kind: str, key: str) -> str:
        """화면·카드가 비워 보낸 값의 기본값 (config.default.toml [종류])."""
        return str(userconfig.default(self.paths, kind, key, ""))

    def daily_abyssSettings(self) -> dict:  # noqa: N802
        a = load_config(self.paths)["abyss"]
        from mabi.tasks import abyss
        return {"dungeon": a["dungeon"], "difficulty": a.get("difficulty") or self._rep_default("abyss", "difficulty"),
                "runs": int(a.get("runs", 0)),
                "slot": int(a.get("slot", 0)), "chars": [{"slot": c["slot"], "name": c["name"]} for c in prof.chars(self.paths)],
                "minutes": float(a.get("minutes", 0)), "dungeons": abyss.dungeons(), "frontOnly": list(abyss.FRONT_ONLY),
                "revive": bool(a.get("revive", True)), "mode": a.get("mode") or self._rep_default("abyss", "mode"),
                "difficulties": abyss.difficulties(),
                "running": self._alive_now(self._rep("abyss").thread)}

    # ---- 보스전 기본값 (어비스·레이드 탭) — 캐릭터 탭에서 따로 정하지 않은 캐릭터에 ----
    def daily_bossSettings(self) -> dict:  # noqa: N802
        from mabi.tasks import boss_skills
        b = self._doc().get("boss_skills", {})
        chars = prof.chars(self.paths)

        def follow(kind) -> int:  # 이 기본값을 따르는 캐릭터 수
            own = {int(x) for s in ("_slots", "_off_slots") for x in b.get(kind + s, [])}
            return sum(c["slot"] not in own for c in chars)
        return {**{k: bool(b.get(k, False)) for k in boss_skills.KINDS},
                "follow": {**{k: follow(k) for k in boss_skills.KINDS}, "total": len(chars)}}

    def daily_saveBoss(self, v: dict) -> dict:  # noqa: N802
        """보스전 기본값 저장. 새 기본값과 같아진 캐릭터별 설정은 지운다 (그 캐릭터는 기본값을 따름)."""
        from mabi.tasks import boss_skills
        with userconfig.LOCK:  # 화면·작업 큐가 함께 고친다
            doc = self._doc()
            if "boss_skills" not in doc:
                doc["boss_skills"] = tomlkit.table()
            b = doc["boss_skills"]
            for kind in boss_skills.KINDS:
                if kind not in v:
                    continue
                on = bool(v[kind])
                b[kind] = on
                same = kind + ("_slots" if on else "_off_slots")
                if same in b:
                    b[same] = tomlkit.array()
            userconfig.save(self.paths, doc)
        return {"ok": True}

    def daily_raidSettings(self) -> dict:  # noqa: N802
        from mabi.tasks import raid
        r = load_config(self.paths)["raid"]
        raids = raid.raids()
        return {"raid": r["raid"], "difficulty": r.get("difficulty") or self._rep_default("raid", "difficulty"),
                "slot": int(r.get("slot", 0)),
                "runs": int(r.get("runs", 0)), "minutes": float(r.get("minutes", 0)), "revive": bool(r.get("revive", True)),
                "mode": r.get("mode") or self._rep_default("raid", "mode"), "raids": list(raids),
                "difficulties": raids, "running": self._alive_now(self._rep("raid").thread)}

    def daily_fieldBossSettings(self) -> dict:  # noqa: N802
        """필드 보스 칸의 보스·난이도 목록과 기본값 (mabi.tasks.field_boss). 고른 값은 화면이 fieldBoss 로 기억한다."""
        from mabi.tasks import field_boss
        return field_boss.choices()

    def _repeat_launch(self, kind: str, v: dict, on_event=None) -> threading.Thread:
        """어비스·레이드 반복 (kind: REPEATS): 고른 장소(던전·레이드)·난이도·횟수·시간을 config.toml [kind] 에 저장하고
        mabi.tasks.<kind>.repeat 를 작업 스레드에서 시작한다 (작업 큐가 join). 진행은 'mm:<kind>'
        {type: start|<kind>|done|failed, clears, deaths, ...}, 결과는 self._rep(kind).result (끝 이벤트와 같은 값)."""
        title, place = REPEATS[kind]
        rep = self._rep(kind)
        on_event = on_event or (lambda e: None)

        def event(e):
            self._emit(f"mm:{kind}", e)
            on_event(e)
            if e.get("type") in ("done", "failed"):
                rep.result = e
        rep.result = {"type": "failed", "message": "시작하지 못함"}
        with userconfig.LOCK:  # 화면·작업 큐가 함께 고친다
            doc = self._doc()
            if kind not in doc:
                doc[kind] = tomlkit.table()
            a = doc[kind]
            a[place] = str(v.get(place) or self._rep_default(kind, place))
            a["difficulty"] = str(v.get("difficulty") or self._rep_default(kind, "difficulty"))
            if v.get("mode") in ("solo", "party"):  # 없으면(예전 카드·명령) 탭에 고른 그대로
                a["mode"] = v["mode"]
            a["slot"] = max(0, int(v.get("slot") or 0))
            a["runs"] = max(0, int(v.get("runs") or 0))
            a["minutes"] = max(0, int(v.get("minutes") or 0))
            a["revive"] = v.get("revive") is not False
            userconfig.save(self.paths, doc)
        event({"type": "start"})

        def work():
            import importlib
            from mabi.queue_report import LootMeter
            task = importlib.import_module(f"mabi.tasks.{kind}")
            meter = LootMeter(lambda x: event({"type": "loot", **x}))
            with ExitStack() as stack:  # 끝나면 Bot 등록을 빼고 닫는다
                try:
                    cfg = load_config(self.paths)
                    bot = stack.enter_context(self._game_bot(kind, cfg))
                except Exception as e:  # noqa: BLE001 — Bot 을 만들지 못함 (설정 오류 등)
                    log.exception(f"{title} 반복 시작 실패")
                    event({"type": "failed", "message": str(e)})
                    return
                self._repeat_body(kind, title, task, bot, cfg, v, event, meter)
        rep.thread = threading.Thread(target=work, name=kind, daemon=True)
        rep.thread.start()
        return rep.thread

    def _repeat_body(self, kind, title, task, bot, cfg, v, event, meter) -> None:
        """반복 한 번 (Bot 은 부르는 쪽이 _game_bot 으로 쥐고 있다). 실패는 outcome 으로 가른다 — 키 감시가 살아 있는 동안
        (나와 두기·게임 상태 확인이 F12 로 멈출 수 있게)."""
        from mabi import outcome
        try:
            if not bot.window.find():
                raise ValueError("게임이 꺼져 있습니다")
            a = cfg[kind]  # 게임은 입장할 때만 앞으로 가져온다 (abyss.repeat)
            ch = next((c for c in prof.chars(self.paths) if c["slot"] == int(a.get("slot", 0))), None)
            from mabi.tasks import display
            # 화면 설정 맞추기 — 인터페이스 PC·80% (큐에서 이번 처음일 때만, 되돌리기는 큐 끝). 일일 숙제와 같은 InterfaceFit
            fit = display.InterfaceFit(prof.DailyState(self.paths.state), enabled=bool(v.get("interface")),
                                       on_fit=lambda: event({"type": "interface"}))
            res = task.repeat(bot, cfg, int(a["runs"]), float(a["minutes"]), on_event=event, character=ch, loot=meter,
                              iface=fit)
            event({"type": "done", **res})
        except Exception as e:  # noqa: BLE001 — 가르는 규칙은 일일 숙제와 같은 outcome
            status, summary, messy = outcome.classify(bot, kind, f"{title} 반복", e)
            if messy:
                outcome.recover(bot)  # 어비스·레이드 안에서 실패했으면 나와 둔다 — 다음 카드가 그 안에서 시작하지 않게
            status, summary = outcome.escalate(bot, status, summary)
            if status == "STOP":  # 사용자 중단·게임 꺼짐·연속 실행 제한 → 일시정지 (▶ 로 다시)
                event({"type": "done", "stopped": True, "message": summary})
            else:
                event({"type": "failed", "message": summary})
        finally:
            try:
                meter.close(bot)  # 멈췄어도 그때까지 얻은 것
            except Exception:  # noqa: BLE001 — 못 재도 끝맺음은 한다
                log.exception(f"{title} 반복: 얻은 것 재기 실패")

    def _repeat_stop(self, kind: str, why: str = "") -> dict:
        return self._bot_stop(kind, why)

    # 화면이 부르는 이름 그대로 (web/bridge.js mm.daily.abyssStop · raidStop)
    def daily_abyssStop(self, why: str = "") -> dict:  # noqa: N802
        return self._repeat_stop("abyss", why)

    def daily_raidStop(self, why: str = "") -> dict:  # noqa: N802
        return self._repeat_stop("raid", why)

    # ---- 캐릭터·숙제 설정 ----
    def _doc(self):
        return userconfig.doc(self.paths)

    def daily_settings(self) -> dict:
        doc = self._doc()
        s = doc["silver"]
        over = {}
        f = mpaths.default_data_dir() / "paths.json"
        try:
            over = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except ValueError:
            pass
        by = s.get("by_slot", {})
        chars = prof.chars(self.paths)

        def follow(*keys) -> int:  # 이 기본값을 따르는 캐릭터 수 (그 항목을 캐릭터별로 따로 정하지 않음)
            return sum(not any(k in by.get(str(c["slot"]), {}) for k in keys) for c in chars)
        sun_by = doc["weekday_dungeon"].get("sunday_by_slot", {})
        return {
            "chars": [{**c, **{k: v for k, v in dict(by.get(str(c["slot"]), {})).items()
                               if k in ("field_runs", "dungeon", "floor")}} for c in chars],
            "follow": {"field": follow("field", "field_runs"), "dungeon": follow("dungeon", "floor"),
                       "sunday": sum(str(c["slot"]) not in sun_by for c in chars), "total": len(chars)},
            "sunday": CharsApi._sunday(doc), "sundays": list(SUNDAY_CHOICES),
            "silver": {k: v for k, v in userconfig.silver_defaults(doc).items() if k != "field"},
            "dungeons": userconfig.places(doc, "dungeon"), "fields": userconfig.places(doc, "field"),
            "field": str(s["field"]),
            "stop_key": str(doc["game"].get("stop_key", "f12")),
            "dye_key": str(doc["game"].get("dye_key", "f11")),
            "game_keys": [{"name": n, "label": label, "default": d, "key": gkeys.of(doc, n)}
                          for n, (d, label) in gkeys.GAME_KEYS.items()],
            "fit_display": bool(doc["run"].get("fit_display", True)),
            "restart_auto": bool(doc["restart"].get("auto", True)),
            "paths": {k: over.get(k, "") for k in ("data", "logs", "shots")},
            "current": {"data": str(self.paths.data), "logs": str(self.paths.logs), "shots": str(self.paths.shots)},
        }

    def daily_saveSettings(self, v: dict) -> dict:  # noqa: N802 (화면 이름 그대로)
        """숙제 공통 설정. 캐릭터별 설정은 캐릭터 탭이 chars_save 로 저장한다."""
        with userconfig.LOCK:  # 화면·작업 큐가 함께 고친다
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
                if not userconfig.is_fkey(k):  # 게임이 쓰는 글자·Home/End 키와 겹치지 않게 F 키만
                    return {"error": f"일시정지 키는 F1~F12 중에서: {k}"}
                doc["game"]["stop_key"] = k
            if v.get("dye_key"):
                k = str(v["dye_key"]).lower()
                if not userconfig.is_fkey(k):
                    return {"error": f"염색 도우미 키는 F1~F12 중에서: {k}"}
                if k == str(doc["game"].get("stop_key", "f12")).lower():
                    return {"error": "염색 도우미 키가 일시정지 키와 같습니다"}
                doc["game"]["dye_key"] = k
            gk = v.get("game_keys") or {}
            mine = {str(doc["game"].get("stop_key", "f12")).lower(), str(doc["game"].get("dye_key", "f11")).lower()}
            for n, k in gk.items():
                k = str(k or "").strip().lower()
                if err := gkeys.check(n, k):
                    return {"error": err}
                if k in mine:
                    return {"error": f"{k.upper()} 는 리모콘의 일시정지·염색 도우미 키입니다"}
            for n, k in gk.items():
                doc["game"][f"{n}_key"] = str(k or "").strip().lower()
            if "fit_display" in v:
                doc["run"]["fit_display"] = bool(v["fit_display"])
            if "restart_auto" in v:
                doc["restart"]["auto"] = bool(v["restart_auto"])
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
