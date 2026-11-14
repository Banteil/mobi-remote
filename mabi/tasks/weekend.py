"""주말 퀘스트 (주간 숙제): 토·일요일에만 생기는 이벤트 퀘스트 '주말에는 어비스!'(어비스 클리어) · '주말에는 레이드!'(레이드
클리어)를 캐릭터마다 깬다. 한 캐릭터가 어비스 → 레이드를 마치면 다음 캐릭터로 간다 (캐릭터를 도는 것은 일일 숙제 실행기 runner).

판은 어비스·레이드 반복(abyss.AbyssRepeat · raid.RaidRepeat)을 그대로 쓴다 — 입장·매칭·부활·수리·보상·나가기가 같다.
세는 것은 들어간 판이 아니라 클리어한 판이다 (반복이 결과 패킷·화면으로 센다. 쓰러져 나오거나 시간을 넘긴 판은 다시 들어간다).
어느 던전·레이드를 어떤 난이도·방식(혼자하기·함께하기)으로 돌지는 주간 숙제 탭에서 고른다 → 카드가 [weekend.abyss] ·
[weekend.raid] 칸을 덮어쓴다. 몇 판인지(runs)는 퀘스트가 요구하는 수 — 퀘스트 창에서 진행도를 읽으면 남은 만큼만.

깼는지 (quest_state): HUD 추적 칸(CLI get_quests)에 있으면 아직 안 깬 것, 거기 없으면 퀘스트 창(J) 이벤트 탭의 카드에
'진행하기' 가 있나. 들어가기 전에 보고 이미 깼으면 넘기고, 다 돈 뒤에도 본다 — 카드가 남아 있으면 한 판씩 더 (EXTRA 번까지).
주말인지는 게임 날짜(오전 6시에 바뀜)의 요일로 본다. 주말이 아니면 작업 큐 카드는 기다렸다가 토요일에 돈다 (tasks.SEASON).
"""
import re
from contextlib import contextmanager
from datetime import datetime
from typing import NamedTuple

from .. import gamedata as gd, keys
from ..bot import Bot
from ..exceptions import CannotProceed
from ..profile import RESET_HOUR
from . import abyss, raid, ui_text
from .steps import list_views

# 종류 → (숙제 이름, 장소 칸, 퀘스트 이름 글자 키 data/ui.json)
KINDS = {
    "abyss": ("주말 어비스", "dungeon", "weekend_abyss_quest"),
    "raid": ("주말 레이드", "raid", "weekend_raid_quest"),
}
EXTRA = 2            # 정한 판 수를 다 깼는데 퀘스트가 남았으면 더 도는 판 수 (한 판씩)
QUEST_SCROLL = 3     # 퀘스트 창 목록을 한 번에 내리는 휠 칸 수
QUEST_SCROLLS = 8    # 최대 몇 번 내려가며 볼지
# 카드 제목 아래로 같은 카드의 '진행하기'·진행도를 찾는 높이. 고른(펼친) 카드는 목표 줄·답례까지 보여 제목→버튼이 276,
# 접힌 카드는 188 (2026-11-14 화면). 다음 카드의 버튼은 이보다 아래라 섞이지 않는다
CARD_H = 400
PROGRESS = re.compile(r"(\d+)\s*/\s*(\d+)")


def not_now(now: datetime | None = None) -> str:
    """주말 퀘스트가 없는 날이면 그 까닭, 주말(게임 날짜 토·일요일)이면 빈 문자열."""
    from datetime import timedelta
    day = (now or datetime.now()) - timedelta(hours=RESET_HOUR)
    return "" if day.weekday() >= 5 else "주말 퀘스트는 토·일요일(오전 6시부터 월요일 오전 6시 전까지)에만 있음"


# ---- 퀘스트 창

class Quest(NamedTuple):
    open: bool | None       # 퀘스트 창에 카드가 있나 (있으면 아직 안 깸) — 창을 못 열었으면 None
    done: int | None = None  # 진행도 'n/m' 의 n (못 읽었으면 None)
    goal: int | None = None  # 진행도 'n/m' 의 m

    def left(self, default: int) -> int:
        """남은 판 수 — 진행도를 읽었으면 그것으로, 아니면 default."""
        if self.done is not None and self.goal:
            return max(0, self.goal - self.done)
        return default


