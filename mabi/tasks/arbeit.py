"""아르바이트: 퀘스트 창(J) → 아르바이트 탭의 일을 위에서부터 끝까지 한다 (캐릭터 탭에서 켠 캐릭터만).

아르바이트마다 흐름이 제각각이라 (계단 수리처럼 자동으로 진행하고 바로 끝나는 것, 중간에 다른 NPC 대화가 끼는 것,
결과 보고 → 물품 전달이 있는 것) 정해진 순서를 따라가지 않고 화면에 보이는 것에 반응한다 (2026-10-22 실기 확인):

  '수락'(Space)            → Space
  '전달하기' 창             → A(자동 넣기) → 'Space' 표시가 생기면 Space. 안 채워지면 물품 부족 → 닫고 건너뜀
  '결과 보고'(Space)        → Space
  '퀘스트 클리어' 확인      → Space (그 아르바이트 끝)
  NPC 대화 ('대화 기록' 버튼이 보이는 화면) → '대화 넘기기' 자리 클릭. 대사가 한마디라 버튼이 없어도 화면 아무 데나
                             눌러 넘어가므로 같은 자리를 누르면 된다. 대화가 아닐 때 누르면 미니맵이 눌리므로 꼭 확인한다
  메인 화면에서 멈춤(CLI: 이동·자동 진행·대화·전투 아님) → 퀘스트(J) → 아르바이트 → 그 일의 '진행하기' 다시

수락한 아르바이트의 조건은 CLI get_quests 에 나온다 ('새록 버섯 포자 보유 10/10'). '보유' 조건을 못 채운 일은 진행하기를 누르면
'필요한 아이템이 없습니다' → 물품 줄 → '구하는 방법' 맨 위(추천)로 게임이 필요한 만큼만 채집한다 (구할 방법이 없으면 건너뜀). 끝났는지는 get_quests 에서 그 제목이 사라졌는지로 본다.
버튼 색이 카드마다 달라(멤버십 노랑, 보통 초록) '지원하기'·'진행하기' 버튼과 카드 제목은 글자(OCR)로 찾는다.
"""
import difflib
import re
import time

from .. import ocr
from ..bot import Bot, StepTimeout
from .content import CannotProceed, open_arbeit_tab

PANEL = (1220, 150, 680, 850)  # 퀘스트 창 오른쪽 목록 [x, y, w, h]


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _plain(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t)


def accepted(bot: Bot) -> list[dict]:
    """수락해 둔 아르바이트 [{title, objectives}]. 아르바이트는 수락하면 '사이드' 로 고정(pinned_sub)된다."""
    qs = bot.state.query("get_quests") or []
    return [{"title": q["QuestTitle"], "objectives": q.get("Objectives") or []}
            for q in qs if isinstance(q, dict) and q.get("Source") == "pinned_sub"]


def _finished(bot: Bot, title: str) -> bool:
    """title 아르바이트가 정말 끝났나. 추적 칸에서 사라진 것만으로는 모른다 — 이동·채집·로딩 중에는 추적 칸이
    통째로 비어 get_quests 가 [] 를 준다 (2026-10-22: 채집하러 가자마자 '완료' 로 오판, 17:44 에도 같은 일).
    → 추적 칸에 다른 퀘스트는 보이는데 이 일만 없을 때, 2초 뒤 한 번 더 봐도 그럴 때만 끝난 것으로 본다."""
    for i in range(2):
        qs = bot.state.query("get_quests")
        if not qs:
            return False
        if any(isinstance(q, dict) and _same(q.get("QuestTitle", ""), title) for q in qs):
            return False
        if i == 0:
            bot.sleep(2, 2.5)
    return True


def missing_items(job: dict) -> list[str]:
    """채우지 못한 '보유' 조건 (있으면 그 일은 지금 끝낼 수 없다)."""
    return [_plain(o["Description"]) for o in job["objectives"]
            if "보유" in o.get("Description", "") and not o.get("IsCompleted")]


