"""게임 화면 설정을 이 프로그램이 기대하는 값으로 맞춘다 (템플릿·좌표가 모두 이 값 기준).

  테두리 없는 전체화면, 해상도 1920x1080, 인터페이스 스타일 PC, 스케일 80%

- check(): 바로 알 수 있는 것만 본다 (게임 창 크기, 화면 배율). 메인 화면이면 HUD 템플릿도 맞는지.
- 게임이 켜져 있으면 fix_ingame(): ESC → 환경 설정 → 그래픽 탭에서 바꾼다. 배율이 틀어져 있으면 버튼 위치·크기가
  바뀌어 템플릿이 안 맞으므로 버튼은 글자(OCR)로 찾는다. 스케일 화살표('<' '>')도 글자로 잡힌다 (2026-10-22 확인).
- 실패하거나 게임이 꺼져 있으면 fix_offline(): 게임이 꺼진 상태에서 설정 파일과 레지스트리를 고친다.
  해상도는 LocalLow 설정 파일의 StandaloneResolutionScale (1 = 1920x1080, 1280x720 은 그보다 작은 값),
  화면 모드는 레지스트리(Unity Screenmanager), 인터페이스는 설정 파일 InterfaceStyleType(1 = PC)·InterfaceStyleScale.
  설정 파일은 Base(전체) + Changed(바뀐 것을 '+형식 : 키 : 값' 으로 덧붙이는 기록) 두 개라 둘 다 맞춘다.
  게임은 넥슨 런처가 로그인 정보를 넣어 켜므로 다시 켜는 건 사람이 한다.
"""
import ctypes
import json
import os
import re
import shutil
import time
import uuid
import winreg
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import gamedata as gd, ocr
from ..screen import BASE_H, BASE_W, REG_KEYS, exclusive_fullscreen, is_16_9, screen_mode
from ..bot import Bot, MissingTemplate, StepTimeout

WIDTH, HEIGHT = 1920, 1080
SCALE = 80
SCALE_MIN, SCALE_MAX = 70, 100  # 게임의 인터페이스 스케일 범위 (PC 만. 모바일은 스케일이 없다)
PREFS_DIRS = ("마비노기 모바일", "Mabinogi Mobile")
FOLDERID_LOCAL_APPDATA_LOW = "A520A1A4-1780-4FF6-BD18-167343C5AF16"
# 설정 파일 키 → (형식 번호, 값). 형식 번호는 Changed 기록의 '+N' (2 = 정수, 3 = 실수)
PREFS = {
    "GraphicsUserSetting.StandaloneResolutionScale": (3, "1"),
    "GraphicsUserSetting.InterfaceStyleType": (2, "1"),
    "GraphicsUserSetting.InterfaceStyleScale": (2, str(SCALE)),
}
# 레지스트리 값 이름 앞부분 (뒤에 '_h해시' 가 붙는다) → 값
REG = {
    "Screenmanager Resolution Width_h": WIDTH,
    "Screenmanager Resolution Height_h": HEIGHT,
    "Screenmanager Fullscreen mode_h": 1,  # 1 = 테두리 없는 전체화면 (FullScreenWindow)
}


class DisplayFixFailed(RuntimeError):
    pass


MIN_W, MIN_H = 1280, 720  # 이보다 작으면 늘려 써도 글자·아이콘이 뭉개져 인식이 흔들린다


def size_problem(w: int, h: int) -> str:
    """게임 화면(창 안쪽) 크기 문제 한 줄, 괜찮으면 ''. 16:9 이고 1280x720 이상이면 된다 —
    판단은 1920x1080 기준으로 바꿔서 하므로 (Screen) 2560x1440·3840x2160·1600x900 등도 그대로 쓴다."""
    if not is_16_9(w, h):
        return f"게임 화면 비율이 16:9 가 아님 ({w}x{h}) — 1920x1080 등 16:9 해상도로"
    if w < MIN_W:
        return f"게임 화면이 너무 작음 ({w}x{h}) — {MIN_W}x{MIN_H} 이상으로"
    return ""


