// 작업 큐 화면 쪽 시험 (node tests/queue.test.js). 큐의 주인은 파이썬(tests/test_workqueue.py 등이 시험)이고,
// 화면은 상태를 그리고 버튼을 보내며, 돌던 카드의 질문('mm:queue-ask')에 queue.answer 로 답한다. 그 주고받기를 본다.
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
    answer: async (id, yes) => { calls.push(['answer', id, yes]); return { ok: true }; },
    patch: async (id, f) => { calls.push(['patch', id, f]); return { ok: true }; },
    add: async (spec, where, rp) => { calls.push(['add', spec.kind, where, !!rp]); return Object.assign({ id: 9 }, spec); },
    onAsk: (cb) => { handlers.ask = cb; },
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
;globalThis.__q = { Q_KINDS, get items() { return qItems; }, qStartNow, setBlocked: (f) => { goalBlockedModal = f; } };`;
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

  await scenario('질문: 목표 카드의 막힘 창을 띄우고 답한다', async () => {
    let shown = null;
    Q.setBlocked(async (st, label) => { shown = [st.name, label]; return true; });
    handlers.ask({ id: 3, kind: 'goal_blocked', step: { name: '마법의 호박' }, label: '간식' });
    await sleep(20);
    assert(shown && shown[0] === '마법의 호박' && shown[1] === '간식', 'modal shown');
    assert(calls.some((c) => c[0] === 'answer' && c[1] === 3 && c[2] === true), 'answered yes');
  });

  await scenario('질문: 아니오도 그대로 답한다', async () => {
    Q.setBlocked(async () => false);
    handlers.ask({ id: 4, kind: 'goal_blocked', step: {}, label: 'x' });
    await sleep(20);
    assert(calls.some((c) => c[0] === 'answer' && c[1] === 4 && c[2] === false), 'answered no');
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
