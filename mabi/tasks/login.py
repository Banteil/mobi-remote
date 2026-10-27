"""타이틀/캐릭터 선택 화면에서 지정한 캐릭터로 필드 메인 화면까지 진입.

캐릭터는 선택 화면에서의 순서(slot)로 고른다 (profile.json 에 사용자가 입력).
카드는 생성 순으로 한 줄에 columns 개씩 놓이고, 보유 캐릭터 수는 화면의 카드 수로 센다. 카드 위치는 고정 좌표 대신 카드 우상단
'•••' 버튼을 화면에서 찾아 계산하고, 스크롤이 실제로 됐는지와 노란 선택 테두리가
그 카드에 생겼는지 확인한 뒤에만 게임 시작을 누른다 (엉뚱한 캐릭터 접속 방지).
첫 줄은 스크롤 맨 위, 마지막 줄은 스크롤 맨 아래에서 고른다. 카드 수는 스크롤 맨 위에서 보이는
카드로 세므로 두 줄(columns * 2개)까지 지원한다.

오전 6시 이후 캐릭터가 처음 접속하면 메인 화면 전에 이런 화면이 순서 없이 나올 수 있다 (settle_first_login):
- 출석 대사 → (버튼 없는 첫 대사는 3초쯤 뒤 화면 클릭) → '출석부 건너뛰기' → '출석 완료' 확인(Space)
- '새로운 이벤트' 안내 창 → 닫기
- '오늘의 스텔라 픽' → 아무 카드나 골라 '스텔라 픽' (Space)
- 공지사항 웹 팝업 → ESC
"""
import time

import numpy as np

from .. import gamedata as gd
from .. import situation
from ..bot import AuthBlocked, Bot, StepTimeout
from ..vision import Match


class SelectFailed(StepTimeout):
    pass


_last_login = 0.0  # 마지막으로 '게임 시작'을 누른 시각 (monotonic)


def _rows(menus: list[Match], tol: int = 20) -> list[list[Match]]:
    """'•••' 위치를 줄 단위로 묶는다 (위 → 아래, 줄 안에서는 왼쪽 → 오른쪽)."""
    rows: list[list[Match]] = []
    for m in sorted(menus, key=lambda m: (m.y, m.x)):
        if rows and abs(rows[-1][0].y - m.y) <= tol:
            rows[-1].append(m)
        else:
            rows.append([m])
    return [sorted(r, key=lambda m: m.x) for r in rows]


def _is_selected(frame: np.ndarray, menu: Match, cs: dict) -> bool:
    """카드 왼쪽 테두리에 노란 선택 테두리가 있는지."""
    dx0, dx1 = cs["border_dx"]
    y = menu.y + cs["border_dy"]
    strip = frame[y - 20:y + 20, max(0, menu.x + dx0):menu.x + dx1].reshape(-1, 3).astype(int)
    target = np.array(cs["border_bgr"])
    close = np.abs(strip - target).max(axis=1) <= 40
    return int(close.sum()) >= 20


def _scroll(bot: Bot, cs: dict, notches: int) -> None:
    bot.scroll(*cs["scroll_at"], notches)
    bot.sleep(1.0, 1.4)


def _scrolled_rows(bot: Bot, cs: dict, top: bool) -> list[list[Match]] | None:
    """스크롤 맨 위(top) 또는 맨 아래로 보낸 뒤 '•••' 줄 목록. 스크롤이 확인되지 않으면 None.
    맨 위면 첫 줄이 제자리에 있어야 하고, 맨 아래면 첫 줄이 화면 밖으로 밀려나야 한다."""
    for attempt in range(4):
        _scroll(bot, cs, cs["scroll_notches"] if top else -cs["scroll_notches"])
        rows = _rows(bot.find_all(cs["card_menu"]))
        top_visible = bool(rows) and abs(rows[0][0].y - cs["top_menu_y"]) <= 30
        if rows and top_visible == top:
            return rows
        bot.log.debug(f"캐릭터 선택: 스크롤 확인 실패 (시도 {attempt + 1}), rows={[len(r) for r in rows]}")
    return None


