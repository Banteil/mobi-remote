"""캐릭터 탭(web/daily.js 의 캐릭터 부분)이 부르는 파이썬 쪽 (mm.chars.*). Api 가 이 클래스를 섞어 쓴다.

캐릭터별 설정은 엔진이 읽는 config.toml 에 그대로 쓴다:
- [silver.by_slot.N]  field · field_runs · dungeon · floor · black_hole_in_field
- [run.skip_by_slot]  "N" = ["black_hole"]   (검은 구멍 끄기 — 사냥터 안 검은 구멍도 같이 끈다)
화면에는 '기본값' 대신 실제로 적용되는 값을 보여 주고, 저장할 때는 공통 설정과 다른 값만 덮어쓰기로 남긴다.

카드 그림은 data/portraits/<슬롯>.png. '자동 설정' 이 캐릭터 선택 화면에서 잘라 오거나 사람이 파일로 고른다.
"""
import base64
import logging
import shutil
import threading
from pathlib import Path

import tomlkit

from mabi import gamedata as gd, profile as prof
from mabi.runner import load_config
from mabi.whoami import Characters

log = logging.getLogger("mabi")

MANAGED = ("field", "field_runs", "dungeon", "floor", "black_hole_in_field")  # 이 탭이 다루는 by_slot 키 (나머지는 손대지 않는다)
FLOORS = {int(k): v for k, v in gd.labels()["floors"].items()}