def _item_name(desc: str) -> str:
    """'새록 버섯 포자 보유 3/10' → '새록 버섯 포자'."""
    return re.sub(r"\s*보유.*$", "", desc).strip()


def ungatherable(bot: Bot, job: dict) -> list[str]:
    """모자란 물품 중 채집으로 못 구하는 것 (가공품 등). CLI 채집 가능 목록(조회)과 대조한다.
    사용자 규칙: 모자란 게 채집품뿐이면 채집해서 완료, 가공품이 하나라도 모자라면 포기."""
    if not hasattr(bot, "_gatherable"):
        data = bot.state.query("get_gatherable_items") or {}
        items = data.get("items", data) if isinstance(data, dict) else data
        bot._gatherable = {i.get("DisplayName") for i in items if isinstance(i, dict) and i.get("ToolOk", True)}
    return [n for n in (_item_name(d) for d in missing_items(job)) if n not in bot._gatherable]


def _buttons(bot: Bot) -> list[tuple[str, int, int]]:
    return ocr.find_texts(bot.frame(), PANEL)


def _scroll_panel(bot: Bot, notches: int) -> None:
    r = bot.window.client_rect()
    bot.input.scroll(r.left + bot.cfg["arbeit"]["list_scroll_at"][0], r.top + bot.cfg["arbeit"]["list_scroll_at"][1], notches)
    bot.sleep(1.0, 1.3)


def _find_card_button(bot: Bot, title: str | None, word: str):
    """title 카드의 word 버튼 (title 이 None 이면 맨 위 word 버튼). 목록을 내려 가며 찾는다."""
    for page in range(bot.cfg["arbeit"]["list_pages"]):
        items = _buttons(bot)
        btns = sorted(((x, y) for t, x, y in items if _norm(t) == word), key=lambda b: b[1])
        if title is None:
            if btns:
                return btns[0]
        else:
            head = next(((x, y) for t, x, y in items if _same(t, title)), None)
            if head:
                below = [b for b in btns if b[1] > head[1]]
                if below:
                    return below[0]
            # 수락한 일의 '진행하기' 는 목록 맨 위에 모인다 → 그 아래 '지원하기' 가 보이는데도 못 찾았으면 더 내려도 없다
            if word == "진행하기" and any(_norm(t) == "지원하기" for t, _, _ in items):
                return None
        if page + 1 < bot.cfg["arbeit"]["list_pages"]:
            _scroll_panel(bot, -4)
    return None


def _book(bot: Bot) -> dict | None:
    """오늘 기록(state/날짜.json)의 이 캐릭터 아르바이트 진행 {current, stage, at, done, skipped, stuck}.
    숙제가 도중에 꺼져도 다시 시작하면 이걸 보고 이어 한다 (하던 일은 게임에도 '수락한 일' 로 남아 있어 그 일부터 한다)."""
    st, ch = getattr(bot, "daily", None), getattr(bot, "character", None)
    if st is None or not ch:
        return None
    return st.data.setdefault(str(ch["slot"]), {}).setdefault("_arbeit", {})


def _note(bot: Bot, title: str | None, key: str, stage: str, **lists) -> None:
    """단계 기록 (bot.step: 이어 하기용 단계 키) + 아르바이트 장부 (_arbeit: 지금 일·완료/건너뜀/막힘 목록)."""
    b = _book(bot)
    if b is not None:
        b.update({"current": title, "stage": stage, "at": time.strftime("%H:%M:%S"), **lists})
    bot.step(key, f"{title}: {stage}" if title else stage, job=title)  # 장부도 같이 저장된다


def _card_title(items, bx: int, by: int) -> str:
    """'진행하기' 버튼 (bx, by) 카드의 제목 (짐작). 카드는 위에서부터 [등급·종류] / 제목 / NPC 위치·'n시간 남음' / 설명 /
    [보상 … 버튼] 이다 → 버튼 위에서 가장 가까운 '남음' 줄 바로 위의 글자 (설명이 두 줄이어도 맞는다)."""
    left = [(t, x, y) for t, x, y in items if x < bx - 100 and y < by]
    rest = [y for t, x, y in left if "남음" in t]
    if not rest:
        return ""
    ry = max(rest)
    above = [(t, y) for t, x, y in left if y < ry - 15]
    return max(above, key=lambda r: r[1])[0] if above else ""


