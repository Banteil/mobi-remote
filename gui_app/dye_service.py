"""염색 도우미의 파이썬 쪽: 게임 창 캡처 → DyeTracker → 게임 위 표시 창(Qt) + 화면(웹)에 상태 보내기.

게임 창 클라이언트 영역만 찍는다 (예전엔 주 모니터 전체 — 게임이 다른 모니터·창모드면 어긋났다).
팔레트 자리를 게임 화면 비율로 두므로 해상도가 달라도 같다. 우리 창은 캡처에서 빠지므로(exclude_from_capture)
게임 위에 겹쳐도 찍히지 않는다.

검출은 파이썬(mabi/dye)이 하고 게임 위 표시 창에 그린다. 리모콘 화면(웹)에는 켜짐·팔레트 찾음만 보낸다
— 염색하는 동안은 게임을 보고 있어 리모콘의 상태 표·미리보기는 보이지도 않았다 (2026-10-31 뺌).

맞출 자리 안내·자동 맞추기 (mabi/dye/autofit): 팔레트가 막 열린 첫 안정 화면(늘 위치 0·회전 0·배율 1)으로
팔레트를 복원해 두고, 화면이 멈출 때마다 지금 상태를 재 '해 텍셀이 지금 어디 있나'를 그린다. 계산은 몇 초씩
걸려 작업 스레드(_Jobs)에서 한다 — 일하다 틈틈이 쉬어(fit.Duty) 캡처·흑백 강조가 밀리지 않게.
안내를 끄면 시작 화면만 잡아 두고 계산하지 않는다 (자동 맞추기를 누르면 그때 한다).
켜기 전에 이미 열려 있던 팔레트는 시작 상태를 몰라 안내하지 않는다.
"""
import logging
import re
import threading
import time

import mss
import numpy as np
from PySide6.QtCore import QObject, QRectF, Signal

from mabi.dye import autofit as AF
from mabi.dye import draw as ddraw
from mabi.dye import detect as D
from mabi.dye import fit as FT
from mabi.dye import materials as MT
from mabi.dye.tracker import DyeTracker
from mabi.window import GameWindow

from .dye_tab import AreaEditor, Overlay, exclude_from_capture
from .queue_overlay import to_logical

TICK = 0.12
LIGHT = (5, 90, 35)  # 흑백 밝기 % (최소, 최대, 기본)
START_STILL = 3      # 팔레트가 뜬 뒤 이만큼 이어 멈춘 화면이면 시작 화면으로 잡는다 (열리는 연출·카운트다운 피하기)
START_AFTER = 0.8    # 뜬 뒤 최소 이만큼 (초)

log = logging.getLogger("mabi")


def clean_view(v) -> dict:
    """보기 설정 (설정 파일 dyeView): gray 흑백 강조, light 흑백 밝기 %, area 팔레트 자리 비율 (None = 기본),
    marks 1·2·3번 칸 표시 색 (점·스포이드 테·딱지 — 잘못된 칸은 기본색), still 돌리는 동안 점 끄기,
    guide 맞출 자리 안내."""
    v = v if isinstance(v, dict) else {}
    mk = v.get("marks") if isinstance(v.get("marks"), list) else []
    marks = [str(mk[i]).upper() if i < len(mk) and isinstance(mk[i], str) and re.fullmatch(r"#[0-9a-fA-F]{6}", mk[i])
             else ddraw.MARKS[i] for i in range(3)]
    a = v.get("area")
    ok = (isinstance(a, (list, tuple)) and len(a) == 4
          and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in a)
          and 0 <= a[0] < 1 and 0 <= a[1] < 1 and 0.05 <= a[2] <= 1 and 0.05 <= a[3] <= 1)
    lt = v.get("light")
    lt = LIGHT[2] if not isinstance(lt, (int, float)) or isinstance(lt, bool) else int(min(LIGHT[1], max(LIGHT[0], lt)))
    return {"gray": v.get("gray") is True, "light": lt, "area": [round(float(x), 5) for x in a] if ok else None,
            "marks": marks, "still": v.get("still") is True,
            # 맞출 자리 안내는 보류 — 상시 계산 대신 단축키로 지금 화면 기준 계산하는 쪽으로 다시 설계한다 (2026-10-31)
            "guide": False}


