"""아르바이트: 퀘스트 창(J) → 아르바이트 탭의 일을 위에서부터 끝까지 한다 (캐릭터 탭에서 켠 캐릭터만).

아르바이트마다 흐름이 제각각이라 (계단 수리처럼 자동으로 진행하고 바로 끝나는 것, 중간에 다른 NPC 대화가 끼는 것,
결과 보고 → 물품 전달이 있는 것) 정해진 순서를 따라가지 않고 상황에 반응한다. 상황 판단과 대응(수락·결과 보고·전달 창·
NPC 대화·작별 화면·채집·제작·가공 창·던전 창)은 점검자(mabi.monitor)가 한다. 이 태스크는 일의 진척만 본다:
  메인 화면에서 멈춤(이동·자동 진행·대화·전투 아님) → 퀘스트(J) → 아르바이트 → 그 일의 '진행하기' 다시
  채집 중이면 모자란 개수가 줄어드나, 일이 추적 칸에서 사라졌나(끝)

수락한 아르바이트의 조건은 CLI get_quests 에 나온다 ('새록 버섯 포자 보유 10/10'). '보유' 조건을 못 채운 일은 진행하기를 누르면
'필요한 아이템이 없습니다' → 물품 줄 → '구하는 방법' 맨 위(추천)로 게임이 필요한 만큼만 채집한다 (구할 방법이 없으면 건너뜀). 끝났는지는 get_quests 에서 그 제목이 사라졌는지로 본다.
버튼 색이 카드마다 달라(멤버십 노랑, 보통 초록) '지원하기'·'진행하기' 버튼과 카드 제목은 글자(OCR)로 찾는다.
"""
import difflib
import re
import time

from .. import craft, gamedata as gd, monitor, ocr
from ..bot import Bot
from ..monitor import Ctx, Stuck, detect as d
from ..progress import Progress
from .content import CannotProceed, open_arbeit_tab, questwin_text_ok

PROGRESS, APPLY = gd.text("arbeit_progress"), gd.text("arbeit_apply")  # 카드 버튼 '진행하기' · '지원하기'
HAVE = gd.text("arbeit_have_item")  # CLI 조건 '… 보유 3/10'


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _plain(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t)


def accepted(bot: Bot, raw: bool = False) -> list[dict]:
    """수락해 둔 아르바이트 [{title, objectives}]. 아르바이트는 수락하면 '사이드' 로 고정(pinned_sub)된다.
    사람이 고정해 둔 사이드 퀘스트('[긴급 의뢰] 뱅가드 브리치' 등)도 pinned_sub 라 CLI 로는 못 가른다
    (2026-10-26: 그걸 아르바이트로 알고 진행하다 아르바이트 탭 맨 위 '요일' 카드를 눌러 알비 던전으로 감)
    → 아르바이트 탭에서 본 카드 제목(_arb_titles)에 있는 것만. 탭을 아직 안 봤거나 raw 면 걸러지지 않은 목록."""
    qs = bot.state.query("get_quests") or []
    out = [{"title": q["QuestTitle"], "objectives": q.get("Objectives") or []}
           for q in qs if isinstance(q, dict) and q.get("Source") == "pinned_sub"]
    known = getattr(bot, "_arb_titles", None)
    if raw or known is None:
        return out
    return [j for j in out if any(_same(j["title"], k) for k in known)]


def _finished(bot: Bot, title: str) -> bool:
    """title 아르바이트가 정말 끝났나. 추적 칸에서 사라진 것만으로는 모른다 — 이동·채집·로딩 중에는 추적 칸이
    통째로 비어 get_quests 가 [] 를 준다 (2026-10-22: 채집하러 가자마자 '완료' 로 오판, 17:44 에도 같은 일).
    → 추적 칸에 다른 퀘스트는 보이는데 이 일만 없을 때, 2초 뒤 한 번 더 봐도 그럴 때만 끝난 것으로 본다."""
    for i in range(2):
        qs = bot.state.query("get_quests")
        if not qs:
            return False
        if any(isinstance(q, dict) and _same(q.get("QuestTitle", ""), title) for q in qs):
            return False
        if i == 0:
            bot.sleep(2, 2.5)
    return True


def missing_items(job: dict) -> list[str]:
    """채우지 못한 '보유' 조건 (있으면 그 일은 지금 끝낼 수 없다)."""
    return [_plain(o["Description"]) for o in job["objectives"]
            if HAVE in o.get("Description", "") and not o.get("IsCompleted")]