class CharsApi:
    """self.paths, self.qc(QueryCache), self._emit, self._on_gui, self.win, self._doc() 가 있는 클래스에 섞는다."""

    _scan_thread: threading.Thread | None = None
    _scan_bot = None

    # ---- 경로 ----
    def _portrait(self, slot: int, scan: bool = False) -> Path:
        d = self.paths.data / "portraits"
        return (d / "scan" if scan else d) / f"{int(slot)}.png"

    @staticmethod
    def _data_url(f: Path) -> str | None:
        if not f.is_file():
            return None
        return "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode("ascii")

    # ---- 지금 캐릭터 (상단바) ----
    _name_now: dict = {"name": "", "at": 0.0}
    _name_checked = 0.0  # 마지막으로 화면을 읽어 본 때 (겹쳐 부를 때 한 번만)
    _name_crop = None    # 마지막으로 OCR 한 이름 칸 그림 — 그대로면 다시 읽지 않는다

    def chars_nameNow(self) -> dict:  # noqa: N802
        """지금 접속한 캐릭터 이름 {name, fresh}. CLI 에는 이름이 없어 메인 화면 왼쪽 위 이름을 OCR 로 읽는다.
        게임 창만 따로 찍어(다른 창에 가려 있어도 됨) 부를 때마다 본다. 찍기·화면 확인은 60ms 남짓이고 OCR 만 1초쯤
        걸리므로, 이름 칸 그림이 지난번과 같으면 OCR 을 건너뛴다 (예전엔 15초에 한 번만 읽어 바뀐 게 늦게 보였다).
        게임이 꺼졌거나 캐릭터 선택·타이틀 화면이면 ''. 일일 숙제가 도는 중이면 그 캐릭터 이름 (화면을 건드리지 않는다)."""
        import time as _t
        runner = getattr(self, "_daily_runner", None)
        bot = getattr(runner, "bot", None) if runner else None
        thread = getattr(self, "_daily_thread", None)
        if bot and thread and thread.is_alive() and bot.character:
            self._name_now = {"name": bot.character.get("name", ""), "at": _t.time()}
            return {"name": self._name_now["name"], "fresh": True}
        busy = (self._scan_thread and self._scan_thread.is_alive()) or _t.time() - self._name_checked < 2
        if not busy:
            self._name_checked = _t.time()
            from mabi.screen import grab_window
            from mabi.tasks.login import NAME_AREA, name_in_frame, snap_name
            from mabi.vision import Vision
            from mabi.window import GameWindow
            try:
                cfg = load_config(self.paths)
                w = GameWindow(cfg["game"]["window_title"])
                if not w.find():
                    self._name_now = {"name": "", "at": 0.0}  # 게임이 꺼짐
                else:
                    # 게임 창을 앞으로 가져오지 않고 그 창만 찍는다 → 리모콘을 보고 있어도 읽힌다 (예전엔 게임이 맨 앞일 때만)
                    frame = grab_window(w.hwnd)
                    v = Vision(self.paths.templates)
                    if frame is None:
                        pass
                    elif v.find(frame, cfg["ui"]["main_hud"]):
                        x, y, cw, ch_ = NAME_AREA
                        crop = frame[y:y + ch_, x:x + cw].astype("int16")
                        same = (self._name_crop is not None and self._name_now["name"]
                                and abs(crop - self._name_crop).mean() < 6)
                        if same:
                            self._name_now["at"] = _t.time()
                        else:
                            # OCR 이 한두 글자 틀려도 (받침 'ㅇ' → 'ㅁ' 등) 등록된 캐릭터 이름으로 맞춘다
                            names = [c["name"] for c in
                                     prof.characters(prof.load_profile(self.paths.profile) or {"slots": []})]
                            n = snap_name(name_in_frame(frame), names)
                            n = next((c for c in names if "".join(c.split()) == n), n)
                            if n:
                                self._name_now = {"name": n, "at": _t.time()}
                                self._name_crop = crop
                    elif any(v.find(frame, cfg["ui"][k]) for k in ("charselect_title", "title_start")):
                        # 캐릭터 선택·타이틀 화면 = 접속 중인 캐릭터 없음 (CLI 는 이때 '로딩 중' 이라고만 답한다)
                        self._name_now, self._name_crop = {"name": "", "at": 0.0}, None
            except Exception as e:  # 이름 표시는 덤이다 — 실패해도 조용히
                log.debug(f"지금 캐릭터 이름 읽기 실패: {e}")
        return {"name": self._name_now["name"], "fresh": _t.time() - self._name_now["at"] < 120}

    # ---- 목록 ----
    def chars_list(self) -> dict:
        doc = self._doc()
        s = doc["silver"]
        defaults = {"field": str(s["field"]), "field_runs": int(s["field_runs"]), "dungeon": str(s["dungeon"]),
                    "floor": int(s["floor"]), "black_hole": True}
        by = s.get("by_slot", {})
        skip = doc["run"].get("skip_by_slot", {})
        profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
        known = Characters(self.paths.data).load()["slots"]
        today = prof.DailyState(self.paths.state)
        by_tasks = doc["run"].get("tasks_by_slot", {})
        arb_slots = [int(x) for x in doc.get("arbeit", {}).get("slots", [])]
        out = []
        for c in prof.characters(profile):
            k = str(c["slot"])
            o = dict(by.get(k, {}))
            e = known.get(k) or {}
            fp, card = e.get("fp") or {}, e.get("card") or {}
            # 오늘 숙제 진행 (캐릭터 탭 카드의 '오늘 클리어' 표시). 끈 숙제는 세지 않는다
            order = [t for t in (by_tasks.get(k) or doc["run"]["order"]) if t not in skip.get(k, [])
                     and (t != "arbeit" or c["slot"] in arb_slots)]  # 아르바이트는 켠 캐릭터만
            done = sum(today.is_done(c["slot"], t) for t in order)
            out.append({
                "today": {"done": done, "total": len(order)},
                "slot": c["slot"], "name": c["name"],
                "field": str(o.get("field", defaults["field"])), "field_runs": int(o.get("field_runs", defaults["field_runs"])),
                "dungeon": str(o.get("dungeon", defaults["dungeon"])), "floor": int(o.get("floor", defaults["floor"])),
                "black_hole": "black_hole" not in list(skip.get(k, [])),
                "arbeit": c["slot"] in [int(x) for x in doc.get("arbeit", {}).get("slots", [])],
                "level": fp.get("level") or card.get("level"), "job": fp.get("job") or card.get("job"),
                "portrait": self._data_url(self._portrait(c["slot"])),
            })
        return {"chars": out, "defaults": defaults,
                "fields": [n for n, p in doc["places"].items() if int(p["index"]) == 2],
                "dungeons": [n for n, p in doc["places"].items() if int(p["index"]) < 2],
                "floors": FLOORS, "scanning": bool(self._scan_thread and self._scan_thread.is_alive())}

    # ---- 저장 ----
    def chars_save(self, chars: list) -> dict:
        """chars: [{slot, name, field, field_runs, dungeon, floor, black_hole}] — 화면에 보이는 실제 값."""
        slots = [int(c["slot"]) for c in chars]
        if len(set(slots)) != len(slots):
            return {"error": "같은 슬롯이 두 번 있습니다"}
        prof.save_profile(self.paths.profile, {"slots": sorted(slots),
                                               "names": {str(c["slot"]): (c.get("name") or "").strip() or f"슬롯 {c['slot']}"
                                                         for c in chars}})
        doc = self._doc()
        s = doc["silver"]
        base = {"field": str(s["field"]), "field_runs": int(s["field_runs"]), "dungeon": str(s["dungeon"]),
                "floor": int(s["floor"])}
        overs, skips = {}, {}
        for c in chars:
            o = {k: (int(c[k]) if k in ("field_runs", "floor") else str(c[k]))
                 for k in base if k in c and c[k] is not None and (int(c[k]) if k in ("field_runs", "floor") else str(c[k])) != base[k]}
            if c.get("black_hole") is False:
                o["black_hole_in_field"] = False
                skips[str(c["slot"])] = ["black_hole"]
            overs[str(c["slot"])] = o
        self._write_by_slot(s, overs)
        self._write_skips(doc["run"], skips)
        if "arbeit" in doc:  # 아르바이트는 켠 캐릭터 목록으로 둔다 (기본 꺼짐)
            arr = tomlkit.array()
            arr.extend(sorted(int(c["slot"]) for c in chars if c.get("arbeit")))
            doc["arbeit"]["slots"] = arr
        self.paths.config.write_text(tomlkit.dumps(doc), encoding="utf-8")
        return {"ok": True}

    @staticmethod
    def _write_by_slot(s, overs: dict) -> None:
        # 표를 지우고 새로 만들면 붙은 주석이 날아가므로 제자리에서 고친다. 이 탭이 모르는 키(difficulty, zone 등)는 둔다
        if "by_slot" not in s:
            s["by_slot"] = tomlkit.table(is_super_table=True)
        by = s["by_slot"]
        for slot in list(by):
            if slot not in overs:
                overs[slot] = {}
        for slot, o in sorted(overs.items(), key=lambda kv: int(kv[0])):
            if slot not in by:
                if not o:
                    continue
                by[slot] = tomlkit.table()
            t = by[slot]
            for k in [k for k in t if k in MANAGED and k not in o]:
                del t[k]
            for k, v in o.items():
                t[k] = v
            if not len(t):
                del by[slot]

    @staticmethod
    def _write_skips(run, skips: dict) -> None:
        if not skips:
            if "skip_by_slot" in run:
                del run["skip_by_slot"]
            return
        t = tomlkit.table()
        t.comment("캐릭터 탭에서 끈 숙제 (슬롯 → 숙제 id)")
        for slot, v in sorted(skips.items(), key=lambda kv: int(kv[0])):
            t[slot] = v
        run["skip_by_slot"] = t

    # ---- 카드 그림 ----
    def chars_pickPortrait(self, slot) -> dict:  # noqa: N802
        """사람이 그림 파일을 고른다. 파일 창은 화면 스레드에서만 열린다."""
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QFileDialog

        def pick():
            f, _ = QFileDialog.getOpenFileName(self.win, "캐릭터 그림을 고르세요", "", "그림 (*.png *.jpg *.jpeg *.bmp *.webp)")
            return f
        f = self._on_gui(pick)
        if not f:
            return {"canceled": True}
        img = QImage(f)
        if img.isNull():
            return {"error": "그림을 열지 못했습니다"}
        if img.width() > 600 or img.height() > 600:
            img = img.scaled(600, 600, aspectMode=1, mode=1)  # KeepAspectRatio, SmoothTransformation
        out = self._portrait(slot)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out), "PNG")
        return {"ok": True, "portrait": self._data_url(out)}

    def chars_clearPortrait(self, slot) -> dict:  # noqa: N802
        self._portrait(slot).unlink(missing_ok=True)
        return {"ok": True}

    # ---- 자동 설정 (게임 화면 조작 — 사람이 버튼을 누를 때만) ----
    def chars_scan(self) -> dict:
        if self._scan_thread and self._scan_thread.is_alive():
            return {"error": "이미 읽는 중입니다"}
        if getattr(self, "_daily_thread", None) and self._daily_thread.is_alive():
            return {"error": "일일 숙제가 도는 중입니다"}

        def work():
            from mabi.bot import Bot
            from mabi.tasks import charscan
            try:
                cfg = load_config(self.paths)
                bot = self._scan_bot = Bot(cfg, self.paths, force_exit=False)
                if not bot.window.find():
                    raise RuntimeError("게임이 꺼져 있습니다. 게임을 켠 뒤 다시 눌러 주세요")
                bot.window.focus()
                bot.sleep(0.5)
                self._emit("mm:chars-scan", {"stage": "캐릭터 선택 화면으로 나가는 중"})
                r = charscan.scan(bot, cfg)  # 캐릭터 선택 화면에 머문다 (다시 접속하지 않음)
                shutil.rmtree(self.paths.data / "portraits" / "scan", ignore_errors=True)
                for c in r["cards"]:
                    charscan.save_portrait(c["portrait"], self._portrait(c["slot"], scan=True))
                self._emit("mm:chars-scan", {"done": True, "total": r["total"], "selected": r["selected"],
                                             "cards": [{"slot": c["slot"], "name": c["name"], "score": c["name_score"],
                                                        "level": c["level"], "job": c["job"],
                                                        "portrait": self._data_url(self._portrait(c["slot"], scan=True))}
                                                       for c in r["cards"]]})
            except Exception as e:
                log.exception("캐릭터 자동 설정 실패")
                self._emit("mm:chars-scan", {"error": str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"})
            finally:
                try:
                    self._scan_bot.stopper.close()
                except Exception:
                    pass
                self._scan_bot = None
        self._scan_thread = threading.Thread(target=work, name="chars-scan", daemon=True)
        self._scan_thread.start()
        return {"ok": True}

    def chars_scanStop(self) -> dict:  # noqa: N802
        if self._scan_bot:
            self._scan_bot.stopper.request()
        return {"ok": True}

    def chars_applyScan(self, items: list) -> dict:  # noqa: N802
        """확인 창에서 고른 것만 반영한다. items: [{slot, name, portrait: bool, level, job}]."""
        profile = prof.load_profile(self.paths.profile) or {"slots": [], "names": {}}
        slots, names = set(int(s) for s in profile.get("slots", [])), dict(profile.get("names", {}))
        for it in items:
            slot = int(it["slot"])
            slots.add(slot)
            if (it.get("name") or "").strip():
                names[str(slot)] = it["name"].strip()
            elif str(slot) not in names:
                names[str(slot)] = f"슬롯 {slot}"
            if it.get("level") or it.get("job"):
                Characters(self.paths.data).set_card(slot, it.get("level"), it.get("job"))
            src = self._portrait(slot, scan=True)
            if it.get("portrait") and src.is_file():
                dst = self._portrait(slot)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
        prof.save_profile(self.paths.profile, {"slots": sorted(slots), "names": names})
        return {"ok": True}
