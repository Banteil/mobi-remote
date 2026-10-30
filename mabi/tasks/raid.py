"""레이드 반복 (혼자하기). 사람이 멈추거나(F12) 정한 횟수·시간이 될 때까지 같은 레이드를 다시 돈다.

흐름 (2026-10-28 카브락 어려움 5판으로 확인, 캡처 caps/raid1):
  메뉴(ESC) → '레이드' → 레이드 카드(카브락 / 에이렐 / 화이트 서큐버스) → 입장 창(위쪽 '혼자하기 / 함께하기' 탭, 왼쪽 난이도)
  → 오른쪽 아래 '이동하기' 또는 '출항하기'(둘 다 Space). 이동하기면 선착장까지 걸어가고(같은 맵, 몇 분) 창에서 다시 출항하기
  → 출항선(맵 InstanceRaidLobby '시작의 갑판'). 숏컷 퀘스트 '출항하기 · 조타로 이동 후 출항'
  → 그 퀘스트를 진행하면 연출 뒤 레이드 맵(InstanceRaid)으로. 안에서는 자동 진행·자동 전투가 저절로 켜진다
  → 보스 처치 (패킷 레이드 상태 Cleared + 결과) → 연출 → 결과 화면 '처치 완료' 확인(Space)
  → 오른쪽 맨 위 나가기 → '레이드에서 나가시겠습니까?' 출항선으로 이동(Space) → 배에서 다시 출항.
쓰러지면 '여기서 부활' (부활 제한 3회). 다 쓰면 나가기 → 출항선으로 이동 → 다시 출항.
장비 내구도가 낮으면 나가기 창에서 '파티&던전 나가기'(필드로) → 대장간 수리 → 메뉴에서 다시 입장.
연출은 넘기지 않고 기다린다 — '장면 넘기기' 는 클릭이라 뒤에서 돌던 게임이 앞으로 나온다 (2026-10-28 사용자).
게임을 앞에 둔 채 돌리면(background 끔) 넘긴다.
"""
import time

from .. import gamedata as gd
from ..bot import Bot, StepTimeout
from .. import monitor
from ..place import RAID_LOBBY, place
from . import ui_text
from .content import CannotProceed, watch
from .repeat import Repeat

RAIDS = ["카브락", "에이렐", "화이트 서큐버스"]
DIFFICULTIES = {"카브락": ["입문", "어려움"], "에이렐": ["어려움", "매우 어려움"], "화이트 서큐버스": ["어려움", "매우 어려움"]}

LOBBY_MAP = "InstanceRaidLobby"  # 출항선 (레이드마다 같은 맵)
RAID_MAP = "InstanceRaid"
_boarded: tuple[str, str] | None = None  # 이 리모콘이 마지막으로 태운 출항선 (레이드, 난이도) — 배는 어느 레이드 것인지 모른다
RESULT_OK = (960, 1010)  # 결과 화면 아래 가운데 '확인' (Space)

_find_text = ui_text.find


def _click_text(bot: Bot, want: str, region=None, exact: bool = True, what: str = "", tries: int = 4,
                key: str | None = None) -> None:
    ui_text.click(bot, want, region, exact, what, tries, shot="raid", key=key)


def _map(bot: Bot) -> str | None:
    """패킷이 아는 지금 맵 종류. 로딩 중이면 'loading', 모르면 None."""
    loading = bot.map_loading()
    if loading is None:
        return None
    return "loading" if loading else bot.packets.state.channel_type


def cleared(bot: Bot) -> bool:
    """이 레이드 판의 보스를 잡았나 (패킷 결과·상태 Cleared). 결과 화면이 떠 있는 동안 CLI 퀘스트는 빈 목록이다."""
    st = bot.packets.state
    # 맵을 모를 때(None — 레이드 안에서 리모콘을 켬)도 본다. 아니면 그 판은 클리어를 패킷으로 못 알아챈다
    return bot.packets.ok and _map(bot) in (RAID_MAP, None) and (bool(st.raid_result) or st.raid_state == "Cleared")