def _item_name(desc: str) -> str:
    """'새록 버섯 포자 보유 3/10' → '새록 버섯 포자'."""
    return re.sub(rf"\s*{HAVE}.*$", "", desc).strip()


def ungatherable(bot: Bot, job: dict) -> list[str]:
    """모자란 물품 중 채집으로 못 구하는 것 (가공품 등). CLI 채집 가능 목록(조회)과 대조한다.
    사용자 규칙: 모자란 게 채집품뿐이면 채집해서 완료, 가공품이 하나라도 모자라면 포기."""
    if not hasattr(bot, "_gatherable"):
        data = bot.state.query("get_gatherable_items") or {}
        items = data.get("items", data) if isinstance(data, dict) else data
        bot._gatherable = {i.get("DisplayName") for i in items if isinstance(i, dict) and i.get("ToolOk", True)}
    return [n for n in (_item_name(d) for d in missing_items(job)) if n not in bot._gatherable]


def alter_missing(job: dict) -> list[str]:
    """모자란 물품 중 가공으로만 만드는 것 (레시피 표 via=alter — 두유·말린 찻잎 등). 가공은 시간이 걸려 건너뛰는 일이라
    (사용자 규칙) 진행하기를 누르기 전에 CLI 조건과 레시피 표로 미리 가른다 (2026-10-26 사용자 제안).
    레시피 표가 없으면 [] — 예전처럼 가공 시설 창을 보고 건너뛴다."""
    try:
        table = craft.data().recipes
    except RuntimeError:
        return []
    out = []
    for name in (_item_name(d) for d in missing_items(job)):
        makers = table.makers(name)
        if makers and all(r.get("via") == "alter" for r in makers):
            out.append(name)
    return out


def _is(t: str, word: str) -> bool:
    """버튼 글자 word 인가. OCR 이 한 글자쯤 틀리거나 덧붙여도 ('지원하기》') 같다고 본다.
    '지원하기' 와 '진행하기' 는 반만 같아 섞이지 않는다."""
    n = _norm(t)
    return n == word or (len(n) <= len(word) + 2 and difflib.SequenceMatcher(None, n, word).ratio() >= 0.75)


def _buttons(bot: Bot) -> list[tuple[str, int, int]]:
    """퀘스트 창 오른쪽 목록의 글자. 탭 줄에 걸친 '진행하기'·'지원하기' 는 뺀다 (목록을 내리면 다시 보인다).
    2026-10-24: 반쯤 보인 '지원하기' 자리를 눌러 '이벤트' 탭이 열리고, 수락 대화를 180초 기다리다 FAIL."""
    items = ocr.find_texts(bot.frame(), gd.region("arbeit_panel"))
    return [i for i in items if questwin_text_ok(i[2]) or not (_is(i[0], PROGRESS) or _is(i[0], APPLY))]


def _scroll_panel(bot: Bot, notches: int) -> None:
    bot.scroll(*bot.cfg["arbeit"]["list_scroll_at"], notches)
    bot.sleep(1.0, 1.3)


def _find_card_button(bot: Bot, title: str | None, word: str):
    """title 카드의 word 버튼 (title 이 None 이면 맨 위 word 버튼). 목록을 내려 가며 찾는다.
    못 찾았을 때 무엇을 읽었는지 bot._arb_read 에 남긴다 (쪽마다 글자 목록)."""
    bot._arb_read = []
    for page in range(bot.cfg["arbeit"]["list_pages"]):
        items = _buttons(bot)
        bot._arb_read.append([t for t, _, _ in items])
        btns = sorted(((x, y) for t, x, y in items if _is(t, word)), key=lambda b: b[1])
        if title is None:
            if btns:
                return btns[0]
        else:
            head = next(((x, y) for t, x, y in items if _same(t, title)), None)
            if head:
                below = [b for b in btns if b[1] > head[1]]
                if below:
                    return below[0]
            # 수락한 일의 '진행하기' 는 목록 맨 위에 모인다 → 그 아래 '지원하기' 가 보이는데도 못 찾았으면 더 내려도 없다
            if word == PROGRESS and any(_is(t, APPLY) for t, _, _ in items):
                return None
        if page + 1 < bot.cfg["arbeit"]["list_pages"]:
            _scroll_panel(bot, -4)
    return None


def _book(bot: Bot) -> dict | None:
    """오늘 기록(state/날짜.json)의 이 캐릭터 아르바이트 진행 {current, stage, at, done, skipped, stuck}.
    숙제가 도중에 꺼져도 다시 시작하면 이걸 보고 이어 한다 (하던 일은 게임에도 '수락한 일' 로 남아 있어 그 일부터 한다)."""
    st, ch = getattr(bot, "daily", None), getattr(bot, "character", None)
    if st is None or not ch:
        return None
    return st.data.setdefault(str(ch["slot"]), {}).setdefault("_arbeit", {})


