"""상황별 대응 — 점검자가 상황(detect)을 보고 여기서 하나를 골라 처리한다.

태스크는 자기가 하는 일(Ctx)만 알려 준다: 무슨 일인지, 이 상황이면 그 일은 끝(finish_on), 태스크만 아는 판단(decide).
처리기는 한 번에 한 걸음만 한다. 돌려주는 값:
  str    — 한 일 (점검자가 기록하고 다시 본다)
  Finish — 이 일은 여기서 끝 (결과). 점검자가 남은 화면을 정리하고 태스크에 돌려준다
  None   — 이 상황에서 할 일이 없다 (메인 화면 등 — 태스크 몫)
"""
import time
from dataclasses import dataclass

from .. import gamedata as gd, ocr, situation as sit
from ..bot import StepTimeout
from . import detect as d

# 제작·가공 창 왼쪽 위 제목 칸 (1920 기준). 가공 시설 창은 제목이 '…가공' ('식재료 가공' 등)
CRAFT_TITLE_AREA, ALTER_TITLE = (80, 15, 420, 60), "가공"
ALTER_CARDS = (600, 160, 580, 560)  # 가공 시설 창 카드 목록 (x, y, w, h) — 카드 아래쪽에 이름


@dataclass
class Finish:
    result: str   # 'short' · 'alter' · 'dungeon' · 'stuck' …
    why: str = ""


def _esc(bot, n=1):
    for _ in range(n):
        bot.key("esc")
        bot.sleep(0.8, 1.0)


def _shot(bot, tag):
    return bot.snapshot(tag).name


# ---------------------------------------------------------------- 공통 (어느 태스크든)

def loading(bot, ctx, seen):
    bot.wait_loaded(10)
    return "로딩 대기"


def attendance(bot, ctx, seen):
    return sit.clear_attendance(bot, seen.frame)


def farewell(bot, ctx, seen):
    # 대화는 끝났는데(패킷) 작별 대사 화면('대화 기록')이 남음 — 메인 화면도 대화도 아니라 아무것도 안 하고 서 있었다
    # (2026-10-26 접속 단계 2분, 아르바이트 대화 조건 뒤 대기) → '대화 넘기기' 자리를 눌러 닫는다
    bot.click(tuple(bot.cfg["arbeit"]["dialog_next_xy"]))
    ctx.talked = True
    return "작별 대사 닫음"


def scene(bot, ctx, seen):
    # 어비스·던전 중이거나 뒤에서 도는 중이면 누르지 않고 연출이 끝나길 기다린다 (Bot.may_skip_scene)
    if bot.may_skip_scene():
        bot.click(seen.hit)
        return "장면 넘기기"
    bot.sleep(1.5, 2)
    return "연출 대기"


