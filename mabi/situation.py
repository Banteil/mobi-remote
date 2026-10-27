"""지금 게임이 어떤 상황인가 — 어디서 켜도 그 자리에서 다음 단계로 가기 위한 한곳.

상황 판단은 패킷 → CLI → 화면 순서다 (docs/STATUS.md '상태 판단 순서'). 숙제마다 '메인 화면에서 출발' 을 가정하면
전달 창·작별 대사·던전 창·가공 창 앞에 선 채로 시작했을 때 헤맨다 (2026-10-26). look() 이 지금 상황을 한 단어로 주고,
숙제는 그 상황에 맞는 단계부터 한다 (예: 공물 — 심층 던전 창이 이미 열려 있으면 퀘스트 창을 건너뛴다).

출석: 오전 6시(게임 날짜 바뀜)가 지나면 다음에 필드로 나올 때 출석 대사가 뜬다. 접속 단계(login)는 원래 넘겼지만
어비스 반복처럼 캐릭터를 바꾸지 않고 6시를 넘기면 — 쓰러져 나가거나 수리하러 나가는 순간 — 출석 대사에 막혔다
(2026-10-26 사용자). clear_attendance() 를 막는 화면 넘기기(content.clear_blockers)가 늘 먼저 부른다.
"""
import time

from .profile import game_date

# look() 결과
RUN_LIMIT = "run_limit"            # '게임이 너무 오랫동안 실행되고 있습니다' (CLI 가 알려 준 것만 — 화면 OCR 은 Bot.run_limited)
LOADING = "loading"                # 맵 로딩 중 (패킷)
CHARSELECT = "charselect"          # 캐릭터 선택 화면 (패킷, 모르면 그림)
TITLE = "title"                    # 타이틀 화면 ('게임 시작')
ATTENDANCE = "attendance"          # 출석 대사 ('출석부 건너뛰기')
DELIVER = "deliver"                # 아르바이트 물품 '전달하기' 창
DUNGEON_WINDOW = "dungeon_window"  # 던전 입장 창 (일반·심층·요일 탭 중 하나가 선택됨)
CRAFT = "craft"                    # 제작·가공 창 첫 화면 ('설비로 이동')
DIALOG = "dialog"                  # NPC 대화 (패킷, 모르면 '대화 기록'·넘기기 버튼)
FAREWELL = "farewell"              # 대화는 끝났는데(패킷) 작별 대사 화면이 남음 — '대화 넘기기' 자리를 누르면 닫힌다
MAIN = "main"                      # 필드 메인 화면
UNKNOWN = "unknown"

DUNGEON_TABS = {"dungeon_tab_normal_on": "normal", "dungeon_tab_deep_on": "deep", "dungeon_tab_weekday_on": "weekday"}


def _find(bot, frame, name):
    return bool(name) and bot.vision.has(name) and bot.vision.find(frame, name)


def dungeon_tab(bot, frame=None) -> str | None:
    """던전 창이 열려 있으면 선택된 탭 ('normal' · 'deep' · 'weekday'), 아니면 None."""
    frame = bot.frame() if frame is None else frame
    return next((tab for name, tab in DUNGEON_TABS.items() if _find(bot, frame, name)), None)


def look(bot, frame=None) -> str:
    """지금 상황 한 단어. 판정은 점검자의 상황 인식(mabi.monitor.detect) 한곳에서 한다 — 위 상수에 더해
    아르바이트·제작 창 같은 것도 나온다 (detect 의 상수)."""
    from .monitor import detect
    return detect.look(bot, frame).what


# ---------------------------------------------------------------- 출석

def attendance_due(bot) -> bool:
    """오늘(게임 날짜) 출석을 아직 안 넘겼을 수 있나 — 리모콘이 이 캐릭터로 오늘 출석을 넘긴 적이 없고,
    이 실행을 시작한 뒤에 게임 날짜가 바뀌었다 (접속 단계는 출석을 따로 넘기고 attendance_done 을 부른다)."""
    return getattr(bot, "attendance_date", None) not in (None, game_date())


def attendance_done(bot) -> None:
    bot.attendance_date = game_date()


def clear_attendance(bot, frame=None) -> str | None:
    """출석 대사를 하나 넘긴다. 넘긴 것의 이름, 없으면 None.
    - '출석부 건너뛰기' 가 보이면 그것만 누른다 ('대화 넘기기' 는 다른 대사로 이어진다 — 사용자 2026-10-22)
    - 그 전에 NPC 가 버튼 없는 대사를 한두 마디 한다 (몇 마디인지는 무작위 — 사용자 2026-10-27). 패킷이 출석 대화
      시작을 알렸으면 건너뛰기가 뜰 때까지 가운데를 2초에 한 번 눌러 대사를 넘긴다
    - 패킷이 없으면: 날짜가 바뀐 뒤(attendance_due)에 패킷이 NPC 대화 중이라는데 넘기기 버튼이 없을 때만 가운데를 누른다
      (4초에 한 번 — 대사가 뜬 뒤 잠깐 입력을 안 받는다)"""
    frame = bot.frame() if frame is None else frame
    c = bot.cfg["login"]
    p = bot.packets
    if (m := _find(bot, frame, c.get("attendance_skip"))):
        bot.click(m)
        attendance_done(bot)
        if p.ok:
            p.state.attendance_at = 0.0  # 끝 패킷을 아직 몰라 넘긴 쪽이 지운다 (안 눌렸으면 건너뛰기가 남아 다시 누른다)
        return "출석부 건너뛰기"
    if p.ok and p.state.attending():
        if time.monotonic() - getattr(bot, "_attendance_clicked", 0) < 2:
            return "출석 대사 기다림"
        bot._attendance_clicked = time.monotonic()
        bot.click(tuple(c["first_dialog_xy"]))
        return "출석 대사 넘김"
    if not attendance_due(bot):
        return None
    if not (p.ok and p.state.in_dialogue) or bot.skip_button(frame) or bot.at_main():
        return None
    if time.monotonic() - getattr(bot, "_attendance_clicked", 0) < 4:
        return None
    bot._attendance_clicked = time.monotonic()
    bot.log.info("날짜가 바뀐 뒤 버튼 없는 대사 (출석 첫 대사) → 화면 한 번 클릭")
    bot.click(tuple(c["first_dialog_xy"]))
    return "출석 첫 대사"


# ---------------------------------------------------------------- 메인 화면으로

def to_main(bot, timeout: float = 60) -> str:
    """지금 상황에서 메인 화면까지 (어디서 켜도). 마지막 상황을 돌려준다 (MAIN 이면 성공).
    점검자(mabi.monitor)가 남은 대사·확인·전달 창·작별 화면·출석을 정리하고, 그래도 메인이 아니면 ESC (Bot.to_main).
    NPC 대화 도중이면 메뉴(수락·결과 보고)까지 처리한다 — ESC 가 하던 아르바이트를 날리지 않게."""
    from . import monitor
    from .bot import StepTimeout
    mon = monitor.of(bot)
    end = time.monotonic() + timeout
    at = look(bot)
    while at != MAIN and time.monotonic() < end:
        if at in (RUN_LIMIT, CHARSELECT, TITLE):
            return at  # 게임 밖이거나 사람 몫 — 접속 단계가 따로 한다
        if at == LOADING:
            bot.wait_loaded(max(1, end - time.monotonic()))
        elif not mon.settle(monitor.Ctx("to_main", menus=True)) and look(bot) not in (MAIN, LOADING):
            try:
                bot.to_main(tries=2)
            except StepTimeout:
                pass
        bot.sleep(1.2, 1.6)
        at = look(bot)
    return at
