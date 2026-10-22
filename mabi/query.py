"""조회 결과를 화면에 쓰기 좋게 정리한다 (리모콘 src/query.js 의 조회 부분).

제작·가공 목록(학습 지식·레시피 장부가 얽힌 부분)은 그 화면을 옮길 때 따로 둔다.
모든 함수는 실패하면 {"error", "message"} 를 돌려준다.
"""
from . import richtext
from .cache import QueryCache

LOCATION_LABEL = {"inventory": "가방", "account_storage": "계정창고", "character_storage": "캐릭창고"}
LOCATION_KEY = {"inventory": "bag", "character_storage": "char", "account_storage": "acc"}


def matches(hay, needle) -> bool:
    """공백·대소문자 무시 부분 일치. 태그는 먼저 벗긴다."""
    if not needle:
        return True
    h = (richtext.strip(str(hay or "")) or "").lower().replace(" ", "")
    return str(needle).lower().replace(" ", "") in h


def name_fields(display: str) -> dict:
    """화면용 이름과 원문. 게임에 보낼 때는 반드시 name_raw."""
    return {"name": richtext.strip(display), "name_raw": display}


def _fail(res: dict) -> dict:
    return {"error": res.get("error"), "message": res.get("message")}


def _meta(res: dict) -> dict:
    return {"cached": res.get("cached", False), "stale": bool(res.get("stale"))}