def dialog(bot, ctx, seen):
    """NPC 대화: 대사가 몇 마디든 '대화 넘기기' 자리를 누르면 넘어간다. 대사 내용으로 판단하지 않는다.
    날짜가 바뀐 뒤의 버튼 없는 첫 대사는 출석이다 (situation.clear_attendance)."""
    if not ctx.talk:
        return None
    if (done := sit.clear_attendance(bot, seen.frame)):
        return done
    if ctx.leave:
        return _leave_line(bot)
    if ctx.choose:
        from ..tasks.dialogue import menu_shown
        return _choose(bot, ctx, menu_shown(bot))
    if not ctx.menus:
        return _dialog_blocker(bot, seen)
    # 메뉴를 다루는 일 (아르바이트): 말을 건 직후 메뉴 버튼([수락]·[결과 보고])은 1~2초 늦게 뜬다 → 패킷이 대사라고 하면
    # 바로 넘기고, 아니면 조금 기다렸다 다시 본다. 메뉴가 뜨기 전에 넘기기를 눌러 수락을 놓쳤다 (2026-10-26 10:34 콜헨)
    # 버튼이 보이면 바로 Space. 넘길 대사('대화 넘기기' 버튼)가 남았으면 넘기고, 메뉴만 떠 있으면 오른쪽 위를 누르지 않고
    # 버튼이 그려지길 기다린다 — 메뉴 앞에서 넘기기 자리를 거듭 누르며 30초 가까이 수락을 못 했다 (2026-10-28 08:00:42~08:01:11)
    from ..tasks.dialogue import lines_left, menu_open, next_line
    ctx.talked = True
    a = bot.cfg["arbeit"]
    menu = menu_open(bot)
    end = time.monotonic() + (3 if menu is not False else 0)
    while True:
        for name, key, stage in ((a["report"], "arb_report", "결과 보고"), (a["accept"], "arb_accept", "수락")):
            if bot.exists(name):
                ctx.note(key, stage)
                bot.key("space")
                return stage
        if time.monotonic() > end or lines_left(bot):
            break
        bot.sleep(0.3, 0.4)
    if menu and not lines_left(bot):
        # 메뉴가 떠 있고(패킷) 넘길 대사가 없다 → 그림이 안 맞아도 버튼 줄 글자로 확인하고 Space ('수락'·'결과 보고' 에
        # Space 배지). 템플릿 점수가 문턱에 못 미쳐 16초·30초씩 수락을 못 한 적이 있다 (2026-10-28 08:43·09:07)
        texts = [ocr.nospace(t) for t, _, _ in ocr.find_texts(bot.frame(), gd.region("board_choices"))]
        for word, key, stage, tpl in (("arbeit_report", "arb_report", "결과 보고", a["report"]),
                                      ("arbeit_accept", "arb_accept", "수락", a["accept"])):
            if any(gd.text(word) in t for t in texts):
                # 그림으로 못 찾은 화면은 버튼 시험 화면 후보로 남긴다 (tools/button_fixture.py)
                bot.log.debug(f"'{stage}' 버튼을 그림으로 못 찾아 글자로 확인 → Space ({bot.snapshot('missed_' + tpl).name})")
                ctx.note(key, stage)
                bot.key("space")
                return stage
        bot.log.debug(f"메뉴는 떠 있는데 '수락'·'결과 보고' 버튼을 못 찾음 ({bot.snapshot('arbeit_menu').name})")
        return "메뉴 버튼 기다림"
    next_line(bot)
    return "대사 넘김"


def _choose(bot, ctx, shown):
    """선택지 중 ctx.choose 낱말이 든 것을 누른다. 선택지 버튼은 메뉴(패킷 · 없으면 CLI)가 켜진 뒤 조금 늦게 그려진다 →
    버튼 줄을 글자로 읽고, 원하는 것이 없으면 아무거나 누르지 않고 기다린다 (시간 상한은 태스크 몫). 고른 뒤 남은 대사는 넘긴다."""
    from ..tasks.dialogue import next_line
    if "chosen" not in ctx.events and (shown if shown is not None else bot._act(None).get("IsWaitingForSelection")):
        hit = next(((t, x, y) for t, x, y in ocr.find_texts(bot.frame(), gd.region(ctx.choose_region))
                    if ctx.choose in ocr.nospace(t)), None)
        if not hit:
            bot.sleep(1, 1.3)
            return "선택지 기다림"
        bot.click((hit[1], hit[2]))
        ctx.event("chosen")
        bot.sleep(1.2, 1.6)
        return f"선택지 '{hit[0]}'"
    next_line(bot)
    return "대사 넘김"


def _leave_line(bot):
    """대화를 마치는 중: 메뉴가 떠 있으면 ESC('대화 종료'), 대사(작별 인사 등 — ESC 로 안 넘어간다)면 넘기기 자리.
    메뉴는 패킷, 모르면 CLI(선택 기다림)로 본다."""
    from ..tasks.dialogue import menu_shown, next_line, step, wait_next
    shown = menu_shown(bot)
    if shown is None:
        shown = bool(bot._act(None).get("IsWaitingForSelection"))
    if not shown:
        next_line(bot)
        return "대사 넘김"
    before = step(bot)
    bot.key("esc")
    if wait_next(bot, before, 3) is None:
        bot.sleep(1.2, 1.6)
    return "대화 종료"


