// 작업 큐 상태 기계 시험 (node tests/queue.test.js): app.js·daily.js 를 가짜 DOM·mm 위에 올리고 시나리오를 돌린다.
const fs = require('fs');
process.on('unhandledRejection', () => {}); process.on('uncaughtException', (e) => { if (!/LOADERS|is not a function/.test(String(e))) console.error('uncaught', e.message); });
const vm = require('vm');
const ROOT = require('path').join(__dirname, '..', 'web') + '/';

function any() {  // 무엇을 불러도·읽어도 되는 가짜
  const f = function () { return any(); };
  return new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => '';
      if (k === 'then') return undefined;
      if (k === 'length') return 0;
      if (k === Symbol.iterator) return function* () {};
      return any();
    },
    set() { return true; },
    apply() { return any(); },
  });
}

const calls = [];
let dailyWaiterFire = null;
const mm = new Proxy({}, { get: (t, k) => any() });
const mmReal = {
  labels: { queue_state: {} },
  queue: { load: async () => ({ items: [] }), save: async () => {}, record: async (r) => { calls.push(['record', r.label, r.result]); }, history: async () => [] },
  daily: new Proxy({
    start: async () => { calls.push(['daily.start']); return {}; },
    stop: async (end) => { calls.push(['daily.stop', end]); setTimeout(() => dailyWaiterFire && dailyWaiterFire({ type: 'done', results: [[1, 'STOP']] }), 5); },
    pauseCancel: async () => { calls.push(['daily.pauseCancel']); },
    abyssStop: async () => { calls.push(['abyssStop']); },
  }, { get: (t, k) => (k in t ? t[k] : any()) }),
  cancel: async () => {},
};
const ctx = {
  console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, Date, Math, JSON, Object, Array, String, Number,
  document: any(), window: any(), navigator: any(), localStorage: any(), location: any(), requestAnimationFrame: any(),
  getComputedStyle: any(), ResizeObserver: function () { return any(); }, MutationObserver: function () { return any(); },
  Image: function () { return any(); }, fetch: any(), alert: any(), performance: { now: () => Date.now() },
  mm: new Proxy(mmReal, { get: (t, k) => (k in t ? t[k] : any()) }),
};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
// index.html 의 script 순서대로 이어 붙여 읽는다 (같은 전역을 쓰는 여러 파일)
const order = [...fs.readFileSync(ROOT + 'index.html', 'utf8').matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]);
let src = "'use strict';\n" + order.map((f) => fs.readFileSync(ROOT + f, 'utf8').replace(/^'use strict';/, '')).join('\n;\n');
// const/let 은 vm 전역 객체에 안 붙는다 → 시나리오에서 쓰는 것만 밖으로 꺼낸다
src += `
;globalThis.__q = {
  get items() { return qItems; }, set items(v) { qItems = v; },
  get running() { return qRunning; }, get stop() { return qStop; },
  qTick, qStartNow, qPause, qRemove, qPlayAll, Q_KINDS,
  setBusy: (v) => { busy = v; },
  setDailyWaiter: (f) => { dlWaiter = f; },
};`;
try { vm.runInContext(src, ctx, { filename: 'web/*.js' }); } catch (e) { console.error('load error', e); process.exit(1); }
const Q = ctx.__q;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 숙제 runner 를 가짜로: start 후 dlWaiter 를 기다린다 (실제 runDailyItem 그대로, ensureDisplay 만 통과)
vm.runInContext('ensureDisplay = async () => true;', ctx);
// dlWaiter 를 바깥에서 부를 수 있게
dailyWaiterFire = (e) => vm.runInContext('dlWaiter', ctx) && vm.runInContext('dlWaiter', ctx)(e);

let actionRuns = 0;
Q.Q_KINDS.action.run = async (it) => { actionRuns++; calls.push(['action', it.label]); await sleep(10); return true; };

