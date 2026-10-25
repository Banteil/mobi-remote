"""커넥터 오류 코드 → 한국어 설명과 할 일 (리모콘 src/errors.js + 2026-10-15 판의 새 코드).

같은 코드라도 명령에 따라 뜻이 달라지는 경우(not_found 등)는 BY_COMMAND 가 덮어쓴다.
표에 없는 코드일 때만 영어 원문을 함께 보여준다 — 정보를 지우는 것보다 낫다.
"""
import re

COMMON = {
    # 전송 계층 (CLI 가 게임에 닿지 못함)
    "disconnected": ("게임에 연결할 수 없습니다", '게임이 실행 중인지, 설정에서 "MM AI 에이전트 활성화"가 켜져 있는지 확인하세요.'),
    "unknown_command": ("게임이 모르는 명령입니다", "게임이 업데이트되었을 수 있습니다. 옵션에서 호환성 검사를 다시 해 보세요."),
    "unsupported_command": ("지원하지 않는 명령입니다", ""),
    "usage_error": ("명령 사용법이 잘못되었습니다", ""),
    "spawn_failed": ("커넥터를 실행하지 못했습니다", "MabinogiMobile_CLI.exe 위치를 확인하세요."),
    "busy": ("다른 명령이 실행 중입니다", "끝난 뒤 다시 시도하세요."),
    "canceled": ("다른 명령이 이 동작을 대체했습니다", ""),
    "timeout": ("시간이 초과되어 중단되었습니다", "잠시 후 다시 시도하세요."),
    # 본문 / 대상
    "invalid_body": ("명령 본문 형식이 잘못되었습니다", "필수 항목이 빠졌거나 이름이 다릅니다."),
    "not_found": ("해당 이름을 찾을 수 없습니다", "게임에 표시되는 이름과 정확히 같아야 합니다. 표에서 골라 주세요."),
    "invalid_count": ("횟수가 시설 상한을 넘었습니다", "더 적은 횟수로 나눠서 시도하세요. (거부라 정령의 날개는 소모되지 않았습니다)"),
    # 상태
    "invalid_state": ("지금 멈출 수 있는 동작이 없습니다", '게임에 정지 버튼이 떠 있을 때만 동작합니다. 바닥에 앉은 상태라면 "일어나기"를 쓰세요.'),
    "not_sitting": ("앉아 있지 않습니다", '/앉기 로 앉은 상태에서만 일어날 수 있습니다. 의자에 앉았다면 "정지"를 쓰세요.'),
    "no_control_object": ("조작할 캐릭터가 없습니다", ""),
    # 던전·전장뿐 아니라 자동 이동이 막힌 특수 지역도 여기에 걸린다 (채집·제작·가공의 첫 단계가 자동 이동)
    "not_in_field": ("이곳에서는 자동 이동을 쓸 수 없습니다", "던전·전장·하우징이나 일부 특수 지역에서는 불가합니다. 일반 필드로 나간 뒤 다시 시도하세요."),
    "blocked": ("게임 화면에 처리할 것이 있어 중단되었습니다", "게임에서 뜬 창이나 선택지를 정리한 뒤 다시 시도하세요."),
    "requires_user_interaction": ("게임에서 직접 조작해야 합니다", "게임 화면을 확인하세요."),
    "overweight": ("소지 무게를 초과했습니다", "창고에 넣거나 정리한 뒤 다시 시도하세요."),
    "no_route": ("그 장소로 가는 경로를 찾을 수 없습니다", "다른 지역에 있거나 이동이 막혀 있을 수 있습니다."),
    "interrupted_by_attack": ("공격을 받아 중단되었습니다", "주변 몬스터를 정리한 뒤 다시 시도하세요."),
    # 비용
    "not_enough_currency": ("재화가 부족합니다", "정령의 날개 잔량을 확인하세요."),
    "cost_payment_failed": ("비용 지불에 실패했습니다", ""),
    "insufficient_transfer_cost": ("보관함 재료를 꺼낼 비용이 부족합니다",
                                   "분해된 장비 부품이 모자랍니다. 장비를 분해해 채우거나 재료를 가방으로 옮긴 뒤 다시 시도하세요."),
    # 자격 / 해금
    "insufficient_living_skill_level": ("생활 스킬 레벨이 부족합니다", "해당 생활 스킬을 더 올려야 합니다."),
    "insufficient_facility_level": ("시설 레벨이 부족합니다", ""),
    "insufficient_decor_score": ("데코 점수가 부족합니다", ""),
    "crafting_locked": ("제작 기능이 아직 해금되지 않았습니다", ""),
    "not_available": ("지금은 사용할 수 없습니다", ""),
    "facility_not_found": ("해당 시설을 찾을 수 없습니다", "시설이 해금되지 않았거나 접근할 수 없습니다."),
    "queue_full": ("가공 시설의 칸이 꽉 찼습니다", "완료된 작업을 수령해 칸을 비운 뒤 다시 시도하세요."),
    # 재료 / 도구
    "not_enough_ingredient": ("재료가 부족합니다", '갱신 후 해당 항목의 "부족 재료" 칸을 확인하세요.'),
    "ingredient_locked": ("재료가 잠겨 있습니다", "게임에서 해당 아이템의 잠금을 풀어 주세요."),
    "required_consumable_missing": ("필요한 소모품이 없습니다", "빈 병처럼 채집에 함께 쓰이는 아이템이 필요합니다. 중간에 바닥나도 여기서 멈춥니다."),
    "tool_missing": ("채집 도구가 없습니다", "해당 채집에 맞는 도구를 갖춰 주세요."),
    "tool_broken": ("채집 도구가 망가졌습니다", "도구를 수리하거나 교체하세요."),
    # 가공 작업
    "no_altering": ("가공 작업이 없습니다", ""),
    "no_completed_work": ("완료된 가공 작업이 없습니다", ""),
    "no_completed_work_at_facility": ("그 시설에 완료된 작업이 없습니다", "다른 시설의 작업을 수령해 보세요."),
    "not_completed_yet": ("아직 완료되지 않았습니다", "남은 시간이 지난 뒤 다시 수령하세요."),
    # 채팅 (2026-10-15 판부터 매번 게임 안 확인 창)
    "user_declined": ("게임에서 보내기를 취소했습니다", "같은 메시지를 다시 보내려면 다시 실행하세요."),
    "confirm_timeout": ("게임 확인 창에 답이 없어 취소되었습니다", "게임 화면에서 확인 창을 눌러 주세요."),
    "inappropriate_text": ("부적절한 문장으로 걸러졌습니다", "욕설·비방·개인정보가 없도록 문장을 고쳐 보내세요."),
    "rate_limited": ("너무 자주 보냈습니다", "잠시 후 다시 보내세요."),
    # 내부
    "query_failed": ("조회에 실패했습니다", ""),
    "unknown_query": ("알 수 없는 조회입니다", ""),
}