def _dialog_blocker(bot, seen):
    """기다리는 중에 끼어든 대화 (메뉴는 건드리지 않는다): 오른쪽 위 '대화 넘기기' 버튼이 보이거나, 패킷이 NPC 가 말을 걸어
    왔고 메뉴는 없다고 할 때 대사를 넘긴다. 주간 목표('모험가 길드의 정기 의뢰')를 그 주에 처음 채우면 조작이 돌아오는 순간
    에반이 찾아와 보상 이야기를 한다 — 나가기 뒤뿐 아니라 던전·사냥터 '다시 하기' 뒤 다음 판 안에서도 (사용자 2026-10-27).
    뒤에서 도는 중이면 클릭이 게임을 앞으로 가져오므로 스스로 넘어가길 기다리고, 30초 넘게 그대로일 때만 누른다."""
    from ..tasks.dialogue import _packet, menu_open

    hit = bot.skip_button(seen.frame)
    s = _packet(bot)
    # HUD 가 보이면 대화 창이 아직 안 열렸다 — 그때 '대화 넘기기' 자리를 누르면 HUD 버튼(어비스 나가기 근처)이 눌릴 수 있다
    talk = (s is not None and s.in_dialogue and menu_open(bot) is False
            and not (seen.frame is not None and bot.vision.find(seen.frame, bot.ui["main_hud"])))
    if not (hit and hit[0] == "dialog") and not talk:
        bot._skip_seen = None
        return None
    if bot.behind():
        since = getattr(bot, "_skip_seen", None)
        if since is None:
            bot._skip_seen = time.monotonic()
            return None
        if time.monotonic() - since < 30:
            return None
    bot._skip_seen = None
    if hit and hit[0] == "dialog":
        bot.click(hit[1])
        return "대화 넘기기"
    from ..tasks.dialogue import next_line
    next_line(bot)
    return "대사 넘김"


def confirm(bot, ctx, seen):
    """퀘스트 클리어 등의 '확인' — Space. 뒤에서 보낸 Space 가 안 먹어 같은 창이 그대로면 누른다."""

    if bot.background and time.monotonic() - getattr(bot, "_confirm_keyed", 0) < 10:
        bot.click(seen.hit)
    else:
        bot.key("space")
        bot._confirm_keyed = time.monotonic()
    if ctx.menus:
        bot.sleep(2, 2.5)
    ctx.event("confirmed")
    return "확인"


def touch(bot, ctx, seen):
    if bot.behind():
        bot.key("space")  # 뒤에서는 키로 (클릭은 게임을 앞으로 가져와야 한다)
    else:
        bot.click(tuple(bot.cfg["dungeon"]["touch_xy"]))
    return "화면 터치"


def menu_space(bot, ctx, seen):
    ctx.note(*(("arb_report", "결과 보고") if seen.what == d.REPORT else ("arb_accept", "수락")))
    bot.key("space")
    return "결과 보고" if seen.what == d.REPORT else "수락"


def deliver(bot, ctx, seen):
    """'전달하기' 창. '자동 넣기'(A)는 누를 때마다 켜졌다 꺼졌다 하는 스위치라 한 번만 누르고 채워지길 기다린다
    (두 번 누르면 도로 꺼져 0/5 로 남는다 — 2026-10-22). 몇 번 봐도 'Space' 표시가 없으면 정말 모자란 것."""
    a = bot.cfg["arbeit"]
    if bot.vision.find(seen.frame, a["deliver_ready"]):
        ctx.note("arb_deliver", "물품 전달")
        bot.key("space")
        ctx.n["deliver"] = 0
        bot.sleep(1, 1.3)
        return "물품 전달"
    tries = ctx.n.get("deliver", 0)
    if tries >= 4:
        _esc(bot)
        return Finish("short", f"전달할 물품이 모자람 → {_shot(bot, 'arbeit_short')}")
    if tries == 0:
        bot.key("a")
    ctx.n["deliver"] = tries + 1
    bot.sleep(1, 1.3)
    return "자동 넣기" if tries == 0 else "전달 물품 채워지길 기다림"