def _same(a: str, b: str) -> bool:
    """같은 제목인가. 카드 제목은 OCR 이라 한 글자쯤 틀린다 ('빚은' → '빛은', 2026-10-22) → 비슷하면 같다고 본다."""
    a, b = _norm(a), _norm(b)
    if not (a and b):
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def _panel_jobs(bot: Bot) -> list[tuple[str, tuple[int, int], int]]:
    """퀘스트 창 아르바이트 탭에서 수락해 둔 일 ('진행하기' 카드) [(제목 짐작, 버튼 자리, 목록 쪽)].
    CLI get_quests 에는 지금 추적 중인(pinned) 아르바이트 하나만 나와서 (2026-10-22: 막힌 일 두 개가 목록에서
    빠져 '다 끝남' 으로 기록됨) 수락한 일 전부는 이 창으로 본다. 창은 열린 채로 두고 마지막 쪽까지 내려가 있다."""
    _settle(bot)  # 창을 열 때 ESC 가 남은 NPC 메뉴·전달 창을 닫아 버리지 않게
    open_arbeit_tab(bot)
    out = []
    pages = bot.cfg["arbeit"]["list_pages"]
    bot._arb_scrolled = 0
    bot._arb_closed = False
    for page in range(pages):
        items = _buttons(bot)
        for t, x, y in items:
            if _norm(t) == "진행하기" and not any(o[1] == (x, y) for o in out):
                out.append((_card_title(items, x, y), (x, y), page))
        # 구인 마감 ('새로운 아르바이트를 기다려주세요') — 남은 일도 지원할 일도 없다. 더 볼 것 없음
        if any("구인마감" in _norm(t) or "기다려주세요" in _norm(t) for t, _, _ in items):
            bot._arb_closed = not out
            break
        # 수락한 일('진행하기')은 목록 맨 위에 모이고 그 아래가 구인 중('지원하기') → '지원하기' 가 보이면 더 내릴 필요 없다
        if any(_norm(t) == "지원하기" for t, _, _ in items) or page + 1 >= pages:
            break
        _scroll_panel(bot, -4)
        bot._arb_scrolled += 1
    return out


def _press_other(bot: Bot, exclude) -> str | None:
    """추적 중이 아닌 수락한 일 중 exclude 에 없는 것의 '진행하기' 를 누른다. 누른 일의 제목 (CLI 기준) 또는 None."""
    jobs = [j for j in _panel_jobs(bot) if not any(_same(j[0], e) for e in exclude)]
    if not jobs:
        bot.to_main()
        return None
    guess, pos, page = jobs[0]
    # 내려가 있으면 그 쪽으로 돌아가서 누른다 (대개 맨 위 쪽이라 스크롤이 없다)
    if getattr(bot, "_arb_scrolled", 0) != page:
        _scroll_panel(bot, 4 * (bot._arb_scrolled + 1))
        for _ in range(page):
            _scroll_panel(bot, -4)
    items = _buttons(bot)
    btn = next(((x, y) for t, x, y in items if _norm(t) == "진행하기"
                and (_same(_card_title(items, x, y), guess) if guess else abs(y - pos[1]) < 30)), None)
    if not btn:
        bot.to_main()
        return None
    bot.click(btn)
    bot.sleep(2, 2.5)
    _fast_travel(bot)
    # CLI 퀘스트 목록은 '화면에 보이는' 추적 칸만 준다 → 창이 닫히고 추적 칸에 이 일이 뜰 때까지 몇 초 걸린다
    # (2026-10-22: 바로 물어 빈 목록 → 수락 안 된 것으로 보고 '막힘' 처리)
    for _ in range(8):
        now = accepted(bot)
        if now:
            return now[0]["title"]
        bot.sleep(1, 1.2)
    bot.log.warning(f"아르바이트 '{guess}': 진행하기를 눌렀는데 추적 칸에 안 나타남 → {bot.snapshot('arbeit_pin').name}")
    return guess or None


