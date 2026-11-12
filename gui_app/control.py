"""다른 프로그램이 리모콘을 부리는 통로 — 상태 묻기와 조작을 JSON 으로 주고받는다.

예전 통로(web_main.SINGLE)는 두 번째로 켠 리모콘이 첫 리모콘에 글자 한 줄을 던지고 끝나는 일방통행이라,
밖에서는 명령이 받아들여졌는지도, 지금 무엇이 도는지도 알 수 없었다. 이 통로는 묻고 답한다.

통로: 이름 있는 파이프 ``\\\\.\\pipe\\MobiRemote-control`` (같은 Windows 사용자만 붙을 수 있다 — 리모콘이 관리자
권한으로 떠 있어도 일반 권한 프로그램이 붙는다). 한 줄에 JSON 하나 (UTF-8, 줄바꿈으로 끝).
  요청  {"id": 1, "cmd": "status", "args": {...}}
  답    {"id": 1, "ok": true, "data": {...}}   또는   {"id": 1, "ok": false, "error": "bad_args", "message": "..."}
  알림  {"event": "card", "data": {...}, "at": "2026-11-13T09:00:00"}   ('watch' 를 보낸 연결에만)
한 연결로 여러 요청을 보내도 된다. 답은 받은 순서와 다를 수 있으니 id 로 맞춘다.
무엇을 할 수 있는지는 'hello' 가 명령 목록(이름·설명·인자)으로 알려 준다 — 부르는 쪽이 목록을 따로 들고 있지 않아도 된다.

명령 하나하나는 화면 버튼·F12·예전 명령 통로와 같은 함수(작업 큐)를 부른다. 여기서 새 규칙을 만들지 않는다.
"""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("mabi")

PIPE = "MobiRemote-control"

ABOUT = ("모비 커넥터 리모콘 — 마비노기 모바일을 대신 조작하는 프로그램. 할 일은 작업 큐의 카드로 쌓이고 위에서부터 차례로 한다 "
         "(일일 숙제·어비스·레이드·가공 수령·각인 강화·게임 다시 켜기 등). 카드 상태: wait 대기 · run 하는 중 · pause 일시정지 · "
         "done 끝 · fail 실패 · skip 건너뜀. 일시정지 카드가 맨 위에 있으면 그 아래 카드도 돌지 않는다 — 'resume' 으로 이어 한다. "
         "게임 키보드의 F12 도 같은 일시정지·이어 하기다.")


class BadArgs(ValueError):
    """인자가 틀렸다 — 답의 error 는 bad_args, message 는 이 글."""


class Refused(RuntimeError):
    """지금은 할 수 없다 (다른 작업이 도는 중 등) — 답의 error 는 refused."""


@dataclass
class Command:
    name: str
    summary: str
    run: Callable[[dict], object]
    args: dict = field(default_factory=dict)  # 인자 이름 → 설명 (선택 인자는 설명 앞에 '(선택)')
    act: bool = False  # 게임·작업 큐를 바꾸는 명령인가 (False 면 묻기만)

    def describe(self) -> dict:
        return {"name": self.name, "summary": self.summary, "args": self.args, "act": self.act}


def _card(x: dict) -> dict:
    """작업 큐 카드 → 밖에 줄 모양 (화면용 내부 칸은 뺀다)."""
    v = x.get("view") or {}
    out = {"id": x.get("id"), "kind": x.get("kind"), "label": x.get("label") or "", "status": x.get("status"),
           "note": x.get("note") or ""}
    for k in ("goal", "now", "step", "stat"):
        if v.get(k):
            out[k] = v[k]
    if isinstance(v.get("bar"), (int, float)):
        out["bar"] = v["bar"]
    for k in ("slot", "chars", "dungeon", "raid", "difficulty", "runs", "mode", "only"):
        if x.get(k) not in (None, "", []):
            out[k] = x[k]
    return out


def _int(args: dict, key: str, default=None, low: int = 0) -> int:
    v = args.get(key, default)
    if v is None:
        raise BadArgs(f"'{key}' 가 필요합니다")
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise BadArgs(f"'{key}' 는 숫자여야 합니다: {v!r}") from None
    if n < low:
        raise BadArgs(f"'{key}' 는 {low} 이상이어야 합니다")
    return n