def dungeon_window(bot, ctx, seen):
    if (r := ctx.finish_on.get(d.DUNGEON_WINDOW)):
        return Finish(r, f"던전 창이 열림 ({seen.info.get('tab')}) → {_shot(bot, 'arbeit_dungeon')}")
    if ctx.keep_dungeon_window:
        return None  # 던전 숙제는 그 창에서 입장한다 (태스크 몫)
    _esc(bot)
    return "던전 창 닫음"


def dead(bot, ctx, seen):
    """쓰러짐 — '여기서 부활' 만 쓴다 (사용자 방침). 못 하면 이 일은 끝 ('dead' — 어비스는 나가서 처음부터)."""
    if not ctx.revive:
        return None
    from ..tasks.abyss import revive_here
    from ..tasks.content import ensure_auto
    if revive_here(bot):
        ensure_auto(bot)
        ctx.event("revived")
        return "여기서 부활"
    return Finish("dead", "'여기서 부활' 을 못 함")


# ---------------------------------------------------------------- 접속 직후 창 (어느 일에서든 뜰 수 있다)

NETWORK_TRIES, NETWORK_WINDOW = 3, 600  # 이 시간(초) 안에 '다시 시도하기' 를 이만큼 눌러도 또 뜨면 일시정지


def network(bot, ctx, seen):
    """'네트워크가 불안정' → '다시 시도하기'. NETWORK_WINDOW 안에 NETWORK_TRIES 번을 넘기면 사람에게 넘긴다 —
    F12 와 같은 일시정지 (사용자 2026-10-28). '시작 화면으로' 는 누르지 않는다."""
    now = time.monotonic()
    tries = [t for t in getattr(bot, "_network_tries", []) if now - t < NETWORK_WINDOW]
    shot = _shot(bot, "network")
    if len(tries) >= NETWORK_TRIES:
        bot.log.error(f"'네트워크가 불안정' 이 {len(tries)}번 다시 시도해도 또 뜸 → 일시정지 ({shot})")
        bot.stopper.by_key = True  # F12 일시정지와 같게 — F12 로 이어 한다
        bot.stopper.stopped.set()
        from ..bot import StopRequested
        raise StopRequested()
    bot._network_tries = tries + [now]
    bot.log.warning(f"'네트워크가 불안정' → 다시 시도하기 ({len(tries) + 1}/{NETWORK_TRIES}, {shot})")
    if seen.hit and seen.hit != (0, 0):
        bot.click(seen.hit)
    else:
        bot.key("space")  # 글자를 못 찾음 — 초록 기본 버튼이 '다시 시도하기'
    bot.sleep(5, 6)
    return "네트워크 다시 시도"


def stella(bot, ctx, seen):
    c = bot.cfg["login"]
    bot.click(tuple(c["stella_card_xy"]))  # 어느 카드든 상관없음
    try:
        bot.wait(c["stella_pick"], timeout=10)
    except StepTimeout:
        return "스텔라 픽 카드 누름"
    bot.sleep(0.5, 0.8)
    bot.key("space")
    return "스텔라 픽"


def notice(bot, ctx, seen):
    _esc(bot)
    return "공지 팝업 닫음"


def event_popup(bot, ctx, seen):
    bot.click(seen.hit)
    bot.sleep(0.6, 1.0)
    return "새 이벤트 창 닫음"


# ---------------------------------------------------------------- 던전·사냥터 끝 (ctx.reward)

def reward(bot, ctx, seen):
    """보상 화면: (추가 루팅) → again 버튼이 있으면 누르고 끝 (반복 플레이), 아니면 나가기(ESC).
    보상 연출이 길면 버튼이 늦게 뜬다 — 한 번만 보고 나가면 다음 판을 지도에서 다시 찾아간다."""
    if ctx.extra_loot and not ctx.n.get("loot"):
        from ..tasks.content import do_extra_loot
        bot.sleep(2, 3)  # 보상 연출
        do_extra_loot(bot, ctx.extra_loot)
        ctx.n["loot"] = 1
        return "추가 루팅"
    if ctx.again:
        try:
            bot.click(bot.wait(ctx.again, timeout=6, interval=0.5))
            return Finish("again", "보상 화면에서 다시 하기")
        except StepTimeout:
            bot.log.warning(f"보상 화면에 '다시 하기' 가 안 보임 → 나가서 지도로 ({_shot(bot, 'dungeon_no_retry')})")
            ctx.again = None
    elif not ctx.n.get("reward_wait"):
        ctx.n["reward_wait"] = 1
        bot.sleep(2, 3)  # 보상 연출
    bot.key("esc")
    return "보상 화면 나가기"


