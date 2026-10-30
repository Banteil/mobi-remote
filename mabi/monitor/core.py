"""점검자 — 태스크가 '이 동작을 하겠다/했다' 고 알리면 지금 상황을 보고 판단한다 (2026-10-26 사용자 설계).

태스크는 자기가 아는 순서대로 동작을 요청만 하고, 상황 판단과 대응은 여기 한곳에 둔다.
태스크마다 if 를 따로 가지던 때는 한 태스크에서 고친 것(작별 화면·출석)이 다른 태스크에 없어 같은 화면에서 또 막혔다.

  check(ctx)  지금 상황을 보고 막는 것이 있으면 담당 처리기(handlers)로 한 걸음 처리한다.
              결과 Seen: done(한 일) · finish(이 일은 여기서 끝) · 둘 다 없으면 태스크 몫 (메인 화면 등)
  settle(ctx) 처리할 것이 없어질 때까지 check — 퀘스트 창(J)·ESC 를 누르기 전에 남은 대화·창을 끝까지 처리한다
  act(...)    동작 전에 settle → 동작 → 기대한 결과가 시간 안에 나오나. 안 나오면 다시 (tries 번까지)
  clear(...)  막는 화면 하나만 넘긴다 (기다리는 중에 끼어든 창 — content.clear_blockers 가 이걸 부른다)

헛돌기 방지: 같은 처리가 화면이 그대로인 채 same_limit 번 거듭되거나, 모르는 상황이 unknown_limit 초 이어지면
(메인 화면으로 한 번 돌려 본 뒤에도) Stuck. 판단과 동작은 logs/acts/날짜.jsonl 에 한 줄씩 남긴다.
"""
import json
import time
from pathlib import Path

import numpy as np

from . import detect as d, handlers as h
from .handlers import Finish


class Stuck(RuntimeError):
    """점검자가 보기에 같은 자리에서 헛돌고 있다."""


class Ctx:
    """지금 하는 일. task 는 숙제 id, what 은 그 안의 일 (아르바이트 제목 등 — 로그용).
    menus: NPC 메뉴(수락·결과 보고)·전달 창·던전 창까지 다룬다. job: 채집·제작·가공 창까지 (menus 포함). talk: NPC 대화를 넘긴다.
    finish_on: 이 상황이면 이 일은 끝 {상황: 결과}. decide: 태스크만 아는 판단 {상황: fn(bot, ctx, seen) -> 끝낼 이유|None}.
    note: (단계 키, 설명) — 태스크의 단계 기록 (이어 하기용).
    reward: 보상 화면을 다룬다 (던전·사냥터를 끝내는 중) — extra_loot 추가 루팅 횟수, again 이 보이면 누르고 끝.
    revive: 쓰러지면 '여기서 부활' (못 하면 끝 'dead'). 끄면 쓰러짐은 태스크 몫.
    choose: NPC 선택지 중 이 낱말이 든 것을 누른다 (요일 던전 임무 게시판 · 대장간 '수리' — 원하는 게 없으면 누르지 않고 기다린다).
      choose_region 은 선택지 버튼 줄 (gamedata 영역 이름).
    leave: NPC 대화를 마치는 중 — 메뉴는 고르지 않고 ESC('대화 종료'), 작별 인사 등 대사는 넘긴다.
    alter: 가공해도 되는 물품 이름 (짧은 가공 — 아르바이트가 정한다). 비어 있으면 가공 창은 건너뛴다."""

    def __init__(self, task: str, what: str = "", job: bool = False, menus: bool | None = None, talk: bool = True,
                 finish_on=None, decide=None, note=None, keep_dungeon_window: bool = False,
                 reward: bool = False, extra_loot: int = 0, again: str | None = None, revive: bool = False,
                 choose: str | None = None, choose_region: str = "board_choices", leave: bool = False,
                 alter=()):
        self.task, self.what, self.job, self.talk = task, what, job, talk
        self.menus = job if menus is None else menus
        self.finish_on, self.decide = finish_on or {}, decide or {}
        self._note, self.keep_dungeon_window = note, keep_dungeon_window
        self.reward, self.extra_loot, self.again = reward, extra_loot, again
        self.revive, self.choose, self.choose_region, self.leave = revive, choose, choose_region, leave
        self.alter = tuple(alter)
        self.n: dict[str, int] = {}
        self.talked = False  # NPC 대화를 마쳤다 (대화 조건을 채워도 게임이 다음 걸음으로 가지 않는다)
        self.events: set[str] = set()

    def note(self, key: str, stage: str) -> None:
        if self._note:
            self._note(key, stage)

    def event(self, name: str) -> None:
        self.events.add(name)

    def take(self, name: str) -> bool:
        """처리기가 남긴 일(채집 시작·확인 누름 등)이 있었나 — 한 번 보면 지운다."""
        if name in self.events:
            self.events.discard(name)
            return True
        return False


