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
import os
import re
import shutil
import time
import winreg
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from .. import ocr
from ..bot import Bot, StepTimeout

WIDTH, HEIGHT = 1920, 1080
SCALE = 80
REG_KEYS = (r"Software\devCAT\마비노기 모바일", r"Software\devCAT\Mabinogi Mobile")
PREFS_DIRS = ("마비노기 모바일", "Mabinogi Mobile")
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


# ---------------------------------------------------------------- 확인
def check(bot: Bot | None = None, window=None) -> dict:
    """{ok, problems: [..], client: (w, h), dpi}. 게임이 없으면 running False."""
    win = window or (bot.window if bot else None)
    if win is None or not game_running(win):
        return {"ok": False, "running": False, "problems": ["게임이 꺼져 있음"]}
    try:
        r = win.client_rect()
    except RuntimeError:
        return {"ok": False, "running": False, "problems": ["게임이 꺼져 있음"]}
    dpi = ctypes.windll.user32.GetDpiForWindow(win.hwnd) or 96
    problems = []
    if (r.width, r.height) != (WIDTH, HEIGHT):
        problems.append(f"게임 화면이 {r.width}x{r.height} (1920x1080 이어야 함)")
    if dpi != 96:
        problems.append(f"Windows 화면 배율이 {round(dpi / 96 * 100)}% (100% 이어야 함)")
    # 인터페이스 스타일·스케일은 게임 설정 파일로 본다 (게임이 켜져 있어도 바꾸면 Changed 파일에 바로 덧붙는다 — 2026-10-22).
    # 파일이 없을 때만 화면의 HUD 모양으로 짐작한다
    prefs = read_prefs()
    if prefs:
        for key, (_, want) in PREFS.items():
            have = prefs.get(key)
            if have is not None and float(have) != float(want):
                problems.append(f"{PREFS_LABEL[key]}: {_shown(key, have)} ({_shown(key, want)} 이어야 함)")
    if bot is not None and not problems and not prefs:
        # 메인 화면인데 HUD 템플릿이 안 맞으면 인터페이스 배율·스타일이 다른 것
        # bot.frame() 은 중단 키를 검사한다 — '직접 맞춘 뒤 F12' 로 다시 확인할 때 그 F12 를 중단으로 받으므로 바로 찍는다.
        # 화면을 그대로 찍으므로 게임이 다른 창(브라우저 등)에 가려 있으면 그 창을 보고 '다름' 으로 판단했다 (2026-10-22)
        # → 게임을 앞으로 가져온 뒤 찍는다. 곧 숙제를 시작할 참이라 어차피 앞으로 온다
        if ctypes.windll.user32.GetForegroundWindow() != win.hwnd:
            win.focus()
            time.sleep(0.8)
        frame = bot.screen.grab()
        if bot.state.query("get_my_info") is not None and not bot.vision.find(frame, bot.ui["main_hud"]):
            problems.append("메인 화면 표시(HUD)가 기준과 다름 — 인터페이스 스타일·스케일 확인 필요")
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
    label = _find(items, "스케일조절")
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


def fix_ingame(bot: Bot, cfg: dict) -> list[str]:
    """게임 안 환경 설정에서 맞춘다. 바꾼 것 목록. 실패하면 DisplayFixFailed."""
    done = []
    try:
        bot.to_main(tries=4)
    except StepTimeout:
        pass  # HUD 템플릿이 배율 때문에 안 맞을 수 있다. ESC 메뉴는 글자로 찾는다
    r = bot.window.client_rect()
    bot.key("esc")
    bot.sleep(1.5, 1.8)
    _click_text(bot, "환경설정", region=(r.width // 2, 0, r.width // 2, r.height), what="환경 설정")
    _click_text(bot, "그래픽", region=(0, 0, r.width, r.height // 4), exact=True, what="그래픽 탭")

    items = _texts(bot)
    screen = _find(items, "테두리없는전체화면")
    res_label = _find(items, "해상도", exact=True)
    if not screen or not res_label:
        raise DisplayFixFailed(f"화면 설정 칸을 찾지 못함 → {bot.snapshot('display').name}")
    cur = next(((t, x, y) for t, x, y in items
                if abs(y - res_label[2]) < 30 and x > res_label[1] + 150 and re.search(r"\d+\D\d+", t)), None)
    changed_screen = False
    bot.click((screen[1], screen[2]))  # 이미 골라져 있어도 누르는 건 해가 없다
    bot.sleep(0.8, 1.0)
    if not cur or "1920" not in cur[0]:
        bot.click((cur[1], cur[2]) if cur else (res_label[1] + 500, res_label[2]))
        bot.sleep(1.0, 1.3)
        _click_text(bot, "1920", region=(r.width // 2, 0, r.width // 2, r.height), what="1920x1080", wait=1.0)
        done.append(f"해상도 {cur[0] if cur else '?'} → 1920x1080")
        changed_screen = True
    _click_text(bot, "설정값적용하기", what="설정값 적용하기", wait=2.5)
    if changed_screen:
        done.append("설정값 적용")

    _click_text(bot, "PC", region=(r.width // 2, 0, r.width // 2, r.height), exact=True, what="인터페이스 PC", wait=1.2)
    # 스케일 조절 줄이 보이도록 오른쪽 칸을 내린다
    bot.input.scroll(r.left + int(r.width * 0.73), r.top + int(r.height * 0.65), -10)
    bot.sleep(1.2, 1.5)
    for _ in range(8):
        pct, left, right = _scale_row(bot)
        if pct is None:
            raise DisplayFixFailed(f"스케일 조절 값을 읽지 못함 → {bot.snapshot('display').name}")
        if pct == SCALE:
            break
        bot.click(left if pct > SCALE else right)  # 한 번에 10%씩. 누를 때마다 배치가 바뀌므로 매번 다시 읽는다
        bot.sleep(1.0, 1.3)
        done.append(f"스케일 {pct}% → {pct - 10 if pct > SCALE else pct + 10}%")
    else:
        raise DisplayFixFailed(f"스케일을 {SCALE}% 로 맞추지 못함 → {bot.snapshot('display').name}")

    bot.key("esc")  # 환경 설정 닫기
    bot.sleep(1.5, 1.8)
    try:
        bot.to_main(tries=3)
    except StepTimeout:
        pass
    result = check(bot)
    if not result["ok"]:
        raise DisplayFixFailed("바꾼 뒤에도 확인 실패: " + ", ".join(result["problems"]) + f" → {bot.snapshot('display').name}")
    return done


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


# ---------------------------------------------------------------- 전체 흐름
def ensure(bot: Bot, cfg: dict, backup_dir: Path, allow_close: bool = True) -> str:
    """켜져 있으면 게임 안에서, 실패하면 (allow_close) 게임을 끄고 파일로. 꺼져 있으면 파일로."""
    if not game_running(bot.window):
        done = fix_offline(backup_dir, bot.window)
        return f"게임이 꺼져 있어 파일로 맞춤 ({len(done)}곳). 게임을 켜면 적용됩니다"
    # 창 크기·HUD 가 맞아 보여도 스케일·해상도는 메뉴를 봐야 알 수 있어 늘 메뉴에서 확인한다 (맞으면 안 바꾼다)
    try:
        bot.window.focus()
        done = fix_ingame(bot, cfg)
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