# ---------------------------------------------------------------- 일 (아르바이트·제작 — ctx.job)

def howto(bot, ctx, seen):
    """'필요한 아이템이 없습니다' → 물품 줄 → '구하는 방법' 맨 위(추천) → 게임이 필요한 만큼 채집하러 간다.
    채집 물품이 여러 개면 하나를 다 캐고 나서 이 창이 다시 뜬다 → 물품 하나마다 한 번 (국경 수비대 물자 보급은 세 가지)."""
    a = bot.cfg["arbeit"]
    items = ocr.find_texts(seen.frame, tuple(a["howto_area"]))
    rows = sorted(((t, x, y) for t, x, y in items if not any(w in t for w in gd.words("arbeit_howto_skip"))),
                  key=lambda r: r[2])
    # 채집으로도 구할 수 있는 가공품은 채집 줄을 고른다 — 가공 시설 줄이 맨 위일 수 있다 (깔끔 버섯 포자: 채집·약품 가공 시설·전리품)
    # (OCR 이 한 줄을 여러 조각으로 읽을 수 있어 같은 높이의 조각은 같은 줄로 본다)
    fy = [y for t, _, y in rows if any(w in t for w in gd.words("arbeit_howto_facility"))]
    other = [r for r in rows if all(abs(r[2] - y) > 30 for y in fy)]
    if ctx.alter and fy:  # 짧은 가공으로 하는 일 → 가공 시설 줄
        mine = [r for r in rows if any(abs(r[2] - y) <= 30 for y in fy)]
        ctx.note("arb_alter", "가공 시설로")
        bot.click((mine[0][1], mine[0][2]))
        bot.sleep(1.5, 2)
        return "구하는 방법 → 가공 시설"
    rows = [(x, y) for _, x, y in (other or rows)]
    if not rows or ctx.n.get("howto", 0) >= 5:
        _esc(bot, 2)
        return Finish("short", f"구하는 방법이 없음 → {_shot(bot, 'arbeit_short')}")
    ctx.n["howto"] = ctx.n.get("howto", 0) + 1
    ctx.note("arb_gather", "채집 중")
    bot.click(rows[0])
    bot.sleep(2, 2.5)
    fast_travel(bot)
    ctx.event("gather")
    return "채집하러 감 (구하는 방법 맨 위)"


def item_missing(bot, ctx, seen):
    if (why := ctx.decide.get(d.ITEM_MISSING, lambda *_: None)(bot, ctx, seen)):
        _esc(bot)
        return Finish("short", why)
    ox, oy = bot.cfg["arbeit"]["item_row_from_title"]
    bot.click((seen.hit.x + ox, seen.hit.y + oy))
    bot.sleep(1.2, 1.5)
    return "모자란 물품 줄 → 구하는 방법"


def item_use(bot, ctx, seen):
    """아이템을 쓰는 일 ('행운의 편지' 등): 진행하기를 누르면 게임이 가방을 열고 그 아이템에 '사용하기' 를 띄운다 → Space.
    모르는 화면으로 보고 두 번 진행하기만 다시 누르다 막힘으로 끝냈다 (2026-10-28)."""
    ctx.n["item_use"] = ctx.n.get("item_use", 0) + 1
    if ctx.n["item_use"] > 3:
        _esc(bot)
        return Finish("stuck", f"'사용하기' 를 눌러도 그대로 → {_shot(bot, 'arbeit_item_use')}")
    ctx.note("arb_item_use", "아이템 사용")
    bot.key("space")
    bot.sleep(1.5, 2)
    return "아이템 사용"


def _short_toast(bot) -> bool:
    """방금 누른 버튼 뒤 '재료가 부족합니다.' 가 떴나."""
    try:
        bot.wait(bot.cfg["arbeit"]["craft_short_toast"], timeout=2.5, interval=0.3)
        return True
    except StepTimeout:
        return False


