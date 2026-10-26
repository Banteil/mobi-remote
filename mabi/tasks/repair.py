"""대장간 전체 수리. 어비스 반복 중 장비 내구도가 낮아지면 판 사이에 다녀온다 (사용자 2026-10-25).

흐름 (사용자 설명 · 2026-10-25 테스트, 괄호 안 대사·패킷 이름은 그때 본 예 — NPC 마다 대사·마디 수가 달라 판단에 쓰지 않는다.
판단은 패킷의 선택지 떠 있음 · 대사 단계가 넘어갔나 · 화면의 버튼 글자로만 한다):
  메인 화면 → 퀵 내비게이터('.' 키 — 캐릭터를 눌렀을 때 뜨는 메뉴, '주요' 탭: 잡화점·대장간 …)
  → '대장간' = 가장 가까운 대장간으로 자동 이동 (빠른 이동 T) → 도착하면 대장간 NPC 대화가 저절로 열린다
  → 첫 대사 → 메뉴 (수리 · 특화 · 각인 강화 …)
  → '수리' → NPC 한마디("수리는 자신 없는데에…", 패킷 OpenNPCRepair) → 넘기면 수리하기 창
    (도구 수리 / 장착 장비 수리 / 전체 수리 Space) → Space
  → '소지한 장비 수리 — 총 N개의 장비를 수리하시겠습니까?' 수리하기 Space → 수리 성공(패킷) → NPC 한마디 + 메뉴(AfterRepair)
  → ESC '대화 종료' → 작별 인사(EndDialogue, 눌러야 끝남) → 메인 화면
대사 넘기기 · 메뉴에서 '수리' 고르기 · 대화 마치기는 점검자 몫 (Ctx choose · leave). 여기는 이동과 수리 창만 본다.
고칠 장비가 없으면 '수리' 버튼이 꺼져 있어 눌러도 아무 일이 없다 (패킷도 안 옴) → 고칠 게 없는 것으로 끝낸다.
내구도는 패킷(장비 내구도 깎임 알림 = 현재/최대 비율)으로만 안다. CLI 에는 장비 내구도가 없다.
"""
import time

from .. import gamedata as gd
from ..bot import Bot
from . import dialogue, ui_text
from .content import CannotProceed

def _find(bot: Bot, key: str, region: str, exact: bool = True):
    return ui_text.find(bot, gd.text(key), gd.region(region), exact)


def _wait(bot: Bot, key: str, region: str, timeout: float, exact: bool = True):
    return ui_text.wait(bot, gd.text(key), gd.region(region), timeout, exact)


def durability(bot: Bot) -> float | None:
    """수리 뒤로 본 장비 내구도 비율 중 가장 낮은 것 (패킷). 모르면 None."""
    return bot.packets.state.durability if bot.packets.ok else None


def needed(bot: Bot, below: float) -> bool:
    d = durability(bot)
    return bool(below) and d is not None and d <= below


def _repair_window(bot: Bot) -> bool:
    return bool(_find(bot, "repair_all", "repair_buttons", exact=False))


def _close_repair_window(bot: Bot) -> bool:
    """대화 처리기: 수리하기 창이 떠 있으면 ESC 로 닫는다."""
    if not dialogue.menu_open(bot) and _repair_window(bot):
        bot.key("esc")
        bot.sleep(1.2, 1.6)
        return True
    return False


def _leave_npc(bot: Bot) -> None:
    dialogue.leave(bot, handlers=(lambda: _close_repair_window(bot),))


def _open_quick_nav(bot: Bot) -> tuple[int, int]:
    """퀵 내비게이터(단축키 '.', 캐릭터를 눌렀을 때 뜨는 그 메뉴)를 열고 '대장간' 자리를 돌려준다. 몇 번 해도 안 열리면 CannotProceed.
    메뉴 글자 읽기에 3~4초 걸린다 → 6초까지 본다."""
    key = bot.cfg["game"].get("quick_nav_key") or "."
    for i in range(3):
        _leave_npc(bot)
        bot.key(key)
        hit = _wait(bot, "repair_smithy", "char_menu", 6, exact=False)
        if not hit and (tab := _find(bot, "char_menu_main", "char_menu")):  # 다른 탭이 열려 있다 → '주요'
            bot.click(tab)
            hit = _wait(bot, "repair_smithy", "char_menu", 6, exact=False)
        if hit:
            return hit
        bot.log.info(f"퀵 내비게이터가 안 열림 ({i + 1}/3) → 다시")
        bot.key("esc")
        bot.sleep(1.0, 1.4)
    raise CannotProceed(f"퀵 내비게이터(대장간)가 열리지 않음 → {bot.snapshot('repair_menu').name}")


def _moving(bot: Bot) -> bool | None:
    """'대장간' 을 누른 뒤 움직이기 시작했나 (패킷: 자동 이동 · NPC 에게 다가가는 AI · 대화 시작 · 맵 이동). 모르면 None."""
    if not bot.packets.ok:
        return None
    return bot.wait_packet(lambda s: s.traveling or s.loading or bool(s.ai) or s.in_dialogue, 5)