def _quest_title(bot: Bot) -> str:
    """CLI 숏컷 퀘스트 제목 (색 태그 뺌) — 배 '출항하기', 판 중 '카브락 클리어', 끝 '카브락 토벌 완료'."""
    qs = bot.state.query("get_quests") if bot.state.available() else None
    for q in qs or []:
        if q.get("Source") == "shortcut":
            t = q.get("QuestTitle", "")
            while "<" in t and ">" in t[t.index("<"):]:
                i = t.index("<")
                t = t[:i] + t[t.index(">", i) + 1:]
            return t
    return ""


def where(bot: Bot, raid: str) -> str:
    """지금 어디인가 — 어디서 시작해도 그 자리부터 잇는다.
      loading  맵 로딩 중            ship   출항선 (배)               play   레이드 맵, 보스를 아직 안 잡음
      cleared  레이드 맵, 보스를 잡음 (연출·결과 화면·나가기 전)        entry  입장 창 (혼자하기 / 함께하기 탭)
      list     레이드 목록           menu   메뉴(ESC)                  main   그 밖의 메인 화면 (필드)
      other    그 밖의 창 — ESC 로 닫으면 된다"""
    m = _map(bot)
    if m == "loading":
        return "loading"
    if m == RAID_MAP:
        return "cleared" if cleared(bot) else "play"
    if m == LOBBY_MAP:
        return "ship"
    if m is None:  # 패킷이 맵을 모름 (맵에 들어간 뒤 리모콘을 켬) — 레이드 상태 패킷 → CLI 장소·퀘스트로
        # 레이드 상태는 맵과 따로 온다. 보스를 잡은 직후 다시 켜 연출 중이면 CLI 퀘스트가 비고 결과 화면도 아직이라
        # '그 밖의 창' 으로 보고 메뉴에서 입장하려다 멈췄다 (2026-10-28 19:37)
        st = bot.packets.state
        if bot.packets.ok and (st.raid_result or st.raid_state == "Cleared"):
            return "cleared"
        if bot.packets.ok and st.raid_state == "InProgress":
            return "play"
        if place(bot).kind == RAID_LOBBY:  # CLI 장소 이름이 출항선
            return "ship"
        title = _quest_title(bot)
        if title.endswith(gd.text("raid_quest_clear")):
            return "play"
        if title.endswith(gd.text("raid_quest_done")):
            return "cleared"
        if not title and _find_text(bot, gd.text("raid_result"), gd.region("raid_result")):
            return "cleared"  # 결과 화면 동안은 CLI 퀘스트가 빈 목록이다
    if _find_text(bot, gd.text("abyss_together"), gd.region("abyss_entry_top")):
        return "entry"
    if _find_text(bot, raid, gd.region("raid_list")):
        return "list"
    if bot.at_main():
        return "main"
    if bot.exists(bot.ui["menu_quit"]):
        return "menu"
    if m is None and bot.is_loading():
        return "loading"
    return "other"


def where_settled(bot: Bot, raid: str) -> str:
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while (at := where(bot, raid)) == "loading" and time.monotonic() < end:
        if not bot.wait_loaded(end - time.monotonic()):
            bot.sleep(2, 2.5)
    return at


def _wait_settled(bot: Bot, timeout: float) -> bool:
    """로딩·자동 이동이 끝나 메인 화면이 보일 때까지 (abyss._wait_settled 와 같음)."""
    from .abyss import _wait_settled as settled
    return settled(bot, timeout)


def _entry_button(bot: Bot) -> str:
    """입장 창 오른쪽 아래 버튼: 'sail'(출항하기) · 'move'(이동하기) · ''."""
    if _find_text(bot, gd.text("raid_sail"), gd.region("abyss_entry_right")):
        return "sail"
    if _find_text(bot, gd.text("abyss_move"), gd.region("abyss_entry_right")):
        return "move"
    return ""