def alter(bot, ctx, seen):
    """가공 시설 앞 '가공하기'. 짧은 가공(ctx.alter — 아르바이트가 정함)만 한다: Space → 끝날 때까지(CLI get_altering_works)
    → 모두 받기(Space) → 가공 완료 확인(Space) → 창 닫기. 재료가 모자라면 포기 (사용자 규칙 2026-10-30). 그 밖의 가공은 건너뛴다."""
    if not ctx.alter:
        _esc(bot)
        return Finish("alter", f"가공이 필요한 일 → {_shot(bot, 'arbeit_alter')}")
    ctx.n["alter"] = ctx.n.get("alter", 0) + 1
    if ctx.n["alter"] > 6:
        return Finish("stuck", f"가공을 거듭해도 일이 안 끝남 → {_shot(bot, 'arbeit_alter')}")
    ctx.note("arb_alter", "가공")
    bot.key("space")
    if _short_toast(bot):
        _esc(bot)
        return Finish("alter_short", f"가공 재료 부족 → {_shot(bot, 'arbeit_alter')}")
    names = set(ctx.alter)
    end = time.monotonic() + bot.cfg["arbeit"].get("alter_wait", 180)
    while True:
        bot.sleep(3, 3.5)
        data = bot.state.query("get_altering_works") or {}
        works = [w for w in (data.get("works") or []) if w.get("DisplayName") in names]
        if works and all(w.get("IsCompleted") for w in works):
            break
        if time.monotonic() > end:
            _esc(bot)
            return Finish("stuck", f"가공이 끝나지 않음 → {_shot(bot, 'arbeit_alter')}")
    bot.key("space")  # 모두 받기
    bot.sleep(2, 2.5)
    bot.key("space")  # 가공 완료 — 확인
    bot.sleep(1.5, 2)
    _esc(bot)
    ctx.note("arb_alter", "가공 받음")
    return "가공 → 받기"


def _alter_go(bot, ctx, seen):
    """가공 시설 창 첫 화면 (아르바이트가 요구하는 가공품 카드만 보인다) → 카드 → '가공하러 가기'(Space) → 빠른 이동."""
    ctx.n["alter_go"] = ctx.n.get("alter_go", 0) + 1
    if ctx.n["alter_go"] > 4:
        return Finish("stuck", f"가공 시설 창에서 나아가지 못함 → {_shot(bot, 'arbeit_alter')}")
    # 카드는 제작 창과 달리 '설비로 이동' 아래가 아니라 오른쪽 목록에 있다 → 카드 아래 이름 글자를 찾아 그 카드를 누른다
    cards = ocr.find_texts(seen.frame, ALTER_CARDS)
    if not ctx.alter:
        # 조건을 모르고 온 일 (추적 칸에 없던 일을 이어 함) → 보이는 카드 이름이 짧은 가공이면 가공한다
        ctx.alter = tuple(t for t, _, _ in cards if ctx.alter_ok([t]))
        if not ctx.alter:
            _esc(bot)
            return Finish("alter", f"가공 시설 창 → {_shot(bot, 'arbeit_alter')}")
    names = {ocr.nospace(n) for n in ctx.alter}
    hit = next(((x, y) for t, x, y in cards if ocr.nospace(t) in names), None)
    if not hit:
        return Finish("stuck", f"가공 시설 창에서 가공품 카드를 못 찾음 → {_shot(bot, 'arbeit_alter')}")
    bot.click((hit[0], hit[1] - 60))
    bot.sleep(1.2, 1.5)
    ctx.note("arb_alter", "가공하러 감")
    bot.key("space")
    if _short_toast(bot):
        _esc(bot)
        return Finish("alter_short", f"가공 재료 부족 → {_shot(bot, 'arbeit_alter')}")
    bot.sleep(0.5, 1)
    fast_travel(bot)
    return "가공하러 감"


def craft_transfer(bot, ctx, seen):
    # 가방에 모자란 재료를 보관함에서 가져올지 묻는 창 (비용 표시가 있다) → 확인(Space)
    ctx.note("arb_craft", "재료 전송 (보관함에서)")
    bot.key("space")
    bot.sleep(1.5, 2)
    return "재료 전송"