def _note(bot: Bot, title: str | None, key: str, stage: str, **lists) -> None:
    """단계 기록 (bot.step: 이어 하기용 단계 키) + 아르바이트 장부 (_arbeit: 지금 일·완료/건너뜀/막힘 목록)."""
    b = _book(bot)
    if b is not None:
        b.update({"current": title, "stage": stage, "at": time.strftime("%H:%M:%S"), **lists})
    bot.step(key, f"{title}: {stage}" if title else stage, job=title)  # 장부도 같이 저장된다


def _card_title(items, bx: int, by: int) -> str:
    """'진행하기' 버튼 (bx, by) 카드의 제목 (짐작). 카드는 위에서부터 [등급·종류] / 제목 / NPC 위치·'n시간 남음' / 설명 /
    [보상 … 버튼] 이다 → 버튼 위에서 가장 가까운 '남음' 줄 바로 위의 글자 (설명이 두 줄이어도 맞는다)."""
    left = [(t, x, y) for t, x, y in items if x < bx - 100 and y < by]
    rest = [y for t, x, y in left if gd.text("arbeit_time_left") in t]
    if not rest:
        return ""
    ry = max(rest)
    above = [(t, y) for t, x, y in left if y < ry - 15]
    return max(above, key=lambda r: r[1])[0] if above else ""


def _same(a: str, b: str) -> bool:
    """같은 제목인가. 카드 제목은 OCR 이라 한 글자쯤 틀린다 ('빚은' → '빛은', 2026-10-22) → 비슷하면 같다고 본다."""
    a, b = _norm(a), _norm(b)
    if not (a and b):
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def _panel_jobs(bot: Bot) -> list[tuple[str, tuple[int, int], int]]:
    """퀘스트 창 아르바이트 탭에서 수락해 둔 일 ('진행하기' 카드) [(제목 짐작, 버튼 자리, 목록 쪽)].
    CLI get_quests 에는 지금 추적 중인(pinned) 아르바이트 하나만 나와서 (2026-10-22: 막힌 일 두 개가 목록에서
    빠져 '다 끝남' 으로 기록됨) 수락한 일 전부는 이 창으로 본다. 창은 열린 채로 두고 마지막 쪽까지 내려가 있다."""
    _settle(bot)  # 창을 열 때 ESC 가 남은 NPC 메뉴·전달 창을 닫아 버리지 않게
    open_arbeit_tab(bot)
    out = []
    pages = bot.cfg["arbeit"]["list_pages"]
    bot._arb_scrolled = 0
    bot._arb_closed = False
    for page in range(pages):
        items = _buttons(bot)
        for t, x, y in items:
            if _is(t, PROGRESS) and not any(o[1] == (x, y) for o in out):
                out.append((_card_title(items, x, y), (x, y), page))
                if out[-1][0]:
                    bot._arb_titles = {*(getattr(bot, "_arb_titles", None) or ()), out[-1][0]}
        # 구인 마감 ('새로운 아르바이트를 기다려주세요') — 남은 일도 지원할 일도 없다. 더 볼 것 없음
        if any(w in _norm(t) for t, _, _ in items for w in gd.words("arbeit_closed")):
            bot._arb_closed = not out
            break
        # 수락한 일('진행하기')은 목록 맨 위에 모이고 그 아래가 구인 중('지원하기') → '지원하기' 가 보이면 더 내릴 필요 없다
        if any(_is(t, APPLY) for t, _, _ in items) or page + 1 >= pages:
            break
        _scroll_panel(bot, -4)
        bot._arb_scrolled += 1
    return out


