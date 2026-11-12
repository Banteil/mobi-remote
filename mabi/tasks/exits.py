"""콘텐츠(일반 던전·어비스·레이드·출항선)·보관함 구역 안에서 나가기의 공통 틀.

순서는 같다: 오른쪽 위 나가기(단축키 또는 아이콘) → 확인 창 → 확인(Space, 안 먹으면 버튼 클릭) → 로딩 → 밖 메인 화면.
종류마다 다른 것(안인가 · 확인 창 알아보기 · 확인 방법 · 나가기 전에 판이 끝났나)만 하위 클래스가 덮어쓴다
(DungeonExit 은 여기, abyss.AbyssExit · raid.RaidExit · raid.ShipExit · drill.DrillExit · field_boss.FieldBossExit).
예전엔 네 벌이 따로 있어 'Space 가 안 먹으면 클릭'(레이드)·'나가기 전에 판이 끝났나'(어비스)가 한쪽에만 있었다.

leave_instance(bot) 는 지금 자리(place)를 보고 맞는 나가기를 부른다 — 실패 뒤 정리(runner.recover)·접속(login)이 쓴다.
"""
import time

from .. import keys
from ..bot import Bot, StepTimeout


class Exit:
    NAME = ""        # 로그·오류에 쓰는 이름
    SNAP = "leave"   # 실패 스냅샷 이름
    HOTKEY = None    # 나가기 단축키 이름 (mabi.keys — 레이드는 보관함 키. 클릭과 달리 뒤에서 도는 게임을 앞으로 가져오지 않는다)
    TIMEOUT = 120    # 나가기를 누르는 데 쓰는 시간 상한 (횟수가 아니라 시간 — 사람이 PC 를 쓰는 동안 클릭이 몇 번 건너뛰어져도)

    # ---- 종류마다 덮어쓴다
    def inside(self, bot: Bot) -> bool:
        """아직 안이라 나가기를 눌러야 하나 (모르면 안으로 본다)."""
        raise NotImplementedError

    def gone(self, bot: Bot) -> bool:
        """다 나왔나 (메인 화면과 같이 본다). 기본은 안이 아님."""
        return not self.inside(bot)

    def dialog(self, bot: Bot, timeout: float):
        """확인 창이 떴으면 그 표시(누를 자리면 좌표), 아니면 None. timeout 동안 기다린다."""
        raise NotImplementedError

    def confirm(self, bot: Bot, hit) -> None:
        """확인 창에서 나가기. 기본: Space, 로딩이 안 시작되고 창이 남았으면 그 자리를 누른다
        (레이드에서 29판을 잘 돌다 이 창에서만 Space 를 안 받고 창이 그대로 남았다 — 마우스로는 넘어감, 2026-10-28)."""
        bot.key("space")
        if not bot.wait_packet(lambda s: s.loading, 6, since=bot.input_mark) and (again := self.dialog(bot, 0)):
            bot.log.info(f"Space 를 눌러도 {self.NAME}에서 안 나가짐 → 확인 버튼 클릭")
            if isinstance(again, tuple):
                bot.click(again)
            else:
                bot.key("space")

    def surely_inside(self, bot: Bot) -> bool:
        """단축키를 눌러도 되나 — 패킷이 맵을 알고 안이라고 할 때만 (기본은 inside 와 같음)."""
        return self.inside(bot)

    def finished_before(self, bot: Bot) -> bool:
        """나가기 전에 판이 끝났나 (끝났으면 나가지 않고 부르는 쪽이 결과로 잇는다)."""
        return False

    def uncover(self, bot: Bot) -> None:
        """나가기 버튼이 안 보일 때 — 가린 창(부활 창 등)을 닫아 본다."""
        bot.key("esc")

    def open_dialog(self, bot: Bot):
        """확인 창이 아직 없을 때 나가기를 눌러 띄운다 → dialog 표시, 못 띄웠으면 None (안인지부터 다시 본다).
        기본: 오른쪽 위 나가기 아이콘 — 단축키가 있고 안이 확실하면 키 먼저. 아이콘이 안 보이면 uncover."""
        ui = bot.ui
        if not bot.exists(ui["abyss_exit"]):
            self.uncover(bot)
            bot.sleep(1.0, 1.5)
            return None
        hit = None
        # 단축키(X)는 안이 확실할 때만 — X 는 본래 '보관함으로 이동'이다 (콘텐츠 안에선 나가기 창이 먼저 뜨지만
        # 메인 필드로 나가면 그 이동이 이어진다, 2026-11-02). 필드로 나가는 쪽은 HOTKEY 를 두지 않는다 → 아이콘
        if self.HOTKEY and self.surely_inside(bot):
            key = keys.of(bot, self.HOTKEY)
            bot.log.debug(f"{self.NAME} 나가기: {key} 키")
            bot.key(key)
            hit = self.dialog(bot, 4)
        if not hit:
            bot.log.debug(f"{self.NAME} 나가기: 아이콘 클릭")
            bot.click(ui["abyss_exit"])
            hit = self.dialog(bot, 5)
        return hit

    # ---- 공통
    def run(self, bot: Bot) -> bool:
        """나간다. 다 나와 메인 화면이 보이면 True, 나가기 전에 판이 끝났으면 False."""
        for attempt in range(self.RETRIES + 1):
            got = self._press(bot)
            if got is not None:
                return got
            if attempt == self.RETRIES:
                break
            # 확인까지 눌렀는데 그대로 안이다 — 나가는 사이 부활(어비스 우연한 만남: 캠프파이어에 앉은 파장이 전체 부활)이
            # 확인 창을 닫았다. 한 번 나가기로 정했으면 무슨 일이 생겨도 나간다 (2026-11-06 사용자) → 처음부터 다시 누른다
            bot.log.warning(f"{self.NAME} 나가기를 눌렀는데 아직 안 (나가는 사이 부활 등) → 다시 나가기 "
                            f"({attempt + 1}/{self.RETRIES}) → {bot.snapshot(self.SNAP + '_again').name}")
        raise StepTimeout(f"{self.NAME}에서 나가기를 {self.RETRIES + 1}번 눌러도 안에 남음 → {bot.snapshot(self.SNAP).name}")

    RETRIES = 3     # 확인까지 눌렀는데 안에 남았을 때 처음부터 다시 누르는 횟수
    STAY = 20       # 확인 뒤 이만큼 로딩이 안 시작되고 안에 그대로면 안 나가진 것으로 본다 (초)

    def _press(self, bot: Bot) -> bool | None:
        """나가기 → 확인 → 밖. True 나옴 / False 나가기 전에 판이 끝남 / None 확인까지 눌렀는데 안에 남음."""
        deadline = time.monotonic() + self.TIMEOUT
        while True:
            if self.finished_before(bot):
                bot.log.info(f"나가기 전에 판이 끝남 ({self.NAME}) → 나가지 않고 결과로")
                return False
            if not self.inside(bot):
                break
            if time.monotonic() > deadline:
                raise StepTimeout(f"{self.NAME}에서 나가지 못함 → {bot.snapshot(self.SNAP).name}")
            hit = self.dialog(bot, 0)  # 확인 창이 이미 떠 있으면(지난 시도의 Space 가 안 먹음) 그 창부터
            if not hit:
                hit = self.open_dialog(bot)
                if not hit:
                    continue
                bot.sleep(0.5, 0.9)
            bot.log.debug(f"{self.NAME} 나가기: 확인 창 → 나가기")
            self.confirm(bot, hit)
            break
        # 밖으로 나와 메인 화면이 보일 때까지 — 패킷이 있으면 맵을 떠나기 시작하는 순간(길어야 15초)을 기다렸다가,
        # 로딩 동안은 화면을 보지 않는다
        pressed = time.monotonic()
        if bot.wait_packet(lambda s: s.loading, 15, since=bot.input_mark) is False and self.inside(bot) \
                and not bot.map_loading():
            return None  # 패킷: 맵을 떠나기 시작하지 않았고 그대로 안
        end = time.monotonic() + bot.cfg["timing"]["loading"]
        left = False  # 로딩이든 밖이든 한 번이라도 안을 벗어났나
        while time.monotonic() < end:
            if bot.map_loading():
                left = True
                bot.wait_loaded(end - time.monotonic())
                continue
            if self.gone(bot):
                left = True
                if bot.at_main():
                    return True
                if not bot.is_loading():
                    bot.clear_blockers(ocr=True)  # 나오면서 뜬 퀘스트 완료 창 등
            elif not left and not bot.is_loading() and time.monotonic() - pressed > self.STAY:
                return None  # 패킷 없이 화면으로만: 확인 뒤 한참 그대로 안
            bot.sleep(2)
        raise StepTimeout(f"{self.NAME}에서 나온 뒤 메인 화면이 나오지 않음")