def open_entry(bot: Bot, raid: str, difficulty: str = "", at: str = "") -> None:
    """raid 입장 창을 열고 '혼자하기' · 난이도를 맞춘다. at 이 entry·list·menu 면 그 자리부터."""
    if at == "entry" and not _find_text(bot, raid, gd.region("raid_entry_title")):
        bot.log.info(f"다른 레이드의 입장 창 → 닫고 '{raid}' 로")
        bot.key("esc")
        bot.sleep(1.0, 1.4)
        at = ""
    if at != "entry":
        if at != "list":
            for _ in range(0 if at == "menu" else 3):
                bot.to_main()
                bot.key("esc")
                bot.sleep(1.5, 1.8)
                if _find_text(bot, gd.text("raid_menu"), gd.region("menu_right")):
                    break
                bot.clear_blockers(ocr=True)
            _click_text(bot, gd.text("raid_menu"), gd.region("menu_right"), what="메뉴의 레이드")
            bot.sleep(1.0, 1.5)
        _click_text(bot, raid, gd.region("raid_list"), what=f"레이드 '{raid}'")
        if not ui_text.wait(bot, gd.text("abyss_together"), gd.region("abyss_entry_top"), timeout=8):
            raise CannotProceed(f"'{raid}' 입장 창이 열리지 않음 → {bot.snapshot('raid').name}")
    # 탭 글자는 고르면 끝에 따옴표 같은 표시가 붙어 읽힌다 ('혼자하기'') — 들어 있기만 하면 된다
    _click_text(bot, gd.text("raid_solo"), gd.region("abyss_entry_top"), exact=False, what="혼자하기")
    if difficulty:
        _click_text(bot, difficulty, gd.region("raid_difficulty"), what=f"난이도 '{difficulty}'")


def _travel_to_dock(bot: Bot) -> bool:
    """'이동하기' 로 선착장까지 걸어가는 동안 기다린다. 도착해 입장 창이 다시 뜨면 True, 창 없이 메인 화면에
    멈췄으면 False. 메인 화면만 기다리면 도착 뒤 뜬 입장 창 앞에서 이동 상한(10분)까지 서 있었다 (2026-10-28 사용자)."""
    end = time.monotonic() + bot.cfg["raid"].get("travel_timeout", 600)
    still = 0  # 메인 화면에 멈춰 있는 것을 연달아 본 횟수 (이동 사이 잠깐 멈춤과 가르려고)
    while time.monotonic() < end:
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if _find_text(bot, gd.text("abyss_together"), gd.region("abyss_entry_top")):
            bot.log.info("선착장 도착 → 입장 창")
            return True
        if bot.at_main() and not bot.auto_traveling():
            still += 1
            if still >= 3:
                bot.log.info("이동이 멈췄는데 입장 창이 없음 → 메뉴에서 다시 엶")
                return False
        else:
            still = 0  # 걷는 중이거나 창이 떠 있음 — 막는 창 닫기(ESC)는 하지 않는다: 막 뜬 입장 창을 닫을 수 있다
        bot.sleep(2, 2.5)
    raise CannotProceed(f"선착장으로 가지 못함 → {bot.snapshot('raid_travel').name}")


def board(bot: Bot, raid: str, difficulty: str, at: str = "") -> None:
    """입장 창 → 출항선(배)까지. '이동하기' 면 선착장까지 걸어간 뒤 창에서 '출항하기'."""
    for attempt in range(3):
        open_entry(bot, raid, difficulty, at=at)
        at = ""
        button = ""
        for _ in range(5):
            if (button := _entry_button(bot)):
                break
            bot.sleep(1.0, 1.4)
        if not button:
            raise CannotProceed(f"'{raid}' 입장 창에 출항하기·이동하기가 없음 → {bot.snapshot('raid').name}")
        bot.key("space")
        if button == "move":
            bot.log.info("선착장에서 멂 → 이동하기")
            bot.sleep(2, 3)
            key = bot.cfg["game"].get("fast_travel_key")
            if key and bot.fast_travel_ok():
                bot.log.info("빠른 이동")
                bot.key(key)
            # 도착하면 입장 창이 다시 뜬다 → 그 자리부터 (혼자하기·난이도를 다시 맞추고 출항하기). 창 없이 멈췄으면 메뉴에서
            at = "entry" if _travel_to_dock(bot) else ""
            continue
        # 출항하기 → 배로 (맵 로딩)
        bot.wait_packet(lambda s: s.loading, 20, since=bot.input_mark)
        end = time.monotonic() + bot.cfg["timing"]["loading"]
        while time.monotonic() < end:
            if (w := where(bot, raid)) == "ship":
                bot.log.info("출항선에 탐")
                global _boarded
                _boarded = (raid, difficulty)
                return
            if w == "loading":
                bot.wait_loaded(end - time.monotonic())
            else:
                bot.sleep(2, 2.5)
        raise CannotProceed(f"출항선에 타지 못함 → {bot.snapshot('raid_board').name}")
    raise CannotProceed(f"선착장에 가도 출항하기가 나오지 않음 → {bot.snapshot('raid_board').name}")