class LogRing(logging.Handler):
    """최근 로그 줄을 메모리에 들고 있는다 ('log' 명령). 파일을 다시 읽지 않는다."""

    def __init__(self, size: int = 400):
        super().__init__(logging.INFO)
        self.lines: collections.deque = collections.deque(maxlen=size)

    def emit(self, record):  # noqa: A003
        try:
            self.lines.append({"t": time.strftime("%H:%M:%S", time.localtime(record.created)),
                               "level": record.levelname, "text": record.getMessage()})
        except Exception:  # noqa: BLE001
            pass


class Commands:
    """명령 목록과 실행. api 는 gui_app.api.Api (시험에서는 가짜)."""

    def __init__(self, api, started: float | None = None, log_ring: LogRing | None = None):
        self.api = api
        self.started = started or time.time()
        self.ring = log_ring
        self.table: dict[str, Command] = {}
        for c in self._commands():
            self.table[c.name] = c

    # ---------------------------------------------------------------- 목록
    def _commands(self) -> list[Command]:
        slot = "캐릭터 슬롯 번호 (options 의 chars)"
        mode = "(선택) solo 혼자하기 · party 함께하기 — 비우면 리모콘 설정대로"
        runs = "(선택) 판 수 — 0 이나 비우면 멈출 때까지"
        return [
            Command("hello", "리모콘 이름·판·명령 목록과 이 프로그램 설명", self.hello),
            Command("status", "지금 상태 한눈에 — 작업 큐(하는 중인 카드·진행), 게임 창, 기다리는 질문", self.status),
            Command("queue", "작업 큐 카드 전체", lambda a: self._queue()),
            Command("options", "카드에 넣을 수 있는 값 — 캐릭터 슬롯, 숙제, 이번 주 어비스·레이드와 난이도", self.options),
            Command("history", "끝난 카드 기록 (최근 것부터)", self.history, {"limit": "(선택) 몇 개 — 기본 20"}),
            Command("report", "지난번 작업 큐가 끝났을 때의 결과 보고", lambda a: self.api.queue_lastReport()),
            Command("log", "리모콘 로그 최근 줄", self.log_lines,
                    {"n": "(선택) 몇 줄 — 기본 40", "level": "(선택) WARNING 이면 경고·오류만"}),
            Command("watch", "이 연결로 카드 시작·끝, 큐 끝, 질문, 알림을 계속 받는다", lambda a: {"watching": True}),
            Command("pause", "작업 큐 일시정지 — 지금 명령까지 끊는다 (F12 와 같음)", self.pause, act=True),
            Command("resume", "맨 위 일시정지 카드부터 이어 한다", self.resume, act=True),
            Command("skip", "지금 카드만 그만두고 다음 카드로 (Shift+F12 와 같음)", self.skip, act=True),
            Command("stop_all", "작업 큐 전체 중단 — 남은 카드를 모두 비운다 (Ctrl+F12 와 같음)", self.stop_all, act=True),
            Command("daily", "일일 숙제 카드를 넣고 큐를 돌린다", self.daily,
                    {"slots": "캐릭터 슬롯 번호 목록 — 비우면 모든 캐릭터",
                     "only": "(선택) 이 숙제만 (options 의 daily 이름이나 id 목록)",
                     "force": "(선택) true 면 오늘 끝낸 기록이 있어도 다시"}, act=True),
            Command("abyss", "어비스 반복 카드를 큐 뒤에 넣는다 (쉬고 있으면 바로 시작)", self.abyss,
                    {"slot": slot, "dungeon": "던전 이름 (options 의 abyss)", "runs": runs,
                     "difficulty": "(선택) 난이도 — 비우면 리모콘 설정대로", "mode": mode}, act=True),
            Command("raid", "레이드 반복 카드를 큐 뒤에 넣는다 (쉬고 있으면 바로 시작)", self.raid,
                    {"slot": slot, "raid": "레이드 이름 (options 의 raid)", "runs": runs,
                     "difficulty": "(선택) 난이도 — 비우면 리모콘 설정대로", "mode": mode}, act=True),
            Command("collect_all", "가공 완료분 전체 수령 카드를 맨 위에 넣고 바로", self.collect_all, act=True),
            Command("enhance", "각인 강화 반복을 지금 시작 (게임에 각인 강화 창을 열어 둔 상태에서, 다른 카드가 돌면 안 함)",
                    self.enhance, act=True),
            Command("restart_game", "게임을 껐다 켜서 같은 캐릭터로 접속 (꺼져 있으면 켠다). 돌던 카드는 그 뒤 이어서",
                    self.restart_game, act=True),
            Command("play", "그 카드를 지금 한다 (맨 위로 올려 시작)", self.play, {"id": "카드 id"}, act=True),
            Command("remove", "그 카드를 뺀다 (하는 중이면 멈추고 뺀다)", self.remove, {"id": "카드 id"}, act=True),
            Command("answer", "카드가 물어본 것(status 의 ask)에 답한다", self.answer,
                    {"id": "카드 id", "yes": "true 예 · false 아니오"}, act=True),
            Command("show", "리모콘 창을 앞으로 띄운다", self.show, act=True),
        ]

    def catalog(self) -> list[dict]:
        return [c.describe() for c in self.table.values()]

    # ---------------------------------------------------------------- 실행
    def run(self, name: str, args: dict | None = None) -> dict:
        """명령 하나 → 답 {ok, data} 또는 {ok: False, error, message}. 예외를 밖으로 내지 않는다."""
        c = self.table.get(str(name or ""))
        if c is None:
            return {"ok": False, "error": "unknown_command", "message": f"없는 명령: {name!r} — 'hello' 로 목록을 보세요"}
        args = args if isinstance(args, dict) else {}
        try:
            data = c.run(args)
        except BadArgs as e:
            return {"ok": False, "error": "bad_args", "message": str(e)}
        except Refused as e:
            return {"ok": False, "error": "refused", "message": str(e)}
        except Exception as e:  # noqa: BLE001 — 통로가 죽으면 안 된다
            log.exception(f"제어 명령 '{c.name}' 실패")
            return {"ok": False, "error": "failed", "message": f"{type(e).__name__}: {e}"}
        if c.act:
            log.info(f"제어 통로 → {c.name}" + (f" {json.dumps(args, ensure_ascii=False)}" if args else ""))
        return {"ok": True, "data": data}

    # ---------------------------------------------------------------- 묻기
    def hello(self, a: dict) -> dict:
        from .api import APP_NAME, APP_VERSION
        return {"app": APP_NAME, "version": APP_VERSION, "pid": os.getpid(), "about": ABOUT, "commands": self.catalog()}

    def _queue(self) -> dict:
        snap = self.api.queue.snapshot()
        return {"running": bool(snap.get("running")), "items": [_card(x) for x in snap.get("items") or []]}

    def status(self, a: dict) -> dict:
        from .api import APP_VERSION
        q = self._queue()
        items = q["items"]
        counts = collections.Counter(x["status"] for x in items)
        cur = next((x for x in items if x["status"] == "run"), None)
        top_pause = next((x for x in items if x["status"] == "pause"), None)
        pending = getattr(self.api, "_q_pending_ask", None)
        return {"version": APP_VERSION, "uptimeSec": int(time.time() - self.started),
                "game": {"window": self._game_window()},
                "connector": {"runLimited": bool(getattr(self.api.cli, "run_limited", False))},
                "queue": {"running": q["running"], "current": cur, "paused": top_pause,
                          "counts": dict(counts), "waiting": [x for x in items if x["status"] == "wait"]},
                "ask": pending["ask"] if pending else None}

    def _game_window(self) -> bool:
        """게임 창이 떠 있나 — 창 제목으로만 본다 (커넥터를 부르지 않는다: 자주 물어도 게임의 사용 제한에 안 잡히게)."""
        try:
            from mabi.runner import load_config
            from mabi.window import GameWindow
            return GameWindow(load_config(self.api.paths)["game"]["window_title"]).find()
        except Exception:  # noqa: BLE001
            return False

    def options(self, a: dict) -> dict:
        from mabi import gamedata as gd
        from mabi import profile as prof
        from mabi.tasks import TASKS
        ab, rd = self.api.daily_abyssSettings(), self.api.daily_raidSettings()
        return {"chars": [{"slot": c["slot"], "name": c["name"]} for c in prof.chars(self.api.paths)],
                "daily": [{"id": k, "name": v[0]} for k, v in TASKS.items()],
                "abyss": {"solo": gd.abysses(mode="solo"), "party": gd.abysses(mode="party"),
                          "default": {k: ab[k] for k in ("dungeon", "difficulty", "mode", "slot")}},
                "raid": {"difficulties": rd["difficulties"],
                         "default": {k: rd[k] for k in ("raid", "difficulty", "mode", "slot")}},
                "modes": {"solo": "혼자하기", "party": "함께하기"}}

    def history(self, a: dict) -> list:
        n = _int(a, "limit", 20, 1)
        rows = self.api.queue_history(n) or []
        return rows[:n]

    def log_lines(self, a: dict) -> list:
        n = _int(a, "n", 40, 1)
        lines = list(self.ring.lines) if self.ring else []
        if str(a.get("level", "")).upper() in ("WARNING", "WARN", "ERROR"):
            lines = [x for x in lines if x["level"] in ("WARNING", "ERROR", "CRITICAL")]
        return lines[-n:]

    # ---------------------------------------------------------------- 조작 (화면 버튼·F12 와 같은 함수)
    def pause(self, a: dict) -> dict:
        self.api.queue_halt()
        return self._queue()

    def resume(self, a: dict) -> dict:
        q = self.api.queue
        if q.running:
            raise Refused("이미 돌고 있습니다")
        if not q.can_resume():
            raise Refused("이어 할 일시정지 카드가 없습니다")
        q.resume_top()
        return self._queue()

    def skip(self, a: dict) -> dict:
        q = self.api.queue
        if not (q.current() or q.top_paused()):
            raise Refused("하는 중이거나 멈춘 카드가 없습니다")
        q.skip_current()
        self.api.cli.cancel()
        return self._queue()

    def stop_all(self, a: dict) -> dict:
        q = self.api.queue
        if not q.items:
            raise Refused("작업 큐가 비어 있습니다")
        q.clear()
        self.api.cli.cancel()
        return self._queue()

    def _slot(self, v) -> int:
        from mabi import profile as prof
        slots = [c["slot"] for c in prof.chars(self.api.paths)]
        n = _int({"slot": v}, "slot", None, 1)
        if n not in slots:
            raise BadArgs(f"슬롯 {n} 캐릭터가 없습니다 (있는 슬롯: {slots})")
        return n

    def _start(self, spec: dict, where: str = "end", replace_paused: bool = False) -> dict:
        """카드를 넣고, 큐가 쉬고 있으면 돌린다 (예전 명령 통로 --abyss 와 같음)."""
        it = self.api.queue_add(spec, where, replace_paused)
        if where != "now" and not self.api.queue.running:
            self.api.queue.tick()
        return _card(it)

    def daily(self, a: dict) -> dict:
        from mabi import profile as prof
        from mabi.tasks import TASKS
        raw = a.get("slots")
        if raw in (None, "", []):
            slots = [c["slot"] for c in prof.chars(self.api.paths)]
        else:
            slots = [self._slot(s) for s in (raw if isinstance(raw, list) else [raw])]
        only = None
        if a.get("only"):
            by_name = {v[0]: k for k, v in TASKS.items()}
            only = []
            for x in a["only"] if isinstance(a["only"], list) else [a["only"]]:
                k = x if x in TASKS else by_name.get(x)
                if not k:
                    raise BadArgs(f"없는 숙제: {x!r} (있는 것: {', '.join(v[0] for v in TASKS.values())})")
                only.append(k)
        return self._start({"kind": "daily", "label": "일일 숙제", "chars": slots, "only": only,
                            "force": bool(a.get("force"))}, replace_paused=True)

    def _repeat(self, kind: str, a: dict) -> dict:
        """어비스·레이드 반복 카드 (예전 --abyss/--raid 와 같은 모양)."""
        title, place = {"abyss": ("어비스", "dungeon"), "raid": ("레이드", "raid")}[kind]
        settings = self.api.daily_abyssSettings() if kind == "abyss" else self.api.daily_raidSettings()
        slot = self._slot(a.get("slot", settings.get("slot")))
        mode = a.get("mode") or None
        if mode not in (None, "solo", "party"):
            raise BadArgs("mode 는 solo 나 party 입니다")
        where = str(a.get(place) or "").strip()
        if kind == "abyss":
            from mabi import gamedata as gd
            table = gd.abysses(mode=mode or settings.get("mode") or "solo")
        else:
            table = settings["difficulties"]
        if where not in table:
            raise BadArgs(f"이번 주에 없는 {title}: {where!r} (있는 것: {', '.join(table)})")
        # 비우면 리모콘 설정의 난이도 (예전 통로와 같다). 그 던전에 없는 난이도면 지어내지 않고 고르라고 돌려보낸다
        difficulty = str(a.get("difficulty") or "").strip() or settings["difficulty"]
        if table[where] and difficulty not in table[where]:
            raise BadArgs(f"{where} 에 없는 난이도: {difficulty!r} (있는 것: {', '.join(table[where])})")
        name = next((c["name"] for c in settings["chars"] if c["slot"] == slot), "") if "chars" in settings else ""
        if not name:
            from mabi import profile as prof
            name = next((c["name"] for c in prof.chars(self.api.paths) if c["slot"] == slot), "")
        return self._start({"kind": kind, "label": f"{title} · {name or '지금 캐릭터'}", "slot": slot, place: where,
                            "difficulty": difficulty, "runs": _int(a, "runs", 0), "minutes": 0, "revive": True,
                            **({"mode": mode} if mode else {})})

    def abyss(self, a: dict) -> dict:
        return self._repeat("abyss", a)

    def raid(self, a: dict) -> dict:
        return self._repeat("raid", a)

    def collect_all(self, a: dict) -> dict:
        return _card(self.api.queue_add({"kind": "action", "act": "collectAll", "label": "가공 완료분 전체 수령",
                                         "detail": "완료된 시설 모두"}, "now"))

    def enhance(self, a: dict) -> dict:
        if self.api.queue.running:
            raise Refused("다른 작업이 도는 중이라 시작하지 않습니다")
        return _card(self.api.queue_add({"kind": "enhance", "label": "각인 강화 반복"}, "now"))

    def restart_game(self, a: dict) -> dict:
        return _card(self.api.queue_add({"kind": "restart", "label": "게임 다시 켜기", "why": "명령", "force": True}, "now"))

    def _find(self, a: dict) -> dict:
        n = _int(a, "id")
        it = self.api.queue.find(n)
        if not it:
            raise BadArgs(f"카드 {n} 이 없습니다")
        return it

    def play(self, a: dict) -> dict:
        it = self._find(a)
        self.api.queue_playOne(it["id"])
        return self._queue()

    def remove(self, a: dict) -> dict:
        it = self._find(a)
        self.api.queue_remove(it["id"])
        return self._queue()

    def answer(self, a: dict) -> dict:
        if "yes" not in a:
            raise BadArgs("'yes' 가 필요합니다 (true·false)")
        r = self.api.queue_answer(_int(a, "id"), bool(a["yes"]))
        if not r.get("ok"):
            raise Refused("그 카드가 기다리는 질문이 없습니다")
        return r

    def show(self, a: dict) -> dict:
        self.api._bring_front()
        return {}


