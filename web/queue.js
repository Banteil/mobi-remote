'use strict';
/* 작업 큐 화면 — 카드 그리기 · 버튼 · 한 번 하는 행동 담기 · 막힘 질문 창 · 작업 기록. 큐 자체는 파이썬(mabi/workqueue.py).
 * 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 작업 큐 ────────────────────────────────────── */

/**
 * 카드를 줄 세워 두고 위에서부터 하나씩 민다. 캐릭터는 하나고 게임 조작도 한 번에 하나라 동시에 돌릴 수 없어서 큐다.
 *
 * 큐의 주인은 파이썬이다 (mabi/workqueue.py · gui_app/queue_api.py). 순서·상태·실행·멈춤(F12 포함)·저장·기록을
 * 거기서 하고, 화면은 'mm:queue' 로 받은 상태를 그리고 버튼을 보내기만 한다. 그래서 화면을 다시 띄워도 큐는 끊기지 않는다.
 * 돌던 카드가 사람에게 물어야 하면(재료를 직접 구해 와야 함) 'mm:queue-ask' 로 묻고, 여기서 창을 띄워 queue.answer 로 답한다.
 *
 * 진행 상황은 상태바가 아니라 **그 항목의 카드**에 적는다. 여러 개가 줄 서 있으면
 * "제작 중"이라는 한 줄만으로는 어느 것 이야기인지 알 수 없다.
 */
let qItems = [];      // 파이썬이 준 카드 목록 (보기용 — 고치려면 mm.queue.* 로)
let qRunning = false;

/**
 * 카드 종류의 화면 쪽 표시 (daily·abyss 는 daily.js 가 더한다). 실행은 모두 파이썬.
 *   amount(x)    → 수량·내용 한 줄 (카드)
 *   card(x)      → 카드의 수량 칸 HTML (없으면 amount 한 줄)
 *   editable     → ✎ (목표 수량 바꾸기)
 *   doneToast(x) → 끝났을 때 토스트 [제목, 내용] (없으면 안 띄움)
 */
const Q_KINDS = {
  goal: {
    editable: true,
    amount: (x) => '목표 ' + num(x.target) + '개' + (x.made ? ' · 만든 ' + num(x.made) : '') +
      (x.spent ? ' · 날개 ' + num(x.spent) : '') + (x.via ? ' · ' + x.via : ''),
    card: (x) => {
      const nowHave = x.have !== undefined ? x.have : x.startHave;
      // 수량은 이름 옆이 아니라 아래 줄에 둔다. "새로 100개"만으로는 지금 몇 개를 들고
      // 있는지 알 수 없어, 목표를 얼마로 잡을지 판단할 근거가 되지 못한다.
      return '<div class="q-amt">목표 <b>' + num(x.target) + '</b>개' +
        (nowHave !== undefined ? ' · 현재 <b>' + num(nowHave) + '</b>개' : '') +
        (x.made ? ' <span class="muted">(만든 ' + num(x.made) + ')</span>' : '') +
        '</div>' +
        '<div class="q-sub">' + esc(x.via || '') +
        (x.recipe ? ' · ' + esc(x.recipe) : '') +
        (x.spent ? ' · 날개 ' + num(x.spent) : '') +
        (!x.spent && x.wings ? ' · 예상 ' + num(x.wings) + (x.partial ? '+' : '') : '') +
        '</div>';
    },
    doneToast: (x) => ['목표 달성', x.label + ' 새로 ' + num(x.target) + '개' + (x.spent ? ' · 날개 ' + num(x.spent) : '')],
  },
  action: {
    amount: (x) => x.detail || '',  // 실행은 파이썬 (queue_api.ActionKind) — 결과는 mm:exec-done 으로 알린다
  },
};

function qKind(x) { return Q_KINDS[x.kind || 'goal'] || Q_KINDS.goal; }