def compass_ready(bot: Bot) -> bool:
    """오른쪽 아래 나침반(Space)이 기본 모양인가 — 그러면 Space 가 추적 중인 목표(노란 마름모)를 진행한다.
    주변에 상호작용할 것이 있으면 다른 모양, 자동 진행 중이면 정지(■)로 바뀐다 (2026-10-28 사용자).
    바늘은 방향 따라 돌아 그림이 안 맞아서, 바늘의 빨간 끝과 흰 몸통 비율로 본다 (나침반 약 3%·13%, 그 밖 빨강 0)."""
    x, y, w, h = gd.region("compass")
    c = bot.frame()[y:y + h, x:x + w].reshape(-1, 3).astype(int)
    b, g, r = c[:, 0], c[:, 1], c[:, 2]
    red = ((r > 200) & (g < 110) & (b < 110)).mean()
    white = ((r > 225) & (g > 225) & (b > 225)).mean()
    return red > 0.015 and 0.06 < white < 0.22


def _press_sail(bot: Bot) -> bool:
    """배 숏컷 퀘스트 '출항하기' 를 진행한다. 나침반이 기본 모양이고 CLI 자동 진행 대상이 숏컷이면 Space
    (키라 게임을 뒤에 둔 채로 된다 — 2026-10-28 뒤에서 Space 로 출항 확인). 안 되면 HUD 오른쪽 퀘스트 제목을 누르고,
    그것도 안 되면 퀘스트 창(J)의 '출항하기' 카드 '진행하기'. 누른 뒤 시작 신호가 왔으면 True."""
    def started(since: int, timeout: float) -> bool:
        return bool(bot.wait_packet(lambda s: s.loading or s.raid_state == "InProgress", timeout, since=since)) \
            or bool(bot.packets.find("autoplay.start_ok", since)) or bool(bot.packets.find("raid.depart", since))

    act = bot.activity() or {}
    if act.get("AutoPlayTarget", "shortcut") == "shortcut" and compass_ready(bot):
        bot.key("space")
        if started(bot.input_mark, 8):
            return True
        bot.log.info("나침반 Space 로 출항이 시작되지 않음 → 퀘스트 제목을 누름")
    hit = _find_text(bot, gd.text("raid_sail"), gd.region("quest_hud"))
    if hit:
        bot.click(hit)
        if started(bot.input_mark, 8):
            return True
    bot.key("j")
    bot.sleep(1.5, 2)
    title = _find_text(bot, gd.text("raid_sail"), gd.region("questwin_list"))
    goes = [(x, y) for t, x, y in ui_text.find_texts(bot.frame(), gd.region("questwin_list"))
            if ui_text.norm(t) == ui_text.norm(gd.text("raid_go"))]
    goes = [g for g in goes if title and 0 < g[1] - title[1] < 260]
    if not goes:
        bot.key("esc")
        return False
    bot.click(min(goes, key=lambda g: g[1]))
    return started(bot.input_mark, 10)


def sail(bot: Bot) -> None:
    """배에서 출항해 레이드 맵에 들어갈 때까지. 출항 연출은 로딩 사이에 나온다."""
    for _ in range(3):
        if not bot.at_main():
            bot.clear_blockers(ocr=True)
        if _press_sail(bot):
            break
        bot.sleep(2, 3)
    else:
        raise CannotProceed(f"출항하기를 진행하지 못함 → {bot.snapshot('raid_sail').name}")
    end = time.monotonic() + bot.cfg["raid"].get("sail_timeout", 300)
    while time.monotonic() < end:
        m = _map(bot)
        if m == RAID_MAP:
            bot.log.info("레이드 맵에 들어옴")
            return
        if m == "loading":
            bot.wait_loaded(end - time.monotonic())
            continue
        if m is None and _quest_title(bot).endswith(gd.text("raid_quest_clear")):
            return
        bot.clear_blockers()  # 출항 연출 (앞에 있으면 넘기고, 뒤에서면 기다린다 — may_skip_scene)
        bot.sleep(1.5, 2)
    raise StepTimeout(f"출항 뒤 레이드 맵에 들어가지 못함 → {bot.snapshot('raid_sail').name}")