def count_characters(bot: Bot, cfg: dict) -> int:
    """선택 화면의 캐릭터 수 (스크롤 맨 위에서 보이는 카드 수)."""
    rows = _scrolled_rows(bot, cfg["charselect"], top=True)
    if rows is None:
        raise SelectFailed(f"캐릭터 카드를 찾지 못함 → {bot.snapshot('charselect').name}")
    return sum(len(r) for r in rows)


def select_character(bot: Bot, cfg: dict, character: dict) -> None:
    cs = cfg["charselect"]
    name = character.get("name", f"슬롯 {character['slot']}")
    total = count_characters(bot, cfg)  # 스크롤 맨 위 상태가 된다
    if character["slot"] > total:
        raise SelectFailed(f"{name}: 캐릭터가 {total}개뿐이라 슬롯 {character['slot']} 이 없음")
    row, col = divmod(character["slot"] - 1, cs["columns"])
    last_row = (total - 1) // cs["columns"]
    if row not in (0, last_row):
        raise SelectFailed(f"{name}: 세 줄 이상인 캐릭터 목록은 지원하지 않음")

    rows = _scrolled_rows(bot, cs, top=row == 0)
    r = (rows[0] if row == 0 else rows[-1]) if rows else []
    if col >= len(r):
        raise SelectFailed(f"{name}: 캐릭터 카드 위치를 찾지 못함 → {bot.snapshot('charselect').name}")
    target = r[col]

    ox, oy = cs["card_click_offset"]
    x, y = target.x + ox, target.y + oy
    if y > cs["max_click_y"]:
        raise SelectFailed(f"{name}: 카드 클릭 위치가 게임 시작 버튼과 겹침 (y={y})")

    for _ in range(2):
        bot.click((x, y))
        bot.sleep(0.8, 1.2)
        frame = bot.frame()
        menus = bot.vision.find_all(frame, cs["card_menu"])
        # 클릭 후 같은 자리의 카드가 선택됐는지 (스크롤이 움직였으면 실패로 본다)
        same = next((m for m in menus if abs(m.x - target.x) <= 6 and abs(m.y - target.y) <= 6), None)
        if same and _is_selected(frame, same, cs):
            bot.log.info(f"{name} 선택 확인")
            return
    raise SelectFailed(f"{name}: 선택 테두리 확인 실패 → {bot.snapshot('charselect').name}")


def settle_first_login(bot: Bot, cfg: dict, timeout: float) -> list[str]:
    """접속 직후 화면들(출석 대사, 새 이벤트 창, 스텔라 픽, 공지 팝업 …)은 점검자가 처리하고, 메인 화면이 몇 번 이어지면 끝낸다.
    처리한 것 목록 반환. 버튼 없는 출석 첫 대사만 여기서 본다 (알아볼 표시가 없다)."""
    from .. import monitor
    c = cfg["login"]
    mon = monitor.of(bot)
    # 대화는 넘기지 않는다 — 출석은 '출석부 건너뛰기' 로만 ('대화 넘기기' 는 다른 대사로 이어진다, 사용자 2026-10-22)
    ctx = monitor.Ctx("login", "접속 직후", talk=False)
    handled = []
    end = time.monotonic() + timeout
    stable = unknown = 0
    while stable < 3:
        if time.monotonic() > end:
            raise StepTimeout(f"접속 후 메인 화면이 안정되지 않음 → {bot.snapshot('login').name}")
        bot.sleep(1.2, 1.6)
        seen = mon.check(ctx, guard=False)
        if seen.done:
            stable = unknown = 0
            if seen.done not in monitor.WAITS and seen.done not in handled:
                handled.append(seen.done)
            continue
        if seen.what == monitor.detect.MAIN:
            stable += 1
            unknown = 0
            continue
        stable = 0
        unknown += 1
        # 출석 이벤트의 첫 NPC 대사엔 버튼이 없고 화면을 한 번 눌러야 '출석부 건너뛰기'가 나온다.
        # 대사가 뜬 뒤 한동안 입력을 안 받으므로 3초쯤 지나서 누른다 (2026-10-22 새 캐릭터로 확인).
        # 대사 화면엔 믿을 만한 표시가 없어(말풍선 아이콘은 움직임) '모르는 화면 + 로딩 아님(CLI)' 으로 판단한다
        # 아무것도 처리하기 전(=첫 대사)에만 누른다. '출석 완료' 연출 중에 누르면 가운데 보상 아이템이 눌린다
        if not handled and unknown in (2, 6) and bot.in_game():
            bot.log.info("버튼 없는 화면이 이어짐 (출석 대사) → 화면 한 번 클릭")
            bot.snapshot("first_dialog")
            bot.click(tuple(c["first_dialog_xy"]))
            continue
        if unknown % 10 == 0:  # 모르는 창(채팅 입력 등)이 열려 HUD 가 가려졌을 수 있다 → ESC 로 정리 시도
            try:
                bot.to_main(tries=3)
            except StepTimeout:
                pass
    return handled


