"""게임 하나와의 연결 (GameSession) — 창·화면 캡처·입력·그림 찾기(Vision)·CLI·패킷. 프로세스에 게임이 하나라 여러 작업(Bot)이
같이 쓸 수 있다. 작업 하나의 문맥(설정·캐릭터·단계 기록·멈춤·뒤에서 돌기·끼어들기 …)과 기다림은 Bot 이 쥔다 (mabi/bot.py).

여기 있는 것은 기다리지 않는다 — 멈춤 키·숙제 시간 상한·끼어들기를 보며 쉬는 일(sleep·check_stop)은 작업의 몫이라,
누르기 전후의 쉬기·포커스 옮기기·건너뛴 클릭 세기는 Bot 이 하고 여기서는 한 번 찍고·한 번 누르고·한 번 묻는다.
"""
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from . import judge, packet_monitor
from .blackbox import BlackBox
from .connector import Connector
from .digits import DigitReader
from .game_state import Activity, GameState
from .inputs import Input, post_key
from .screen import Screen
from .vision import Vision
from .window import GameWindow

SHOT_KEEP_DAYS = 7
SHOT_NAME = re.compile(r"\d{8}_\d{6}_.+\.png")  # snapshot() 이 붙이는 이름
LOADING_DOUBT = 20.0  # 패킷 로딩이 이보다 길면 새 맵 진입을 놓쳤나 CLI 로 본다 (map_loading)


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


