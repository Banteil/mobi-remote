"""게임 다시 켜기 — 연속 실행 제한 창('게임이 너무 오랫동안 실행되고 있습니다. 게임을 재시작해주세요.' + 초록 '종료')이 뜨면.

창은 밤새 돌린 뒤쯤 뜬다. 떠 있어도 판 안의 일은 계속 되지만 화면 위 가운데를 가려(ui.json covers) 입장 창 같은 다음 일을
못 한다 (2026-11-10 친구 PC: 전멸 뒤 입장 창에서 74분 멈춤). 게임을 다시 켜면 풀리므로 사람 대신 한다 (2026-11-11 사용자,
기본 켬 — [restart] auto).
  - 언제: 작업 큐가 돌 때만 (쉬고 있으면 사람이 하는 중). 끊어도 되는 자리(mabi/cutpoint — 필드에서 단계가 바뀔 때 ·
    어비스·레이드 판 사이)에서 창을 보면(watch) 큐 맨 위에 '게임 다시 켜기' 카드를 올린다 → 큐가 하던 카드를 그 자리에서
    밀어내고 이것부터 한 뒤 하던 카드를 이어 한다. 창 때문에 일이 실패했으면(outcome.escalate → now) 바로 밀어낸다.
  - 어떻게(run): 끄기 전 캐릭터를 기억 → 게임 창 닫기 신호(WM_CLOSE — 창의 X 와 같다) → 게임 프로세스가 끝날 때까지
    → 넥슨 플러그 '바로실행' 링크 ([restart] launch — 런처가 로그인 정보를 넣어 켠다. 넥슨 플러그·게임 실행 파일은
    관리자 권한을 요구하지 않아(asInvoker) UAC 창도 안 뜬다) → 타이틀 → 그 캐릭터로 접속 (tasks.login).
    제한 창의 '종료' 는 누르지 않는다 — 창 닫기는 실기에서 확인됐고(2026-11-11) 그 창이 없어도 같은 길이라 명령으로
    시험할 수 있다 (force — gui.py --restart-game).
  - 못 하면(넥슨 로그인 풀림·업데이트·점검 등) CannotProceed — 큐는 그 카드에서 일시정지 (사람이 게임을 켜고 ▶).
게임 서버와 연결이 끊긴 창(점검 등 — bot.server_down_shown)이 뜨면 같은 닫기 신호로 게임을 끄고 큐를 일시정지한다
(server_down — 점검은 몇 시간이라 다시 켜지는 않는다).
큐와는 set_hook·set_pause_hook 으로만 잇는다 (cutpoint 와 같은 방식 — 여기는 큐를 모른다).
"""
from __future__ import annotations

import ctypes
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # bot 이 cutpoint → restart 를 불러오므로 여기서 bot 을 바로 불러오면 돌고 돈다
    from .bot import Bot

log = logging.getLogger("mabi")

_hook = None  # (까닭, now) -> bool: 작업 큐가 '게임 다시 켜기' 를 받았으면 True (gui_app/queue_api._q_restart)
_pause = None  # (메모) -> None: 작업 큐를 이 메모로 일시정지 (gui_app/queue_api — 서버 연결이 끊겨 게임을 끔)

SYNCHRONIZE, WAIT_TIMEOUT, ERROR_ACCESS_DENIED, WM_CLOSE = 0x00100000, 0x102, 5, 0x0010
CONFIRM_TAKES = 3  # 첫 신호 뒤 '게임을 종료하시겠습니까?' 창이 뜨길 기다리는 초 — 그다음 신호가 '게임 종료'
CLOSE_TAKES = 15  # 그 뒤로 신호마다 게임 창이 닫히길 기다리는 초 — 안 닫히면 다시 보낸다
CLOSE_TRIES = 3


def set_hook(fn) -> None:
    global _hook
    _hook = fn


def set_pause_hook(fn) -> None:
    global _pause
    _pause = fn


def enabled(cfg: dict) -> bool:
    return bool((cfg.get("restart") or {}).get("auto", True))


def _ask(why: str, now: bool) -> bool:
    try:
        return bool(_hook(why, now))
    except Exception:  # noqa: BLE001 — 다시 켜기 요청이 하던 일을 막으면 안 된다
        log.exception("게임 다시 켜기 요청 실패")
        return False