BY_COMMAND = {
    "execute_gathering": {
        "not_found": ("채집할 수 없는 대상입니다", "채집 목록에 있는 이름이어야 합니다. 생활 스킬 레벨이 모자라면 목록에 나오지 않습니다."),
        "overweight": ("소지 무게를 초과해 채집을 멈췄습니다", "이미 모은 양은 유지됩니다. 정리 후 이어서 채집하세요."),
    },
    "execute_crafting": {
        "not_found": ("그런 제작 레시피가 없습니다", "옷감·목재·가죽·철괴 등은 제작이 아니라 가공입니다."),
        "not_available": ("지금 제작할 수 없는 레시피입니다", ""),
        # 목록의 ✔ 는 1회 기준이라 여러 회를 시도하면 여기서 걸린다
        "not_enough_ingredient": ("재료가 부족합니다", "목록의 ✔는 1회 기준입니다. 횟수를 줄여 보세요. (거부라 정령의 날개는 소모되지 않았습니다)"),
    },
    "execute_altering": {
        "not_found": ("그런 가공 레시피가 없습니다", "가공 목록에서 정확한 이름을 확인하세요."),
        "not_enough_ingredient": ("재료가 부족합니다", '가공 목록을 갱신하면 "부족 재료" 칸에 무엇이 얼마나 모자란지 나옵니다.'),
    },
    "complete_altering_work": {
        "not_found": ("그런 가공 대상이 없습니다", "수령은 시설 단위입니다. 그 시설에서 만드는 아이템 이름을 지정하세요."),
    },
    "change_instrument": {"not_found": ("보유하지 않은 악기입니다", "악기 목록에서 고르세요.")},
    "play_music_score": {
        "not_found": ("보유하지 않은 악보입니다", "악보 목록에서 고르세요."),
        "user_composed_not_allowed": ("직접 만들거나 복사한 악보는 연주할 수 없습니다", "커넥터로는 게임이 준 악보(상점·보상)만 연주됩니다."),
        "no_instrument": ("악기를 들고 있지 않습니다", "악기를 먼저 장착하세요."),
        "not_available_on_combat": ("전투 중에는 연주할 수 없습니다", ""),
        "not_available_on_riding": ("탑승 중에는 연주할 수 없습니다", ""),
        "not_available_on_dead": ("쓰러진 상태에서는 연주할 수 없습니다", ""),
    },
}