let failed = 0;
async function scenario(name, fn) {
  calls.length = 0; actionRuns = 0;
  Q.items = [];
  try { await fn(); console.log('PASS', name); } catch (e) { failed++; console.log('FAIL', name, '-', e.message); console.log(calls); }
}
function assert(c, m) { if (!c) throw new Error(m); }

(async () => {
  await sleep(200);  // 시작 코드(loadQueue 등)가 끝나길
  await scenario('지금 바로: 돌던 숙제는 대기로, 행동 먼저, 그다음 숙제 이어서', async () => {
    Q.items = [{ id: 1, kind: 'daily', status: 'wait', label: '일일 숙제', chars: [1] }];
    Q.qTick();
    await sleep(20);
    assert(Q.items[0].status === 'run', 'daily should run');
    Q.qStartNow({ id: 2, kind: 'action', status: 'wait', label: '채집' });
    await sleep(60);
    assert(calls.some((c) => c[0] === 'daily.stop' && c[1] === false), 'daily paused (not ended)');
    assert(actionRuns === 1, 'action ran');
    // 행동 끝 → 숙제 다시 start
    assert(calls.filter((c) => c[0] === 'daily.start').length === 2, 'daily restarted: ' + JSON.stringify(calls));
    dailyWaiterFire({ type: 'done', results: [[1, 'OK']] });
    await sleep(30);
    assert(!Q.running && Q.items.length === 0, 'queue drained');
  });

  await scenario('F12 로 숙제가 스스로 멈춤 → 일시정지, 뒤 카드는 안 돈다', async () => {
    Q.items = [{ id: 1, kind: 'daily', status: 'wait', label: '일일 숙제', chars: [1] },
               { id: 2, kind: 'action', status: 'wait', label: '채집' }];
    Q.qTick();
    await sleep(20);
    dailyWaiterFire({ type: 'done', results: [[1, 'STOP']] });
    await sleep(30);
    assert(Q.items[0].status === 'pause', 'daily pause, got ' + Q.items[0].status);
    assert(actionRuns === 0, 'action must not run');
    assert(!Q.running, 'queue stopped');
  });

  await scenario('▶ 전체 시작: 일시정지 카드부터 위에서 차례로', async () => {
    Q.items = [{ id: 1, kind: 'daily', status: 'pause', label: '일일 숙제', chars: [1] },
               { id: 2, kind: 'action', status: 'wait', label: '채집' }];
    Q.qPlayAll();
    await sleep(20);
    assert(Q.items[0].kind === 'daily' && Q.items[0].status === 'run', 'daily runs first');
    dailyWaiterFire({ type: 'done', results: [[1, 'OK']] });
    await sleep(40);
    assert(actionRuns === 1, 'then action');
    assert(Q.items.length === 0, 'all done & removed');
  });

  await scenario('돌던 숙제 카드를 빼면 종료(stop true), 큐 멈춤', async () => {
    Q.items = [{ id: 1, kind: 'daily', status: 'wait', label: '일일 숙제', chars: [1] },
               { id: 2, kind: 'action', status: 'wait', label: '채집' }];
    Q.qTick();
    await sleep(20);
    Q.qRemove(1);
    await sleep(30);
    assert(calls.some((c) => c[0] === 'daily.stop' && c[1] === true), 'daily ended');
    assert(actionRuns === 0, 'queue stops after removing running card');
    assert(calls.some((c) => c[0] === 'record' && c[2] === 'removed'), 'recorded removed');
  });

  await scenario('⏸ 큐 일시정지: 숙제 일시정지 (밀림 아님)', async () => {
    Q.items = [{ id: 1, kind: 'daily', status: 'wait', label: '일일 숙제', chars: [1] }];
    Q.qTick();
    await sleep(20);
    Q.qPause();
    await sleep(30);
    assert(Q.items[0].status === 'pause', 'pause, got ' + Q.items[0].status);
    assert(!Q.running, 'stopped');
  });
  process.exit(failed ? 1 : 0);
})();
