"""일일 숙제 실행부. 콘솔(run.py)과 GUI 가 같이 쓴다.

Runner.run() 은 캐릭터마다 접속 → 숙제 순서대로 실행하고, 진행 상황을 on_event 콜백으로 알린다.
이벤트는 dict 하나이고 type 으로 구분한다 (GUI 는 이것만 보고 화면을 그린다):
  start      {"characters": [{"slot", "name"}], "order": [tid], "labels": {tid: 이름}}
  character  {"slot", "name"}
  task_start {"slot", "task", "label"}
  task_end   {"slot", "task", "label", "status", "summary", "seconds"}
  done       {"results": [(label, status, summary)], "report": 리포트 파일 경로}
status: OK / CHECK(했지만 확인 결과 남음) / MANUAL(할 수 있는 건 다 함, 남은 건 사람이 — 다시 시작해도 넘김) / FAIL / ERROR / SKIP / HEAVY(가방 무게) / STOP / DONE(오늘 완료)
"""
import ctypes
import logging
import re
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from . import profile as prof
from . import queue_report, tasks
from .bot import AuthBlocked, Bot, MissingTemplate, Overweight, StepTimeout, StopRequested
from .paths import Paths
from .report import RunReport
from .tasks import display, login
from .tasks.content import CannotProceed, leave_dungeon

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