const Q_TIP = {
  wait: '대기 — 큐가 돌면 위에서부터 차례로 진행합니다',
  pause: '일시정지 — 멈춘 자리에서 기다립니다. 카드의 ▶ 나 아래 ▶(전체 시작)로 이어 합니다',
  done: '완료', fail: '실패 — 이유를 읽고 ▶ 로 다시 걸거나 정리로 치웁니다', run: '진행 중',
};
const Q_STATE = Object.fromEntries(['wait', 'run', 'pause', 'done', 'fail'].map((k) =>
  [k, { label: (mm.labels.queue_state || {})[k] || k, cls: 'q-' + k, tip: Q_TIP[k] }]));

function applyQueue(s) {
  if (!s) return;
  const wasRunning = qRunning;
  qItems = Array.isArray(s.items) ? s.items : [];
  qRunning = !!s.running;
  paintQueue();
  // 큐가 서면 화면을 한 번 새로 고친다. 수량이 많이 바뀌어 있다.
  if (wasRunning && !qRunning) refreshActive().catch(() => {});
}

async function loadQueue() {
  try {
    const s = await mm.queue.state();
    applyQueue(s);
    if (s && s.ask) qShowAsk(s.ask);  // 화면을 다시 띄웠는데 기다리는 질문이 있다
  } catch (_) { /* 큐를 못 읽어도 화면은 뜬다 */ }
}

mm.queue.onChange(applyQueue);
mm.queue.onToast((m) => { if (m) toast(m.title, m.text || '', m.kind || 'ok'); });
mm.queue.onDone((m) => {
  const it = m && m.item;
  if (!it) return;
  const t = qKind(it).doneToast && qKind(it).doneToast(it);  // 일일 숙제는 결과 보고서 창이 따로 뜬다
  if (t) toast(t[0], t[1], 'ok');
});

/* 돌던 카드의 질문 (지금은 목표 카드의 '재료를 직접 구해 와야 함'). 큐가 서면 파이썬이 null 을 보내 창을 닫는다 */
let qAskOpen = null;
mm.queue.onAsk((ask) => {
  if (ask) qShowAsk(ask);
  else if (qAskOpen !== null && !$('#modal').classList.contains('hidden')) $('#modal-cancel').click();
});

async function qShowAsk(ask) {
  if (qAskOpen !== null) return;
  qAskOpen = ask.id;
  let yes = false;
  try {
    if (ask.kind === 'goal_blocked') yes = await goalBlockedModal(ask.step || {}, ask.label || '');
  } finally {
    qAskOpen = null;
  }
  mm.queue.answer(ask.id, !!yes).catch(() => {});
}

/** 목표 카드를 맨 아래에 담는다 (돌리지는 않는다 — 날개가 나가는 일은 사람이 재생을 누른 뒤에). */
async function qAdd(spec) {
  const it = await mm.queue.add(Object.assign({ spent: 0, steps: 0 }, spec), 'end');
  toast('큐에 담았습니다', it.label + ' 새로 ' + num(it.target) + '개 — 재생을 누르면 진행합니다.', 'ok');
  return it;
}

function qFind(id) { return qItems.find((x) => String(x.id) === String(id)); }

function qNote(it, text) {
  it.note = text;
  if (it.id !== undefined) mm.queue.patch(it.id, { note: text }).catch(() => {});
}

function qRemove(id) { mm.queue.remove(id); }

/**
 * 지금 바로 시작 (숙제 시작 · 반복 시작 · 파란 버튼). 맨 위에 넣고 바로 돌린다.
 * 돌고 있는 작업이 있으면 세워서 대기로 돌리고(뒤로 밀림), 이 작업이 끝나면 이어서 한다.
 * replacePaused: 같은 종류의 일시정지 카드를 이걸로 바꾼다 (숙제 시작 = 새 숙제).
 */
function qStartNow(spec, replacePaused) {
  return mm.queue.add(spec, 'now', !!replacePaused);
}

/* ── 한 번 하는 행동 (제작·채집·가공·수령·연주) ──
 * 파란 버튼 = 지금 바로 (qStartNow — 돌던 작업은 뒤로 밀렸다가 이어서), '목표' 버튼 = 큐 맨 아래에 담기.
 * 숙제·어비스가 도는 중에 버튼을 눌러도 게임 조작이 겹치지 않게 모두 큐를 거친다. 날개가 드는 것은 넣기 전에 묻는다. */