# 기다리는 처리 — 화면이 그대로여도 헛도는 게 아니다 (각자 시간 상한이 있다)
WAITS = {"로딩 대기", "연출 대기", "전달 물품 채워지길 기다림", "선택지 기다림", "출석 대사 기다림"}
QUIET = WAITS | {"대사 넘김", "출석 대사 넘김"}  # 로그(INFO)에 남기지 않는 흔한 처리 (기록 파일에는 남는다)
# 화면이 거의 같아도 나아가는 처리의 헛돌기 기준 (대사는 말풍선 글자만 바뀌어 줄인 화면으로는 같아 보인다 —
# 패킷을 모를 때를 위해 넉넉히. 패킷이 알면 대사 순번이 바뀌는 것으로 나아간 것을 안다)
SAME_LIMIT = {"대사 넘김": 20, "대화 넘기기": 20, "출석 대사 넘김": 30}


def _thumb(frame):
    return None if frame is None else frame[::24, ::24].astype(np.int16)


class Monitor:
    def __init__(self, bot):
        self.bot = bot
        c = bot.cfg.get("monitor", {})
        self.same_limit = c.get("same_limit", 6)
        self.unknown_limit = c.get("unknown_limit", 60)
        self.act_within = c.get("act_within", 15)
        self._sit = None
        self._last = None  # (한 일, 화면 줄임) — 헛돌기 확인
        self._same = 0
        self._unknown_since = None
        self._unknown_tried = False
        shots = getattr(bot, "shot_dir", None)
        self.path = Path(shots).parent / "acts" if isinstance(shots, (str, Path)) else None

    # ---------------------------------------------------------------- 기록
    def record(self, ctx, kind: str, seen=None, **kw) -> None:
        """logs/acts/날짜.jsonl 에 한 줄. 무엇을 하는 중(task·what)에 무슨 상황(sit·src)에서 무엇을 했나(kind·did·ok)."""
        if self.path is None:
            return
        ch = getattr(self.bot, "character", None)
        row = {"t": time.strftime("%H:%M:%S"), "slot": ch.get("slot") if isinstance(ch, dict) else None,
               "task": ctx.task if ctx else None, "what": ctx.what if ctx else None, "kind": kind}
        if seen is not None:
            row.update(sit=seen.what, src=seen.src)
        row.update({k: v for k, v in kw.items() if v is not None})
        try:
            self.path.mkdir(parents=True, exist_ok=True)
            with open(self.path / f"{time.strftime('%Y%m%d')}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ---------------------------------------------------------------- 점검
    def check(self, ctx: Ctx, frame=None, skip=(), ocr: bool = False, guard: bool = True) -> d.Seen:
        # 점검하는 동안(처리기의 sleep·클릭 포함)은 끼어들지 않는다 — 점검자가 이미 지금 화면을 다룬다
        if getattr(self.bot, "_interrupting", True) is not False:
            return self._check(ctx, frame, skip, ocr, guard)
        self.bot._interrupting = True
        try:
            return self._check(ctx, frame, skip, ocr, guard)
        finally:
            self.bot._interrupting = False

    def _check(self, ctx: Ctx, frame=None, skip=(), ocr: bool = False, guard: bool = True) -> d.Seen:
        bot = self.bot
        t0 = time.monotonic()
        seen = d.look(bot, frame, skip=skip, ocr=ocr)
        seen.done = seen.finish = None
        if seen.what != self._sit:
            self.record(ctx, "상황", seen)
            self._sit = seen.what
        if seen.what == d.RUN_LIMIT:
            # '종료' 하나뿐인 창 — 누르지 않고 사람에게. runner 가 실패 + 연속 실행 제한이면 일시정지한다
            raise RuntimeError("게임 연속 실행 제한 창 ('게임을 재시작해주세요')")
        if (r := ctx.finish_on.get(seen.what)) and seen.what != d.DUNGEON_WINDOW:
            out = Finish(r, seen.what)  # 태스크가 기다리던 화면 (던전 창은 처리기가 사진을 남긴다)
        else:
            handler = None if seen.what in d.OUTSIDE else h.pick(ctx, seen.what)
            out = handler(bot, ctx, seen) if handler else None
        ms = int((time.monotonic() - t0) * 1000)
        if isinstance(out, Finish):
            (bot.log.info if out.why == seen.what else bot.log.warning)(f"점검: [{ctx.what or ctx.task}] {seen.what} → 끝 ({out.result}) {out.why}")
            self.record(ctx, "끝", seen, result=out.result, why=out.why, ms=ms)
            seen.finish = out
            self._last, self._same = None, 0
            return seen
        if seen.what == d.UNKNOWN and guard:
            self._on_unknown(ctx, seen)
        elif seen.what != d.UNKNOWN:
            self._unknown_since, self._unknown_tried = None, False
        if out:
            seen.done = out
            # 기다리는 중의 정리(clear)는 Bot.clear_blockers 가 '막는 화면 넘김' 으로 남긴다
            quiet = out in QUIET or ctx.task == "blocker"
            (bot.log.debug if quiet else bot.log.info)(f"점검: [{ctx.what or ctx.task}] {seen.what} → {out}")
            self.record(ctx, "처리", seen, did=out, ms=ms)
            if guard:
                self._guard(ctx, seen, out)
        return seen

    def _guard(self, ctx, seen, out) -> None:
        """같은 처리가 화면이 바뀌지 않은 채 거듭되면 헛도는 것 (누른 게 안 먹음)."""
        if out in WAITS:
            return
        th = _thumb(seen.frame)
        p = self.bot.packets
        step = p.state.dialogue_step if p.ok else None  # 대사 순번 (패킷) — 바뀌면 나아간 것
        last = self._last
        same = (last is not None and last[0] == out and last[2] == step and th is not None and last[1] is not None
                and last[1].shape == th.shape and float(np.abs(th - last[1]).mean()) < 2)
        self._same = self._same + 1 if same else 0
        self._last = (out, th, step)
        limit = SAME_LIMIT.get(out, self.same_limit)
        if self._same >= limit:
            shot = self.bot.snapshot("monitor_same").name
            self.record(ctx, "헛돌기", seen, did=out, n=self._same)
            self._last, self._same = None, 0
            raise Stuck(f"'{out}' 를 {limit}번 넘게 했는데 화면이 그대로 ({seen.what}) → {shot}")

    def _on_unknown(self, ctx, seen) -> None:
        """모르는 상황이 오래 이어짐 — 한 번은 메인 화면으로 돌려 보고, 그래도면 Stuck (처리기를 더해야 할 화면).
        메인으로 돌린 뒤 태스크가 같은 동작을 해 또 모르는 상황이 되는 것도 같은 일에서 두 번째면 멈춘다 — 메인 화면을 거치면
        시계가 다시 0 이 되어, 못 알아보는 제작 창을 60초마다 닫고 다시 여는 걸 거듭했다 (2026-10-26 11:22~11:28)."""
        now = time.monotonic()
        if self._unknown_since is None:
            self._unknown_since = now
            return
        if now - self._unknown_since < self.unknown_limit:
            return
        shot = self.bot.snapshot("monitor_unknown").name
        if not self._unknown_tried and not ctx.n.get("unknown_escape"):
            ctx.n["unknown_escape"] = 1
            self._unknown_tried, self._unknown_since = True, now
            self.bot.log.warning(f"점검: [{ctx.what or ctx.task}] 모르는 상황이 {self.unknown_limit}초째 → 메인 화면으로 ({shot})")
            self.record(ctx, "모름", seen, did="메인 화면으로", shot=shot)
            from ..bot import StepTimeout
            try:
                self.bot.to_main(tries=3)
            except StepTimeout:
                pass
            return
        self.record(ctx, "모름", seen, did="멈춤", shot=shot)
        self._unknown_since, self._unknown_tried = None, False
        raise Stuck(f"모르는 상황이 이어짐 → {shot}")

    # ---------------------------------------------------------------- 정리
    def settle(self, ctx: Ctx | None = None, max_n: int = 25) -> Finish | None:
        """처리할 것이 없어질 때까지 (남은 대사·확인·전달 창). 퀘스트 창(J)·ESC 를 누르기 전에 부른다 —
        ESC 는 NPC 메뉴에선 '대화 종료', 전달 창에선 '닫기' 라 남은 아르바이트 화면이 날아간다 (2026-10-22)."""
        ctx = ctx or Ctx("settle", menus=True)
        for _ in range(max_n):
            seen = self.check(ctx, guard=False)
            if seen.finish:
                return seen.finish
            if not seen.done:
                if self.bot.dialogue_playing():  # 대화가 열리는 중
                    self.bot.sleep(1, 1.3)
                    continue
                return None
            self.bot.sleep(0.4, 0.6)
        return None

    def leave(self, ctx: Ctx | None = None) -> None:
        """하던 일을 놓고 메인 화면으로 (남은 화면을 정리한 뒤 ESC)."""
        from ..bot import StepTimeout
        self.settle(Ctx(ctx.task if ctx else "settle", ctx.what if ctx else "", menus=True))
        try:
            self.bot.to_main()
        except StepTimeout:
            pass

    def clear(self, ctx: Ctx | None = None, skip=(), ocr: bool = False) -> str | None:
        """막는 화면 하나를 넘긴다. 넘긴 것의 이름, 없으면 None. 기다리는 쪽(bot.wait·어비스 대기)이 끼어든 창을 치울 때."""
        seen = self.check(ctx or Ctx("blocker"), skip=skip, ocr=ocr, guard=False)
        return seen.done if seen.done not in WAITS else None

    # ---------------------------------------------------------------- 동작 확인
    def act(self, ctx: Ctx, what: str, do, expect, within: float | None = None, tries: int = 2) -> bool | None:
        """what 동작을 한다: 막는 것 정리 → do() → expect() 가 within 초 안에 참이 되나. 안 되면 다시 (tries 번까지).
        True 됨 / False 할 수 없음 (do() 가 False — 버튼이 없음 등, 다시 하지 않는다) / None 했는데 기대한 변화가 끝내 없음."""
        within = within or self.act_within
        for n in range(1, tries + 1):
            # 던전 창에서 하는 동작(입장)이면 그 창을 닫지 않는다
            self.settle(Ctx(ctx.task, ctx.what, menus=True, keep_dungeon_window=ctx.keep_dungeon_window))
            t0 = time.monotonic()
            if do() is False:
                self.record(ctx, "동작", did=what, ok=False, why="할 수 없음", n=n)
                return False
            while time.monotonic() - t0 < within:
                if expect():
                    self.record(ctx, "동작", did=what, ok=True, n=n, ms=int((time.monotonic() - t0) * 1000))
                    return True
                self.bot.sleep(0.6, 0.8)
            self.bot.log.warning(f"점검: [{ctx.what or ctx.task}] '{what}' 뒤 기대한 변화가 {within:.0f}초 안에 없음 ({n}/{tries})")
            self.record(ctx, "동작", did=what, ok=False, why="기대한 결과 없음", n=n)
        return None


def of(bot) -> Monitor:
    """bot 의 점검자 (없으면 만든다)."""
    m = getattr(bot, "_monitor", None)
    if not isinstance(m, Monitor) or m.bot is not bot:
        m = bot._monitor = Monitor(bot)
    return m