class DungeonExit(Exit):
    """일반 던전(공물·은동전·요일): 어비스와 같은 오른쪽 맨 위 나가기 → '던전에서 퇴장하시겠습니까?' → 나가기(Space)."""
    NAME, SNAP = "던전", "dungeon_leave"

    def inside(self, bot):
        from ..place import DUNGEON, place
        return place(bot).kind == DUNGEON

    def dialog(self, bot, timeout):
        if timeout <= 0:
            return bot.exists(bot.ui["abyss_exit_dialog"]) or None
        try:
            return bot.wait(bot.ui["abyss_exit_dialog"], timeout=timeout)
        except StepTimeout:
            return None


class HousingExit(Exit):
    """여관 안쪽 보관함 구역·마이 홈: 오른쪽 위 나가기 (던전과 같은 아이콘) → 아래 '반호르 여관에서 나가시겠습니까?'
    (마을 이름이 들어가 글자 대신 초록 'Space 나가기' 버튼으로 본다) → Space, 안 먹으면 그 버튼.
    여기서 접속을 끊은 캐릭터는 숙제 이동이 안 돼 헤맨다 — 숙제 시작(login)·실패 뒤 정리(recover)가 먼저 꺼낸다."""
    NAME, SNAP = "보관함 구역", "housing_leave"
    LOADING = "loading"   # 확인 창 없이 바로 맵을 떠나기 시작함

    def inside(self, bot):
        from ..place import HOUSINGS, place
        return place(bot).kind in HOUSINGS

    def dialog(self, bot, timeout):
        end = time.monotonic() + max(0.0, timeout)
        while True:
            if bot.map_loading():
                return self.LOADING
            if hit := bot.exists(bot.ui["housing_exit_ok"]):
                return hit
            if time.monotonic() >= end:
                return None
            bot.sleep(0.4, 0.6)

    def confirm(self, bot, hit):
        if hit == self.LOADING:
            return
        super().confirm(bot, hit)


def leave_instance(bot: Bot) -> bool:
    """지금 콘텐츠(일반 던전·어비스·레이드·출항선)·보관함 구역 안이면 맞는 나가기로 밖 메인 화면까지.
    나갔으면 True, 밖이면 False.
    사냥터·검은 구멍은 나가지 않는다 (끝날 때까지 기다리는 것이 숙제 규칙 — login._leave_dungeon)."""
    from ..place import ABYSS, DUNGEON, HOUSINGS, RAID, RAID_LOBBY, place
    kind = place(bot).kind
    if kind in HOUSINGS:
        HousingExit().run(bot)
    elif kind == DUNGEON:
        DungeonExit().run(bot)
    elif kind == ABYSS:
        from . import abyss
        abyss.get_out(bot)
    elif kind in (RAID, RAID_LOBBY):
        from . import raid
        raid.get_out(bot)
    else:
        return False
    bot.log.info(f"콘텐츠 안({kind}) → 나옴")
    return True
