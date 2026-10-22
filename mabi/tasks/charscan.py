"""캐릭터 선택 화면을 읽어 캐릭터 수·카드 그림·이름(추정)을 모은다 (캐릭터 탭의 '자동 설정').

카드 위치는 접속(login)과 같이 카드 우상단 '•••' 를 찾아 정한다. 그림은 카드에서 잘라 그대로 쓰면 되지만,
이름은 게임 글꼴(테두리 있는 흰 글씨)이라 Windows OCR 은 한두 글자씩 틀려서('옥' → '목' 같은 혼동)
PP-OCRv5 한국어 모델(ocr.read_line)로 읽는다. 그래도 OCR 만 믿지 않고 '읽은 값' 으로 돌려주어
화면에서 사람이 확인한 뒤에 저장한다.

그림은 카드를 하나씩 눌러 '선택된' 모습(노란 불꽃 배경, 얼굴 확대)으로 바꾼 뒤 찍는다 (사용자 요청 2026-10-22).
누르고 0.6초면 확대가 끝나므로 1초쯤 뒤 선택 테두리를 확인하고 찍는다 (표정 동작은 상관없음).
다 읽으면 원래 골라져 있던 카드를 다시 눌러 두고 캐릭터 선택 화면에 머문다 (다시 접속하지 않는다).
"""
import re

import cv2
import numpy as np

from .. import ocr
from ..bot import Bot, StepTimeout
from . import login


def _text_lines(frame: np.ndarray, x: int, y: int, w: int, h: int, white: int = 215) -> list[tuple[int, int]]:
    """영역 안에서 흰 글자 줄의 (위, 아래) y 목록 (화면 좌표)."""
    mask = frame[y:y + h, x:x + w].min(axis=2) >= white
    prof = mask.sum(axis=1)
    out, start = [], None
    for i, c in enumerate(list(prof) + [0]):
        if c > 3 and start is None:
            start = i
        elif c <= 3 and start is not None:
            if i - start >= 10:  # 글자 높이보다 얇은 건 테두리·잡티
                out.append((y + start, y + i))
            start = None
    return out


TIME_RE = re.compile(r"^\d+\s*(시간|분|초)")
# 직업 이름 (OCR 끝에 붙는 군더더기를 떼려고 맞춰 본다. 목록에 없으면 읽은 대로)
JOBS = ("대검전사", "검술사", "전사", "석궁사수", "장궁병", "궁수", "화염술사", "빙결술사", "전격술사", "마법사",
        "힐러", "사제", "수도사", "암흑술사", "음유시인", "악사", "댄서", "격투가", "듀얼블레이드")


def _hangul(t: str) -> str:
    return "".join(ch for ch in t if "가" <= ch <= "힣")


def _timeish(t: str) -> bool:
    """'간분' '시간' 처럼 접속 시간 글자 조각뿐인 것."""
    h = _hangul(t)
    return bool(h) and set(h) <= set("시간분초") and any(ch in h for ch in "간분초")


def _best_read(frame: np.ndarray, x: int, w: int, y0: int, y1: int) -> tuple[str, float]:
    """줄을 위아래 여백을 바꿔 가며 몇 번 읽고 가장 확신 높은 것."""
    best = ("", 0.0)
    for pad in (4, 7, 10):
        t, sc = ocr.read_line(frame[max(0, y0 - pad):y1 + pad, x:x + w])
        if sc > best[1]:
            best = (t, sc)
    return best


