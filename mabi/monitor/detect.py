"""지금 무슨 상황인가 — 점검자가 쓰는 상황 인식 한곳.

순서는 패킷 → CLI → 화면이고, 위에 있는 것이 먼저다 (창이 겹치면 맨 앞 창이 위쪽 줄에 있다).
태스크는 이 표를 보지 않는다. 새 화면을 만나면 여기에 한 줄, handlers 에 대응 하나를 넣으면 모든 태스크가 같이 쓴다.
판정이 맞는지는 tests/fixtures/screens/<상황>/ 의 화면으로 확인한다 (tests/test_screens.py).
"""
from dataclasses import dataclass, field

from .. import situation as sit

# 상황 이름 (situation.py 의 것에 아르바이트·제작·던전 화면을 더한 것)
RUN_LIMIT, LOADING, CHARSELECT, TITLE = sit.RUN_LIMIT, sit.LOADING, sit.CHARSELECT, sit.TITLE
ATTENDANCE, DELIVER, DUNGEON_WINDOW, DIALOG, FAREWELL = sit.ATTENDANCE, sit.DELIVER, sit.DUNGEON_WINDOW, sit.DIALOG, sit.FAREWELL
MAIN, UNKNOWN, CRAFT = sit.MAIN, sit.UNKNOWN, sit.CRAFT
EXIT_ASK = "exit_ask"              # '게임을 종료하시겠습니까?' · '던전에서 퇴장하시겠습니까?' — Space·확인이 '예' 라 건드리지 않는다
HOWTO = "howto"                    # '구하는 방법' 창 (모자란 물품을 어디서 구하나)
ITEM_MISSING = "item_missing"      # '퀘스트를 위해 필요한 아이템이 없습니다.'
CONFIRM = "confirm"                # 초록 '확인' 버튼 (퀘스트 클리어 등)
ACCEPT = "accept"                  # NPC 메뉴 '수락' (Space)
REPORT = "report"                  # NPC 메뉴 Space 선택지 ('결과 보고' 등)
ALTER = "alter"                    # 가공 시설 창 '가공하기'
CRAFT_TRANSFER = "craft_transfer"  # '재료를 전송하시겠습니까?'
CRAFT_GO = "craft_go"              # 제작 창 '제작하러 가기' / 설비 앞 '제작하기'
SCENE = "scene"                    # 연출 '장면 넘기기'
REWARD = "reward"                  # 던전·사냥터 보상 화면 ('나가기' · '다시 하기' · '새 임무 선택')
TOUCH = "touch"                    # 던전 클리어 뒤 '화면을 터치해 주세요'
DEAD = "dead"                      # 내 캐릭터가 쓰러짐 (패킷 — 부활 창 열림)
STELLA = "stella"                  # '오늘의 스텔라 픽' (하루 첫 접속)
NOTICE = "notice"                  # 공지사항 웹 팝업 (ESC 로 닫힘)
EVENT_POPUP = "event_popup"        # '새로운 이벤트' 안내 창 (회색 '닫기')

OUTSIDE = (RUN_LIMIT, CHARSELECT, TITLE, EXIT_ASK)  # 게임 밖이거나 사람 몫 — 점검자가 누르지 않는다


@dataclass
class Seen:
    """한 번 본 것. what 이 상황 이름, hit 은 그 화면에서 찾은 자리(있으면), src 는 무엇으로 알았나."""
    what: str
    hit: object = None
    src: str = "screen"
    frame: object = None
    idle: bool | None = None  # MAIN 일 때만: 이동·자동 진행·대화·전투가 아님 (CLI·패킷)
    info: dict = field(default_factory=dict)
    done: str | None = None   # 점검자가 한 일 (core.check 가 채운다)
    finish: object = None     # 이 일은 여기서 끝 (handlers.Finish)


def idle(bot) -> bool:
    """이동·자동 진행·대화·전투 중이 아님. 자동 진행(IsAutoPlaying)은 아직 패킷으로 끝을 모른다 — 나머지는 패킷 우선."""
    a = bot._act(None)
    return not (a.get("IsAutoPlaying") or bot.auto_traveling(a) or bot.dialogue_playing(a) or bot.in_combat(a))