def play(bot: Bot, run_timeout: float, revive: bool = True, on_revive=lambda: None) -> str:
    """레이드 맵에서 보스를 잡을 때까지. 'clear' | 'dead' | 'timeout'.
    쓰러지면 '여기서 부활' (점검자 — abyss.revive_here, 부활 횟수를 다 쓰면 'dead'). 배고프면 먹는다."""
    end = time.monotonic() + run_timeout
    ctx = monitor.Ctx("raid", "레이드 진행", revive=revive)
    while True:
        if bot.wait_packet(lambda s: bool(s.raid_result) or s.raid_state == "Cleared", 3) is None:
            bot.sleep(3)
        if cleared(bot):
            bot.log.info("패킷: 레이드 보스 처치 → 클리어")
            return "clear"
        act = bot.activity() or {}
        if not revive and bot.is_dead(act):
            return "dead"
        seen = watch(bot, ctx, act)
        if seen.finish and seen.finish.result == "dead":
            return "clear" if cleared(bot) else "dead"
        if ctx.take("revived"):
            on_revive()
            continue
        if not seen.done:
            bot.eat_if_hungry()
        if time.monotonic() > end:
            return "timeout"


def finish_result(bot: Bot) -> None:
    """보스 처치 연출이 끝나고 뜨는 결과 화면('처치 완료', 확인 Space)을 넘긴다. 연출은 기다린다 (뒤에서면).
    나가기 버튼(abyss_exit)이 보이면 결과 화면이 이미 지나갔다."""
    end = time.monotonic() + bot.cfg["raid"].get("result_timeout", 300)
    presses = 0
    while time.monotonic() < end:
        if _find_text(bot, gd.text("raid_result"), gd.region("raid_result")):
            bot.sleep(1.0, 1.5)
            presses += 1
            if presses <= 2:
                bot.key("space")
            else:  # Space 가 두 번 안 들었다 — 게임이 키를 놓치는 때가 있다 (2026-10-28 2분 동안 그대로) → '확인' 을 누른다
                bot.log.info("결과 화면 Space 가 안 들음 → 확인 버튼을 누름")
                bot.click(RESULT_OK)
            bot.sleep(1.5, 2)
            if not _find_text(bot, gd.text("raid_result"), gd.region("raid_result")):
                bot.log.info("결과 화면 확인")
                return
            continue
        if bot.exists(bot.ui["abyss_exit"]) and bot.at_main():
            return
        bot.clear_blockers()
        bot.sleep(1.5, 2)
    raise StepTimeout(f"레이드 결과 화면을 넘기지 못함 → {bot.snapshot('raid_result').name}")


def leave_ship(bot: Bot) -> None:
    """출항선에서 내린다: 나가기 → '출항선에서 퇴장하시겠습니까?' 나가기(Space) → 필드 메인 화면까지.
    어느 레이드의 배인지 모를 때(리모콘을 켜기 전에 탔거나 다른 레이드 카드) 메뉴에서 다시 들어가려고."""
    for _ in range(3):
        if _map(bot) not in (LOBBY_MAP, None):
            break
        if not bot.exists(bot.ui["abyss_exit"]):
            bot.clear_blockers(ocr=True)
            bot.sleep(1.0, 1.5)
            continue
        bot.key("x")  # 나가기 단축키 (leave 와 같음) — 안 뜨면 아이콘 클릭
        if not ui_text.wait(bot, gd.text("raid_ship_leave"), gd.region("raid_ship_leave"), timeout=4, exact=False):
            bot.click(bot.ui["abyss_exit"])
            if not ui_text.wait(bot, gd.text("raid_ship_leave"), gd.region("raid_ship_leave"), timeout=5, exact=False):
                continue
        bot.sleep(0.5, 0.8)
        bot.key("space")
        if not bot.wait_packet(lambda s: s.loading, 6, since=bot.input_mark):
            # Space 가 안 먹고 창이 남았으면 '나가기' 버튼을 누른다 (leave 와 같은 일, 2026-10-28)
            btn = ui_text.find(bot, gd.text("raid_ship_leave_ok"), gd.region("raid_ship_leave_buttons"))
            if btn:
                bot.log.info("Space 를 눌러도 출항선에서 안 내림 → '나가기' 클릭")
                bot.click(btn)
        break
    else:
        raise StepTimeout(f"출항선에서 내리지 못함 → {bot.snapshot('raid_ship_leave').name}")
    bot.wait_packet(lambda s: s.loading, 15, since=bot.input_mark)
    if not _wait_settled(bot, bot.cfg["timing"]["loading"]):
        raise StepTimeout("출항선에서 내린 뒤 메인 화면이 나오지 않음")