def watch(bot: Bot) -> bool:
    """끊어도 되는 자리에서 (cutpoint): 연속 실행 제한 창이면 작업 큐에 '게임 다시 켜기' 를 올린다 → True.
    큐가 그 자리에서 하던 카드를 밀어낸다. 창 확인은 '종료' 버튼 색부터 봐서(run_limit_shown) 평소엔 가볍다."""
    if _hook is None or not enabled(bot.cfg) or not bot.run_limit_popup():
        return False
    return _ask("화면에 연속 실행 제한 창", now=False)


def now(bot: Bot, why: str) -> bool:
    """연속 실행 제한 창 때문에 일이 실패했다 (outcome.escalate) — 하던 카드를 바로 밀어내고 다시 켠다. 큐가 받았으면 True."""
    if _hook is None or not enabled(bot.cfg):
        return False
    return _ask(why, now=True)


# ---------------------------------------------------------------- 다시 켜기 (큐의 '게임 다시 켜기' 카드)
def run(bot: Bot, cfg: dict, character: dict | None = None, keep=lambda ch: None, force: bool = False) -> str:
    """게임을 끄고 다시 켜서 같은 캐릭터로 접속한다. character 는 앞서 기억한 캐릭터(이어 하기 — 이미 꺼진 게임),
    keep(캐릭터) 는 끄기 전에 알아낸 캐릭터를 카드에 적어 두라는 것. 게임이 켜져 있는데 제한 창이 없으면(사람이 이미
    다시 켬 · ▶ 로 이어 하기) 끄지 않고 접속만 확인한다 — force(명령)면 창이 없어도 끈다."""
    from .tasks import login
    c = cfg["restart"]
    if bot.window.find():
        if not force and not bot.run_limit_popup():
            bot.log.info("연속 실행 제한 창이 없음 → 다시 켜지 않고 접속만 확인")
            bot.log.info(login.run(bot, cfg, character))
            return "연속 실행 제한 창이 없음 — 다시 켜지 않음"
        character = login.current_character(bot) or character
        keep(character)
        _quit(bot, float(c["exit_timeout"]))
    else:
        bot.log.info("게임이 꺼져 있음 → 바로 켬")
    _launch(bot, cfg)
    bot.log.info(login.run(bot, cfg, character))
    return f"게임을 다시 켜고 {character['name'] if character else '마지막 캐릭터'} 로 접속"


