"""MabinogiMobile_CLI(공식 AI 커넥터) 호출. 리모콘 src/connector.js 를 옮긴 것.

- 비ASCII 본문은 'base64:' + UTF-8 base64 로 넘긴다 (콘솔 코드페이지가 한글을 깨뜨린다).
- stdout 은 \\uXXXX 이스케이프된 JSON 이다. 파싱이 안 되면 last-response.json(진짜 UTF-8)을 읽는다.
- 게임의 거부도 종료 코드 0 으로 오므로 ok = 종료 코드 0 이면서 본문에 error 가 없을 때.
- 게임 행동 명령(execute_* 등)은 한 번에 하나만 (게임이 동시에 두 행동을 못 한다).
- 게임이 꺼져 있으면 호출 하나가 약 5초 걸린다 (CLI 자체 파이프 타임아웃).
"""
import base64
import json
import os
import re
import subprocess
import threading
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from . import gamedata as gd

EXE_NAME = "MabinogiMobile_CLI.exe"
LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
LAST_RESPONSE = LOCAL / "MabinogiMobileCLI" / "last-response.json"
CAPABILITIES = LOCAL / "MabinogiMobileCLI" / "CAPABILITIES.json"
CREATE_NO_WINDOW = 0x08000000

EXIT_REASON = {2: "usage_error", 3: "canceled", 4: "unknown_command", 5: "disconnected"}

# 비용은 CAPABILITIES 의 Note("Running this command consumes 5 정령의 날개.")에서 읽는다.
# 아래는 못 읽었을 때의 대체값 (0 으로 보는 것보다 안전)
COSTED_COMMANDS = {"execute_gathering", "execute_crafting", "execute_altering"}
COST_RE = re.compile(r"consumes\s+(\d+)\s+([^.]+?)\s*\.", re.I)

# 게임 상태를 바꾸는 명령 (조회가 아닌 것)
ACTION_COMMANDS = {"write_chat", "play_music_score", "change_instrument", "stop_action", "stand_up",
                   "execute_gathering", "execute_altering", "complete_altering_work", "execute_crafting"}

REG_KEYS = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Nexon\MabinogiM"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Nexon\MabinogiM"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Nexon\MabinogiM")]
INSTALL_PATTERNS = [r"Nexon\MabinogiMobile", r"Program Files\Nexon\MabinogiMobile",
                    r"Program Files (x86)\Nexon\MabinogiMobile", r"Games\Nexon\MabinogiMobile",
                    r"Nexon\마비노기 모바일"]
