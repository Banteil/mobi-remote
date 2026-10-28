"""일일 미션: N → (남았으면) 연금술 · 채집(자급자족의 삶) 진행 → 완료한 미션 '선물 받기' → 상단 2/4/6회 누적 보상.
음식 미션은 여기서 하지 않는다 (메인 화면으로 돌아올 때 배고프면 먹는 것으로 채워진다 — bot.eat_if_hungry).

미션 목록과 진행 상태는 CLI get_daily_missions 로 읽는다 (Title, CurrentCount, GoalCount, IsCompleted, IsRewardReceived).
- 선물을 받아도 카드 자리는 그대로이고 '미션 완료' 도장이 찍힌다. 아래쪽 카드는 스크롤해야 보인다.
- 누적 보상은 받을 수 있을 때 'N회' 글자가 크고 노랗게 바뀐다. 받으면 체크 표시가 된다.
- 재료 아이템 3회 채집: 미션 카드 '진행하기' → 미션 창이 닫히고 캐릭터가 근처에서 알아서 채집한다.
  CLI 로 완료를 확인한 뒤 미션 창을 다시 연다. 사냥터에서 가끔 채워지지만 안 될 때가 많다.
- 연금술 3회 사용: 미션 카드 '진행하기' → 보석 연금술 → 재료 자동 넣기 → 모두 승급 한 번이면 완료.
  승급 직후 다음 단계 '모두 승급'(훨씬 비쌈)이 바로 나오므로 한 번만 누르고 ESC 로 빠져나온다.
  ESC 를 몇 번 누르면 일일 미션 창으로 돌아온다.
"""
import time

from .. import monitor
from ..bot import Bot, StepTimeout
from ..ocr import read_ko, read_text
from .content import CannotProceed, has_word, wait_until


def _ctx(what: str) -> monitor.Ctx:
    return monitor.Ctx("daily_mission", what)


def _press(bot: Bot, c: dict, button) -> bool:
    """미션 창의 버튼을 누른다. 미션 창이 아니면 (다른 창이 덮음) 누르지 않고 False."""
    if not bot.exists(c["title"]):
        return False
    bot.click(button)
    return True


def missions(bot: Bot) -> list[dict]:
    return bot.state.query("get_daily_missions") or []


def verify(bot: Bot, cfg: dict) -> bool:
    """완료한 미션의 선물을 모두 받았고, 직접 하는 미션(연금술·채집)이 남지 않았으면 완료.
    다른 조건을 못 채운 미션(음식 등)은 따지지 않는다."""
    ms = missions(bot)
    return bool(ms) and not unclaimed(bot) and not own_pending(bot, cfg["daily_mission"])


def own_pending(bot: Bot, c: dict) -> list[str]:
    """직접 진행하는 미션(연금술·채집) 중 아직 안 끝난 것의 제목."""
    return [m["Title"] for key in ("alchemy", "gather") if c[key]["enabled"]
            and (m := _pending(bot, c[key]["mission_keyword"]))]


def unclaimed(bot: Bot) -> list[dict]:
    return [m for m in missions(bot) if m.get("IsCompleted") and not m.get("IsRewardReceived")]


def _is(m: dict, keyword: str) -> bool:
    """미션 제목이나 설명에 keyword 가 들어 있나 (제목은 날마다 바뀔 수 있어 설명도 본다)."""
    return keyword in (m.get("Title", "") + m.get("Description", "")).replace(" ", "")


def _pending(bot: Bot, keyword: str) -> dict | None:
    return next((m for m in missions(bot) if _is(m, keyword) and not m.get("IsCompleted")), None)


def _wait_done(bot: Bot, keyword: str, timeout: float, mark: int, what: str, interval: float = 3) -> None:
    """미션이 끝날 때까지. 패킷 '미션 완료' 알림이 오면 CLI 로 그 미션이 맞는지 본다 (같은 때 다른 미션이 끝날 수 있다).
    패킷 감시가 없으면 CLI 를 interval 마다."""
    if not bot.packets.ok:
        wait_until(bot, lambda: not _pending(bot, keyword), timeout, interval=interval, what=what)
        return
    end = time.monotonic() + timeout
    while _pending(bot, keyword):
        left = end - time.monotonic()
        if left <= 0:
            raise StepTimeout(f"{timeout:.0f}s 안에 {what} 충족 안 됨")
        seen = bot.packets.wait("dm.completed", min(left, 15), after=mark)  # 15초마다 CLI 로도 (감시가 놓쳤을 때)
        if seen:
            mark = seen.seq
        else:
            monitor.of(bot).clear()  # 기다리는 동안 끼어든 창 (채집 중 퀘스트 완료 등)


