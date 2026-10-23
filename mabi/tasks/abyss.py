"""어비스 반복 플레이. 일일 숙제와 따로, 사람이 멈추거나(F12) 정한 횟수·시간이 될 때까지 같은 어비스를 다시 돈다.

흐름 (2026-10-23 '허상의 정박지' 로 확인):
  메뉴(ESC) → '어비스' → 오른쪽 목록에서 던전 → 입장 화면('함께하기' · 난이도 · '우연한 만남' 켬) → '입장하기'
  → 우연한 만남 매칭 (모두 모이면 자동 입장) → 들어가면 숏컷 자동 진행·자동 전투가 저절로 켜진다
  → 클리어하면 '던전 클리어 / 화면을 터치해 주세요' → 보상 화면(나가기 ESC / 다시 하기 Space / 다른 던전 가기)
  → '다시 하기' = 같은 던전·난이도로 다시 매칭 → 4초 세고 입장
죽으면 오른쪽 맨 위 나가기 버튼 → '던전에서 퇴장하시겠습니까?' 나가기(Space) → 처음부터 다시 입장한다.
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


def open_entry(bot: Bot, dungeon: str, difficulty: str = "") -> None:
    """메인 화면 → 메뉴 → 어비스 → dungeon 입장 화면. '함께하기' · 난이도 · '우연한 만남' 을 맞춘다."""
    bot.to_main()
    for _ in range(3):
        bot.key("esc")
        bot.sleep(1.5, 1.8)
        if _find_text(bot, gd.text("abyss_menu"), gd.region("menu_right")):
            break
        bot.to_main()
    _click_text(bot, gd.text("abyss_menu"), gd.region("menu_right"), what="메뉴의 어비스")
    bot.sleep(1.0, 1.5)
    _click_text(bot, dungeon, gd.region("abyss_list"), what=f"어비스 '{dungeon}'")
    bot.sleep(1.0, 1.5)
    # 입장 화면: '입장하기' 가 보일 때까지
    for _ in range(5):
        if _find_text(bot, gd.text("abyss_enter"), gd.region("abyss_entry_right")):
            break
        bot.sleep(1.0, 1.4)
    else:
        raise CannotProceed(f"'{dungeon}' 입장 화면이 열리지 않음 → {bot.snapshot('abyss').name}")
    _click_text(bot, gd.text("abyss_together"), gd.region("abyss_entry_top"), what="함께하기")
    if difficulty:
        _click_text(bot, difficulty, gd.region("abyss_difficulty"), what=f"난이도 '{difficulty}'")
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
        bot.sleep(2)


def play(bot: Bot, run_timeout: float) -> str:
    """어비스 안에서 끝날 때까지 지켜본다. 'clear' | 'dead' | 'timeout'.
    배고프면 그때마다 음식을 먹는다 (어비스 반복은 일일 숙제의 하루 횟수 제한 없이)."""
    end = time.monotonic() + run_timeout
    while True:
        bot.sleep(3)
        act = bot.state.activity() or {}
        if act.get("IsDead"):
            return "dead"
        if act.get("IsAbyssResultSequencePlaying"):
            return "clear"
        if inside(bot):
            bot.eat_if_hungry()
        elif (bot.exists(bot.ui["dungeon_retry"]) or bot.exists(bot.ui["reward_exit"])
              or touch_prompt_visible(bot)):
            return "clear"  # 클리어 연출로 HUD 가 사라졌다 (CLI 를 못 읽었을 때)
        if time.monotonic() > end:
            return "timeout"


def _switch_character(bot: Bot, cfg: dict, character: dict) -> None:
    """고른 캐릭터로 접속한다. 이미 그 캐릭터면 그대로 (어비스 안이어도 이어서). 다른 캐릭터로 어비스 안이면 나간 뒤 바꾼다."""
    from .login import current_name, name_matches
    from . import login
    bot.background = False
    if inside(bot):
        if name_matches(current_name(bot), character.get("name", "")):
            return
        bot.log.info(f"다른 캐릭터로 어비스 안 → 나간 뒤 {character['name']} 로 접속")
        leave(bot)
    elif after_clear(bot):
        bot.key("esc")  # 보상 화면 '나가기' — 판은 이미 끝났다
        bot.sleep(3, 4)
        leave_wait = time.monotonic() + bot.cfg["timing"]["loading"]
        while not bot.at_main() and time.monotonic() < leave_wait:
            bot.sleep(2)
    bot.character = character
    bot.log.info(login.run(bot, cfg, character))


def after_clear(bot: Bot) -> bool:
    """클리어 화면('화면을 터치해 주세요')이나 보상 화면(다시 하기 / 나가기)인가."""
    ui = bot.ui
    act = bot.state.activity() if bot.state.available() else None
    return bool((act or {}).get("IsAbyssResultSequencePlaying") or bot.exists(ui["dungeon_retry"])
                or bot.exists(ui["reward_exit"]) or touch_prompt_visible(bot))


def to_reward(bot: Bot) -> None:
    """클리어 화면을 넘겨 보상 화면(나가기 / 다시 하기)까지."""
    ui = bot.ui
    end = time.monotonic() + 120
    keyed = 0
    while not bot.exists(ui["dungeon_retry"]):
        if time.monotonic() > end:
            raise StepTimeout(f"어비스 보상 화면이 나오지 않음 → {bot.snapshot('abyss_reward').name}")
        if bot.vision.has(ui["scene_skip"]) and bot.click_if(ui["scene_skip"]):
            pass
        elif touch_prompt_visible(bot) or bot.exists(ui["dungeon_touch"]):
            # 뒤에서 할 때는 클릭 대신 키로 넘겨 본다 (클릭은 게임을 잠깐 앞으로 가져와야 한다)
            if bot.background and keyed < 2:
                bot.key("space")
                keyed += 1
            else:
                bot.click(tuple(bot.cfg["dungeon"]["touch_xy"]))
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
    stat = {"clears": 0, "deaths": 0, "retries": 0}

    def done() -> bool:
        return (runs and stat["clears"] >= runs) or (minutes and time.monotonic() - t0 >= minutes * 60)

    def emit(**kw):
        on_event({"type": "abyss", **stat, "seconds": round(time.monotonic() - t0), **kw})

    goal = (f"{runs}판" if runs else "") + (" · " if runs and minutes else "") + (f"{minutes:g}분" if minutes else "")
    bot.log.info(f"어비스 반복 시작: {dungeon}{' / ' + difficulty if difficulty else ''} — {goal or '멈출 때까지'}")
    # 어디서 시작하나: 어비스 안이면 그 판부터, 클리어·보상 화면이면 보상부터 (2026-10-23 클리어 화면에서 시작해
    # 입장부터 하려다 ESC 가 듣지 않아 멈췄다), 아니면 메뉴에서 입장
    stage = "entry"
    if character:
        _switch_character(bot, cfg, character)
    bot.background = behind
    if inside(bot):
        stage = "play"
        bot.log.info("이미 어비스 안 → 이 판부터 이어서")
    elif after_clear(bot):
        stage = "reward"
        bot.log.info("어비스 클리어 화면 → 보상부터")
    while True:
        if stage == "entry":
            # 입장은 메뉴·목록·버튼을 눌러야 해서 게임을 앞에 두고 한다. 들어간 뒤로는 다시 뒤에서
            bot.step("abyss_open", f"어비스 입장 화면 ({dungeon})")
            bot.background = False
            open_entry(bot, dungeon, difficulty)
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
            n = stat["clears"] + stat["deaths"] + stat["retries"] + 1
            bot.step("abyss_play", f"{n}번째 판 진행 중")
            emit(stage="play")
            r = play(bot, a["run_timeout"])
        if r == "dead":
            stat["deaths"] += 1
            bot.log.warning(f"사망 → 나가서 처음부터 다시 입장 (사망 {stat['deaths']}번)")
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
            bot.log.info(f"클리어 {stat['clears']}판 (사망 {stat['deaths']} · 경과 {secs // 60}분 {secs % 60}초)")
            emit(stage="clear")
            if done():
                bot.key("esc")  # 보상 화면 '나가기'
                bot.sleep(3, 4)
                break
            bot.key("space")  # 다시 하기 (Space) → 같은 던전·난이도로 다시 매칭
            bot.sleep(2, 3)
            if bot.exists(bot.ui["dungeon_retry"]):  # 키가 안 들었으면 누른다
                bot.click(bot.ui["dungeon_retry"])
                bot.sleep(2, 3)
            stage = "match"
        if done():
            break
    secs = round(time.monotonic() - t0)
    bot.log.info(f"어비스 반복 끝: 클리어 {stat['clears']}판, 사망 {stat['deaths']}번 ({secs // 60}분)")
    return {**stat, "seconds": secs}
