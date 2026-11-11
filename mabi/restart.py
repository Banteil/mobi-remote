"""게임 다시 켜기 — 연속 실행 제한 창('게임이 너무 오랫동안 실행되고 있습니다. 게임을 재시작해주세요.' + 초록 '종료')이 뜨면.

창은 밤새 돌린 뒤쯤 뜬다. 떠 있어도 판 안의 일은 계속 되지만 화면 위 가운데를 가려(ui.json covers) 입장 창 같은 다음 일을
못 한다 (2026-11-10 친구 PC: 전멸 뒤 입장 창에서 74분 멈춤). 게임을 다시 켜면 풀리므로 사람 대신 한다 (2026-11-11 사용자,
기본 켬 — [restart] auto).
  - 언제: 작업 큐가 돌 때만 (쉬고 있으면 사람이 하는 중). 끊어도 되는 자리(mabi/cutpoint — 필드에서 단계가 바뀔 때 ·
    어비스·레이드 판 사이)에서 창을 보면(watch) 큐 맨 위에 '게임 다시 켜기' 카드를 올린다 → 큐가 하던 카드를 그 자리에서
    밀어내고 이것부터 한 뒤 하던 카드를 이어 한다. 창 때문에 일이 실패했으면(outcome.escalate → now) 바로 밀어낸다.
  - 어떻게(run): 끄기 전 캐릭터를 기억 → 창의 '종료' → 게임 프로세스가 끝날 때까지 → 넥슨 플러그 '바로실행' 링크
    ([restart] launch — 런처가 로그인 정보를 넣어 켠다. 리모콘이 관리자 권한이면 그 아래로 켜져 UAC 창도 안 뜬다)
    → 타이틀 → 그 캐릭터로 접속 (tasks.login).
  - 못 하면(넥슨 로그인 풀림·업데이트·점검 등) CannotProceed — 큐는 그 카드에서 일시정지 (사람이 게임을 켜고 ▶).
큐와는 set_hook 으로만 잇는다 (cutpoint 와 같은 방식 — 여기는 큐를 모른다).
"""
from __future__ import annotations

import ctypes
import logging
import os
import time
from typing import TYPE_CHECKING

from . import gamedata as gd

if TYPE_CHECKING:  # bot 이 cutpoint → restart 를 불러오므로 여기서 bot 을 바로 불러오면 돌고 돈다
    from .bot import Bot

log = logging.getLogger("mabi")

_hook = None  # (까닭, now) -> bool: 작업 큐가 '게임 다시 켜기' 를 받았으면 True (gui_app/queue_api._q_restart)

SYNCHRONIZE, WAIT_TIMEOUT, ERROR_ACCESS_DENIED = 0x00100000, 0x102, 5


def set_hook(fn) -> None:
    global _hook
    _hook = fn


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
def run(bot: Bot, cfg: dict, character: dict | None = None, keep=lambda ch: None) -> str:
    """창의 '종료' 로 끄고 다시 켜서 같은 캐릭터로 접속한다. character 는 앞서 기억한 캐릭터(이어 하기 — 이미 꺼진 게임),
    keep(캐릭터) 는 끄기 전에 알아낸 캐릭터를 카드에 적어 두라는 것. 게임이 켜져 있는데 창이 없으면(사람이 이미 다시
    켬 · ▶ 로 이어 하기) 끄지 않고 접속만 확인한다."""
    from .tasks import login
    c = cfg["restart"]
    if bot.window.find():
        if not bot.run_limit_popup():
            bot.log.info("연속 실행 제한 창이 없음 → 다시 켜지 않고 접속만 확인")
            bot.log.info(login.run(bot, cfg, character))
            return "연속 실행 제한 창이 없음 — 다시 켜지 않음"
        character = _character(bot) or character
        keep(character)
        _quit(bot, float(c["exit_timeout"]))
    else:
        bot.log.info("게임이 꺼져 있음 → 바로 켬")
    _launch(bot, cfg)
    bot.log.info(login.run(bot, cfg, character))
    return f"게임을 다시 켜고 {character['name'] if character else '마지막 캐릭터'} 로 접속"


def _character(bot: Bot) -> dict | None:
    """지금 캐릭터 (슬롯·이름) — 다시 켜서 이 캐릭터로 접속한다. 프로필에 없으면 None (선택 화면에서 골라져 있던
    캐릭터 = 마지막으로 한 캐릭터로 들어간다)."""
    from . import profile as prof
    from .tasks.login import current_name, name_matches
    p = bot.packets
    name = (p.state.my_name if p.ok else None) or ""
    if not name:
        try:
            name = current_name(bot)
        except Exception:  # noqa: BLE001 — 이름을 못 읽어도 다시 켜기는 한다
            name = ""
    if not name:
        return None
    chars = prof.characters(prof.load_profile(bot.paths.profile) or {"slots": []})
    return next((ch for ch in chars if name_matches(name, ch["name"])), None)


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


def _gone(bot: Bot, pid: int, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not bot.window.find() and not (pid and _alive(pid)):
            return True
        bot.sleep(1)
    return False


def _quit(bot: Bot, timeout: float) -> None:
    """창의 '종료' 를 누르고 게임 프로세스가 끝날 때까지. 안 꺼지면 한 번 더 누른다."""
    pid = _pid(bot.window.hwnd)
    x, y, w, h = gd.region("run_limit_button")
    for attempt in range(2):
        bot.log.info("연속 실행 제한 창 '종료' 누름 → 게임을 다시 켬" + (" (다시)" if attempt else ""))
        bot.click((x + w // 2, y + h // 2))
        if _gone(bot, pid, timeout / 2):
            bot.log.info("게임 꺼짐")
            return
    from .tasks.content import CannotProceed
    raise CannotProceed(f"'종료' 를 눌러도 게임이 꺼지지 않음 → {bot.snapshot('restart_quit').name}")


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