async function actSpec(spec) {
  if (spec.command && !(await confirmCost(spec.command, { label: spec.label, note: spec.note, skipConfirm: spec.skipConfirm }))) return null;
  return Object.assign({ kind: 'action', note: '' }, spec);
}

async function actNow(spec) {
  const it = await actSpec(spec);
  if (!it) return;
  const cur = qItems.find((x) => x.status === 'run');
  if (cur) toast('먼저 합니다', it.label + ' — 진행 중이던 "' + cur.label + '" 은 끝나면 이어서', 'ok');
  qStartNow(it);
}

async function actGoal(spec) {
  const it = await actSpec(spec);
  if (!it) return;
  await mm.queue.add(it, 'end');
  toast('큐에 담았습니다', it.label + ' — 재생을 누르면 진행합니다.', 'ok');
}

/** 큐가 행동을 마친 뒤 다시 읽을 탭 (app.js 의 mm.onExecDone 이 부른다) */
const ACT_REFRESH = {
  craft: () => loadCraft(true), alter: () => loadAlter(true), collect: () => loadAlter(true), collectAll: () => loadAlter(true),
};

/** 이 항목부터 돌린다 (끝난 것이면 다시 걸기). */
function qPlayOne(id) { mm.queue.playOne(id); }

/** 진행 중인 이 항목에서 큐를 일시정지한다 (카드의 ⏸ — 이번 걸음을 마치고). ▶ 로 하던 자리에서 이어 간다. */
function qPauseOne(id) { mm.queue.pauseOne(id); }

function qMove(id, delta) { mm.queue.move(id, delta); }

async function qEdit(id) {
  const it = qFind(id);
  if (!it || !qKind(it).editable) return;
  const n = await promptNumber('목표 수량 바꾸기', '"' + it.label + '" 를 새로 몇 개?', it.target,
    '진행 중인 항목도 바꿀 수 있습니다. 다음 걸음부터 새 수량으로 판단하며, ' +
    '이미 만든 만큼은 그대로 인정합니다.');
  if (!n) return;
  mm.queue.edit(id, n);  // 돌고 있는 목표는 다음 걸음부터 새 수량으로
}

/** 실패한 항목을 치운다. 완료는 끝나는 즉시 스스로 빠지므로, 남는 것은 막혔거나 실패한 것들이다. */
function qTidy() { mm.queue.tidy(); }

/** 전부 지운다. 되돌릴 수 없으니 한 번 물어본다. */
async function qClear() {
  if (!qItems.length) return;
  const ok = await confirmModal('작업 큐 비우기',
    '<p>담아 둔 <b>' + qItems.length + '건</b>을 전부 지웁니다.</p>' +
    '<p class="hint">진행 중인 것이 있으면 이번 걸음을 마치고 멈춥니다. 이미 쓴 정령의 날개는 돌아오지 않습니다.</p>',
    '전부 지우기');
  if (ok) mm.queue.clear();
}

/** 재생 ▶ (전체 시작). 일시정지한 카드도 대기로 되돌려 위에서부터 차례로 한다. */
function qPlayAll() { mm.queue.playAll(); }

/** 부드럽게 멈춘다 (이번 걸음을 마치고). 카드는 일시정지 — 재생을 누르면 이어진다. */
function qPause() {
  if (!qRunning) return;
  mm.queue.pause();
  say('이번 걸음을 마치고 멈춥니다.');
}

/** 지금 명령까지 끊고 멈춘다 (돌고 있는 CLI 호출에 취소를 보낸다). 카드는 똑같이 일시정지. */
function qHalt() {
  mm.queue.halt();
  say('멈추는 중입니다.');
}

/* ── 큐 결과 창 ──
 * 큐를 시작한 뒤 남은 카드가 없어지면(다 끝남 · 전체 중단 Ctrl+F12 · 마지막 카드 뺌) 파이썬이 보고서를 보낸다
 * (mabi/queue_report.py). 요약 탭 = 카드별 결과 + 모두 합친 얻은 것·쓴 것·재화, 카드 탭 = 그 카드의 세부 (숙제는 캐릭터별). */
