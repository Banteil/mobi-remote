"""어비스 반복 플레이. 일일 숙제와 따로, 사람이 멈추거나(F12) 정한 횟수·시간이 될 때까지 같은 어비스를 다시 돈다.

흐름 (2026-10-23 '허상의 정박지' 로 확인):
  메뉴(ESC) → '어비스' → 오른쪽 목록에서 던전 → 입장 화면('함께하기' · 난이도 · '우연한 만남' 켬) → '입장하기'
  → 우연한 만남 매칭 (모두 모이면 자동 입장) → 들어가면 숏컷 자동 진행·자동 전투가 저절로 켜진다
  → 클리어하면 '던전 클리어 / 화면을 터치해 주세요' → 보상 화면(나가기 ESC / 다시 하기 Space / 다른 던전 가기)
  → '다시 하기' = 같은 던전·난이도로 다시 매칭 → 4초 세고 입장
판이 끝났을 때 장비 내구도(패킷)가 repair_below 이하면 '다시 하기' 대신 나가서 대장간에서 전체 수리하고 다시 입장한다 (tasks.repair).
쓰러지면 '행동불능' + '남은 부활 횟수 N/M' 과 오른쪽 아래 '여신상에서 부활' / '여기서 부활'(R, 아이템 1개) 이 뜬다.
최대 횟수 M 은 함께하기·난이도 등에 따라 다르다 (3, 6 을 봤다) — 고정값으로 보지 않는다.
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
from . import repair, ui_text
from .content import CannotProceed, touch_prompt_visible

DIFFICULTIES = ["입문", "어려움", "매우 어려움", "매우 어려움2"]


_norm = ui_text.norm
_find_text = ui_text.find


def _click_text(bot: Bot, want: str, region=None, exact: bool = True, what: str = "", tries: int = 4) -> None:
    ui_text.click(bot, want, region, exact, what, tries, shot="abyss")


ABYSS_MAP = "InstanceAbyssDungeon"  # 패킷의 맵 종류


def inside(bot: Bot) -> bool:
    """어비스 판 안인가 — 패킷이 알면 어비스 맵에 있고 로딩 중이 아니며 이 맵에서 결과가 아직 안 옴
    ('다시 하기' 뒤 지난 판 맵에 선 채 매칭을 기다리는 건 판 안이 아니다). 모르면 오른쪽 맨 위 나가기 버튼."""
    loading = bot.map_loading()
    if loading is not None:
        st = bot.packets.state
        return not loading and st.channel_type == ABYSS_MAP and not st.abyss_result
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
        if bot.map_loading():  # 패킷: 맵 로딩 중 — 끝나는 순간까지 화면은 안 본다
            bot.wait_loaded(end - time.monotonic())
            continue
        if not bot.auto_traveling() and bot.at_main():
            return True
        if not bot.is_loading():
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
    if key and bot.fast_travel_ok():
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
      matching 매칭 중 — 패킷의 매칭 상태로, 없으면 입장 화면인데 입장하기·이동하기 버튼이 없는 것으로.
               매칭 중 화면은 필드 + 오른쪽 '우연한 만남' 창 (2026-10-25 captures/abyss)
      list     어비스 목록 (dungeon 이름이 오른쪽 목록에)
      loading  맵 로딩 중 (패킷, 모르면 CLI 가 답하지 않는 것으로)    other  그 밖의 창 — ESC 로 닫으면 된다"""
    if bot.map_loading():
        return "loading"
    if inside(bot):
        return "play"
    if after_clear(bot):
        return "reward"
    if bot.at_main():
        return "main"
    if bot.exists(bot.ui["menu_quit"]):
        return "menu"
    if bot.packets.ok and bot.packets.state.abyss_matching in (1, 2, 3):
        return "matching"  # 패킷: 우연한 만남 매칭 중 (화면은 필드 + 오른쪽 '우연한 만남' 창)
    if _find_text(bot, gd.text("abyss_together"), gd.region("abyss_entry_top")):
        return "entry" if _entry_button(bot) else "matching"
    if _find_text(bot, dungeon, gd.region("abyss_list")):
        return "list"
    if bot.map_loading() is None and bot.is_loading():
        return "loading"
    return "other"