def _auth_names(bot: Bot) -> list[str]:
    """접속 오류 창들. 보통 '계정 인증 실패' → 확인 → '서버에 입장할 수 없음' 이 세트로 뜬다."""
    return [n for n in bot.ui.get("login_errors", []) if bot.vision.has(n)]


def _auth_fail_visible(bot: Bot) -> bool:
    names = _auth_names(bot)
    if not names:
        return False
    frame = bot.frame()
    return any(bot.vision.find(frame, n) for n in names)


def _clear_auth_fail(bot: Bot, cfg: dict) -> None:
    """접속 오류 창들을 확인(Space)으로 모두 닫고 타이틀이 나오면 auth_cooldown 초 쉰다.
    한 실행(bot)에서 두 번째면 더 시도하지 않고 AuthBlocked (계속 두드리면 더 꼬일 수 있다)."""
    bot.auth_fails = getattr(bot, "auth_fails", 0) + 1
    shot = bot.snapshot("auth_fail").name
    if bot.auth_fails >= 2:
        raise AuthBlocked(f"접속 오류(계정 인증 실패)가 다시 남 → 실행을 멈춥니다. 게임에서 확인 후 직접 로그인해 주세요 → {shot}")
    bot.log.warning(f"접속 오류 창 → 확인 누르고 {cfg['login']['auth_cooldown']}초 쉰 뒤 다시 접속 → {shot}")
    names, title = _auth_names(bot), bot.ui["title_start"]
    for _ in range(4):  # 창이 연달아 뜬다 → 타이틀이 나올 때까지 확인
        bot.key("space")
        try:
            m = bot.wait_any([title, *names], timeout=30)
        except StepTimeout:
            break  # 아래 접속 흐름이 다시 화면을 기다린다
        if m.name == title:
            break
        bot.log.info(f"접속 오류 창 이어짐: {m.name} → 확인")
        bot.sleep(1, 1.5)
    bot.sleep(cfg["login"]["auth_cooldown"])


NAME_AREA = gd.region("main_name")  # 메인 화면 왼쪽 위 캐릭터 이름 줄 [x, y, w, h] (위 줄은 타이틀)


def _norm_name(t: str) -> str:
    return "".join(t.split())


def current_name(bot: Bot) -> str:
    """접속한 캐릭터 이름. 패킷이 알면 그것 (화면과 상관없이 정확하다), 모르면 메인 화면 왼쪽 위를 OCR.
    CLI get_my_info 에는 이름이 없다. 못 읽으면 ''. OCR 은 메인 화면일 때만 (창이 열려 있으면 그 자리에 다른 것이 있다)."""
    p = bot.packets
    if p.at_charselect():
        return ""
    if p.ok and p.state.my_name and not p.state.loading:
        return _norm_name(p.state.my_name)
    if not bot.at_main():
        return ""
    return name_in_frame(bot.frame())


def _name_score(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, _norm_name(a), _norm_name(b)).ratio()


def name_matches(read: str, name: str) -> bool:
    """OCR 로 읽은 이름이 이 캐릭터 이름인가. 한글 OCR 은 받침·자모를 한두 글자 틀린다
    (2026-10-23 첫 글자 '옥' → '목') → 글자 수가 같고 대부분 맞으면 같은 이름으로 본다."""
    a, b = _norm_name(read), _norm_name(name)
    if not (a and b):
        return False
    if a == b:
        return True
    # 세 글자 이상이고 같은 자리 한 글자만 다르면 ('ㅡ' → 'ㅗ' 등) — 짧은 이름은 비율로는 못 잡는다
    if len(a) == len(b) >= 3 and sum(x != y for x, y in zip(a, b)) == 1:
        return True
    return abs(len(a) - len(b)) <= 1 and _name_score(a, b) >= 0.75