const QR_RESULT = {
  done: ['완료', 'pill-ok'], fail: ['실패', 'pill-bad'], pause: ['일시정지', 'pill-warn'],
  stop: ['중단', 'pill-muted'], preempt: ['밀림', 'pill-muted'], run: ['진행 중', 'pill-muted'],
};
let qrData = null;
let qrTab = 'sum';

function qrPill(r) {
  const [t, k] = QR_RESULT[r] || [r, 'pill-muted'];
  return '<span class="pill ' + k + '">' + t + '</span>';
}

function qrTook(secs) {
  const m = Math.round((secs || 0) / 60);
  return m >= 60 ? Math.floor(m / 60) + '시간 ' + (m % 60) + '분' : m ? m + '분' : (secs || 0) + '초';
}

/** 얻은 것 · 쓴 것 · 재화 (x: {gained, used, cur}). compact: 캐릭터 칸 안에 작게 */
function lootHtml(x, compact) {
  const list = (m, sign) => Object.entries(m || {}).sort((a, b) => b[1] - a[1])
    .map(([k, n]) => '<span class="qr-item">' + esc(k) + ' <b>' + sign + num(n) + '</b></span>').join('');
  const cur = Object.entries(x.cur || {}).sort((a, b) => b[1] - a[1])
    .map(([k, n]) => '<span class="qr-item ' + (n > 0 ? 'qr-up' : 'qr-down') + '">' + esc(k) + ' <b>' + (n > 0 ? '+' : '−') + num(Math.abs(n)) + '</b></span>').join('');
  const rows = [['얻은 것', list(x.gained, '+')], ['재화', cur], ['쓴 것', list(x.used, '−')]].filter((r) => r[1]);
  if (!rows.length) return compact ? '' : '<p class="muted">가방·재화 변화가 없습니다.</p>';
  return '<div class="qr-loot' + (compact ? ' compact' : '') + '">' +
    rows.map(([t, h]) => '<div class="qr-lrow"><span class="qr-lt">' + t + '</span><div class="qr-items">' + h + '</div></div>').join('') + '</div>';
}