# ---------------------------------------------------------------- 확인
def check(bot: Bot | None = None, window=None, interface: bool = True) -> dict:
    """{ok, problems: [..], client: (w, h), dpi}. 게임이 없으면 running False.
    interface=False: 인터페이스 스타일·스케일은 따지지 않는다 — 일일 숙제는 시작할 때 PC·80% 로 바꾸고 끝나면 되돌린다
    (prepare_interface / restore_interface)."""
    win = window or (bot.window if bot else None)
    if win is None or not game_running(win):
        return {"ok": False, "running": False, "problems": ["게임이 꺼져 있음"]}
    if ctypes.windll.user32.IsIconic(win.hwnd):
        # 내려가 있으면 크기를 알 수 없고, '전체화면' 은 내려가 있는 동안 레지스트리가 창모드로 바뀐다 (2026-10-23) → 앞으로.
        # 곧 숙제를 시작할 참이라 어차피 앞으로 온다
        win.focus()
        time.sleep(2.5)
    try:
        r = win.client_rect()
    except RuntimeError:
        return {"ok": False, "running": False, "problems": ["게임이 꺼져 있음"]}
    dpi = ctypes.windll.user32.GetDpiForWindow(win.hwnd) or 96
    problems = [p for p in [size_problem(r.width, r.height)] if p]
    # '전체화면'(독점) 은 16:9·크기가 맞아도 안 된다 — 화면을 찍으면 멈춘 옛 화면만 나온다 (screen.exclusive_fullscreen).
    # 2026-10-23 1280x720 전체화면에서 확인은 통과하고 맞추기는 헛돌았다 → 짚고, 맞추기는 Alt+Enter 로 빼낸 뒤 맞춘다
    if exclusive_fullscreen():
        problems.insert(0, "화면 모드가 '전체화면' — '테두리 없는 전체화면' 으로")
    # Windows 화면 배율(DPI)은 더 따지지 않는다 — 배율이 달라도 게임 창 안쪽은 비율대로 커질 뿐이고, 찍은 화면을
    # 1920x1080 기준으로 바꿔 쓰므로 (Screen.grab) 해상도가 다른 것과 같다 (2026-10-23)
    # 렌더링 해상도는 게임 설정 파일로 본다. 인터페이스 스타일·스케일은 파일을 보지 않는다 — 게임 중에 바꿔도 파일에
    # 바로 쓰이지 않아 (2026-10-23 확인) 지금 값과 다를 수 있다 → 메인 화면 HUD 모양으로 본다
    prefs = read_prefs()
    for key, (_, want) in PREFS.items():
        if "InterfaceStyle" in key:
            continue
        have = prefs.get(key)
        if have is not None and float(have) != float(want):
            problems.append(f"{PREFS_LABEL[key]}: {_shown(key, have)} ({_shown(key, want)} 이어야 함)")
    if interface and not problems and (bot is None or not bot.in_game()):
        problems.append("인터페이스 스타일·스케일 확인 못 함 — 게임에 접속한 뒤 다시 확인하거나 '맞추기'")
    if interface and bot is not None and not problems:
        # 메인 화면인데 HUD 템플릿이 안 맞으면 인터페이스 배율·스타일이 다른 것
        # bot.frame() 은 중단 키를 검사한다 — '직접 맞춘 뒤 F12' 로 다시 확인할 때 그 F12 를 중단으로 받으므로 바로 찍는다.
        # 화면을 그대로 찍으므로 게임이 다른 창(브라우저 등)에 가려 있으면 그 창을 보고 '다름' 으로 판단했다 (2026-10-22)
        # → 게임을 앞으로 가져온 뒤 찍는다. 곧 숙제를 시작할 참이라 어차피 앞으로 온다
        if ctypes.windll.user32.GetForegroundWindow() != win.hwnd:
            win.focus()
            time.sleep(0.8)
        frame = bot.screen.grab()
        if not bot.vision.find(frame, bot.ui["main_hud"]):
            problems.append(f"인터페이스가 PC · {SCALE}% 가 아님 (메인 화면 표시가 기준과 다름) — '맞추기'")
    return {"ok": not problems, "running": True, "problems": problems, "client": (r.width, r.height), "dpi": dpi}


PREFS_LABEL = {
    "GraphicsUserSetting.StandaloneResolutionScale": "렌더링 해상도",
    "GraphicsUserSetting.InterfaceStyleType": "인터페이스 스타일",
    "GraphicsUserSetting.InterfaceStyleScale": "인터페이스 스케일",
}


def _shown(key: str, v: str) -> str:
    f = float(v)
    if key.endswith("StandaloneResolutionScale"):
        return f"{round(f * 100)}%"
    if key.endswith("InterfaceStyleType"):
        return {1: "PC"}.get(int(f), f"모바일({int(f)})")
    return f"{int(f)}%"


def read_prefs() -> dict[str, str]:
    """게임 설정 파일의 지금 값 {키: 값}. Base 위에 Changed 기록을 차례로 덮는다 (마지막 줄이 이긴다). 파일이 없으면 {}."""
    out: dict[str, str] = {}
    best = 0.0
    for name in PREFS_DIRS:
        d = _prefs_root() / name
        base, changed = d / "BaseMMPlayerPrefs.txt", d / "ChangedMMPlayerPrefs.txt"
        if not base.is_file():
            continue
        vals: dict[str, str] = {}
        try:
            for line in base.read_text(encoding="utf-8", errors="replace").splitlines():
                k, sep, v = line.partition(" : ")
                if sep and k.strip() in PREFS:
                    vals[k.strip()] = v.strip()
            if changed.is_file():
                for line in changed.read_text(encoding="utf-8", errors="replace").splitlines():
                    parts = line.split(" : ", 2)  # '+2 : 키 : 값'
                    if len(parts) == 3 and parts[1].strip() in PREFS:
                        vals[parts[1].strip()] = parts[2].strip()
        except OSError:
            continue
        # 폴더가 둘이면 (예전 영문 폴더가 남아 있다) 최근에 쓴 쪽
        m = max(f.stat().st_mtime for f in (base, changed) if f.is_file())
        if vals and m > best:
            out, best = vals, m
    return out