def _read_card(frame: np.ndarray, menu, cs: dict) -> dict:
    """{name, name_score, level, job, portrait, selected}. 이름 바로 아래 줄은 늘 접속 시간('17시간' '30초')이므로
    그 줄을 찾아 바로 위 줄을 이름으로 본다. 못 찾으면 가장 확신 높은 한글 줄."""
    dx, dy = cs["card_from_menu"]
    left, top = menu.x + dx, menu.y + dy
    px, py, pw, ph = cs["portrait"]
    pic = frame[top + py:top + py + ph, left + px:left + px + pw].copy()
    nx, ny, nw, nh = cs["name_area"]
    reads = [(*_best_read(frame, left + nx, nw, y0, y1), y0) for y0, y1 in _text_lines(frame, left + nx, top + ny, nw, nh)]
    name, score = "", 0.0
    i = next((i for i, r in enumerate(reads) if TIME_RE.match(r[0])), None)
    if i:
        name, score = _hangul(reads[i - 1][0]), reads[i - 1][1]
    else:
        cand = [r for r in reads if len(_hangul(r[0])) >= 2 and not TIME_RE.match(r[0]) and "대표" not in r[0]]
        if cand:
            r = max(cand, key=lambda r: r[1])
            name, score = _hangul(r[0]), r[1] * 0.8  # 위치로 확인 못 했으니 덜 믿는다
    # 못 읽었거나 미덥지 않으면 글자 찾기(det)까지 맡겨 다시 읽는다. 화면 맨 아래 어두워지는 곳에 걸리면 글자가
    # 회색이라 흰 줄 찾기가 실패하고, '1시간 17분' 의 조각을 이름으로 잡기도 한다 ('간분', 2026-10-21)
    if not name or score < 0.85 or _timeish(name):
        reads = ocr.read_lines(frame[top + ny:top + ny + nh, left + nx:left + nx + nw])
        i = next((i for i, r in enumerate(reads) if TIME_RE.match(r[0])), None)
        if i and not _timeish(reads[i - 1][0]) and (reads[i - 1][1] > score or _timeish(name)):
            name, score = _hangul(reads[i - 1][0]), reads[i - 1][1]
    if _timeish(name):
        name, score = "", 0.0
    bx, by, bw, bh = cs["badge"]
    lv, _ = ocr.read_line(frame[top + by:top + by + bh, left + bx:left + bx + bw])
    lv = re.sub(r"\D", "", lv)
    jx, jy, jw, jh = cs["job_area"]
    job_raw, _ = ocr.read_line(frame[top + jy:top + jy + jh, left + jx:left + jx + jw])
    job = next((j for j in JOBS if j in job_raw), _hangul(job_raw))
    return {"name": name, "name_score": round(score, 2), "level": int(lv) if lv and int(lv) <= 200 else None,
            "job": job, "portrait": pic, "selected": login._is_selected(frame, menu, cs)}


def _read_row(bot: Bot, cs: dict, first: bool, tag: str) -> list[dict]:
    """첫 줄(first) 또는 마지막 줄 카드를 읽는다. 스크롤 직후엔 카드가 아직 미끄러지거나 글자가 늦게 뜨므로
    '•••' 위치를 읽을 그 화면에서 다시 찾고, 이름을 못 읽은 카드가 있으면 조금 기다렸다 다시 읽는다."""
    best: list[dict] = []
    for attempt in range(3):
        bot.sleep(0.6, 0.8)
        frame = bot.frame()
        rows = login._rows(bot.vision.find_all(frame, cs["card_menu"]))
        if not rows:
            continue
        got = [_read_card(frame, m, cs) for m in (rows[0] if first else rows[-1])]
        save_portrait(frame, bot.shot_dir / f"charscan_{tag}.png")  # 마지막으로 읽은 화면 (잘못 읽었을 때 확인용, 덮어씀)
        if sum(1 for c in got if c["name"]) > sum(1 for c in best if c["name"]) or len(got) > len(best):
            best = got
        if got and all(c["name"] for c in got):
            return got
    bot.log.warning(f"캐릭터 카드 이름 일부를 못 읽음 ({tag})")
    return best


def _focus(bot: Bot, cs: dict, menu) -> np.ndarray | None:
    """카드를 눌러 선택된 모습으로 바꾸고 그 화면을 돌려준다. 선택 테두리가 확인 안 되면 None."""
    ox, oy = cs["card_click_offset"]
    # 아래 줄 카드는 가운데가 '게임 시작' 버튼과 겹칠 수 있다 → 카드 위쪽(그림 부분)을 누른다
    y = min(menu.y + oy, cs["max_click_y"])
    if y < menu.y + 60:
        return None
    for _ in range(2):
        bot.click((menu.x + ox, y))
        bot.sleep(*cs["focus_wait"])
        frame = bot.frame()
        if login._is_selected(frame, menu, cs):
            return frame
    return None