def snap_name(read: str, names) -> str:
    """읽은 이름을 등록된 캐릭터 이름 중 가장 가까운 것으로 맞춘다 (확실할 때만). 없으면 읽은 그대로."""
    hits = sorted(((_name_score(read, n), n) for n in names if name_matches(read, n)), reverse=True)
    if hits and (len(hits) == 1 or hits[0][0] - hits[1][0] >= 0.1):
        return _norm_name(hits[0][1])
    return _norm_name(read)


def name_in_frame(frame) -> str:
    """찍어 둔 메인 화면에서 왼쪽 위 캐릭터 이름 (메인 화면인지는 부르는 쪽이 본다). 못 읽으면 ''."""
    from .. import ocr
    texts = [t for t, _, _ in ocr.find_texts(frame, NAME_AREA)]
    return _norm_name(texts[0]) if len(texts) == 1 else ""


def _leave_dungeon(bot: Bot) -> bool:
    """던전 안이거나 클리어/보상 화면에 남아 있으면 (중단·충돌 뒤 다시 시작한 경우) 마무리하고 나온다."""
    from .content import after_clear, dungeon_state, game_space, hunt_quest, inside_space, play_dungeon, wait_field, wait_until
    ui = bot.ui
    # 끊긴 숙제가 요일 던전이면 보상 화면에서 추가 루팅까지 (그냥 나가면 숙제 쪽은 일일 달성만 보고 끝내 추가 루팅이 빠진다)
    prog = bot.daily.progress() if bot.daily else None
    cut = prog.get("task") if prog and bot.character and prog.get("slot") == bot.character.get("slot") else None
    extra_loot = int(bot.cfg["weekday_dungeon"].get("extra_loot", 0) or 0) if cut == "weekday_dungeon" else 0
    # 검은 구멍·사냥터 안에서 끊겼으면 나가지 않고 끝날 때까지 본다 — 캐릭터를 다시 고르면 그 판(횟수·은동전)이 날아간다.
    # 끝난 뒤 그 숙제를 하면 숙제 쪽이 게임 상태(일일 달성·은동전 수)와 자기 단계 기록을 보고 나머지만 한다
    bh = bot.cfg["black_hole"]
    if bh["space_keyword"] in game_space(bot):
        bot.step("bh_inside_at_login", "검은 구멍 안에서 시작 → 클리어까지 기다림")
        wait_until(bot, lambda: not inside_space(bot, bh["space_keyword"]), bh["clear_timeout"], interval=5,
                   what="검은 구멍 클리어")
        bot.sleep(2, 3)
        bot.dismiss_popups()
        # 사냥터 안의 검은 구멍이었으면 사냥터로 돌아온다 — 끝나지 않은 사냥터를 이어서 본다 (은동전은 이미 나갔다)
        if not _in_field(bot):
            return True
    if _in_field(bot):
        hunt = hunt_quest(bot) or "패킷"
        bot.step("field_inside_at_login", f"사냥터 안에서 시작 ({hunt}) → 클리어까지 기다림")
        wait_field(bot, "", bot.cfg["silver"]["field_timeout"])
        return True
    state = dungeon_state(bot)  # 패킷, 모르면 CLI
    if state == "InProgress":
        bot.step("dungeon_inside_at_login", "던전 안에서 시작 → 클리어까지 기다렸다가 나옴")
        play_dungeon(bot, bot.cfg["tribute"]["clear_timeout"], extra_loot)
        return True
    if state == "Cleared" or bot.exists(ui["dungeon_touch"]) or bot.exists(ui["reward_exit"]):
        bot.step("dungeon_reward_at_login", "던전 클리어 화면에서 시작 → 보상 받고 나옴")
        after_clear(bot, extra_loot)
        return True
    return False


