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
    if ctx.choose:
        from ..tasks.dialogue import menu_shown
        return _choose(bot, ctx, menu_shown(bot))
    if not ctx.menus:
        return _dialog_blocker(bot, seen)
    # 메뉴를 다루는 일 (아르바이트): 말을 건 직후 메뉴 버튼([수락]·[결과 보고])은 1~2초 늦게 뜬다 → 패킷이 대사라고 하면
    # 바로 넘기고, 아니면 조금 기다렸다 다시 본다. 메뉴가 뜨기 전에 넘기기를 눌러 수락을 놓쳤다 (2026-10-26 10:34 콜헨)
    from ..tasks.dialogue import menu_open, next_line
    ctx.talked = True
    if menu_open(bot) is False:
        next_line(bot)
        return "대사 넘김"
    bot.sleep(1.5, 2)
    a = bot.cfg["arbeit"]
    for name, key, stage in ((a["report"], "arb_report", "결과 보고"), (a["accept"], "arb_accept", "수락")):
        if bot.exists(name):
            ctx.note(key, stage)
            bot.key("space")
            return stage
    next_line(bot)
    return "대사 넘김"


def _choose(bot, ctx, shown):
    """선택지 중 ctx.choose 낱말이 든 것을 누른다. 선택지 버튼은 메뉴(패킷 · 없으면 CLI)가 켜진 뒤 조금 늦게 그려진다 →
    버튼 줄을 글자로 읽고, 원하는 것이 없으면 아무거나 누르지 않고 기다린다 (시간 상한은 태스크 몫). 고른 뒤 남은 대사는 넘긴다."""
    from ..tasks.dialogue import next_line
    if "chosen" not in ctx.events and (shown if shown is not None else bot._act(None).get("IsWaitingForSelection")):
        hit = next(((t, x, y) for t, x, y in ocr.find_texts(bot.frame(), gd.region("board_choices"))
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


def _dialog_blocker(bot, seen):
    """기다리는 중에 끼어든 대화 (메뉴는 건드리지 않는다): 오른쪽 위 '대화 넘기기' 버튼이 보일 때만 누른다.
    뒤에서 도는 중이면 클릭이 게임을 앞으로 가져오므로 스스로 넘어가길 기다리고, 30초 넘게 그대로일 때만 누른다."""

    hit = bot.skip_button(seen.frame)
    if not hit or hit[0] != "dialog":
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
    bot.click(hit[1])
    return "대화 넘기기"


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
    rows = sorted(((x, y) for t, x, y in items if not any(w in t for w in gd.words("arbeit_howto_skip"))), key=lambda r: r[1])
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


def alter(bot, ctx, seen):
    # 가공은 시간이 걸려(수십 초~) 기다리지 않고 건너뛴다 (사용자 규칙)
    _esc(bot)
    return Finish("alter", f"가공이 필요한 일 → {_shot(bot, 'arbeit_alter')}")


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
        d.CONFIRM: confirm, d.TOUCH: touch, d.DEAD: dead}
# NPC 메뉴·전달·던전 창을 다루는 일 (ctx.menus — 아르바이트·정리). 기다리는 중의 정리는 메뉴를 누르지 않는다
MENUS = {d.REPORT: menu_space, d.ACCEPT: menu_space, d.DELIVER: deliver, d.DUNGEON_WINDOW: dungeon_window}
# 채집·제작·가공 창 (ctx.job — 아르바이트 한 건을 하는 중)
JOB = {d.HOWTO: howto, d.ITEM_MISSING: item_missing, d.ALTER: alter, d.CRAFT_TRANSFER: craft_transfer,
       d.CRAFT_GO: craft_go, d.CRAFT: craft}


# 던전·사냥터를 끝내는 중 (ctx.reward) — 어비스 반복의 보상 화면은 어비스가 따로 본다
DUNGEON = {d.REWARD: reward}


def pick(ctx, what):
    if ctx.choose and what in (d.REPORT, d.ACCEPT):
        return dialog  # 고를 선택지가 따로 있는 대화 — Space(기본 선택지)를 누르지 않는다
    return (BASE.get(what) or (MENUS.get(what) if ctx.menus else None) or (JOB.get(what) if ctx.job else None)
            or (DUNGEON.get(what) if ctx.reward else None))