def game_running(window) -> bool:
    return bool(window.hwnd and ctypes.windll.user32.IsWindow(window.hwnd)) or window.find()


# ---------------------------------------------------------------- 게임 안에서 바꾸기
def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _texts(bot: Bot, region=None) -> list[tuple[str, int, int]]:
    return ocr.find_texts(bot.frame(), region)


def _find(items, want: str, exact: bool = False, below: int = -1, above: int = 99999):
    for t, x, y in items:
        n = _norm(t)
        if (n == want if exact else want in n) and below < y < above:
            return t, x, y
    return None


def _click_text(bot: Bot, want: str, region=None, exact: bool = False, what: str = "", wait: float = 1.5):
    hit = _find(_texts(bot, region), want, exact)
    if not hit:
        raise DisplayFixFailed(f"'{what or want}' 를 화면에서 찾지 못함 → {bot.snapshot('display').name}")
    bot.click((hit[1], hit[2]))
    bot.sleep(wait, wait + 0.4)
    return hit


def _scale_row(bot: Bot):
    """(스케일 값, '<' 위치, '>' 위치). 화살표를 못 읽으면 값 글자에서 배율에 비례한 거리로 계산한다
    (100% 일 때 값 가운데에서 약 171px)."""
    items = _texts(bot)
    label = _find(items, gd.text("display_scale"))
    if not label:
        return None, None, None
    row = [(t, x, y) for t, x, y in items if abs(y - label[2]) < 30 and x > label[1]]
    val = next(((t, x, y) for t, x, y in row if re.fullmatch(r"\d{2,3}%", _norm(t))), None)
    if not val:
        return None, None, None
    pct = int(_norm(val[0])[:-1])
    left = next(((x, y) for t, x, y in row if _norm(t) == "<"), None) or (val[1] - int(1.71 * pct), val[2])
    right = next(((x, y) for t, x, y in row if _norm(t) == ">"), None) or (val[1] + int(1.71 * pct), val[2])
    return pct, left, right