def _in_field(bot: Bot) -> bool:
    """사냥터 안인가. 패킷이 알면 사냥터 상태로, 모르면 진행 중인 사냥터 퀘스트(CLI)가 있는 것으로."""
    from .content import hunt_quest
    st = bot.packets.state
    if bot.packets.ok and st.field_state is not None:
        return st.field_state in ("InProgress", "WaitingForChannelTransfer")
    return bool(hunt_quest(bot))


def run(bot: Bot, cfg: dict, character: dict | None = None) -> str:
    """NPC 대화를 스스로 다루는 일 — 그동안 대화는 끼어들기로 넘기지 않는다 (Bot.npc_talk, monitor.interrupts)."""
    with bot.npc_talk():
        return _task(bot, cfg, character)


def _task(bot: Bot, cfg: dict, character: dict | None = None) -> str:
    """character 가 None 이면 현재(또는 마지막) 캐릭터로 접속.
    '계정 인증 실패' 창이 있거나 접속 중에 뜨면 확인 → 쉬었다가 한 번 더 시도한다."""
    for attempt in range(2):
        if _auth_fail_visible(bot):
            _clear_auth_fail(bot, cfg)
        try:
            return _run(bot, cfg, character)
        except StepTimeout:
            if attempt or not _auth_fail_visible(bot):
                raise
    raise AssertionError("unreachable")