# ---------------------------------------------------------------- 예전 통로(글자 한 줄) → 명령
def legacy(msg: bytes) -> tuple[str, dict] | None:
    """gui.py --halt 등이 첫 리모콘에 던지는 글자 → (명령, 인자). 모르는 글자면 None (창을 띄운다).
    예전 통로도 같은 명령을 부르게 해서 규칙이 두 군데 생기지 않게 한다."""
    simple = {b"resume": "resume", b"halt": "pause", b"enhance": "enhance", b"restart": "restart_game", b"show": "show"}
    if msg in simple:
        return simple[msg], {}
    text = msg.decode("utf-8", "replace")
    if text.startswith("daily:"):
        parts = text.split(":")[1:]
        slots = [int(x) for x in (parts[0] if parts else "").split(",") if x.strip().isdigit()]
        only = [x for x in (parts[1] if len(parts) > 1 else "").split(",") if x] or None
        return "daily", {"slots": slots or None, "only": only, "force": len(parts) > 2 and parts[2] == "force"}
    if text.startswith(("abyss:", "raid:")):
        kind, *parts = text.split(":")
        place = "dungeon" if kind == "abyss" else "raid"
        keys = ["slot", place, "runs", "difficulty", "mode"]
        return kind, {k: v for k, v in zip(keys, parts) if v != ""}
    return None