def _press_other(bot: Bot, exclude) -> str | None:
    """추적 중이 아닌 수락한 일 중 exclude 에 없는 것의 '진행하기' 를 누른다. 누른 일의 제목 (CLI 기준) 또는 None."""
    jobs = [j for j in _panel_jobs(bot) if not any(_same(j[0], e) for e in exclude)]
    if not jobs:
        bot.to_main()
        return None
    guess, pos, page = jobs[0]
    # 내려가 있으면 그 쪽으로 돌아가서 누른다 (대개 맨 위 쪽이라 스크롤이 없다)
    if getattr(bot, "_arb_scrolled", 0) != page:
        _scroll_panel(bot, 4 * (bot._arb_scrolled + 1))
        for _ in range(page):
            _scroll_panel(bot, -4)
    items = _buttons(bot)
    btn = next(((x, y) for t, x, y in items if _is(t, PROGRESS)
                and (_same(_card_title(items, x, y), guess) if guess else abs(y - pos[1]) < 30)), None)
    if not btn:
        bot.to_main()
        return None
    bot.click(btn)
    bot.sleep(2, 2.5)
    _fast_travel(bot)
    # CLI 퀘스트 목록은 '화면에 보이는' 추적 칸만 준다 → 창이 닫히고 추적 칸에 이 일이 뜰 때까지 몇 초 걸린다
    # (2026-10-22: 바로 물어 빈 목록 → 수락 안 된 것으로 보고 '막힘' 처리)
    for _ in range(8):
        now = accepted(bot)
        if now:
            return now[0]["title"]
        bot.sleep(1, 1.2)
    bot.log.warning(f"아르바이트 '{guess}': 진행하기를 눌렀는데 추적 칸에 안 나타남 → {bot.snapshot('arbeit_pin').name}")
    return guess or None


def _idle(bot: Bot) -> bool:
    return d.idle(bot)


def _fast_travel(bot: Bot) -> bool:
    return monitor.fast_travel(bot)


def _settle(bot: Bot) -> None:
    """남은 NPC 대사·메뉴·확인·전달 창을 끝까지 처리한다 (점검자). 퀘스트 창(J)·ESC 를 누르기 전에 부른다 —
    ESC 는 NPC 메뉴에선 '대화 종료', 전달 창에선 '닫기' 라 남은 아르바이트 화면이 날아간다 (2026-10-22)."""
    monitor.of(bot).settle(Ctx("arbeit", menus=True))


def _leave(bot: Bot, ctx: Ctx | None = None) -> None:
    monitor.of(bot).leave(ctx)


def _job_ctx(bot: Bot, title: str) -> Ctx:
    """아르바이트 한 건. 던전 창이 열리면 그 일은 끝 (요일 던전 숙제 몫 — 던전 창 앞에서 8분을 기다리던 것, 2026-10-26).
    모자란 물품이 채집으로 못 구하는 것(가공품 등)이면 끝 (사용자 규칙: 채집품만 모자라면 채집해서 완료)."""
    def missing(bot, ctx, seen):
        job = next((j for j in accepted(bot) if _same(j["title"], title)), None)
        if job and (bad := ungatherable(bot, job)):
            return f"채집으로 못 구하는 물품 부족 ({', '.join(bad)})"
        return None
    return Ctx("arbeit", title, job=True, finish_on={d.DUNGEON_WINDOW: "dungeon"}, decide={d.ITEM_MISSING: missing},
               note=lambda key, stage: _note(bot, title, key, stage))


def _moved(bot: Bot) -> bool:
    """'진행하기' 뒤 무엇이든 시작됐나 — 이동·대화·자동 진행이거나 메인 화면이 아님 (창이 열림)."""
    return not (bot.at_main() and _idle(bot))


def _press_progress(bot: Bot, title: str) -> bool:
    """맨 위 카드의 '진행하기'. 누를 수 없었으면 False. 눌렀는데 아무 변화가 없으면 점검자가 한 번 더 누른다."""
    def do():
        open_arbeit_tab(bot)
        # 하고 있는(추적 중인) 일은 목록 맨 위 카드다 → 제목을 OCR 로 맞춰 볼 것 없이 맨 위 '진행하기' (2026-10-22 사용자 지적)
        b = _find_card_button(bot, None, PROGRESS)
        if not b:
            bot.to_main()
            return False
        bot.click(b)
        bot.sleep(2, 2.5)
        _fast_travel(bot)
        return True
    return monitor.of(bot).act(Ctx("arbeit", title), "진행하기", do, lambda: _moved(bot), within=12) is not False


