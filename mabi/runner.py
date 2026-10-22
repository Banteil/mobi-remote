"""일일 숙제 실행부. 콘솔(run.py)과 GUI 가 같이 쓴다.

Runner.run() 은 캐릭터마다 접속 → 숙제 순서대로 실행하고, 진행 상황을 on_event 콜백으로 알린다.
이벤트는 dict 하나이고 type 으로 구분한다 (GUI 는 이것만 보고 화면을 그린다):
  start      {"characters": [{"slot", "name"}], "order": [tid], "labels": {tid: 이름}}
  character  {"slot", "name"}
  task_start {"slot", "task", "label"}
  task_end   {"slot", "task", "label", "status", "summary", "seconds"}
  done       {"results": [(label, status, summary)], "report": 리포트 파일 경로}
status: OK / CHECK(했지만 확인 결과 남음) / MANUAL(할 수 있는 건 다 함, 남은 건 사람이 — 다시 시작해도 넘김) / FAIL / ERROR / SKIP / HEAVY(가방 무게) / STOP / DONE(오늘 이미 완료)
"""
import ctypes
import logging
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import profile as prof
from . import tasks
from .bot import AuthBlocked, Bot, MissingTemplate, Overweight, StepTimeout, StopRequested
from .paths import Paths
from .report import RunReport
from .tasks import login
from .tasks.content import CannotProceed

log = logging.getLogger("mabi")


def setup_logging(paths: Paths, console: bool = True) -> logging.Logger:
    """mabi 로거에 날짜별 파일(DEBUG)과 콘솔(INFO)을 붙인다. 여러 번 불러도 중복으로 붙지 않는다."""
    paths.logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    log.setLevel(logging.DEBUG)
    for h in [h for h in log.handlers if getattr(h, "_mabi_base", False)]:
        log.removeHandler(h)
    file = logging.FileHandler(paths.logs / f"{datetime.now():%Y%m%d}.log", encoding="utf-8")
    file.setFormatter(fmt)
    file._mabi_base = True
    log.addHandler(file)
    if console and sys.stdout:
        con = logging.StreamHandler(sys.stdout)
        con.setLevel(logging.INFO)
        con.setFormatter(fmt)
        con._mabi_base = True
        log.addHandler(con)
    return log


def load_config(paths: Paths) -> dict:
    return tomllib.loads(paths.config.read_text(encoding="utf-8"))


@dataclass
class RunOptions:
    chars: list[int] | None = None      # None = profile 의 전원
    only: list[str] | None = None       # 일부 숙제만
    current: bool = False               # 캐릭터 전환 없이 지금 캐릭터로
    force: bool = False                 # 오늘 끝낸 숙제도 다시
    dry_run: bool = False
    extra: dict = field(default_factory=dict)  # 리포트에 남길 실행 정보


def overweight(bot: Bot, cfg: dict) -> str | None:
    """가방 무게가 한도 이상이면 이유 문자열 (보상·채집을 못 받아 숙제가 막힌다)."""
    inv = bot.state.query("get_inventory") if bot.state.available() else None
    if not inv:
        return None
    cur, mx = inv.get("CurrentInventoryWeight", 0), inv.get("MaxInventoryWeight", 0)
    if mx and cur >= mx * cfg["run"].get("max_weight_ratio", 1.0):
        return f"가방 무게 {cur:.0f}/{mx:.0f}"
    return None


def _done_view(stored) -> dict:
    """오늘 끝난 숙제를 화면에 보일 상태. '남음(직접)' 은 그대로 보여 준다 (다시 하지는 않는다)."""
    if isinstance(stored, str) and stored.startswith("MANUAL"):
        return {"status": "MANUAL", "summary": stored.split(":", 1)[-1].strip()}
    return {"status": "DONE", "summary": "오늘 이미 완료"}