# ---------------------------------------------------------------- 알림 ('watch' 한 연결에)
class Events:
    """화면으로 가는 이벤트(api._emit) 중 밖에서 알 만한 것만 골라 알림으로 바꾼다.
    작업 큐 상태는 걸음마다 오므로, 카드 상태가 바뀔 때와 큐가 서고 설 때만 낸다."""

    def __init__(self, send: Callable[[str, object], None]):
        self.send = send
        self._status: dict = {}
        self._running: bool | None = None
        self._lock = threading.Lock()

    def on_emit(self, channel: str, payload) -> None:
        try:
            if channel == "mm:queue" and isinstance(payload, dict):
                self._queue(payload)
            elif channel == "mm:queue-report" and isinstance(payload, dict):
                cards = payload.get("cards") or []
                self.send("queue_done", {"cards": [{"label": c.get("label"), "status": c.get("status"),
                                                    "note": c.get("note")} for c in cards]})
            elif channel == "mm:queue-ask":
                self.send("ask", payload)
            elif channel == "mm:queue-toast" and isinstance(payload, dict):
                self.send("toast", payload)
        except Exception:  # noqa: BLE001 — 알림 하나 때문에 화면 알림이 끊기면 안 된다
            log.debug("제어 통로 알림 실패", exc_info=True)

    def _queue(self, snap: dict) -> None:
        items = [_card(x) for x in snap.get("items") or []]
        out = []
        with self._lock:
            now = {x["id"]: x["status"] for x in items}
            for x in items:
                before = self._status.get(x["id"])
                if before != x["status"] and (before is not None or x["status"] == "run"):
                    out.append(("card", {**x, "from": before}))
            running = bool(snap.get("running"))
            if self._running is not None and running != self._running:
                out.append(("queue", {"running": running}))
            self._status, self._running = now, running
        for name, data in out:
            self.send(name, data)