def _merged(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merged(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config(paths: Paths) -> dict:
    """사용자 설정(config.toml — 기본값과 다른 값만, mabi.userconfig) 아래에 배포 기본값(config.default.toml)을 깐다.
    옛 판처럼 통째로 복사해 둔 config.toml 이면 처음 한 번 '다른 값만' 으로 옮긴다."""
    from . import userconfig
    try:
        userconfig.migrate(paths, log)
    except Exception as e:  # noqa: BLE001 — 옮기지 못해도 읽기는 된다
        log.warning(f"설정 파일을 옮기지 못함 — 그대로 씀: {e}")
    user = tomllib.loads(paths.config.read_text(encoding="utf-8"))
    default = paths.resources / "config.default.toml"
    if not default.exists():
        return user
    return _merged(tomllib.loads(default.read_text(encoding="utf-8")), user)


@dataclass
class RunOptions:
    chars: list[int] | None = None      # None = profile 의 전원
    only: list[str] | None = None       # 일부 숙제만
    current: bool = False               # 캐릭터 전환 없이 지금 캐릭터로
    force: bool = False                 # 오늘 끝낸 숙제도 다시
    dry_run: bool = False
    # 인터페이스 PC·80% 맞추기. 작업 큐는 한 번 도는 동안 처음 한 번만 맞추고(interface_ready = 이미 맞춤),
    # 되돌리기는 큐가 다 끝났을 때 한 번 한다 (restore=False — daily_api.daily_displayRestore)
    display: bool = True
    interface_ready: bool = False
    restore: bool = True
    extra: dict = field(default_factory=dict)  # 리포트에 남길 실행 정보


def box(bot: Bot, tag: str) -> None:
    """실패한 숙제의 직전 30초(화면·누른 것·패킷)를 남긴다 — 남기다 터져도 실패 처리는 이어 간다."""
    try:
        name = bot.dump_box(tag)
    except Exception as e:  # noqa: BLE001
        log.debug(f"블랙박스를 남기지 못함: {e}")
        return
    if name:
        log.info(f"블랙박스: {name}")


def overweight(bot: Bot, cfg: dict) -> str | None:
    """가방이 꽉 찼으면 이유 문자열 (자동 이동·전투가 멈추고 보상·채집을 못 받아 숙제가 막힌다)."""
    inv = bot.state.query("get_inventory") if bot.state.available() else None
    if not inv:
        return None
    cur, mx = inv.get("CurrentInventoryWeight", 0), inv.get("MaxInventoryWeight", 0)
    if mx and cur >= mx:
        return f"가방 무게 {cur:.0f}/{mx:.0f}"
    return None


def _done_view(stored) -> dict:
    """오늘 끝난 숙제를 화면에 보일 상태. '남음(직접)' 은 그대로 보여 준다 (다시 하지는 않는다)."""
    if isinstance(stored, str) and stored.startswith("MANUAL"):
        return {"status": "MANUAL", "summary": stored.split(":", 1)[-1].strip()}
    return {"status": "DONE", "summary": "오늘 완료"}


class FailStreak:
    """다른 캐릭터에서 같은 숙제가 같은 이유로 연달아 실패했나. 그러면 원인이 캐릭터가 아니라 리모콘·게임 쪽이라
    나머지 캐릭터도 같은 자리에서 실패한다 (2026-10-30: 6명 모두 접속 단계에서 3분씩 같은 실패) → 멈추고 사람에게."""

    def __init__(self):
        self.last: dict[str, tuple[str, int | None]] = {}  # 숙제 → (실패 이유, 캐릭터 슬롯)

    def __call__(self, slot, tid: str, status: str, summary: str) -> bool:
        if status not in ("FAIL", "ERROR"):
            self.last.pop(tid, None)
            return False
        why = re.sub(r"\d+", "#", summary.split("→")[0]).strip()  # 스크린샷 이름·숫자는 빼고 비교
        prev = self.last.get(tid)
        self.last[tid] = (why, slot)
        return bool(prev and prev[0] == why and prev[1] != slot)


class Runner:
    _interface_ready = False  # 이번 실행에서 인터페이스를 PC·80% 로 맞췄나 (한 번)

    def __init__(self, paths: Paths, on_event: Callable[[dict], None] | None = None, force_exit: bool = True):
        self.paths = paths
        self.on_event = on_event or (lambda e: None)
        self.force_exit = force_exit
        self.bot: Bot | None = None
        self._stop_requested = False
        # 캐릭터마다 얻은 것 (작업 큐 결과 창) — 숙제를 시작할 때와 그 캐릭터를 끝낼 때 가방·재화를 찍어 뺀다
        self._loot = queue_report.LootMeter(lambda x: self._emit("loot", **x))

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
        bot.auto_clear = True  # 기다리는 화면이 오래 안 나오면 대화·퀘스트 클리어 창 등을 넘겨 본다
        if self._stop_requested:
            bot.stopper.request()
        bot.daily = state
        bot.on_step = lambda s, t: self._emit("step", slot=(bot.character or {}).get("slot"), task=bot.task_id, step=s, text=t or s)
        if cfg["game"].get("pause_on_touch", True) and not opts.dry_run:
            bot.stopper.watch_manual(lambda: bot.window.hwnd)
        results: list[tuple[str, str, str]] = []
        report = None
        try:
            if not bot.window.find():
                raise ValueError("게임이 꺼져 있습니다. 게임을 켠 뒤 시작하세요")
            # 다 끝난 날엔 게임을 건드리지 않는다 — 앞으로 가져오지도, 화면 설정을 따지지도 않고 '오늘 완료' 만 알린다
            if self._has_work(cfg, opts, by_slot, characters, state):
                # 앞으로 가져온 뒤에 크기를 본다 — '전체화면' 이면 내려가 있는 동안 크기 0·레지스트리 창모드다 (2026-10-23)
                bot.window.focus()
                bot.sleep(2)
                r = bot.window.client_rect()
                from .screen import exclusive_fullscreen
                from .tasks.display import size_problem
                # 화면은 시작 전에 묻고 맞춘다. 콘솔 실행 등을 위한 마지막 방어
                if (bad := size_problem(r.width, r.height)):
                    raise ValueError(bad)
                if exclusive_fullscreen():  # 화면이 멈춰 보여 아무것도 알아보지 못한다
                    raise ValueError("화면 모드가 '전체화면' 이면 화면을 볼 수 없습니다 — '테두리 없는 전체화면' 으로 바꾼 뒤 시작하세요")
            report = RunReport(paths.runs, cfg, bot, {**opts.extra, "chars": opts.chars, "only": opts.only,
                                                      "force": opts.force, "current": opts.current})
            self._emit("start", characters=[{"slot": c["slot"], "name": c["name"]} if c else
                                            {"slot": None, "name": "현재 캐릭터"} for c in characters],
                       order=opts.only or cfg["run"]["order"], labels={t: l for t, (l, _) in registry.items()})
            log.info(f"시작: 캐릭터 {len(characters)}명, 게임 날짜 {state.date}  (일시정지: {cfg['game']['stop_key'].upper()})")
            bot.check_in()
            characters = self._arrange(cfg, opts, by_slot, characters, state)
            self._interface_ready = False
            try:
                self._loop(cfg, opts, registry, by_slot, characters, state, bot, report, results)
            finally:
                self._loot.close(bot)  # 마지막 캐릭터 (중단으로 끝나도)
            if not any(s == "STOP" for _, s, _ in results):
                state.clear_progress()  # 끝까지 돌았다. 중단·충돌이면 남겨 두고 다음에 거기서부터
                # 모든 캐릭터가 끝났다 → 시작할 때 기억해 둔 인터페이스 설정으로 되돌린다 (일시정지면 이어 할 때까지 둔다)
                if opts.restore and state.data.get(display.RESTORE_KEY) and not opts.dry_run:
                    try:
                        msg = display.restore_interface(bot, state)
                        if msg:
                            log.info(msg)
                    except (display.DisplayFixFailed, StepTimeout, MissingTemplate, RuntimeError) as e:
                        log.warning(f"인터페이스 설정을 되돌리지 못함 — 다음 숙제가 끝날 때 다시 시도: {e}")
                # 화면 모드·해상도도 숙제 시작 전 맞추기에서 기억해 둔 값으로. 인터페이스 다음에 한다
                # ('전체화면' 으로 되돌리면 그 뒤로는 화면을 볼 수 없다)
                if opts.restore and (paths.data / display.RESTORE_FILE).is_file() and not opts.dry_run:
                    try:
                        msg = display.restore_screen(bot, paths.data / display.RESTORE_FILE)
                        if msg:
                            log.info(msg)
                    except (display.DisplayFixFailed, StepTimeout, MissingTemplate, RuntimeError) as e:
                        log.warning(f"화면 설정을 되돌리지 못함 — 다음 숙제가 끝날 때 다시 시도: {e}")
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

    @classmethod
    def _has_work(cls, cfg, opts, by_slot, characters, state) -> bool:
        """오늘 할 숙제가 남은 캐릭터가 있나. 강제·현재 캐릭터면 늘 있다."""
        if opts.force or opts.current:
            return True
        return any(not state.is_done(ch["slot"], t) for ch in characters for t in cls._order(cfg, opts, by_slot, ch))

    def has_work(self, opts: RunOptions) -> bool:
        """숙제 시작 전 화면 확인이 쓴다 — 다 끝난 날엔 화면 설정을 보지도 맞추지도 않는다."""
        cfg = load_config(self.paths)
        by_slot = {int(k): v for k, v in cfg["run"].get("tasks_by_slot", {}).items()}
        return self._has_work(cfg, opts, by_slot, self.characters(cfg, opts), prof.DailyState(self.paths.state))

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

    def _prepare_interface(self, bot, state, opts, after_login: bool = False) -> bool:
        """이번 실행에서 처음이면 지금 인터페이스 설정을 기억하고 PC·80% 로 맞춘다 (템플릿·좌표가 모두 이 기준).
        끝나면 되돌린다. 게임 안(CLI 로 확인)이거나 방금 접속했을 때만 — 환경 설정은 게임 안에서만 열린다. 맞췄으면 True."""
        if self._interface_ready or opts.dry_run or not opts.display or opts.interface_ready:
            return False
        if not after_login and not bot.in_game():
            return False
        if not after_login and (why := display.busy(bot)):
            log.info(f"{why} → 인터페이스 맞추기는 접속 단계가 정리한 뒤로")
            return False
        self._interface_ready = True
        try:
            log.info(display.prepare_interface(bot, state))
        except (display.DisplayFixFailed, StepTimeout, MissingTemplate) as e:
            log.warning(f"인터페이스 PC·80% 로 맞추지 못함 — 그대로 진행: {e}")
        return True

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

        if not any(todo(ch) for ch in chars):  # 다 끝났다 — 지금 캐릭터 이름을 읽으러 화면을 볼 것도 없다
            return chars
        later =[ch for ch in chars if retry(ch)]
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
            from .tasks.login import current_name, snap_name
            try:
                now = snap_name(current_name(self.bot), [ch["name"] for ch in chars])
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
                leave_dungeon(bot)  # 던전 안에서 실패했으면 다음 숙제를 밖에서 시작하게
            except (StepTimeout, MissingTemplate, RuntimeError):
                pass
            except Exception:  # noqa: BLE001
                log.exception("실패 뒤 던전에서 나가기 실패")
            try:
                bot.to_main()
            except (StepTimeout, MissingTemplate, RuntimeError):  # RuntimeError: 게임 창이 없음 (꺼짐)
                pass
            except Exception:  # noqa: BLE001 — 정리 실패로 다음 숙제까지 막지 않는다 (다음 숙제가 시작 점검을 한다)
                log.exception("실패 뒤 메인 화면으로 돌아가기 실패")

        repeated = FailStreak()

        def step(slot, tid: str, label: str, fn) -> str:
            """숙제 하나 실행. 상태 문자열 반환."""
            log.info(f"▶ {label}")
            bot.task_id, bot.resume, bot.verified = tid, None, False
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
                bot.check_in()  # 숙제마다 지금 상태부터 — 앞 숙제·캐릭터에서 남은 패킷 상태를 믿고 시작하지 않는다
                bot.deadline = time.monotonic() + float(cfg["run"].get("task_timeout_min", 45)) * 60
                try:
                    summary = fn()
                finally:
                    bot.deadline = None
                status = "OK"
                check = tasks.VERIFY.get(tid)
                if check and tid not in bot.also_done and not bot.verified:
                    try:
                        if not check(bot, cfg):
                            if tid in tasks.MANUAL_LEFT:  # 할 수 있는 건 다 함. 남은 건 사람이 직접 (다시 시작해도 넘김)
                                status, summary = "MANUAL", f"{summary} — 남은 건 직접 처리"
                            else:
                                status, summary = "CHECK", f"{summary} — 확인 결과 아직 남음"
                    except (StepTimeout, CannotProceed, MissingTemplate) as e:
                        # 확인을 못 했으면 끝났다고 하지 않는다 (예전엔 OK·오늘 완료로 남았다)
                        log.warning(f"{label} 완료 확인 실패: {e}")
                        status, summary = "CHECK", f"{summary} — 완료 확인 실패: {e}"
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
                box(bot, tid)
                recover(tid)
            except Exception as e:  # 한 숙제의 실패가 전체를 멈추지 않도록
                log.exception(label)
                status, summary = "ERROR", f"{type(e).__name__}: {e} → {bot.snapshot(tid).name}"
                box(bot, tid)
                recover(tid)  # 알 수 없는 오류 뒤에도 다음 숙제가 낯선 화면에서 시작하지 않게
            # 도중에 게임이 꺼지면 (튕김·사람이 끔) 남은 캐릭터마다 접속을 두드리며 실패를 쌓지 않는다 → 일시정지.
            # 단계 기록은 남아 있어 게임을 켜고 다시 시작(F12)하면 이 자리부터 이어 한다
            if status in ("FAIL", "ERROR") and not bot.window.find():
                log.error("게임이 꺼짐 → 일시정지 (게임을 켠 뒤 다시 시작하면 이어 함)")
                status, summary = "STOP", "게임이 꺼짐 — 게임을 켠 뒤 다시 시작하면 이어 합니다"
            # 게임을 오래 켜 두면 '재시작해 주세요' 창(AI 에이전트 연속 실행 제한)이 떠 CLI·조작이 막힌다 →
            # 남은 숙제를 실패로 쌓지 않고 일시정지. 창은 '종료' 뿐이라 누르지 않는다
            elif status in ("FAIL", "ERROR") and bot.run_limited():
                log.error("게임 연속 실행 제한 창 → 일시정지 (게임을 다시 켠 뒤 이어 하기)")
                status, summary = "STOP", "게임을 너무 오래 켜 둠 — 게임을 다시 켠 뒤 이어 하기를 누르면 이어 합니다"
            elif repeated(slot, tid, status, summary):
                log.error(f"{label}: 앞 캐릭터와 같은 이유로 또 실패 → 일시정지 (원인을 확인한 뒤 이어 하기)")
                status, summary = "STOP", f"두 캐릭터 연달아 같은 실패 — 확인 필요: {summary}"
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
                    results.append((f"[{who}]", "DONE", "오늘 완료"))
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
            self._loot.close(bot)  # 앞 캐릭터가 얻은 것 (다른 캐릭터로 바꾸기 전에)
            bot.character = ch
            report.character(ch)
            self._emit("character", slot=slot, name=who)
            bot.watch_weight = False  # 접속 중에는 이전 캐릭터의 가방 무게를 보지 않는다
            # 지금 접속한 캐릭터는 메인 화면 왼쪽 위 이름(OCR, login.current_name)으로 알아보고 같으면 다시 고르지 않는다
            # (예전 '지문' 방식은 자주 틀려서 뺐다 — 2026-10-22). 던전 안·클리어 화면에서 멈췄던 경우는 login.run 이 먼저 정리한다
            # 인터페이스는 접속 확인(메인 HUD 템플릿)보다 먼저 맞춘다 — PC·80% 가 아니면 HUD 가 안 맞아 접속을 못 알아본다.
            # 게임 밖(타이틀·캐릭터 선택)이면 접속한 뒤에 맞추고, 그래서 접속 확인이 실패했으면 맞춘 뒤 한 번 더 접속한다
            self._prepare_interface(bot, state, opts)
            status = step(slot, "login", f"[{who}] 접속", lambda: login.run(bot, cfg, ch))
            if status not in ("OK", "STOP") and self._prepare_interface(bot, state, opts):
                status = step(slot, "login", f"[{who}] 접속", lambda: login.run(bot, cfg, ch))
            if status == "STOP":
                return
            if status != "OK":
                continue  # 접속 실패 시 이 캐릭터의 숙제는 건너뛴다
            self._prepare_interface(bot, state, opts, after_login=True)
            bot.also_done = {t for t in registry if ch and not opts.force and state.is_done(slot, t)}
            heavy = overweight(bot, cfg)
            if heavy:
                log.warning(f"[{who}] {heavy} → 이 캐릭터는 건너뜀")
                results.append((f"[{who}]", "HEAVY", heavy))
                for t in order:
                    self._emit("task_end", slot=slot, task=t, label=t, status="HEAVY", summary=heavy, seconds=0)
                continue
            bot.watch_weight = True  # 숙제 중에만 가방 무게 감시
            self._loot.open(bot, who)
            for tid in order:
                label, fn = registry[tid]
                if tid in bot.also_done:  # 다른 숙제 안에서 이미 끝냄 (사냥터 안 검은 구멍 등)
                    log.info(f"▷ [{who}] {label}: 완료")
                    self._emit("task_end", slot=slot, task=tid, label=label, status="DONE", summary="완료", seconds=0)
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
            else:
                # 일일 미션 뒤에 한 숙제(아르바이트 → '따뜻한 손길')로 새로 깬 미션의 선물. 받을 게 있을 때만 창을 연다
                if "daily_mission" in order and order[-1] != "daily_mission":
                    try:
                        got = tasks.daily_mission.claim_leftovers(bot, cfg)
                        if got:
                            log.info(f"  [{who}] 마지막에 남은 일일 미션 선물: {got}")
                    except StopRequested:
                        log.warning("사용자 중단")
                        return
                    except (StepTimeout, CannotProceed, MissingTemplate, RuntimeError) as e:
                        log.warning(f"[{who}] 마지막 일일 미션 선물 받기 실패: {e}")