def _idle(bot: Bot) -> bool:
    a = bot.state.activity() or {}
    return not any(a.get(k) for k in ("IsAutoPlaying", "IsAutoTraveling", "IsDialoguePlaying", "IsInCombat"))


def _fast_travel(bot: Bot) -> bool:
    """먼 곳으로 자동 이동 중이면 빠른 이동 키(T)를 누른다 (content.travel 과 같은 기준). 눌렀으면 True."""
    key = bot.cfg["game"].get("fast_travel_key")
    act = bot.state.activity() or {}
    if key and act.get("IsAutoTraveling") and act.get("AutoTravelRemainingPositionCount", 0) > 0:
        bot.log.info("빠른 이동")
        bot.key(key)
        return True
    return False


def _settle(bot: Bot) -> None:
    """남은 NPC 대사·확인 창을 정리한다 (ESC 로는 대사가 안 닫혀 to_main 이 실패한다).
    채집이 끝나면 게임이 알아서 전달하러 가서 대화가 열려 있기도 하다 (2026-10-22 싱싱한 달걀)."""
    # 이 뒤에는 늘 퀘스트 창(J)·to_main 의 ESC 가 온다. ESC 는 NPC 메뉴에선 '대화 종료', 전달 창에선 '닫기' 라
    # 아르바이트 화면이 남아 있으면 그 일을 날린다 (2026-10-22 결과 보고 대신 ESC 가 여러 번) → 여기서 전부 끝까지 처리한다
    a, ui = bot.cfg["arbeit"], bot.ui
    pressed_a = False
    for _ in range(25):
        frame = bot.frame()
        find = lambda n: bot.vision.find(frame, n)  # noqa: E731
        if find(ui["confirm_green"]) or find(a["report"]) or find(a["accept"]):
            # 결과 보고·수락·퀘스트 클리어 확인 모두 Space
            bot.key("space")
        elif find(a["deliver_title"]):
            if find(a["deliver_ready"]):
                bot.key("space")
            elif not pressed_a:  # 자동 넣기는 토글이라 한 번만
                bot.key("a")
                pressed_a = True
        elif find(a["dialog_log"]):
            # 말을 건 직후 메뉴 버튼([결과 보고] 등)은 1~2초 늦게 뜬다 → 기다렸다 다시 보고 결정
            bot.sleep(1.5, 2)
            if bot.exists(a["report"]):
                bot.key("space")
            else:
                bot.click(tuple(a["dialog_next_xy"]))
        else:
            act = bot.state.activity() or {}
            if act.get("IsDialoguePlaying"):  # 대화가 열리는 중
                bot.sleep(1, 1.3)
                continue
            return
        bot.sleep(1.2, 1.5)


def _leave(bot: Bot) -> None:
    _settle(bot)
    try:
        bot.to_main()
    except StepTimeout:
        pass


def _press_progress(bot: Bot, title: str) -> bool:
    _settle(bot)
    open_arbeit_tab(bot)
    # 하고 있는(추적 중인) 일은 목록 맨 위 카드다 → 제목을 OCR 로 맞춰 볼 것 없이 맨 위 '진행하기' (2026-10-22 사용자 지적)
    b = _find_card_button(bot, None, "진행하기")
    if not b:
        bot.to_main()
        return False
    bot.click(b)
    bot.sleep(2, 2.5)
    _fast_travel(bot)
    return True