def _back_to_window(bot: Bot, c: dict) -> None:
    """ESC 로 일일 미션 창까지 돌아온다. 획득 연출·퀘스트 완료 창은 ESC 대신 점검자가 넘긴다."""
    for _ in range(6):
        if bot.exists(c["title"]):
            return
        if not monitor.of(bot).check(_ctx("미션 창으로"), guard=False).done:
            bot.key("esc")
        bot.sleep(1.2, 1.6)
    open_window(bot, c)


def open_window(bot: Bot, c: dict) -> None:
    bot.to_main()
    bot.key(c["key"])
    bot.wait(c["title"], timeout=10)
    bot.sleep(1, 1.5)


def _scroll_list(bot: Bot, c: dict, notches: int) -> None:
    bot.scroll(*c["list_scroll_at"], notches)
    bot.sleep(0.8, 1.0)


def _list_views(bot: Bot, c: dict):
    """목록 맨 위부터 조금씩 내려가며 한 화면씩 넘겨준다. 더 내려가지 않으면 (맨 아래) 끝.
    한 번에 많이 내리면 가운데 줄을 건너뛴다 (2026-10-25, 선물 7개를 못 보고 넘어감)."""
    x, y, w, h = c["list_area"]
    _scroll_list(bot, c, 15)
    before = None
    for _ in range(c["list_steps"]):
        yield
        now = bot.frame()[y:y + h, x:x + w].astype("int16")
        if before is not None and abs(now - before).mean() < 2:
            return
        before = now
        _scroll_list(bot, c, -c["list_step"])


def _ensure_window(bot: Bot, c: dict) -> None:
    """선물을 받은 뒤 획득 연출 등이 창을 덮었으면 잠깐 기다리고, 그래도 아니면 창을 다시 연다."""
    for _ in range(3):
        if bot.exists(c["title"]):
            return
        monitor.of(bot).check(_ctx("미션 창 확인"), guard=False)
        bot.sleep(0.8, 1.0)
    open_window(bot, c)


def _gift_taken(bot: Bot, mark: int, left: int) -> bool:
    """방금 누른 '선물 받기'가 받아졌나. 패킷(받기 성공) → CLI(못 받은 수가 줄었나) 순서로 본다."""
    if bot.packets.ok:
        seen = bot.packets.wait(("dm.reward_ok", "dm.reward_fail"), 4, after=mark)
        if seen is not None:
            return seen.key == "dm.reward_ok"
    try:
        wait_until(bot, lambda: len(unclaimed(bot)) < left, 4, interval=1, what="선물 받기")
        return True
    except StepTimeout:
        return False


def _gift_buttons(bot: Bot, c: dict) -> list:
    """보이는 '선물 받기'. 창이 열리거나 스크롤이 멈추는 연출 중에는 점수가 0.74 까지 떨어지므로
    (2026-10-25 1초 간격 기록) 한 장만 보고 없다고 하지 않고 조금 뒤 다시 본다."""
    for i in range(3):
        buttons = bot.find_all(c["gift"])
        if buttons or i == 2:
            return buttons
        bot.sleep(0.4, 0.5)
    return []


def claim_gifts(bot: Bot, c: dict) -> int:
    """CLI 가 '다 했는데 선물 안 받음'이라고 하는 미션이 없어질 때까지, 목록을 위에서부터 훑으며
    보이는 '선물 받기'를 하나씩 누르고 받아졌는지 확인한다. 받은 개수 반환."""
    n = 0
    for r in range(c["gift_rounds"]):
        left = len(unclaimed(bot))
        if not left:
            break
        if r:
            # 다시 훑을 때는 창을 새로 연다 — 새로 열면 선물을 받을 카드가 맨 위로 모인다 (2026-10-25 실측).
            # 연금술에서 ESC 로 돌아온 창에서 맨 윗줄 선물 2개를 세 번 훑고도 못 찾은 적이 있다
            bot.log.info(f"못 받은 선물 {left}개 → 미션 창을 다시 열어 찾음")
            open_window(bot, c)
        else:
            _ensure_window(bot, c)
        for _ in _list_views(bot, c):
            while left:
                buttons = _gift_buttons(bot, c)
                if not buttons:
                    break
                mark = bot.packets.mark()
                bot.click(buttons[0])
                if not _gift_taken(bot, mark, left):
                    bot.log.info("'선물 받기'를 눌렀는데 받아지지 않음")
                    break
                n, left = n + 1, left - 1
                bot.sleep(0.6, 0.9)
                _ensure_window(bot, c)
            if not left:
                break
    _scroll_list(bot, c, 15)
    return n