class Query:
    def __init__(self, cache: QueryCache):
        self.cache = cache

    def _get(self, cmd, **kw):
        return self.cache.get(cmd, **kw)

    # ---------------- 캐릭터
    def me(self, **kw) -> dict:
        """get_my_info 에는 캐릭터명이 없다. Title=착용 타이틀, RealmName=서버. 이름을 표시하려 하지 말 것."""
        res = self._get("get_my_info", **kw)
        if not res.get("data"):
            return _fail(res)
        d = res["data"]
        v = d.get("Vitals") or {}
        wc, wm = v.get("InventoryWeightCurrent") or 0, v.get("InventoryWeightMax") or 0
        return {"title": d.get("Title"), "realm": d.get("RealmName"), "level": d.get("Level"),
                "job": d.get("EnabledCombatJobDisplayName"),
                "combat": (d.get("CombatScore") or {}).get("Value"), "living": (d.get("LivingScore") or {}).get("Value"),
                "hp": (v.get("HealthCurrent"), v.get("HealthMax")), "satiety": (v.get("SatietyValue"), v.get("SatietyMax")),
                "weight": (round(wc), round(wm)), "weight_pct": round(wc / wm * 100) if wm else 0,
                "buffs": v.get("ActiveBuffCount"), **_meta(res)}

    def currencies(self, search: str = "", non_zero: bool = False, **kw) -> dict:
        res = self._get("get_currencies", **kw)
        if not res.get("data"):
            return _fail(res)
        rows = [r for r in res["data"] if matches(r.get("DisplayName"), search) and (not non_zero or r.get("Amount"))]
        return {"items": [{"name": r["DisplayName"], "amount": r["Amount"]} for r in rows], **_meta(res)}

    def wings(self, **kw) -> int | None:
        r = self.currencies(**kw)
        if "error" in r:
            return None
        return next((i["amount"] for i in r["items"] if i["name"] == "정령의 날개"), 0)

    def activity(self, **kw) -> dict:
        """항상 실시간. IsReviving 은 살아 있어도 true 로 남는 경우가 있어 판단에 쓰지 않는다."""
        kw.setdefault("max_age", 0)
        res = self._get("get_activity", **kw)
        if not res.get("data"):
            return _fail(res)
        d = res["data"]
        perf, mode = d.get("Performance") or {}, d.get("Mode") or {}
        return {
            "auto_playing": bool(d.get("IsAutoPlaying")), "auto_traveling": bool(d.get("IsAutoTraveling")),
            "in_combat": bool(d.get("IsInCombat")), "dead": bool(d.get("IsDead")), "reviving": bool(d.get("IsReviving")),
            "dialogue": bool(d.get("IsDialoguePlaying") or d.get("IsWaitingForSelection")),
            "performing": bool(perf.get("IsPlaying")),
            "perf": {"playing": bool(perf.get("IsPlaying")), "instrument": perf.get("InstrumentName") or "",
                     "title": perf.get("MusicTitle") or "", "loop": bool(perf.get("IsLoop")),
                     "total": float(perf.get("TotalDurationSeconds") or 0), "elapsed": float(perf.get("ElapsedSeconds") or 0),
                     "remaining": float(perf.get("RemainingSeconds") or 0), "channels": int(perf.get("ChannelCount") or 0)},
            "sitting": mode.get("SitState") == "Sitting", "main_button": mode.get("MainButtonState"),
            "riding": mode.get("MountPartState") == "Mounted",
            "dungeon": (d.get("Dungeon") or {}).get("State"),
            "busy": bool(d.get("IsAutoPlaying") or d.get("IsAutoTraveling") or d.get("IsInCombat")
                         or perf.get("IsPlaying") or d.get("IsWaitingForSelection")),
            **_meta(res)}

    def environment(self, **kw) -> dict:
        res = self._get("get_current_environment", **kw)
        if not res.get("data"):
            return _fail(res)
        d = res["data"]
        h, pos = d.get("Housing") or {}, d.get("WorldPosition")
        return {"channel": d.get("ChannelDisplayName"), "space": d.get("GameSpaceDisplayName"),
                "pos": (round(pos["X"]), round(pos["Y"])) if pos else None, "weather": d.get("Weather"),
                "erinn_time": d.get("ErinnNow"), "housing": bool(h.get("IsInHousing")), **_meta(res)}

    def inventory(self, **kw) -> dict:
        res = self._get("get_inventory", **kw)
        if not res.get("data"):
            return _fail(res)
        d = res["data"]
        cur, mx = d.get("CurrentInventoryWeight") or 0, d.get("MaxInventoryWeight") or 0
        return {"current": round(cur), "max": round(mx), "pct": round(cur / mx * 100) if mx else 0, **_meta(res)}

    # ---------------- 소지품
    def items(self, search: str = "", category: str = "", **kw) -> dict:
        """같은 이름이 보관처별로 쪼개져 오므로 합산한다. 무게는 가방만 차지하므로 보관처는 칸을 나눠 둔다."""
        res = self._get("get_items", **kw)
        if res.get("data") is None:
            return _fail(res)
        allrows = res["data"] if isinstance(res["data"], list) else []
        by: dict[str, dict] = {}
        for r in allrows:
            if not matches(r.get("DisplayName"), search) or (category and r.get("CategoryDisplayName") != category):
                continue
            e = by.setdefault(r["DisplayName"], {**name_fields(r["DisplayName"]), "category": r.get("CategoryDisplayName"),
                                                 "total": 0, "at": {"bag": 0, "char": 0, "acc": 0}, "locked": False})
            e["total"] += r.get("Count", 0)
            k = LOCATION_KEY.get(r.get("Location"))
            if k:
                e["at"][k] += r.get("Count", 0)
            e["locked"] = e["locked"] or bool(r.get("IsLocked"))
        cats = sorted({r.get("CategoryDisplayName") for r in allrows if r.get("CategoryDisplayName")})
        return {"items": sorted(by.values(), key=lambda e: -e["total"]), "categories": cats, **_meta(res)}

    def owned_totals(self, **kw) -> dict[str, int]:
        """이름 → 가방+보관함 총량. MissingIngredients 의 Owned 는 가방만 세므로 이걸로 다시 센다."""
        res = self._get("get_items", **kw)
        tot: dict[str, int] = {}
        for it in res.get("data") or []:
            for key in {it["DisplayName"], richtext.strip(it["DisplayName"])}:
                tot[key] = tot.get(key, 0) + it.get("Count", 0)
        return tot

    # ---------------- 미션·퀘스트
    @staticmethod
    def mission_state(m: dict) -> str:
        """open(진행 중) / unclaimed(다 했는데 보상 안 받음) / done(받음)"""
        if not m.get("IsCompleted"):
            return "open"
        return "done" if m.get("IsRewardReceived") else "unclaimed"

    @staticmethod
    def drop_phantoms(rows: list) -> list:
        """게임에 없는 미션 제거. 제목이 같은 묶음에 수령 완료 건이 있으면, 같은 묶음의 '완료·미수령'은
        지난 주기 잔재로 보고 버린다 (실측: 주간 미션이 1회 수령함 + 2회 완료·미수령 두 건으로 옴).
        진행 중인 건은 진짜 다음 단계일 수 있어 남긴다."""
        claimed = {m.get("Title") for m in rows if m.get("IsCompleted") and m.get("IsRewardReceived")}
        return [m for m in rows if not (m.get("Title") in claimed and m.get("IsCompleted") and not m.get("IsRewardReceived"))]

    def _missions(self, cmd: str, only_open: bool, **kw) -> dict:
        res = self._get(cmd, **kw)
        if res.get("data") is None:
            return _fail(res)
        rows = self.drop_phantoms(res["data"] or [])
        states = [self.mission_state(m) for m in rows]
        items = [{"title": m.get("Title"), "desc": m.get("Description"), "cur": m.get("CurrentCount", 0),
                  "goal": m.get("GoalCount", 0), "state": s} for m, s in zip(rows, states)
                 if not only_open or s != "done"]
        return {"items": items, "total": len(rows), "open": states.count("open"),
                "unclaimed": states.count("unclaimed"), **_meta(res)}

    def daily(self, only_open: bool = False, **kw) -> dict:
        return self._missions("get_daily_missions", only_open, **kw)

    def weekly(self, only_open: bool = False, **kw) -> dict:
        return self._missions("get_weekly_missions", only_open, **kw)

    def quests(self, **kw) -> dict:
        """퀘스트 트래커의 '지금 보는 탭' 것만 온다 — 빈 목록도 정상 (같은 자리에서 0건과 8건이 번갈아 나온다)."""
        res = self._get("get_quests", **kw)
        if res.get("data") is None:
            return _fail(res)
        out = []
        for q in res["data"] or []:
            objs = []
            for o in q.get("Objectives") or []:
                desc = richtext.strip(o.get("Description") or "")
                prog = f"{o.get('Count')}/{o.get('Goal')}" if (o.get("Goal") or 0) > 0 else None
                objs.append({"desc": desc, "desc_raw": o.get("Description") or "", "done": bool(o.get("IsCompleted")),
                             # 설명 끝에 진행도가 이미 붙어 오는 목표가 있다 ("심층 던전 클리어 2/3")
                             "progress": prog if prog and prog not in desc else None})
            out.append({"title": richtext.strip(q.get("QuestTitle") or ""), "title_raw": q.get("QuestTitle") or "",
                        "source": q.get("SourceDisplayName") or q.get("Source"), "objectives": objs})
        return {"items": out, **_meta(res)}

    # ---------------- 주변
    def near_pcs(self, **kw) -> dict:
        """이름 칸은 RealmName(서버). 캐릭터명은 어디서도 안 준다."""
        kw.setdefault("max_age", 0)
        res = self._get("get_near_pcs", **kw)
        rows = res.get("data") or []
        return {"items": sorted(({"name": p.get("RealmName"), "title": p.get("Title"),
                                  "distance": round(p.get("Distance") or 0, 1), "level": p.get("Level"),
                                  "job": p.get("EnabledCombatJobDisplayName"), "combat": p.get("CombatScore"),
                                  "friend": bool(p.get("IsFriend")), "party": bool(p.get("IsInParty")),
                                  "guild": bool(p.get("IsSameGuild")), "in_combat": bool(p.get("IsInCombat")),
                                  "playing": bool((p.get("Performance") or {}).get("IsPlaying"))}
                                 for p in rows), key=lambda p: p["distance"])}

    def near_npcs(self, **kw) -> dict:
        kw.setdefault("max_age", 0)
        res = self._get("get_near_npcs", **kw)
        d = res.get("data")
        return {"items": d if isinstance(d, list) else (d or {}).get("npcs", [])}

    # ---------------- 연주·소셜·채집
    def instruments(self, **kw) -> dict:
        res = self._get("get_instruments", **kw)
        if res.get("data") is None:
            return _fail(res)
        return {"items": [{"name": i["Name"], "equipped": bool(i.get("IsEquipped")),
                           # int 최대값은 사실상 무한(소모 없음)
                           "durability": None if (i.get("Durability") or 0) >= 2147483647 else i.get("Durability")}
                          for i in res["data"] or []], **_meta(res)}

    def music_scores(self, search: str = "", **kw) -> dict:
        """2026-10-15 판부터 게임이 준 악보만 온다 (직접 만들거나 복사한 악보는 빠짐)."""
        res = self._get("get_music_scores", **kw)
        if res.get("data") is None:
            return _fail(res)
        rows = [s for s in res["data"] or [] if matches(s.get("DisplayTitle"), search)]
        return {"items": [{"title": s["DisplayTitle"], "label": s["DisplayTitle"].removeprefix("악보: "),
                           "location": s.get("Location"), "copyable": bool(s.get("IsCopyingAllowed")),
                           "locked": bool(s.get("IsLocked"))} for s in rows], **_meta(res)}

    def social(self, search: str = "", **kw) -> dict:
        """표정은 EmojiText 로 보낸다("/미소"처럼 보내면 unsupported_command). 행동은 ChatCommands[0].
        일어서기는 목록에 없지만 같은 자리에 얹는다 — 보내는 방식만 전용 명령(stand_up)."""
        res = self._get("get_social_actions", **kw)
        if res.get("data") is None:
            return _fail(res)
        d = res["data"]
        beh = [{"name": b["DisplayName"], "send": (b.get("ChatCommands") or [None])[0], "command": "write_chat"}
               for b in d.get("Behaviours") or [] if matches(b.get("DisplayName"), search)]
        if matches("일어서기", search):
            beh.append({"name": "일어서기", "send": None, "command": "stand_up"})
        fac = [{"name": f["DisplayName"], "send": f.get("EmojiText"), "command": "write_chat"}
               for f in d.get("Facials") or [] if matches(f.get("DisplayName"), search)]
        return {"behaviours": beh, "facials": fac, **_meta(res)}

    def gather(self, search: str = "", only_ok: bool = False, **kw) -> dict:
        res = self._get("get_gatherable_items", **kw)
        if res.get("data") is None:
            return _fail(res)
        allrows = (res["data"] or {}).get("items", [])
        rows = [r for r in allrows if matches(r.get("DisplayName"), search) and (not only_ok or r.get("ToolOk"))]
        return {"items": [{**name_fields(r["DisplayName"]), "tool": bool(r.get("ToolOk"))} for r in rows],
                "total": len(allrows), **_meta(res)}
