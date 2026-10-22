"""태스크가 사용하는 고수준 조작 API.

좌표는 모두 게임 클라이언트 기준이며, 클릭 시 화면 좌표로 변환한다.
F12(설정 game.stop_key)를 누르면 다음 대기/캡처 시점에 StopRequested 가 발생해 전체 실행이 중단된다.
5초 안에 멈추지 못하면 프로세스를 강제로 끝낸다 (inputs.StopWatcher).
"""
import logging
import random
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .digits import DigitReader
from .connector import Connector
from .game_state import GameState
from .inputs import Input, StopWatcher, vk_of
from .screen import Screen
from .vision import Match, Vision
from .window import GameWindow


class StopRequested(Exception):
    pass


class StepTimeout(Exception):
    pass


class Overweight(Exception):
    """가방 무게가 한도를 넘어 숙제를 이어갈 수 없음. 실행기는 그 캐릭터를 건너뛴다."""


class MissingTemplate(Exception):
    pass


class AuthBlocked(Exception):
    """'계정 인증 실패'가 거듭 나서 접속을 더 시도하지 않는다. 실행기는 전체 실행을 멈춘다."""


class Bot:
    def __init__(self, cfg: dict, paths, dry_run: bool = False, force_exit: bool = True, cli=None):
        self.cfg = cfg
        self.paths = paths
        self.log = logging.getLogger("mabi")
        self.window = GameWindow(cfg["game"]["window_title"])
        self.screen = Screen(self.window)
        v = cfg["vision"]
        self.vision = Vision(paths.templates, v["threshold"], v["roi_margin"])
        i = cfg["input"]
        self.input = Input(i["jitter_px"], dry_run=dry_run, log=self.log)
        self.delay = (i["delay_min"], i["delay_max"])
        self.stopper = StopWatcher(vk_of(cfg["game"]["stop_key"]), log=self.log, force_exit=force_exit)
        self.ui = cfg["ui"]
        self.counters = cfg["counters"]
        self.digits = DigitReader(paths.templates / "digits", self.counters["white_threshold"])
        self.cli = cli or Connector(lambda: cfg["game"].get("cli_path"), self.log)
        self.state = GameState(self.cli, self.log)
        self.shot_dir = paths.shots
        self.character: dict | None = None  # 지금 숙제 중인 캐릭터 ({"slot", "name"}), runner 가 설정
        self.weight_limit = 0.0  # 가방 무게 감시 비율 (0 = 끔), runner 가 설정
        self._weight_at = 0.0
        self.daily = None  # 오늘 진행 기록 (profile.DailyState), runner 가 설정
        self.also_done: set[str] = set()  # 다른 태스크 안에서 함께 끝낸 태스크 id (runner 가 완료로 기록)
        self.task_id: str | None = None  # 지금 하는 숙제 id, runner 가 설정
        # 이 숙제를 지난번에 어디까지 했나 ({"stage", "at", ...}) — 도중에 끊겼으면 있다. 숙제가 보고 이어 한다
        self.resume: dict | None = None
        self._last_food_check = 0.0
        self._frame: np.ndarray | None = None

    def step(self, step: str, text: str = "", **data) -> None:
        """숙제 안의 단계를 오늘 기록에 남긴다 (끊긴 뒤 다시 시작하면 bot.resume 으로 돌아온다).
        step 은 단계 키 (숙제마다 정한 고정 이름 — 이어 하기는 이걸로 판단), text 는 로그·화면용 설명."""
        self.log.info(f"  · [{step}] {text}" if text else f"  · [{step}]")
        if self.daily is not None and self.character and self.task_id:
            self.daily.set_step(self.character["slot"], self.task_id, step, text, **data)

    def resumed_at(self, *steps: str) -> dict | None:
        """지난번에 이 숙제가 steps 중 한 단계에서 끊겼으면 그 기록."""
        r = self.resume
        return r if r and r.get("step") in steps else None

    # ---- 기본 ----
    def check_stop(self) -> None:
        if self.stopper.stopped.is_set():
            raise StopRequested()
        self.check_weight()

    def check_weight(self, every: float = 20) -> None:
        """weight_limit(비율)이 켜져 있으면 every 초마다 CLI 로 가방 무게를 보고, 넘으면 Overweight."""
        if not self.weight_limit or time.monotonic() - self._weight_at < every:
            return
        self._weight_at = time.monotonic()
        inv = self.state.query("get_inventory", timeout=10) if self.state.available() else None
        cur, mx = (inv or {}).get("CurrentInventoryWeight", 0), (inv or {}).get("MaxInventoryWeight", 0)
        if not mx or cur < mx * self.weight_limit:
            return
        # 무게를 넘으면 자동 이동·전투가 멈추므로 던전 안이라도 바로 그만둔다
        raise Overweight(f"가방 무게 {cur:.0f}/{mx:.0f}")

    def sleep(self, a: float, b: float | None = None) -> None:
        end = time.monotonic() + (random.uniform(a, b) if b else a)
        while True:
            self.check_stop()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.1, left))

    def pause(self) -> None:
        """조작 사이의 기본 대기."""
        self.sleep(*self.delay)

    def frame(self) -> np.ndarray:
        self.check_stop()
        # 화면을 그대로 캡처하므로 다른 창(터미널, 알림 등)이 위에 있으면 인식이 틀어진다
        self.ensure_focus()
        self._frame = self.screen.grab()
        return self._frame

    def _require_template(self, name: str) -> None:
        if not self.vision.has(name):
            raise MissingTemplate(f"템플릿 '{name}' 이 없습니다. tools/capture.py 로 만들어 주세요.")

    # ---- 인식 ----
    def find(self, name: str, region=None, threshold=None, fresh: bool = True) -> Match | None:
        self._require_template(name)
        frame = self.frame() if fresh or self._frame is None else self._frame
        return self.vision.find(frame, name, region, threshold)

    def find_all(self, name: str, region=None, threshold=None) -> list[Match]:
        self._require_template(name)
        return self.vision.find_all(self.frame(), name, region, threshold)

    def exists(self, name: str, **kw) -> bool:
        return self.find(name, **kw) is not None

    def wait_any(self, names: list[str], timeout: float = 10, interval: float = 0.4) -> Match:
        for n in names:
            self._require_template(n)
        end = time.monotonic() + timeout
        while True:
            frame = self.frame()
            for n in names:
                m = self.vision.find(frame, n)
                if m:
                    return m
            if time.monotonic() > end:
                raise StepTimeout(f"{timeout:.0f}s 안에 {names} 중 아무것도 나타나지 않음")
            self.sleep(interval)

    def wait(self, name: str, timeout: float = 10, interval: float = 0.4) -> Match:
        return self.wait_any([name], timeout, interval)

    def wait_gone(self, name: str, timeout: float = 10, interval: float = 0.4) -> None:
        end = time.monotonic() + timeout
        while self.exists(name):
            if time.monotonic() > end:
                raise StepTimeout(f"{timeout:.0f}s 동안 '{name}' 이 사라지지 않음")
            self.sleep(interval)

    def read_counter(self, name: str) -> int | None:
        """재화 현재값 (예: 'silver', 'tribute'). CLI 조회가 안 되면 HUD 숫자를 판독한다."""
        if self.state.available():
            value = self.state.currency(self.counters["cli_names"][name])
            if value is not None:
                return value
        value = self.digits.read_stable(self.screen.grab, self.counters[name])
        if value is None:
            path = self.snapshot(f"counter_{name}_unreadable")
            self.log.warning(f"{name} 숫자 판독 실패 → {path.name}")
        return value

    # ---- 조작 ----
    def ensure_focus(self) -> None:
        """게임 창이 앞에 없으면 가져온다. 포커스를 옮긴 직후 첫 키 입력은 게임이 무시하므로
        효과 없는 키(Shift)를 한 번 먼저 보낸다."""
        if self.window.is_foreground() or self.input.dry_run:
            return
        self.window.focus()
        self.sleep(0.8)
        self.input.key("shift")
        self.sleep(0.3)

    def click_xy(self, x: int, y: int) -> None:
        self.ensure_focus()
        r = self.window.client_rect()
        self.input.click(r.left + x, r.top + y)
        self.pause()

    def click(self, target: str | Match | tuple[int, int], timeout: float = 10) -> Match | None:
        """템플릿 이름이면 나타날 때까지 기다렸다가 중앙을 클릭."""
        if isinstance(target, str):
            m = self.wait(target, timeout)
            self.log.debug(f"click {m.name} score={m.score:.2f} at {m.center}")
            self.click_xy(*m.center)
            return m
        if isinstance(target, Match):
            self.click_xy(*target.center)
            return target
        self.click_xy(*target)
        return None

    def click_if(self, name: str, **kw) -> bool:
        m = self.find(name, **kw)
        if m:
            self.click_xy(*m.center)
        return m is not None

    def click_steps(self, steps: list[str], timeout: float = 10) -> None:
        for step in steps:
            self.click(step, timeout)

    def key(self, key: str) -> None:
        self.ensure_focus()
        self.input.key(key)
        self.pause()

    # ---- 복구 ----
    def dismiss_popups(self, max_n: int = 6) -> int:
        """공지/이벤트 팝업 등을 닫는다. 닫은 개수를 반환."""
        closers = [n for n in self.ui["popup_closers"] if self.vision.has(n)]
        closed = 0
        for _ in range(max_n):
            frame = self.frame()
            m = next((m for n in closers if (m := self.vision.find(frame, n))), None)
            if not m:
                break
            self.click_xy(*m.center)
            closed += 1
            self.sleep(0.6, 1.0)
        return closed

    def at_main(self) -> bool:
        return self.exists(self.ui["main_hud"])

    def eat_if_hungry(self, every: float = 60) -> bool:
        """좌상단 음식 아이콘의 'B' 표시가 보이면 (배고픔) B 를 눌러 음식을 먹는다. every 초에 한 번만 확인."""
        name = self.ui.get("food_b")
        if not name or not self.vision.has(name) or time.monotonic() - self._last_food_check < every:
            return False
        self._last_food_check = time.monotonic()
        if not self.exists(name):
            return False
        self.key("b")
        self.log.info("배고픔 표시 → 음식 먹기 (B)")
        self.sleep(1.5, 2)
        return True

    def skip_dialogue(self, max_n: int = 10) -> int:
        """NPC 대화(주간 정기 의뢰 조건 충족 시 클리어 후 가끔 나옴)가 진행 중이면 '대화 넘기기'를 누른다. 누른 횟수 반환."""
        name = self.ui.get("dialog_skip")
        n = 0
        for _ in range(max_n):
            act = self.state.activity() if self.state.available() else None
            playing = bool(act and act.get("IsDialoguePlaying"))
            m = self.find(name) if name and self.vision.has(name) else None
            if not playing and not m:
                break
            if m:
                self.click(m)
                n += 1
            self.sleep(1.2, 1.8)
        if n:
            self.log.info(f"대화 넘기기 {n}회")
        return n

    def to_main(self, tries: int = 10) -> None:
        """ESC 와 팝업 닫기를 반복해서 필드 메인 화면으로 돌아온다. 돌아오면 배고픔도 확인한다."""
        exit_dialog, cancel = self.ui["exit_dialog"], self.ui["exit_dialog_cancel"]
        for _ in range(tries):
            if self.at_main():
                self.eat_if_hungry()
                return
            # 타이틀·캐릭터 선택 화면에서 ESC 를 누르면 뒤로 가다가 '게임을 종료하시겠습니까?' 가 뜬다
            if self.exists(self.ui["title_start"]) or self.exists(self.ui["charselect_title"]):
                raise StepTimeout("게임 밖(타이틀/캐릭터 선택) 화면이라 메인으로 돌아갈 수 없음")
            if self.vision.has(self.ui["dialog_skip"]) and self.click_if(self.ui["dialog_skip"]):
                self.sleep(1.2, 1.8)
                continue
            if self.vision.has(exit_dialog) and self.exists(exit_dialog):
                self.click(cancel)
                continue
            if self.exists(self.ui["menu_quit"]):  # 메뉴(ESC)가 열려 있음 → ESC 로 닫고 애니메이션 대기
                self.key("esc")
                self.sleep(1.2, 1.6)
                continue
            if not self.dismiss_popups(1):
                self.key("esc")
            self.sleep(0.8, 1.3)
        if not self.at_main():
            raise StepTimeout("메인 화면으로 돌아오지 못함")

    def to_charselect(self) -> None:
        """메인 화면 → 메뉴 → 게임 종료 → '캐릭터 선택 화면으로'."""
        ui = self.ui
        self.to_main()
        # 음식 먹는 동작 직후 등에는 ESC 가 무시되기도 하므로 메뉴가 열릴 때까지 몇 번 시도한다
        for i in range(3):
            self.key("esc")
            try:
                self.wait(ui["menu_quit"], timeout=5)
                break
            except StepTimeout:
                if i == 2:
                    raise
                self.to_main()
        self.click(ui["menu_quit"])
        # 창이 뜨는 애니메이션 중에 클릭하면 아래 '시작 화면으로'가 눌릴 수 있어 단축키(Space)를 쓴다
        self.wait(ui["dialog_to_charselect"])
        self.sleep(0.8, 1.2)
        self.key("space")
        errors = [n for n in ui.get("login_errors", []) if self.vision.has(n)]
        m = self.wait_any([ui["charselect_title"], ui["title_start"], *errors], timeout=60)
        if m.name in errors:  # login.run 이 확인을 누르고 쉬었다가 다시 시도한다
            raise StepTimeout(f"접속 오류 창 ({m.name})")
        if m.name == ui["title_start"]:
            self.log.warning("캐릭터 선택 대신 타이틀로 나감 → 게임 시작")
            self.click(m)
            self.wait(ui["charselect_title"], timeout=60)
        self.state.available(refresh=True)

    def snapshot(self, tag: str) -> Path:
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        path = self.shot_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}.png"
        ok, buf = cv2.imencode(".png", self.screen.grab())
        if ok:
            buf.tofile(str(path))
        return path
