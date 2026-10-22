"""은동전 소모: 20개(unit) 단위로 사냥터/던전에 배분.

캐릭터별 계획은 config.toml 의 [silver] 기본값을 [silver.by_slot.<슬롯>] 이 덮어쓴다.
  field_runs        사냥터 최대 횟수 (0 이면 사냥터 안 감)
  dungeon           남은 은동전으로 돌 던전 (빈 문자열이면 던전 안 감)
  min_units_for_field  은동전이 이 단위 이상 있을 때만 사냥터를 간다
                    (기본 2: 20개뿐이면 던전 1회만, 40개 이상이면 사냥터부터)
예) 어떤 캐릭터 = 사냥터 2회, 남은 건 피오드 던전 → field_runs = 2, dungeon = "피오드 던전"
"""
from ..bot import Bot, StepTimeout
from . import black_hole
from .content import (CannotProceed, enter_from_dungeon_window, go_to_place, has_word, play_field, read_button,
                      select_zone)


def verify(bot: Bot, cfg: dict) -> bool:
    """은동전이 한 단위(20) 미만으로 남았으면 완료."""
    coins = bot.read_counter("silver")
    return coins is not None and coins < cfg["silver"]["unit"]


def settings(cfg: dict, slot: int | None) -> dict:
    """[silver] 기본값에 캐릭터별 설정을 덮어쓴 결과."""
    base = {k: v for k, v in cfg["silver"].items() if k != "by_slot"}
    if slot is not None:
        base.update(cfg["silver"].get("by_slot", {}).get(str(slot), {}))
    return base


def plan(coins: int, s: dict) -> tuple[int, int]:
    """(사냥터 횟수, 던전 횟수)"""
    units = coins // s["unit"]
    field = 0
    if units >= s["min_units_for_field"] or not s["dungeon"]:
        field = min(s["field_runs"], units)
    dungeon = units - field if s["dungeon"] else 0
    return field, dungeon


def dungeon_once(bot: Bot, c: dict, again: bool = False, more: bool = False) -> str:
    """지도로 던전 입구까지 이동 → 난이도/층/구역 선택 → 입장 → 클리어. 반환 'clear' | 'fail' | 'again'.
    again: 직전 보상 화면에서 '다시 하기'를 눌러 같은 구역의 임무 화면이 이미 열려 있음 (이동·구역 선택 생략).
    more: 이번 뒤에 던전을 더 돌 예정 → 보상 화면에서 '다시 하기'로 바로 이어간다."""
    ui = bot.ui
    retry_btn = ui["dungeon_retry"] if more else None
    if again:
        try:
            return enter_from_dungeon_window(bot, c["clear_timeout"], expect_cost=c["dungeon_cost"],
                                             again=retry_btn, retry=True)
        except StepTimeout:
            bot.log.warning(f"다시 하기 후 임무 화면이 안 보임, 지도로 다시 이동 → {bot.snapshot('dungeon_again').name}")
            bot.to_main()
    m = go_to_place(bot, c["dungeon"], arrive=[ui["dungeon_tab_normal"], ui["dungeon_tab_deep"]],
                    timeout=c["travel_timeout"])
    bot.sleep(1, 1.5)
    # 던전 창은 돌 수 있는 가장 어려운 단계로 열린다. 심층 던전이 있는 던전(피오드·룬다 제외)은
    # '심층 던전' 탭으로 열리므로, 은동전 숙제는 반드시 '던전' 탭으로 바꾼다 (이후 구역 확인·입장 가격 확인으로 한 번 더 막는다)
    if m.name == ui["dungeon_tab_deep"]:
        bot.click(ui["dungeon_tab_normal_off"], timeout=5)
        bot.wait(ui["dungeon_tab_normal"], timeout=5)
        bot.sleep(0.8, 1.2)
    select_zone(bot, c["difficulty"], c["floor"], c["zone"])
    return enter_from_dungeon_window(bot, c["clear_timeout"], expect_cost=c["dungeon_cost"], again=retry_btn)


