"""콘텐츠(던전·사냥터·어비스·레이드·드릴) 안에서 기다리며 지켜보기 — 자동 전투 켜기, 한 번 보기(watch), 전투 대기 뼈대(Fight)."""
import time

from ..bot import Bot


def ensure_auto(bot: Bot) -> None:
    """자동 전투가 꺼져 있으면 켠다."""
    ui = bot.ui
    if bot.vision.has(ui["auto_off"]) and bot.click_if(ui["auto_off"]):
        bot.log.info("자동 전투 켬")


def watch(bot: Bot, ctx, act: dict | None = None, ocr: bool = False):
    """던전·사냥터·어비스 안에서 기다리는 동안 한 번 본다 — 쓰러짐('여기서 부활', ctx.revive)과 끼어든 창은 점검자가.
    패킷이 없으면 쓰러짐을 CLI(act — 이미 받아 둔 get_activity)로 본다. 점검자가 본 것(Seen)을 돌려준다.
    안에서는 연출의 '장면 넘기기' 를 누르지 않고 기다린다 (던전·어비스 규칙 — 검은 구멍·사냥터도 같이)."""
    from .. import monitor
    from ..monitor import handlers
    prev, bot.scene_skip = bot.scene_skip, False
    try:
        seen = monitor.of(bot).check(ctx, guard=False, ocr=ocr)
    finally:
        bot.scene_skip = prev
    # 패킷이 쓰러짐을 아직 모르면(None — 판 안에서 켬. 파티 판은 부활 가능 신호가 안 와 '내 캐릭터' 를 알아야 한다) CLI 로
    unknown = not bot.packets.ok or bot.packets.state.dead is None
    if not seen.finish and not seen.done and unknown and bot.is_dead(act):
        out = handlers.dead(bot, ctx, seen)
        if isinstance(out, monitor.Finish):
            seen.finish = out
        else:
            seen.done = out
    if seen.finish and seen.finish.result == "dead":
        bot.log.warning("사망 상태, '여기서 부활' 을 못 함")
    return seen


class Fight:
    """콘텐츠 안에서 끝날 때까지 지켜보는 공통 뼈대 — 어비스·레이드 판(play), 나이트메어 드릴 구역(wait_zone).
    한 바퀴: 패킷으로 wake 를 WAKE 초까지 기다림 (패킷이 없거나 모르면 IDLE 초 쉼) → packet_end() → CLI 활동(act)
      → act_end(act) → 부활하지 않는 설정이면 쓰러짐 = 'dead' → before_watch(act) → watch (쓰러짐 '여기서 부활'·끼어든 창 —
      점검자) → 쓰러짐으로 끝났으면 dead_end(seen) → 부활했으면 on_revive 하고 다음 바퀴 → screen_end(seen)
      → 싸우는 중(fighting)이면 배고프면 먹기·tick(act) (보스전 궁극기·팔라딘 변신) → 시간 상한이면 timed_out().
    종류마다 다른 것만 덮어쓴다. 단계가 None 이 아닌 값을 돌려주면 그것이 결과 (0 도 결과 — 드릴의 못 깸),
    NEXT 면 다음 바퀴로. 필드 보스·뱅가드는 패킷 기다림 없이 화면을 짧게 보는 다른 꼴이라 따로 돈다."""
    NEXT = object()
    WAKE = 3      # 패킷으로 기다리는 시간 (초)
    IDLE = 3.0    # 패킷이 없거나 모를 때 쉬는 시간 (초)
    KIND, WHAT = "dungeon", "진행 중"  # 점검자 Ctx 이름

    def __init__(self, bot: Bot, timeout: float, revive: bool = True, on_revive=None, tick=None):
        self.bot, self.revive, self.on_revive, self.tick = bot, revive, on_revive, tick
        self.start = time.monotonic()
        self.end = self.start + timeout
        from .. import monitor
        self.ctx = monitor.Ctx(self.KIND, self.WHAT, revive=revive)

    # ---- 종류마다 덮어쓴다
    def wake(self, s) -> bool:
        """이 패킷 상태면 기다림을 바로 깬다 (결과 옴 등)."""
        return False

    def packet_end(self):
        """CLI 를 묻기 전에 (패킷으로) 끝났나."""

    def act_end(self, act: dict):
        """CLI 활동으로 끝났나."""

    def before_watch(self, act: dict) -> None:
        """점검자가 보기 전에 할 것."""

    def watch_ocr(self) -> bool:
        """점검자가 글자로도 볼까 (느리다)."""
        return False

    def dead_end(self, seen):
        """쓰러졌는데 '여기서 부활' 을 못 함 (점검자) — 결과, None 이면 이어 본다."""
        return "dead"

    def screen_end(self, seen):
        """점검자가 본 화면으로 끝났나."""

    def fighting(self, seen) -> bool:
        """싸우는 중이라 먹기·tick 을 해도 되나 (점검자가 무언가를 처리했으면 아님)."""
        return not seen.done

    def timed_out(self):
        return "timeout"

    # ---- 공통
    def run(self):
        bot = self.bot
        while True:
            if bot.wait_packet(self.wake, self.WAKE) is None:
                bot.sleep(self.IDLE)
            r = self.packet_end()
            if r is self.NEXT:
                continue
            if r is not None:
                return r
            act = bot.activity() or {}
            if (r := self.act_end(act)) is not None:
                return r
            if not self.revive and bot.is_dead(act):
                return "dead"
            self.before_watch(act)
            seen = watch(bot, self.ctx, act, ocr=self.watch_ocr())
            if seen.finish and seen.finish.result == "dead" and (r := self.dead_end(seen)) is not None:
                return r
            if self.on_revive is not None and self.ctx.take("revived"):
                self.on_revive()
                continue
            if (r := self.screen_end(seen)) is not None:
                return r
            if self.fighting(seen):
                bot.eat_if_hungry()
                if self.tick:
                    self.tick(act)
            if time.monotonic() > self.end:
                return self.timed_out()