def _work(bot: Bot, title: str) -> str:
    """한 아르바이트를 끝까지. 'done' | 'short'(물품 부족) | 'stuck'."""
    a, ui = bot.cfg["arbeit"], bot.ui
    end = time.monotonic() + a["job_timeout"]
    idle_since, pushes, deliver_tries, last_sig, card_clicks = None, 0, 0, None, 0
    gathering, gather_end, howto_tries, last_check = False, 0.0, 0, 0.0
    while time.monotonic() < end:
        bot.sleep(1.0, 1.4)
        # 채집하러 간 뒤: 조건이 채워지면 바로 완료하러 간다 (게임은 필요한 만큼만 캐고 멈춘다)
        if gathering and time.monotonic() - last_check > 3:
            last_check = time.monotonic()
            job = next((j for j in accepted(bot) if _same(j["title"], title)), None)
            if job is None:
                if _finished(bot, title):
                    return "done"
                continue  # 추적 칸이 잠깐 비었다 (이동·로딩 중) — 끝난 게 아니다
            if not missing_items(job):
                gathering = False
                _note(bot, title, "arb_gathered", "채집 끝 → 완료하러 이동")
                # 게임이 알아서 전달하러 가기도 한다 (2026-10-22: 40m 앞에서 '진행하기' 를 다시 누르려다 못 찾고
                # 막힘으로 끝냄) → 이동 중이면 그대로 두고, 멈춰 있을 때만 누른다. 못 눌러도 아래 '멈춤' 처리가 다시 민다
                if _idle(bot):
                    bot.log.info(f"아르바이트 '{title}': 채집 완료 → 완료하러 이동")
                    _press_progress(bot, title)
                else:
                    bot.log.info(f"아르바이트 '{title}': 채집 완료 → 게임이 완료하러 가는 중")
                    _fast_travel(bot)
                idle_since = None
                continue
            if time.monotonic() > gather_end:
                bot.log.warning(f"아르바이트 '{title}': 채집이 끝나지 않음 ({', '.join(missing_items(job))}) → {bot.snapshot('arbeit_gather').name}")
                _leave(bot)
                return "short"
        frame = bot.frame()
        find = lambda n: bot.vision.find(frame, n)  # noqa: E731
        # '필요한 아이템이 없습니다' → 물품 줄 → '구하는 방법' 에서 맨 위(추천) → 게임이 채집하러 간다.
        # 채집 물품이 여러 개면 하나를 다 캐고 나서 이 창이 다시 뜬다 → 같은 처리를 되풀이
        if find(a["howto_title"]):
            items = ocr.find_texts(frame, tuple(a["howto_area"]))
            rows = sorted(((x, y) for t, x, y in items if "추천" not in t and "구하는" not in t), key=lambda r: r[1])
            if not rows or howto_tries >= 3:
                bot.log.warning(f"아르바이트 '{title}': 구하는 방법이 없음 → {bot.snapshot('arbeit_short').name}")
                for _ in range(2):
                    bot.key("esc")
                    bot.sleep(0.8, 1.0)
                _leave(bot)
                return "short"
            howto_tries += 1
            _note(bot, title, "arb_gather", "채집 중")
            bot.click(rows[0])
            bot.sleep(2, 2.5)
            _fast_travel(bot)
            gathering, gather_end, last_check = True, time.monotonic() + a["gather_timeout"], time.monotonic()
            idle_since = None
            continue
        if (m := find(a["item_missing"])):
            job = next((j for j in accepted(bot) if _same(j["title"], title)), None)
            if job and (bad := ungatherable(bot, job)):
                bot.log.warning(f"아르바이트 '{title}': 채집으로 못 구하는 물품 부족 ({', '.join(bad)}) → 포기")
                bot.key("esc")
                bot.sleep(1, 1.3)
                _leave(bot)
                return "short"
            ox, oy = a["item_row_from_title"]
            bot.click((m.x + ox, m.y + oy))
            bot.sleep(1.2, 1.5)
            idle_since = None
            continue
        if (m := find(ui["confirm_green"])):  # 퀘스트 클리어 등
            bot.key("space")
            bot.sleep(2, 2.5)
            if _finished(bot, title):
                return "done"
            idle_since = None
            continue
        if find(a["deliver_title"]):
            # '자동 넣기'(A)는 누를 때마다 켜졌다 꺼졌다 하는 스위치라 한 번만 누르고 채워지길 기다린다
            # (두 번 누르면 도로 꺼져 0/5 로 남는다 — 2026-10-22). 몇 번 봐도 'Space' 표시가 없으면 정말 모자란 것
            if find(a["deliver_ready"]):
                _note(bot, title, "arb_deliver", "물품 전달")
                bot.key("space")
                deliver_tries = 0
            elif deliver_tries == 0:
                bot.key("a")
                deliver_tries = 1
            elif deliver_tries < 4:
                deliver_tries += 1
            else:
                bot.log.warning(f"아르바이트 '{title}': 전달할 물품이 모자람 → {bot.snapshot('arbeit_short').name}")
                bot.key("esc")
                bot.sleep(1, 1.5)
                _leave(bot)
                return "short"
            bot.sleep(1, 1.3)
            idle_since = None
            continue
        if find(a["accept"]) or find(a["report"]):
            _note(bot, title, *(("arb_report", "결과 보고") if find(a["report"]) else ("arb_accept", "수락")))
            bot.key("space")
            idle_since = None
            continue
        # 제작 아르바이트: '진행하기' 를 누르면 제작 창이 열린다 → 물품 → 제작하러 가기 → (설비로 이동) 제작하기 → 확인
        # '제작하기' 템플릿은 '제작하러 가기' 에도 0.8 정도로 걸리므로 '가기' 를 먼저 본다 (반대는 0.7 미만).
        # 비용 아이콘('2')이 붙는 제작도 있어 두 템플릿 모두 버튼 글자만 잘랐다.
        # 재료는 숫자를 읽지 않고 그냥 Space 를 누른다 — 모자라면 게임이 위에 '재료가 부족합니다.' 를 띄우고 아무것도
        # 하지 않는다 → 그걸 보면 포기 (재료 숫자 OCR 은 아이콘 위 글자라 자주 틀렸다 — 2026-10-22 사용자 제안)
        if find(a["alter_button"]):
            # 가공 시설 창 ('가공하기') — 가공은 시간이 걸려(수십 초~) 기다리지 않고 포기하고 넘어간다 (사용자 규칙).
            # 17:38·20:44 '마지막 재료'(가죽 가공) 에서 이 창에 멈춰 '막힘' 이 됐다
            bot.log.warning(f"아르바이트 '{title}': 가공이 필요한 일 → 건너뜀 ({bot.snapshot('arbeit_alter').name})")
            bot.key("esc")
            bot.sleep(1, 1.5)
            _leave(bot)
            return "alter"
        if find(a["craft_transfer"]):
            # 가방에 모자란 재료를 보관함에서 가져올지 묻는 창 (비용 표시가 있다) → 확인(Space). 2026-10-22 철괴 12/3 중 보관함분
            _note(bot, title, "arb_craft", "재료 전송 (보관함에서)")
            bot.key("space")
            bot.sleep(1.5, 2)
            idle_since = None
            continue
        go, make = find(a["craft_go"]), None
        if not go:
            make = find(a["craft_make"])
        if go or make:
            _note(bot, title, "arb_craft", "제작")
            bot.key("space")
            try:
                bot.wait(a["craft_short_toast"], timeout=2.5, interval=0.3)
                bot.log.warning(f"아르바이트 '{title}': 제작 재료 부족 → {bot.snapshot('arbeit_craft').name}")
                bot.key("esc")
                bot.sleep(1, 1.5)
                _leave(bot)
                return "short"
            except StepTimeout:
                pass  # 안내가 없으면 제작이 진행된 것
            bot.sleep(0.5, 1)
            _fast_travel(bot)
            idle_since = None
            continue
        if (mv := find(a["craft_list"])):  # 제작 창 첫 화면: 아르바이트가 요구하는 물품 하나만 보인다
            # 오른쪽 창이 열렸는데 버튼을 못 알아보면 카드를 또 눌러 창을 닫는 걸 되풀이한다 → 몇 번이면 그만
            card_clicks += 1
            if card_clicks > 4:
                bot.log.warning(f"아르바이트 '{title}': 제작 창 버튼을 알아보지 못함 → {bot.snapshot('arbeit_craft').name}")
                break
            ox, oy = a["craft_item_from_list"]
            bot.click((mv.x + ox, mv.y + oy))
            bot.sleep(1.2, 1.5)
            idle_since = None
            continue
        if find(a["dialog_log"]):  # NPC 대화: 대사가 몇 마디든 '대화 넘기기' 자리를 누르면 넘어간다
            # 말을 건 직후에는 메뉴 버튼([결과 보고] 등)이 1~2초 늦게 뜬다 → 조금 기다렸다 다시 보고 결과 보고면 Space
            bot.sleep(1.5, 2)
            if bot.exists(a["report"]):
                _note(bot, title, "arb_report", "결과 보고")
                bot.key("space")
            else:
                bot.click(tuple(a["dialog_next_xy"]))
            idle_since = None
            continue
        if (m := find(ui["scene_skip"])):
            bot.click(m)
            idle_since = None
            continue
        if bot.at_main() and _idle(bot) and not gathering:
            idle_since = idle_since or time.monotonic()
            if time.monotonic() - idle_since >= a["idle_wait"]:
                job = next((j for j in accepted(bot) if _same(j["title"], title)), None)
                if job is None:
                    if _finished(bot, title):
                        return "done"  # 확인 창 없이 끝나는 일
                    idle_since = None
                    continue
                # '주변을 살펴보는 중' 같은 짧은 동작은 CLI 에 진행 중으로 안 나온다 → 조건이 바뀌었으면 나아간 것으로 본다
                sig = [(o.get("Description"), o.get("Count")) for o in job["objectives"]]
                if sig != last_sig:
                    last_sig, pushes = sig, 0
                if pushes >= a["max_pushes"]:
                    break
                pushes += 1
                bot.log.info(f"아르바이트 '{title}': 멈춰 있음 → 진행하기 ({pushes})")
                if not _press_progress(bot, title):
                    break
                idle_since = None
            continue
        idle_since = None
    bot.log.warning(f"아르바이트 '{title}': 끝나지 않음 → {bot.snapshot('arbeit_stuck').name}")
    _leave(bot)
    return "stuck"


