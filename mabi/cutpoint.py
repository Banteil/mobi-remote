"""정해진 시간에만 하는 일이 열렸을 때, 돌던 일을 '끊어도 되는 자리' 에서 끊고 그 일을 먼저 한다.

무엇이 정해진 시간에만 하는 일인지는 작업 큐가 카드 종류에게 묻는다 (Kind.timed · Kind.ready) — 여기는 모른다.
여기는 '지금 끊어도 되나' 만 정한다 (판정은 safe 하나로):
  - 단계가 바뀌는 때 (bot.step) 에만 본다. 끊긴 일은 진행 기록으로 그 단계부터 이어 한다.
  - 일반 필드·마을 (패킷 맵 종류 Field) 에 있을 때만. 던전·어비스·레이드·사냥터·검은 구멍·드릴·필드 보스 영역처럼
    따로 들어가는 곳 안이면 그 판이 끝나 밖으로 나온 뒤의 단계에서 끊는다 — 중간에 나가면 판·횟수·재화가 날아간다.
  - 맵을 모르면 (로딩 중·패킷 없음) 끊지 않는다. 매칭을 걸어 둔 채 · 쓰러진 채도 끊지 않는다.
  봇 없이 CLI 걸음으로 도는 일(제작·가공·채집 목표 카드)은 걸음 사이가 늘 끊어도 되는 자리라 그 사이마다 cut 을 바로 부른다.
  어비스·레이드 반복은 판이 끝나면 '다시 하기' 로 안에서 다음 판을 잡아 필드에 나오지 않는다 — 판 사이에 due() 로 묻고
  열렸으면 다시 하기 대신 나간다 (tasks.repeat.yield_between). 그러면 다음 입장 단계(필드)에서 여기서 끊긴다.
끊는 일은 작업 큐가 한다 (set_hook — 그 카드를 맨 위로 올리고 지금 카드를 밀어낸다 → 봇은 다음 대기에서 멈춘다).
끊는 자리에서는 연속 실행 제한 창도 본다 (restart.watch) — 떠 있으면 '게임 다시 켜기' 카드가 맨 위에 올라 같은 길로 먼저 한다.
"""
import logging

from . import restart

log = logging.getLogger("mabi")

OPEN_FIELD = "Field"            # 마을·일반 필드의 맵 종류 (사냥터는 BattleField, 던전류는 Instance…, 필드 보스는 FieldBoss)
NO_CUT_STEPS = ("abyss_match",)  # 입장을 누른 뒤에 기록하는 단계 — 아직 필드에 있어도 곧 들어간다

_hook = None  # () -> str: 먼저 할 일이 있어 지금 카드를 밀어냈으면 까닭, 아니면 "" (작업 큐)
_due = None   # () -> str: 먼저 할 일이 열렸나 — 묻기만 (작업 큐)


def set_hook(fn, due=None) -> None:
    global _hook, _due
    _hook, _due = fn, due


def due(bot=None) -> str:
    """먼저 할 일이 열려 있나 (밀어내지는 않는다). 열렸으면 까닭, 아니면 "". bot 을 주면(어비스·레이드 판 사이)
    연속 실행 제한 창도 본다 — 떠 있으면 '게임 다시 켜기' 가 먼저 할 일이 된다."""
    if bot is not None:
        restart.watch(bot)
    if _due is None:
        return ""
    try:
        return _due() or ""
    except Exception:  # noqa: BLE001 — 끼워 넣기 확인이 하던 일을 막으면 안 된다
        log.exception("끼워 넣기 확인 실패")
        return ""


def safe(bot) -> bool:
    """지금 하던 일을 끊어도 되는 곳인가."""
    p = bot.packets
    if not p.ok:
        return False
    s = p.state
    return bool(not s.loading and s.channel_type == OPEN_FIELD and not s.abyss_matching and not s.dead)


def check(bot, step: str) -> None:
    """단계가 바뀔 때 (bot.step). 먼저 할 일이 열렸고 끊어도 되는 곳이면 큐가 지금 일을 밀어낸다."""
    if step in NO_CUT_STEPS or not safe(bot):
        return
    restart.watch(bot)  # 연속 실행 제한 창이면 '게임 다시 켜기' 카드가 맨 위에 — 아래 cut 이 지금 일을 밀어낸다
    cut(f"'{step}' 단계 앞")


def cut(where: str) -> bool:
    """여기는 끊어도 되는 자리다 — 먼저 할 일이 열렸으면 큐가 지금 일을 밀어낸다. 밀어냈으면 True (큐가 서는 중)."""
    if _hook is None:
        return False
    try:
        why = _hook()
    except Exception:  # noqa: BLE001 — 끼워 넣기 확인이 하던 일을 막으면 안 된다
        log.exception("끼워 넣기 확인 실패")
        return False
    if why:
        log.info(f"{why} → {where}에서 지금 일을 멈추고 먼저 함 (끝나면 이어서)")
    return bool(why)