def _work(bot: Bot, title: str) -> str:
    """한 아르바이트를 끝까지. 'done' | 'short'(물품 부족) | 'alter'(가공 필요) | 'dungeon'(던전 클리어 필요) | 'stuck'
    | 'gather_stall'(채집이 멈춤). 화면 대응은 점검자, 여기서는 진척(채집 개수·끝남·멈춤)만 본다."""
    a = bot.cfg["arbeit"]
    mon, ctx = monitor.of(bot), _job_ctx(bot, title)
    # 일 전체: 채집 개수가 늘거나 채집을 마치면 시계를 되감는다 (job_timeout 동안 아무 진척이 없으면 막힘, job_max 가 상한)
    work = Progress(stall=a["job_timeout"], cap=a.get("job_max", 1800))
    gather = None  # 채집 중이면 Progress — 남은 개수가 gather_timeout 동안 그대로면 포기
    idle_since, pushes, last_sig, last_check = None, 0, None, 0.0
    busy_since, busy_told = None, False  # 메인 화면인데 '움직이는 중' 으로 보인 때부터
    unseen, untracked = 0, False  # 멈춰 있을 때 추적 칸에 이 일이 안 보인 횟수 · 끝내 안 보여 추적 칸 없이 미는 중
    try:
        while not work.expired:
            bot.sleep(1.0, 1.4)
            # 채집하러 간 뒤: 조건이 채워지면 바로 완료하러 간다 (게임은 필요한 만큼만 캐고 멈춘다)
            if gather and time.monotonic() - last_check > 3:
                last_check = time.monotonic()
                job = next((j for j in accepted(bot) if _same(j["title"], title)), None)
                if job is None:
                    if _finished(bot, title):
                        return "done"
                    continue  # 추적 칸이 잠깐 비었다 (이동·로딩 중) — 끝난 게 아니다
                # 개수가 늘고 있으면 기다린다. 국경 수비대 물자 보급처럼 100개짜리를 두세 가지 캐는 일은 10분 넘게 걸려
                # 정해진 시간(5분)으로 끊으면 82/100 에서 '물품 부족' 으로 건너뛰었다 (2026-10-24)
                if gather.update(missing_items(job)):
                    work.poke()
                if not missing_items(job):
                    gather = None
                    work.poke()  # 전달·제작 등 남은 걸음에 시간을 새로
                    _note(bot, title, "arb_gathered", "채집 끝 → 완료하러 이동")
                    # 게임이 알아서 전달하러 가기도 한다 (2026-10-22: 40m 앞에서 '진행하기' 를 다시 누르려다 못 찾고
                    # 막힘으로 끝냄) → 이동 중이면 그대로 두고, 멈춰 있을 때만 누른다. 못 눌러도 아래 '멈춤' 처리가 다시 민다
                    if _idle(bot):
                        bot.log.info(f"아르바이트 '{title}': 채집 완료 → 완료하러 이동")
                        _press_progress(bot, title)
                    else:
                        bot.log.info(f"아르바이트 '{title}': 채집 완료 → 게임이 완료하러 가는 중")
                        _fast_travel(bot)
                    idle_since = None
                    continue
                if gather.stalled:
                    # 물품이 없는 게 아니라 채집이 막힌 것 (길이 막힘·전투 등) → '사람 몫' 이 아니라 다음에 다시 해 볼 일
                    bot.log.warning(f"아르바이트 '{title}': 채집이 {a['gather_timeout']}초째 늘지 않음 ({', '.join(missing_items(job))}) → {bot.snapshot('arbeit_gather').name}")
                    _leave(bot, ctx)
                    return "gather_stall"
            seen = mon.check(ctx)
            if seen.finish:
                _leave(bot, ctx)
                return seen.finish.result
            if ctx.take("gather"):  # 점검자가 '구하는 방법' 으로 채집하러 보냈다
                gather, last_check = Progress(stall=a["gather_timeout"]), time.monotonic()
                work.poke()
            if ctx.take("confirmed") and _finished(bot, title):  # 퀘스트 클리어 확인
                return "done"
            if seen.done:
                idle_since = None
                continue
            if seen.what == d.MAIN and not seen.idle and not gather:
                # 패킷 상태가 끝 신호를 놓쳐 '이동 중' 등으로 남으면 멈춘 캐릭터 앞에서 8분을 기다렸다
                # ('행운의 편지' 첫 전달 뒤, 2026-10-28 07:06~07:14) → 오래가면 CLI 로 다시 보고 멈췄으면 멈춘 것으로
                busy_since = busy_since or time.monotonic()
                if time.monotonic() - busy_since > a.get("busy_recheck", 40) and d.cli_idle(bot):
                    if not busy_told:
                        bot.log.warning(f"아르바이트 '{title}': {time.monotonic() - busy_since:.0f}초째 '{d.busy_why(bot)}' 인데 "
                                        f"CLI 는 멈춤 → 멈춘 것으로 봄")
                        busy_told = True
                    seen.idle = True
            else:
                busy_since, busy_told = None, False
            if seen.what == d.MAIN and seen.idle and not gather:
                idle_since = idle_since or time.monotonic()
                # NPC 대화를 마친 뒤에는 짧게 — 'NPC 와 대화' 조건을 채워도 게임이 다음 걸음으로 가지 않는다 (2026-10-26 사용자)
                if time.monotonic() - idle_since < (a.get("idle_wait_after_talk", 3) if ctx.talked else a["idle_wait"]):
                    continue
                job = next((j for j in accepted(bot) if _same(j["title"], title)), None)
                if job is None and not untracked:
                    if _finished(bot, title):
                        return "done"  # 확인 창 없이 끝나는 일
                    # 추적 칸(CLI)에 끝내 안 나오는 일이 있다 — '행운의 편지' 는 진행 중에도 get_quests 에 없어 여기서
                    # 소리 없이 되돌기만 하며 NPC 사이에서 몇 분씩 서 있었다 (2026-10-28 07:06~07:14, 09:11~09:13).
                    # 두 번 거푸 안 보이면 추적 칸 없이 진행하기로 민다 (끝남은 퀘스트 클리어 '확인' 으로 안다)
                    unseen += 1
                    if unseen < 2:
                        idle_since = None
                        continue
                    untracked = True
                    bot.log.info(f"아르바이트 '{title}': 추적 칸(CLI)에 안 나옴 → 조건을 보지 않고 진행하기로 민다")
                # '주변을 살펴보는 중' 같은 짧은 동작은 CLI 에 진행 중으로 안 나온다 → 조건이 바뀌었으면 나아간 것으로 본다
                sig = [(o.get("Description"), o.get("Count")) for o in job["objectives"]] if job else None
                if sig != last_sig:
                    last_sig, pushes = sig, 0
                if pushes >= a["max_pushes"]:
                    break
                pushes += 1
                ctx.talked = False
                bot.log.info(f"아르바이트 '{title}': 멈춰 있음 → 진행하기 ({pushes})")
                if not _press_progress(bot, title):
                    break
                idle_since = None
                continue
            idle_since = None
    except Stuck as e:
        bot.log.warning(f"아르바이트 '{title}': {e}")
        _leave(bot, ctx)
        return "stuck"
    bot.log.warning(f"아르바이트 '{title}': 끝나지 않음 → {bot.snapshot('arbeit_stuck').name}")
    _leave(bot, ctx)
    return "stuck"