def _apply_top(bot: Bot) -> bool:
    """맨 위 '지원하기' → 이동 → 수락 대화. 수락 대화까지 오면 True (수락은 _work 가 한다)."""
    _settle(bot)
    open_arbeit_tab(bot)
    b = _find_card_button(bot, None, "지원하기")
    if not b:
        bot.to_main()
        return False
    bot.click(b)
    a = bot.cfg["arbeit"]
    bot.sleep(2, 2.5)
    _fast_travel(bot)
    bot.wait(a["accept"], timeout=a["travel_timeout"], interval=1.5)
    bot.key("space")
    bot.sleep(1.5, 2)
    for _ in range(10):  # 수락 뒤 이어지는 대사를 넘긴다
        if not bot.exists(a["dialog_log"]):
            break
        bot.click(tuple(a["dialog_next_xy"]))
        bot.sleep(1.2, 1.6)
    return True


def verify(bot: Bot, cfg: dict) -> bool:
    """수락해 둔 아르바이트가 남지 않았으면 완료. 포기한 일(가공품 부족 등)이 남아 있으면 '남음(직접)'.
    CLI 는 추적 중인 일 하나만 보여 주므로 퀘스트 창 목록의 '진행하기' 카드로 본다."""
    if accepted(bot):
        return False
    if getattr(bot, "_arb_closed", False):
        return True  # 숙제 끝에 본 목록이 '구인 마감' (남은 일 없음) — 창을 또 열지 않는다
    left = _panel_jobs(bot)
    bot.to_main()
    return not left