# blocked 는 본문의 kind 가 무엇이 막았는지 알려 준다 (할 일이 kind 마다 다르다)
BLOCKED_KIND = {
    "dead": ("커넥터가 쓰러진 상태로 보고 있습니다",
             "실제로 쓰러져 있다면 게임에서 부활 방법을 고른 뒤 다시 시도하세요. 멀쩡한데 계속 이러면 게임에 다시 접속해 보세요."),
}

RECIPE_REASON = {
    "not_enough_ingredient": "재료 부족", "insufficient_living_skill_level": "생활 레벨 부족",
    "insufficient_facility_level": "시설 레벨 부족", "insufficient_decor_score": "데코 점수 부족",
    "queue_full": "시설 칸 없음", "ingredient_locked": "재료 잠김", "insufficient_transfer_cost": "반출 비용 부족",
}


def describe(command: str | None, error: str | None, raw: str = "", data=None) -> dict:
    """{code, text, hint, raw, known}"""
    code = str(error or "").strip()
    entry = BY_COMMAND.get(command or "", {}).get(code) or COMMON.get(code)
    text, hint = entry if entry else (None, "")
    if isinstance(data, dict):
        if code == "blocked" and data.get("kind"):
            k = BLOCKED_KIND.get(data["kind"])
            if k:
                text, hint = k
            else:
                hint = f"막은 요소: {data['kind']}. {hint}"
        if code == "invalid_count" and data.get("maxCount") is not None:
            hint = f"이 시설의 1회 상한은 {data['maxCount']}회입니다."
        if code in ("overweight", "blocked", "interrupted_by_attack", "required_consumable_missing") \
                and data.get("gained") is not None:
            hint = (hint + " " if hint else "") + f"중단 전까지 {data['gained']}개 얻었습니다."
        if code == "rate_limited" and data.get("retryAfterSeconds"):
            hint = f"{data['retryAfterSeconds']}초 뒤에 다시 보내세요."
    # 생활 스킬 요구 레벨은 어느 조회로도 알 수 없다. 이 거부 메시지가 숫자를 말해 주는 유일한 자리라 원문을 붙인다
    if code == "insufficient_living_skill_level" and re.search(r"\d", raw or ""):
        hint = (hint + " " if hint else "") + f"게임 메시지: {raw}"
    return {"code": code, "text": text or code or "알 수 없는 오류", "hint": hint, "raw": raw or "", "known": bool(entry)}


def line(command, error, raw="", data=None) -> str:
    """한 줄 요약. 번역이 있으면 한국어만, 표에 없는 코드면 영어 원문을 덧붙인다."""
    d = describe(command, error, raw, data)
    base = d["text"] + (f" — {d['hint']}" if d["hint"] else "")
    return base if d["known"] or not d["raw"] else f"{base} ({d['raw']})"


def reason_text(code: str | None) -> str:
    return RECIPE_REASON.get(code, str(code)) if code else ""