def where_settled(bot: Bot, dungeon: str) -> str:
    """where, 단 로딩 중이면 끝날 때까지 (상한 timing.loading)."""
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while (at := where(bot, dungeon)) == "loading" and time.monotonic() < end:
        if not bot.wait_loaded(end - time.monotonic()):  # 패킷이 모르면 CLI 로 다시 본다
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
        bot.clear_blockers(ocr=True)  # ESC 를 먹은 창 (메인 HUD 가 보이는 채로 뜬 퀘스트 완료 창 등)
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
    """매칭(우연한 만남)이 잡혀 어비스 안으로 들어갈 때까지. 모두 모이면 저절로 들어간다. 시간 안에 못 들어가면 False.
    패킷이 있으면 맵을 떠나는 순간 바로 알고, 로딩 동안은 화면을 보지 않는다. 어비스 맵에 들어온 지 10초가 지났는데
    나가기 버튼이 가려져 있으면 그래도 들어온 것으로 본다 (판 진행 쪽이 가린 창을 넘긴다). 기다리기 시작한 뒤에 들어간
    어비스 맵만 센다 — '다시 하기' 뒤엔 지난 판 맵에 선 채로 매칭을 기다릴 수 있다."""
    start = time.monotonic()
    end = start + timeout
    while not inside(bot):
        if time.monotonic() > end:
            return False
        loading = bot.map_loading()
        st = bot.packets.state
        if loading:
            bot.wait_loaded(end - time.monotonic())
            continue
        if loading is False and st.channel_type == ABYSS_MAP and st.entered_at > start:
            if time.monotonic() - st.entered_at > 10:
                bot.log.info("패킷: 어비스 맵에 들어옴 (나가기 버튼은 가려짐)")
                return True
            bot.clear_blockers()
            bot.sleep(1)
            continue
        bot.clear_blockers(ocr=True)  # 매칭 중에 퀘스트 클리어 창 등이 뜨면 입장을 막는다 (2026-10-24 06:07)
        # 3초 쉬되 맵을 떠나기 시작하면 바로 깬다
        if bot.wait_packet(lambda s: s.loading, 3) is None:
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
    # 밖(필드)으로 나와 메인 화면이 보일 때까지 — 패킷이 있으면 맵을 떠나기 시작하는 순간(길어야 15초)을 기다렸다가,
    # 로딩 동안은 화면을 보지 않는다
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    bot.wait_packet(lambda s: s.loading, 15)
    while inside(bot) or not bot.at_main():
        if time.monotonic() > end:
            raise StepTimeout("어비스에서 나온 뒤 메인 화면이 나오지 않음")
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if not inside(bot) and not bot.is_loading():
            bot.clear_blockers(ocr=True)  # 나오면서 뜬 퀘스트 완료 창
        bot.sleep(2)


def revives_left(bot: Bot) -> int | None:
    """남은 부활 횟수 = 이 판의 최대 - 쓴 횟수 (패킷 revive.count, 최대는 판마다 게임이 보내는 값 — 3, 6 을 봤다).
    화면 '남은 부활 횟수 3/3' 일 때 쓴 0 · 최대 3 (death1 실측). 모르면 None."""
    st = bot.packets.state
    if bot.packets.ok and st.revives_max:
        return max(0, st.revives_max - (st.revives_used or 0))
    return None