def _progress(items, title_y: int) -> tuple[int, int] | tuple[None, None]:
    """퀘스트 창에서 읽은 글자들 중 제목 아래 카드 안의 첫 'n/m'."""
    for t, _, y in sorted(items, key=lambda i: i[2]):
        if 0 <= y - title_y < CARD_H and (m := PROGRESS.search(t)):
            n, g = int(m.group(1)), int(m.group(2))
            if 0 < g <= 99 and n <= g:
                return n, g
    return None, None


def _from_tracker(bot: Bot, title: str) -> Quest:
    """HUD 퀘스트 추적 칸(CLI get_quests)에 이 퀘스트가 있으면 아직 안 깬 것 — 목표 줄에 'n/m' 이 있으면 진행도도.
    없다고 깬 것은 아니다 (창이 열렸거나 이동·로딩 중엔 추적 칸이 통째로 비고, 추적을 뺄 수도 있다) → 그땐 open=None."""
    from .. import richtext
    qs = bot.state.query("get_quests") if bot.state.available() else None
    for row in qs or []:
        if isinstance(row, dict) and ui_text.norm(title) in ui_text.norm(richtext.strip(row.get("QuestTitle", ""))):
            for o in row.get("Objectives") or []:
                if isinstance(o, dict) and (m := PROGRESS.search(richtext.strip(o.get("Description", "")))):
                    return Quest(True, int(m.group(1)), int(m.group(2)))
            return Quest(True)
    return Quest(None)


def _card_go(items, title_y: int) -> bool:
    """제목 아래 같은 카드 안에 '진행하기' 버튼 글자가 있나."""
    go = ui_text.norm(gd.text("questwin_go"))
    return any(0 < y - title_y < CARD_H and ui_text.norm(t) == go for t, _, y in items)


def _from_window(bot: Bot, title: str) -> Quest:
    """퀘스트 창(J) 이벤트 탭에서 카드를 찾는다 (2026-11-14 사용자 화면: 카드마다 제목·'N일 N시간 남음'·설명·'진행하기').
    카드에 '진행하기' 가 있으면 아직 안 깬 것. 목록 끝까지 그런 카드가 없으면(카드가 없거나 버튼이 없음) 깬 것.
    이벤트 탭이 아예 없어도(이벤트 퀘스트를 다 깸) 깬 것. 창을 못 열면 open=None."""
    from ..ocr import find_texts
    bot.to_main()
    bot.key(keys.of(bot, "quest"))
    tab = ui_text.wait(bot, gd.text("questwin_event_tab"), gd.region("questwin_tabs"), timeout=6)
    if not tab:
        # 이벤트 퀘스트를 다 깨면 이벤트 탭이 통째로 없어진다 (2026-11-14 실기: 주말 두 퀘스트를 다 깬 캐릭터는 탭 줄이
        # 지도·퀘스트·아르바이트뿐). 창은 열렸는데(아르바이트 탭 글자가 보임) 이벤트 탭만 없으면 깬 것
        opened = ui_text.match(find_texts(bot.frame(), gd.region("questwin_tabs")), gd.text("arbeit_tab"), exact=False)
        bot.to_main()
        if opened:
            bot.log.info("퀘스트 창에 이벤트 탭이 없음 → 이벤트 퀘스트가 남지 않음")
            return Quest(False)
        bot.log.warning(f"퀘스트 창 이벤트 탭을 찾지 못해 '{title}' 를 확인 못 함 → {bot.snapshot('weekend_quest').name}")
        return Quest(None)
    bot.click(tab)
    bot.sleep(1, 1.5)
    area = gd.region("questwin_list")
    found = Quest(False)
    for _ in list_views(bot, area, tuple(bot.cfg["tribute"]["list_scroll_at"]), QUEST_SCROLL, QUEST_SCROLLS):
        items = find_texts(bot.frame(), area)
        hit = ui_text.match(items, title, exact=False)
        if not hit:
            continue
        if _card_go(items, hit[2]):
            found = Quest(True, *_progress(items, hit[2]))
            break
        if hit[2] < area[1] + area[3] - CARD_H:  # 카드가 다 보이는데 '진행하기' 가 없다 (아래로 잘렸으면 더 내려서 본다)
            break
    bot.to_main()
    return found