class ControlServer:
    """파이프를 열고 요청을 받아 Commands 로 돌린다. Qt 를 쓰는 것은 여기뿐 (화면 스레드에서 만든다).
    명령은 작업 스레드에서 돌린다 — 화면 스레드를 막지 않게. 답은 시그널로 화면 스레드에 넘겨 쓴다."""

    def __init__(self, commands: Commands):
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtNetwork import QLocalServer

        class _Bridge(QObject):
            out = Signal(int, bytes)
        self.commands = commands
        self.bridge = _Bridge()
        self.bridge.out.connect(self._write)
        self.conns: dict = {}
        self.watchers: set[int] = set()
        self._seq = 0
        self.events = Events(self._broadcast)
        QLocalServer.removeServer(PIPE)
        self.server = QLocalServer()
        # 같은 사용자의 일반 권한 프로그램도 붙게 (리모콘은 관리자 권한으로 뜬다 — 기본 권한이면 관리자만 붙는다)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(PIPE):
            log.warning(f"제어 통로를 열지 못함: {self.server.errorString()}")
        self.server.newConnection.connect(self._accept)

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            self._seq += 1
            cid = self._seq
            self.conns[cid] = {"sock": conn, "buf": b""}
            conn.readyRead.connect(lambda c=cid: self._read(c))
            conn.disconnected.connect(lambda c=cid: self._drop(c))

    def _drop(self, cid: int) -> None:
        c = self.conns.pop(cid, None)
        self.watchers.discard(cid)
        if c:
            c["sock"].deleteLater()

    def _read(self, cid: int) -> None:
        c = self.conns.get(cid)
        if not c:
            return
        c["buf"] += bytes(c["sock"].readAll())
        if len(c["buf"]) > 1_000_000:  # 줄바꿈 없이 계속 오면 버린다
            c["buf"] = b""
            return
        *lines, c["buf"] = c["buf"].split(b"\n")
        for line in lines:
            if line.strip():
                threading.Thread(target=self._handle, args=(cid, line), name="control", daemon=True).start()

    def _handle(self, cid: int, line: bytes) -> None:
        rid = None
        try:
            req = json.loads(line.decode("utf-8"))
            if not isinstance(req, dict):
                raise ValueError("JSON 객체가 아닙니다")
            rid = req.get("id")
            res = self.commands.run(req.get("cmd"), req.get("args"))
            if req.get("cmd") == "watch" and res.get("ok"):
                self.watchers.add(cid)
        except ValueError as e:
            res = {"ok": False, "error": "bad_request", "message": str(e)}
        self.bridge.out.emit(cid, self._line({"id": rid, **res}))

    @staticmethod
    def _line(obj: dict) -> bytes:
        return (json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")

    def _broadcast(self, name: str, data) -> None:
        if not self.watchers:
            return
        line = self._line({"event": name, "data": data, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        for cid in list(self.watchers):
            self.bridge.out.emit(cid, line)

    def _write(self, cid: int, data: bytes) -> None:
        c = self.conns.get(cid)
        if c:
            c["sock"].write(data)
            c["sock"].flush()

    def close(self) -> None:
        for cid in list(self.conns):
            self._drop(cid)
        self.server.close()