def _apply_top(bot: Bot) -> bool | None:
    """맨 위 '지원하기' → 이동 → 수락. 수락했으면 True, 지원할 일이 없으면 False, 눌렀는데 수락하지 못했으면 None,
    '구인 마감' 도 '지원하기' 도 못 읽었으면 'missing'.
    가는 길과 NPC 대화는 점검자가 본다: 메뉴가 늦게 떠도 '수락' 이 보일 때 누른다 — 기다리던 쪽이 '대화 넘기기' 를 눌러
    수락을 놓치고 3분을 기다린 적이 있다 (2026-10-26 10:34). 수락 전에 대화가 끝나면 한 번 더 지원한다."""
    a = bot.cfg["arbeit"]
    mon = monitor.of(bot)
    ctx = Ctx("arbeit", "지원하기", menus=True)
    missing = False

    def do():
        nonlocal missing
        # 목록이 보이는데 '지원하기' 를 못 읽고 그냥 닫은 적이 있다 (2026-10-29 13:33, 0개 완료인데 OK) →
        # '구인 마감' 이 아니면 창을 다시 열어 한 번 더 보고, 그래도 없으면 읽은 글자와 화면을 남기고 실패로
        for n in range(1, 3):
            open_arbeit_tab(bot)
            b = _find_card_button(bot, None, APPLY)
            if b:
                break
            read = getattr(bot, "_arb_read", [])
            closed = any(w in _norm(t) for page in read for t in page for w in gd.words("arbeit_closed"))
            if closed:
                bot.to_main()
                return False
            bot.log.warning(f"아르바이트: 목록에서 '지원하기' 를 못 찾음 ({n}/2) — 읽은 글자 {read} "
                            f"→ {bot.snapshot('arbeit_no_apply').name}")
            bot.to_main()
            bot.sleep(1.5, 2)
        else:
            missing = True
            return False
        bot.click(b)
        bot.sleep(2, 2.5)
        _fast_travel(bot)
        return True

    def started():  # 이동이나 대화가 시작됐나 — 엉뚱한 창(주간 미션 등)이 열렸으면 180초를 기다리지 않게 (2026-10-26 10:51)
        return bot.auto_traveling() or bot.dialogue_playing() or bot.exists(a["accept"])

    for n in range(1, 3):
        r = mon.act(ctx, "지원하기", do, started, within=15, tries=1)
        if r is False:
            return "missing" if missing else False
        end, still = time.monotonic() + a["travel_timeout"], 0
        while r and time.monotonic() < end:
            seen = mon.check(ctx)
            if seen.done == "수락":
                mon.settle(Ctx("arbeit", menus=True))  # 수락 뒤 이어지는 대사
                return True
            if seen.finish:
                break
            if seen.what == d.MAIN and seen.idle:
                still += 1
                if still >= 4:
                    break  # 이동도 대화도 끝났는데 수락하지 못했다
            else:
                still = 0
                if seen.what == d.MAIN:
                    _fast_travel(bot)
            bot.sleep(0.5, 0.8)
        bot.log.warning(f"아르바이트: 지원하기 뒤 수락하지 못함 ({n}/2) → {bot.snapshot('arbeit_apply').name}")
        mon.leave(ctx)
    return None