def run(bot: Bot, cfg: dict) -> str:
    if not bot.state.available():
        raise CannotProceed("아르바이트는 진행 상태 확인에 CLI 가 필요함")
    a = cfg["arbeit"]
    done, skipped, stuck = [], {}, []
    book = _book(bot) or {}
    # 오늘 앞 실행에서 물품 부족으로 건너뛴 일은 다시 가 보지 않는다 (사람 몫). 막혔던 일은 다시 해 본다
    skipped.update(book.get("skipped") or {})
    if book.get("current"):
        bot.log.info(f"아르바이트 지난 기록: '{book['current']}' {book.get('stage', '')} ({book.get('at', '')}) → 이어서")

    def save(title=None, key="arb_job", stage="진행"):
        _note(bot, title, key, stage, done=[*dict.fromkeys([*(book.get("done") or []), *done])], skipped=skipped, stuck=stuck)

    for _ in range(a["max_jobs"]):
        pressed = False
        # 물품이 모자라도 바로 건너뛰지 않는다 — 진행하기를 누르면 게임이 '구하는 방법'(채집 장소)을 알려 주고,
        # 그걸 고르면 필요한 만큼만 채집한다. 구할 방법이 없을 때만 _work 가 'short' 로 돌려준다
        jobs = [j for j in accepted(bot) if not any(_same(j["title"], e) for e in [*skipped, *stuck])]
        job = jobs[0] if jobs else None
        if job is None:
            # 추적 중이 아닌 수락한 일 (앞 실행에서 막혔거나 사람이 받아 둔 일) 부터 이어 한다
            title = _press_other(bot, [*skipped, *stuck, *done])
            if title:
                bot.log.info(f"아르바이트 이어서 진행: {title}")
                # 추적 칸에 안 보여도 그만두지 않는다 — 진행하기로 바로 NPC 대화([결과 보고] 메뉴)가 열리면 추적 칸이
                # 가려져 CLI 에 안 나온다 (2026-10-22 '별과 돌이 빚은 광석'). _work 가 화면을 보고 처리한다.
                # 이미 '진행하기' 를 눌러 이동·대화가 시작됐다 → 또 누르지 않고 바로 화면 반응으로 (2026-10-22:
                # 또 누르려고 퀘스트 창을 열다 NPC 대화와 겹쳐 '메인 화면으로 돌아오지 못함' 으로 실패)
                job, pressed = {"title": title}, True
        if job is None and getattr(bot, "_arb_closed", False):
            break  # 방금 본 목록이 '구인 마감' — 지원하러 창을 또 열 필요 없다
        if job is None:
            # 할 수 있는 수락한 일이 없으면 새 일에 지원한다
            before = {j["title"] for j in accepted(bot)}
            if not _apply_top(bot):
                break
            new = [j for j in accepted(bot) if j["title"] not in before]
            # 수락 직후 후속 대화가 남아 있을 수 있다 → _work 가 정리하며 진행한다
            title = new[0]["title"] if new else None
            if title is None:
                bot.sleep(2, 3)
                new = [j for j in accepted(bot) if j["title"] not in before]
                if not new:
                    stuck.append("(지원 후 수락 확인 실패)")
                    break
                title = new[0]["title"]
            bot.log.info(f"아르바이트 지원: {title}")
            continue
        bot.log.info(f"아르바이트 진행: {job['title']}")
        save(job["title"])
        if not pressed and not _press_progress(bot, job["title"]):
            stuck.append(job["title"])
            continue
        r = _work(bot, job["title"])
        if r == "done":
            done.append(job["title"])
            bot.log.info(f"아르바이트 완료: {job['title']}")
        elif r == "short":
            skipped[job["title"]] = "전달 물품 부족"
        elif r == "alter":
            skipped[job["title"]] = "가공 필요"
        else:
            stuck.append(job["title"])
        save(None, "arb_result", {"done": "완료", "short": "건너뜀", "alter": "건너뜀(가공)"}.get(r, "막힘")
             + f": {job['title']}")
    save(None, "arb_end", "아르바이트 목록 끝")
    _leave(bot)
    out = f"아르바이트 {len(done)}개 완료"
    if skipped:
        out += ", 건너뜀: " + ", ".join(f"{t}({w})" for t, w in skipped.items())
    if stuck:
        # 막힌 일은 사람 몫이 아니라 다시 해 볼 일 → 실패로 남겨 다음 실행 때 이어 한다 ('남음(직접)' 은 물품 부족만)
        raise CannotProceed(out + ", 막힘: " + ", ".join(dict.fromkeys(stuck)))
    return out
