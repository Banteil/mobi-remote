"""던전/사냥터 공용 실행 루틴. 개별 숙제 태스크가 조합해서 사용한다.

던전 진행 상태는 CLI get_activity 의 Dungeon.State 로 판단한다.
  NotInDungeon → (입장) InProgress → Cleared → (보상 화면에서 나가기) NotInDungeon
입장하면 자동 전투가 저절로 켜진다 (던전, 사냥터, 검은 구멍 모두).
우하단 ASSIST(H)는 자동 스킬 사용 여부라 켜져 있어야 하므로 절대 누르지 않는다. 클리어 후 화면 흐름:
  '화면을 터치해 주세요' → 보상 연출('장면 넘기기') → 보상 화면(추가 루팅 Space / 나가기 ESC)
  → (아르바이트로 들어온 경우) '퀘스트 클리어' 확인 → 필드
추가 루팅은 요일 던전에만 있다 (다른 던전, 심층 던전, 사냥터에는 없음).
"""
import difflib
import re
import time
from typing import Callable

from .. import gamedata as gd
from ..bot import Bot, StepTimeout


def ensure_auto(bot: Bot) -> None:
    """자동 전투가 꺼져 있으면 켠다."""
    ui = bot.ui
    if bot.vision.has(ui["auto_off"]) and bot.click_if(ui["auto_off"]):
        bot.log.info("자동 전투 켬")


def handle_death(bot: Bot) -> bool:
    """쓰러지면 '여기서 부활' 만 쓴다 (여신상 부활은 쓰지 않는다 — 사용자 방침). 부활했으면 True."""
    from .abyss import revive_here  # abyss 가 이 모듈을 가져다 쓴다
    if revive_here(bot):
        bot.log.warning("사망 → 여기서 부활")
        ensure_auto(bot)
        return True
    return False


# 퀘스트 창(J) 아래 탭 줄(지도·퀘스트·아르바이트·이벤트) 윗선 (1920 기준). 카드 버튼이 이 줄에 반쯤 걸쳐 보일 때
# 그 자리를 누르면 버튼 대신 탭('이벤트')이 눌린다 — 공물 던전(2026-10-24 16:48)·알바(17:42, 18:10)에서 따로 터졌다.
# 퀘스트 창의 버튼은 모두 questwin_buttons / questwin_text_ok 로 걸러서 누른다 (안 보이면 목록을 내려서 다시)
QUESTWIN_TAB_BAR_Y = 950
# 자동 이동이 끝난 뒤 도착 화면(던전 창 등)이 뜰 때까지 기다리는 상한 (초). 빠른 이동 뒤 걸어서 들어가는 시간까지 넉넉히
ARRIVE_GRACE = 45
# 퀘스트 창 → 진행하기 → 이동 단계가 막히면 처음부터 다시 해 보는 횟수. 입구에 사람이 몰려 창이 안 뜨거나
# 창이 지난 스크롤 자리로 열리는 등 한 번 더 하면 되는 일이 많다 (2026-10-26)
STEP_RETRIES = 2