def _pid(hwnd: int) -> int:
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _alive(pid: int) -> bool:
    """프로세스가 아직 있나 (창이 사라진 뒤에도 끝나는 데 시간이 걸린다 — 다 끝나기 전에 켜면 '이미 실행 중' 일 수 있다)."""
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        return k32.GetLastError() == ERROR_ACCESS_DENIED  # 권한이 없어 못 연 것은 아직 있는 것, 그 밖은 없는 것
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(h), 0) == WAIT_TIMEOUT
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def _until(bot: Bot, cond, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while True:
        if cond():
            return True
        if time.monotonic() > end:
            return False
        bot.sleep(1)


def _close(hwnd: int) -> None:
    ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def _quit(bot: Bot, timeout: float) -> None:
    """게임 창에 닫기 신호를 보내고 게임 프로세스가 끝날 때까지. 게임은 첫 신호에 '게임을 종료하시겠습니까?' (취소 /
    게임 종료) 창을 띄우고 두 번째 신호에 꺼진다 (2026-11-11 실기 네 번 — 두 번째 뒤 5~16초). 그래서 3초 뒤 한 번 더
    보내고, 그래도 창이 남아 있으면 다시 보낸다. 창이 닫혀도 정리하느라 프로세스가 남아 있을 수 있어 끝날 때까지
    기다린다 (다 끝나기 전에 켜면 '이미 실행 중' 일 수 있다)."""
    from .tasks.content import CannotProceed
    pid = _pid(bot.window.hwnd)
    for attempt in range(CLOSE_TRIES):
        bot.log.info("게임 창 닫기" + ("", " (종료 확인)", f" (다시 {attempt - 1})")[min(attempt, 2)])
        _close(bot.window.hwnd)  # 앞의 _until 이 창을 다시 찾았다 (find 가 hwnd 를 새로 적는다)
        if _until(bot, lambda: not bot.window.find(), CLOSE_TAKES if attempt else CONFIRM_TAKES):
            break
    else:
        raise CannotProceed(f"닫기 신호를 {CLOSE_TRIES}번 보내도 게임 창이 그대로 → {bot.snapshot('restart_quit').name}")
    if not _until(bot, lambda: not (pid and _alive(pid)), timeout):
        raise CannotProceed(f"게임 창은 닫혔는데 {timeout:.0f}초 안에 프로세스가 끝나지 않음")
    bot.log.info("게임 꺼짐")


# ---------------------------------------------------------------- 서버 연결 끊김 (점검)
DOWN_NOTE = "게임 서버 연결이 끊겨(점검 등) 게임을 껐습니다 — 점검이 끝나면 게임을 켜고 ▶"


def server_down(bot: Bot) -> str:
    """게임 서버와 연결이 끊긴 창이 떠 있다 (bot.server_down_shown — 목요일 점검·임시 점검). 그 창은 게임을 끌 때까지
    남고, 리모콘은 그 앞에서 하던 일만 붙잡고 있었다 (2026-11-12 06:00~06:13 어비스 보스방). 그래서 게임을 끄고 작업 큐를
    일시정지한다 (2026-11-12 사용자). 점검은 몇 시간이라 다시 켜지는 않는다 — 점검 뒤 사람이 게임을 켜고 ▶ 면 하던 카드를
    그 자리부터 이어 한다. 끄는 길은 다시 켜기와 같은 창 닫기 신호(_quit). 창의 '확인' 이 무엇을 하는지는 아직 몰라 먼저
    누르지 않고, 닫기 신호로 창이 안 닫힐 때만 '확인'(Space) 뒤 한 번 더 보낸다. 큐에 남길 메모를 돌려준다 —
    봇은 멈춤 요청 상태가 된다 (뒤이어 무엇을 하려 해도 StopRequested)."""
    from .tasks.content import CannotProceed
    timeout = float(bot.cfg["restart"]["exit_timeout"])
    bot.log.error(f"게임 서버와 연결이 끊김 (점검 등) → 게임을 끄고 작업 큐 일시정지 ({bot.snapshot('server_down').name})")
    note = DOWN_NOTE
    try:
        try:
            _quit(bot, timeout)
        except CannotProceed as e:
            if not bot.window.find():
                raise  # 창은 닫혔는데 프로세스가 안 끝남 — '확인' 을 누를 창이 없다
            bot.log.warning(f"{e} → 창의 '확인'(Space)을 누르고 다시 닫기")
            bot.key("space")
            bot.sleep(3)
            if bot.window.find():
                _quit(bot, timeout)
    except CannotProceed as e:
        bot.log.error(f"게임을 끄지 못함: {e}")
        note = f"게임 서버 연결이 끊김(점검 등) — 게임을 끄지 못함 ({e}) · 게임을 끄고, 점검이 끝나면 켠 뒤 ▶"
    if _pause is not None:
        try:
            _pause(note)
        except Exception:  # noqa: BLE001 — 큐에 메모를 못 남겨도 멈추기는 한다
            log.exception("작업 큐 일시정지 요청 실패")
    bot.stopper.request(note)
    return note


def _launch(bot: Bot, cfg: dict) -> None:
    """넥슨 플러그 바로실행 링크로 켜고 타이틀(또는 캐릭터 선택·메인)이 보일 때까지."""
    from .bot import StopRequested
    from .tasks.content import CannotProceed
    c, ui = cfg["restart"], bot.ui
    limit = float(c["start_timeout"])
    bot.log.info("게임 켜기 — 넥슨 플러그 바로실행")
    os.startfile(c["launch"])  # noqa: S606 — 사용자가 쓰는 바로가기와 같은 링크 (설정값)
    end = time.monotonic() + limit
    while not bot.window.find():
        if time.monotonic() > end:
            raise CannotProceed(f"게임이 {limit:.0f}초 안에 켜지지 않음 — 넥슨 플러그(로그인·업데이트)를 확인한 뒤 ▶")
        bot.sleep(2)
    bot.log.info("게임 창이 뜸 → 타이틀 기다림")
    screens = [ui["title_start"], ui["charselect_title"], ui["main_hud"]]
    while True:
        try:  # 막 뜬 창은 크기가 다르거나 검은 화면이라 찾기가 실패할 수 있다 — 끝날 때까지 다시 본다
            if any(bot.exists(n) for n in screens):
                return
        except StopRequested:
            raise
        except Exception as e:  # noqa: BLE001
            bot.log.debug(f"타이틀 찾기 실패 (켜지는 중): {e}")
        if time.monotonic() > end:
            raise CannotProceed(f"게임은 켜졌는데 {limit:.0f}초 안에 타이틀이 안 보임 → {bot.snapshot('restart_title').name}")
        bot.sleep(2)
