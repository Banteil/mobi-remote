"""제작·가공·채집·수령 명령 하나를 실행하면서 배울 것을 챙긴다 (리모콘 app/main.js 의 'exec' 처리).

- 가공 등록 전에 그 시설 칸을 센다. 칸이 없는데 보내면 게임이 이동까지 시킨 뒤 막으면서 날개 5를 가져간다(실측) —
  그래서 커넥터에 넘기기 전에 facility_full 로 끊는다.
- 레시피 표(recipes.json)에 없는 레시피만 1회 제작·가공 전후 인벤을 비교해 재료를 역산한다 (패치로 새로 생긴 것).
- 가공이 blocked/queue_full 로 막히고 큐가 그대로면 그 개수가 곧 칸 수 → 레벨까지 확정된다.
  queue_full 은 2026-10-15 판부터 execute_altering 이 시작 전·후 모두 직접 알려 주는 칸 없음 신호다.
- 수령 시설에 완료된 것이 한 종류뿐이면 받은 보상이 곧 그 레시피의 산출물이다.
학습 실패는 실행 결과에 영향을 주지 않는다. 비용 확인(사용자 동의)은 부르는 쪽 몫이다.
"""
import time
from dataclasses import dataclass
from typing import Callable

from .. import errors
from ..cache import QueryCache
from ..connector import Connector

FULL_ERRORS = ("blocked", "queue_full")


@dataclass
class ExecResult:
    ok: bool
    code: int
    error: str | None = None
    message: str | None = None
    data: object = None
    duration_ms: int = 0
    wings_spent: int = 0          # 게임이 알려 준 실제 소모량 우선, 없으면 성공 시 추정 비용
    cost_info: dict | None = None  # knowledge.parse_cost 결과
    ko: dict | None = None         # errors.describe 결과 (실패일 때)
    facility_level: dict | None = None  # 이번에 칸 수·레벨이 새로 확정됐으면 {facility, level, slots}

def recipe_learn_kind(command: str, body) -> str | None:
    """레시피를 배울 수 있는 명령인가. 제작은 1회일 때만, 가공은 큐에 올리는 순간 재료가 빠진다."""
    if command == "execute_crafting":
        n = (body or {}).get("craftCount") if isinstance(body, dict) else None
        return "craft" if n is None or n == 1 else None
    if command == "execute_altering":
        return "alter"
    return None


def _works(cli: Connector) -> list | None:
    try:
        r = cli.run("get_altering_works")
    except Exception:
        return None
    if not r.ok:
        return None
    return (r.data or {}).get("works") or [] if isinstance(r.data, dict) else []


def facility_used(cli: Connector, facility: str) -> int | None:
    """그 시설 큐에 몇 건이 올라가 있는지 (완료분도 칸을 차지하므로 전부 센다). 못 세면 None."""
    works = _works(cli)
    return None if works is None else sum(1 for w in works if w.get("FacilityName") == facility)


def sole_completed_recipe(cli: Connector, display_name: str) -> str | None:
    """수령 직전, 그 시설에 완료된 가공이 한 종류뿐인가. 섞여 있으면 어느 보상이 누구 것인지 몰라 배우지 않는다."""
    works = _works(cli)
    if not works:
        return None
    mine = next((w for w in works if w.get("DisplayName") == display_name), None)
    if not mine:
        return None
    names = {w.get("DisplayName") for w in works if w.get("IsCompleted") and w.get("FacilityName") == mine.get("FacilityName")}
    return next(iter(names)) if len(names) == 1 else None


def produced_per_work(qc: QueryCache, display_name: str):
    """가공 1건 산출량. 캐시된 조회에서 꺼낸다 (호출 없음). 자주 안 바뀌어 오래된 것이라도 쓴다."""
    c = qc.read("get_alterable_items", 24 * 3600)
    items = (c["data"] or {}).get("items") or [] if c and isinstance(c.get("data"), dict) else []
    hit = next((x for x in items if x.get("DisplayName") == display_name), None)
    return hit.get("ProducedPerWork") if hit else None


def item_snapshot(cd, cli: Connector) -> dict | None:
    """인벤 스냅샷. 실패하면 None — 학습을 포기할 뿐 실행에는 영향이 없다."""
    try:
        r = cli.run("get_items")
        return cd.knowledge.item_totals(r.data) if r.ok else None
    except Exception:
        return None