def leave(bot: Bot, to_field: bool = False) -> None:
    """레이드 맵에서 나간다: 나가기 → '레이드에서 나가시겠습니까?' → 출항선으로 이동(Space) 또는 '파티&던전 나가기'(필드).
    다 나와 메인 화면이 보일 때까지."""
    want = LOBBY_MAP
    deadline = time.monotonic() + 120  # 횟수가 아니라 시간으로 — 사람이 PC 를 쓰는 동안 클릭이 몇 번 건너뛰어져도 버틴다
    while True:
        if time.monotonic() > deadline:
            raise StepTimeout(f"레이드에서 나가지 못함 → {bot.snapshot('raid_leave').name}")
        if _map(bot) not in (RAID_MAP, None):
            break
        # 확인 창이 이미 떠 있으면(지난 시도의 Space 가 안 먹음) 나가기 아이콘을 또 누르지 않고 그 창부터
        hit = ui_text.find(bot, gd.text("raid_leave_ship"), gd.region("raid_leave_buttons"))
        if not hit:
            if not bot.exists(bot.ui["abyss_exit"]):
                bot.key("esc")  # 부활 창·결과 화면 등이 가리면 닫아 본다
                bot.sleep(1.0, 1.5)
                continue
            # 나가기 단축키 X — 클릭과 달리 뒤에서 도는 게임을 앞으로 가져오지 않는다 (결과 화면이 떠 있을 땐 안 먹음)
            bot.key("x")
            hit = ui_text.wait(bot, gd.text("raid_leave_ship"), gd.region("raid_leave_buttons"), timeout=4)
            if not hit:
                bot.click(bot.ui["abyss_exit"])
                hit = ui_text.wait(bot, gd.text("raid_leave_ship"), gd.region("raid_leave_buttons"), timeout=5)
            if not hit:
                continue
            bot.sleep(0.5, 0.8)
        if to_field:
            _click_text(bot, gd.text("raid_leave_field"), gd.region("raid_leave_buttons"), what="파티&던전 나가기")
            want = "Field"
            break
        bot.key("space")  # 출항선으로 이동
        if not bot.wait_packet(lambda s: s.loading, 6, since=bot.input_mark) and \
                ui_text.find(bot, gd.text("raid_leave_ship"), gd.region("raid_leave_buttons")):
            # 29판을 잘 돌다가 이 창에서만 Space 를 안 받고 창이 그대로 남았다 — 마우스로는 바로 넘어감 (2026-10-28)
            bot.log.info("Space 를 눌러도 출항선으로 안 넘어감 → '출항선으로 이동' 클릭")
            bot.click(hit)
        break
    bot.wait_packet(lambda s: s.loading, 15, since=bot.input_mark)
    end = time.monotonic() + bot.cfg["timing"]["loading"]
    while time.monotonic() < end:
        m = _map(bot)
        if m == "loading":
            bot.wait_loaded(end - time.monotonic())
            continue
        if m not in (RAID_MAP, "loading") and bot.at_main():
            if m and want == LOBBY_MAP and m != LOBBY_MAP:
                bot.log.warning(f"출항선이 아닌 곳({m})으로 나옴")
            return
        if m != RAID_MAP and not bot.is_loading():
            bot.clear_blockers(ocr=True)
        bot.sleep(2)
    raise StepTimeout("레이드에서 나온 뒤 메인 화면이 나오지 않음")