def verify(bot: Bot, cfg: dict) -> bool:
    """수락해 둔 아르바이트가 남지 않았으면 완료. 포기한 일(가공품 부족 등)이 남아 있으면 '남음(직접)'.
    CLI 는 추적 중인 일 하나만 보여 주므로 퀘스트 창 목록의 '진행하기' 카드로 본다."""
    if accepted(bot):
        return False
    if getattr(bot, "_arb_closed", False):
        return True  # 숙제 끝에 본 목록이 '구인 마감' (남은 일 없음) — 창을 또 열지 않는다
    left = _panel_jobs(bot)
    bot.to_main()
    return not left


def run(bot: Bot, cfg: dict) -> str:
    """NPC 대화를 스스로 다루는 일 — 그동안 대화는 끼어들기로 넘기지 않는다 (Bot.npc_talk, monitor.interrupts)."""
    with bot.npc_talk():
        return _task(bot, cfg)


def _task(bot: Bot, cfg: dict) -> str:
    if not bot.state.available():
        raise CannotProceed("아르바이트는 진행 상태 확인에 CLI 가 필요함")
    a = cfg["arbeit"]
    done, skipped, stuck = [], {}, []
    unconfirmed = 0  # 지원했는데 수락한 일이 안 보인 횟수
    book = _book(bot) or {}
    # 아르바이트 탭 카드 제목을 먼저 읽어 둔다 — 고정해 둔 사이드 퀘스트를 아르바이트로 알지 않게 (accepted)
    bot._arb_titles = set()
    _panel_jobs(bot)
    bot.to_main()
    # 오늘 앞 실행에서 물품 부족으로 건너뛴 일은 다시 가 보지 않는다 (사람 몫). 막혔던 일은 다시 해 본다
    skipped.update(book.get("skipped") or {})
    # 다만 그 사이 물품이 다 모였으면 (채집을 시간으로 끊었는데 게임이 마저 캔 경우) 다시 해 본다
    for j in accepted(bot):
        for t in [t for t in skipped if _same(t, j["title"])]:
            if not missing_items(j):
                bot.log.info(f"아르바이트 '{t}': 건너뛴 일인데 물품이 다 모임 → 다시 진행")
                skipped.pop(t)
    if book.get("current"):
        bot.log.info(f"아르바이트 지난 기록: '{book['current']}' {book.get('stage', '')} ({book.get('at', '')}) → 이어서")

    def save(title=None, key="arb_job", stage="진행"):
        _note(bot, title, key, stage, done=[*dict.fromkeys([*(book.get("done") or []), *done])], skipped=skipped, stuck=stuck)

    for _ in range(a["max_jobs"]):
        pressed = False
        # 물품이 모자라도 바로 건너뛰지 않는다 — 진행하기를 누르면 게임이 '구하는 방법'(채집 장소)을 알려 주고,
        # 그걸 고르면 필요한 만큼만 채집한다. 구할 방법이 없을 때만 _work 가 'short' 로 돌려준다
        jobs = [j for j in accepted(bot) if not any(_same(j["title"], e) for e in [*skipped, *stuck])]
        job = jobs[0] if jobs else None
        if job is None:
            # 추적 중이 아닌 수락한 일 (앞 실행에서 막혔거나 사람이 받아 둔 일) 부터 이어 한다
            title = _press_other(bot, [*skipped, *stuck, *done])
            if title:
                bot.log.info(f"아르바이트 이어서 진행: {title}")
                # 추적 칸에 안 보여도 그만두지 않는다 — 진행하기로 바로 NPC 대화([결과 보고] 메뉴)가 열리면 추적 칸이
                # 가려져 CLI 에 안 나온다 (2026-10-22 '별과 돌이 빚은 광석'). _work 가 화면을 보고 처리한다.
                # 이미 '진행하기' 를 눌러 이동·대화가 시작됐다 → 또 누르지 않고 바로 화면 반응으로 (2026-10-22:
                # 또 누르려고 퀘스트 창을 열다 NPC 대화와 겹쳐 '메인 화면으로 돌아오지 못함' 으로 실패)
                job, pressed = {"title": title}, True
                # 카드 제목을 못 읽고(OCR) 눌렀더니 이미 막혔거나 건너뛴 일이었다 (2026-10-26 08:05 '뱅가드 브리치'를
                # 막힘 처리 직후 또 가서 8분을 더 씀) → 하지 않고 끝낸다. 제목 모를 카드를 또 누르게 되므로 목록도 여기까지
                if any(_same(title, e) for e in [*skipped, *stuck, *done]):
                    bot.log.info(f"아르바이트 '{title}': 이미 막힘·건너뜀으로 본 일 → 이번엔 그만")
                    _leave(bot)
                    break
        if job is None and getattr(bot, "_arb_closed", False):
            break  # 방금 본 목록이 '구인 마감' — 지원하러 창을 또 열 필요 없다
        if job is None:
            # 할 수 있는 수락한 일이 없으면 새 일에 지원한다
            before = {j["title"] for j in accepted(bot, raw=True)}
            applied = _apply_top(bot)
            if applied == "missing":
                stuck.append("(지원하기를 못 찾음)")
                break
            if applied is None:
                stuck.append("(지원 후 수락 대화 없음)")
                break
            if not applied:
                break
            # 수락 직후 후속 대화가 남아 있을 수 있다 → _work 가 정리하며 진행한다.
            # 추적 칸은 대화·이동이 끝나야 떠서 CLI 에 늦게 나온다 (2026-10-23: 2~3초만 보고 '수락 확인 실패' 로 FAIL)
            new = []
            for _ in range(8):
                new = [j for j in accepted(bot, raw=True) if j["title"] not in before]
                if new:
                    break
                bot.sleep(1.5, 2)
            if new:
                bot.log.info(f"아르바이트 지원: {new[0]['title']}")
                bot._arb_titles = {*(getattr(bot, "_arb_titles", None) or ()), new[0]["title"]}
                unconfirmed = 0
            else:
                # 그래도 안 보이면 퀘스트 창 목록(_press_other)에서 '진행하기' 카드로 찾는다. 두 번 거푸면 그만
                unconfirmed += 1
                bot.log.info("아르바이트 지원: 추적 칸에 안 보임 → 퀘스트 창 목록으로 확인")
                if unconfirmed >= 2:
                    stuck.append("(지원 후 수락 확인 실패)")
                    break
            continue
        if "objectives" in job and (alter := alter_missing(job)):
            bot.log.info(f"아르바이트 '{job['title']}': 가공품이 모자람 ({', '.join(alter)}) → 가지 않고 건너뜀")
            skipped[job["title"]] = "가공 필요"
            save(None, "arb_result", f"건너뜀(가공): {job['title']}")
            continue
        bot.log.info(f"아르바이트 진행: {job['title']}")
        save(job["title"])
        if not pressed and not _press_progress(bot, job["title"]):
            stuck.append(job["title"])
            continue
        r = _work(bot, job["title"])
        if r == "done":
            done.append(job["title"])
            bot.log.info(f"아르바이트 완료: {job['title']}")
        elif r == "short":
            skipped[job["title"]] = "전달 물품 부족"
        elif r == "alter":
            skipped[job["title"]] = "가공 필요"
        elif r == "dungeon":
            skipped[job["title"]] = "던전 클리어 필요"
        else:  # stuck · gather_stall — 다음 실행 때 다시 해 본다
            stuck.append(job["title"] + (" (채집이 멈춤)" if r == "gather_stall" else ""))
        save(None, "arb_result", {"done": "완료", "short": "건너뜀", "alter": "건너뜀(가공)", "dungeon": "건너뜀(던전)",
                                  "gather_stall": "막힘(채집이 멈춤)"}.get(r, "막힘")
             + f": {job['title']}")
    save(None, "arb_end", "아르바이트 목록 끝")
    _leave(bot)
    out = f"아르바이트 {len(done)}개 완료"
    if skipped:
        out += ", 건너뜀: " + ", ".join(f"{t}({w})" for t, w in skipped.items())
    if stuck:
        # 막힌 일은 사람 몫이 아니라 다시 해 볼 일 → 실패로 남겨 다음 실행 때 이어 한다 ('남음(직접)' 은 물품 부족만)
        raise CannotProceed(out + ", 막힘: " + ", ".join(dict.fromkeys(stuck)))
    return out