UNINSTALL_ROOTS = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                   (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                   (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]


def is_run_limit(error, message) -> bool:
    """CLI 오류가 '연속 실행 제한' 인가. 오류 코드는 아직 실측 전이라 코드·문구 어느 쪽이든 continuous/run limit 이면."""
    t = f"{error or ''} {message or ''}".lower().replace("_", " ")
    return "continuous" in t or "run limit" in t or "오랫동안 실행" in t


@dataclass
class Result:
    ok: bool
    code: int
    reason: str | None = None   # 종료 코드 사유 또는 본문 error
    data: object = None
    error: str | None = None
    message: str | None = None
    ms: int = 0


# ---------------------------------------------------------------- 실행 파일 찾기
def _reg_value(root, key: str, name: str) -> str | None:
    try:
        with winreg.OpenKey(root, key) as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip() or None
    except OSError:
        return None


def _drives() -> list[str]:
    """실제로 있는 드라이브만. A·B 는 없는 플로피를 찔러 느려질 수 있어 C 부터."""
    return [f"{chr(c)}:" for c in range(ord("C"), ord("Z") + 1) if os.path.exists(f"{chr(c)}:\\")]


def _uninstall_dirs() -> list[str]:
    """제거 프로그램 목록에서 경로가 될 만한 값(InstallLocation·DisplayIcon·UninstallString)을 전부 모은다.
    폴더 이름은 사람이 바꿀 수 있어 이름으로 거르지 않고, 그 안에 exe 가 실제로 있는지로 판정한다."""
    likely, rest, seen = [], [], set()
    for root, key in UNINSTALL_ROOTS:
        try:
            base = winreg.OpenKey(root, key)
        except OSError:
            continue
        with base:
            for i in range(winreg.QueryInfoKey(base)[0]):
                try:
                    sub = winreg.OpenKey(base, winreg.EnumKey(base, i))
                except OSError:
                    continue
                with sub:
                    for name in ("InstallLocation", "DisplayIcon", "UninstallString"):
                        try:
                            v = str(winreg.QueryValueEx(sub, name)[0]).strip().lstrip('"')
                        except OSError:
                            continue
                        v = v.split('"', 1)[0].strip()
                        v = re.sub(r",\s*\d+$", "", v)   # DisplayIcon 의 ',0'
                        if not re.match(r"^[a-zA-Z]:\\", v):
                            continue
                        d = str(Path(v).parent) if re.search(r"\.(exe|dll|ico)$", v, re.I) else v.rstrip("\\/")
                        if d.lower() in seen:
                            continue
                        seen.add(d.lower())
                        (likely if re.search("mabinogi|마비노기", d, re.I) else rest).append(d)
    return likely + rest


def candidates(configured: str | None = None) -> Iterator[tuple[str, str]]:
    """(경로, 출처)를 정확한 것 → 싼 것 → 비싼 것 순으로 하나씩 낸다 (앞에서 찾으면 뒤 탐색 비용을 안 치른다)."""
    if os.environ.get("MM_CLI_PATH"):
        yield os.environ["MM_CLI_PATH"], "MM_CLI_PATH 환경변수"
    if configured:
        yield configured, "설정에서 지정"
    for root, key in REG_KEYS:
        d = _reg_value(root, key, "RootPath")
        if d:
            yield str(Path(d) / EXE_NAME), "레지스트리 " + key.rsplit("\\", 1)[-1]
    for drv in _drives():
        for p in INSTALL_PATTERNS:
            yield str(Path(drv + "\\") / p / EXE_NAME), "기본 설치 경로"
    for drv in _drives():
        base = Path(drv + "\\Nexon")
        try:
            subs = [p for p in base.iterdir() if p.is_dir()] if base.exists() else []
        except OSError:
            subs = []
        for p in subs:
            yield str(p / EXE_NAME), "Nexon 폴더 탐색"
    for d in _uninstall_dirs():
        yield str(Path(d) / EXE_NAME), "제거 프로그램 목록"


@dataclass
class Located:
    path: str
    source: str
    found: bool
    tried: list = field(default_factory=list)


class Connector:
    def __init__(self, configured_path: Callable[[], str | None] = lambda: None, log=None):
        """configured_path: 설정에서 직접 지정한 CLI 경로를 돌려주는 함수 (없으면 None)."""
        self._configured = configured_path
        self._located: Located | None = None
        self._action_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._costs: dict | None = None
        self.log = log
        self.on_call: Callable[[str, object, Result], None] | None = None  # 호출 기록용
        # 게임을 오래 켜 두면 AI 에이전트 명령에 '연속 실행 제한'이 걸린다 (게임 데이터 CliForAi_ExecuteCommon_
        # MsgContinuousRunLimit · 화면에는 '게임이 너무 오랫동안 실행되고 있습니다' 창). 한 번 걸리면 게임을 다시 켜야 풀린다
        self.run_limited = False

    # ---- 실행 파일 ----
    def locate(self, force: bool = False) -> Located:
        if self._located and not force and (not self._located.found or os.path.exists(self._located.path)):
            return self._located
        tried = []
        for p, src in candidates(self._configured()):
            tried.append(p)
            if os.path.exists(p):
                self._located = Located(p, src, True, tried)
                return self._located
        self._located = Located(EXE_NAME, "PATH (탐색 실패)", False, tried)
        return self._located

    # ---- 호출 ----
    @staticmethod
    def encode_body(body) -> str | None:
        if body is None:
            return None
        s = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        if s == "":
            return None
        return s if s.isascii() else "base64:" + base64.b64encode(s.encode("utf-8")).decode("ascii")

    @staticmethod
    def _parse(stdout: bytes):
        text = stdout.decode("utf-8", "replace").strip()
        if text:
            try:
                return json.loads(text)
            except ValueError:
                pass
        try:
            return json.loads(LAST_RESPONSE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"raw": text} if text else None

    def run(self, command: str, body=None, timeout: float | None = None) -> Result:
        """명령 하나. 게임 행동 명령은 동시에 하나만 (이미 진행 중이면 error='busy')."""
        action = command in ACTION_COMMANDS
        if action and not self._action_lock.acquire(blocking=False):
            return Result(False, -1, "busy", None, "busy", "다른 명령이 진행 중입니다")
        try:
            return self._run(command, body, timeout, track=action)
        finally:
            if action:
                self._action_lock.release()

    def _run(self, command: str, body, timeout: float | None, track: bool) -> Result:
        args = [self.locate().path, command]
        enc = self.encode_body(body)
        if enc is not None:
            args.append(enc)
        t0 = time.monotonic()
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        except OSError as e:
            r = Result(False, -1, "spawn_failed", None, "spawn_failed", str(e), int((time.monotonic() - t0) * 1000))
            self._notify(command, body, r)
            return r
        if track:
            self._proc = p
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
        finally:
            if track:
                self._proc = None
        data = self._parse(out)
        body_err = data.get("error") if isinstance(data, dict) else None
        code = p.returncode
        r = Result(ok=code == 0 and not body_err, code=code,
                   reason=EXIT_REASON.get(code) or (str(body_err) if body_err else None), data=data,
                   error=body_err or EXIT_REASON.get(code),
                   message=(data.get("message") if isinstance(data, dict) else None)
                   or err.decode("utf-8", "replace").strip() or EXIT_REASON.get(code),
                   ms=int((time.monotonic() - t0) * 1000))
        if not r.ok and is_run_limit(r.error, r.message):
            self.run_limited = True
        self._notify(command, body, r)
        return r

    def _notify(self, command, body, r: Result) -> None:
        if self.on_call:
            try:
                self.on_call(command, body, r)
            except Exception:
                pass

    def cancel(self) -> None:
        """진행 중인 게임 행동 명령을 끊는다 (CLI 프로세스 종료 → 게임도 그 행동을 멈춘다)."""
        p = self._proc
        if p and p.poll() is None:
            p.kill()

    def busy(self) -> bool:
        return self._action_lock.locked()

    # ---- 상태 ----
    def status(self) -> dict:
        """{connected, pipe, reason}. reason: game_off | option_off | no_connector | None.
        no_connector(커넥터 exe 를 못 찾음)는 게임이 꺼진 것과 다르다 — 이 PC 에 게임이 없다는 뜻이 대부분."""
        r = self.run("status", timeout=15)
        data = r.data if isinstance(r.data, dict) else {}
        gone = r.reason == "spawn_failed" or not self.locate().found
        return {"connected": data.get("pipe") == "connected", "pipe": data.get("pipe", "unknown"),
                "reason": data.get("reason") or ("no_connector" if gone else None)}

    # ---- 명령 목록과 비용 ----
    def capabilities(self, refresh: bool = False) -> list[dict]:
        if refresh:
            r = self.run("capabilities", timeout=30)
            if r.ok and isinstance(r.data, dict) and r.data.get("commands"):
                CAPABILITIES.parent.mkdir(parents=True, exist_ok=True)
                CAPABILITIES.write_text(json.dumps(r.data, ensure_ascii=False, indent=2), encoding="utf-8")
                self._costs = None
                return r.data["commands"]
        try:
            return json.loads(CAPABILITIES.read_text(encoding="utf-8")).get("commands", [])
        except (OSError, ValueError):
            return []

    def costs(self) -> dict[str, dict]:
        """{명령: {amount, currency}}. CAPABILITIES 에서 런타임에 읽으므로 게임이 비용을 바꿔도 따라간다."""
        if self._costs is None:
            m = {}
            for c in self.capabilities():
                hit = COST_RE.search(c.get("Note") or "")
                if hit:
                    m[c["Command"]] = {"amount": int(hit.group(1)), "currency": hit.group(2).strip()}
            if not m:
                m = {c: {"amount": gd.rules()["wingCostPerCommand"]["amount"], "currency": gd.currency("wings")} for c in COSTED_COMMANDS}
            self._costs = m
        return self._costs

    def cost_of(self, command: str) -> dict | None:
        return self.costs().get(command)


COST_SPENT_RE = re.compile(r"(?P<cur>[^,.]+?)\s+(?P<spent>\d+)\s+spent,\s*(?P<left>\d+)\s+left", re.I)


def parse_cost(sentence: str | None) -> dict | None:
    """응답 cost 문장 '정령의 날개 5 spent, 52510 left.' → {currency, spent, left}. blocked 여도 나갈 수 있다."""
    m = COST_SPENT_RE.search(sentence or "")
    if not m:
        return None
    return {"currency": m.group("cur").strip(), "spent": int(m.group("spent")), "left": int(m.group("left"))}