class _ToGui(QObject):
    state = Signal(object, object)
    stopped = Signal()


class _Jobs:
    """작업 스레드 하나. 이름마다 가장 마지막에 넣은 일만 남기고, 넣은 순서와 상관없이 PRIORITY 순으로 한다
    (화면이 멈출 때마다 넣는 상태 재기가 쌓이지 않게)."""
    PRIORITY = ("build", "solve", "pose")

    def __init__(self):
        self.cv = threading.Condition()
        self.todo: dict = {}
        threading.Thread(target=self._run, name="dye-fit", daemon=True).start()

    def put(self, name, fn) -> None:
        with self.cv:
            self.todo[name] = fn
            self.cv.notify()

    def clear(self) -> None:
        with self.cv:
            self.todo.clear()

    def _run(self) -> None:
        FT.pausing(FT.Duty())
        while True:
            with self.cv:
                while not self.todo:
                    self.cv.wait()
                name = next(n for n in self.PRIORITY if n in self.todo)
                fn = self.todo.pop(name)
            try:
                fn()
            except Exception:
                log.exception("염색 자리 계산 실패 (%s)", name)


class DyeService:
    def __init__(self, presets, emit, title: str, cache_dir=None):
        """presets: PresetStore · emit(채널, 값): 화면 이벤트 · title: 게임 창 제목 ·
        cache_dir: 게임에서 꺼낸 재질 그림을 둘 곳 (없으면 재질 섞인 옷도 한 재질처럼 계산)."""
        self.presets, self.emit = presets, emit
        self.game = GameWindow(title)
        self.overlay: Overlay | None = None
        self.gui = _ToGui()
        self.gui.state.connect(self._paint)
        self.gui.stopped.connect(self._hide)
        self.thread: threading.Thread | None = None
        self.running = False
        self.tracker: DyeTracker | None = None
        self.win = None  # 메인 창 (캡처에서 뺀다)
        self.view = clean_view(None)
        self.editor: AreaEditor | None = None
        # 맞출 자리 안내·자동 맞추기
        self.cache_dir = cache_dir
        self.jobs = _Jobs()
        self._refs = None             # 재질 그림 (처음 쓸 때 읽는다)
        self._rect_last = None
        self.auto_stop: threading.Event | None = None
        self._fit_reset(closed=False)

    # ---- 제어 (작업 스레드에서 불려도 된다) ----
    def start(self) -> dict:
        if self.running:
            return {"ok": True}
        cur = self.presets.current() or {}
        self.tracker = DyeTracker()
        self.tracker.set_targets(cur.get("colors"), cur.get("tol"))
        self._fit_reset(closed=False)  # 닫힌 것을 한 번 봐야 다음에 뜨는 팔레트를 시작 상태로 믿는다
        self.set_view(self.view)
        self.running = True
        self.thread = threading.Thread(target=self._loop, name="dye", daemon=True)
        self.thread.start()
        try:
            self.game.focus()  # 리모콘에서 켜면 바로 게임에서 팔레트를 만질 수 있게
        except RuntimeError:
            pass  # 게임이 없으면 뜰 때까지 기다린다 (_loop)
        self.emit("mm:dye-state", {"started": True})  # 단축키로 켰을 때도 화면 단추가 따라오게
        return {"ok": True}

    def stop(self) -> dict:
        self.running = False
        if self.auto_stop:
            self.auto_stop.set()
        if self.thread:
            self.thread.join(2)
        self._fit_reset(closed=False)   # 돌던 계산도 끊는다 (세션이 바뀌면 멈춘다)
        self.gui.stopped.emit()
        return {"ok": True}

    def retarget(self) -> None:
        """프리셋·색·오차가 바뀌면 다음 바퀴에 다시 찾는다."""
        if self.tracker:
            cur = self.presets.current() or {}
            self.tracker.set_targets(cur.get("colors"), cur.get("tol"))
            if self.sess:
                self._solve()

    def set_view(self, view: dict) -> None:
        self.view = clean_view(view)
        if self.tracker:
            v = self.view
            self.tracker.set_view(v["area"], v["gray"], v["light"] / 100, v["still"])
            if v["guide"]:
                self._kick()   # 안내를 이제 켰으면 잡아 둔 시작 화면으로 계산

    def edit_area(self, on_done) -> dict:
        """화면 스레드에서. 게임 위에 그리기 창을 띄운다. 다 그리면 가까운 테두리에 맞춰 on_done(비율 | None)."""
        rect = self._rect()
        if rect is None:
            return {"error": "게임 창을 찾지 못했습니다"}
        _, lx, ly, r = to_logical(rect)

        def done(area):
            if area is not None:
                area = self._snap(area)
            on_done(area)
        if self.editor:
            self.editor.close()
        self.editor = AreaEditor(QRectF(lx, ly, rect[2] / r, rect[3] / r), self.view["area"] or D.PALETTE_AT, done)
        self.editor.show()
        exclude_from_capture(self.editor)  # 맞출 때 찍는 화면에 우리 창이 섞이지 않게
        self.editor.activateWindow()
        self.editor.setFocus()
        return {"ok": True}

    def _snap(self, area):
        """그린 사각형(비율)을 지금 게임 화면의 가까운 테두리에 맞춘다. 못 찍으면 그린 대로."""
        rect = self._rect()
        if rect is None:
            return area
        with mss.mss() as sct:
            img = np.asarray(sct.grab({"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]}))
        f = D.Frame(img)
        px = D.Rect(D.jround(area[0] * f.w), D.jround(area[1] * f.h), D.jround(area[2] * f.w), D.jround(area[3] * f.h))
        return list(D.area_of(f, D.snap_area(f, px)))

    def _rect(self):
        """게임 창 클라이언트 영역 (x, y, w, h) 실제 픽셀. 없거나 내려가 있으면 None."""
        try:
            r = self.game.client_rect()
        except RuntimeError:
            return None
        return (r.left, r.top, r.width, r.height) if r.width > 0 and r.height > 0 else None

    # ---- 캡처 루프 ----
    def _loop(self) -> None:
        with mss.mss() as sct:
            while self.running:
                t0 = time.monotonic()
                rect = self._rect()
                if rect is None:
                    time.sleep(1)
                    continue
                img = np.asarray(sct.grab({"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]}))
                try:
                    st = self.tracker.tick(img)
                except Exception as e:  # 한 바퀴 실패로 도우미가 죽지 않게
                    self.emit("mm:dye-state", {"error": str(e)})
                    time.sleep(1)
                    continue
                self._rect_last = rect
                try:
                    self._fit_tick(img, st)
                except Exception:
                    log.exception("염색 자리 안내 실패")
                if st.redraw:
                    self.gui.state.emit(st, rect)
                rest = TICK - (time.monotonic() - t0)
                if rest > 0:
                    time.sleep(rest)

    # ---- 맞출 자리 안내·자동 맞추기 ----
    def _fit_reset(self, closed: bool) -> None:
        self.jobs.clear()
        self.sess: AF.Session | None = None
        self.guide: dict | None = None  # {'points', 'text', 'done'} — autofit.Session.guide
        self.fit_text = ""            # 계산 중 알림 (있으면 guide 문구 대신)
        self._key = None              # 세션을 만든 팔레트 자리
        self._fresh = closed          # 이번에 뜬 팔레트를 처음부터 봤나
        self._opened = 0.0
        self._still = 0
        self._building = False
        self._start = None            # 시작 화면 (frame, box, rings, skip) — 계산은 필요할 때
        self._want_auto = False       # 자리를 찾으면 바로 자동 맞추기

    def _repaint(self) -> None:
        if self.tracker and self._rect_last and self.running:
            self.gui.state.emit(self.tracker.last, self._rect_last)

    def _say(self, text: str) -> None:
        self.fit_text = text
        self._repaint()

    def _fit_tick(self, img, st) -> None:
        tr = self.tracker
        if st.status != "active" or tr.box is None:
            if self._key is not None:
                if self.auto_stop:
                    self.auto_stop.set()
                self._fit_reset(closed=True)
            self._fresh = True
            return
        b = tr.box
        key = (b.x, b.y, b.w, b.h)
        if key != self._key:          # 새로 떴다
            fresh = self._fresh and self._key is None   # 자리만 바뀐 것(자리 고치기)은 처음이 아니다
            self._fit_reset(closed=False)
            self._key, self._fresh, self._opened = key, fresh, time.monotonic()
        if self._start is None:
            if not tr.lead or not tr.lead.rings:
                return
            if not self._fresh:
                self.fit_text = "자리 안내는 팔레트를 열기 전에 염색 도우미를 켜 두어야 합니다"
                return
            self._still = self._still + 1 if (tr.lead_ok and not tr.moving) else 0
            if self._still >= START_STILL and time.monotonic() - self._opened >= START_AFTER:
                self._start = (np.array(img[..., :3]), b, list(tr.lead.rings), list(tr.lead.skip))
                self.emit("mm:dye-state", {"found": True, "fit": True})
                if self.view["guide"]:
                    self._kick()
            return
        if self.sess is None or self.auto_stop is not None or not self.view["guide"]:
            return                    # 아직 계산 전·자동 맞추기 중(그쪽이 잰다)·안내 꺼짐
        if tr.moving:
            if self.guide and self.guide.get("points"):
                self.guide = {**self.guide, "points": []}   # 움직이는 동안엔 지난 점이 틀리다
        elif st.redraw and self.sess.goal is not None:
            frame = np.array(img[..., :3])
            # 화면 고리 색이 이미 모두 목표 안이면 계산보다 화면을 믿는다
            caught = bool(st.rings) and all(r.slot >= 0 for r in st.rings) and len(st.rings) >= len(self.sess.use)
            self.jobs.put("pose", lambda: self._pose(frame, caught))

    def _materials(self):
        if self._refs is None and self.cache_dir is not None:
            try:
                self._refs = MT.load(self.cache_dir, MT.game_dir_of(self.game.hwnd)) or {}
            except Exception:
                log.exception("염색 재질 그림을 읽지 못함")
                self._refs = {}
        return self._refs or None

    def _kick(self) -> None:
        """잡아 둔 시작 화면으로 팔레트 읽기 → 자리 찾기 (이미 했거나 하는 중이면 그대로)."""
        if self._start is None or self.sess is not None or self._building:
            return
        self._building = True
        frame, box, rings, skip = self._start
        self._say("팔레트 읽는 중…")
        self.jobs.put("build", lambda: self._build(frame, box, rings, skip))

    def _build(self, frame, box, rings, skip) -> None:
        t0 = time.monotonic()
        try:
            sess = AF.Session(frame, box, rings, skip, self._materials())
        except Exception:
            self._building = False
            self._say("팔레트를 읽지 못했습니다")
            raise
        if self._key != (box.x, box.y, box.w, box.h):
            return                    # 그새 닫혔다
        log.info("염색 팔레트 복원 %.1fs, 재질 %s", time.monotonic() - t0, sess.mats)
        sess.last = ((0.0, 0.0), 0.0, 1.0, 0, 1.0)
        self.sess = sess
        self._building = False
        self._solve()

    def _solve(self) -> None:
        sess, targets = self.sess, self.tracker.slot_targets() if self.tracker else []
        if not sess:
            return
        self._say("맞출 자리 찾는 중…")

        def run():
            t0 = time.monotonic()
            ok = sess.solve(targets, stop=lambda: self.sess is not sess)
            if self.sess is not sess:
                return
            log.info("염색 자리 찾기 %.1fs: %s", time.monotonic() - t0,
                     f"회전 {sess.goal[0]:.1f}° 배율 {sess.goal[1]:.3f} 오차 ×{sess.approx:g}" if ok else "없음")
            self.guide = sess.guide(sess.last)
            self.fit_text = ""
            stop = self.auto_stop
            if self._want_auto and stop is not None and not stop.is_set():
                self._want_auto = False
                if ok:
                    threading.Thread(target=self._auto_run, args=(sess, stop), name="dye-auto", daemon=True).start()
                    return
                self.auto_stop = None
                self.emit("mm:dye-state", {"auto": False})
            self._repaint()
        self.jobs.put("solve", run)

    def _pose(self, frame, caught) -> None:
        sess = self.sess
        if not sess or sess.goal is None or self.auto_stop is not None:
            return
        m = sess.pose(frame)
        if self.sess is sess and self.auto_stop is None:
            self.guide = sess.guide(m, caught)
            self._repaint()

    def autofit(self) -> dict:
        """자동 맞추기 — 다시 누르면 멈춘다. 게임에서 키를 눌러도 멈춘다."""
        if self.auto_stop is not None:
            self.auto_stop.set()
            return {"ok": True, "stopped": True}
        sess = self.sess
        if not self.running:
            return {"error": "염색 도우미가 꺼져 있습니다"}
        if self._start is None:
            return {"error": "팔레트를 열기 전에 염색 도우미를 켜 두어야 합니다" if self._key and not self._fresh
                    else "팔레트를 아직 읽지 못했습니다"}
        if sess is not None and sess.goal is None and not self.fit_text:
            return {"error": "이 색 조합이 되는 자리를 찾지 못했습니다"}
        stop = threading.Event()
        self.auto_stop = stop
        self.emit("mm:dye-state", {"auto": True})
        if sess is not None and sess.goal is not None:
            threading.Thread(target=self._auto_run, args=(sess, stop), name="dye-auto", daemon=True).start()
        else:                         # 아직 계산 전·중 — 자리를 찾으면 바로 시작
            self._want_auto = True
            self._kick()
        return {"ok": True}

    def _auto_run(self, sess, stop) -> None:
        from mabi.inputs import ManualInputWatcher
        watch = ManualInputWatcher(lambda: self.game.hwnd, lambda what: stop.set())

        def show(gd):
            self.guide = gd
            self._repaint()
        try:
            self.game.focus()
            time.sleep(0.3)
            with mss.mss() as sct:
                def snap():
                    rect = self._rect()
                    if rect is None:
                        return None
                    return np.asarray(sct.grab({"left": rect[0], "top": rect[1], "width": rect[2], "height": rect[3]}))

                def to_screen(x, y):
                    rect = self._rect() or (0, 0, 0, 0)
                    return rect[0] + x, rect[1] + y

                drv = AF.AutoDriver(sess, snap, AF.Mouse(to_screen, stop.is_set), stop,
                                    lambda m, what: show({"points": [], "text": f"자동 맞추는 중 — {what}", "done": False}))
                try:
                    ok, m = drv.run()
                    log.info("염색 자동 맞추기 %s", "맞춤" if ok else "못 맞춤")
                    gd = sess.guide(m)
                    if not ok and not gd["done"]:
                        gd = {**gd, "text": "자동으로 다 맞추지 못했습니다 — " + gd["text"]}
                    show(gd)
                except AF.Stopped:
                    show({"points": [], "text": "자동 맞추기를 멈췄습니다", "done": False})
        except Exception:
            log.exception("염색 자동 맞추기 실패")
            show({"points": [], "text": "자동 맞추기 중 오류가 났습니다", "done": False})
        finally:
            watch.close()
            self.auto_stop = None
            self.emit("mm:dye-state", {"auto": False})
            self._repaint()

    # ---- 화면 스레드 ----
    def _ensure_overlay(self, screen) -> Overlay:
        if self.overlay is None:
            self.overlay = Overlay()
        if self.overlay.geometry() != screen.geometry():
            self.overlay.place(screen)  # 게임이 있는 모니터 전체
        if not self.overlay.isVisible():
            self.overlay.show()
            exclude_from_capture(self.overlay)
            if self.win:
                exclude_from_capture(self.win)
        return self.overlay

    def _hide(self) -> None:
        if self.overlay:
            self.overlay.items = []
            self.overlay.hide()
        if self.win:
            exclude_from_capture(self.win, False)
        self.emit("mm:dye-state", {"stopped": True})

    def _paint(self, st, rect) -> None:
        # 캡처는 게임 창 실제 픽셀, 그리기는 그 모니터의 논리 픽셀
        screen, lx, ly, r = to_logical(rect)
        ov = self._ensure_overlay(screen)
        g = screen.geometry()
        scale = 1 / r
        guide = None
        if not st.hidden and (self.view["guide"] or self.auto_stop is not None):
            gd = self.guide or {}
            text = self.fit_text or gd.get("text", "")
            guide = {"points": gd.get("points", []), "text": text, "done": gd.get("done", False)} if text else None
        ov.items = [] if st.hidden else ddraw.overlay_items(st, scale=scale, origin=(lx - g.x(), ly - g.y()),
                                                             screen_w=g.width(), measure=ov.measure,
                                                             slots=self.view["marks"], guide=guide)
        ov.update()
        self.emit("mm:dye-state", {"found": st.palette is not None, "text": st.text, "fit": self._start is not None})