function showQueueReport(rep) {
  if (!rep || !(rep.cards || []).length) return;
  qrData = rep;
  qrTab = 'sum';
  const hm = (t) => { const d = new Date(t); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
  $('#qr-title').textContent = rep.why === 'done' ? '작업 큐 결과 — 모두 완료' : '작업 큐 결과 — 중단됨';
  $('#qr-time').textContent = rep.start && rep.end ? hm(rep.start) + ' ~ ' + hm(rep.end) + ' (' + qrTook((rep.end - rep.start) / 1000) + ')' : '';
  paintQueueReport();
  $('#q-report').classList.remove('hidden');
}

function paintQueueReport() {
  const rep = qrData;
  if (!rep) return;
  $('#qr-tabs').innerHTML = [['sum', '요약', '']].concat(rep.cards.map((c) => [String(c.id), c.label, c.result]))
    .map(([k, t, r]) => '<button class="qr-tab' + (k === qrTab ? ' on' : '') + '" data-qr-tab="' + esc(k) + '">' +
      esc(t) + (r ? ' <i class="qr-dot qr-' + esc(r) + '"></i>' : '') + '</button>').join('');
  $('#qr-shot').classList.add('hidden');
  $('#qr-scroll').scrollTop = 0;
  if (qrTab === 'sum') {
    const n = {};
    rep.cards.forEach((c) => { n[c.result] = (n[c.result] || 0) + 1; });
    $('#qr-sum').innerHTML = Object.entries(n).map(([r, c]) => {
      const [t, k] = QR_RESULT[r] || [r, 'pill-muted'];
      return '<span class="pill ' + k + '">' + t + ' ' + c + '</span>';
    }).join('');
    $('#qr-body').innerHTML =
      '<div class="dl-rp-char"><h4>한 일</h4>' + rep.cards.map((c) =>
        '<div class="qr-card" data-qr-tab="' + c.id + '">' + qrPill(c.result) + '<b>' + esc(c.label) + '</b>' +
        '<span class="qr-goal">' + esc((c.view && c.view.goal) || c.detail || '') + '</span>' +
        '<span class="muted">' + qrTook(c.secs) + '</span></div>').join('') + '</div>' +
      '<div class="dl-rp-char"><h4>모두 합친 결과</h4>' + lootHtml(rep.total || {}) + '</div>';
    return;
  }
  const c = rep.cards.find((x) => String(x.id) === qrTab);
  if (!c) return;
  const v = c.view || {};
  const bar = Array.isArray(v.bar) && v.bar[1] ? Math.round(v.bar[0] / v.bar[1] * 100) + '%' : '';
  const head = '<div class="dl-rp-char"><h4>' + esc(c.label) + ' ' + qrPill(c.result) + '</h4>' +
    '<div class="qr-kv">' +
    [['내용', (v.goal || c.detail || '')], ['진행', [v.now, bar, v.stat].filter(Boolean).join(' · ')],
      ['걸린 시간', qrTook(c.secs) + (c.runs > 1 ? ' · ' + c.runs + '번에 나눠 함' : '')], ['메모', c.note]]
      .filter((r) => r[1]).map(([k, t]) => '<span>' + k + '</span><span>' + esc(t) + '</span>').join('') + '</div></div>';
  if (c.kind === 'daily') {
    const d = dailyReportHtml(c.tasks, c.loot);
    $('#qr-sum').innerHTML = d.pills;
    $('#qr-body').innerHTML = head + d.body;
  } else {
    $('#qr-sum').innerHTML = '';
    const lt = (c.loot || []).length ? lootHtml(c.loot.reduce((a, x) => {
      ['gained', 'used', 'cur'].forEach((k) => Object.entries(x[k] || {}).forEach(([n, q]) => { a[k][n] = (a[k][n] || 0) + q; }));
      return a;
    }, { gained: {}, used: {}, cur: {} })) : '<p class="muted">가방·재화 변화가 없습니다.</p>';
    $('#qr-body').innerHTML = head + '<div class="dl-rp-char"><h4>얻은 것</h4>' + lt + '</div>';
  }
}

mm.queue.onReport(showQueueReport);
document.addEventListener('click', (e) => {
  const t = e.target.closest('#q-report [data-qr-tab]');
  if (!t) return;
  qrTab = t.dataset.qrTab;
  paintQueueReport();
});

async function showLastQueueReport() {
  const rep = await mm.queue.lastReport().catch(() => null);
  if (rep) showQueueReport(rep);
  else toast('아직 결과가 없습니다', '작업 큐를 한 번 다 돌리면(또는 전체 중단하면) 여기서 다시 볼 수 있습니다.', 'ok');
}

/* ── 작업 기록 ── 끝난 항목(완료·실패·일시정지·뺌)을 파이썬이 한 줄씩 파일에 남기고, '기록' 창에서 본다 */
const QH_RESULT = {
  done: ['완료', 'pill-ok'], fail: ['실패', 'pill-bad'], pause: ['일시정지', 'pill-warn'],
  stop: ['멈춤', 'pill-muted'], removed: ['뺌', 'pill-muted'],
};

async function showQueueHistory() {
  const rows = await mm.queue.history(300).catch(() => []);
  const pad = (n) => String(n).padStart(2, '0');
  const hm = (t) => { const d = new Date(t); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
  const day = (t) => { const d = new Date(t); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };
  const took = (r) => {
    const m = Math.round((r.end - r.start) / 60000);
    return m >= 60 ? Math.floor(m / 60) + '시간 ' + (m % 60) + '분' : m + '분';
  };
  let last = '';
  const html = (rows || []).map((r) => {
    const [txt, cls] = QH_RESULT[r.result] || [r.result, 'pill-muted'];
    const d = day(r.end);
    const head = d !== last ? '<div class="qh-day">' + d + '</div>' : '';
    last = d;
    return head + '<div class="qh-row">' +
      '<span class="qh-time" title="걸린 시간 ' + took(r) + '">' + hm(r.start) + ' ~ ' + hm(r.end) + '</span>' +
      '<span class="pill ' + cls + '">' + txt + '</span>' +
      '<span class="qh-label">' + esc(r.label || '') + '</span>' +
      '<span class="qh-detail">' + esc(r.detail || '') + (r.note ? '<span class="qh-note">' + esc(r.note) + '</span>' : '') + '</span>' +
      '</div>';
  }).join('');
  $('#q-hist-body').innerHTML = html || '<p class="muted">아직 기록이 없습니다. 작업 큐에서 끝난 작업이 여기에 남습니다.</p>';
  $('#q-hist-n').textContent = rows && rows.length ? '최근 ' + rows.length + '건' : '';
  $('#q-hist').classList.remove('hidden');
}

/**
 * 카드의 진행 줄 — 지금 하는 일 · 단계 · 막대. 글은 파이썬이 만든다 (x.view, gui_app/queue_api.py 의 Kind.view).
 * 화면 위 오버레이(gui_app/overlay.py)도 같은 view 를 그려 둘이 같은 말을 한다.
 */
function qProgress(x) {
  const v = x.view || {};
  const bar = Array.isArray(v.bar) && v.bar[1] > 0 ? v.bar : null;
  const run = x.status === 'run';
  if (!v.now && !v.step && !bar && !run) return '';
  const pct = bar ? Math.min(100, Math.round(bar[0] / bar[1] * 100)) : 0;
  const nums = bar && x.kind !== 'abyss' ? num(bar[0]) + '/' + num(bar[1]) : '';
  return '<div class="q-prog">' +
    (v.now || run
      ? '<div class="q-now"><span>' + esc(v.now || '') + '</span>' +
        (run && x.startedAt ? '<span class="q-el" data-since="' + x.startedAt + '">' + qElapsed(x.startedAt) + '</span>' : '') + '</div>'
      : '') +
    (v.step ? '<div class="q-step" title="' + esc(v.step) + '">' + esc(v.step) + '</div>' : '') +
    // 너비는 그린 뒤 paintQueue 가 넣는다 — 인라인 style 은 CSP(style-src 'self')에 막힌다
    (bar ? '<div class="q-barrow"><div class="q-bar"><i data-pct="' + pct + '"></i></div>' +
      '<span>' + [nums, pct + '%', v.stat].filter(Boolean).map(esc).join(' · ') + '</span></div>'
      : (v.stat ? '<div class="q-step">' + esc(v.stat) + '</div>' : '')) +
    '</div>';
}

function qElapsed(since) {
  const s = Math.max(0, Math.floor((Date.now() - since) / 1000));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, ss = s % 60;
  const p = (n) => String(n).padStart(2, '0');
  return (h ? h + ':' + p(m) : m) + ':' + p(ss);
}

// 진행 중 카드의 걸린 시간 (카드를 다시 그리지 않고 글자만)
setInterval(() => {
  document.querySelectorAll('#q-list .q-el').forEach((el) => { el.textContent = qElapsed(Number(el.dataset.since)); });
}, 1000);

function paintQueue() {
  const list = $('#q-list');
  if (!list) return;

  const waiting = qItems.filter((x) => x.status === 'wait').length;
  const running = qItems.find((x) => x.status === 'run');

  $('#q-count').textContent = qItems.length ? qItems.length + '건' : '';
  // 접었을 때는 세로 라벨이 개수를 대신 알려 준다
  $('#q-tag-n').textContent = qItems.length ? '  ' + qItems.length + '건' : '';
  $('#q-state').textContent = running ? '진행 중' : (waiting ? '대기 ' + waiting : '');
  $('#q-state').className = 'q-state' + (running ? ' on' : '');

  $('#q-play').disabled = qRunning || !(waiting || qItems.some((x) => x.status === 'pause'));  // 일시정지만 있어도 ▶ = 이어 하기
  $('#q-pause').disabled = !qRunning;
  $('#q-halt').disabled = !qRunning;
  $('#q-tidy').disabled = !qItems.some((x) => x.status === 'done' || x.status === 'fail');
  $('#q-clear').disabled = !qItems.length;
  if (typeof dlRefresh === 'function') dlRefresh();  // 일일 숙제 탭 버튼 (일시정지 카드)

  if (!qItems.length) {
    list.innerHTML = '<p class="q-empty">비어 있음</p>';
    return;
  }

  list.innerHTML = qItems.map((x, i) => {
    const st = Q_STATE[x.status] || Q_STATE.wait;
    const run = x.status === 'run';
    const ended = x.status === 'done' || x.status === 'fail';

    // 진행 중에는 ⏸ 만, 끝난 것에는 ▶(다시 걸기)만 낸다. 지금 누를 수 없는 버튼을
    // 흐리게 늘어놓는 것보다 아예 없는 편이 무엇을 할 수 있는지 분명하다.
    const btns =
      (run ? '<button class="q-btn" data-q-pause="' + x.id + '" title="이번 걸음을 마치고 일시정지">⏸</button>' : '') +
      (!run ? '<button class="q-btn" data-q-play="' + x.id + '" title="' + (ended ? '다시 걸기' : '이것부터 진행') + '">▶</button>' : '') +
      (qKind(x).editable ? '<button class="q-btn" data-q-edit="' + x.id + '" title="수량 바꾸기">✎</button>' : '') +
      '<button class="q-btn" data-q-del="' + x.id + '" title="큐에서 빼기">✕</button>';

    const k = qKind(x);
    // 이름은 길면 잘린다. 잘린 것을 확인할 길이 title 말고 없다.
    return '<div class="q-item ' + st.cls + '">' +
      '<div class="q-top"><span class="q-badge" title="' + esc(st.tip || '') + '">' + st.label + '</span>' +
      '<b title="' + esc(x.label) + '">' + esc(x.label) + '</b>' +
      '<span class="spacer"></span>' + btns +
      '</div>' +
      (k.card ? k.card(x) : '<div class="q-amt">' + esc(k.amount(x)) + '</div>') +
      qProgress(x) +
      (x.note ? '<div class="q-note">' + esc(x.note) + '</div>' : '') +
      (run
        ? ''
        : '<div class="q-move">' +
          '<button class="q-btn" data-q-up="' + x.id + '"' + (i === 0 ? ' disabled' : '') + ' title="위로">▲</button>' +
          '<button class="q-btn" data-q-dn="' + x.id + '"' + (i === qItems.length - 1 ? ' disabled' : '') + ' title="아래로">▼</button>' +
          '</div>') +
      '</div>';
  }).join('');
  list.querySelectorAll('.q-bar i[data-pct]').forEach((el) => { el.style.width = el.dataset.pct + '%'; });
}
/**
 * 자동으로 구할 수 없는 재료를 만났을 때.
 *
 * 커넥터에는 상점·거래 명령이 없어 앱이 대신 구해 올 방법이 아예 없다.
 * 그래서 무엇이 왜 막혔는지 정확히 알려주고 사람에게 넘긴다.
 */
async function goalBlockedModal(st, label) {
  const others = (st.otherShort || []).map((x) => esc(x.name) + ' ' + x.lack + '개').join(', ');
  return await confirmModal('진행할 수 없습니다',
    '<p><b>' + esc(label) + '</b> 를 만들려면 <b>' + esc(st.name || '?') + '</b> 이(가) 필요합니다.</p>' +
    '<p class="mark-bad">' + esc(st.message || '') + '</p>' +
    (st.forRecipe ? '<p class="hint">' + esc(st.forRecipe) + ' 의 재료입니다.</p>' : '') +
    (others ? '<p class="hint">이것 말고도 부족합니다: ' + others + '</p>' : '') +
    '<p class="hint">상점 구입이나 거래는 커넥터에 명령 자체가 없어 앱이 대신 할 수 없습니다. ' +
    '직접 구해 오신 뒤 <b>확인</b>을 누르면 이어서 진행하고, <b>취소</b>하면 여기서 멈춥니다.</p>',
    '구해 왔습니다 — 계속');
}