class GameSession:
    # 뒤에서 키를 보낸 적이 있다 (앞으로 가져올 때 포커스를 한 번 거쳐 준다). 게임 쪽 상태라 작업마다가 아니라 함께 쓴다 —
    # 큐는 카드마다 Bot 을 새로 만들어, 앞 카드(어비스)가 뒤에서 키를 보낸 뒤 다음 카드가 이걸 모르고 앞으로 가져와
    # ESC 가 세 번 다 무시됐다 (2026-10-24 21:24, 캐릭터 바꾸기 실패)
    # 켜자마자 True — 지난 실행(재시작 전)이나 다른 도구가 뒤에서 키를 보내 게임이 비활성인 줄 알고 있을 수 있다.
    # 재시작 직후 Space·ESC·X 가 안 먹고 클릭만 먹었다 (2026-10-28 15:50·15:56·18:31 재시작 뒤)
    posted = True
    _shots_pruned = False

    def __init__(self, cfg: dict, paths, dry_run: bool = False, cli=None):
        self.cfg = cfg  # 연결을 만든 설정 — 작업마다 다른 설정은 Bot.cfg 에서 읽는다
        self.paths = paths
        self.dry_run = dry_run
        self.log = logging.getLogger("mabi")
        self.window = GameWindow(cfg["game"]["window_title"])
        self.screen = Screen(self.window)
        v = cfg["vision"]
        self.vision = Vision(paths.templates, v["threshold"], v["roi_margin"])
        self.input = Input(cfg["input"]["jitter_px"], dry_run=dry_run, log=self.log)
        self.digits = DigitReader(paths.templates / "digits", cfg["counters"]["white_threshold"])
        self.cli = cli or Connector(lambda: cfg["game"].get("cli_path"), self.log)
        self.state = GameState(self.cli, self.log)
        # 게임 서버 패킷 (받기만) — 맵 이동·던전 상태를 화면·CLI 보다 먼저 안다. 꺼져 있으면 쓰지 않는다
        self.packets = (packet_monitor.shared(paths.logs) if cfg["game"]["packet_watch"]
                        else packet_monitor.PacketMonitor(paths.logs))
        self.shot_dir = paths.shots
        self.box = BlackBox()  # 직전 30초 화면·누른 것 — 실패하면 dump_box 로 남긴다
        if not GameSession._shots_pruned:  # 프로세스에 한 번
            GameSession._shots_pruned = True
            prune_shots(self.shot_dir, self.log)
        self._act_cache: tuple[float, dict | None] | None = None  # (받은 때, CLI get_activity 답) — activity()
        self._env_cache: tuple[float, dict | None] | None = None  # (받은 때, get_current_environment 답) — environment()
        self.cli_checked = 0.0  # CLI 연결 여부를 마지막으로 다시 물은 때
        # 이 연결로 캐릭터를 골라 게임에 들어간 때 (monotonic, 0 = 모름 — 리모콘을 켜기 전에 접속했거나 사람이 접속).
        # 게임 다시 켜기 카드와 숙제가 같은 연결을 쓰므로, 다시 켠 직후 숙제도 접속한 지 얼마 안 됐음을 안다 (공물 퀘스트)
        self.login_at = 0.0

    @staticmethod
    def shape(cfg: dict, paths, dry_run: bool = False) -> tuple:
        """연결을 만들 때 쓰는 설정 값들 (이 밖의 설정은 연결이 읽지 않는다). 같으면 이미 있는 연결을 그대로 쓸 수 있다 (fits)."""
        g, v = cfg["game"], cfg["vision"]
        return (str(paths.templates), str(paths.logs), str(paths.shots), g["window_title"], g.get("cli_path"),
                bool(g["packet_watch"]), v["threshold"], v["roi_margin"], cfg["input"]["jitter_px"],
                cfg["counters"]["white_threshold"], dry_run)

    def fits(self, cfg: dict, paths, dry_run: bool = False) -> bool:
        """이 설정으로 만들어도 지금 연결과 같은가 — 설정에서 창 제목·CLI 경로·그림 문턱 등을 바꾸면 새로 만든다."""
        return self.shape(self.cfg, self.paths, self.dry_run) == self.shape(cfg, paths, dry_run)

    # ---- 찍기·누르기 (한 번씩 — 쉬기·포커스는 Bot) ----
    def capture(self, behind: bool = False) -> np.ndarray | None:
        """화면 한 장 (1920x1080 기준). behind: 가려져 있어도 게임 창만 (PrintWindow) — 내려가 있으면 None.
        찍은 것은 블랙박스에 남긴다."""
        img = self.screen.grab_behind() if behind else self.screen.grab()
        if img is not None:
            self.box.frame(img)
        return img

    def mark_input(self, what: str) -> int:
        """누르기 직전: 블랙박스에 적고 지금 패킷 번호를 돌려준다 (Bot.input_mark — wait_packet(since=) 로 '누른 뒤' 를 본다)."""
        mark = self.packets.mark()
        self.box.input(what)
        return mark

    def click_at(self, x: int, y: int) -> None:
        """기준(1920x1080) 좌표를 지금 해상도의 실제 자리로 바꿔 누른다."""
        self.input.click(*self.screen.to_screen(x, y))

    def press_at(self, x: int, y: int, seconds: float) -> None:
        self.input.press(*self.screen.to_screen(x, y), seconds)

    def move_to(self, x: int, y: int) -> None:
        self.input.move(*self.screen.to_screen(x, y))

    def scroll_at(self, x: int, y: int, notches: int) -> None:
        self.input.scroll(*self.screen.to_screen(x, y), notches)

    def drag_between(self, x1: int, y1: int, x2: int, y2: int, steps: int) -> None:
        self.input.drag(*self.screen.to_screen(x1, y1), *self.screen.to_screen(x2, y2), steps=steps)

    def send_key(self, key: str) -> None:
        """앞에 있는 창으로 키 (SendInput)."""
        self.input.key(key)

    def post_key(self, key: str) -> None:
        """게임 창에 직접 키 (뒤에 있어도). 그 뒤로 앞으로 가져올 때 포커스를 한 번 거쳐야 한다 (posted)."""
        post_key(self.window.hwnd, key)
        GameSession.posted = True

    def snapshot(self, tag: str, behind: bool = False) -> Path:
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        path = self.shot_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}.png"
        try:
            # 뒤에서 돌 때는 게임 창만 (화면을 찍으면 위에 있는 다른 창이 찍힌다 — 2026-10-23 어비스 실패 사진)
            img = self.screen.grab_behind() if behind else None
            ok, buf = cv2.imencode(".png", img if img is not None else self.screen.grab())
        except RuntimeError:  # 게임 창이 없음 (꺼짐) — 실패 기록 중에 또 터지지 않게
            return path.with_name(path.stem + "_게임꺼짐")
        if ok:
            buf.tofile(str(path))
        return path

    def dump_box(self, tag: str, behind: bool = False) -> str:
        """블랙박스(직전 30초 화면·누른 것·패킷)를 스크린샷 폴더에 남기고 폴더 이름을 돌려준다 (못 남기면 "")."""
        try:
            img = self.screen.grab_behind() if behind else None
            last = img if img is not None else self.screen.grab()
        except RuntimeError:  # 게임 꺼짐 — 들고 있던 것만
            last = None
        d = self.box.dump(self.shot_dir, tag, self.packets, last)
        return d.name if d else ""

    # ---- 게임 상태 읽기 (패킷이 알면 패킷, 모르면 CLI) ----
    def activity(self, max_age: float = 1.0) -> dict | None:
        """CLI get_activity. 여러 판단이 같은 순간에 따로 묻지 않게 max_age 초 안의 답은 같이 쓴다 (한 번 보는 데
        세 번씩 묻던 것). 받을 때마다 패킷 상태의 오래 남는 값(던전·사냥터·쓰러짐)을 그 답으로 맞춘다 — 가장 믿을
        정보는 CLI (PacketMonitor.merge_cli). 답이 없으면(로딩·캐릭터 선택·끊김) None, 이때 CLI 연결 여부를 가끔 다시 묻는다
        — 처음 정한 값이 실행 내내 남아 끊긴 CLI 를 '로딩 중' 으로 보던 것."""
        now = time.monotonic()
        if self._act_cache and now - self._act_cache[0] <= max_age:
            return self._act_cache[1]
        if not self.state.available():
            if now - self.cli_checked < 30:
                return None
            self.cli_checked = now
            if not self.state.available(refresh=True):
                return None
        act = self.state.activity()
        if act is None and now - self.cli_checked >= 10:
            self.cli_checked = now
            self.state.available(refresh=True)
        self._act_cache = (time.monotonic(), act)
        if act and self.packets.status == "running":
            self.packets.merge_cli(act, now)
        return act

    def environment(self, max_age: float = 3.0) -> dict | None:
        """CLI get_current_environment (장소 이름 등). max_age 초 안의 답은 같이 쓴다."""
        now = time.monotonic()
        c = self._env_cache
        if c and now - c[0] <= max_age:
            return c[1]
        env = self.state.query("get_current_environment") if self.state.available() else None
        self._env_cache = (now, env if isinstance(env, dict) else None)
        return self._env_cache[1]

    def _act_state(self, act: dict | None) -> Activity:
        """CLI get_activity 를 읽은 것 (game_state.Activity). act 는 이미 받아 둔 답 — 없으면 묻는다 (activity)."""
        return Activity.of(act if act is not None else self.activity())

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

    def map_loading(self) -> bool | None:
        """패킷으로 본 맵 로딩 중 여부 (맵을 떠났고 새 맵에 아직 안 들어감). 모르면 None —
        감시가 꺼졌거나 끊김, 또는 감시를 켠 뒤 아직 맵을 옮긴 적이 없음.
        로딩이 LOADING_DOUBT 초 넘게 가면 CLI 와 맞춰 본다 — 흐름이 끊겨 맵 진입 패킷을 놓치면 로딩 중이 그대로 남는다.
        CLI 가 답하면(로딩 중엔 답하지 않는다) 게임 안이니 패킷은 모르는 것(None)으로 → 부르는 쪽이 CLI·화면으로."""
        p = self.packets
        if not p.ok or (p.state.channel is None and not p.state.loading):
            return None
        if not p.state.loading or time.monotonic() - p.state.loading_at < LOADING_DOUBT:
            return p.state.loading
        v = judge.decide(self, "로딩", [
            ("CLI 응답", lambda: False if self.activity(max_age=2.0) is not None else None),
            ("패킷", lambda: True),
        ])
        return True if v.value else None

    def is_loading(self) -> bool:
        """맵 로딩 중인가. 패킷이 알면 패킷으로, 모르면 CLI 가 답하지 않는 것으로 (로딩 중엔 get_activity 가 오류)."""
        known = self.map_loading()
        if known is not None:
            return known
        return self.activity(max_age=0.5) is None and self.state.available()  # 답이 없는데 CLI 는 붙어 있다

    def in_game(self) -> bool:
        """게임 안(캐릭터로 접속해 맵에 있음)인가. 패킷이 알면 그것 (로그아웃·입장·맵 진입), 모르면 CLI get_my_info 가 답하는지."""
        p = self.packets
        if p.status == "running" and p.state.in_game is not None:
            return p.state.in_game and not p.state.loading
        return self.state.query("get_my_info") is not None

    def auto_traveling(self, act: dict | None = None) -> bool:
        """자동 이동 중인가. 패킷(자동 이동 시작·끝, 나한테만 옴)이 알면 그것, 모르면 CLI IsAutoTraveling."""
        p = self.packets
        if p.ok and p.state.traveling is not None:
            return p.state.traveling
        return self._act_state(act).traveling

    def fast_travel_ok(self, act: dict | None = None) -> bool:
        """지금 빠른 이동(T)을 누를 만한가. 패킷이면 게임이 알려 주는 빠른 이동 가능 상태,
        모르면 CLI 의 자동 이동 중 + 남은 경로 점이 있음."""
        p = self.packets
        if p.ok and p.state.fast_travel_ok is not None and p.state.traveling is not None:
            return p.state.traveling and p.state.fast_travel_ok
        a = self._act_state(act)
        return a.traveling and a.travel_left > 0

    def in_combat(self, act: dict | None = None) -> bool:
        """전투 중인가. 패킷(내 캐릭터 전투 상태)이 알면 그것, 모르면 CLI IsInCombat."""
        p = self.packets
        if p.ok and p.state.in_combat is not None:
            return p.state.in_combat
        return self._act_state(act).combat

    def dialogue_playing(self, act: dict | None = None) -> bool:
        """NPC 대화 중인가. 패킷(대화 대상)이 알면 그것, 모르면 CLI IsDialoguePlaying."""
        p = self.packets
        if p.ok and (p.state.fresh or p.state.in_dialogue):
            return p.state.in_dialogue
        return self._act_state(act).dialogue

    def cutscene_playing(self) -> bool | None:
        """컷신(연출) 재생 중인가 — 패킷(컷신 시작·끝)으로만 안다. 모르면 None (CLI 에는 일반 컷신 상태가 없다)."""
        p = self.packets
        return p.state.cutscene if p.ok and (p.state.fresh or p.state.cutscene) else None