def _crop_portrait(frame: np.ndarray, menu, cs: dict) -> np.ndarray:
    dx, dy = cs["card_from_menu"]
    px, py, pw, ph = cs["portrait"]
    left, top = menu.x + dx, menu.y + dy
    return frame[top + py:top + py + ph, left + px:left + px + pw].copy()


def _focus_row(bot: Bot, cs: dict, first: bool, cards: list[dict]) -> None:
    """한 줄의 카드를 차례로 눌러 선택된 모습의 그림으로 바꾼다. 실패한 카드는 평소 그림 그대로 둔다."""
    rows = login._rows(bot.find_all(cs["card_menu"]))
    if not rows:
        return
    for menu, card in zip(rows[0] if first else rows[-1], cards):
        frame = _focus(bot, cs, menu)
        if frame is None:
            bot.log.warning(f"카드 선택 확인 실패 → 평소 그림으로 ({card.get('name') or '?'})")
            continue
        card["portrait"] = _crop_portrait(frame, menu, cs)


def scan(bot: Bot, cfg: dict) -> dict:
    """{total, cards: [{slot, name, portrait(BGR), selected}], selected}. 세 줄 이상이면 가운데 줄은 못 읽는다.
    어느 화면에서 시작하든 캐릭터 선택 화면으로 나가서 읽고, 그 화면에 머문다."""
    cs, ui = cfg["charselect"], bot.ui
    charsel, title, main = ui["charselect_title"], ui["title_start"], ui["main_hud"]
    if not bot.at_main() and not (bot.exists(title) or bot.exists(charsel)):
        try:
            bot.to_main(tries=4)
        except StepTimeout:
            pass
    if bot.at_main():
        bot.to_charselect()
    m = bot.wait_any([charsel, title, main], timeout=cfg["login"]["timeout"])
    if m.name == title:
        bot.click(m)
        m = bot.wait_any([charsel, main], timeout=cfg["login"]["timeout"])
    if m.name == main:
        bot.to_charselect()
    bot.wait(charsel)
    bot.sleep(1.5, 2)

    total = login.count_characters(bot, cfg)  # 스크롤 맨 위
    cards: dict[int, dict] = {}
    last_row = (total - 1) // cs["columns"]
    # 이름·레벨·직업은 카드를 누르기 전에 읽는다 (선택된 카드는 노란 배경이라 흰 글자 줄 찾기가 어렵다)
    if login._scrolled_rows(bot, cs, top=True):
        row = _read_row(bot, cs, first=True, tag="top")
        for col, c in enumerate(row):
            cards[col + 1] = c
        _focus_row(bot, cs, True, row)
    if last_row > 0 and login._scrolled_rows(bot, cs, top=False):
        row = _read_row(bot, cs, first=False, tag="bottom")
        for col, c in enumerate(row):
            cards[last_row * cs["columns"] + col + 1] = c
        _focus_row(bot, cs, False, row)
    out = [{"slot": s, **c} for s, c in sorted(cards.items()) if s <= total]
    selected = next((c["slot"] for c in out if c["selected"]), None)
    bot.log.info(f"캐릭터 선택 화면: {total}명, 읽은 카드 {len(out)}장, 골라져 있던 슬롯 {selected}")
    if selected:  # 누르기 전 골라져 있던 카드로 되돌려 둔다 ('게임 시작' 을 누르면 원래 캐릭터)
        row, col = divmod(selected - 1, cs["columns"])
        rows = login._scrolled_rows(bot, cs, top=row == 0)
        r = (rows[0] if row == 0 else rows[-1]) if rows else []
        if col < len(r) and _focus(bot, cs, r[col]) is None:
            bot.log.warning(f"원래 골라져 있던 슬롯 {selected} 로 되돌리지 못함")
    login._scrolled_rows(bot, cs, top=True)  # 화면을 원래대로
    return {"total": total, "cards": out, "selected": selected}


def save_portrait(img: np.ndarray, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", img)
    if ok:
        path.write_bytes(buf.tobytes())