def quest_state(bot: Bot, kind: str) -> Quest:
    """이 종류의 주말 퀘스트를 아직 안 깼나 — HUD 추적 칸(CLI)에 있으면 그것으로 (창을 안 열어도 된다), 아니면 퀘스트 창 이벤트 탭."""
    title = gd.text(KINDS[kind][2])
    q = _from_tracker(bot, title)
    where = "추적 칸"
    if q.open is None:
        q, where = _from_window(bot, title), "이벤트 탭"
    bot.log.info(f"주말 퀘스트 '{title}' ({where}): " + (
        "확인 못 함" if q.open is None else "깸 (진행할 카드 없음)" if not q.open else
        "아직 안 깸" + (f" — 진행도 {q.done}/{q.goal}" if q.done is not None else "")))
    return q


# ---- 반복

@contextmanager
def _kept(bot: Bot):
    """반복이 바꾼 봇 설정(뒤에서 돌기·연출 넘기기)을 숙제가 끝나면 되돌린다 — 다음 숙제·캐릭터 접속은 예전처럼."""
    was = (bot.background, bot.scene_skip)
    try:
        yield
    finally:
        bot.background, bot.scene_skip = was


def picked(cfg: dict, kind: str) -> dict:
    """이번에 돌 것 — [kind] 칸(어비스·레이드 탭 설정)에 [weekend.kind] 칸(주간 숙제 탭에서 고른 것)을 덮는다."""
    return {**cfg[kind], **cfg["weekend"][kind], "slot": 0, "minutes": 0}


def _repeat(bot: Bot, cfg: dict, kind: str, runs: int) -> dict:
    sub = {**cfg, kind: {**picked(cfg, kind), "runs": runs}}
    cls = abyss.AbyssRepeat if kind == "abyss" else raid.RaidRepeat
    with _kept(bot):
        return cls(bot, sub, runs=runs).run()


def run(bot: Bot, cfg: dict, kind: str) -> str:
    name, place, _ = KINDS[kind]
    if (why := not_now()):
        raise CannotProceed(why)
    pick = picked(cfg, kind)
    target = f"{pick[place]} {pick.get('difficulty', '')} {'혼자하기' if pick.get('mode') == 'solo' else '함께하기'}"
    q = quest_state(bot, kind)
    if q.open is False:
        bot.verified = True
        return "이미 깸 (퀘스트 창에 없음)"
    runs = q.left(int(pick.get("runs") or 1))
    if runs <= 0:  # 진행도는 다 찼는데 카드가 남음 (완료 창을 아직 안 넘김 등) — 한 판 돌아 본다
        runs = 1
    bot.log.info(f"{name}: {target} — 클리어 {runs}판" + (f" (진행도 {q.done}/{q.goal})" if q.done is not None else ""))
    total = 0
    for extra in range(EXTRA + 1):
        total += _repeat(bot, cfg, kind, runs)["clears"]
        q = quest_state(bot, kind)
        if q.open is False:
            bot.verified = True
            return f"{target} 클리어 {total}판 — 퀘스트 깸"
        if q.open is None:
            return f"{target} 클리어 {total}판 (퀘스트 창을 못 봐 확인 못 함)"
        if extra < EXTRA:
            runs = max(1, q.left(1))
            bot.log.warning(f"{name}: {total}판 클리어했는데 퀘스트가 남아 있음 → {runs}판 더")
    raise CannotProceed(f"{target} {total}판 클리어했지만 퀘스트 창에 '{gd.text(KINDS[kind][2])}' 가 남아 있음")


def run_abyss(bot: Bot, cfg: dict) -> str:
    return run(bot, cfg, "abyss")


def run_raid(bot: Bot, cfg: dict) -> str:
    return run(bot, cfg, "raid")


def verify(kind: str):
    """퀘스트 창에 카드가 없으면 끝 (창을 못 열었으면 끝났다고 하지 않는다)."""
    return lambda bot, cfg: quest_state(bot, kind).open is False


def choices(cfg: dict) -> dict:
    """주간 숙제 탭 '주말 어비스·레이드' 칸이 고를 수 있는 것 — 이번 주 어비스(방식마다 열린 난이도)·레이드, 기본값([weekend])."""
    return {"abyss": {m: gd.abysses(mode=m) for m in ("party", "solo")},
            "raids": raid.raids(),
            "pick": {k: {key: cfg["weekend"][k].get(key) for key in (KINDS[k][1], "difficulty", "mode")} for k in KINDS},
            "runs": {k: int(cfg["weekend"][k].get("runs") or 1) for k in KINDS},
            "notNow": not_now()}
