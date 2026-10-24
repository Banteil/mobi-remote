"""어비스 반복 플레이. 일일 숙제와 따로, 사람이 멈추거나(F12) 정한 횟수·시간이 될 때까지 같은 어비스를 다시 돈다.

흐름 (2026-10-23 '허상의 정박지' 로 확인):
  메뉴(ESC) → '어비스' → 오른쪽 목록에서 던전 → 입장 화면('함께하기' · 난이도 · '우연한 만남' 켬) → '입장하기'
  → 우연한 만남 매칭 (모두 모이면 자동 입장) → 들어가면 숏컷 자동 진행·자동 전투가 저절로 켜진다
  → 클리어하면 '던전 클리어 / 화면을 터치해 주세요' → 보상 화면(나가기 ESC / 다시 하기 Space / 다른 던전 가기)
  → '다시 하기' = 같은 던전·난이도로 다시 매칭 → 4초 세고 입장
쓰러지면 '행동불능' + '남은 부활 횟수 N/3' 과 오른쪽 아래 '여신상에서 부활'(R) / '여기서 부활'(아이템 1개) 이 뜬다.
'여기서 부활' 을 누르고 그 판을 이어 한다 (2026-10-24 확인 — 누르면 IsDead 가 false, IsReviving 이 true 로 남는다).
부활 횟수를 다 썼거나 함께하기에서 전멸해 '여기서 부활' 이 막히면 망설이지 않고 나간다 (사용자 규칙):
오른쪽 맨 위 나가기 버튼 → '던전에서 퇴장하시겠습니까?' 나가기(Space) → 처음부터 다시 입장한다.
어비스 안은 CLI 가 던전으로 치지 않는다 (Dungeon.State 가 NotInDungeon). 그래서 안에 있는지는 나가기 버튼으로,
끝났는지는 get_activity 의 IsAbyssResultSequencePlaying 과 클리어 화면으로 본다.
"""
import ctypes
import time

from .. import gamedata as gd
from ..bot import Bot, StepTimeout
from ..ocr import find_texts
from .content import CannotProceed, touch_prompt_visible

DIFFICULTIES = ["입문", "어려움", "매우 어려움", "매우 어려움2"]


def _norm(t: str) -> str:
    return "".join(t.split())


def _find_text(bot: Bot, want: str, region=None, exact: bool = True):
    w = _norm(want)
    for t, x, y in find_texts(bot.frame(), region):
        n = _norm(t)
        if n == w if exact else w in n:
            return x, y
    return None


def _click_text(bot: Bot, want: str, region=None, exact: bool = True, what: str = "", tries: int = 4) -> None:
    for _ in range(tries):
        hit = _find_text(bot, want, region, exact)
        if hit:
            bot.click(hit)
            bot.sleep(1.2, 1.6)
            return
        bot.sleep(1.0, 1.4)
    raise CannotProceed(f"'{what or want}' 를 화면에서 찾지 못함 → {bot.snapshot('abyss').name}")


def inside(bot: Bot) -> bool:
    """어비스(던전) 안 — 오른쪽 맨 위 나가기 버튼이 보인다."""
    return bot.exists(bot.ui["abyss_exit"])


def _chance_on(bot: Bot) -> tuple[bool, tuple[int, int]] | None:
    """입장 화면 '우연한 만남' 토글이 켜져 있나 (켜지면 초록), 토글 자리. 글자를 못 찾으면 None."""
    hit = _find_text(bot, gd.text("abyss_chance"), gd.region("abyss_entry_right"))
    if not hit:
        return None
    x, y = hit[0] + 95, hit[1]  # 토글은 글자 오른쪽 (1920 기준 약 95px)
    patch = bot.frame()[y - 6:y + 6, x - 20:x + 20].reshape(-1, 3).astype(int)
    green = ((patch[:, 1] > 150) & (patch[:, 2] < 120) & (patch[:, 0] < 150)).mean()
    return green > 0.2, (x, y)


