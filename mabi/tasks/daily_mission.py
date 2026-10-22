"""일일 미션: N → 완료한 미션 '선물 받기' → (연금술 미션이 남았으면) 연금술 → 상단 2/4/6회 누적 보상.

미션 목록과 진행 상태는 CLI get_daily_missions 로 읽는다 (Title, CurrentCount, GoalCount, IsCompleted, IsRewardReceived).
- 선물을 받아도 카드 자리는 그대로이고 '미션 완료' 도장이 찍힌다. 아래쪽 카드는 스크롤해야 보인다.
- 누적 보상은 받을 수 있을 때 'N회' 글자가 크고 노랗게 바뀐다. 받으면 체크 표시가 된다.
- 음식 N개 먹기: 배고프지 않으면 B 로는 못 먹는다. 미션 카드 '진행하기' → 인벤토리 음식 탭 → 여행자 간식 →
  사용하기(Space) 를 하면 바로 일일 미션 창으로 돌아온다. 남은 개수만큼 반복.
- 재료 아이템 3회 채집: 미션 카드 '진행하기' → 미션 창이 닫히고 캐릭터가 근처에서 알아서 채집한다.
  CLI 로 완료를 확인한 뒤 미션 창을 다시 연다. 사냥터에서 가끔 채워지지만 안 될 때가 많다.
- 연금술 3회 사용: 미션 카드 '진행하기' → 보석 연금술 → 재료 자동 넣기 → 모두 승급 한 번이면 완료.
  승급 직후 다음 단계 '모두 승급'(훨씬 비쌈)이 바로 나오므로 한 번만 누르고 ESC 로 빠져나온다.
  ESC 를 몇 번 누르면 일일 미션 창으로 돌아온다.
"""
from ..bot import Bot, StepTimeout
from ..ocr import read_ko, read_text
from .content import has_word, wait_until


def missions(bot: Bot) -> list[dict]:
    return bot.state.query("get_daily_missions") or []


def verify(bot: Bot, cfg: dict) -> bool:
    """완료한 미션의 선물을 모두 받았으면 완료 (조건을 못 채운 미션은 따지지 않는다)."""
    ms = missions(bot)
    return bool(ms) and not unclaimed(bot)


def unclaimed(bot: Bot) -> list[dict]:
    return [m for m in missions(bot) if m.get("IsCompleted") and not m.get("IsRewardReceived")]


def _is(m: dict, keyword: str) -> bool:
    """미션 제목이나 설명에 keyword 가 들어 있나 (제목은 날마다 바뀔 수 있어 설명도 본다)."""
    return keyword in (m.get("Title", "") + m.get("Description", "")).replace(" ", "")


def _pending(bot: Bot, keyword: str) -> dict | None:
    return next((m for m in missions(bot) if _is(m, keyword) and not m.get("IsCompleted")), None)


def _back_to_window(bot: Bot, c: dict) -> None:
    """ESC 로 일일 미션 창까지 돌아온다."""
    for _ in range(6):
        if bot.exists(c["title"]):
            return
        bot.key("esc")
        bot.sleep(1.2, 1.6)
    open_window(bot, c)


def open_window(bot: Bot, c: dict) -> None:
    bot.to_main()
    bot.key(c["key"])
    bot.wait(c["title"], timeout=10)
    bot.sleep(1, 1.5)


def _scroll_list(bot: Bot, c: dict, notches: int) -> None:
    r = bot.window.client_rect()
    x, y = c["list_scroll_at"]
    bot.input.scroll(r.left + x, r.top + y, notches)
    bot.sleep(0.8, 1.0)


def claim_gifts(bot: Bot, c: dict) -> int:
    """보이는 '선물 받기'를 모두 누르고, 없으면 목록을 내려가며 반복한다. 누른 횟수 반환."""
    n = 0
    _scroll_list(bot, c, 15)  # 맨 위부터
    for _ in range(c["list_pages"] + 1):
        for _ in range(12):
            buttons = bot.find_all(c["gift"])
            if not buttons:
                break
            bot.click(buttons[0])
            n += 1
            bot.sleep(1.0, 1.3)
        _scroll_list(bot, c, -10)
    _scroll_list(bot, c, 15)
    return n