def revive_here(bot: Bot) -> bool:
    """사망 화면에서 '여기서 부활'(R). 부활했으면 True, 못 했으면 False → 부르는 쪽이 나가서 처음부터.
    막혔는지 미리 알아내려 하지 않는다 — R 을 누르고 정해진 시간 안에 부활 신호가 오는지로 정한다 (사용자 2026-10-25).
    함께하기 전멸·부활 아이템 없음 등으로 막혀 있으면 R 은 아무 일도 하지 않아 누르는 비용이 없다.
    (예전엔 화면 글자·버튼 색으로 미리 막힘을 판단했는데, 잘못 읽으면 부활할 수 있는데도 나가 버렸다.)
    누르기 전에 나가는 것은 확실한 신호뿐: 패킷이 알려 준 이 판의 부활 횟수를 다 씀.
    부활 신호: 패킷 revive.item_ok (ReviveUsingConsumable_RSP_SUCCESS) 또는 쓰러짐이 풀림 (패킷 SetDead 0 · CLI IsDead)."""
    if revives_left(bot) == 0:
        bot.log.warning(f"부활 횟수를 다 씀 (패킷) → 나감 ({bot.snapshot('abyss_dead').name})")
        return False
    # 사망 화면 버튼은 쓰러지고 1~2초 뒤에 뜨고, 그 전의 키는 무시된다 → 버튼이 보일 때까지 잠깐.
    # 못 찾아도(전멸이면 버튼이 없다) 그냥 누른다 — 판단은 아래 시간 제한이 한다
    for _ in range(3):
        if bot.vision.find(bot.frame(), "revive_here"):
            break
        bot.sleep(1.5, 2)
    mark = bot.packets.mark()
    bot.key("r")  # '여기서 부활' 단축키 (사용자 확인 2026-10-25) — 버튼 위치가 모드마다 달라도 된다
    end = time.monotonic() + bot.cfg["abyss"].get("revive_timeout", 10)
    again = False
    while time.monotonic() < end:
        bot.sleep(1.0)
        if bot.packets.find("revive.item_ok", mark) or not bot.is_dead():
            left = revives_left(bot)
            bot.log.info(f"여기서 부활{f' (남은 부활 {left}번)' if left is not None else ''}")
            return True
        if not again and end - time.monotonic() < 5:  # 첫 키가 무시됐을 수 있다 (아직 쓰러진 채일 때만 한 번 더)
            bot.key("r")
            again = True
    bot.log.warning(f"'여기서 부활' 신호가 없음 (전멸·부활 횟수·아이템 없음 등) → 나감 ({bot.snapshot('abyss_dead').name})")
    return False


def play(bot: Bot, run_timeout: float, revive: bool = True, on_revive=lambda: None) -> str:
    """어비스 안에서 끝날 때까지 지켜본다. 'clear' | 'dead' | 'timeout'.
    쓰러지면 revive 일 때 '여기서 부활' 하고 이어 한다 (못 하면 'dead' → 나가서 처음부터).
    배고프면 그때마다 음식을 먹는다 (어비스 반복은 일일 숙제의 하루 횟수 제한 없이)."""
    end = time.monotonic() + run_timeout
    mark = bot.packets.mark()

    def cleared(_s=None) -> bool:  # 패킷: 이 판의 결과가 옴 (클리어 순간, CLI 결과 연출 표시와 같은 때)
        return bot.packets.find("abyss.result", mark, lambda v: bool(v.get("abyss"))) is not None

    while True:
        if bot.wait_packet(cleared, 3) is None:  # 3초 쉬되 결과가 오면 바로 깬다
            bot.sleep(3)
        if cleared():
            bot.log.info("패킷: 어비스 결과 옴 → 클리어")
            return "clear"
        act = bot.state.activity() or {}
        if bot.is_dead(act):
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
    known = bot.map_loading() is not None  # 패킷이 지금 맵을 안다
    st = bot.packets.state
    if known:
        if st.loading or st.channel_type != ABYSS_MAP:
            return False  # 어비스 맵이 아니다 (필드로 나왔거나 옮기는 중)
        if st.abyss_result:
            return True  # 패킷: 이 맵에서 결과가 옴 (나가면 새 맵 진입 때 지운다)
    act = bot.state.activity() if bot.state.available() else None
    if (act or {}).get("IsAbyssResultSequencePlaying"):
        return True
    if known:
        return False  # 어비스 맵인데 결과가 안 옴 — 판 중이다 (그림은 보지 않는다)
    return bool(bot.exists(ui["dungeon_retry"]) or bot.exists(ui["reward_exit"]) or touch_prompt_visible(bot))


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
            pass  # 연출은 스스로 끝나길 기다린다 (Bot.scene_skip — 어비스 중엔 누르지 않음)
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