def with_retries(bot: Bot, what: str, fn: Callable, retries: int = STEP_RETRIES):
    """fn() 을 하고, 막히면(StepTimeout·RuntimeError) 메인 화면으로 돌아가 retries 번까지 다시 한다."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except (StepTimeout, RuntimeError) as e:
            if attempt == retries:
                raise
            bot.log.warning(f"{what} 막힘 → 다시 시도 ({attempt + 1}/{retries}): {e}")
            bot.to_main()


def questwin_buttons(bot: Bot, name: str, region=None) -> list:
    """퀘스트 창에서 템플릿 name 버튼 중 탭 줄에 걸치지 않고 다 보이는 것 (위에서부터)."""
    return sorted((b for b in bot.find_all(name, region=region) if b.y + b.h <= QUESTWIN_TAB_BAR_Y), key=lambda b: b.y)


def questwin_text_ok(y: int) -> bool:
    """OCR 로 찾은 버튼 글자(가운데 y)가 탭 줄에 걸치지 않았나 (버튼 높이 약 60)."""
    return y <= QUESTWIN_TAB_BAR_Y - 30


def open_arbeit_tab(bot: Bot) -> None:
    """퀘스트 창(J)을 열고 아르바이트 탭으로."""
    ui = bot.ui
    bot.to_main()
    bot.hover_off()  # 지난번에 누른 탭 위에 커서가 남아 있으면 탭 그림이 커져 안 맞는다
    bot.key("j")
    try:
        bot.click(ui["questwin_tab_arbeit"], timeout=5)
    except StepTimeout:
        # 퀘스트 탭 목록이 길면 맨 아래 카드의 '진행하기' 버튼이 탭 아이콘 위에 겹쳐 그림이 안 맞는다
        # (2026-10-22 '함께하는 대모험' 카드) → 탭 글자 '아르바이트' 를 읽어 확인하고 탭 자리를 누른다
        from ..ocr import find_texts
        hit = next(((tx, ty) for t, tx, ty in find_texts(bot.frame(), gd.region("arbeit_tab")) if gd.text("arbeit_tab") in t), None)
        if not hit:
            raise StepTimeout(f"퀘스트 창의 아르바이트 탭을 찾지 못함 → {bot.snapshot('questwin').name}")
        bot.log.debug(f"아르바이트 탭 그림이 가려짐 → 탭 글자 {hit} 를 누름")
        bot.click(hit)  # 아이콘 쪽은 겹친 '진행하기' 버튼이라 글자를 누른다
    bot.sleep(1, 1.5)



def open_guide(bot: Bot) -> None:
    """'/' 콘텐츠 가이드를 연다. 지역 이동 직후 등에는 키가 무시되기도 해서 몇 번 다시 누른다."""
    for _ in range(3):
        bot.to_main()
        bot.key("/")
        try:
            bot.wait(bot.ui["guide_title"], timeout=6)
            bot.sleep(1, 1.5)
            return
        except StepTimeout:
            bot.log.debug("콘텐츠 가이드가 열리지 않아 다시 누름")
            bot.sleep(2, 3)
    raise CannotProceed(f"콘텐츠 가이드(/)가 열리지 않음 → {bot.snapshot('guide').name}")


def daily_achieved(bot: Bot, label: str) -> bool:
    """'/' 콘텐츠 가이드 왼쪽 위 '일일 달성'에서 label(콘텐츠 이름 템플릿) 아이콘에 초록 체크가 있는지.
    체크는 이름 글자 왼쪽 아래(아이콘 오른쪽 아래 모서리)에 붙는다."""
    g = bot.cfg["guide"]
    open_guide(bot)
    m = bot.find(label, region=g["daily_panel"])
    if not m:
        bot.to_main()
        raise CannotProceed(f"콘텐츠 가이드 일일 달성에 '{label}' 이 없음 → {bot.snapshot('guide').name}")
    dx, dy = g["check_offset"]
    x, y = m.x + dx, m.y + dy
    patch = bot.frame()[y - 5:y + 5, x - 5:x + 5].reshape(-1, 3).astype(int)
    green = ((patch[:, 1] > 120) & (patch[:, 2] < 120) & (patch[:, 0] < 160)).mean()
    bot.to_main()
    return green > 0.3


def open_guide_card(bot: Bot, card: str) -> bool:
    """'/' 콘텐츠 가이드의 일일 콘텐츠에서 card(카드 제목 템플릿)의 '바로 가기'를 누른다.
    오늘 끝낸 콘텐츠는 카드가 사라지므로 카드가 없으면 False (= 이미 완료)."""
    ui = bot.ui
    open_guide(bot)
    title = bot.find(card)
    if not title:
        bot.to_main()
        return False
    # 같은 카드의 '바로 가기' = 제목보다 아래, 카드 폭(약 650px) 안에 있는 버튼
    go = [b for b in bot.find_all(ui["guide_go"]) if b.y > title.y and 0 <= b.x - title.x < 650]
    if not go:
        raise RuntimeError(f"콘텐츠 가이드 '{card}' 카드의 바로 가기를 찾지 못함")
    bot.click(go[0])
    return True


def wait_until(bot: Bot, pred: Callable[[], bool], timeout: float, interval: float = 3.0, what: str = "") -> None:
    end = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > end:
            raise StepTimeout(f"{timeout:.0f}s 안에 {what or '조건'} 충족 안 됨")
        bot.sleep(interval)


def game_space(bot: Bot) -> str:
    """지금 장소 이름. 패킷이 알면 맵 진입 때 온 맵 이름 (검은 구멍은 '지하로 뚫린 검은 구멍_<사냥터>'),
    로딩 중이거나 모르면 CLI get_current_environment (로딩 중엔 답이 없어 '')."""
    if bot.map_loading() is False and bot.packets.state.channel_name:
        return bot.packets.state.channel_name
    env = bot.state.query("get_current_environment") if bot.state.available() else None
    return (env or {}).get("GameSpaceDisplayName", "")


def started(bot: Bot, arrive: list[str], within: float = 12) -> None:
    """'진행하기' 뒤 무엇이든 시작됐나 — 이동·로딩·대화거나 도착 화면이 보임. 엉뚱한 버튼·창을 눌렀으면 이동 상한(몇 분)까지
    기다리지 않고 StepTimeout (단계 다시 하기가 정리하고 한 번 더 한다). 패킷도 CLI 도 없으면 알 수 없어 그냥 둔다."""
    if not bot.packets.ok and not bot.state.available():
        return
    end = time.monotonic() + within
    while time.monotonic() < end:
        if bot.auto_traveling() or bot.map_loading() or bot.dialogue_playing() or any(bot.exists(n) for n in arrive):
            return
        bot.sleep(1, 1.3)
    from .. import monitor
    shot = bot.snapshot("travel_start").name
    monitor.of(bot).record(None, "동작", did="진행하기 → 이동", ok=False, why="이동이 시작되지 않음", shot=shot)
    raise StepTimeout(f"진행하기 뒤 {within:.0f}초 안에 이동이 시작되지 않음 → {shot}")


def travel(bot: Bot, arrive: list[str], timeout: float) -> None:
    """'진행하기' 등으로 시작된 자동 이동이 끝나 arrive 중 하나가 보일 때까지 대기.
    설정에 fast_travel_key 가 있으면 이동 시작 후 한 번 눌러 빠른 이동한다."""
    key = bot.cfg["game"].get("fast_travel_key")
    # 패킷: 자동 이동 시작이 오면 바로 (빠른 이동 가능 여부도 같이 온다). 모르면 예전처럼 2~3초 뒤 CLI 로
    moved = bot.wait_packet(lambda s: s.traveling, 5) is True
    if moved:
        bot.sleep(0.5)
    else:
        bot.sleep(2, 3)
        started(bot, arrive)
    if key and bot.fast_travel_ok():
        bot.log.info("빠른 이동")
        bot.key(key)
    # 이동이 끝났는데(패킷·CLI) 도착 화면이 한참 안 뜨면 엉뚱한 곳에 선 것 — 상한(timeout)까지 기다리지 않는다
    # (2026-10-26 요일 던전 입구에서 던전 창 없이 5분 서 있음)
    end = time.monotonic() + timeout
    stopped = None
    while True:
        try:
            return bot.wait_any(arrive, timeout=min(10, max(0, end - time.monotonic())), interval=1.0)
        except StepTimeout:
            if time.monotonic() >= end:
                raise
        if bot.auto_traveling() or bot.map_loading():
            moved, stopped = True, None
        elif moved:
            stopped = stopped or time.monotonic()
            if time.monotonic() - stopped > ARRIVE_GRACE:
                raise StepTimeout(f"이동이 끝났는데 {ARRIVE_GRACE}s 안에 {arrive} 중 아무것도 나타나지 않음")


class CannotProceed(RuntimeError):
    """던전 미해금, 장소를 못 찾음 등 진행할 수 없는 상황. 실행기는 실패로 기록하고 다음 숙제로 넘어간다."""


def open_map(bot: Bot) -> None:
    """지도(M)를 연다. 처음에는 지금 있는 지역의 지역 맵이 열린다."""
    for _ in range(3):  # M 이 무시될 때가 있어 지도가 열렸는지 확인하고 다시 누른다
        bot.to_main()
        bot.key("m")
        try:
            bot.wait(bot.ui["map_open"], timeout=4)
            break
        except StepTimeout:
            bot.log.debug("지도가 열리지 않아 M 다시 누름")
    else:
        raise CannotProceed(f"지도(M)가 열리지 않음 → {bot.snapshot('map').name}")
    bot.sleep(0.8, 1.2)


def open_world_map(bot: Bot) -> None:
    """지도(M) → '울라 대륙' → 최대 축소 → 좌측 상단 끝으로 드래그."""
    mc = bot.cfg["map"]
    open_map(bot)
    bot.click(tuple(mc["ulla_click"]))
    bot.sleep(1, 1.4)
    bot.scroll(900, 500, -mc["zoom_notches"])
    bot.sleep(0.8, 1.2)
    (fx, fy), (tx, ty) = mc["drag_from"], mc["drag_to"]
    for _ in range(mc["drag_times"]):
        bot.drag(fx, fy, tx, ty)
        bot.sleep(0.5, 0.8)
    bot.sleep(0.8, 1.2)


def similar(a: str, b: str) -> float:
    """OCR 결과와 이름이 얼마나 비슷한지 (0~1). 공백은 무시한다."""
    a, b = a.replace(" ", ""), b.replace(" ", "")
    if not a or not b:
        return 0.0
    if b in a:
        return 1.0
    # OCR 결과 뒤에 다른 글자가 붙는 경우('…사냥터 입구')가 많아 같은 길이의 구간끼리 비교한다
    n = len(b)
    windows = [a[i:i + n] for i in range(max(1, len(a) - n + 1))]
    return max(difflib.SequenceMatcher(None, w, b).ratio() for w in windows)


def read_button(frame, region) -> tuple[int | None, str, str]:
    """숫자와 한글이 섞인 버튼('20 입장하기', '10 임무 시작', '2층 3구역 진입') → (가격, Windows 글자, 한글 글자).
    숫자는 Windows OCR, 한글은 RapidOCR 로 읽는다 (ocr.py 머리말). 가격은 버튼 글자의 마지막 숫자."""
    from ..ocr import read_ko, read_text
    win, ko = read_text(frame, region), read_ko(frame, region)
    nums = re.findall(r"\d+", win)
    return (int(nums[-1]) if nums else None), win, ko


def has_word(word: str, *texts: str) -> bool:
    """한글 단어가 읽은 글자들 중 하나에 있는지 (띄어쓰기 무시)."""
    from ..ocr import nospace
    w = nospace(word)
    return any(w in nospace(t) for t in texts)


def _castles(bot: Bot) -> list[tuple[int, int, str]]:
    """월드맵에 보이는 지역(성) 아이콘들의 (중심 x, 중심 y, 아래 이름 OCR)."""
    from ..ocr import read_ko, read_text
    frame = bot.frame()
    out = []
    for m in bot.find_all(bot.cfg["map"]["castle"]):
        x, y = m.center
        region = [max(0, m.x - 80), m.y + 38, 200, 50]
        text = read_ko(frame, region) or read_text(frame, region, white=230) or read_text(frame, region, white=200)
        out.append((x, y, text))
    return out


def _best_anchor(named: list, towns: dict, town: str) -> tuple[int, int, str]:
    """이름을 읽은 성들 중 기준점을 고른다. 목표 마을 자체를 읽었으면 그것, 아니면 다른 성들의 상대 위치와
    가장 잘 맞는(= OCR 이 맞게 읽었을 가능성이 높은) 성. 이름 하나만으로 판단하지 않기 위한 교차 확인."""
    exact = [(x, y, n) for x, y, n in named if n == town]
    if exact:
        return exact[0]

    def agree(a):
        ax, ay, an = a
        return sum(1 for x, y, n in named if n != an
                   and abs(ax + towns[n][0] - towns[an][0] - x) < 60 and abs(ay + towns[n][1] - towns[an][1] - y) < 60)
    return max(named, key=agree)


def find_town(bot: Bot, town: str) -> tuple[int, int]:
    """월드맵에서 town 의 성 아이콘 화면 좌표. 보이는 지역 이름을 기준점 삼아 위치를 계산하고,
    화면 밖이면 그쪽으로 지도를 끌어 온다. 끄는 거리가 매번 달라도 기준점으로 다시 계산한다."""
    mc = bot.cfg["map"]
    towns = mc["towns"]
    x0, y0, x1, y1 = mc["safe_area"]
    for _ in range(8):
        castles = _castles(bot)
        named = []
        for x, y, text in castles:
            best = max(towns, key=lambda t: similar(text, t))
            if similar(text, best) >= 0.6:
                named.append((x, y, best))
        bot.log.debug(f"월드맵 지역: {[(n, x, y) for x, y, n in named]}")
        if not named:  # 아무 이름도 못 읽음 → 남쪽으로 조금 이동해 다시 본다
            bot.drag(900, 700, 900, 300, steps=30)
            bot.sleep(1.2, 1.5)
            continue
        ax, ay, anchor = _best_anchor(named, towns, town)
        tx = ax + towns[town][0] - towns[anchor][0]
        ty = ay + towns[town][1] - towns[anchor][1]
        if x0 <= tx <= x1 and y0 <= ty <= y1 and not (tx > 1190 and ty > 860):
            # OCR 만 믿지 않고, 계산한 자리에 실제 성 아이콘(템플릿)이 있을 때만 누른다
            near = [(x, y) for x, y, _ in castles if abs(x - tx) < 60 and abs(y - ty) < 60]
            if near:
                return near[0]
            bot.log.debug(f"'{town}' 계산 위치 ({tx}, {ty}) 에 성 아이콘이 없음 → 다시 읽기")
            bot.sleep(1, 1.5)
            continue
        # 목표가 화면 가운데로 오도록 끌기 (한 번에 최대 600px)
        dx = max(-600, min(600, 900 - tx))
        dy = max(-600, min(600, 480 - ty))
        bot.drag(900, 480, 900 + dx, 480 + dy, steps=30)
        bot.sleep(1.2, 1.5)
    raise CannotProceed(f"월드맵에서 '{town}' 을 찾지 못함 → {bot.snapshot('map').name}")


def _read_best(frame, region, name: str) -> tuple[float, str]:
    """작은 글자는 OCR 결과가 흰색 기준값에 따라 달라지므로 여러 번 읽어 name 과 가장 비슷한 것을 고른다."""
    from ..ocr import read_ko, read_text
    reads = [read_ko(frame, region)] + [read_text(frame, region, white=w, scale=sc)
                                        for w, sc in ((200, 2), (170, 2), (140, 4), (200, 3))]
    return max((similar(t, name), t) for t in reads)


def _pick_from_list(bot: Bot, place: dict, name: str) -> bool:
    """지역 맵 왼쪽 아래 목록의 장소 칸이 name 인지 이름 글자 템플릿으로 확인하고 누른다.
    다른 지역 맵이면 그 칸에 다른 장소가 있으므로 False. (작은 목록 글자는 OCR 이 자주 틀려 템플릿을 쓴다)"""
    mc = bot.cfg["map"]
    if place.get("tab"):
        bot.click(tuple(mc["tabs"][place["tab"]]))
        bot.sleep(0.8, 1.2)
    y = (mc["list_y_tabbed"] if place.get("tab") else mc["list_y"])[place["index"]]
    m = bot.find(place["label"], region=[70, y - 30, 180, 60], threshold=mc["list_threshold"])
    if not m:
        bot.log.debug(f"목록 {place['index']}번 칸이 '{name}' 이 아님")
        return False
    bot.click((mc["list_x"], y))
    try:
        bot.wait(bot.ui["map_go_here"], timeout=5)
    except StepTimeout:
        return False
    bot.sleep(0.5, 0.8)
    score, shown = _read_best(bot.frame(), mc["info_name_region"], name)  # 기록용 (판단에는 쓰지 않음)
    bot.log.debug(f"정보 창 '{shown}' ↔ '{name}' ({score:.2f})")
    return True


def other_town(bot: Bot, town: str) -> bool:
    """패킷: 지금 다른 마을(Field 맵)에 있나. 모르거나 마을이 아닌 곳(사냥터·던전)이면 False."""
    st = bot.packets.state if bot.packets.ok else None
    if not st or st.loading or st.channel_type != "Field" or not st.channel_name:
        return False
    here = st.channel_name.replace(" ", "")
    if here != town.replace(" ", ""):
        bot.log.debug(f"패킷: 지금 마을 '{st.channel_name}' ≠ '{town}' → 월드맵으로")
        return True
    return False


def go_to_place(bot: Bot, name: str, arrive: list[str], timeout: float, tries: int = STEP_RETRIES + 1):
    """지도에서 장소([places] 의 마을/탭/목록 칸)를 찾아 '여기로 가기' → 도착까지.
    지금 있는 지역 맵에 있으면 바로 고르고, 아니면 월드맵에서 마을을 찾아 들어간다.
    장소를 못 고르거나 이동 뒤 도착 화면이 안 뜨면 처음부터 tries 번까지."""
    place = bot.cfg["places"].get(name)
    if place is None:
        raise CannotProceed(f"config.toml [places] 에 '{name}' 이 없음")

    def go():
        open_map(bot)
        # 다른 마을에 있으면 지역 맵 목록이 다르다 — 탭 자리를 누르면 그 지역 목록 칸이 눌린다 (2026-10-25).
        # 패킷이 지금 마을을 알면 목표 마을이 아닐 때 바로 월드맵으로 간다. 사냥터·던전 안이거나 모르면 목록 글자로 본다
        if other_town(bot, place["town"]) or not _pick_from_list(bot, place, name):
            open_world_map(bot)
            bot.click(find_town(bot, place["town"]))
            bot.sleep(2, 2.5)
            if not _pick_from_list(bot, place, name):
                raise CannotProceed(f"'{place['town']}' 지역 맵에서 '{name}' 을 고르지 못함 → {bot.snapshot('map').name}")
        bot.step("travel", f"{name} ({place['town']}) 로 이동", place=name)
        bot.key("space")
        return travel(bot, arrive=arrive, timeout=timeout)

    return with_retries(bot, f"'{name}' 으로 가기", go, retries=tries - 1)


def select_zone(bot: Bot, difficulty: str, floor: int, zone: int) -> None:
    """일반 던전 창에서 난이도와 층-구역을 고르고, 진입 버튼 글자로 확인한다.
    해당 구역이 보이지 않으면 (미해금 등) CannotProceed."""
    ui = bot.ui
    if difficulty:
        tpl = {"일반": ui["dungeon_diff_normal"], "어려움": ui["dungeon_diff_hard"]}.get(difficulty)
        if tpl is None:
            raise CannotProceed(f"알 수 없는 난이도 '{difficulty}' (일반 / 어려움)")
        if not bot.click_if(tpl):
            raise CannotProceed(f"난이도 '{difficulty}' 버튼이 없음 → {bot.snapshot('difficulty').name}")
        bot.sleep(0.8, 1.2)
    m = bot.find(f"zone_{floor}-{zone}")
    if not m:
        raise CannotProceed(f"{floor}층 {zone}구역이 보이지 않음 (미해금이거나 템플릿 없음) → {bot.snapshot('zone').name}")
    bot.click(m)
    bot.sleep(0.8, 1.2)
    want = f"{floor}층 {zone}구역"
    _, win, ko = read_button(bot.frame(), ui["enter_button_region"])
    text = ko or win
    if has_word(gd.text("dungeon_deep"), win, ko):  # 심층 던전이 있는 던전은 창이 심층 탭으로 열린다. 은동전 숙제가 심층으로 들어가면 안 된다
        raise CannotProceed(f"심층 던전 구역이 선택됨: 버튼 '{text}' → {bot.snapshot('zone').name}")
    if not has_word(want, win, ko):
        raise CannotProceed(f"구역 선택 확인 실패: 버튼 '{text}' / '{win}' (기대 '{want}') → {bot.snapshot('zone').name}")
    bot.log.info(f"구역 선택: {text}")


def dungeon_state(bot: Bot) -> str | None:
    """던전 상태. 패킷이 알면 그것 (바뀌는 즉시), 모르면 CLI."""
    if bot.packets.ok and bot.packets.state.dungeon_state:
        return bot.packets.state.dungeon_state
    act = bot.state.activity() if bot.state.available() else None
    return (act or {}).get("Dungeon", {}).get("State")


def wait_dungeon(bot: Bot, pred: Callable[[str], bool], timeout: float, interval: float = 3.0) -> str | None:
    """던전 상태(NotInDungeon/Entering/InProgress/Cleared)가 pred 를 만족할 때까지 기다려 그 상태를 돌려준다.
    시간 초과면 "". 패킷이 상태를 알면 패킷으로 (바뀌는 즉시), 모르면 CLI 를 interval 마다 (CLI 조회 실패는 "Unknown").
    둘 다 못 쓰면 None — 화면으로 판단할 것. 감시가 도중에 시작돼 아직 상태를 모를 때(던전 안에서 시작)도 CLI 로 간다."""
    end = time.monotonic() + timeout
    while True:
        p = bot.packets
        left = end - time.monotonic()
        if p.ok and p.state.dungeon_state is not None:
            if bot.wait_packet(lambda s: pred(s.dungeon_state), max(0.0, min(left, interval))):
                return p.state.dungeon_state
        elif bot.state.available():
            st = dungeon_state(bot) or "Unknown"
            if pred(st):
                return st
            if left > 0:
                bot.sleep(min(left, interval))
        else:
            return None
        if time.monotonic() > end:
            return ""


def enter_from_dungeon_window(bot: Bot, clear_timeout: float, extra_loot: int = 0,
                              expect_cost: int | None = None, again: str | None = None,
                              retry: bool = False) -> str:
    """던전 창(단계 선택)이 열린 상태에서 선택된 단계로 입장해 끝까지 진행. 반환 'clear' | 'fail' | 'again'.
    expect_cost 가 있으면 임무 화면의 입장 버튼 가격(예: 은동전 20 = 소탕 10 + 더블 루팅 10)을 확인한다.
    retry: 직전 보상 화면에서 '다시 하기'를 눌러 이미 임무 화면이 열려 있음 (단계 '진입' 생략).
    again: 보상 화면에서 누를 반복 버튼('다시 하기'). 누르면 'again' 을 반환한다."""
    ui = bot.ui
    if not retry:
        bot.key("space")                 # 단계 '진입'
    bot.wait_any([ui["dungeon_mission_enter"], ui["dungeon_mission_enter_deep"], ui["dungeon_mission_enter_silver"],
                  ui["dungeon_retry_enter"]], timeout=15)
    bot.sleep(0.8, 1.2)
    if expect_cost is not None:
        price, win, ko = read_button(bot.frame(), ui["mission_button_region"])
        if price != expect_cost or not has_word(gd.text("dungeon_enter"), win, ko):
            raise CannotProceed(f"입장 버튼 '{win}' / '{ko}' — 비용 {expect_cost} 이 아님 (더블 루팅 꺼짐?) "
                                f"→ {bot.snapshot('mission_cost').name}")
    bot.step("dungeon_enter", "던전 입장")
    bot.key("space")                     # 임무 선택 '입장하기' (일반 던전은 은동전, 심층 던전은 공물 소모)
    return play_dungeon(bot, clear_timeout, extra_loot, again)


def play_dungeon(bot: Bot, clear_timeout: float, extra_loot: int = 0, again: str | None = None) -> str:
    """입장 직후부터 클리어 → 보상 → 필드 복귀까지. 반환: 'clear' | 'fail' | 'again'(반복 버튼을 누름)
    도는 동안은 연출의 '장면 넘기기' 를 누르지 않는다 (Bot.scene_skip)."""
    prev, bot.scene_skip = bot.scene_skip, False
    try:
        return _play_dungeon(bot, clear_timeout, extra_loot, again)
    finally:
        bot.scene_skip = prev


def _play_dungeon(bot: Bot, clear_timeout: float, extra_loot: int, again: str | None) -> str:
    ui = bot.ui
    entered = wait_dungeon(bot, lambda s: s == "InProgress", bot.cfg["timing"]["loading"], interval=2)
    if entered == "":
        raise StepTimeout("던전 입장 확인 실패")
    if entered is not None:
        bot.step("in_dungeon", "던전 진행 중")

        end = time.monotonic() + clear_timeout
        while True:
            state = wait_dungeon(bot, lambda s: s != "InProgress", 3)
            if state:
                break
            if state is None:  # 패킷도 CLI 도 끊김 → 클리어 화면으로
                bot.wait(ui["dungeon_touch"], timeout=max(1.0, end - time.monotonic()), interval=2.0)
                state = "Cleared"
                break
            if bot.is_dead():
                if not handle_death(bot):
                    bot.log.warning("사망 상태, '여기서 부활' 을 못 함")
            if time.monotonic() > end:
                raise StepTimeout("던전 클리어 대기 시간 초과")
        result = "clear" if state == "Cleared" else "fail"
        bot.step("dungeon_reward", "던전 클리어 → 보상·나가기" if result == "clear" else f"던전 끝남({state}) → 나가기")
        if result == "fail":
            bot.log.warning(f"던전 종료 상태: {state} → {bot.snapshot('dungeon_end').name}")
    else:
        # CLI 를 못 쓰면 클리어 화면이 뜰 때까지 기다린다
        bot.wait(ui["dungeon_touch"], timeout=clear_timeout, interval=2.0)
        result = "clear"

    if finish_dungeon(bot, extra_loot, again) and result == "clear":
        return "again"
    return result


def touch_prompt_visible(bot: Bot) -> bool:
    return has_word(gd.text("clear_touch"), *_touch_texts(bot, bot.frame()))


def clear_blockers(bot: Bot, skip=(), ocr: bool = False) -> str | None:
    """다른 조작을 막는 화면을 하나 넘긴다 — 대화(대화 넘기기), 연출(장면 넘기기), 퀘스트 클리어 등의 초록 '확인',
    '화면을 터치해 주세요', 출석 대사, 작별 대사. 넘긴 것의 이름, 없으면 None. skip 에 든 템플릿은 건드리지 않는다 (지금 기다리는 것).
    숙제·어비스처럼 오래 혼자 도는 동안 언제든 끼어들 수 있다: 주말 어비스 3판 퀘스트가 반복 도중 깨지며
    클리어 창이 떠 매칭을 10분 막았다 (2026-10-24 06:07). Bot.wait_any 가 오래 못 찾을 때와 어비스 대기 중에 부른다.
    판단과 대응은 점검자(mabi.monitor)가 한다 — NPC 메뉴(수락·결과 보고)·전달 창은 누르지 않는다.
    ocr: '확인'·'화면을 터치해 주세요' 를 글자로도 본다 (느려서 가끔만)."""
    from .. import monitor
    return monitor.of(bot).clear(skip=skip, ocr=ocr)


def _confirm_text(frame) -> tuple[int, int] | None:
    """화면 아래 가운데 초록 버튼 글자가 '확인' 이면 그 자리 (OCR)."""
    from ..ocr import find_texts
    return next(((x, y) for t, x, y in find_texts(frame, gd.region("confirm_button"))
                 if "".join(t.split()) == gd.text("confirm")), None)


def _touch_texts(bot: Bot, frame) -> tuple[str, str]:
    from ..ocr import read_ko, read_text
    r = bot.cfg["dungeon"]["touch_text_region"]
    return read_ko(frame, r), read_text(frame, r, white=220)


def after_clear(bot: Bot, extra_loot: int = 0, again: str | None = None, timeout: float = 180) -> bool:
    """클리어 뒤 화면들 — 클리어 화면 터치 · 연출 · 보상(추가 루팅·나가기) · 퀘스트 클리어 확인 · 대화 · 작별 화면 —
    을 순서와 상관없이 점검자가 처리하고, 던전 밖 메인 화면이 몇 번 이어지면 끝낸다.
    again 버튼('다시 하기'·'새 임무 선택')이 보상 화면에 있으면 나가는 대신 누르고 True (반복 플레이).
    던전과 사냥터가 따로 갖던 마무리(finish_dungeon · settle_after_clear · close_quest_clears)를 하나로 했다."""
    from .. import monitor
    from ..monitor import detect as d
    mon = monitor.of(bot)
    ctx = monitor.Ctx(bot.task_id or "dungeon", "클리어 뒤", menus=True, reward=True, extra_loot=extra_loot, again=again)
    end = time.monotonic() + timeout
    stable, touched = 0, 0.0
    while stable < 3:
        if time.monotonic() > end:
            raise StepTimeout(f"클리어 후 화면 정리 실패 → {bot.snapshot('settle').name}")
        seen = mon.check(ctx, guard=False)
        if seen.finish:
            if seen.finish.result == "again":
                return True
            stable = 0
        elif seen.done:
            stable = 0
        elif seen.what == d.MAIN and dungeon_state(bot) in ("InProgress", "Cleared"):
            # 클리어 직후 클리어 화면('화면을 터치해 주세요' — 반투명이라 그림으로 잘 안 잡힌다)이 뜨기 전·뜬 뒤에도
            # 던전 HUD 는 그대로 보인다 → 아직 던전 안. 클리어(패킷·CLI)면 화면 위쪽 빈 곳을 가끔 누른다
            stable = 0
            if dungeon_state(bot) == "Cleared" and time.monotonic() - touched > 2.5:
                touched = time.monotonic()
                bot.click(tuple(bot.cfg["dungeon"]["touch_xy"]))
        elif seen.what == d.MAIN and touch_prompt_visible(bot):
            stable = 0  # 사냥터 클리어 화면도 HUD 가 보인 채로 뜬다 — 반투명 글자라 그림 대신 글자로
            bot.click(tuple(bot.cfg["dungeon"]["touch_xy"]))
        elif seen.what == d.MAIN and not (bot.dialogue_playing() or bot.cutscene_playing()):
            stable += 1  # HUD 가 보여도 패킷이 대화·연출 중이라고 하면 아직 안 끝났다
        else:
            stable = 0
        bot.sleep(1.0, 1.5)
    bot.to_main()
    return False


def finish_dungeon(bot: Bot, extra_loot: int = 0, again: str | None = None) -> bool:
    """던전 클리어 화면 → 보상(추가 루팅) → 나가기 → 퀘스트 클리어 확인 → 필드 (after_clear)."""
    return after_clear(bot, extra_loot, again)


def settle_after_clear(bot: Bot, timeout: float = 180, again: str | None = None) -> bool:
    """사냥터 클리어 뒤 마무리 (after_clear). 사냥터는 클리어 화면에서도 HUD 가 보인다."""
    return after_clear(bot, again=again, timeout=timeout)


def do_extra_loot(bot: Bot, n: int) -> int:
    """요일 던전 보상 화면에서 추가 루팅(Space)을 n 회 연달아 누른다 (0.5초 간격).
    비용은 골드 6천 / 1만2천 / 1만8천이라, 끝난 뒤 줄어든 골드로 실제 횟수를 확인한다."""
    gold = bot.state.currency(gd.currency("gold")) if bot.state.available() else None
    for _ in range(n):
        bot.key("space")
        bot.sleep(0.5, 0.7)
    bot.sleep(2, 2.5)  # 마지막 루팅 연출
    done = n
    if gold is not None:
        now = bot.state.currency(gd.currency("gold"))
        if now is not None:
            spent = gold - now
            done = sum(1 for cost in (6000, 18000, 36000)[:n] if spent >= cost)
    bot.log.info(f"추가 루팅 {done}회" + ("" if done == n else f" (요청 {n}회)"))
    return done


def dungeon_once(bot: Bot, open_steps: list[str], lack: list[str] = (), clear_timeout: float = 600) -> str:
    """메인 화면에서 open_steps 를 눌러 던전 창을 연 뒤 1회 진행.
    반환: 'clear' | 'fail' | 'lack'(입장 재화 부족)"""
    ui = bot.ui
    bot.to_main()
    bot.click_steps(open_steps)
    if lack:
        bot.key("space")
        m = bot.wait_any([*lack, ui["dungeon_mission_enter"]], timeout=15)
        if m.name in lack:
            bot.to_main()
            return "lack"
        bot.key("space")
        return play_dungeon(bot, clear_timeout)
    return enter_from_dungeon_window(bot, clear_timeout)


def quest_titles(bot: Bot) -> list[str] | None:
    """퀘스트 제목 목록. CLI 조회 실패면 None (빈 목록과 구분해야 클리어로 오판하지 않는다)."""
    quests = bot.state.query("get_quests")
    return None if quests is None else [q.get("QuestTitle", "") for q in quests]


def play_field(bot: Bot, place: str, clear_timeout: float, on_enter=None, again: str | None = None) -> str:
    """사냥터 창에서 '입장하기'(또는 '임무 시작')를 누른 뒤 클리어까지. 반환 'clear' | 'again'.
    입장하면 퀘스트 목록에 '<장소> 사냥 …' 퀘스트가 생기고, 클리어하면 사라진다 (CLI get_quests).
    on_enter(bot) 는 입장 직후 한 번 호출된다 (사냥터 안의 검은 구멍 처리 등). 그동안에도 사냥터 시간은 흐른다.
    again 을 주면 보상 화면에서 그 버튼('새 임무 선택')을 눌러 사냥터 창으로 바로 돌아가고 'again' 을 반환한다."""
    bot.step("field_enter", f"{place} 사냥터 입장", place=place)
    bot.key("space")
    # 패킷이 먼저 (사냥터 상태 InProgress + 사냥터 맵 로딩 끝 — 상태는 로딩 전에 먼저 온다), 못 쓰거나 안 오면 CLI 퀘스트 목록
    entered = bot.wait_packet(lambda s: s.field_state == "InProgress" and s.channel_type == "BattleField" and not s.loading,
                              bot.cfg["timing"]["loading"])
    if not entered:
        wait_until(bot, lambda: bool(hunt_quest(bot, place)), bot.cfg["timing"]["loading"] if entered is None else 10,
                   what="사냥터 입장")
    bot.step("in_field", f"사냥터 진행 중: {hunt_quest(bot, place)}", place=place)
    if on_enter:
        on_enter(bot)
    return wait_field(bot, place, clear_timeout, again)


def hunt_quest(bot: Bot, place: str = "") -> str | None:
    """진행 중인 사냥터 퀘스트 제목 ('<장소> 사냥 …'), 없으면 '', 조회 실패면 None. place 가 비면 아무 사냥터나."""
    titles = quest_titles(bot)
    if titles is None:
        return None
    # 장소를 안 주면 config [places] 의 사냥터(index 2) 중 아무거나 — 이야기 퀘스트의 '사냥' 과 헷갈리지 않게
    places = [place] if place else [n for n, p in bot.cfg["places"].items() if int(p.get("index", -1)) == 2]
    return next((t for t in titles if gd.text("hunt_quest") in t and any(t.startswith(p) for p in places)), "")


def wait_field(bot: Bot, place: str, clear_timeout: float, again: str | None = None) -> str:
    """사냥터 안에서 클리어까지 기다리고 마무리. 반환 'clear' | 'again'.
    사냥터 안에서 끊긴 뒤 다시 시작했을 때도 이걸로 그 판을 끝까지 본다 (은동전은 이미 나갔다)."""
    def hunt():
        return hunt_quest(bot, place)

    end = time.monotonic() + clear_timeout
    # 패킷이 사냥터 상태를 알면 그걸로 — 클리어 순간(WaitingForChannelTransfer) 바로 안다. 퀘스트 목록으로 보는 아래 방식은
    # 3번 연속(15초+) 확인이 필요하고 창이 HUD 를 가리면 오판했다. 감시가 도중에 끊기면 아래 방식으로 넘어간다
    while bot.packets.ok and bot.packets.state.field_state == "InProgress":
        if bot.wait_packet(lambda s: s.field_state != "InProgress", 5):
            bot.log.info(f"패킷: 사냥터 끝남 ({bot.packets.state.field_state})")
            bot.step("field_reward", "사냥터 클리어 → 마무리")
            return "again" if settle_after_clear(bot, again=again) else "clear"
        if bot.is_dead() and not handle_death(bot):
            bot.log.warning("사망 상태, '여기서 부활' 을 못 함")
        if time.monotonic() > end:
            raise StepTimeout("사냥터 클리어 대기 시간 초과")
    gone = 0
    covered_since = None
    # 조회 실패나 일시적인 빈 응답으로 끝났다고 오판하지 않도록 3번 연속 없어야 클리어로 본다
    while gone < 3:
        h = hunt()
        # CLI 퀘스트 목록은 화면에 보이는 추적 칸만 준다 → 지도 등 창이 열려 HUD 가 가려지면 사냥 퀘스트가 '없음' 으로
        # 나온다 (2026-10-23: 사냥 중 지도가 열려 클리어로 오판, 다음 던전으로 떠남). 메인 화면일 때만 셈에 넣는다
        if h == "" and not bot.at_main() and not bot.exists(bot.ui["reward_exit"]) and not touch_prompt_visible(bot):
            h = None  # 클리어 화면(터치·보상)도 아닌데 HUD 가 가려짐 = 다른 창이 열린 것
            covered_since = covered_since or time.monotonic()
            if time.monotonic() - covered_since > 30:  # 창이 계속 열려 있으면 닫는다 (사냥터 시간은 흐르고 있다)
                bot.log.info("사냥터: 창이 열려 진행 상황이 가려짐 → 닫음")
                try:
                    bot.to_main(tries=4)
                except StepTimeout:
                    pass
                covered_since = None
        else:
            covered_since = None
        gone = gone + 1 if h == "" else 0
        if bot.is_dead() and not handle_death(bot):
            bot.log.warning("사망 상태, '여기서 부활' 을 못 함")
        if time.monotonic() > end:
            raise StepTimeout("사냥터 클리어 대기 시간 초과")
        bot.sleep(5)
    bot.step("field_reward", "사냥터 클리어 → 마무리")
    return "again" if settle_after_clear(bot, again=again) else "clear"