def claim_milestones(bot: Bot, c: dict) -> int:
    """상단 누적 보상 중 받을 수 있는 것(라벨이 크고 노란 상태)을 누른다."""
    n = 0
    y0, y1 = c["milestone_label_y"]
    _ensure_window(bot, c)
    _scroll_list(bot, c, 15)
    for x in c["milestone_x"]:
        crop = bot.frame()[y0:y1, x - 25:x + 25].reshape(-1, 3).astype(int)
        yellow = ((crop[:, 2] > 200) & (crop[:, 1] > 150) & (crop[:, 0] < 120)).mean()
        if yellow > 0.08:
            mark = bot.packets.mark()
            bot.click((x, c["milestone_icon_y"]))
            if not bot.packets.ok or bot.packets.wait("dm.milestone_ok", 4, after=mark):
                n += 1
            bot.sleep(1.2, 1.5)
            _ensure_window(bot, c)
    return n


def find_go_button(bot: Bot, c: dict, keyword: str):
    """제목에 keyword 가 들어간 카드의 '진행하기' 버튼. 목록을 내려가며 찾는다.
    OCR 이 받침을 틀리기도 하므로 (꼬르륵 → 꼬르록) keyword 는 제목 앞 두 글자 정도로 준다."""
    dx, dy, w, h = c["card_title_offset"]
    for _ in _list_views(bot, c):
        frame = bot.frame()
        for b in bot.find_all(c["go"]):
            region = [b.x + dx, b.y + dy, w, h]
            if has_word(keyword, read_ko(frame, region), read_text(frame, region, white=180)):
                return b
    return None


def do_alchemy(bot: Bot, c: dict, m: dict) -> str:
    """연금술 미션 카드 '진행하기' → 보석 연금술 → 재료 자동 넣기 → 모두 승급 1회 → 미션 창으로."""
    a = c["alchemy"]
    go = find_go_button(bot, c, m["Title"][:2])
    if not go:
        return f"연금술 미션 카드를 찾지 못함 → {bot.snapshot('alchemy').name}"
    # 진행하기 → 연금술 창. 안 열리면 카드 자리가 아직 미션 창일 때만 한 번 더 (다른 창 위를 누르지 않게)
    if not monitor.of(bot).act(_ctx("연금술"), "연금술 진행하기", lambda: _press(bot, c, go),
                               lambda: bot.exists(a["title"]), within=10):
        return f"연금술 창이 열리지 않음 → {bot.snapshot('alchemy').name}"
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
        mark = bot.packets.mark()
        bot.key("a")  # '모두 승급' (A 배지)
        result = "연금술 완료"
        try:
            _wait_done(bot, a["mission_keyword"], 20, mark, "연금술 미션 완료", interval=2)
        except StepTimeout:
            result = _upgrade_more(bot, a)
        bot.sleep(2, 3)  # 승급 연출
    _back_to_window(bot, c)  # 승급 결과 → 보석 연금술 → 연금술 → 일일 미션 창
    return result


def _upgrade_more(bot: Bot, a: dict, tries: int = 4) -> str:
    """모두 승급 한 번으로 미션 횟수(3회)가 안 찼을 때 — 재료가 모자라 2번만 승급됨 (2026-10-28 2/3).
    골드는 상관없고 미션을 채우는 게 먼저다 (사용자). 단일 '승급'(Space) 은 쓰지 않고 '모두 승급'(A) 으로만 —
    미션이 찰 때까지 다시 누른다 (사용자 요청). '모두 승급' 버튼이 안 보이면 더 올릴 보석이 없다."""
    for _ in range(tries):
        if not _pending(bot, a["mission_keyword"]):
            return "연금술 완료"
        try:
            bot.wait(a["upgrade_all"], timeout=6)  # 승급 연출이 끝나고 버튼이 다시 보일 때까지
        except StepTimeout:
            return f"더 승급할 보석이 없어 연금술 미션 미완료 → {bot.snapshot('alchemy').name}"
        mark = bot.packets.mark()
        bot.log.info("연금술 미션이 덜 참 → '모두 승급' (A) 한 번 더")
        bot.key("a")
        try:
            _wait_done(bot, a["mission_keyword"], 20, mark, "연금술 미션 완료", interval=2)
            return "연금술 완료"
        except StepTimeout:
            pass
    return f"모두 승급을 {tries}번 더 해도 미션 미완료 → {bot.snapshot('alchemy').name}"


