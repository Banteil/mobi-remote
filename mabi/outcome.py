"""작업 하나(숙제·반복)가 예외로 끝났을 때 결과를 가르는 공통 규칙 — 일일 숙제(runner)와 어비스·레이드 반복
(daily_api._repeat_launch)이 같이 쓴다. 예전엔 runner 에만 있어 반복은 게임 꺼짐·연속 실행 제한·가방 무게도 모두
'실패' 로만 보고 큐가 다음 카드로 넘어갔다.

결과 상태: OK · STOP(멈춤 — 이어 하기로 계속) · HEAVY(가방 무게) · SKIP(템플릿 없음) · FAIL · ERROR.
"""
import logging

from .bot import AuthBlocked, Bot, MissingTemplate, Overweight, StepTimeout, StopRequested

log = logging.getLogger("mabi")


def box(bot: Bot, tag: str) -> None:
    """실패한 작업의 직전 30초(화면·누른 것·패킷)를 남긴다 — 남기다 터져도 실패 처리는 이어 간다."""
    try:
        name = bot.dump_box(tag)
    except Exception as e:  # noqa: BLE001
        log.debug(f"블랙박스를 남기지 못함: {e}")
        return
    if name:
        log.info(f"블랙박스: {name}")


def classify(bot: Bot, tag: str, label: str, e: BaseException) -> tuple[str, str, bool]:
    """예외 → (상태, 요약, 화면 정리가 필요한가). 실패면 스냅샷·블랙박스를 남긴다."""
    from .tasks.content import CannotProceed
    if isinstance(e, StopRequested):
        log.warning("사용자 중단")
        return "STOP", "", False
    if isinstance(e, AuthBlocked):  # 접속을 더 두드리면 꼬일 수 있다 → 전체를 멈추고 사람에게 넘긴다
        log.error(str(e))
        return "STOP", str(e), False
    if isinstance(e, Overweight):  # 가방 정리가 필요 → 그 캐릭터의 남은 일은 건너뛴다
        log.warning(f"{label}: {e} → 이 캐릭터는 건너뜀")
        return "HEAVY", str(e), False
    if isinstance(e, MissingTemplate):
        return "SKIP", str(e), False
    if isinstance(e, CannotProceed):  # 미해금 등: 실패로 기록하고 다음으로
        return "FAIL", str(e), True
    if isinstance(e, StepTimeout):
        summary = f"{e} → {bot.snapshot(tag).name}"
        box(bot, tag)
        return "FAIL", summary, True
    log.error(label, exc_info=e)  # 한 작업의 알 수 없는 오류가 전체를 멈추지 않도록
    summary = f"{type(e).__name__}: {e} → {bot.snapshot(tag).name}"
    box(bot, tag)
    return "ERROR", summary, True


def recover(bot: Bot) -> None:
    """실패한 작업 뒤 정리: 콘텐츠(던전·어비스·레이드) 안이면 나오고 메인 화면으로 — 다음 작업이 낯선 화면에서 시작하지 않게.
    정리 실패로 다음 작업까지 막지 않는다 (다음 작업이 시작 점검을 한다)."""
    from .tasks.exits import leave_instance
    for what, fn in (("콘텐츠에서 나가기", lambda: leave_instance(bot)), ("메인 화면으로 돌아가기", bot.to_main)):
        try:
            fn()
        except (StepTimeout, MissingTemplate, RuntimeError):  # RuntimeError: 게임 창이 없음 (꺼짐)
            pass
        except Exception:  # noqa: BLE001
            log.exception(f"실패 뒤 {what} 실패")


def escalate(bot: Bot, status: str, summary: str) -> tuple[str, str]:
    """실패가 작업 탓이 아니라 게임 탓이면 멈춤으로 바꾼다 — 남은 일마다 같은 실패를 쌓지 않게.
    게임이 꺼짐(튕김·사람이 끔) · '재시작해 주세요' 창(AI 에이전트 연속 실행 제한 — 창은 '종료' 뿐이라 누르지 않는다)."""
    if status not in ("FAIL", "ERROR"):
        return status, summary
    if not bot.window.find():
        log.error("게임이 꺼짐 → 일시정지 (게임을 켠 뒤 다시 시작하면 이어 함)")
        return "STOP", "게임이 꺼짐 — 게임을 켠 뒤 다시 시작하면 이어 합니다"
    if bot.run_limited():
        log.error("게임 연속 실행 제한 창 → 일시정지 (게임을 다시 켠 뒤 이어 하기)")
        return "STOP", "게임을 너무 오래 켜 둠 — 게임을 다시 켠 뒤 이어 하기를 누르면 이어 합니다"
    return status, summary
