r"""게임 데이터에서 뽑은 레시피(mabi-recipes\recipes.json)를 리모콘이 읽는 data\recipes.json 으로 바꾼다.

    .venv\Scripts\python.exe tools\build_recipes.py [원본 recipes.json]

- 원본은 게임 client.sheetdata.bin 의 CraftingRecipe·Altering 시트를 푼 것이다 (만드는 법은 mabi-recipes\README.md).
- 리모콘에 필요한 칸만 남긴다: 이름·산출물·1회 산출량·시설과 레벨·생활 스킬과 레벨·재료.
- 줄 순서는 원본 그대로 둔다. 같은 이름의 레시피가 여럿이면 게임 목록도 이 순서로 오고(2026-10-25 CLI 대조),
  시키면 언제나 첫 줄이 돈다 — 순서가 곧 "어느 갈래가 도는가"다.
- 가공 시간(sec)은 시트에서 아직 못 찾았다. 이미 만든 data\recipes.json(없으면 옛 alter-recipes.json)에서
  같은 레시피(id, 없으면 이름+재료)의 값을 이어받는다.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "recipes.json"
OLD_ALTER = ROOT / "data" / "alter-recipes.json"
SRC = ROOT.parent / "mabi-recipes" / "recipes.json"  # 저장소 옆 폴더 (인자로 다른 곳을 줄 수 있다)


def _ingredients(lst) -> dict:
    out: dict = {}
    for i in lst or []:
        out[i["name"]] = out.get(i["name"], 0) + i["amount"]
    return out


def _quest(lst) -> list:
    """퀘스트 아이템 재료 (도안 등). 채집·가공·제작 어느 쪽으로도 못 만든다"""
    return [i["name"] for i in lst or [] if i.get("type") == "questItem"]


def _old_secs() -> tuple[dict, dict]:
    """이어받을 가공 시간. (id → sec, (이름, 재료) → sec)"""
    by_id, by_key = {}, {}
    if OUT.exists():
        for r in json.loads(OUT.read_text(encoding="utf-8"))["recipes"]:
            if r.get("sec") is not None:
                by_id[r["id"]] = r["sec"]
                by_key[(r["name"], json.dumps(r["ingredients"], sort_keys=True, ensure_ascii=False))] = r["sec"]
    if OLD_ALTER.exists():
        for e in json.loads(OLD_ALTER.read_text(encoding="utf-8"))["recipes"].values():
            for v in e["variants"]:
                if v.get("sec") is not None:
                    by_key.setdefault(("*", json.dumps(v["ingredients"], sort_keys=True, ensure_ascii=False)), v["sec"])
    return by_id, by_key


def build(src: Path) -> dict:
    raw = json.loads(src.read_text(encoding="utf-8"))
    by_id, by_key = _old_secs()
    rows = []
    for r in raw["crafting"]:
        res = r["results"][0]
        row = {"id": r["id"], "via": "craft", "name": r["name"], "product": res["name"], "per": res["amount"],
               "facility": r["facilityName"], "level": r["facilityLevel"],
               "skill": (r.get("livingSkill") or {}).get("name"), "skillLevel": r.get("unlockSkillLevel"),
               "ingredients": _ingredients(r["ingredients"])}
        if _quest(r["ingredients"]):
            row["quest"] = _quest(r["ingredients"])
        rows.append(row)
    for r in raw["altering"]:
        res = r["results"][0]
        ing = _ingredients(r["ingredients"])
        key = json.dumps(ing, sort_keys=True, ensure_ascii=False)
        rows.append({"id": r["id"], "via": "alter", "name": r["name"], "product": res["name"], "per": res["amount"],
                     "facility": r["facilityName"], "level": r["unlockFacilityLevel"], "category": r.get("category"),
                     "sec": by_id.get(r["id"], by_key.get((r["name"], key), by_key.get(("*", key)))),
                     "ingredients": ing})
    return {"_설명": "마비노기 모바일 제작·가공 레시피 전체. 게임 데이터(client.sheetdata.bin)에서 뽑은 것이라 재료가 "
                   "빠짐없이 들어 있다. tools/build_recipes.py 로 만든다.",
            "_필드": {"via": "craft(제작) | alter(가공)", "name": "게임 목록·명령에 쓰는 레시피 이름",
                     "product": "만들어지는 아이템", "per": "1회 산출 개수", "facility": "시설 이름",
                     "level": "필요한 시설 레벨", "skill": "해금 생활 스킬 (제작만)", "skillLevel": "해금 스킬 레벨",
                     "sec": "가공 1회 시간(초). 모르면 null", "ingredients": "{재료: 1회분 개수}",
                     "quest": "퀘스트 아이템 재료 — 직접 구해야 한다"},
            "_순서": "같은 name 이 여럿이면 게임 목록도 이 순서이고, 시키면 첫 줄이 돈다.",
            "_출처": raw.get("source"), "_만든시각": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "recipes": rows}


def dump(d: dict) -> str:
    """레시피 한 줄에 하나 (2천 줄 남짓이라 들여쓰면 수만 줄이 된다)"""
    head = {k: v for k, v in d.items() if k != "recipes"}
    body = ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in d["recipes"])
    return json.dumps(head, ensure_ascii=False, indent=1)[:-2] + ',\n "recipes": [\n' + body + "\n ]\n}\n"


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else SRC
    d = build(src)
    text = dump(d)
    json.loads(text)  # 깨진 파일을 쓰지 않는다
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(OUT)
    n = len(d["recipes"])
    alter = [r for r in d["recipes"] if r["via"] == "alter"]
    print(f"{OUT}: 레시피 {n}개 (제작 {n - len(alter)}, 가공 {len(alter)}), "
          f"가공 시간 모름 {sum(1 for r in alter if r['sec'] is None)}개")