def claim_milestones(bot: Bot, c: dict) -> int:
    """상단 누적 보상 중 받을 수 있는 것(라벨이 크고 노란 상태)을 누른다."""
    n = 0
    y0, y1 = c["milestone_label_y"]
    for x in c["milestone_x"]:
        crop = bot.frame()[y0:y1, x - 25:x + 25].reshape(-1, 3).astype(int)
        yellow = ((crop[:, 2] > 200) & (crop[:, 1] > 150) & (crop[:, 0] < 120)).mean()
        if yellow > 0.08:
            bot.click((x, c["milestone_icon_y"]))
            n += 1
            bot.sleep(1.2, 1.5)
    return n


def find_go_button(bot: Bot, c: dict, keyword: str):
    """제목에 keyword 가 들어간 카드의 '진행하기' 버튼. 목록을 내려가며 찾는다.
    OCR 이 받침을 틀리기도 하므로 (꼬르륵 → 꼬르록) keyword 는 제목 앞 두 글자 정도로 준다."""
    _scroll_list(bot, c, 15)
    dx, dy, w, h = c["card_title_offset"]
    for _ in range(c["list_pages"] + 1):
        frame = bot.frame()
        for b in bot.find_all(c["go"]):
            region = [b.x + dx, b.y + dy, w, h]
            if has_word(keyword, read_ko(frame, region), read_text(frame, region, white=180)):
                return b
        _scroll_list(bot, c, -10)
    return None