def field_once(bot: Bot, c: dict, again: bool = False, more: bool = False) -> str:
    """지도로 사냥터 입구까지 이동 → 입장 버튼 가격 확인 → 입장 → 클리어. 반환 'clear' | 'again'.
    again: 직전 사냥터 보상 화면에서 '새 임무 선택'을 눌러 이미 사냥터 창이 열려 있음 (이동 생략, 버튼은 '임무 시작').
    more: 이번 뒤에 사냥터를 더 돌 예정 → 보상 화면에서 '새 임무 선택'으로 바로 이어간다."""
    ui = bot.ui

    def button() -> str:
        price, win, ko = read_button(bot.frame(), ui["mission_button_region"])
        return f"{win} | {ko}" if (win or ko) else ""
    text = ""
    if again:
        try:
            bot.wait(ui["field_mission_start"], timeout=15)
            bot.sleep(0.8, 1.2)
            text = button()
        except StepTimeout:
            bot.log.warning(f"새 임무 선택 후 사냥터 창이 안 보임, 지도로 다시 이동 → {bot.snapshot('field_again').name}")
            bot.to_main()
    for attempt in range(2):
        if text:
            break
        go_to_place(bot, c["field"], arrive=[ui["dungeon_mission_enter_silver"]], timeout=c["travel_timeout"])
        bot.sleep(1, 1.5)
        text = button()
        if not text and not attempt:
            # 도착 직후 사냥터 창이 잠깐 떴다가 닫히는 경우가 있다 (탈것에서 내리는 중 등) → 한 번 더 이동
            bot.log.warning(f"사냥터 창이 닫힘, 다시 이동 → {bot.snapshot('field_window').name}")
    select_recommended(bot)
    # 처음엔 '20 입장하기', 새 임무 선택으로 돌아오면 '20 임무 시작'. 가격은 Windows OCR, 글자는 둘 중 하나
    price, win, ko = read_button(bot.frame(), ui["mission_button_region"])
    if price != c["dungeon_cost"] or not has_word("입장", win, ko) and not has_word("시작", win, ko):
        raise CannotProceed(f"사냥터 입장 버튼 '{win}' / '{ko}' — 비용 {c['dungeon_cost']} 이 아님 "
                            f"→ {bot.snapshot('field_cost').name}")
    on_enter = black_hole_first if c.get("black_hole_in_field") and "black_hole" not in bot.also_done else None
    return play_field(bot, c["field"], c["field_timeout"], on_enter=on_enter,
                      again=ui["field_new_mission"] if more else None)


def select_recommended(bot: Bot) -> None:
    """사냥터 창은 지난번에 들어간 난이도로 열리므로, 추천 표시가 붙은 난이도 버튼을 누른다.
    추천 표시는 버튼 아래 '✦추천✦' 글자와 버튼 오른쪽 위 엄지 아이콘이 번갈아 나온다."""
    ui = bot.ui
    y = bot.cfg["silver"]["field_difficulty_y"]
    try:
        m = bot.wait_any([ui["field_recommend"], ui["field_recommend_thumb"]], timeout=5)
    except StepTimeout:
        bot.log.warning(f"사냥터 추천 난이도 표시를 못 찾음, 선택된 난이도로 진행 → {bot.snapshot('field_diff').name}")
        return
    # 글자는 버튼 바로 아래 가운데, 엄지는 버튼 오른쪽 위 모서리에 붙는다
    x = m.center[0] if m.name == ui["field_recommend"] else m.center[0] - 45
    bot.click((x, y))
    bot.sleep(0.8, 1.2)


def black_hole_first(bot: Bot) -> None:
    """사냥터에 들어간 직후 검은 구멍부터 한 번. 끝나면 밖으로 나와 사냥터 임무가 자동으로 이어진다.
    실패해도 사냥터는 계속 기다리고, 검은 구멍 태스크가 나중에 다시 시도한다."""
    try:
        bot.log.info(f"사냥터 안 검은 구멍: {black_hole.run(bot, bot.cfg)}")
        bot.also_done.add("black_hole")
    except (StepTimeout, CannotProceed, RuntimeError) as e:
        bot.log.warning(f"사냥터 안 검은 구멍 실패, 사냥터는 계속 진행: {e} → {bot.snapshot('field_blackhole').name}")