def do_gather(bot: Bot, c: dict, m: dict) -> str:
    """채집 미션 카드 '진행하기' → 미션 창이 닫히고 캐릭터가 근처에서 알아서 채집한다.
    CLI 로 미션 완료를 기다린 뒤 미션 창을 다시 연다."""
    g = c["gather"]
    go = find_go_button(bot, c, m["Title"][:2])
    if not go:
        return f"채집 미션 카드를 찾지 못함 → {bot.snapshot('gather').name}"
    mark = bot.packets.mark()
    # 진행하기 → 미션 창이 닫히고 채집하러 간다. 창이 그대로면 한 번 더
    if not monitor.of(bot).act(_ctx("채집"), "채집 진행하기", lambda: _press(bot, c, go),
                               lambda: not bot.exists(c["title"]), within=8):
        return f"채집 진행하기를 눌러도 미션 창이 그대로 → {bot.snapshot('gather').name}"
    try:
        _wait_done(bot, g["mission_keyword"], g["timeout"], mark, "채집 미션 완료", interval=5)
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
    # 단계: dm_open → dm_alchemy / dm_gather → dm_gifts → dm_milestones.
    # 직접 진행하는 건 연금술·채집(자급자족의 삶) 둘뿐이고, 선물·누적 보상은 맨 끝에 한꺼번에 받는다.
    # 음식 미션은 하지 않는다 — 메인 화면으로 돌아올 때 배고프면 먹는 것(bot.eat_if_hungry, 하루 2번)으로 채워진다.
    # 미션마다 진행 수·받은 선물은 CLI 가 알려 주므로 끊겨도 처음부터 다시 돌면 남은 것만 한다
    labels = {"alchemy": "연금술", "gather": "채집"}
    todo = [(key, m) for key in labels if c[key]["enabled"] and (m := _pending(bot, c[key]["mission_keyword"]))]
    bot.step("dm_open", "일일 미션 창 → 진행할 미션: " + (", ".join(labels[k] for k, _ in todo) or "없음"))
    open_window(bot, c)
    notes = []
    for key, m in todo:
        bot.step(f"dm_{key}", f"{labels[key]} 미션 ({m.get('CurrentCount')}/{m.get('GoalCount')})")
        notes.append((do_alchemy if key == "alchemy" else do_gather)(bot, c, m))

    bot.step("dm_gifts", "선물 받기")
    gifts = claim_gifts(bot, c)
    bot.step("dm_milestones", "누적 보상 받기")
    milestones = claim_milestones(bot, c)

    ignore = set(c.get("ignore", []))  # 다른 숙제를 하다 저절로 깨지는 미션은 미완료로 알리지 않는다
    pending = [f"{m['Title']}({m['Description']} {m['CurrentCount']}/{m['GoalCount']})"
               for m in missions(bot) if not m.get("IsCompleted") and m["Title"] not in ignore]
    missed = [m["Title"] for m in unclaimed(bot)]
    shot = bot.snapshot("dm_missed").name if missed else ""  # 왜 못 찾았는지 볼 수 있게 미션 창을 남긴다
    bot.to_main()
    summary = f"선물 {gifts}개, 누적 보상 {milestones}개"
    if notes:
        summary += ", " + ", ".join(notes)
    if pending:
        summary += f", 미완료: {', '.join(pending)}"
    if missed:
        summary += f", 못 받은 선물: {', '.join(missed)} → {shot}"
    # 직접 하는 미션이 남았으면 실패로 남겨 다음에 다시 한다 — 연금술 2/3 인 채 OK 로 기록돼 다시 돌려도
    # '오늘 완료' 로 건너뛰었다 (2026-10-28)
    if own_pending(bot, c):
        raise CannotProceed(summary)
    return summary


def claim_leftovers(bot: Bot, cfg: dict) -> str | None:
    """캐릭터의 숙제가 다 끝난 뒤: 일일 미션보다 뒤에 한 숙제(아르바이트 → '따뜻한 손길')나 나중에 먹은 음식으로
    새로 깬 미션의 선물만 받는다. 받을 게 없으면 창을 열지 않는다 (CLI 로만 본다)."""
    c = cfg["daily_mission"]
    if not bot.state.available() or not unclaimed(bot):
        return None
    open_window(bot, c)
    gifts = claim_gifts(bot, c)
    milestones = claim_milestones(bot, c)
    bot.to_main()
    return f"선물 {gifts}개, 누적 보상 {milestones}개"
