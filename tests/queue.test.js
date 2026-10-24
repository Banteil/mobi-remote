// 작업 큐 화면 쪽 시험 (node tests/queue.test.js). 큐의 주인은 파이썬(tests/test_workqueue.py 가 시험)이고,
// 화면은 'mm:queue-run' 으로 받은 카드(목표·행동)를 돌려 queue.uiDone 으로 답한다. 그 손주고받기를 본다.
const fs = require('fs');
const vm = require('vm');
process.on('unhandledRejection', () => {});
process.on('uncaughtException', () => {});
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
const handlers = {};
const mmReal = {
  labels: { queue_state: {} },
  queue: new Proxy({
    state: async () => ({ items: [], running: false }),
    uiDone: async (id, r) => { calls.push(['uiDone', id, r]); return { ok: true }; },
    patch: async (id, f) => { calls.push(['patch', id, f]); return { ok: true }; },
    add: async (spec, where, rp) => { calls.push(['add', spec.kind, where, !!rp]); return Object.assign({ id: 9 }, spec); },
    onRun: (cb) => { handlers.run = cb; }, onStop: (cb) => { handlers.stop = cb; },
    onChange: (cb) => { handlers.change = cb; }, onDone: (cb) => { handlers.done = cb; }, onToast: () => {},
  }, { get: (t, m) => (m in t ? t[m] : any()) }),
};
const ctx = {
  console, setTimeout, clearTimeout, setInterval, clearInterval, Promise, Date, Math, JSON, Object, Array, String, Number,
  document: any(), navigator: any(), localStorage: any(), location: any(), requestAnimationFrame: any(),
  getComputedStyle: any(), ResizeObserver: function () { return any(); }, MutationObserver: function () { return any(); },
  Image: function () { return any(); }, fetch: any(), alert: any(), performance: { now: () => Date.now() },
  mm: new Proxy(mmReal, { get: (t, k) => (k in t ? t[k] : any()) }),
};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
// index.html 의 script 순서대로 이어 붙여 읽는다 (같은 전역을 쓰는 여러 파일)
const order = [...fs.readFileSync(ROOT + 'index.html', 'utf8').matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]);
let src = "'use strict';\n" + order.map((f) => fs.readFileSync(ROOT + f, 'utf8').replace(/^'use strict';/, '')).join('\n;\n');
src += `
;globalThis.__q = { Q_KINDS, get stop() { return qStop; }, get items() { return qItems; }, qStartNow, qSetStop };`;
try { vm.runInContext(src, ctx, { filename: 'web/*.js' }); } catch (e) { console.error('load error', e); process.exit(1); }
const Q = ctx.__q;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let failed = 0;
async function scenario(name, fn) {
  calls.length = 0;
  try { await fn(); console.log('PASS', name); } catch (e) { failed++; console.log('FAIL', name, '-', e.message); console.log(JSON.stringify(calls)); }
}
function assert(c, m) { if (!c) throw new Error(m); }

(async () => {
  await sleep(100);  // 시작 코드가 끝나길

  await scenario('목표 카드: 돌리고 진행 값과 함께 답한다', async () => {
    Q.Q_KINDS.goal.run = async (it) => { it.made = 4; it.spent = 100; return true; };
    handlers.run({ id: 3, item: { id: 3, label: '못', target: 10 } });
    await sleep(20);
    const d = calls.find((c) => c[0] === 'uiDone');
    assert(d && d[1] === 3 && d[2].ok === true, 'uiDone ok');
    assert(d[2].patch.made === 4 && d[2].patch.spent === 100, 'patch carries progress');
    assert(d[2].stop === null, 'no stop');
  });

  await scenario('멈춤 신호: 돌고 있는 목표 루프가 qStop 을 본다', async () => {
    let sawStop = null;
    Q.Q_KINDS.goal.run = async () => { await sleep(30); sawStop = Q.stop && Q.stop.reason; return false; };
    handlers.run({ id: 4, item: { id: 4, label: '못', target: 10 } });
    await sleep(5);
    handlers.stop({ reason: 'preempt' });
    await sleep(50);
    assert(sawStop === 'preempt', 'loop saw preempt, got ' + sawStop);
    const d = calls.find((c) => c[0] === 'uiDone');
    assert(d && d[2].ok === false && d[2].stop === null, 'preempt is decided by python, not sent back');
  });

  await scenario('생활 스킬 부족은 화면이 정해 올린다', async () => {
    Q.Q_KINDS.goal.run = async () => { Q.qSetStop('skill', { what: '은 광석', level: 5 }); return false; };
    handlers.run({ id: 5, item: { id: 5, label: '은괴', target: 3 } });
    await sleep(20);
    const d = calls.find((c) => c[0] === 'uiDone');
    assert(d && d[2].stop && d[2].stop.reason === 'skill' && d[2].stop.what === '은 광석', 'skill stop sent');
  });

  await scenario('지금 바로 = queue.add(now), 숙제 시작은 일시정지 카드를 바꿈', async () => {
    Q.qStartNow({ kind: 'daily', label: '일일 숙제' }, true);
    await sleep(5);
    assert(calls.some((c) => c[0] === 'add' && c[1] === 'daily' && c[2] === 'now' && c[3] === true), 'add now replace');
  });

  await scenario('mm:queue 상태를 그대로 받는다', async () => {
    handlers.change({ items: [{ id: 1, kind: 'daily', status: 'pause', label: '일일 숙제', chars: [1] }], running: false });
    assert(Q.items.length === 1 && Q.items[0].status === 'pause', 'items applied');
  });
  process.exit(failed ? 1 : 0);
})();