def exit_reward(bot: Bot) -> None:
    """보상 화면 '나가기'(ESC) → 필드 메인 화면까지."""
    bot.key("esc")
    bot.sleep(3, 4)
    # 필드로 나오는 로딩이 끝나 메인 화면이 보일 때까지 — 3~4초만 보고 끝내면 다음 카드(다른 캐릭터)가
    # 로딩 화면에서 ESC 메뉴를 찾다 실패했다 (2026-10-24 21:24)
    if not _wait_settled(bot, bot.cfg["timing"]["loading"]):
        if after_clear(bot):  # 나가기 키가 안 들었다
            bot.key("esc")
            _wait_settled(bot, bot.cfg["timing"]["loading"])
    # 판 수를 채운 판에서 깨진 퀘스트(주말 어비스 3판 등)의 완료 창이 필드로 나온 뒤 뜬다. 메인 HUD 가
    # 보이는 채로 떠서 ESC 를 먹어, 다음 카드가 캐릭터를 바꾸려다 메뉴가 안 열려 실패했다 (2026-10-24 21:24).
    # 무한 반복은 '다시 하기' Space 가 그 창의 '확인' 까지 눌러 넘어갔다
    for _ in range(3):
        bot.sleep(1.5, 2)
        bot.clear_blockers(ocr=True)


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
    below = float(a.get("repair_below", 0.05) or 0)  # 장비 내구도가 이 비율 이하면 판 사이에 대장간에서 수리 (0 = 안 함)
    repaired_from = None  # 마지막 수리 직전 내구도 — 수리 뒤 첫 판에서 이보다 높아지지 않았으면 수리가 안 된 것

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
    bot.scene_skip = False  # 연출은 누르지 않고 기다린다 — 누르면 뒤에서 돌던 게임이 앞으로 나온다 (2026-10-25 사용자)
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
                exit_reward(bot)
                break
            if repair.needed(bot, below):
                if repaired_from is not None and repair.durability(bot) <= repaired_from:  # 수리했는데 그대로거나 더 낮다
                    raise CannotProceed(f"수리했는데도 장비 내구도가 {repair.durability(bot) * 100:.0f}% "
                                        f"→ {bot.snapshot('repair_again').name}")
                bot.log.info(f"장비 내구도 {repair.durability(bot) * 100:.0f}% (기준 {below * 100:g}%) → 다시 하기 대신 나가서 수리")
                emit(stage="repair")
                repaired_from = repair.durability(bot)
                exit_reward(bot)
                repair.run(bot)
                stat["repairs"] = stat.get("repairs", 0) + 1
                stage = "entry"
                continue
            repaired_from = None
            bot.key("space")  # 다시 하기 (Space) → 같은 던전·난이도로 다시 매칭
            for _ in range(2):  # 키가 안 들었으면 — 뒤에서는 키를 한 번 더, 앞에서는 누른다
                # 패킷: 매칭 상태(요청·찾는 중·잡힘)나 맵 로딩이 오면 눌린 것. 모르면 2~3초 뒤 화면의 '다시 하기' 버튼으로
                took = bot.wait_packet(lambda s: s.abyss_matching in (1, 2, 3) or s.loading, 3)
                if took:
                    break
                if took is None:
                    bot.sleep(2, 3)
                if not bot.exists(bot.ui["dungeon_retry"]):
                    break
                if _behind(bot):
                    bot.key("space")
                else:
                    bot.click(bot.ui["dungeon_retry"])
            stage = "match"
        if done():
            break
    secs = round(time.monotonic() - t0)
    bot.log.info(f"어비스 반복 끝: 클리어 {stat['clears']}판, 사망 {stat['deaths']}번 ({secs // 60}분)")
    return {**stat, "seconds": secs}
