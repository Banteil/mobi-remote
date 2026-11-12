"""지도(M)·월드맵에서 장소를 골라 '여기로 가기' — 마을 찾기, 지역 맵 목록 칸 고르기, 도착까지 (go_to_place)."""
import difflib

from .. import keys
from ..bot import Bot
from ..exceptions import CannotProceed, StepTimeout
from ..place import OPEN_FIELD
from .arrival import travel
from .steps import STEP_RETRIES, with_retries


def open_map(bot: Bot) -> None:
    """지도(M)를 연다. 처음에는 지금 있는 지역의 지역 맵이 열린다."""
    for _ in range(3):  # M 이 무시될 때가 있어 지도가 열렸는지 확인하고 다시 누른다
        bot.to_main()
        bot.key(keys.of(bot, "map"))
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
            (fx, fy), (tx, ty) = mc["nudge_drag"]
            bot.drag(fx, fy, tx, ty, steps=30)
            bot.sleep(1.2, 1.5)
            continue
        ax, ay, anchor = _best_anchor(named, towns, town)
        tx = ax + towns[town][0] - towns[anchor][0]
        ty = ay + towns[town][1] - towns[anchor][1]
        if x0 <= tx <= x1 and y0 <= ty <= y1 and not (tx > mc["panel_from"][0] and ty > mc["panel_from"][1]):
            # OCR 만 믿지 않고, 계산한 자리에 실제 성 아이콘(템플릿)이 있을 때만 누른다
            near = [(x, y) for x, y, _ in castles if abs(x - tx) < 60 and abs(y - ty) < 60]
            if near:
                return near[0]
            bot.log.debug(f"'{town}' 계산 위치 ({tx}, {ty}) 에 성 아이콘이 없음 → 다시 읽기")
            bot.sleep(1, 1.5)
            continue
        # 목표가 지도 가운데로 오도록 끌기 (한 번에 최대 max_drag px)
        (cx, cy), lim = mc["center"], mc["max_drag"]
        dx = max(-lim, min(lim, cx - tx))
        dy = max(-lim, min(lim, cy - ty))
        bot.drag(cx, cy, cx + dx, cy + dy, steps=30)
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
    if not st or st.loading or st.channel_type != OPEN_FIELD or not st.channel_name:
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
