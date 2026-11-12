// web/*.js 를 index.html 순서대로 '따로따로' 한 컨텍스트에 읽어 본다 (브라우저의 <script> 여러 개와 같은 방식).
// 1) 맨 위 선언 이름이 두 파일에 겹치나  2) 읽는 동안 오류(앞 파일이 뒤 파일 것을 바로 씀)  3) 시작(main.js → wire …) 중 ReferenceError
// 사용: node tests/web_load.test.js [web 폴더] [이름 목록 저장 파일] — 기존 queue.test.js 는 파일을 이어 붙여 읽어 순서 문제를 못 잡는다
const fs = require('fs'), vm = require('vm'), path = require('path');
const ROOT = process.argv[2] || path.join(__dirname, '..', 'web'), OUT = process.argv[3];
const errors = [];
process.on('unhandledRejection', (e) => errors.push('비동기: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e)));
process.on('uncaughtException', (e) => errors.push('예외: ' + (e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e)));
function any() {
  const f = function () { return any(); };
  return new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => '';
      if (k === 'then') return undefined;
      if (k === 'length') return 0;
      if (k === Symbol.iterator) return function* () {};
      return any();
    },
    set() { return true; }, apply() { return any(); }, construct() { return any(); },
  });
}
function mmAny() {  // mm.* 호출은 늘 Promise (파이썬 다리와 같게)
  const f = function () {};
  return new Proxy(f, {
    get(t, k) { if (k === 'then') return undefined; if (k === Symbol.toPrimitive) return () => ''; return k === 'limits' ? any() : mmAny(); },
    apply() { return Promise.resolve(any()); },
  });
}
// 화면 코드의 타이머는 따로 — 가짜 값(Proxy)을 clearTimeout 에 넘겨도 검사기 타이머가 망가지지 않게, 오래 기다리는 것은 돌리지 않는다
const pageTimers = new Set();
const pSet = (fn, ms) => { if ((ms || 0) > 1000) return 0; const t = setTimeout(() => { pageTimers.delete(t); fn(); }, ms); t.unref(); pageTimers.add(t); return t; };
const pClear = (t) => { if (pageTimers.has(t)) { clearTimeout(t); pageTimers.delete(t); } };
const ctx = {
  console, setTimeout: pSet, clearTimeout: pClear, setInterval: () => 0, clearInterval: () => {}, Promise, Date, Math, JSON, Object, Array, String, Number,
  Set, Map, RegExp, Error, Symbol, Boolean, parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, Blob: function () {},
  document: any(), navigator: any(), location: any(), requestAnimationFrame: (cb) => pSet(cb, 0),
  getComputedStyle: any(), ResizeObserver: function () { return any(); }, MutationObserver: function () { return any(); },
  HTMLElement: function () {}, ClipboardItem: function () {}, AudioContext: function () { return any(); },
  Image: function () { return any(); }, fetch: any(), alert: any(), performance: { now: () => Date.now() }, mm: mmAny(),
};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
const order = [...fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8').matchAll(/<script src="([^"]+)"/g)].map((m) => m[1]);
const decl = /^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)|^(?:const|let|var|class)\s+([A-Za-z_$][\w$]*)/;
const owner = {}, dups = [], names = {};
for (const f of order) {
  const src = fs.readFileSync(path.join(ROOT, f), 'utf8');
  src.split('\n').forEach((line) => {
    if (/^(?:const|let|var)\s+[[{]/.test(line)) errors.push(f + ': 구조 분해 선언 (검사 못 함): ' + line);
    const m = decl.exec(line);
    if (!m) return;
    const n = m[1] || m[2];
    if (owner[n]) dups.push(n + ' : ' + owner[n] + ' · ' + f);
    else owner[n] = f;
    names[n] = f;
  });
  try { new vm.Script(src, { filename: f }).runInContext(ctx); }
  catch (e) { errors.push('읽기 ' + f + ': ' + e.message); }
}
setTimeout(() => {
  // 선언한 이름이 실제로 전역에 보이나
  // 초기화 전(TDZ)이거나 없으면 읽을 때 던진다
  const undef = Object.keys(names).filter((n) => {
    try { return vm.runInContext('typeof ' + n, ctx) === 'undefined'; } catch (e) { return true; }
  });
  console.log('파일', order.length, '· 맨 위 이름', Object.keys(names).length);
  console.log('겹친 이름', dups.length ? dups : '없음');
  console.log('못 찾은 이름', undef.length ? undef : '없음');
  console.log('오류', errors.length ? errors : '없음');
  if (OUT) fs.writeFileSync(OUT, JSON.stringify(Object.keys(names).sort(), null, 1));
  process.exit(dups.length || undef.length || errors.length ? 1 : 0);
}, 1500);