def _run(bot: Bot, cfg: dict, character: dict | None) -> str:
    c, ui = cfg["login"], bot.ui
    main, title, charsel = ui["main_hud"], ui["title_start"], ui["charselect_title"]
    name = character.get("name", f"슬롯 {character['slot']}") if character else "현재 캐릭터"
    auth = _auth_names(bot)

    def wait_screen_for(names: list[str], timeout: float) -> Match:
        """화면 대기 중 접속 오류 창이 뜨면 바로 StepTimeout (run 이 처리) — 180초를 버리지 않게."""
        m = bot.wait_any([*names, *auth], timeout=timeout)
        if m.name in auth:
            raise StepTimeout(f"접속 오류 창 ({m.name})")
        return m

    def wait_screen(names: list[str]) -> Match:
        return wait_screen_for(names, c["timeout"])

    if bot.state.available() or bot.packets.ok:  # 던전·사냥터 상태는 패킷만으로도 안다
        _leave_dungeon(bot)

    # NPC 대화(아르바이트 메뉴·전달 창 등)에 멈춰 있으면 ESC 로는 안 닫히고 (to_main 이 헛돈다) 닫혀도 그 일이 날아간다
    # → 아르바이트 정리로 끝까지 넘긴다 (Space 선택지면 진행). 2026-10-22 케이틴 메뉴에서 이어 하다 26초 헛돎
    from .arbeit import _settle
    from .dialogue import in_dialog
    if bot.state.available() and in_dialog(bot):
        bot.log.info("NPC 대화 중에 시작 → 대화부터 정리")
        _settle(bot)
    # 어디서 켰든 지금 상황(situation.look)을 보고 메인 화면까지 — 작별 대사('벌써 가?')·출석·전달 창·던전 창 등
    # (2026-10-26 전달 창을 닫은 뒤 이어 하기 — 작별 대사 화면에서 메인 화면을 1분 넘게 기다림)
    at = situation.look(bot)
    if at not in (situation.MAIN, situation.LOADING, situation.CHARSELECT, situation.TITLE, situation.DIALOG):
        bot.log.info(f"시작 상황: {at} → 메인 화면으로")
        situation.to_main(bot, 30)

    # 게임 안에서 창(지도, 퀘스트 등)이 열려 있으면 어느 화면인지 판단할 수 없으므로 먼저 닫는다
    if not bot.at_main() and not (bot.exists(title) or bot.exists(charsel)):
        try:
            bot.to_main(tries=4)
        except StepTimeout:
            pass  # 로딩 중 등. 아래에서 화면이 나타날 때까지 기다린다

    if bot.at_main():
        if character is None:
            bot.dismiss_popups()
            return "이미 접속 중"
        # 왼쪽 위 이름이 이 캐릭터면 다시 고르지 않는다 (접속 전환을 아끼고, 하던 숙제를 그 자리에서 이어 한다)
        now = current_name(bot)
        if name_matches(now, character.get("name", "")):
            bot.log.info(f"이미 {character['name']} 로 접속 중 (화면 이름 확인) → 다시 고르지 않음")
            bot.dismiss_popups()
            bot.to_main()
            return f"{name} 이미 접속 중"
        bot.log.info(f"지금 캐릭터: {now or '이름을 못 읽음'} → {name} 로 다시 고름")
        bot.to_charselect()

    m = wait_screen([main, charsel, title])
    bot.log.debug(f"접속 시작 화면: {m.name}")
    if m.name == title:
        bot.click(m)
        m = wait_screen([main, charsel])
    if m.name == main and character is not None:  # 타이틀에서 바로 마지막 캐릭터로 들어간 경우
        bot.to_charselect()
        m = bot.wait(charsel)

    if m.name == charsel:
        bot.sleep(1.5, 2)  # 카드 목록 표시 대기
        if character is not None:
            try:
                select_character(bot, cfg, character)
            except SelectFailed as e:  # 화면 전환 직후 카드가 움직이는 중일 수 있다
                bot.log.warning(f"캐릭터 선택 실패, 다시 시도: {e}")
                bot.sleep(3, 4)
                select_character(bot, cfg, character)
        global _last_login
        wait = c["min_interval"] - (time.monotonic() - _last_login)
        if _last_login and wait > 0:
            bot.log.info(f"접속 간격 유지: {wait:.0f}초 대기")  # 너무 잦은 접속 전환은 게임 오류를 부른다
            bot.sleep(wait)
        bot.wait(ui["charselect_start"], timeout=10)
        mark = bot.packets.mark()
        bot.key("space")  # '게임 시작' 단축키. 클릭보다 확실하다
        t0 = _last_login = time.monotonic()
        # 입력이 무시되는 경우가 있다 → 선택 화면이 그대로면 다시 누른다
        for _ in range(3):
            # 패킷: 게임 서버 입장(in_game)·맵 로딩이 오면 눌린 것 — 바로 넘어간다. 모르면 5초 뒤 화면으로
            started = bot.wait_packet(lambda s: bool(s.in_game) or s.loading, 5)
            if started is None:
                bot.sleep(5)
            if started or not bot.exists(charsel):
                break
            bot.log.info("게임 시작이 눌리지 않음 → 다시 시도")
            bot.key("space")
        closers = [n for n in ui["popup_closers"] if bot.vision.has(n)]
        first = [c["stella_title"], c["notice_webview"], c["attendance_skip"], c["event_popup_close"],
                 ui["scene_skip"]]  # 하루 첫 접속 화면
        # 출석 첫 대사처럼 아는 버튼이 하나도 없는 화면도 있다 → 로딩이 끝나 게임 안(CLI)이면 settle 로 넘긴다
        end = time.monotonic() + c["timeout"]
        while True:
            try:
                m = wait_screen_for([main, *first, *closers], 6)
                bot.log.debug(f"게임 시작 → {m.name} ({time.monotonic() - t0:.0f}s)")
                break
            except StepTimeout:
                if _auth_fail_visible(bot):
                    raise
                # 게임 안인가: 패킷(게임 시작 뒤 맵에 들어감, 로딩 끝) 또는 CLI
                p = bot.packets
                entered = p.ok and p.find("channel.entering", mark) is not None and not p.state.loading
                if entered or bot.state.query("get_my_info") is not None:
                    bot.log.debug(f"게임 시작 → 버튼 없는 화면, 게임 안 ({time.monotonic() - t0:.0f}s)")
                    break
                if time.monotonic() > end:
                    raise StepTimeout(f"{name} 접속 후 메인 화면이 나타나지 않음 → {bot.snapshot('login').name}")

    bot.state.available(refresh=True)
    handled = settle_first_login(bot, cfg, c["settle_timeout"])
    situation.attendance_done(bot)
    if handled:
        bot.log.info(f"접속 직후 화면 처리: {', '.join(handled)}")
    closed = bot.dismiss_popups()
    bot.to_main()
    extra = handled + ([f"팝업 {closed}개"] if closed else [])
    return f"{name} 접속 완료" + (f" ({', '.join(extra)})" if extra else "")