class Runner:
    def __init__(self, paths: Paths, on_event: Callable[[dict], None] | None = None, force_exit: bool = True):
        self.paths = paths
        self.on_event = on_event or (lambda e: None)
        self.force_exit = force_exit
        self.bot: Bot | None = None
        self._stop_requested = False

    def stop(self) -> None:
        """GUI 의 중단 버튼. 봇은 다음 대기/캡처 시점에 멈춘다."""
        self._stop_requested = True
        if self.bot:
            self.bot.stopper.request()

    def _emit(self, type_: str, **kw) -> None:
        try:
            self.on_event({"type": type_, **kw})
        except Exception:  # 화면 쪽 오류가 숙제를 멈추지 않도록
            log.exception("이벤트 처리 실패")

    def characters(self, cfg: dict, opts: RunOptions) -> list[dict | None]:
        if opts.current:
            return [None]
        profile = prof.load_profile(self.paths.profile)
        if profile is None:
            raise ValueError("숙제할 캐릭터(슬롯)가 설정되지 않았습니다")
        chars = prof.characters(profile)
        if opts.chars:
            chars = [ch for ch in chars if ch["slot"] in set(opts.chars)]
        return chars

    def run(self, opts: RunOptions) -> list[tuple[str, str, str]]:
        paths = self.paths
        cfg = load_config(paths)
        registry = tasks.build(cfg)
        by_slot = {int(k): v for k, v in cfg["run"].get("tasks_by_slot", {}).items()}
        referenced = (opts.only or []) + cfg["run"]["order"] + [t for v in by_slot.values() for t in v]
        unknown = sorted({t for t in referenced if t not in registry})
        if unknown:
            raise ValueError(f"알 수 없는 숙제: {unknown}")
        characters = self.characters(cfg, opts)
        state = prof.DailyState(paths.state)

        if not ctypes.windll.shell32.IsUserAnAdmin():
            log.warning("관리자 권한이 아닙니다. 게임이 관리자 권한으로 실행 중이면 입력이 무시됩니다.")

        bot = self.bot = Bot(cfg, paths, dry_run=opts.dry_run, force_exit=self.force_exit)
        if self._stop_requested:
            bot.stopper.request()
        bot.daily = state
        results: list[tuple[str, str, str]] = []
        report = None
        try:
            bot.window.require()
            r = bot.window.client_rect()
            if (r.width, r.height) != (1920, 1080):  # 화면은 시작 전에 묻고 맞춘다. 콘솔 실행 등을 위한 마지막 방어
                raise ValueError(f"게임 화면이 {r.width}x{r.height} 입니다. 1920x1080 으로 맞춘 뒤 시작하세요")
            bot.window.focus()
            bot.sleep(1)
            report = RunReport(paths.runs, cfg, bot, {**opts.extra, "chars": opts.chars, "only": opts.only,
                                                      "force": opts.force, "current": opts.current})
            self._emit("start", characters=[{"slot": c["slot"], "name": c["name"]} if c else
                                            {"slot": None, "name": "현재 캐릭터"} for c in characters],
                       order=opts.only or cfg["run"]["order"], labels={t: l for t, (l, _) in registry.items()})
            log.info(f"시작: 캐릭터 {len(characters)}명, 게임 날짜 {state.date}  (일시정지: {cfg['game']['stop_key'].upper()})")
            characters = self._arrange(cfg, opts, by_slot, characters, state)
            self._loop(cfg, opts, registry, by_slot, characters, state, bot, report, results)
            if not any(s == "STOP" for _, s, _ in results):
                state.clear_progress()  # 끝까지 돌았다. 중단·충돌이면 남겨 두고 다음에 거기서부터
        except StopRequested:
            results.append(("실행", "STOP", "사용자 중단"))
        finally:
            if report:
                report.finish(results)
            log.info("==== 결과 ====")
            for label, status, summary in results:
                log.info(f"{status:5} {label}: {summary}")
            self._emit("done", results=results, report=str(report.path) if report else None)
            bot.stopper.close()
        return results

    @staticmethod
    def _order(cfg, opts, by_slot, ch) -> list[str]:
        """이 캐릭터가 할 숙제 순서 (캐릭터 탭에서 끈 숙제는 뺀다)."""
        slot = ch["slot"] if ch else None
        order = opts.only or (by_slot.get(slot) if ch else None) or cfg["run"]["order"]
        if ch:  # 캐릭터 탭에서 끈 숙제 (검은 구멍 등)
            off = cfg["run"].get("skip_by_slot", {}).get(str(slot), [])
            order = [t for t in order if t not in off]
            # 아르바이트는 거꾸로 켠 캐릭터만 (새 기능이라 기본은 안 함)
            if slot not in [int(s) for s in cfg.get("arbeit", {}).get("slots", [])]:
                order = [t for t in order if t != "arbeit"]
        return order

    def _arrange(self, cfg, opts, by_slot, characters, state) -> list:
        """다시 시작할 때의 캐릭터 순서.
        - 지난번에 멈춘 캐릭터(진행 기록)부터 이어 한다 — 앞 캐릭터로 돌아가 접속 전환을 낭비하지 않게.
        - 해 보고 실패한 숙제만 남은 캐릭터는 맨 뒤로 (공물 퀘스트처럼 접속 직후엔 안 되는 것도 그사이 풀린다)."""
        if opts.force or opts.current or len(characters) < 2:
            return characters
        chars = list(characters)

        def fresh(ch) -> bool:  # 아직 안 해 본 숙제가 있다
            return any(not state.is_done(ch["slot"], t) and not state.failed(ch["slot"], t)
                       for t in self._order(cfg, opts, by_slot, ch))

        def retry(ch) -> bool:
            return not fresh(ch) and any(state.failed(ch["slot"], t) for t in self._order(cfg, opts, by_slot, ch))

        def todo(ch) -> bool:
            return any(not state.is_done(ch["slot"], t) for t in self._order(cfg, opts, by_slot, ch))

        later = [ch for ch in chars if retry(ch)]
        if later:
            log.info(f"실패한 숙제만 남은 캐릭터는 맨 뒤로: {', '.join(ch['name'] for ch in later)}")
        chars = [ch for ch in chars if ch not in later] + later

        # 맨 앞에 둘 캐릭터: ① 지난번에 숙제 도중 끊긴 캐릭터 ② 아니면 지금 접속해 있는 캐릭터 (할 게 남았으면)
        # — 접속 전환을 아끼고 하던 걸 그 자리에서 잇는다. 접속(login) 도중 끊긴 건 아무것도 안 한 것이라 치지 않는다
        prog = state.progress()
        first, why = None, ""
        if prog and prog.get("task") != "login":
            first = next((ch for ch in chars if ch["slot"] == prog["slot"] and todo(ch)), None)
            why = (f"지난 실행이 {prog['at']} '{prog['task']}'"
                   f"{' · ' + prog['stage'] if prog.get('stage') else ''} 에서 멈춤")
        if first is None:
            from .tasks.login import current_name
            try:
                now = current_name(self.bot)
            except Exception:
                now = ""
            first = next((ch for ch in chars if now and "".join(ch["name"].split()) == now and todo(ch)), None)
            why = "지금 접속 중인 캐릭터"
        if first and chars[0] is not first:
            chars = [first, *[ch for ch in chars if ch is not first]]
        if first:
            log.info(f"이어 하기: [{first['name']}] 부터 ({why})")
        return chars

    def _loop(self, cfg, opts, registry, by_slot, characters, state, bot, report, results) -> None:
        def recover(tid: str) -> None:
            """실패한 숙제 뒤 메인 화면으로. 접속 실패는 게임 밖 화면이라 건드리지 않는다."""
            if tid == "login":
                return
            try:
                bot.to_main()
            except (StepTimeout, MissingTemplate):
                pass

        def step(slot, tid: str, label: str, fn) -> str:
            """숙제 하나 실행. 상태 문자열 반환."""
            log.info(f"▶ {label}")
            bot.task_id, bot.resume = tid, None
            if slot is not None:
                last = state.last_step(slot, tid)
                # 끝까지 간 기록('end')이 아니면 그 단계에서 끊긴 것 → 숙제가 거기서부터 이어 한다
                if last and last.get("step") not in (None, "end"):
                    bot.resume = last
                    log.info(f"  지난번에 {last.get('at', '')} [{last['step']}] {last.get('text', '')} 에서 끊김"
                             " → 거기서부터 이어 함")
                state.set_progress(slot, tid)
            report.task_start(tid)
            self._emit("task_start", slot=slot, task=tid, label=label)
            t0 = time.monotonic()
            try:
                summary = fn()
                status = "OK"
                check = tasks.VERIFY.get(tid)
                if check and tid not in bot.also_done:
                    try:
                        if not check(bot, cfg):
                            if tid in tasks.MANUAL_LEFT:  # 할 수 있는 건 다 함. 남은 건 사람이 직접 (다시 시작해도 넘김)
                                status, summary = "MANUAL", f"{summary} — 남은 건 직접 처리"
                            else:
                                status, summary = "CHECK", f"{summary} — 확인 결과 아직 남음"
                    except (StepTimeout, CannotProceed, MissingTemplate) as e:
                        log.warning(f"{label} 완료 확인 실패: {e}")
            except StopRequested:
                log.warning("사용자 중단")
                status, summary = "STOP", ""
            except AuthBlocked as e:  # 접속을 더 두드리면 꼬일 수 있다 → 전체를 멈추고 사람에게 넘긴다
                log.error(str(e))
                status, summary = "STOP", str(e)
            except Overweight as e:  # 가방 정리가 필요 → 이 캐릭터의 남은 숙제는 건너뛴다
                log.warning(f"{label}: {e} → 이 캐릭터는 건너뜀")
                status, summary = "HEAVY", str(e)
            except MissingTemplate as e:
                status, summary = "SKIP", str(e)
            except CannotProceed as e:  # 미해금 등: 실패로 기록하고 다음 숙제로
                status, summary = "FAIL", str(e)
                recover(tid)
            except StepTimeout as e:
                status, summary = "FAIL", f"{e} → {bot.snapshot(tid).name}"
                recover(tid)
            except Exception as e:  # 한 숙제의 실패가 전체를 멈추지 않도록
                log.exception(label)
                status, summary = "ERROR", f"{type(e).__name__}: {e} → {bot.snapshot(tid).name}"
            secs = round(time.monotonic() - t0)
            log.info(f"  {status} {summary} ({secs}s)")
            # 중단·실패(튕김 등)는 그 단계에서 이어 해야 하므로 단계 기록을 남겨 둔다
            if slot is not None and status not in ("STOP", "FAIL", "ERROR"):
                state.set_step(slot, tid, "end", f"끝: {status}")
            results.append((label, status, summary))
            report.task_end(status, summary)
            self._emit("task_end", slot=slot, task=tid, label=label, status=status, summary=summary, seconds=secs)
            return status

        # 지난번에 끊긴 자리 — 그 캐릭터는 그 숙제부터 한다 (앞 숙제 중 실패해서 다시 할 게 있어도 끊긴 일이 먼저)
        cut = state.progress()
        first = True
        for ch in characters:
            who = ch["name"] if ch else "현재 캐릭터"
            slot = ch["slot"] if ch else None
            order = self._order(cfg, opts, by_slot, ch)
            if ch and not opts.force:
                todo = [t for t in order if not state.is_done(slot, t)]
                if not todo:
                    log.info(f"[{who}] 오늘 숙제 완료 기록이 있어 건너뜀")
                    results.append((f"[{who}]", "DONE", "오늘 이미 완료"))
                    for t in order:
                        self._emit("task_end", slot=slot, task=t, label=t, **_done_view(state.get(slot, t)), seconds=0)
                    continue
                for t in order:
                    if t not in todo:
                        self._emit("task_end", slot=slot, task=t, label=t, **_done_view(state.get(slot, t)), seconds=0)
                order = todo
            if ch and cut and cut.get("slot") == slot and cut.get("task") in order and order[0] != cut["task"]:
                order = [cut["task"], *[t for t in order if t != cut["task"]]]
                log.info(f"[{who}] 끊긴 숙제 '{registry[cut['task']][0]}' 부터")
            bot.character = ch
            report.character(ch)
            self._emit("character", slot=slot, name=who)
            bot.weight_limit = 0.0  # 접속 중에는 이전 캐릭터의 가방 무게를 보지 않는다
            # 지금 접속한 캐릭터를 알아보는 기능(지문)은 자주 틀려서 뺐다 (2026-10-22) → 늘 다시 고른다.
            # 던전 안·클리어 화면에서 멈췄던 경우는 login.run 이 먼저 정리한다
            status = step(slot, "login", f"[{who}] 접속", lambda: login.run(bot, cfg, ch))
            if status == "STOP":
                return
            if status != "OK":
                continue  # 접속 실패 시 이 캐릭터의 숙제는 건너뛴다
            bot.also_done = {t for t in registry if ch and not opts.force and state.is_done(slot, t)}
            heavy = overweight(bot, cfg)
            if heavy:
                log.warning(f"[{who}] {heavy} → 이 캐릭터는 건너뜀")
                results.append((f"[{who}]", "HEAVY", heavy))
                for t in order:
                    self._emit("task_end", slot=slot, task=t, label=t, status="HEAVY", summary=heavy, seconds=0)
                continue
            bot.weight_limit = cfg["run"].get("max_weight_ratio", 1.0)  # 숙제 중에만 가방 무게 감시
            for tid in order:
                label, fn = registry[tid]
                if tid in bot.also_done:  # 다른 숙제 안에서 이미 끝냄 (사냥터 안 검은 구멍 등)
                    log.info(f"▷ [{who}] {label}: 이미 완료")
                    self._emit("task_end", slot=slot, task=tid, label=label, status="DONE", summary="이미 완료", seconds=0)
                    continue
                status = step(slot, tid, f"[{who}] {label}", lambda fn=fn: fn(bot, cfg))
                if ch:
                    state.set(slot, tid, "done" if status == "OK" else f"{status}: {results[-1][2]}")
                    for t in bot.also_done:
                        state.set(slot, t, "done")
                if status == "STOP":
                    return
                if status == "HEAVY":
                    break