def _wait_settled(bot: Bot, timeout: float) -> bool:
    """로딩·자동 이동이 끝나 메인 화면이 보일 때까지. 보이면 True.
    로딩이 끝났는데(CLI 가 답함) 메인 화면이 아니면 막는 창을 넘긴다 — 판을 마치고 나가거나 캐릭터를 바꾸려는 순간
    퀘스트 완료 창이 뜨면 그대로 서 있었다 (2026-10-24 사용자)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        act = bot.state.activity() if bot.state.available() else None
        if not (act or {}).get("IsAutoTraveling") and bot.at_main():
            return True
        if act is not None:
            bot.clear_blockers(ocr=True)
        bot.sleep(2, 2.5)
    return False


def _travel_to_entry(bot: Bot) -> None:
    """입장 화면 버튼이 '이동하기' 다 — 캐릭터가 어비스 입구에서 멀다 (캐릭터를 바꾸면 그 캐릭터가 마지막에 있던 곳에서
    시작해 거의 늘 이렇다 — 2026-10-24 '입장하기' 만 기다리다 실패). 눌러서 입구로 가고, 멀면 빠른 이동(T)."""
    bot.log.info("어비스 입구에서 멂 → 이동하기")
    _click_text(bot, gd.text("abyss_move"), gd.region("abyss_entry_right"), what="이동하기")
    bot.sleep(2, 3)
    key = bot.cfg["game"].get("fast_travel_key")
    act = (bot.state.activity() if bot.state.available() else None) or {}
    if key and act.get("IsAutoTraveling") and act.get("AutoTravelRemainingPositionCount", 0) > 0:
        bot.log.info("빠른 이동")
        bot.key(key)
    if not _wait_settled(bot, bot.cfg["abyss"].get("travel_timeout", 300)):
        raise CannotProceed(f"어비스 입구로 가지 못함 → {bot.snapshot('abyss_travel').name}")


def _entry_button(bot: Bot) -> str:
    """입장 화면 오른쪽 아래 버튼: 'enter'(입장하기) · 'move'(이동하기) · ''(둘 다 없음 — 매칭 중 등)."""
    texts = [_norm(t) for t, _, _ in find_texts(bot.frame(), gd.region("abyss_entry_right"))]
    if _norm(gd.text("abyss_enter")) in texts:
        return "enter"
    if _norm(gd.text("abyss_move")) in texts:
        return "move"
    return ""


def where(bot: Bot, dungeon: str) -> str:
    """지금 어느 화면인가 — 어디서 시작해도 그 자리부터 잇는다 (2026-10-24: 입장 화면을 띄운 채 시작하면
    메인 화면만 기다리며 멍하니 있었다).
      play     어비스 안 (나가기 버튼)              reward  클리어·보상 화면
      main     필드 메인 화면                       menu    메뉴(ESC)가 열려 있음
      entry    입장 화면 (위쪽 '혼자하기 / 함께하기' 탭)
      matching 입장 화면인데 입장하기·이동하기 버튼이 없음 — 매칭 중으로 본다 (매칭 중 화면은 아직 못 봤다)
      list     어비스 목록 (dungeon 이름이 오른쪽 목록에)
      loading  CLI 가 답하지 않음 (로딩 중엔 get_activity 가 오류)   other  그 밖의 창 — ESC 로 닫으면 된다"""
    if inside(bot):
        return "play"
    if after_clear(bot):
        return "reward"
    if bot.at_main():
        return "main"
    if bot.exists(bot.ui["menu_quit"]):
        return "menu"
    if _find_text(bot, gd.text("abyss_together"), gd.region("abyss_entry_top")):
        return "entry" if _entry_button(bot) else "matching"
    if _find_text(bot, dungeon, gd.region("abyss_list")):
        return "list"
    if bot.state.available() and bot.state.activity() is None:
        return "loading"
    return "other"


def where_settled(bot: Bot, dungeon: str) -> str:
    """where, 단 로딩 중이면 끝날 때까지 (상한 timing.loading)."""
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while (at := where(bot, dungeon)) == "loading" and time.monotonic() < end:
        bot.sleep(2, 2.5)
    return at


def _open_list(bot: Bot, menu_open: bool = False) -> None:
    """메인 화면 → 메뉴(ESC) → '어비스' → 어비스 목록. menu_open 이면 열린 메뉴에서 바로."""
    for _ in range(0 if menu_open else 3):
        bot.to_main()
        bot.key("esc")
        bot.sleep(1.5, 1.8)
        if _find_text(bot, gd.text("abyss_menu"), gd.region("menu_right")):
            break
    _click_text(bot, gd.text("abyss_menu"), gd.region("menu_right"), what="메뉴의 어비스")
    bot.sleep(1.0, 1.5)


def open_entry(bot: Bot, dungeon: str, difficulty: str = "", _moved: bool = False, at: str = "") -> None:
    """dungeon 입장 화면을 열고 '함께하기' · 난이도 · '우연한 만남' 을 맞춘다. at(where 결과)이 입장 화면이나
    어비스 목록이면 그 자리부터, 아니면 메인 화면 → 메뉴 → 어비스 → 목록에서 dungeon.
    '함께하기' 를 먼저 고른다 — '혼자하기' 탭이면 입구에서 먼 캐릭터는 버튼이 '이동하기' 라 입장할 수 없는데,
    '함께하기' 는 어디서든 매칭된다 (2026-10-24: 혼자하기 탭에서 '입장하기' 만 찾다 실패). 그래도 '이동하기' 면
    입구로 간 뒤 한 번 더 연다."""
    if at == "entry" and not _find_text(bot, dungeon, gd.region("abyss_entry_title")):
        bot.log.info(f"다른 어비스의 입장 화면 → 닫고 '{dungeon}' 로")
        at = ""
    if at != "entry":
        if at != "list":
            _open_list(bot, menu_open=at == "menu")
        _click_text(bot, dungeon, gd.region("abyss_list"), what=f"어비스 '{dungeon}'")
        bot.sleep(1.0, 1.5)
        # 입장 화면이 열렸나: 위쪽 '혼자하기 / 함께하기' 탭 글자로 본다 (버튼 글자는 탭·위치에 따라 바뀐다)
        for _ in range(6):
            if _find_text(bot, gd.text("abyss_together"), gd.region("abyss_entry_top")):
                break
            bot.sleep(1.0, 1.4)
        else:
            raise CannotProceed(f"'{dungeon}' 입장 화면이 열리지 않음 → {bot.snapshot('abyss').name}")
    _click_text(bot, gd.text("abyss_together"), gd.region("abyss_entry_top"), what="함께하기")
    if difficulty:
        _click_text(bot, difficulty, gd.region("abyss_difficulty"), what=f"난이도 '{difficulty}'")
    # 함께하기에서 '입장하기' 가 보일 때까지 ('이동하기' 면 입구로 가서 다시)
    for _ in range(5):
        button = _entry_button(bot)
        if button == "enter":
            break
        if button == "move" and not _moved:
            _travel_to_entry(bot)
            return open_entry(bot, dungeon, difficulty, _moved=True)
        bot.sleep(1.0, 1.4)
    else:
        raise CannotProceed(f"'{dungeon}' 함께하기에 '입장하기' 가 없음 → {bot.snapshot('abyss').name}")
    on = _chance_on(bot)
    if on is None:
        raise CannotProceed(f"'우연한 만남' 을 찾지 못함 → {bot.snapshot('abyss').name}")
    if not on[0]:
        bot.click(on[1])
        bot.sleep(1.0, 1.3)
        on = _chance_on(bot)
        if not on or not on[0]:
            raise CannotProceed(f"'우연한 만남' 을 켜지 못함 → {bot.snapshot('abyss').name}")
        bot.log.info("우연한 만남 켬")


def wait_entered(bot: Bot, timeout: float) -> bool:
    """매칭(우연한 만남)이 잡혀 어비스 안으로 들어갈 때까지. 모두 모이면 저절로 들어간다. 시간 안에 못 들어가면 False."""
    end = time.monotonic() + timeout
    while not inside(bot):
        if time.monotonic() > end:
            return False
        bot.clear_blockers(ocr=True)  # 매칭 중에 퀘스트 클리어 창 등이 뜨면 입장을 막는다 (2026-10-24 06:07)
        bot.sleep(3)
    return True


def leave(bot: Bot) -> None:
    """어비스 안에서 나간다: 오른쪽 맨 위 나가기 → '던전에서 퇴장하시겠습니까?' 나가기(Space)."""
    ui = bot.ui
    for _ in range(3):
        if not inside(bot):
            bot.key("esc")  # 부활 창 등이 가리고 있으면 닫아 본다
            bot.sleep(1.0, 1.5)
            continue
        bot.click(ui["abyss_exit"])
        try:
            bot.wait(ui["abyss_exit_dialog"], timeout=5)
        except StepTimeout:
            continue
        bot.sleep(0.6, 0.9)
        bot.key("space")
        break
    else:
        raise StepTimeout(f"어비스에서 나가지 못함 → {bot.snapshot('abyss_leave').name}")
    # 밖(필드)으로 나와 메인 화면이 보일 때까지
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while inside(bot) or not bot.at_main():
        if time.monotonic() > end:
            raise StepTimeout("어비스에서 나온 뒤 메인 화면이 나오지 않음")
        if not inside(bot) and bot.state.activity() is not None:
            bot.clear_blockers(ocr=True)  # 나오면서 뜬 퀘스트 완료 창
        bot.sleep(2)


def _revives_left(bot: Bot, frame) -> int | None:
    """사망 화면 가운데 '남은 부활 횟수 N/3' 의 N. 못 읽으면 None. 함께하기 전멸('전멸하였습니다')이면 0.
    글자 칸만 잘라 읽으면 검출이 안 돼 '행동불능' 줄까지 넓게 읽는다."""
    import re
    texts = [t for t, _, _ in find_texts(frame, gd.region("abyss_revive_left"))]
    if any(gd.text("abyss_wiped") in t for t in texts):
        return 0  # 전멸이면 '여기서 부활' 버튼 자체가 없다 (2026-10-24 확인)
    for t in texts:
        m = re.search(r"(\d+)\s*/\s*\d+", t)
        if m:
            return int(m.group(1))
    return None


def revive_here(bot: Bot) -> bool:
    """사망 화면에서 '여기서 부활' 을 누른다. 부활했으면 True.
    부활 횟수가 0 이거나 버튼이 없거나 막혀 있으면(켜진 버튼은 주황) 누르지 않고 False → 나간다."""
    for _ in range(3):  # 사망 화면 버튼은 쓰러지고 1~2초 뒤에 뜬다
        frame = bot.frame()
        if any(gd.text("abyss_wiped") in t for t, _, _ in find_texts(frame, gd.region("abyss_revive_left"))):
            bot.log.warning(f"함께하기 전멸 ('여기서 부활' 없음) → 나감 ({bot.snapshot('abyss_dead').name})")
            return False
        hit = next(((x, y) for t, x, y in find_texts(frame, gd.region("abyss_revive_button"))
                    if gd.text("abyss_revive_here") in t), None)  # '여기서' — '부활' 은 '부할' 로 자주 읽힌다
        if hit:
            break
        bot.sleep(1.5, 2)
    else:
        bot.log.warning(f"'여기서 부활' 버튼이 없음 → 나감 ({bot.snapshot('abyss_dead').name})")
        return False
    left = _revives_left(bot, frame)
    x, y = hit
    patch = frame[y - 14:y + 14, max(0, x - 70):x + 70].reshape(-1, 3).astype(int)  # BGR
    orange = ((patch[:, 2] > 200) & (patch[:, 1] > 110) & (patch[:, 1] < 210) & (patch[:, 0] < 110)).mean()
    if left == 0 or orange < 0.15:
        why = "부활 횟수를 다 씀" if left == 0 else "'여기서 부활' 이 막힘 (함께하기 전멸 등)"
        bot.log.warning(f"{why} → 나감 ({bot.snapshot('abyss_dead').name})")
        return False
    bot.click(hit)
    end = time.monotonic() + 10
    while time.monotonic() < end:
        bot.sleep(1.5)
        if not (bot.state.activity() or {}).get("IsDead"):
            bot.log.info(f"여기서 부활{f' (남은 부활 {left - 1}번)' if left else ''}")
            return True
    bot.log.warning(f"'여기서 부활' 을 눌렀는데 일어나지 않음 → 나감 ({bot.snapshot('abyss_dead').name})")
    return False


def play(bot: Bot, run_timeout: float, revive: bool = True, on_revive=lambda: None) -> str:
    """어비스 안에서 끝날 때까지 지켜본다. 'clear' | 'dead' | 'timeout'.
    쓰러지면 revive 일 때 '여기서 부활' 하고 이어 한다 (못 하면 'dead' → 나가서 처음부터).
    배고프면 그때마다 음식을 먹는다 (어비스 반복은 일일 숙제의 하루 횟수 제한 없이)."""
    end = time.monotonic() + run_timeout
    while True:
        bot.sleep(3)
        act = bot.state.activity() or {}
        if act.get("IsDead"):
            if revive and revive_here(bot):
                on_revive()
                continue
            return "dead"
        if act.get("IsAbyssResultSequencePlaying"):
            return "clear"
        if inside(bot):
            if not bot.clear_blockers():  # 판 중에 깨진 퀘스트의 클리어 창·대화
                bot.eat_if_hungry()
        elif (bot.exists(bot.ui["dungeon_retry"]) or bot.exists(bot.ui["reward_exit"])
              or touch_prompt_visible(bot)):
            return "clear"  # 클리어 연출로 HUD 가 사라졌다 (CLI 를 못 읽었을 때)
        else:
            bot.clear_blockers(ocr=True)  # 나가기 버튼을 가린 창 — 퀘스트 완료 창은 템플릿이 안 맞을 때가 있어 글자로도
        if time.monotonic() > end:
            return "timeout"


def _switch_character(bot: Bot, cfg: dict, character: dict) -> None:
    """고른 캐릭터로 접속한다. 이미 그 캐릭터면 그대로 (어비스 안이어도 이어서). 다른 캐릭터로 어비스 안이면 나간 뒤 바꾼다.
    이름은 메인 화면 왼쪽 위에서만 읽힌다 → 매칭 중이면 들어갈 때까지 기다려 안에서 읽고, 어비스 목록·입장 화면이나
    다른 창이면 login.run 이 ESC 로 닫고 읽는다 (같은 캐릭터면 repeat 가 메뉴에서 다시 연다)."""
    from .login import current_name, name_matches
    from . import login
    bot.background = False
    at = where_settled(bot, cfg["abyss"]["dungeon"])
    if at == "matching":
        bot.log.info("매칭 중에 시작 → 들어간 뒤 캐릭터 확인")
        bot.step("abyss_match", "우연한 만남 매칭 중")
        if wait_entered(bot, cfg["abyss"]["match_timeout"]):
            at = "play"
    if at == "play":
        if name_matches(current_name(bot), character.get("name", "")):
            return
        bot.log.info(f"다른 캐릭터로 어비스 안 → 나간 뒤 {character['name']} 로 접속")
        leave(bot)
    elif at == "reward":
        bot.key("esc")  # 보상 화면 '나가기' — 판은 이미 끝났다
        bot.sleep(3, 4)
        _wait_settled(bot, bot.cfg["timing"]["loading"])
    bot.character = character
    bot.log.info(login.run(bot, cfg, character))


def after_clear(bot: Bot) -> bool:
    """클리어 화면('화면을 터치해 주세요')이나 보상 화면(다시 하기 / 나가기)인가."""
    ui = bot.ui
    act = bot.state.activity() if bot.state.available() else None
    return bool((act or {}).get("IsAbyssResultSequencePlaying") or bot.exists(ui["dungeon_retry"])
                or bot.exists(ui["reward_exit"]) or touch_prompt_visible(bot))


def _behind(bot: Bot) -> bool:
    """뒤에서 도는 중인가 (사람이 다른 일을 하는 중) — 그러면 클릭(게임을 앞으로 가져옴) 대신 키·기다림으로.
    어비스는 뒤에서 도는 작업이라 화면을 잡지 않는 게 우선이다 (2026-10-24 사용자)."""
    return bool(bot.background) and not bot.window.is_foreground()


def to_reward(bot: Bot) -> None:
    """클리어 화면을 넘겨 보상 화면(나가기 / 다시 하기)까지. 뒤에서는 클릭하지 않는다 (장면 넘기기는 기다리고,
    '화면을 터치해 주세요' 는 Space)."""
    ui = bot.ui
    end = time.monotonic() + 120
    while not bot.exists(ui["dungeon_retry"]):
        if time.monotonic() > end:
            raise StepTimeout(f"어비스 보상 화면이 나오지 않음 → {bot.snapshot('abyss_reward').name}")
        if bot.vision.has(ui["scene_skip"]) and bot.exists(ui["scene_skip"]):
            if not _behind(bot):
                bot.click_if(ui["scene_skip"])
        elif bot.clear_blockers(skip=(ui["dungeon_touch"],)):
            pass  # 클리어와 함께 깨진 퀘스트의 클리어 창·대화 (주말 어비스 3판 등)
        elif touch_prompt_visible(bot) or bot.exists(ui["dungeon_touch"]):
            if _behind(bot):
                bot.key("space")
            else:
                bot.click(tuple(bot.cfg["dungeon"]["touch_xy"]))
        else:
            # 판을 마치는 순간 깨진 퀘스트(주말 어비스 3판 등)의 완료 창이 보상 화면을 가린다 — 글자로 '확인' 을 찾는다
            bot.clear_blockers(skip=(ui["dungeon_touch"],), ocr=True)
        bot.sleep(1.5, 2.0)
    bot.sleep(1.5, 2.0)  # 보상 연출


def repeat(bot: Bot, cfg: dict, runs: int = 0, minutes: float = 0, on_event=lambda e: None,
           character: dict | None = None) -> dict:
    """어비스를 반복한다. runs·minutes 가 0 이면 사람이 멈출 때까지 (StopRequested).
    시간이 다 되면 그 판은 마저 끝내고 보상 화면에서 나간다. character({slot, name})가 있으면 그 캐릭터로 접속해서
    한다 (지금 그 캐릭터면 다시 고르지 않는다). 반환 {clears, deaths, retries, seconds}."""
    a = cfg["abyss"]
    dungeon, difficulty = a["dungeon"], a.get("difficulty", "")
    behind = bool(a.get("background", True))
    user_window = ctypes.windll.user32.GetForegroundWindow()  # 입장 뒤 되돌려 줄 창 (리모콘 등)
    t0 = time.monotonic()
    stat = {"clears": 0, "deaths": 0, "retries": 0, "revives": 0}

    def done() -> bool:
        return (runs and stat["clears"] >= runs) or (minutes and time.monotonic() - t0 >= minutes * 60)

    def emit(**kw):
        on_event({"type": "abyss", **stat, "seconds": round(time.monotonic() - t0), **kw})

    goal = (f"{runs}판" if runs else "") + (" · " if runs and minutes else "") + (f"{minutes:g}분" if minutes else "")
    bot.log.info(f"어비스 반복 시작: {dungeon}{' / ' + difficulty if difficulty else ''} — {goal or '멈출 때까지'}")
    # 어디서 시작하나 (where): 어비스 안이면 그 판부터, 클리어·보상 화면이면 보상부터 (2026-10-23 클리어 화면에서
    # 시작해 입장부터 하려다 ESC 가 듣지 않아 멈췄다), 매칭 중이면 들어가길 기다리고, 입장 화면·어비스 목록이면
    # 그 자리부터, 그 밖(메인·다른 창)은 메뉴에서 입장
    bot.auto_clear = True
    if character:
        _switch_character(bot, cfg, character)
    bot.background = behind
    at = where_settled(bot, dungeon)
    stage = {"play": "play", "reward": "reward", "matching": "match"}.get(at, "entry")
    if at != "main":
        bot.log.info({"play": "이미 어비스 안 → 이 판부터 이어서", "reward": "어비스 클리어 화면 → 보상부터",
                      "matching": "매칭 중 → 들어가길 기다림", "entry": "어비스 입장 화면 → 그 자리부터",
                      "list": "어비스 목록 → 그 자리부터", "menu": "메뉴가 열려 있음 → 그 자리부터"}.get(at, f"알 수 없는 화면({at}) → 닫고 메뉴에서 입장"))
    while True:
        if stage == "entry":
            # 입장은 메뉴·목록·버튼을 눌러야 해서 게임을 앞에 두고 한다. 들어간 뒤로는 다시 뒤에서
            bot.step("abyss_open", f"어비스 입장 화면 ({dungeon})")
            bot.background = False
            open_entry(bot, dungeon, difficulty, at=at)
            at = ""  # 처음 한 번만 — 다음 입장은 판이 끝난 자리(메인)에서
            _click_text(bot, gd.text("abyss_enter"), gd.region("abyss_entry_right"), what="입장하기")
            if behind:
                bot.background = True
                bot.window.give_back(user_window)
            stage = "match"
        if stage == "match" and not inside(bot):
            bot.step("abyss_match", "우연한 만남 매칭 중")
            emit(stage="match")
            if not wait_entered(bot, a["match_timeout"]):
                stat["retries"] += 1
                bot.log.warning(f"{a['match_timeout'] / 60:.0f}분 안에 매칭·입장이 되지 않음 → 처음부터 다시 "
                                f"→ {bot.snapshot('abyss_match').name}")
                bot.to_main()
                stage = "entry"
                continue
        if stage == "reward":
            r = "clear"
        else:
            n = stat["clears"] + stat["deaths"] + stat["retries"] + 1  # 부활은 같은 판
            bot.step("abyss_play", f"{n}번째 판 진행 중")
            emit(stage="play")
            r = play(bot, a["run_timeout"], bool(a.get("revive", True)),
                     on_revive=lambda: (stat.__setitem__("revives", stat["revives"] + 1), emit(stage="play")))
        if r == "dead":
            stat["deaths"] += 1
            bot.log.warning(f"쓰러짐 → 나가서 처음부터 다시 입장 (나간 판 {stat['deaths']}번)")
            leave(bot)
            stage = "entry"
        elif r == "timeout":
            stat["retries"] += 1
            bot.log.warning(f"{a['run_timeout'] / 60:.0f}분 안에 끝나지 않음 → 나가서 다시 입장 → {bot.snapshot('abyss_timeout').name}")
            leave(bot)
            stage = "entry"
        else:
            to_reward(bot)
            stat["clears"] += 1
            secs = round(time.monotonic() - t0)
            bot.log.info(f"클리어 {stat['clears']}판 (부활 {stat['revives']} · 사망으로 나감 {stat['deaths']} · 경과 {secs // 60}분 {secs % 60}초)")
            emit(stage="clear")
            if done():
                bot.key("esc")  # 보상 화면 '나가기'
                bot.sleep(3, 4)
                # 필드로 나오는 로딩이 끝나 메인 화면이 보일 때까지 — 3~4초만 보고 끝내면 다음 카드(다른 캐릭터)가
                # 로딩 화면에서 ESC 메뉴를 찾다 실패했다 (2026-10-24 21:24)
                if not _wait_settled(bot, bot.cfg["timing"]["loading"]):
                    if after_clear(bot):  # 나가기 키가 안 들었다
                        bot.key("esc")
                        _wait_settled(bot, bot.cfg["timing"]["loading"])
                break
            bot.key("space")  # 다시 하기 (Space) → 같은 던전·난이도로 다시 매칭
            bot.sleep(2, 3)
            for _ in range(2):  # 키가 안 들었으면 — 뒤에서는 키를 한 번 더, 앞에서는 누른다
                if not bot.exists(bot.ui["dungeon_retry"]):
                    break
                if _behind(bot):
                    bot.key("space")
                else:
                    bot.click(bot.ui["dungeon_retry"])
                bot.sleep(2, 3)
            stage = "match"
        if done():
            break
    secs = round(time.monotonic() - t0)
    bot.log.info(f"어비스 반복 끝: 클리어 {stat['clears']}판, 사망 {stat['deaths']}번 ({secs // 60}분)")
    return {**stat, "seconds": secs}
