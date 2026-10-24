'use strict';
/* 작업 큐 — 목표 루프 · 큐 · 한 번 하는 행동 · 작업 기록. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 목표 걸기 ───────────────────────────────────── */

/* "이걸 N개 만들어 줘" — 끝까지 미는 것은 파이썬 작업 큐 (gui_app/queue_api.py GoalKind). 여기서는 견적을 보여 주고 담는다. */

/**
 * 목표를 큐에 건다.
 *
 * target 은 **새로 만들 개수**다. 판단 엔진(goal.js)은 "몇 개를 들고 있으면 끝인가"로
 * 보므로, 시작 시점의 보유량을 더해 절대 목표로 바꿔 넘긴다. 그 기준점은 큐가 이 항목을
 * 실제로 집어 들 때 다시 잡는다 — 줄 서 있는 동안 직접 캐 왔을 수도 있다.
 */
async function runGoal(name, target, label, via, have) {
  if (busy) { toast('실행 중', '이전 명령이 끝난 뒤 시도하세요.', 'bad'); return; }

  const base = Math.max(0, Number(have) || 0);
  const pre = await mm.goal.next(name, base + target);
  if (pre.error) { toast('계획 실패', pre.message || pre.error, 'bad'); return; }
  if (pre.step.kind === 'blocked') { await goalBlockedModal(pre.step, label || name); return; }

  const bal = await mm.query('wings', {});
  const est = pre.estimate;
  const okGo = await confirmModal('자동 진행',
    '<p>' + esc(label || name) + ' 를 <b>새로 ' + num(target) + '개</b> 만듭니다. ' +
    '<span class="muted">(지금 ' + num(pre.have) + '개 → ' + num(pre.have + target) + '개)</span></p>' +
    '<div class="cost">' +
      '<div>예상 <span class="big">' + num(est.wings) + '</span> 정령의 날개' +
      ' <span class="muted">(호출 ' + est.calls + '회)</span></div>' +
      '<div class="muted">보유 ' + num(bal.amount || 0) + '</div>' +
    '</div>' +
    (est.partial
      ? '<p class="hint mark-warn">이 견적은 <b>하한</b>입니다. 아직 모르는 레시피가 있어 그 아래 단계는 셀 수 없고, ' +
        '채집이 한 번에 몇 개를 줄지도 해 봐야 압니다.</p>'
      : '') +
    '<p class="hint">채집·가공·제작을 필요한 만큼 이어서 돌립니다. ' +
    '상태바의 <b>취소</b>로 언제든 멈출 수 있습니다.</p>');
  if (!okGo) return;

  // 바로 돌리지 않고 큐에 넣는다. 오른쪽 목록에서 순서를 바꾸거나 빼거나 수량을 고칠 수 있고,
  // 여러 목표를 걸어 두고 자리를 비울 수도 있다.
  qAdd({ via: via || '제작', name: name, label: label || name, target: target,
    wings: est.wings, partial: !!est.partial });
}

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
  done: '완료', fail: '중단 — 이유를 읽고 ▶ 로 다시 걸거나 정리로 치웁니다', run: '진행 중',
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

/** 중단된 항목을 치운다. 완료는 끝나는 즉시 스스로 빠지므로, 남는 것은 막혔거나 실패한 것들이다. */
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
      (x.note ? '<div class="q-note">' + esc(x.note) + '</div>' : '') +
      (run
        ? ''
        : '<div class="q-move">' +
          '<button class="q-btn" data-q-up="' + x.id + '"' + (i === 0 ? ' disabled' : '') + ' title="위로">▲</button>' +
          '<button class="q-btn" data-q-dn="' + x.id + '"' + (i === qItems.length - 1 ? ' disabled' : '') + ' title="아래로">▼</button>' +
          '</div>') +
      '</div>';
  }).join('');
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
