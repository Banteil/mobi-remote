'use strict';
/**
 * window.mm — 화면(이 웹 페이지)이 파이썬 쪽을 부르는 유일한 통로.
 *
 * 레거시(Electron)에서는 preload.js 가 같은 이름의 IPC 를 노출했다. 화면 코드(app.js)를 그대로 쓰려고
 * 같은 모양을 QWebChannel 위에 다시 만든다. 모든 호출은 Promise 를 돌려준다 (레거시도 ipcRenderer.invoke).
 *   mm.query('me') → backend.call(id, 'query', '["me"]') → 파이썬이 작업 스레드에서 처리 → reply(id, json)
 * 이벤트(파이썬 → 화면)는 backend.event(채널, json) 하나로 받아 채널별 구독자에게 나눠 준다.
 */
(function () {
  let seq = 0;
  const pending = new Map();
  const listeners = new Map();
  let resolveReady;
  const ready = new Promise((r) => { resolveReady = r; });

  function start() {
    // qwebchannel.js 는 Qt 가 qrc 로 넣어 준다 (index.html 에서 이 파일보다 먼저 읽는다)
    new QWebChannel(qt.webChannelTransport, (ch) => {
      const be = ch.objects.backend;
      be.reply.connect((id, json) => {
        const p = pending.get(id);
        if (!p) return;
        pending.delete(id);
        let v = null;
        try { v = JSON.parse(json); } catch (_) { /* 빈 응답 */ }
        if (v && v.__error) p.reject(new Error(v.__error)); else p.resolve(v);
      });
      be.event.connect((channel, json) => {
        let v = null;
        try { v = JSON.parse(json); } catch (_) { /* 값 없는 이벤트 */ }
        for (const cb of listeners.get(channel) || []) {
          try { cb(v); } catch (e) { console.error(e); }
        }
      });
      resolveReady(be);
    });
  }

  function call(method, ...args) {
    return ready.then((be) => new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      be.call(id, method, JSON.stringify(args));
    }));
  }

  function on(channel, cb) {
    if (!listeners.has(channel)) listeners.set(channel, new Set());
    listeners.get(channel).add(cb);
    return () => listeners.get(channel).delete(cb);
  }

  const c = (m) => (...a) => call(m, ...a);

  window.mm = {
    // 첫 페인트 전에 theme.js 가 읽는다. 파이썬이 페이지를 만들 때 window.__MM_INIT__ 로 심어 준다
    initialTheme: (window.__MM_INIT__ && window.__MM_INIT__.theme) || 'dark',
    appInfo: (window.__MM_INIT__ && window.__MM_INIT__.app) || {},
    // 표시 문구 표 (data/labels.json — 파이썬과 같은 파일)
    labels: (window.__MM_INIT__ && window.__MM_INIT__.labels) || {},

    status: c('status'),
    query: c('query'),
    queryMany: c('queryMany'),
    exec: c('exec'),
    cancel: c('cancel'),
    costOf: c('costOf'),
    capabilities: c('capabilities'),

    log: { tail: c('log.tail'), files: c('log.files'), open: c('log.open') },
    knowledge: {
      get: c('kn.get'), setSlots: c('kn.setSlots'), setLevel: c('kn.setLevel'), rules: c('kn.rules'),
      markFull: c('kn.markFull'), forgetRecipe: c('kn.forgetRecipe'),
    },
    cfg: { get: c('cfg.get'), sort: c('cfg.sort'), theme: c('cfg.theme'), set: c('cfg.set') },
    goal: { next: c('goal.next') },
    pl: {
      list: c('pl.list'), create: c('pl.create'), update: c('pl.update'), remove: c('pl.remove'),
      addTrack: c('pl.addTrack'), removeTrack: c('pl.removeTrack'), moveTrack: c('pl.moveTrack'),
    },
    planCraft: c('plan.craft'),
    planNeeds: c('plan.needs'),
    cli: { locate: c('cli.locate'), choose: c('cli.choose'), clearPath: c('cli.clearPath') },
    dye: {
      prefs: c('dye.prefs'), add: c('dye.add'), update: c('dye.update'), remove: c('dye.remove'), select: c('dye.select'),
      // 레거시는 화면(렌더러)이 캡처·검출을 했다. 이제 파이썬이 하고 결과만 mm:dye-state 로 보낸다
      start: c('dye.start'), stop: c('dye.stop'), shot: c('dye.shot'), snap: c('dye.snap'),
      onState: (cb) => on('mm:dye-state', cb),
    },
    update: {
      check: c('update.check'), download: c('update.download'), install: c('update.install'), page: c('update.page'),
      onProgress: (cb) => on('mm:update-progress', cb),
    },
    cursorNudge: c('cursor.nudge'),
    win: { narrow: c('win.narrow') },
    book: { stats: c('book.stats'), harvest: c('book.harvest') },
    // 작업 큐 — 주인은 파이썬 (mabi/workqueue.py). 화면은 상태를 받아 그리고 버튼만 보낸다
    queue: {
      state: c('queue.state'), add: c('queue.add'), remove: c('queue.remove'), move: c('queue.move'),
      playOne: c('queue.playOne'), pauseOne: c('queue.pauseOne'), pause: c('queue.pause'), halt: c('queue.halt'),
      playAll: c('queue.playAll'), tidy: c('queue.tidy'), clear: c('queue.clear'), edit: c('queue.edit'),
      patch: c('queue.patch'), answer: c('queue.answer'), history: c('queue.history'),
      onChange: (cb) => on('mm:queue', cb), onAsk: (cb) => on('mm:queue-ask', cb),
      onDone: (cb) => on('mm:queue-done', cb), onToast: (cb) => on('mm:queue-toast', cb),
    },
    fav: { all: c('fav.all'), toggle: c('fav.toggle'), clear: c('fav.clear') },
    version: { info: c('version.info'), check: c('version.check'), accept: c('version.accept') },
    cache: { list: c('cache.list'), clear: c('cache.clear') },
    openExternal: c('openExternal'),

    // 일일 숙제 (파이썬판에서 새로 생긴 것)
    daily: {
      state: c('daily.state'), stop: c('daily.stop'),
      settings: c('daily.settings'), saveSettings: c('daily.saveSettings'),
      shot: c('daily.shot'),
      openFolder: c('daily.openFolder'),
      onDisplay: (cb) => on('mm:display', cb),
      abyssSettings: c('daily.abyssSettings'), abyssStop: c('daily.abyssStop'),
      onAbyss: (cb) => on('mm:abyss', cb),
      onEvent: (cb) => on('mm:daily', cb),
      onLog: (cb) => on('mm:daily-log', cb),
    },
    chars: {
      list: c('chars.list'), save: c('chars.save'), nameNow: c('chars.nameNow'),
      pickPortrait: c('chars.pickPortrait'), clearPortrait: c('chars.clearPortrait'),
      scan: c('chars.scan'), scanStop: c('chars.scanStop'), applyScan: c('chars.applyScan'),
      onScan: (cb) => on('mm:chars-scan', cb),
    },

    onExecStart: (cb) => on('mm:exec-start', cb),
    onExecDone: (cb) => on('mm:exec-done', cb),
    onFacilityLevel: (cb) => on('mm:facility-level', cb),
  };

  start();
})();