def _go_smithy(bot: Bot) -> None:
    """퀵 내비게이터 '대장간' → 도착해 대장간 NPC 대화가 열릴 때까지 (도착하면 대화가 저절로 열린다).
    눌렀는데 패킷으로 움직임이 없으면 메뉴를 다시 열어 한 번 더. 이동 중 빠른 이동이 되면 T."""
    for attempt in range(2):
        bot.click(_open_quick_nav(bot))
        if _moving(bot) is not False:
            break
        bot.log.info("'대장간' 을 눌렀는데 움직이지 않음 (패킷) → 메뉴를 다시 엶")
    else:
        raise CannotProceed(f"'대장간' 을 눌러도 움직이지 않음 → {bot.snapshot('repair_menu').name}")
    bot.log.info("대장간으로 이동")
    key = bot.cfg["game"].get("fast_travel_key")
    fast = False
    end = time.monotonic() + bot.cfg["abyss"].get("travel_timeout", 300)
    while time.monotonic() < end:
        if bot.map_loading():
            bot.wait_loaded(end - time.monotonic())
            continue
        if dialogue.talking(bot):  # 도착해 대화가 열림 — 메뉴는 인사말을 넘긴 뒤에 뜬다 (_open_repair)
            return
        if key and not fast and bot.fast_travel_ok():
            bot.log.info("빠른 이동")
            bot.key(key)
            fast = True
        bot.sleep(1.5, 2)
    raise CannotProceed(f"대장간 NPC 대화가 열리지 않음 → {bot.snapshot('repair_npc').name}")


def _open_repair(bot: Bot) -> bool:
    """메뉴 '수리' → 수리하기 창. 열렸으면 True, 고칠 장비가 없어 아무 일이 없으면 False.
    인사말 넘기기 · 메뉴 버튼이 그려지길 기다렸다 '수리' 누르기 · 그 뒤 NPC 한마디("수리는 자신 없는데에…") 넘기기는 점검자가 한다
    (대장간 NPC 마다 대사·마디 수가 다를 수 있다). 고칠 장비가 없으면 '수리' 가 꺼져 있어 눌러도 대사가 그대로다 (패킷)."""
    from .. import monitor
    mon = monitor.of(bot)
    ctx = monitor.Ctx("repair", "대장간 메뉴", choose=gd.text("repair"), choose_region="npc_buttons")
    end = time.monotonic() + 40
    picked, last = 0, None
    while time.monotonic() < end:
        if _repair_window(bot):
            return True
        before = dialogue.step(bot)
        seen = mon.check(ctx, guard=False)
        last = seen.done or last
        if ctx.take("chosen"):
            picked += 1
            # 패킷이 없으면 대사가 넘어갔는지 몰라 — 몇 번 눌러도 수리하기 창이 안 뜨면 고칠 장비가 없는 것으로
            if dialogue.wait_next(bot, before, 4) is False or picked >= 3:
                return False
            continue
        if not seen.done:
            bot.sleep(0.8, 1.2)
    why = "대장간 메뉴에 '수리' 가 없음" if last == "선택지 기다림" else "수리하기 창이 열리지 않음"
    raise CannotProceed(f"{why} → {bot.snapshot('repair_open').name}")


def run(bot: Bot) -> None:
    """대장간에 가서 전체 수리하고 메인 화면으로 돌아온다. 못 하면 CannotProceed."""
    before = durability(bot)
    bot.log.info(f"장비 수리하러 감 (내구도 {before * 100:.0f}%)" if before is not None else "장비 수리하러 감")
    bot.step("repair", "대장간에서 장비 수리")
    bot.background = False  # 클릭이 많다 — 게임을 앞에 둔다
    _go_smithy(bot)
    if not _open_repair(bot):
        bot.log.info("'수리' 를 눌러도 아무 일이 없음 — 고칠 장비가 없음")
        bot.packets.state.durability = None
        _leave_npc(bot)
        return
    mark = bot.packets.mark()
    bot.key("space")  # 전체 수리
    if not _wait(bot, "repair_confirm", "repair_confirm", 8, exact=False):
        raise CannotProceed(f"수리 확인 창이 뜨지 않음 (골드 부족?) → {bot.snapshot('repair_confirm').name}")
    bot.sleep(0.6, 0.9)
    bot.key("space")  # 수리하기
    end = time.monotonic() + 10
    ok = False
    while time.monotonic() < end:
        bot.sleep(1.0)
        if bot.packets.find("equip.repair_fail", mark):
            raise CannotProceed(f"수리 실패 (패킷 — 골드 부족 등) → {bot.snapshot('repair_fail').name}")
        if bot.packets.find("equip.repair_ok", mark):
            ok = True
            break
        if not _find(bot, "repair_confirm", "repair_confirm", exact=False):
            break
    if ok:
        bot.log.info("패킷: 수리 성공")
    elif _find(bot, "repair_confirm", "repair_confirm", exact=False):
        raise CannotProceed(f"수리 확인 창이 닫히지 않음 → {bot.snapshot('repair_confirm').name}")
    else:
        bot.log.info("수리 확인 창 닫힘 (패킷 수리 신호는 못 받음)")
    bot.packets.state.durability = None  # 다음 깎임 알림부터 다시 잰다 (수리 신호를 못 받았어도)
    _leave_npc(bot)  # 수리 뒤 메뉴 → 대화 종료 → 작별 인사 → 메인 화면
    bot.log.info("장비 수리 끝")