def _open_graphics(bot: Bot) -> None:
    """ESC → 환경 설정 → 그래픽 탭. 배율이 달라도 찾도록 버튼은 글자로 찾는다.
    to_main 은 쓰지 않는다 — 인터페이스가 다르면 메인 HUD 템플릿이 안 맞아 ESC 를 거듭 눌러 메뉴를 열었다 닫는다 (2026-10-23)."""
    W, H = BASE_W, BASE_H
    menu, top = (W // 2, 0, W // 2, H), (0, 0, W, H // 4)
    # 탭이 보일 때까지: 메뉴의 '환경 설정' 이 보이면 누르고, 아니면 ESC (다른 창이 열려 있으면 그 창부터 닫힌다).
    # 설정 창이 이미 열려 있으면 그대로 쓴다. 누른 뒤 창이 늦게 뜨기도 해서 (2026-10-23 창모드) 한 번에 끝내지 않는다
    for _ in range(6):
        if _find(_texts(bot, top), gd.text("display_graphics_tab"), exact=True):
            break
        hit = _find(_texts(bot, menu), gd.text("display_settings"))
        if hit:
            bot.click((hit[1], hit[2]))
            bot.sleep(2.0, 2.4)
        else:
            bot.key("esc")
            bot.sleep(1.5, 1.8)
    _click_text(bot, gd.text("display_graphics_tab"), region=top, exact=True, what="그래픽 탭")


def _close_settings(bot: Bot) -> None:
    bot.key("esc")  # 환경 설정 닫기
    bot.sleep(1.5, 1.8)
    try:
        bot.to_main(tries=3)
    except StepTimeout:
        pass


STYLES = {"auto": ("display_interface_auto", "자동"), "pc": ("display_interface_pc", "PC"),
          "mobile": ("display_interface_mobile", "모바일")}


def _style_now(bot: Bot) -> tuple[str | None, dict[str, tuple[int, int]]]:
    """(골라진 스타일 'auto'/'pc'/'mobile', 버튼 위치들). 골라진 버튼만 흰 바탕이다 — 가운데 둘레 밝기의 중간값
    (2026-10-23 실측: 골라진 것 117~214, 나머지 76 이하 — 글자 줄 평균. 중간값은 바탕색을 더 그대로 본다)."""
    frame = bot.frame()
    items = ocr.find_texts(frame, (BASE_W // 2, 0, BASE_W // 2, BASE_H))
    pos = {}
    for k, (key, _) in STYLES.items():
        hit = _find(items, gd.text(key), exact=True)
        if hit:
            pos[k] = (hit[1], hit[2])
    lum = {k: float(np.median(frame[max(0, y - 14):y + 14, max(0, x - 40):x + 40])) for k, (x, y) in pos.items()}
    best = max(lum, key=lum.get) if lum else None
    return (best if best and lum[best] > 140 else None), pos


def _set_interface(bot: Bot, style: str, scale: int | None, done: list[str]) -> tuple[str | None, int | None]:
    """(그래픽 탭이 열린 상태에서) 인터페이스 스타일과 스케일. 스케일 조절 줄은 PC 일 때만 있고 (자동·모바일은 스케일이
    없다) 70~100% 를 화살표 한 번에 10%씩 움직인다. scale 은 PC 일 때만 쓴다 — PC 스케일을 맞춰 두고 다른 스타일로 갔다
    돌아오면 80% 로 돌아가 있었다 (2026-10-23). 바꾸기 전 (스타일, 스케일 %)을 돌려준다 — PC 가 아니었으면 스케일 None.
    인터페이스를 바꾸면 설정 창 배치도 곧바로 바뀌므로 위치는 매번 다시 읽는다."""
    W, H = BASE_W, BASE_H
    bot.scroll(int(W * 0.73), int(H * 0.65), -10)  # 스타일 버튼과 스케일 조절 줄이 함께 보이게 오른쪽 칸을 내린다
    bot.sleep(1.2, 1.5)

    def pick(want: str) -> None:
        pos = _style_now(bot)[1]
        if want not in pos:
            raise DisplayFixFailed(f"인터페이스 '{STYLES[want][1]}' 버튼을 찾지 못함 → {bot.snapshot('display').name}")
        bot.click(pos[want])
        bot.sleep(1.5, 1.8)
        done.append(f"인터페이스 {STYLES[want][1]}")

    before = _style_now(bot)[0]
    if before is None:
        raise DisplayFixFailed(f"지금 인터페이스 스타일을 알아보지 못함 → {bot.snapshot('display').name}")
    before_scale = _scale_row(bot)[0] if before == "pc" else None
    if before != style:
        pick(style)
    if style == "pc" and scale is not None:
        scale = min(max(scale, SCALE_MIN), SCALE_MAX)
        for _ in range(6):
            pct, left, right = _scale_row(bot)
            if pct is None:
                raise DisplayFixFailed(f"스케일 조절 값을 읽지 못함 → {bot.snapshot('display').name}")
            if pct == scale:
                break
            bot.click(left if pct > scale else right)  # 누를 때마다 배치가 바뀌므로 매번 다시 읽는다
            bot.sleep(1.0, 1.3)
            done.append(f"스케일 {pct}% → {pct - 10 if pct > scale else pct + 10}%")
        else:
            raise DisplayFixFailed(f"스케일을 {scale}% 로 맞추지 못함 → {bot.snapshot('display').name}")
    if _style_now(bot)[0] != style:
        raise DisplayFixFailed(f"인터페이스를 {STYLES[style][1]} 로 바꾸지 못함 → {bot.snapshot('display').name}")
    return before, before_scale


def set_interface(bot: Bot, style: str, scale: int | None) -> tuple[list[str], tuple[str | None, int | None]]:
    """게임 안 환경 설정에서 인터페이스 스타일·스케일만 바꾼다. (바꾼 것 목록, 바꾸기 전 (스타일, PC 스케일)).
    실패하면 DisplayFixFailed."""
    done: list[str] = []
    _open_graphics(bot)
    try:
        before = _set_interface(bot, style, scale, done)
    finally:
        _close_settings(bot)
    return done, before


# ---- 숙제 동안만 PC·80% (사용자가 평소 쓰는 설정은 기억했다가 끝나면 되돌린다) ----
# 설정 파일은 보지 않는다 — 게임 중에 바꿔도 파일에 바로 쓰이지 않아 (2026-10-23 확인) 지금 값과 다를 수 있다. 늘 화면으로 본다
RESTORE_KEY = "_interface_restore"  # 오늘 기록(DailyState)에 남기는 원래 설정 {style, scale, at}


def _shown_style(style: str | None, scale: int | None) -> str:
    return f"PC · {scale}%" if style == "pc" else STYLES.get(style, ("", "?"))[1]


def busy(bot: Bot) -> str:
    """콘텐츠 안이거나 NPC 대화 중이면 그 이유. 환경 설정은 ESC 로 메뉴를 여는데, 이때 ESC 는 보상 화면 '나가기'·
    매칭 취소·대화 닫기가 된다 → 인터페이스 맞추기는 미룬다 (2026-10-27 감사: 다시 켠 뒤 첫 카드가 콘텐츠 안에서 ESC 부터).
    패킷 → CLI 순서로 보고, 모르면 ''."""
    from .content import game_space
    p, st = bot.packets, bot.packets.state
    if p.ok:
        if st.dungeon_state in ("Entering", "InProgress", "Cleared"):
            return "던전 안"
        if st.field_state in ("InProgress", "WaitingForChannelTransfer"):
            return "사냥터 안"
        if st.channel_type == "InstanceAbyssDungeon" or st.abyss_result or st.abyss_matching in (1, 2, 3):
            return "어비스 안·매칭 중"
        if st.channel_type in ("InstanceRaid", "InstanceRaidLobby"):
            return "레이드 안·출항선"
        if st.in_dialogue:
            return "NPC 대화 중"
    act = bot.activity() or {}
    if (act.get("Dungeon") or {}).get("State") in ("Entering", "InProgress", "Cleared"):
        return "던전 안"
    if (act.get("Battlefield") or {}).get("IsInBattleField"):
        return "사냥터 안"
    if act.get("IsAbyssResultSequencePlaying"):
        return "어비스 결과"
    if (act.get("dialogue") or {}).get("IsDialoguePlaying"):
        return "NPC 대화 중"
    if bot.cfg["black_hole"]["space_keyword"] in game_space(bot):
        return "검은 구멍 안"
    return ""


def prepare_interface(bot: Bot, state) -> str:
    """숙제 시작: 환경 설정에서 지금 설정을 보고 기억한 뒤 PC·80% 로 맞춘다. 이미 기억해 둔 게 있으면 (끊겼다 이어 하는 중)
    덮어쓰지 않는다 — 그때는 이미 80% 로 바꿔 둔 뒤라 원래 값이 아니다."""
    done, (style, scale) = set_interface(bot, "pc", SCALE)
    if state.data.get(RESTORE_KEY) is None:
        state.data[RESTORE_KEY] = {"style": style, "scale": scale, "at": datetime.now().strftime("%H:%M:%S")}
        state._save()
    if not done:
        return f"인터페이스 PC · {SCALE}% (그대로)"
    return f"인터페이스 {_shown_style(style, scale)} → PC · {SCALE}% ({', '.join(done)})"


class InterfaceFit:
    """작업 하나 동안 인터페이스를 PC·80% 로 처음 한 번 맞춘다 — 일일 숙제(runner)·어비스·레이드 반복(Repeat) 공통.
    환경 설정은 게임 안에서만 열리고, 콘텐츠 안·대화 중엔 ESC 가 나가기·매칭 취소가 돼 미룬다 (busy).
    맞췄으면 on_fit() — 작업 큐가 다음 카드에선 다시 맞추지 않게 (예전엔 맞췄는지와 상관없이 표시해 영영 안 맞췄다).
    되돌리기는 restore_interface (작업 끝·큐 끝)."""

    def __init__(self, state, enabled: bool = True, on_fit=lambda: None):
        self.state, self.enabled, self.on_fit = state, enabled, on_fit
        self.tried = False

    def attempt(self, bot: Bot, after_login: bool = False) -> bool:
        """맞춰 본다. after_login: 방금 접속을 마쳐 게임 안인 것이 확실함. 이번에 시도했으면 True (실패해도)."""
        if self.tried or not self.enabled:
            return False
        if not after_login and not bot.in_game():
            return False
        if not after_login and (why := busy(bot)):
            bot.log.info(f"{why} → 인터페이스 맞추기는 나중에")
            return False
        self.tried = True
        try:
            bot.log.info(prepare_interface(bot, self.state))
            self.on_fit()
        except (DisplayFixFailed, StepTimeout, MissingTemplate) as e:
            bot.log.warning(f"인터페이스 PC·80% 로 맞추지 못함 — 그대로 진행: {e}")
        return True


def restore_interface(bot: Bot, state) -> str:
    """모든 숙제가 끝난 뒤: 기억해 둔 원래 설정으로 되돌린다. 기억이 없거나 원래 PC·80% 면 할 일 없음."""
    rec = state.data.get(RESTORE_KEY)
    if not rec:
        return ""
    style, scale = rec.get("style") or "pc", rec.get("scale")
    scale = (scale or SCALE) if style == "pc" else None
    if (style, scale) != ("pc", SCALE):
        set_interface(bot, style, scale)
    state.data.pop(RESTORE_KEY, None)
    state._save()
    return f"인터페이스 원래대로 ({_shown_style(style, scale)})"


def fix_ingame(bot: Bot, cfg: dict) -> list[str]:
    """게임 안 환경 설정에서 맞춘다. 바꾼 것 목록. 실패하면 DisplayFixFailed."""
    done = []
    W, H = BASE_W, BASE_H  # 찍은 화면 기준 크기
    _open_graphics(bot)

    items = _texts(bot)
    screen = _find(items, gd.text("display_borderless"))
    res_label = _find(items, gd.text("display_resolution"), exact=True)
    if not screen or not res_label:
        raise DisplayFixFailed(f"화면 설정 칸을 찾지 못함 → {bot.snapshot('display').name}")
    cur = next(((t, x, y) for t, x, y in items
                if abs(y - res_label[2]) < 30 and x > res_label[1] + 150 and re.search(r"\d+\D\d+", t)), None)
    changed_screen = False
    bot.click((screen[1], screen[2]))  # 이미 골라져 있어도 누르는 건 해가 없다
    bot.sleep(0.8, 1.0)
    nums = [int(n) for n in re.findall(r"\d{3,4}", cur[0])] if cur else []
    if len(nums) < 2 or size_problem(nums[0], nums[1]):  # 16:9 · 1280x720 이상이면 그대로 둔다
        bot.click((cur[1], cur[2]) if cur else (res_label[1] + 500, res_label[2]))
        bot.sleep(1.0, 1.3)
        _click_text(bot, "1920", region=(W // 2, 0, W // 2, H), what="1920x1080", wait=1.0)
        done.append(f"해상도 {cur[0] + ' ' if cur else ''}→ 1920x1080")
        changed_screen = True
    _apply(bot)
    if changed_screen:
        done.append("설정값 적용")

    # 인터페이스는 여기서 바꾸지 않는다 — 숙제가 시작할 때 PC·80% 로 바꾸고 끝나면 되돌린다 (prepare_interface)
    _close_settings(bot)
    result = check(bot, interface=False)
    if not result["ok"]:
        raise DisplayFixFailed("바꾼 뒤에도 확인 실패: " + ", ".join(result["problems"]) + f" → {bot.snapshot('display').name}")
    return done


def _apply(bot: Bot, blind: bool = False) -> None:
    """'설정값 적용하기'. 바꾼 게 화면 모드면 '새 해상도 설정을 유지하시겠습니까? (5초 후 원래대로)' 창이 뜬다 →
    Space(유지). ESC 를 누르면 원래대로 돌아간다 (2026-10-23 '전체화면' 으로 바꿀 때 확인).
    blind: '전체화면' 으로 바꾸는 중이라 적용 뒤로는 화면이 멈춰 보인다 → 보지 않고 Space."""
    _click_text(bot, gd.text("display_apply"), what="설정값 적용하기", wait=2.5)
    if blind:
        bot.key("space")
    elif _find(_texts(bot), gd.text("display_keep")):
        bot.key("space")
    else:
        return
    bot.sleep(2.0, 2.4)


def _nums(t: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d{3,4}", t)]


def _pick_resolution(bot: Bot, w: int, h: int) -> bool:
    """(그래픽 탭) 해상도 목록에서 w×h 를 고른다. 이미 그 값이거나 목록에 없으면 (창모드 '자유' 등) 그대로. 골랐으면 True."""
    W, H = BASE_W, BASE_H
    items = _texts(bot)
    label = _find(items, gd.text("display_resolution"), exact=True)
    if not label:
        return False
    cur = next(((t, x, y) for t, x, y in items if abs(y - label[2]) < 30 and x > label[1] + 150), None)
    if not cur or _nums(cur[0])[:2] == [w, h] or not _nums(cur[0]):
        return False
    bot.click((cur[1], cur[2]))
    bot.sleep(1.0, 1.3)
    opt = next(((t, x, y) for t, x, y in _texts(bot, (W // 2, 0, W // 2, H))
                if _nums(t)[:2] == [w, h] and (x, y) != (cur[1], cur[2]) and y > cur[2] + 20), None)
    if not opt:
        bot.key("esc")  # 목록 닫기
        bot.sleep(0.8, 1.0)
        return False
    bot.click((opt[1], opt[2]))
    bot.sleep(0.8, 1.0)
    return True


# ---- 숙제 동안만 1920x1080 테두리 없는 전체화면 (원래 화면 모드·해상도는 기억했다가 끝나면 되돌린다) ----
RESTORE_FILE = "display_restore.json"  # 데이터 폴더에 두는 원래 화면 설정 기록
MODES = {0: "display_fullscreen", 1: "display_borderless", 3: "display_windowed"}
MODE_NAMES = {0: "전체화면", 1: "테두리 없는 전체화면", 3: "창모드"}


def screen_now(window) -> dict:
    """지금 화면 모드·해상도·창 위치 {mode, w, h, rect}. 게임을 앞으로 가져온 뒤에 부른다 (screen_mode)."""
    mode, w, h = screen_mode()
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(window.hwnd, ctypes.byref(r))
    return {"mode": mode, "w": w, "h": h, "rect": [r.left, r.top, r.right - r.left, r.bottom - r.top],
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def _shown_screen(rec: dict) -> str:
    name = MODE_NAMES.get(rec.get("mode"), "?")
    if rec.get("mode") == 3:
        return f"{name} {rec['rect'][2]}x{rec['rect'][3]}"
    return f"{name} {rec.get('w')}x{rec.get('h')}"


def restore_screen(bot: Bot, path: Path) -> str:
    """기억해 둔 (path) 원래 화면 모드·해상도로 되돌린다. 되돌렸으면 기록을 지운다. 기록이 없으면 ''.
    '전체화면' 으로 되돌리면 적용한 뒤로는 화면이 멈춰 보이므로 확인 창(Space)과 설정 닫기(ESC)는 보지 않고 누른다."""
    if not path.is_file():
        return ""
    rec = json.loads(path.read_text(encoding="utf-8"))
    mode = rec.get("mode")
    if mode not in MODES:
        path.unlink(missing_ok=True)
        return ""
    bot.window.focus()
    bot.sleep(1.0, 1.3)
    now = screen_now(bot.window)
    if now["mode"] == mode and (mode == 3 or (now["w"], now["h"]) == (rec["w"], rec["h"])):
        changed = False
    else:
        changed = True
        _open_graphics(bot)
        _click_text(bot, gd.text(MODES[mode]), region=(BASE_W // 2, 0, BASE_W // 2, BASE_H), exact=True,
                    what=MODE_NAMES[mode], wait=1.0)
        if mode != 3 and rec.get("w") and rec.get("h"):
            _pick_resolution(bot, rec["w"], rec["h"])
        if mode == 0:
            _apply(bot, blind=True)
            bot.key("esc")  # 환경 설정 닫기 — 한 번이면 메인 화면 (두 번 누르면 메뉴가 열렸다 — 2026-10-23)
            bot.sleep(1.5, 1.8)
        else:
            _apply(bot)
            _close_settings(bot)
    if mode == 3:  # 창모드는 해상도 대신 창 크기·위치
        x, y, w, h = rec["rect"]
        user32 = ctypes.windll.user32
        if user32.IsZoomed(bot.window.hwnd):
            user32.ShowWindow(bot.window.hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(bot.window.hwnd, 0, x, y, w, h, 0x0004)  # SWP_NOZORDER
        changed = True
    path.unlink(missing_ok=True)
    return f"화면 원래대로 ({_shown_screen(rec)})" if changed else ""


# ---------------------------------------------------------------- 게임 끄기
def close_game(window, timeout: float = 40) -> bool:
    """창에 닫기를 보내고 프로세스가 끝나길 기다린다. 끝까지 안 꺼지면 False (강제 종료는 하지 않는다)."""
    user32 = ctypes.windll.user32
    if not game_running(window):
        return True
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(window.hwnd, ctypes.byref(pid))
    user32.PostMessageW(window.hwnd, 0x0010, 0, 0)  # WM_CLOSE
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, pid.value)  # SYNCHRONIZE
    if not h:
        time.sleep(3)
        return not window.find()
    try:
        return k32.WaitForSingleObject(h, int(timeout * 1000)) == 0
    finally:
        k32.CloseHandle(h)


# ---------------------------------------------------------------- 게임이 꺼졌을 때 파일로 바꾸기
def _prefs_root() -> Path:
    """%USERPROFILE%\\AppData\\LocalLow\\devCAT — LocalLow 는 옮겨질 수 있어 Windows 에 위치를 묻는다."""
    try:
        guid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(FOLDERID_LOCAL_APPDATA_LOW).bytes_le)
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(p)) == 0:
            try:
                return Path(p.value) / "devCAT"
            finally:
                ctypes.windll.ole32.CoTaskMemFree(p)
    except (OSError, AttributeError):
        pass
    return Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "devCAT"


def fix_offline(backup_dir: Path, window=None) -> list[str]:
    """게임이 꺼져 있을 때 설정 파일과 레지스트리를 고친다. 바꾼 것 목록. 고치기 전 백업을 backup_dir 에 남긴다."""
    if window is not None and game_running(window):
        raise DisplayFixFailed("게임이 켜져 있어 파일을 고칠 수 없음 (게임이 꺼질 때 설정을 다시 저장한다)")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = backup_dir / f"display_{stamp}"
    done = []

    for name in PREFS_DIRS:
        d = _prefs_root() / name
        base, changed = d / "BaseMMPlayerPrefs.txt", d / "ChangedMMPlayerPrefs.txt"
        if not base.is_file():
            continue
        (bdir / name).mkdir(parents=True, exist_ok=True)
        for f in (base, changed):
            if f.is_file():
                shutil.copy2(f, bdir / name / f.name)
        text = base.read_bytes().decode("utf-8")
        for key, (_, val) in PREFS.items():
            text, n = re.subn(rf"(?m)^({re.escape(key)} : ).*?(\r?)$", rf"\g<1>{val}\g<2>", text)
            if n:
                done.append(f"{name}/Base {key} = {val}")
        base.write_bytes(text.encode("utf-8"))
        if changed.is_file():
            # 바뀐 것 기록은 마지막 줄이 이긴다 → 맞는 값을 끝에 덧붙인다
            raw = changed.read_bytes().decode("utf-8")
            nl = "\r\n" if "\r\n" in raw else "\n"
            add = "".join(f"+{t} : {key} : {val}{nl}" for key, (t, val) in PREFS.items())
            changed.write_bytes((raw if raw.endswith(("\n", "\r")) or not raw else raw + nl).encode("utf-8") + add.encode("utf-8"))
            done.append(f"{name}/Changed 에 {len(PREFS)}줄 덧붙임")

    for sub in REG_KEYS:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE)
        except OSError:
            continue
        with k:
            names, i = [], 0
            while True:
                try:
                    names.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    break
                i += 1
            saved = []
            for prefix, val in REG.items():
                for n in names:
                    if n.startswith(prefix):
                        old = winreg.QueryValueEx(k, n)[0]
                        saved.append(f"{n} = {old}")
                        winreg.SetValueEx(k, n, 0, winreg.REG_DWORD, val)
                        done.append(f"레지스트리 {n} = {val}")
            bdir.mkdir(parents=True, exist_ok=True)
            (bdir / f"registry_{sub.split(chr(92))[-1]}.txt").write_text("\n".join(saved), encoding="utf-8")
    if not done:
        raise DisplayFixFailed("고칠 설정 파일·레지스트리를 찾지 못함")
    return done


def leave_exclusive(bot: Bot) -> bool:
    """'전체화면'(독점) 이면 Alt+Enter 로 창모드로 빼낸다. 독점 전체화면에선 화면을 찍어도 멈춘 옛 화면만 보여서
    (mss·PrintWindow) 환경 설정을 눈으로 따라갈 수 없다 — 창모드가 되면 fix_ingame 이 테두리 없는 전체화면으로 맞춘다.
    (2026-10-23 확인: Alt+Enter → 창모드 1280x720, 모니터 해상도도 원래대로). 빼냈으면 True."""
    bot.window.focus()  # 내려가 있는 동안은 레지스트리가 창모드라 앞으로 가져온 뒤에 본다
    bot.sleep(2.5, 2.8)
    if not exclusive_fullscreen():
        return False
    bot.input.hotkey("alt", "enter")
    end = time.monotonic() + 10
    while exclusive_fullscreen() and time.monotonic() < end:
        time.sleep(0.5)
    if exclusive_fullscreen():
        raise DisplayFixFailed("'전체화면' 에서 빠져나오지 못함 (Alt+Enter)")
    bot.sleep(2.5, 3.0)  # 모니터 해상도가 돌아오고 창이 다시 그려질 때까지
    bot.window.focus()
    return True


# ---------------------------------------------------------------- 전체 흐름
def ensure(bot: Bot, cfg: dict, backup_dir: Path, allow_close: bool = True, remember: Path | None = None) -> str:
    """켜져 있으면 게임 안에서, 실패하면 (allow_close) 게임을 끄고 파일로. 꺼져 있으면 파일로.
    remember: 게임 안에서 맞추기 전 화면 모드·해상도를 이 파일에 적어 둔다 — 숙제가 끝나면 되돌린다 (restore_screen).
    이미 있으면 (전에 맞추고 아직 못 되돌림) 덮어쓰지 않는다 — 그때 값은 이미 바꾼 뒤라 원래 값이 아니다."""
    if not game_running(bot.window):
        done = fix_offline(backup_dir, bot.window)
        return f"게임이 꺼져 있어 파일로 맞춤 ({len(done)}곳). 게임을 켜면 적용됩니다"
    # 창 크기·HUD 가 맞아 보여도 스케일·해상도는 메뉴를 봐야 알 수 있어 늘 메뉴에서 확인한다 (맞으면 안 바꾼다)
    try:
        bot.window.focus()
        if remember is not None and not remember.is_file():
            bot.sleep(2.5, 2.8)  # '전체화면' 은 앞으로 와야 레지스트리가 제 값이다
            remember.parent.mkdir(parents=True, exist_ok=True)
            remember.write_text(json.dumps(screen_now(bot.window), ensure_ascii=False), encoding="utf-8")
        left = leave_exclusive(bot)
        done = (["전체화면 → 창모드 (Alt+Enter)"] if left else []) + fix_ingame(bot, cfg)
        return "게임 안에서 맞춤: " + (", ".join(done) if done else "이미 맞아 있음")
    except DisplayFixFailed as e:
        bot.log.warning(f"게임 안에서 화면 설정 실패: {e}")
        if not allow_close:
            raise
    bot.log.warning("게임을 끄고 설정 파일로 맞춥니다")
    if not close_game(bot.window):
        raise DisplayFixFailed("게임이 꺼지지 않음 — 직접 끈 뒤 다시 시도해 주세요")
    time.sleep(3)  # 꺼질 때 설정을 저장하므로 다 쓰고 난 뒤 고친다
    done = fix_offline(backup_dir, bot.window)
    return f"게임 안에서 실패 → 게임을 끄고 파일로 맞춤 ({len(done)}곳). 런처에서 게임을 다시 켜 주세요"