def run(bot: Bot, cfg: dict) -> str:
    c = settings(cfg, bot.character["slot"] if bot.character else None)
    bot.to_main()
    coins = bot.read_counter("silver")
    if coins is None:
        raise RuntimeError("은동전 개수를 읽을 수 없어 중단")

    # 중간에 끊겼다 다시 실행하는 경우, 오늘 이미 끝낸 사냥터 횟수만큼 뺀다
    slot = bot.character["slot"] if bot.character else None
    fields_done = int(bot.daily.get(slot, "silver_fields") or 0) if bot.daily and slot else 0
    # 사냥터 1판 도중에 끊겼으면: 접속 단계가 그 판을 클리어까지 보고 나왔다 (은동전은 들어갈 때 이미 나감)
    # → 들어가기 전 은동전보다 줄었으면 그 판은 한 것으로 센다
    pend = bot.daily.get(slot, "silver_pending") if bot.daily and slot else None
    if isinstance(pend, dict):
        if pend.get("kind") == "field" and pend.get("coins") is not None and coins <= pend["coins"] - c["dungeon_cost"]:
            fields_done += 1
            bot.daily.set(slot, "silver_fields", fields_done)
            bot.log.info(f"지난번 끊긴 사냥터 {pend.get('n')}회차는 은동전이 나갔으므로 한 것으로 셈")
        bot.daily.set(slot, "silver_pending", None)
    if fields_done:
        c = dict(c, field_runs=max(0, c["field_runs"] - fields_done))
    field_runs, dungeon_runs = plan(coins, c)
    bot.log.info(f"은동전 {coins}개 → 사냥터 {field_runs}회, 던전 {dungeon_runs}회"
                 + (f" (오늘 사냥터 {fields_done}회 완료)" if fields_done else ""))
    if not field_runs and not dungeon_runs:
        return f"은동전 {coins}개, 진행 없음"

    notes = []
    for label, runs, once in (("사냥터", field_runs, field_once), ("던전", dungeon_runs, dungeon_once)):
        if not runs:
            continue
        results = []
        again = False
        for i in range(runs):
            try:
                before = bot.state.currency("은동전")
                kind = "field" if once is field_once else "dungeon"
                bot.step(f"silver_{kind}", f"{label} {i + 1}/{runs}회 (은동전 {before})", n=i + 1, runs=runs)
                if bot.daily and slot:
                    bot.daily.set(slot, "silver_pending", {"kind": kind, "n": i + 1, "coins": before})
                r = once(bot, c, again=again, more=i < runs - 1)
                if bot.daily and slot:
                    bot.daily.set(slot, "silver_pending", None)
                again = r == "again"
                # 화면(가격 OCR·버튼 템플릿)으로 판단한 입장을 CLI 은동전 변화로 한 번 더 확인한다
                after = bot.state.currency("은동전")
                if before is not None and after is not None and before - after != c["dungeon_cost"]:
                    bot.log.warning(f"{label} 1회에 은동전 {before} → {after} (예상 -{c['dungeon_cost']})")
                results.append("clear" if again else r)
                if once is field_once and results[-1] == "clear" and bot.daily and slot:
                    fields_done += 1
                    bot.daily.set(slot, "silver_fields", fields_done)
            except CannotProceed as e:  # 진행 불가 (미해금, 비용 불일치 등) → 이 종류는 그만두고 다음으로
                bot.log.warning(f"{label} 진행 불가: {e}")
                notes.append(f"{label} 진행 불가")
                bot.to_main()
                break
        notes.append(f"{label} 클리어 {results.count('clear')}/{runs}")

    bot.to_main()
    left = bot.read_counter("silver")
    return f"은동전 {coins} → {left}, " + ", ".join(notes)