def look(bot, frame=None, skip=(), ocr: bool = False) -> Seen:
    """지금 상황. skip 에 든 템플릿은 보지 않는다 (기다리는 쪽이 지금 찾는 것). ocr: 템플릿이 잘 안 맞는 '확인'·'화면 터치' 를
    글자로도 본다 (느려서 가끔만)."""
    if bot.cli.run_limited is True:
        return Seen(RUN_LIMIT, src="cli")
    if bot.map_loading():
        return Seen(LOADING, src="packet")
    if bot.packets.at_charselect():
        return Seen(CHARSELECT, src="packet")
    if bot.packets.ok and bot.packets.state.dead:
        return Seen(DEAD, src="packet")  # 사망 화면 위의 창은 부활한 뒤에 본다
    frame = bot.frame() if frame is None else frame
    ui, a = bot.ui, bot.cfg["arbeit"]

    def f(name):
        return (name and name not in skip and bot.vision.has(name) and bot.vision.find(frame, name)) or None

    if f(ui.get("exit_dialog")) or f(ui.get("abyss_exit_dialog")):
        return Seen(EXIT_ASK, frame=frame)
    # 메인 HUD 가 보이면 창이 하나도 안 열린 것 — 창 템플릿(대부분 화면 전체를 뒤져 하나에 0.2초)을 건너뛴다.
    # HUD 가 보인 채로 뜨는 것(퀘스트 클리어 '확인'·화면 터치·연출)만 본다. 한 번 보는 데 2초 걸리던 것 (2026-10-26)
    if f(ui.get("main_hud")):
        from ..tasks.dialogue import _packet
        if (p := _packet(bot)) is not None and p.in_dialogue:
            return Seen(DIALOG, src="packet", frame=frame)  # 대화가 막 열리는 중 (HUD 가 아직 남음)
        if (m := f(ui.get("confirm_green"))):
            return Seen(CONFIRM, m, frame=frame)
        if (m := f(ui.get("reward_exit")) or f(ui.get("dungeon_retry"))):
            return Seen(REWARD, m, frame=frame)  # 사냥터 보상 화면은 HUD 가 보인 채로 뜬다
        if f(ui.get("dungeon_touch")):
            return Seen(TOUCH, frame=frame)
        if (hit := bot.skip_button(frame, skip)) and hit[0] == "scene":
            return Seen(SCENE, hit[1], frame=frame)
        if not (bot.map_loading() or bot.packets.at_charselect()):
            return Seen(MAIN, frame=frame, idle=idle(bot))
    if bot.packets.at_charselect() is None and f(ui.get("charselect_title")):
        return Seen(CHARSELECT, frame=frame)
    if f(ui.get("title_start")):
        return Seen(TITLE, frame=frame)
    # 접속 직후 창들 — 오전 6시 뒤 첫 접속·캐릭터마다 뜰 수도 안 뜰 수도 있어 어느 일에서든 본다
    lg = bot.cfg["login"]
    for what, name in ((STELLA, lg.get("stella_title")), (NOTICE, lg.get("notice_webview")),
                       (EVENT_POPUP, lg.get("event_popup_close"))):
        if (m := f(name)):
            return Seen(what, m, frame=frame)
    if (m := f(bot.cfg["login"].get("attendance_skip"))):
        return Seen(ATTENDANCE, m, frame=frame)
    # 보상 화면 위에 퀘스트 클리어 '확인' 이 겹쳐 뜬다 (주말 어비스 3판 등) → 확인을 먼저
    if (m := f(ui.get("confirm_green"))):
        return Seen(CONFIRM, m, frame=frame)
    if (m := f(ui.get("reward_exit")) or f(ui.get("dungeon_retry"))):
        return Seen(REWARD, m, frame=frame)  # 어비스 보상 화면은 '다시 하기' 로도
    tab = next((t for n, t in sit.DUNGEON_TABS.items() if f(n)), None)
    if tab:
        return Seen(DUNGEON_WINDOW, frame=frame, info={"tab": tab})
    # 아르바이트·제작 창 (아르바이트가 보던 순서 그대로)
    for what, name in ((HOWTO, a["howto_title"]), (ITEM_MISSING, a["item_missing"]), (CONFIRM, ui["confirm_green"]),
                       (DELIVER, a["deliver_title"]), (REPORT, a["report"]), (ACCEPT, a["accept"]),
                       (ALTER, a["alter_button"]), (CRAFT_TRANSFER, a["craft_transfer"]),
                       # '제작하기' 템플릿은 '제작하러 가기' 에도 0.8 정도로 걸린다 → '가기' 를 먼저
                       (CRAFT_GO, a["craft_go"]), (CRAFT_GO, a["craft_make"]), (CRAFT, a["craft_list"])):
        if (m := f(name)):
            return Seen(what, m, frame=frame)
    from ..tasks.dialogue import _packet, in_dialog
    if in_dialog(bot, frame):
        return Seen(DIALOG, src="packet" if _packet(bot) is not None else "screen", frame=frame)
    if bot.packets.ok and f(a["dialog_log"]):
        return Seen(FAREWELL, src="packet+screen", frame=frame)  # 패킷은 대화가 끝났다는데 '대화 기록' 이 남음
    if (hit := bot.skip_button(frame, skip)) and hit[0] == "scene":
        return Seen(SCENE, hit[1], frame=frame)
    if ocr and "confirm_green" not in skip:
        from ..tasks.content import _confirm_text
        if (xy := _confirm_text(frame)):
            return Seen(CONFIRM, xy, src="ocr", frame=frame)  # 템플릿과 모양이 다른 '확인' (어비스 도중 퀘스트 완료 창)
    if f(ui.get("dungeon_touch")):
        return Seen(TOUCH, frame=frame)
    if ocr and "dungeon_touch" not in skip:
        from .. import gamedata as gd
        from ..tasks.content import _touch_texts, has_word
        if has_word(gd.text("clear_touch"), *_touch_texts(bot, frame)):
            return Seen(TOUCH, src="ocr", frame=frame)
    if bot.at_main():
        return Seen(MAIN, frame=frame, idle=idle(bot))
    return Seen(UNKNOWN, frame=frame)
