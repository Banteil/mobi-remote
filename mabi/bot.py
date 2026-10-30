"""태스크가 사용하는 고수준 조작 API.

좌표는 모두 게임 클라이언트 기준이며, 클릭 시 화면 좌표로 변환한다.
F12(설정 game.stop_key)를 누르면 다음 대기/캡처 시점에 StopRequested 가 발생해 전체 실행이 중단된다.
5초 안에 멈추지 못하면 프로세스를 강제로 끝낸다 (inputs.StopWatcher).
"""
import ctypes
import logging
import random
import re
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .digits import DigitReader
from .connector import Connector
from .game_state import GameState
from .inputs import Input, StopWatcher, post_key, vk_of
from . import packet_monitor
from .blackbox import BlackBox
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


SHOT_KEEP_DAYS = 7
# 음식을 먹은(또는 못 먹은) 뒤 다시 B 를 누르기까지 (초)
EAT_GAP = 60
SHOT_NAME = re.compile(r"\d{8}_\d{6}_.+\.png")  # snapshot() 이 붙이는 이름


def prune_shots(shot_dir: Path, log=None, keep_days: int = SHOT_KEEP_DAYS) -> int:
    """keep_days 일보다 오래된 스크린샷을 지운다. 실패·디버깅 때마다 한 장(1MB 남짓)씩 쌓여
    정리 없이 닷새 만에 130MB 가 됐다 (2026-10-25). snapshot() 이 만든 이름만 지운다 — 스크린샷 폴더는
    설정에서 아무 폴더로나 바꿀 수 있다. 지운 개수를 돌려준다."""
    cutoff = time.time() - keep_days * 86400
    n = 0
    for f in shot_dir.glob("*.png") if shot_dir.is_dir() else ():
        if not SHOT_NAME.fullmatch(f.name):
            continue
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            pass  # 열려 있는 파일 등 — 다음에 다시
    if n and log:
        log.info(f"오래된 스크린샷 {n}장 정리 ({keep_days}일 지남)")
    return n