def do_food(bot: Bot, c: dict, m: dict) -> str:
    """음식 미션 카드 '진행하기' → 여행자 간식 사용하기. 남은 개수만큼 반복."""
    f = c["food"]
    for _ in range(m["GoalCount"] - m["CurrentCount"]):
        go = find_go_button(bot, c, m["Title"][:2])
        if not go:
            return f"음식 미션 카드를 찾지 못함 → {bot.snapshot('food').name}"
        bot.click(go)
        try:
            label = bot.wait(f["item"], timeout=10)
        except StepTimeout:
            _back_to_window(bot, c)
            return f"음식 창에 '{f['item']}' 없음 → {bot.snapshot('food').name}"
        bot.sleep(0.5, 0.8)
        bot.click((label.x + label.w // 2, label.y + f["icon_dy"]))  # 이름 위의 아이콘
        # 아이템 정보 창이 뜨면 '사용하기'(Space). 기본 음식으로 지정된 음식은 버튼 배치가 달라 템플릿 대신 단축키를 쓴다
        bot.sleep(1.0, 1.4)
        bot.key("space")
        bot.sleep(1.5, 2)
        _back_to_window(bot, c)  # 보통은 저절로 일일 미션 창으로 돌아온다
    return "음식 완료" if not _pending(bot, f["mission_keyword"]) else f"음식 먹은 뒤에도 미완료 → {bot.snapshot('food').name}"


def do_alchemy(bot: Bot, c: dict, m: dict) -> str:
    """연금술 미션 카드 '진행하기' → 보석 연금술 → 재료 자동 넣기 → 모두 승급 1회 → 미션 창으로."""
    a = c["alchemy"]
    go = find_go_button(bot, c, m["Title"][:2])
    if not go:
        return f"연금술 미션 카드를 찾지 못함 → {bot.snapshot('alchemy').name}"
    bot.click(go)
    bot.wait(a["title"], timeout=10)
    bot.sleep(1, 1.5)
    bot.click(a["gem_card"], timeout=5)
    bot.wait(a["auto_off"], timeout=10)
    # 토글 그림은 창이 열리는 연출 중에도 보여서 너무 일찍 누르면 무시된다 (2026-10-22, 클릭은 됐는데 꺼진 채)
    # → 넉넉히 기다리고, 누른 뒤 꺼진 그림이 그대로면 다시 누른다
    bot.sleep(1.5, 2)
    upgrade = None
    for _ in range(3):
        bot.click(a["auto_off"])
        try:
            upgrade = bot.wait(a["upgrade_all"], timeout=4)
            break
        except StepTimeout:
            if not bot.exists(a["auto_off"]):  # 토글은 켜졌는데 '모두 승급'이 없다 = 정말 승급할 게 없다
                break
            bot.log.info("'재료 자동 넣기'가 켜지지 않음 → 다시 누름")
    if upgrade is None:
        if bot.exists(a["auto_off"]):
            result = f"'재료 자동 넣기'가 3번 눌러도 켜지지 않음 → {bot.snapshot('alchemy').name}"
        else:
            result = f"승급할 보석 없음 → {bot.snapshot('alchemy').name}"
    else:
        bot.click(a["upgrade_all"])  # 한 번만
        try:
            wait_until(bot, lambda: not _pending(bot, a["mission_keyword"]), 20, interval=2, what="연금술 미션 완료")
            result = "연금술 완료"
        except StepTimeout:
            result = f"모두 승급 후에도 미션 미완료 → {bot.snapshot('alchemy').name}"
        bot.sleep(2, 3)  # 승급 연출
    _back_to_window(bot, c)  # 승급 결과 → 보석 연금술 → 연금술 → 일일 미션 창
    return result


def do_gather(bot: Bot, c: dict, m: dict) -> str:
    """채집 미션 카드 '진행하기' → 미션 창이 닫히고 캐릭터가 근처에서 알아서 채집한다.
    CLI 로 미션 완료를 기다린 뒤 미션 창을 다시 연다."""
    g = c["gather"]
    go = find_go_button(bot, c, m["Title"][:2])
    if not go:
        return f"채집 미션 카드를 찾지 못함 → {bot.snapshot('gather').name}"
    bot.click(go)
    try:
        wait_until(bot, lambda: not _pending(bot, g["mission_keyword"]), g["timeout"], interval=5, what="채집 미션 완료")
        result = "채집 완료"
    except StepTimeout:
        result = f"{g['timeout']}초 안에 채집 미션 미완료 → {bot.snapshot('gather').name}"
    bot.sleep(2, 3)  # 마지막 채집 동작이 끝날 때까지
    open_window(bot, c)
    return result


def run(bot: Bot, cfg: dict) -> str:
    c = cfg["daily_mission"]
    if not bot.state.available():
        raise RuntimeError("일일 미션은 진행 상태 확인에 CLI 가 필요함")
    # 단계: dm_gifts → dm_food / dm_alchemy / dm_gather → dm_milestones. 미션마다 진행 수·받은 선물은 CLI 가
    # 알려 주므로 끊겨도 처음부터 다시 돌면 남은 것만 한다 (이미 받은 선물·채운 미션은 건너뜀)
    bot.step("dm_gifts", "일일 미션 창 → 선물 받기")
    open_window(bot, c)
    notes = []
    gifts = claim_gifts(bot, c)

    labels = {"food": "음식 먹기", "alchemy": "연금술", "gather": "채집"}
    for key, do in (("food", do_food), ("alchemy", do_alchemy), ("gather", do_gather)):
        m = _pending(bot, c[key]["mission_keyword"]) if c[key]["enabled"] else None
        if m:
            bot.step(f"dm_{key}", f"{labels[key]} 미션 ({m.get('CurrentCount')}/{m.get('GoalCount')})")
            notes.append(do(bot, c, m))
            gifts += claim_gifts(bot, c)

    if unclaimed(bot):  # 놓친 선물이 있으면 한 번 더
        gifts += claim_gifts(bot, c)
    bot.step("dm_milestones", "누적 보상 받기")
    milestones = claim_milestones(bot, c)

    ignore = set(c.get("ignore", []))  # 다른 숙제를 하다 저절로 깨지는 미션은 미완료로 알리지 않는다
    pending = [f"{m['Title']}({m['Description']} {m['CurrentCount']}/{m['GoalCount']})"
               for m in missions(bot) if not m.get("IsCompleted") and m["Title"] not in ignore]
    missed = [m["Title"] for m in unclaimed(bot)]
    bot.to_main()
    summary = f"선물 {gifts}개, 누적 보상 {milestones}개"
    if notes:
        summary += ", " + ", ".join(notes)
    if pending:
        summary += f", 미완료: {', '.join(pending)}"
    if missed:
        summary += f", 못 받은 선물: {', '.join(missed)}"
    return summary