def execute(cd, cli: Connector, qc: QueryCache, command: str, body=None, timeout: float | None = None,
            on_facility_level: Callable[[dict], None] | None = None) -> ExecResult:
    """명령 하나 실행 + 학습. 비용이 있는 명령은 부르는 쪽이 미리 사용자 확인을 받아야 한다."""
    kn = cd.knowledge
    started = time.monotonic()

    def ms():
        return int((time.monotonic() - started) * 1000)

    if cli.busy():
        return ExecResult(False, -1, "busy", "다른 명령이 실행 중입니다.",
                          ko=errors.describe(command, "busy"))
    cost = cli.cost_of(command)
    name = body.get("displayName") if isinstance(body, dict) else None

    # 레시피를 배울 명령이면 먼저 인벤을 찍어 둔다 (get_items 는 무료). 표에 있는 레시피는 배울 것이 없다
    learn_kind = recipe_learn_kind(command, body) if not cd.recipes.has(name) else None
    snap_before = item_snapshot(cd, cli) if learn_kind else None

    # 가공이면 그 시설 큐를 미리 센다 — 막힌 뒤에도 큐가 그대로인지 봐야 칸 수를 배울 수 있다
    alter_facility = kn.facility_of(name) if command == "execute_altering" and name else None
    used_before = facility_used(cli, alter_facility) if alter_facility else None

    if alter_facility and used_before is not None:
        room = kn.facility_room(alter_facility, used_before)
        if not room["ok"]:
            return ExecResult(False, 0, "facility_full", f"{alter_facility} {room['used']}/{room['slots']}",
                              None, ms(), 0, None,
                              {"code": "facility_full", "text": f"{alter_facility} 칸이 가득 찼습니다",
                               "hint": f"최대 {room['slots']}칸({room['source']}) 중 {room['used']}칸을 쓰고 있습니다. "
                                       "완료분을 수령해 칸을 비우거나, 레벨을 다시 확인하세요.",
                               "raw": "", "known": True})

    # 가공 수령은 "이 레시피가 무엇을 만드는가"를 알 수 있는 유일한 순간이다
    sole = sole_completed_recipe(cli, name) if command == "complete_altering_work" and name else None

    r = cli.run(command, body, timeout=timeout)
    if r.ok and command.startswith("get_"):
        qc.write(command, r.data)
    data = r.data if isinstance(r.data, dict) else {}

    spent = None
    try:
        spent = kn.parse_cost(r.data)  # 게임이 알려 준 실제 소모량이 추정치보다 사실이다
        if data.get("error") == "invalid_count" and data.get("maxCount"):
            kn.learn_craft_limit(name, data["maxCount"])  # 제작 상한은 거부당할 때만 알려준다
    except Exception:
        pass

    if learn_kind and snap_before is not None and r.ok:
        try:
            snap_after = item_snapshot(cd, cli)
            if snap_after is not None:
                kn.learn_recipe_from_diff(name, learn_kind, diff=kn.diff_items(snap_before, snap_after), runs=1,
                                          rewards=data.get("rewards"),
                                          # 가공은 등록 시점에 보상이 없다. 산출량은 조회가 공짜로 알려준다
                                          produced=produced_per_work(qc, name) if learn_kind == "alter" else None)
        except Exception:
            pass

    # 칸이 꽉 차서 막힌 것인가: 큐가 늘지 않았고, 지금까지 본 최대 큐보다 작지 않을 때만 (knowledge 가 한 번 더 거른다)
    level_change = None
    if alter_facility and (used_before or 0) > 0 and data.get("error") in FULL_ERRORS:
        try:
            used_after = facility_used(cli, alter_facility)
            if used_after == used_before:
                before = kn.facility_slots(alter_facility)
                kn.learn_facility_full(alter_facility, used_after)
                after = kn.facility_slots(alter_facility)
                if after.get("level") and after.get("level") != before.get("level"):
                    level_change = {"facility": alter_facility, "level": after["level"], "slots": after["slots"]}
                    if on_facility_level:
                        on_facility_level(level_change)
        except Exception:
            pass

    if sole and r.ok:
        try:
            item = kn.product_from_rewards(sole, data.get("rewards"))
            if item:
                kn.learn_product(sole, item)
        except Exception:
            pass

    return ExecResult(ok=r.ok, code=r.code, error=r.error, message=r.message, data=r.data, duration_ms=ms(),
                      wings_spent=spent["amount"] if spent else (cost["amount"] if cost and r.ok else 0),
                      cost_info=spent, ko=None if r.ok else errors.describe(command, r.error, r.message or "", r.data),
                      facility_level=level_change)