class Bot:
    # 뒤에서 키를 보낸 적이 있다 (앞으로 가져올 때 포커스를 한 번 거쳐 준다). 게임 쪽 상태라 Bot 마다가 아니라 함께 쓴다 —
    # 큐는 카드마다 Bot 을 새로 만들어, 앞 카드(어비스)가 뒤에서 키를 보낸 뒤 다음 카드가 이걸 모르고 앞으로 가져와
    # ESC 가 세 번 다 무시됐다 (2026-10-24 21:24, 캐릭터 바꾸기 실패)
    # 켜자마자 True — 지난 실행(재시작 전)이나 다른 도구가 뒤에서 키를 보내 게임이 비활성인 줄 알고 있을 수 있다.
    # 재시작 직후 Space·ESC·X 가 안 먹고 클릭만 먹었다 (2026-10-28 15:50·15:56·18:31 재시작 뒤)
    _posted = True
    _shots_pruned = False

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
        # 게임 서버 패킷 (받기만) — 맵 이동·던전 상태를 화면·CLI 보다 먼저 안다. 꺼져 있으면 쓰지 않는다
        self.packets = (packet_monitor.shared(paths.logs) if cfg["game"].get("packet_watch", True)
                        else packet_monitor.PacketMonitor(paths.logs))
        self.input_mark: int | None = None  # 마지막으로 누르기 직전의 패킷 번호 (아직 누른 적 없으면 None — 지금 상태만 본다)
        self.shot_dir = paths.shots
        self.box = BlackBox()  # 직전 30초 화면·누른 것 — 실패하면 dump_box 로 남긴다
        if not Bot._shots_pruned:  # 프로세스에 한 번 (큐는 카드마다 Bot 을 만든다)
            Bot._shots_pruned = True
            prune_shots(self.shot_dir, self.log)
        self.character: dict | None = None  # 지금 숙제 중인 캐릭터 ({"slot", "name"}), runner 가 설정
        self.watch_weight = False  # 가방이 꽉 찼는지 감시 (숙제 중에만), runner 가 설정
        self._weight_at = 0.0
        self.daily = None  # 오늘 진행 기록 (profile.DailyState), runner 가 설정
        self.also_done: set[str] = set()  # 다른 태스크 안에서 함께 끝낸 태스크 id (runner 가 완료로 기록)
        self.verified = False  # 지금 숙제가 스스로 완료를 확인했다 (runner 가 다시 확인하지 않는다 — 가이드를 두 번 열던 것)
        self.task_id: str | None = None  # 지금 하는 숙제 id, runner 가 설정
        # 이 숙제를 지난번에 어디까지 했나 ({"stage", "at", ...}) — 도중에 끊겼으면 있다. 숙제가 보고 이어 한다
        self.resume: dict | None = None
        self._act_cache: tuple[float, dict | None] | None = None  # (받은 때, CLI get_activity 답) — activity()
        self._cli_checked = 0.0  # CLI 연결 여부를 마지막으로 다시 물은 때
        self.deadline: float | None = None  # 지금 숙제의 시간 상한 (monotonic, runner 가 정함) — check_stop 이 본다
        self.on_step = None  # 단계가 바뀔 때 (step, text) — runner 가 화면(작업 큐 카드·오버레이)에 알리려고 설정
        self._frame: np.ndarray | None = None
        # 게임을 앞으로 가져오지 않고 한다 — 화면은 가려져 있어도 찍고(PrintWindow), 키는 창에 직접 보낸다.
        # 클릭은 그렇게 안 되므로 누를 때만 잠깐 앞으로 가져왔다가 원래 창을 되돌린다 (어비스 반복 중에 쓴다)
        self.background = False
        # 기다리는 게 오래 안 나오면 막는 화면(대화·연출·퀘스트 클리어 확인·화면 터치)을 넘겨 본다 (tasks.content.clear_blockers).
        # 혼자 오래 도는 일(일일 숙제·어비스 반복)만 켠다 — runner·abyss.repeat 가 설정
        self.auto_clear = False
        self._clearing = False
        # 무작위 이벤트 끼어들기 (monitor.interrupts) — 패킷 신호가 오면 기본 동작(check_stop) 안에서 하던 일을 멈추고 넘긴다.
        # _npc_owned: NPC 대화를 태스크가 다루는 중 (npc_talk) · _interrupting: 끼어들기·점검 중 (다시 끼어들지 않는다)
        self.interrupts = not dry_run
        self._npc_owned = 0
        self._interrupting = False
        self._interrupt_off: dict[str, float] = {}
        self.interrupt_spent = 0.0  # 끼어들기에 쓴 시간 합 — 기다리는 쪽이 시간 상한을 그만큼 늘린다
        # 연출의 '장면 넘기기' 를 누르나. 어비스·던전을 도는 동안은 끈다 — 연출은 스스로 끝나고, 누르면 뒤에서 돌던 게임이
        # 앞으로 튀어나온다 (2026-10-25 사용자: "어비스나 던전 돌 동안은 장면 넘기기를 안해도 될 것 같아")
        self.scene_skip = True
        # 출석을 넘긴 게임 날짜 (situation.attendance_due). 시작할 때는 이미 넘긴 것으로 본다 — 접속 단계가 출석을 따로
        # 넘기고, 이 실행 도중 오전 6시를 넘기면 (어비스 반복 등) 그때부터 출석 대사를 넘길 준비를 한다
        from .profile import game_date
        self.attendance_date = game_date()

    def step(self, step: str, text: str = "", **data) -> None:
        """숙제 안의 단계를 오늘 기록에 남긴다 (끊긴 뒤 다시 시작하면 bot.resume 으로 돌아온다).
        step 은 단계 키 (숙제마다 정한 고정 이름 — 이어 하기는 이걸로 판단), text 는 로그·화면용 설명."""
        self.log.info(f"  · [{step}] {text}" if text else f"  · [{step}]")
        if self.daily is not None and self.character and self.task_id:
            self.daily.set_step(self.character["slot"], self.task_id, step, text, **data)
        if self.on_step:
            self.on_step(step, text)  # runner._emit 이 화면 쪽 오류를 삼킨다

    def check_in(self) -> None:
        """작업·숙제를 시작할 때마다 (처음이든 일시정지 뒤 이어 하기든) 지금 상태부터 다시 본다 — 패킷이 기억하는 지난
        상태를 믿고 시작하지 않는다 (PacketMonitor.reconcile). 캐릭터 선택 화면·로딩이면 CLI 가 답하지 않아 그런 상태는
        모름으로 둔다. CLI 연결 여부도 여기서 다시 묻는다 — 처음 한 번 정한 값이 실행 내내 남아 있었다."""
        if self.packets.status != "running":
            return
        self.state.available(refresh=True)
        self._cli_checked = time.monotonic()
        act = self.activity(max_age=0)
        changed = self.packets.reconcile(act)
        if changed or not act:
            self.log.info(f"시작 점검 ({'CLI' if act else 'CLI 응답 없음 → 모름으로'}): "
                          + (", ".join(changed) if changed else "패킷 상태와 같음"))
        else:
            self.log.debug("시작 점검: 패킷 상태와 CLI 가 같음")

    def activity(self, max_age: float = 1.0) -> dict | None:
        """CLI get_activity. 여러 판단이 같은 순간에 따로 묻지 않게 max_age 초 안의 답은 같이 쓴다 (한 번 보는 데
        세 번씩 묻던 것). 받을 때마다 패킷 상태의 오래 남는 값(던전·사냥터·쓰러짐)을 그 답으로 맞춘다 — 가장 믿을
        정보는 CLI (PacketMonitor.merge_cli). 답이 없으면(로딩·캐릭터 선택·끊김) None, 이때 CLI 연결 여부를 가끔 다시 묻는다
        — 처음 정한 값이 실행 내내 남아 끊긴 CLI 를 '로딩 중' 으로 보던 것."""
        now = time.monotonic()
        if self._act_cache and now - self._act_cache[0] <= max_age:
            return self._act_cache[1]
        if not self.state.available():
            if now - self._cli_checked < 30:
                return None
            self._cli_checked = now
            if not self.state.available(refresh=True):
                return None
        act = self.state.activity()
        if act is None and now - self._cli_checked >= 10:
            self._cli_checked = now
            self.state.available(refresh=True)
        self._act_cache = (time.monotonic(), act)
        if act and self.packets.status == "running":
            self.packets.merge_cli(act, now)
        return act

    def resumed_at(self, *steps: str) -> dict | None:
        """지난번에 이 숙제가 steps 중 한 단계에서 끊겼으면 그 기록."""
        r = self.resume
        return r if r and r.get("step") in steps else None

    # ---- 기본 ----
    def check_stop(self) -> None:
        if self.stopper.stopped.is_set():
            raise StopRequested()
        if self.deadline and time.monotonic() > self.deadline:
            # 숙제 하나의 시간 상한 (runner 가 정함). 안쪽 대기마다 상한이 있어도 그것들이 되풀이되면 끝없이 늘어진다
            self.deadline = None
            raise StepTimeout(f"숙제가 시간 상한 안에 끝나지 않음 → {self.snapshot('task_timeout').name}")
        self.check_weight()
        self.check_interrupt()

    def check_interrupt(self) -> None:
        """패킷이 무작위 이벤트(NPC 가 말을 걺·출석)를 알리면 하던 일을 멈추고 점검자가 넘긴 뒤 돌아간다 (monitor.interrupts).
        뒤에서 도는 중(어비스 반복)은 클릭이 게임을 앞으로 가져오므로 하지 않는다 — 거기선 태스크의 점검자가 본다."""
        if self._interrupting or not self.interrupts or not self.packets.ok:
            return
        from .monitor import interrupts
        what = interrupts.pending(self)  # 패킷 상태만 본다 — 0.1초마다 불려도 가볍다
        if not what or time.monotonic() < self._interrupt_off.get(what, 0) or self.behind():
            return
        self._interrupting = True
        t0 = time.monotonic()
        try:
            interrupts.handle(self, what)
        finally:
            self._interrupting = False
            self.interrupt_spent += time.monotonic() - t0

    def interrupt_cooldown(self, what: str, secs: float) -> None:
        self._interrupt_off[what] = time.monotonic() + secs

    @contextmanager
    def npc_talk(self):
        """이 동안 NPC 대화는 태스크 몫 — 끼어들기로 넘기지 않는다 (메뉴가 1~2초 늦게 떠 그 전에 넘기면 놓친다)."""
        self._npc_owned += 1
        try:
            yield
        finally:
            self._npc_owned -= 1

    def npc_owned(self) -> bool:
        return self._npc_owned > 0

    @contextmanager
    def no_interrupt(self):
        """끼어들지 않는 구간 (점검자가 화면을 보고 처리하는 중 등)."""
        prev, self._interrupting = self._interrupting, True
        try:
            yield
        finally:
            self._interrupting = prev

    def check_weight(self, every: float = 20) -> None:
        """watch_weight 가 켜져 있으면 every 초마다 CLI 로 가방 무게를 보고, 꽉 찼으면 Overweight."""
        if not self.watch_weight or time.monotonic() - self._weight_at < every:
            return
        self._weight_at = time.monotonic()
        if why := self.overweight():  # 무게를 넘으면 자동 이동·전투가 멈추므로 던전 안이라도 바로 그만둔다
            raise Overweight(why)

    def overweight(self) -> str | None:
        """가방이 꽉 찼으면 이유 ('가방 무게 300/300'). 패킷(무게가 바뀔 때마다 온다), 모르면 CLI. 모르면 None.
        꽉 차면 자동 이동·전투가 멈추고 보상·채집을 못 받아 숙제가 막힌다."""
        st = self.packets.state
        if self.packets.ok and st.weight is not None and st.max_weight:
            cur, mx = st.weight, st.max_weight
        else:
            inv = self.state.query("get_inventory", timeout=10) if self.state.available() else None
            cur, mx = (inv or {}).get("CurrentInventoryWeight", 0), (inv or {}).get("MaxInventoryWeight", 0)
        return f"가방 무게 {cur:.0f}/{mx:.0f}" if mx and cur >= mx else None

    def wait_packet(self, pred, timeout: float, since: int | None = None) -> bool | None:
        """패킷 상태(self.packets.state)가 pred 를 만족할 때까지. True 만족 / False 시간 초과 /
        None 감시가 꺼졌거나 서버 패킷이 끊김 — 부르는 쪽은 CLI·화면으로 넘어간다.
        since: 이 이벤트 번호(packets.mark · input_mark) 뒤에 한 번이라도 만족했으면 바로 True — 로딩·이동 시작처럼
        금방 지나가는 상태를 기다릴 때. 누르기 전에 찍은 번호를 넘긴다."""
        end = time.monotonic() + timeout
        while True:
            self.check_stop()
            if not self.packets.ok:
                return None
            if pred(self.packets.state) if since is None else self.packets.saw(pred, since):
                return True
            left = end - time.monotonic()
            if left <= 0:
                return False
            self.packets.changed(min(left, 1.0))

    def map_loading(self) -> bool | None:
        """패킷으로 본 맵 로딩 중 여부 (맵을 떠났고 새 맵에 아직 안 들어감). 모르면 None —
        감시가 꺼졌거나 끊김, 또는 감시를 켠 뒤 아직 맵을 옮긴 적이 없음."""
        p = self.packets
        if not p.ok or (p.state.channel is None and not p.state.loading):
            return None
        return p.state.loading

    def is_loading(self) -> bool:
        """맵 로딩 중인가. 패킷이 알면 패킷으로, 모르면 CLI 가 답하지 않는 것으로 (로딩 중엔 get_activity 가 오류)."""
        known = self.map_loading()
        if known is not None:
            return known
        return self.activity(max_age=0.5) is None and self.state.available()  # 답이 없는데 CLI 는 붙어 있다

    def wait_loaded(self, timeout: float) -> bool | None:
        """패킷으로 맵 로딩이 끝날 때까지 (로딩 중이 아니면 바로 True). False 시간 초과, None 모름 → 화면·CLI 로."""
        if self.map_loading() is None:
            return None
        return self.wait_packet(lambda s: not s.loading, timeout)

    def in_game(self) -> bool:
        """게임 안(캐릭터로 접속해 맵에 있음)인가. 패킷이 알면 그것 (로그아웃·입장·맵 진입), 모르면 CLI get_my_info 가 답하는지."""
        p = self.packets
        if p.status == "running" and p.state.in_game is not None:
            return p.state.in_game and not p.state.loading
        return self.state.query("get_my_info") is not None

    def _act(self, act: dict | None) -> dict:
        return act if act is not None else (self.activity() or {})

    def auto_traveling(self, act: dict | None = None) -> bool:
        """자동 이동 중인가. 패킷(자동 이동 시작·끝, 나한테만 옴)이 알면 그것, 모르면 CLI IsAutoTraveling."""
        p = self.packets
        if p.ok and p.state.traveling is not None:
            return p.state.traveling
        return bool(self._act(act).get("IsAutoTraveling"))

    def fast_travel_ok(self, act: dict | None = None) -> bool:
        """지금 빠른 이동(T)을 누를 만한가. 패킷이면 게임이 알려 주는 빠른 이동 가능 상태,
        모르면 CLI 의 자동 이동 중 + 남은 경로 점이 있음."""
        p = self.packets
        if p.ok and p.state.fast_travel_ok is not None and p.state.traveling is not None:
            return p.state.traveling and p.state.fast_travel_ok
        a = self._act(act)
        return bool(a.get("IsAutoTraveling") and a.get("AutoTravelRemainingPositionCount", 0) > 0)

    def in_combat(self, act: dict | None = None) -> bool:
        """전투 중인가. 패킷(내 캐릭터 전투 상태)이 알면 그것, 모르면 CLI IsInCombat."""
        p = self.packets
        if p.ok and p.state.in_combat is not None:
            return p.state.in_combat
        return bool(self._act(act).get("IsInCombat"))

    def dialogue_playing(self, act: dict | None = None) -> bool:
        """NPC 대화 중인가. 패킷(대화 대상)이 알면 그것, 모르면 CLI IsDialoguePlaying."""
        p = self.packets
        if p.ok and (p.state.fresh or p.state.in_dialogue):
            return p.state.in_dialogue
        return bool(self._act(act).get("IsDialoguePlaying"))

    def cutscene_playing(self) -> bool | None:
        """컷신(연출) 재생 중인가 — 패킷(컷신 시작·끝)으로만 안다. 모르면 None (CLI 에는 일반 컷신 상태가 없다)."""
        p = self.packets
        return p.state.cutscene if p.ok and (p.state.fresh or p.state.cutscene) else None

    def skip_button(self, frame=None, skip=()) -> tuple[str, Match] | None:
        """오른쪽 위 넘기기 버튼과 그 종류 ("scene" 연출 / "dialog" 대화). 없으면 None.
        두 버튼은 같은 자리에 '넘기기' 글자가 같고 반투명이라 그림만으로는 헷갈린다 — 밝은 보스 출현 연출의
        '장면 넘기기' 가 '대화 넘기기' 로 잡혀 눌렸다 (2026-10-25 어비스). 그래서 종류는 패킷 → CLI → 그림 순으로 정한다:
        패킷이 컷신 중이면 연출, 대화 중이면 대화, 둘 다 아니면 (대화로 누를 일이 없으니) 연출로 본다."""
        frame = self.frame() if frame is None else frame
        hits = [m for n in (self.ui.get("dialog_skip"), self.ui.get("scene_skip"))
                if n and n not in skip and self.vision.has(n) and (m := self.vision.find(frame, n))]
        if not hits:
            return None
        m = max(hits, key=lambda h: h.score)
        cut = self.cutscene_playing()
        if cut:
            return "scene", m
        p = self.packets
        if cut is not None and p.ok and (p.state.fresh or p.state.in_dialogue):
            return ("dialog" if p.state.in_dialogue else "scene"), m
        act = self.activity()
        if act is not None and "IsDialoguePlaying" in act:
            return ("dialog" if act["IsDialoguePlaying"] else "scene"), m
        return ("scene" if m.name == self.ui.get("scene_skip") else "dialog"), m

    def behind(self) -> bool:
        """뒤에서 도는 중인가 (게임이 앞에 없음) — 클릭하면 게임이 앞으로 튀어나온다."""
        return bool(self.background) and not self.window.is_foreground() and not self.input.dry_run

    def may_skip_scene(self) -> bool:
        """연출의 '장면 넘기기' 를 눌러도 되나 — 어비스·던전 중(scene_skip 꺼짐)이나 뒤에서 도는 중이면 기다린다."""
        return self.scene_skip and not self.behind()

    def is_dead(self, act: dict | None = None) -> bool:
        """내 캐릭터가 쓰러졌나. 패킷 상태가 알면 그것 — CLI 를 물을 때마다 CLI 답으로 맞춰지고 (일어난 신호를 놓쳐도
        CLI 가 살아 있다면 고쳐진다), 패킷이 방금 바꾼 값은 둔다 (부활 창 신호가 CLI IsDead 보다 약 3초 빠르다, death1 실측).
        모르면 CLI. act 는 이미 받아 둔 get_activity 결과 (없으면 묻는다 — 물으면서 패킷 상태도 맞춰진다)."""
        p = self.packets
        if act is None:
            act = self.activity() or {}
        if p.ok and p.state.dead is not None:
            return p.state.dead
        return bool(act.get("IsDead"))

    def environment(self, max_age: float = 3.0) -> dict | None:
        """CLI get_current_environment (장소 이름 등). max_age 초 안의 답은 같이 쓴다."""
        now = time.monotonic()
        c = getattr(self, "_env_cache", None)
        if c and now - c[0] <= max_age:
            return c[1]
        env = self.state.query("get_current_environment") if self.state.available() else None
        self._env_cache = (now, env if isinstance(env, dict) else None)
        return self._env_cache[1]

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
        if self.background and not self.input.dry_run:
            img = self.screen.grab_behind()
            if img is not None:
                self._frame = img
                self.box.frame(img)
                return img
        # 화면을 그대로 캡처하므로 다른 창(터미널, 알림 등)이 위에 있으면 인식이 틀어진다
        self.ensure_focus()
        self._frame = self.screen.grab()
        self.box.frame(self._frame)
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
        start = time.monotonic()
        end, checked, spent = start + timeout, start, self.interrupt_spent
        while True:
            frame = self.frame()
            for n in names:
                m = self.vision.find(frame, n)
                if m:
                    return m
            now = time.monotonic()
            end, spent = end + self.interrupt_spent - spent, self.interrupt_spent  # 끼어들기에 쓴 시간만큼 더 기다린다
            if now > end:
                raise StepTimeout(f"{timeout:.0f}s 안에 {names} 중 아무것도 나타나지 않음")
            if self.auto_clear and now - start > 4 and now - checked > 3:
                checked = now
                self.clear_blockers(skip=names, ocr=now - start > 8)
            self.sleep(interval)

    def clear_blockers(self, skip=(), ocr: bool = False) -> str | None:
        """막는 화면 하나를 넘긴다 (tasks.content.clear_blockers). 넘겼으면 로그에 남긴다."""
        if self._clearing:
            return None
        from .tasks.content import clear_blockers
        self._clearing = True
        try:
            what = clear_blockers(self, skip, ocr)
        finally:
            self._clearing = False
        if what:
            self.log.info(f"막는 화면 넘김: {what}")
            self.sleep(1.0, 1.4)
        return what

    def wait(self, name: str, timeout: float = 10, interval: float = 0.4) -> Match:
        return self.wait_any([name], timeout, interval)

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
        if self.input.dry_run or (self.window.is_foreground() and not self._posted):
            return
        if self._posted:  # 앞에 있어도 — 비활성인 줄 아는 채로 앞에 있을 수 있다
            # 뒤에서 키를 보낸 뒤(post_key) 처음 앞으로 가져오면 게임이 그 활성화를 놓쳐 키·클릭을 무시했다
            # (2026-10-23). 앞으로 → 다른 창(작업 표시줄) → 다시 앞으로, 두 번째 활성화부터 받는다
            self.window.focus()
            self.sleep(1.0)
            self.window.give_back(ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None))
            self.sleep(1.0)
            Bot._posted = False
        self.window.focus()
        self.sleep(0.8)
        self.input.key("shift")
        self.sleep(0.3)

    def click_xy(self, x: int, y: int) -> bool:
        """기준(1920x1080) 좌표를 누른다. 게임 해상도가 달라도 비율대로 실제 자리를 누른다 (Screen.to_screen).
        눌렀으면 True. 게임 창을 앞으로 못 가져오면 누르지 않고 False — 그대로 누르면 다른 창을 누른다. 조용히 넘기면
        부른 쪽은 눌렀다고 믿으므로, 연달아 SKIP_LIMIT 번 못 누르면 StepTimeout 으로 알린다 (구조 점검 2026-10-30, 뒤에서 도는 반복은 빼고)."""
        self.input_mark = self.packets.mark()  # 누르기 직전 패킷 번호 — wait_packet(since=) 로 '누른 뒤' 를 본다
        self.box.input(f"클릭 ({x}, {y})")
        if self.background and not self.window.is_foreground() and not self.input.dry_run:
            prev = ctypes.windll.user32.GetForegroundWindow()
            self.ensure_focus()
            if not self.window.is_foreground():
                # 사람이 다른 창에서 입력 중이면 Windows 가 앞으로 가져오기를 막는다 — 그대로 누르면 그 창을 누른다
                # (2026-10-28 레이드 나가기 4번 헛클릭). 이번 클릭은 건너뛰고 부른 쪽이 다시 시도하게 둔다
                return self._click_skipped(x, y)
            self.input.click(*self.screen.to_screen(x, y))
            self.sleep(0.3)
            self.window.give_back(prev)
            self.pause()
            self._skipped_clicks = 0
            return True
        self.ensure_focus()
        if not self.window.is_foreground() and not self.input.dry_run:
            return self._click_skipped(x, y)
        self.input.click(*self.screen.to_screen(x, y))
        self.pause()
        self._skipped_clicks = 0
        return True

    SKIP_LIMIT = 5

    def _click_skipped(self, x: int, y: int) -> bool:
        n = self._skipped_clicks = getattr(self, "_skipped_clicks", 0) + 1
        self.log.warning(f"게임 창을 앞으로 가져오지 못해 ({x}, {y}) 클릭을 건너뜀 ({n}/{self.SKIP_LIMIT})")
        # 뒤에서 도는 반복(어비스·레이드)은 사람이 다른 창을 쓰는 게 정상이라 기다렸다 다시 누르게 둔다
        if n >= self.SKIP_LIMIT and not self.background:
            self._skipped_clicks = 0
            raise StepTimeout(f"게임 창을 앞으로 가져오지 못해 {n}번 연달아 누르지 못함 (다른 창이 입력을 잡고 있음?)"
                              f" → {self.snapshot('click_skipped').name}")
        self.sleep(2.0)
        return False

    def hover_off(self, x: int = 300, y: int = 540) -> None:
        """커서를 버튼이 없는 자리(왼쪽 가운데)로 치운다. 누른 버튼 위에 커서가 남아 있으면 마우스를 올린 효과로
        그림이 커져 템플릿이 안 맞는다 (2026-10-24 퀘스트 창 아르바이트 탭 0.85)."""
        self.input.move(*self.screen.to_screen(x, y))

    def scroll(self, x: int, y: int, notches: int) -> None:
        """기준 좌표 (x, y) 에서 휠. notches > 0 위로, < 0 아래로."""
        self.ensure_focus()
        self.input.scroll(*self.screen.to_screen(x, y), notches)

    def drag(self, x1: int, y1: int, x2: int, y2: int, steps: int = 20) -> None:
        """기준 좌표 (x1, y1) → (x2, y2) 로 끈다 (지도 이동 등)."""
        self.ensure_focus()
        self.input.drag(*self.screen.to_screen(x1, y1), *self.screen.to_screen(x2, y2), steps=steps)

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
        self.input_mark = self.packets.mark()  # 누르기 직전 패킷 번호 (click_xy 와 같음)
        self.box.input(f"키 {key}")
        if self.background and not self.window.is_foreground() and not self.input.dry_run:
            post_key(self.window.hwnd, key)
            Bot._posted = True
            self.pause()
            return
        self.ensure_focus()
        if not self.window.is_foreground() and not self.input.dry_run:
            # 앞으로 못 가져왔으면 SendInput 키는 맨 앞의 다른 창으로 간다 — 창에 직접 보낸다
            self.log.warning(f"게임 창을 앞으로 가져오지 못함 → 키 {key} 를 창에 직접 보냄")
            post_key(self.window.hwnd, key)
            Bot._posted = True
            self.pause()
            return
        self.input.key(key)
        self.pause()

    # ---- 복구 ----
    def dismiss_popups(self, max_n: int = 6) -> int:
        """남은 창(공지·새 이벤트 창·스텔라 픽·퀘스트 완료 확인 …)을 점검자가 닫는다. NPC 대화는 건드리지 않는다. 닫은 개수."""
        from . import monitor
        mon, ctx = monitor.of(self), monitor.Ctx("popups", "남은 창 닫기", talk=False)
        closed = 0
        for _ in range(max_n):
            seen = mon.check(ctx, guard=False)
            if not seen.done or seen.done in monitor.WAITS:
                break
            closed += 1
            self.sleep(0.4, 0.6)
        return closed

    def run_limited(self) -> bool:
        """게임이 '너무 오랫동안 실행되고 있습니다 · 재시작' 창을 띄웠나 (AI 에이전트 연속 실행 제한).
        CLI 가 그 오류를 한 번이라도 줬으면 그것, 아니면 화면 위쪽 글자를 읽는다 (실패했을 때만 부른다 — OCR 이 무겁다).
        이 창은 '종료' 하나뿐이라 누르면 게임이 꺼진다 → 누르지 않고 사람에게 넘긴다."""
        if self.cli.run_limited:
            return True
        from . import ocr
        try:
            texts = "".join(t for t, _, _ in ocr.find_texts(self.frame(), (0, 0, 1920, 600))).replace(" ", "")
        except Exception:  # noqa: BLE001 — 확인 실패가 실패 처리를 막으면 안 된다
            return False
        return "오랫동안실행" in texts or "재시작해주세요" in texts

    def at_main(self) -> bool:
        """필드 메인 화면인가 — 패킷이 맵 로딩 중이라고 하면 아니다 (로딩 화면 직전·직후 HUD 가 잠깐 보인다).
        '창이 하나도 안 열림' 은 패킷에 없어서 그 다음은 HUD 그림으로 본다."""
        if self.map_loading() or self.packets.at_charselect():
            return False
        return self.exists(self.ui["main_hud"])

    def no_food(self, look: bool = True) -> bool:
        """이 캐릭터가 오늘 먹을 음식이 없나. 배고픈데 음식이 없으면 좌상단에 빨간 원 + 식기 아이콘이 뜬다.
        그 상태에서 B 를 누르면 제작 창이 열리므로, 한 번 보이면 오늘 기록해 두고 먹기를 시도하지 않는다.
        look: 지금 화면도 본다 (메인 화면일 때만 의미가 있다)."""
        slot = self.character["slot"] if self.character else None
        if self.daily is not None and slot is not None and self.daily.flag(slot, "no_food"):
            return True
        name = self.ui.get("food_none")
        if not look or not name or not self.vision.has(name) or not self.exists(name):
            return False
        self.log.info("음식 없음 표시 → 오늘은 음식 먹기를 하지 않음")
        if self.daily is not None and slot is not None:
            self.daily.set_flag(slot, "no_food")
        return True

    def eat_if_hungry(self) -> bool:
        """메인 화면으로 돌아올 때마다 본다: 좌상단 음식 아이콘의 'B' 표시가 보이면 (배고픔) B 를 눌러 음식을 먹는다.
        숙제로서 먹는 건 캐릭터마다 하루 run.food_max 번까지 (일일 미션 '음식 2개 먹기' 를 채우면 충분하다).
        그만큼 먹었거나 음식이 없으면 (no_food) 보지도 누르지도 않는다. 일일 미션 쪽에서는 음식을 먹지 않는다."""
        name = self.ui.get("food_b")
        if not name or not self.vision.has(name):
            return False
        slot = self.character["slot"] if self.character else None
        tracked = self.daily is not None and slot is not None
        if tracked and self.daily.count(slot, "food") >= self.cfg["run"].get("food_max", 2):
            return False
        if time.monotonic() < getattr(self, "_eat_after", 0.0):
            return False  # 방금 먹었거나 못 먹었다 — 한동안 다시 누르지 않는다
        if self.no_food(look=False) or not self.exists(name) or self.no_food():
            return False
        mark = self.packets.mark()
        self.key("b")
        # 패킷: 먹으면 포만감이 온다. 안 오면 못 먹은 것 (어비스 판 안에서 6초마다 3분 넘게 B 만 누른 일 — 2026-10-27).
        # 먹었어도 'B' 표시가 바로 안 사라질 수 있어 먹은 뒤에도 EAT_GAP 동안은 다시 누르지 않는다
        got = self.packets.wait("char.satiety", 4, after=mark) if self.packets.ok else None
        self._eat_after = time.monotonic() + EAT_GAP
        if self.packets.ok and got is None:
            self.log.warning(f"배고픔 표시 → B 를 눌렀지만 먹지 못함 (포만감 패킷 없음) → {EAT_GAP:.0f}초 뒤 다시")
            return False
        n = self.daily.bump(slot, "food") if tracked else 0
        full = f" · 포만감 {got.vals.get('satiety')}" if got is not None else ""
        self.log.info(f"배고픔 표시 → 음식 먹기 (B){f' — 오늘 {n}번째' if tracked else ''}{full}")
        self.sleep(1.5, 2)
        return True

    def to_main(self, tries: int = 10) -> None:
        """ESC 와 팝업 닫기를 반복해서 필드 메인 화면으로 돌아온다. 돌아오면 배고픔도 확인한다."""
        exit_dialog = self.ui["exit_dialog"]
        wait_end = time.monotonic() + 120  # 로딩·연출을 기다리는 건 tries 와 따로 (그 동안은 누르는 게 없다)
        n = 0
        while n < tries:
            if self.at_main():
                self.eat_if_hungry()
                return
            # 타이틀·캐릭터 선택 화면에서 ESC 를 누르면 뒤로 가다가 '게임을 종료하시겠습니까?' 가 뜬다
            if self.packets.at_charselect() or self.exists(self.ui["title_start"]) or self.exists(self.ui["charselect_title"]):
                raise StepTimeout("게임 밖(타이틀/캐릭터 선택) 화면이라 메인으로 돌아갈 수 없음")
            waiting = time.monotonic() < wait_end
            if waiting and self.map_loading():  # 패킷: 맵을 옮기는 중 — ESC 를 누르지 않고 기다린다
                self.wait_loaded(min(self.cfg["timing"]["loading"], wait_end - time.monotonic()))
                continue
            # 출석 대사·대화·연출·퀘스트 완료 '확인'·화면 터치는 점검자가 (상황 판단을 태스크마다 따로 두지 않는다).
            # 연출은 스스로 끝나길 기다리되, 120초가 넘으면 넘기기를 누른다
            from . import monitor
            seen = monitor.of(self).check(monitor.Ctx("to_main"), guard=False)
            if seen.done == "연출 대기" and not waiting and (hit := self.skip_button()):
                self.click(hit[1])
                n += 1
                continue
            if seen.done:
                n += seen.done not in monitor.WAITS or not waiting  # 기다림도 120초 뒤엔 횟수에 넣는다
                self.sleep(0.6, 1.0)
                continue
            n += 1
            if self.vision.has(exit_dialog) and self.exists(exit_dialog):
                self.key("esc")  # '취소' (ESC 배지) — 단축키로
                continue
            if self.exists(self.ui["menu_quit"]):  # 메뉴(ESC)가 열려 있음 → ESC 로 닫고 애니메이션 대기
                self.key("esc")
                self.sleep(1.2, 1.6)
                continue
            # 템플릿이 안 맞는 퀘스트 완료 창 — ESC 로는 안 닫혀 캐릭터 바꾸기 등이 멈췄다 (2026-10-24 사용자) → 글자로도
            if monitor.of(self).check(monitor.Ctx("to_main"), guard=False, ocr=True).done:
                continue
            self.key("esc")
            self.sleep(0.8, 1.3)
        if not self.at_main():
            # 화면을 남긴다 — 어비스 수리 가던 길에 이것만 남고 무슨 화면이었는지 몰랐다 (2026-10-28 다른 PC 로그)
            raise StepTimeout(f"메인 화면으로 돌아오지 못함 → {self.snapshot('to_main').name}")

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
                # 메인 HUD 가 보이는 채로 뜬 퀘스트 완료 창이 ESC 를 먹는다 (2026-10-24 어비스 3판 뒤 캐릭터 바꾸기)
                self.clear_blockers(ocr=True)
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
            self.key("space")  # 타이틀 '게임 시작' (Space 배지)
            self.wait(ui["charselect_title"], timeout=60)
        self.state.available(refresh=True)

    def dump_box(self, tag: str) -> str:
        """블랙박스(직전 30초 화면·누른 것·패킷)를 스크린샷 폴더에 남기고 폴더 이름을 돌려준다 (못 남기면 "")."""
        try:
            img = self.screen.grab_behind() if self.background else None
            last = img if img is not None else self.screen.grab()
        except RuntimeError:  # 게임 꺼짐 — 들고 있던 것만
            last = None
        d = self.box.dump(self.shot_dir, tag, self.packets, last)
        return d.name if d else ""

    def snapshot(self, tag: str) -> Path:
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        path = self.shot_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}.png"
        try:
            # 뒤에서 돌 때는 게임 창만 (화면을 찍으면 위에 있는 다른 창이 찍힌다 — 2026-10-23 어비스 실패 사진)
            img = self.screen.grab_behind() if self.background else None
            ok, buf = cv2.imencode(".png", img if img is not None else self.screen.grab())
        except RuntimeError:  # 게임 창이 없음 (꺼짐) — 실패 기록 중에 또 터지지 않게
            return path.with_name(path.stem + "_게임꺼짐")
        if ok:
            buf.tofile(str(path))
        return path