def craft_go(bot, ctx, seen):
    """제작: 재료는 숫자를 읽지 않고 그냥 Space — 모자라면 게임이 '재료가 부족합니다.' 를 띄우고 아무것도 하지 않는다."""
    a = bot.cfg["arbeit"]
    ctx.note("arb_craft", "제작")
    bot.key("space")
    try:
        bot.wait(a["craft_short_toast"], timeout=2.5, interval=0.3)
        _esc(bot)
        return Finish("short", f"제작 재료 부족 → {_shot(bot, 'arbeit_craft')}")
    except StepTimeout:
        pass
    bot.sleep(0.5, 1)
    fast_travel(bot)
    return "제작"


def craft(bot, ctx, seen):
    """제작 창 첫 화면: 아르바이트가 요구하는 물품 하나만 보인다 → 그 카드. 가공 시설 창('식재료 가공' 등)도 첫 화면이 같아
    가공 칸이 다 찬 채면 '가공하기' 가 안 떠 헤맸다 (2026-10-26) → 창 제목으로 가공을 알아본다."""
    if any(t.endswith(ALTER_TITLE) for t, _, _ in ocr.find_texts(seen.frame, CRAFT_TITLE_AREA)):
        if ctx.alter or ctx.alter_ok:
            return _alter_go(bot, ctx, seen)
        _esc(bot)
        return Finish("alter", f"가공 시설 창 → {_shot(bot, 'arbeit_alter')}")
    ctx.n["craft"] = ctx.n.get("craft", 0) + 1
    if ctx.n["craft"] > 4:
        return Finish("stuck", f"제작 창 버튼을 알아보지 못함 → {_shot(bot, 'arbeit_craft')}")
    ox, oy = bot.cfg["arbeit"]["craft_item_from_list"]
    bot.click((seen.hit.x + ox, seen.hit.y + oy))
    bot.sleep(1.2, 1.5)
    return "제작 물품 고름"


def fast_travel(bot) -> bool:
    """먼 곳으로 자동 이동 중이면 빠른 이동 키(T)를 누른다. 눌렀으면 True."""
    key = bot.cfg["game"].get("fast_travel_key")
    if key and bot.fast_travel_ok():
        bot.log.info("빠른 이동")
        bot.key(key)
        return True
    return False


# 어느 일이든 (기다리는 중에 끼어든 창 포함)
BASE = {d.LOADING: loading, d.ATTENDANCE: attendance, d.FAREWELL: farewell, d.SCENE: scene, d.DIALOG: dialog,
        d.CONFIRM: confirm, d.TOUCH: touch, d.DEAD: dead, d.STELLA: stella, d.NOTICE: notice, d.EVENT_POPUP: event_popup,
        d.NETWORK: network}
# NPC 메뉴·전달·던전 창을 다루는 일 (ctx.menus — 아르바이트·정리). 기다리는 중의 정리는 메뉴를 누르지 않는다
MENUS = {d.REPORT: menu_space, d.ACCEPT: menu_space, d.DELIVER: deliver, d.DUNGEON_WINDOW: dungeon_window}
# 채집·제작·가공 창 (ctx.job — 아르바이트 한 건을 하는 중)
JOB = {d.HOWTO: howto, d.ITEM_MISSING: item_missing, d.ITEM_USE: item_use, d.ALTER: alter, d.CRAFT_TRANSFER: craft_transfer,
       d.CRAFT_GO: craft_go, d.CRAFT: craft}


# 던전·사냥터를 끝내는 중 (ctx.reward) — 어비스 반복의 보상 화면은 어비스가 따로 본다
DUNGEON = {d.REWARD: reward}


def pick(ctx, what):
    if (ctx.choose or ctx.leave) and what in (d.REPORT, d.ACCEPT):
        return dialog  # 고를 선택지가 따로 있거나 마치는 대화 — Space(기본 선택지)를 누르지 않는다
    return (BASE.get(what) or (MENUS.get(what) if ctx.menus else None) or (JOB.get(what) if ctx.job else None)
            or (DUNGEON.get(what) if ctx.reward else None))