class RaidRepeat(Repeat):
    """레이드 반복 (혼자하기). 판이 끝나면 결과 → 출항선으로 나가 다시 출항한다."""
    KIND, TITLE = "raid", "레이드"
    INSIDE = ("play", "cleared", "ship")

    def target(self):
        return self.a["raid"] + (" / " + self.a["difficulty"] if self.a.get("difficulty") else "")

    def where(self):
        return where_settled(self.bot, self.a["raid"])

    def setup(self):
        self.bot.scene_skip = True  # 레이드는 연출이 길어 넘긴다 (사용자) — 뒤에서 도는 중이면 may_skip_scene 이 막는다

    def leave_for_switch(self, at):
        if at in ("play", "cleared"):
            if at == "cleared":
                finish_result(self.bot)
            leave(self.bot, to_field=True)

    def _next(self) -> str:
        return "ship" if _map(self.bot) in (LOBBY_MAP, None) else "entry"

    def loop(self, at):
        bot, a = self.bot, self.a
        raid, difficulty = a["raid"], a.get("difficulty", "")
        stage = {"play": "play", "cleared": "cleared", "ship": "ship"}.get(at, "entry")
        leftover = at == "cleared"  # 시작 전에 이미 잡아 둔 판 — 결과·나가기만 하고 판 수에는 넣지 않는다
        bot.log.info({"play": "이미 레이드 안 → 이 판부터", "cleared": "보스를 잡은 뒤 → 결과부터", "ship": "출항선 → 출항부터",
                      "entry": "레이드 입장 창 → 그 자리부터", "list": "레이드 목록 → 그 자리부터",
                      "menu": "메뉴가 열려 있음 → 그 자리부터"}.get(at, f"{at} → 메뉴에서 입장"))
        while True:
            if stage == "entry":
                bot.step("raid_open", f"레이드 입장 ({raid})")
                self.emit(stage="entry")
                bot.background = False
                self.recheck("main")  # 이름을 모른 채 이어 했으면 입장 전에 확인 (메인이라 나갈 것 없이 접속만)
                board(bot, raid, difficulty, at=at)
                at = ""
                stage = "ship"
            if stage == "ship" and _boarded != (raid, difficulty):
                bot.log.info(f"어느 레이드의 출항선인지 모름 (태운 것 {_boarded or '없음'}) → 내려서 '{raid}' 로 다시 입장")
                bot.background = False
                leave_ship(bot)
                stage = "entry"
                continue
            if stage == "ship":
                bot.step("raid_sail", "출항")
                self.emit(stage="sail")
                sail(bot)
                stage = "play"
            if stage == "play":
                # 출항(sail) 뒤에만 뒤로 보냈더니, 레이드 안에서 이어 하면 판 내내 게임을 앞으로 가져왔다 (2026-10-28)
                self.to_back()
                r = self.play_round(play, "raid_play")
                if r in ("dead", "timeout"):
                    self.stat["deaths" if r == "dead" else "retries"] += 1
                    bot.log.warning("쓰러짐(부활 횟수를 다 씀) → 나가서 다시 출항" if r == "dead" else
                                    f"{a['run_timeout'] / 60:.0f}분 안에 끝나지 않음 → 나가서 다시 출항 "
                                    f"→ {bot.snapshot('raid_timeout').name}")
                    leave(bot)
                    stage = self._next()
                    if self.done():
                        break
                    continue
                stage = "cleared"
            if stage == "cleared":
                finish_result(bot)
                if leftover:
                    bot.log.info("시작 전에 끝나 있던 판 → 나가서 다시 출항 (판 수에 넣지 않음)")
                    leftover = False
                else:
                    self.cleared()

                def go_out():
                    bot.background = False
                    leave(bot, to_field=True)
                if self.repair_between(go_out):
                    stage = "entry"
                    continue
                leave(bot)
                if self.done():
                    break
                stage = self._next()


def repeat(bot: Bot, cfg: dict, runs: int = 0, minutes: float = 0, on_event=lambda e: None,
           character: dict | None = None, loot=None) -> dict:
    """레이드를 반복한다 (RaidRepeat). runs·minutes 가 0 이면 사람이 멈출 때까지. 시간이 다 되면 그 판은 마저 끝낸다.
    character({slot, name})가 있으면 그 캐릭터로 접속해서 한다. 반환 {clears, deaths, retries, revives, seconds}."""
    return RaidRepeat(bot, cfg, runs, minutes, on_event, character, loot).run()
