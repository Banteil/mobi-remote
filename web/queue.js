'use strict';
/* 작업 큐 — 목표 루프 · 큐 · 한 번 하는 행동 · 작업 기록. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 목표 루프 ───────────────────────────────────── */

/**
 * "이걸 N개 만들어 줘"를 끝까지 밀고 간다.
 *
 * 무엇을 할지는 메인(src/goal.js)이 한 걸음씩 정하고, 여기서는 그 걸음을 실행하고
 * 사람이 개입해야 하는 순간만 처리한다. 매 걸음마다 상태를 새로 읽으므로
 * 채집이 예상보다 많이 들어오든, 가공이 늦게 끝나든 알아서 따라간다.
 *
 * 멈추는 조건은 셋뿐이다 — 목표 달성, 사람이 취소, 그리고 **진전이 없을 때.**
 * 마지막이 제일 중요하다. 헛돌면서 날개를 태우는 것이 가장 나쁜 실패다.
 */
const GOAL_MAX_STEPS = 300;
const GOAL_STUCK_LIMIT = 4;   // 같은 걸음이 이만큼 연달아 나오면 헛도는 것으로 본다

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

/** 큐 항목이 지금 노리는 절대 수량. 기준점 + 새로 만들 개수. */
function goalAbsolute(it) {
  return (it.base || 0) + it.target;
}

/**
 * 큐에 담긴 목표 하나를 끝까지 민다.
 *
 * 예전에는 이 루프가 곧 자동 진행이었다. 지금은 큐가 순서를 정하고 이 함수는 한 항목만 맡는다.
 * 진행 상황은 상태바가 아니라 그 항목의 카드에 적는다 — 여러 개가 줄 서 있으면 어느 것의
 * 이야기인지 알 수 없기 때문이다.
 *
 * @returns 끝까지 갔으면 true
 */
async function runGoalItem(it) {
  const name = it.name, label = it.label;

  // 기준점은 실제로 시작할 때 잡는다. 큐에서 기다리는 동안 보유량이 달라졌을 수 있다.
  // 이미 잡혀 있다면(정지했다가 이어가는 중) 그대로 둔다 — 다시 잡으면 한 일이 없던 것이 된다.
  if (it.base === undefined) {
    try {
      const r0 = await mm.goal.next(name, 0);
      it.base = r0 && r0.have !== undefined ? r0.have : 0;
    } catch (_) { it.base = 0; }
    saveQueue();
  }
  const target = goalAbsolute(it);
  let spent = 0, done = 0, lastKey = '', repeat = 0;
  let okEnd = false;

  for (let i = 0; i < GOAL_MAX_STEPS; i++) {
    if (qStop) break;

    const r = await mm.goal.next(name, goalAbsolute(it));
    if (r.error) { qNote(it, '중단 — ' + (r.message || r.error)); break; }
    const st = r.step;
    it.have = r.have;
    it.made = Math.max(0, r.have - (it.base || 0));

    if (st.kind === 'done') {
      qNote(it, '달성 — 새로 ' + num(it.made) + '개 (날개 ' + num(spent) + ')');
      okEnd = true;
      break;
    }
    if (st.kind === 'blocked') {
      qNote(it, '막힘 — ' + (st.message || st.reason || ''));
      if (!(await goalBlockedModal(st, label || name))) break;
      continue;   // 구해 왔다니 다시 판단해 본다
    }

    // 같은 걸음만 반복되면 헛도는 것이다. 기다림은 원래 반복되므로 제외한다.
    const key = st.kind + ':' + (st.name || '') + ':' + (st.batch || st.runs || '');
    repeat = key === lastKey && st.kind !== 'wait' ? repeat + 1 : 0;
    lastKey = key;
    // 학습은 한 번 해 보고 안 되면 더 해도 안 된다. 5씩 태울 이유가 없다.
    const limit = st.kind === 'learn' ? 1 : GOAL_STUCK_LIMIT;
    if (repeat >= limit) {
      qNote(it, '진전이 없어 멈춤 — ' + (st.name || st.kind) + ' ' + (repeat + 1) + '회 반복');
      break;
    }

    qNote(it, '[' + (done + 1) + '] ' + (st.why || st.kind));

    if (st.kind === 'wait') {
      if (!(await goalWait(st))) break;
      continue;
    }

    const spentNow = await goalExecute(st, done + 1);
    if (spentNow === null) break;     // 실패했고 이어갈 수 없다
    spent += spentNow;
    done++;
    it.spent = spent;
    it.steps = done;
    paintQueue();
  }

  setBusy(false);
  it.spent = spent;
  it.steps = done;
  return okEnd;
}

/* ── 작업 큐 ────────────────────────────────────── */

/**
 * 목표를 줄 세워 두고 하나씩 민다.
 *
 * 캐릭터는 하나고 CLI 호출도 하나씩이라 **동시에 돌릴 수가 없다.** 그래서 큐다.
 * 예전에는 목표를 누르면 그 자리에서 끝까지 돌았고, 그동안 다른 목표를 걸 수 없었다.
 * 이제는 걸어 두기만 하면 순서대로 진행되고, 진행 중에도 뒤에 더 붙이거나 순서를 바꿀 수 있다.
 *
 * 진행 상황은 상태바가 아니라 **그 항목의 카드**에 적는다. 여러 개가 줄 서 있으면
 * "제작 중"이라는 한 줄만으로는 어느 것 이야기인지 알 수 없다.
 */
let qItems = [];
let qRunning = false;
let qSeq = 1;

/**
 * 큐를 세우는 이유 — 하나만 둔다. 돌고 있는 카드가 끝나면 qTick 이 이걸 보고 그 카드를 어떻게 둘지 정한다.
 * 예전에는 qAbort·qRestart·qSkillHalt·카드의 pauseAfter·preempted 가 따로 놀아 순서가 꼬였다 (2026-10-24 F12·▶ 문제).
 *
 *   stopped : 작업이 스스로 멈춤 (숙제 F12·어비스 멈추기) → 일시정지
 *   preempt : '지금 바로' 에 밀림 → 대기로 돌리고 큐를 곧바로 다시 돌린다
 *   pause   : 사람이 멈춤 (⏸·■·취소) → 일시정지
 *   remove  : 돌던 카드를 뺐거나 큐를 비움
 *   skill   : 생활 스킬 레벨 부족 { what, level } → 중단 (기다려도 안 풀린다)
 * 둘이 겹치면 센 쪽 (뒤로 갈수록 셈). 예: 밀리던 숙제가 STOP 으로 끝나도 '밀림' 그대로.
 */
let qStop = null;
const Q_STOP_RANK = { stopped: 0, preempt: 1, pause: 2, remove: 3, skill: 4 };

/** 세우는 이유를 적어 둔다 (돌고 있는 작업에는 알리지 않음 — 작업이 스스로 멈췄을 때). */
function qSetStop(reason, extra) {
  if (!qStop || Q_STOP_RANK[reason] > Q_STOP_RANK[qStop.reason]) qStop = Object.assign({ reason }, extra);
}

/** 큐를 세운다: 이유를 적고, 돌고 있는 카드 종류에 알린다 (숙제는 일시정지·종료, 어비스는 멈춤). 목표·행동은 걸음 사이에 qStop 을 본다. */
function qRequestStop(reason, extra) {
  qSetStop(reason, extra);
  const cur = qItems.find((x) => x.status === 'run');
  const k = cur && qKind(cur);
  if (k && k.stop) k.stop(reason);
}

/**
 * 카드 종류. 종류마다 다른 것은 여기에만 둔다 (daily·abyss 는 daily.js 가 더한다).
 *   run(it)      → 끝까지 갔으면 true
 *   amount(x)    → 수량·내용 한 줄 (카드·기록)
 *   card(x)      → 카드의 수량 칸 HTML (없으면 amount 한 줄)
 *   editable     → ✎ (목표 수량 바꾸기)
 *   doneToast(x) → 끝났을 때 토스트 [제목, 내용] (없으면 안 띄움)
 *   stop(reason) → 큐가 설 때 돌고 있는 작업에 알림
 */
const Q_KINDS = {
  goal: {
    run: (it) => runGoalItem(it),
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
    run: (it) => runActionItem(it),  // 결과 토스트는 runAction 이 띄운다
    amount: (x) => x.detail || '',
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

async function loadQueue() {
  let saved = null;
  try { saved = await mm.queue.load(); } catch (_) { return; }
  qItems = (saved && Array.isArray(saved.items) ? saved.items : []).map((x) => Object.assign({}, x, {
    // 앱을 껐다 켜면 "진행 중"이던 것은 더 이상 진행 중이 아니다
    status: x.status === 'run' ? 'wait' : x.status,
  }));
  for (const x of qItems) qSeq = Math.max(qSeq, (Number(x.id) || 0) + 1);
  paintQueue();
}

function saveQueue() {
  // 진행 중에도 자주 불린다. 실패해도 화면은 그대로 돈다.
  mm.queue.save({ items: qItems }).catch(() => {});
}

function qAdd(spec) {
  const it = Object.assign({
    id: qSeq++,
    status: 'wait',
    note: '',
    spent: 0,
    steps: 0,
  }, spec);
  qItems.push(it);
  paintQueue();
  saveQueue();
  // 담기만 하고 돌리지는 않는다. 날개가 나가는 일은 사람이 재생을 누른 뒤에 시작해야 한다.
  toast('큐에 담았습니다', it.label + ' 새로 ' + num(it.target) + '개 — 재생을 누르면 진행합니다.', 'ok');
  return it;
}

function qFind(id) { return qItems.find((x) => String(x.id) === String(id)); }

function qNote(it, text) {
  it.note = text;
  paintQueue();
}

function qRemove(id) {
  const it = qFind(id);
  if (!it) return;
  if (it.status === 'run') { qRequestStop('remove'); qNote(it, '멈추는 중…'); }
  else if (it.kind === 'daily') mm.daily.pauseCancel();  // 일시정지 중인 숙제 카드를 지우면 종료 (F12 로 이어 하지 않음)
  qItems = qItems.filter((x) => x !== it);
  paintQueue();
  saveQueue();
}

/**
 * 지금 바로 시작 (일일 숙제 '숙제 시작' · 어비스 '반복 시작').
 *
 * 맨 위에 넣고 바로 돌린다. 돌고 있는 작업이 있으면 세워서 대기로 돌리고(뒤로 밀림), 이 작업이 끝나면
 * 이어서 한다. 큐 뒤에 담기만 하는 것은 '목표' 버튼 (제작·채집·가공 목표와 같은 방식).
 */
function qStartNow(it) {
  qItems = qItems.filter((x) => x !== it);
  it.status = 'wait';
  qItems.unshift(it);
  const cur = qItems.find((x) => x.status === 'run');
  paintQueue();
  saveQueue();
  if (!cur) { qTick(); return; }
  qRequestStop('preempt');  // 숙제는 일시정지·어비스는 멈춤 (제작·채집 목표는 이번 걸음을 마치고)
  qNote(cur, '뒤로 미루는 중…');
}

/* ── 한 번 하는 행동 (제작·채집·가공·수령·연주) ──
 * 파란 버튼 = 지금 바로 (qStartNow — 돌던 작업은 뒤로 밀렸다가 이어서), '목표' 버튼 = 큐 맨 아래에 담기.
 * 숙제·어비스가 도는 중에 버튼을 눌러도 게임 조작이 겹치지 않게 모두 큐를 거친다. 날개가 드는 것은 넣기 전에 묻는다. */
async function actSpec(spec) {
  if (spec.command && !(await confirmCost(spec.command, { label: spec.label, note: spec.note, skipConfirm: spec.skipConfirm }))) return null;
  return Object.assign({ id: qSeq++, kind: 'action', status: 'wait', note: '' }, spec);
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
  qItems.push(it);
  paintQueue();
  saveQueue();
  toast('큐에 담았습니다', it.label + ' — 재생을 누르면 진행합니다.', 'ok');
}

const ACT_REFRESH = { craft: () => loadCraft(true), alter: () => loadAlter(true), collect: () => loadAlter(true) };

/** 큐가 부른다. 행동 하나를 하고 성공했으면 true. */
async function runActionItem(it) {
  if (it.act === 'collectAll') { await collectAll(); return true; }
  const r = await runAction(it.command, it.body, { label: it.label, skipConfirm: true });
  if (ACT_REFRESH[it.act]) ACT_REFRESH[it.act]();
  if (!r || !r.ok) qNote(it, '실패 — ' + ((r && r.ko && r.ko.text) || (r && (r.message || r.error)) || '알 수 없음'));
  return !!(r && r.ok);
}

/** 이 항목부터 돌린다. 대기 줄의 맨 앞으로 올리고 큐를 깨운다. */
function qPlayOne(id) {
  const it = qFind(id);
  if (!it) return;
  if (it.status === 'run') return;
  // 이미 끝난 것을 다시 거는 것이면 기준점을 새로 잡는다.
  // 일시정지였다면 그대로 둬야 하던 자리에서 이어간다.
  if (it.status === 'done' || it.status === 'fail') {
    delete it.base;
    delete it.made;
    delete it.doneRuns;  // 어비스 카드
    delete it.doneSecs;
    it.spent = 0;
    it.steps = 0;
    it.note = '';
  }
  it.status = 'wait';
  // 진행 중인 항목 바로 뒤, 다른 대기 항목보다는 앞에 둔다
  qItems = qItems.filter((x) => x !== it);
  const at = qItems.findIndex((x) => x.status === 'run');
  qItems.splice(at < 0 ? 0 : at + 1, 0, it);
  paintQueue();
  saveQueue();
  qTick();
}

/**
 * 진행 중인 이 항목에서 큐를 일시정지한다 (카드의 ⏸ — 돌고 있는 카드에만 있다).
 *
 * 지금 걸음을 마치고 멈춘다. 카드는 일시정지로 남아 ▶ 를 누르면 하던 자리에서 이어 간다 (기준점을 다시 잡지 않는다).
 */
function qPauseOne(id) {
  const it = qFind(id);
  if (!it) return;
  if (it.status === 'run') { qRequestStop('pause'); qNote(it, '이번 걸음을 마치고 멈춥니다…'); }
}

function qMove(id, delta) {
  const i = qItems.findIndex((x) => String(x.id) === String(id));
  const j = i + delta;
  if (i < 0 || j < 0 || j >= qItems.length) return;
  const t = qItems[i]; qItems[i] = qItems[j]; qItems[j] = t;
  paintQueue();
  saveQueue();
}

async function qEdit(id) {
  const it = qFind(id);
  if (!it || !qKind(it).editable) return;
  const n = await promptNumber('목표 수량 바꾸기', '"' + it.label + '" 를 새로 몇 개?', it.target,
    '진행 중인 항목도 바꿀 수 있습니다. 다음 걸음부터 새 수량으로 판단하며, ' +
    '이미 만든 만큼은 그대로 인정합니다.');
  if (!n) return;
  it.target = n;
  if (it.status === 'done' || it.status === 'fail') it.status = 'wait';
  paintQueue();
  saveQueue();
  qTick();
}

/**
 * 중단된 항목을 치운다.
 *
 * 완료는 끝나는 즉시 스스로 빠지므로, 여기 남는 것은 막혔거나 실패한 것들이다.
 * 이유를 읽고 나면 더 볼 일이 없으니 한 번에 치운다.
 */
function qTidy() {
  qItems = qItems.filter((x) => ['wait', 'run', 'pause'].indexOf(x.status) >= 0);
  paintQueue();
  saveQueue();
}

/** 전부 지운다. 되돌릴 수 없으니 한 번 물어본다. */
async function qClear() {
  if (!qItems.length) return;
  const ok = await confirmModal('작업 큐 비우기',
    '<p>담아 둔 <b>' + qItems.length + '건</b>을 전부 지웁니다.</p>' +
    '<p class="hint">진행 중인 것이 있으면 이번 걸음을 마치고 멈춥니다. 이미 쓴 정령의 날개는 돌아오지 않습니다.</p>',
    '전부 지우기');
  if (!ok) return;
  if (qItems.some((x) => x.kind === 'daily' && x.status !== 'run')) mm.daily.pauseCancel();  // 일시정지한 숙제는 종료
  qRequestStop('remove');
  qItems = [];
  paintQueue();
  saveQueue();
}

/** 재생 ▶ (전체 시작). 일시정지한 카드도 대기로 되돌려 위에서부터 차례로 한다.
 * ('보류' — 건너뛰기 — 는 헷갈려서 없앴다. 멈춘 것은 모두 일시정지, 2026-10-24) */
function qPlayAll() {
  for (const x of qItems) if (x.status === 'pause') x.status = 'wait';
  paintQueue();
  saveQueue();
  qTick();
}

/** 부드럽게 멈춘다. 항목 상태는 그대로라 재생을 누르면 이어진다. */
function qPause() {
  if (!qRunning) return;
  qRequestStop('pause');
  say('이번 걸음을 마치고 멈춥니다.');
}

/**
 * 지금 명령까지 끊고 멈춘다.
 *
 * ⏸ 와 다른 점은 걸음이 끝나길 기다리지 않고 돌고 있는 CLI 호출에 취소를 보내는 것. 카드는 똑같이 일시정지.
 */
async function qHalt() {
  qRequestStop('pause');
  try { await mm.cancel(); } catch (_) {}
  say('멈추는 중입니다.');
}

/**
 * 대기 중인 것을 위에서부터 하나씩 민다.
 *
 * 한 항목이 실패해도 큐를 통째로 세우지 않는다. "재료를 직접 구해 오세요"로 막힌 것과
 * 그 뒤에 줄 서 있는 다른 목표는 서로 상관이 없다. 실패한 카드는 이유를 달고 남는다.
 */
async function qTick() {
  if (qRunning) return;
  if (busy) return;              // 다른 명령이 도는 중이면 끼어들지 않는다
  qRunning = true;
  qStop = null;
  paintQueue();

  let drained = false;  // 할 것이 없어서 끝났나 (멈춤·일시정지가 아니라) → 화면 설정 되돌리기
  let restart = false;  // '지금 바로' 에 밀려 섰다 → 곧바로 다시 돈다
  try {
    while (!qStop) {
      const it = qItems.find((x) => x.status === 'wait');
      if (!it) { drained = !qItems.some((x) => x.status === 'pause'); break; }  // 일시정지한 카드가 남았으면 아직 끝이 아니다
      it.status = 'run';
      it.startedAt = Date.now();
      qNote(it, '시작');
      saveQueue();

      const kind = qKind(it);
      let ok = false;
      try { ok = await kind.run(it); }
      catch (err) { qNote(it, '오류 — ' + (err && err.message)); }

      // 도중에 지워졌으면 상태를 되살리지 않는다
      if (!qItems.includes(it)) { qRecord(it, 'removed'); continue; }

      // 다 만든 카드는 치운다. 남겨 두면 할 일 목록에 "할 일이 아닌 것"이 쌓이고,
      // 정작 다음에 뭘 할 차례인지가 안 보인다. 기록은 토스트와 파일 로그에 남는다.
      if (ok) {
        qRecord(it, 'done');
        qItems = qItems.filter((x) => x !== it);
        const t = kind.doneToast && kind.doneToast(it);  // 일일 숙제는 결과 보고서 창이 따로 뜬다
        if (t) toast(t[0], t[1], 'ok');
        paintQueue();
        saveQueue();
        continue;
      }

      const why = qStop && qStop.reason;
      if (!why) {
        it.status = 'fail';
      } else if (why === 'preempt') {
        // 지금 바로 시작에 밀린 것: 대기로 되돌려 앞 작업이 끝나면 이어서 한다
        it.status = 'wait';
        restart = true;
        qNote(it, '뒤로 밀림 — 앞 작업이 끝나면 이어서');
      } else if (why === 'skill') {
        // 스킬 레벨은 시간이 지난다고 오르지 않는다. 대기로 되돌리면 재생을 누를 때마다
        // 같은 거절을 다시 받으므로, 중단으로 못 박고 이유를 카드에 적는다.
        it.status = 'fail';
        qNote(it, '생활 스킬 레벨 부족 — ' + qStop.what +
          (qStop.level ? ' (필요 Lv.' + qStop.level + ')' : '') + ' · 날개는 쓰이지 않았습니다.');
        toast('생활 스킬 레벨이 모자랍니다',
          qStop.what + ' 을(를) 캘 수 없어 작업 큐를 세웠습니다.' +
          (qStop.level ? ' 필요 레벨 ' + qStop.level + '.' : ''), 'bad');
      } else {
        // 사람이 멈춘 것(⏸·■·F12)은 실패가 아니다 — 일시정지로 두고, ▶ 로 하던 자리에서 이어 간다.
        it.status = 'pause';
        qNote(it, it.kind === 'daily' ? '일시정지 · ' + stopKey() + ' 나 ▶ 로 재개' : '일시정지 · ▶ 로 재개');
      }
      qRecord(it, it.status === 'fail' ? 'fail' : it.status === 'pause' ? 'pause' : 'stop');
      paintQueue();
      saveQueue();
    }
  } finally {
    qRunning = false;
    qStop = null;
    paintQueue();
    if (restart) setTimeout(qTick, 0);  // 지금 바로 시작한 작업으로
    else if (drained && typeof qDisplayEnd === 'function') qDisplayEnd();  // 큐 한 번이 끝남 → 맞춘 화면 설정 되돌리기
    // 큐가 비면 화면을 한 번 새로 고친다. 수량이 많이 바뀌어 있다.
    try { await refreshActive(); } catch (_) {}
  }
}


/* ── 작업 기록 ── 끝난 항목(완료·실패·일시정지·뺌)을 한 줄씩 파일에 남기고 '기록' 창에서 본다 */
const QH_RESULT = {
  done: ['완료', 'pill-ok'], fail: ['실패', 'pill-bad'], pause: ['일시정지', 'pill-warn'],
  stop: ['멈춤', 'pill-muted'], removed: ['뺌', 'pill-muted'],
};

/** 카드 한 장의 수량·내용 한 줄 (기록용) */
function qDetail(x) {
  return qKind(x).amount(x);
}

function qRecord(it, result) {
  mm.queue.record({
    start: it.startedAt || Date.now(), end: Date.now(), kind: it.kind || 'goal', label: it.label, result,
    detail: qDetail(it), note: it.note || '',
  }).catch(() => {});
}

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
/** 한 걸음을 실제로 실행한다. 소모한 날개를 돌려주고, 이어갈 수 없으면 null. */
async function goalExecute(st, n) {
  const tag = '(' + n + ') ';

  if (st.kind === 'collect') {
    let r = await runAction('complete_altering_work', { displayName: st.name },
      { label: tag + st.facility + ' 수령', skipConfirm: true });
    // 보상 창이 떠서 막혔으면 사람이 닫기를 기다렸다가 한 번 더
    if (r && !r.ok && r.error === 'blocked') {
      if (await waitForUserInput(st.facility)) {
        r = await runAction('complete_altering_work', { displayName: st.name },
          { label: tag + st.facility + ' 수령(재시도)', skipConfirm: true });
      }
    }
    return r && r.ok ? (r.wingsSpent || 0) : null;
  }

  const isAlter = st.kind === 'alter' || (st.kind === 'learn' && st.via === '가공');
  const command =
    st.kind === 'gather' ? 'execute_gathering'
    : isAlter ? 'execute_altering'
    : 'execute_crafting';

  const body =
    command === 'execute_crafting'
      ? { displayName: st.name, craftCount: st.kind === 'learn' ? 1 : (st.batch || 1) }
      : { displayName: st.name };

  let r = await runAction(command, body, { label: tag + (st.why || st.name), skipConfirm: true });

  // 게임 쪽 확인 창에 막힌 것이면 기다렸다가 한 번 더 시도한다.
  // 다만 가공은 막혀도 날개가 이미 나가므로(실측) 재시도가 공짜가 아니다 — 한 번만.
  if (r && !r.ok && r.error === 'blocked') {
    if (await waitForUserInput(st.name)) {
      r = await runAction(command, body, { label: tag + st.name + ' (재시도)', skipConfirm: true });
    }
  }

  if (!r) return null;
  if (!r.ok) {
    // 상한을 넘겼다면 메인이 maxCount를 배웠다. 다음 걸음에서 맞춰 부른다.
    if (r.error === 'invalid_count') return 0;

    /**
     * 생활 스킬 레벨이 모자라 채집이 아예 안 되는 경우.
     *
     * **기다린다고 풀리지 않는다.** 재료가 모자란 것과 달리 다시 불러도 같은 답만 온다.
     * 그런데 큐는 "진전이 없을 때"까지 몇 번 더 돌아 보는 구조라, 그냥 두면 같은 거절을
     * 반복하며 시간만 쓴다. 그래서 그 자리에서 카드를 접고 큐 전체를 세운다 — 사람이
     * 스킬을 올리기 전에는 뒤에 줄 선 목표도 이 재료를 넘지 못한다.
     *
     * 날개는 안 나간다. CLI 문서상 이 오류는 "rejected before starting" 쪽이고,
     * 시작 전 거절은 비용을 물리지 않는다.
     */
    if (r.error === 'insufficient_living_skill_level') {
      qSetStop('skill', {
        what: st.name,
        level: r.requiredLevel || (r.data && r.data.requiredLevel) || null,
        message: r.message || null,
      });
      return null;
    }
    return null;
  }
  return r.wingsSpent || 0;
}

/** 가공이 끝나기를 기다린다. 남은 시간을 상태바에 보여주고, 취소를 받는다. */
async function goalWait(st) {
  const until = Date.now() + Math.max(5, st.seconds) * 1000;
  toast('대기', st.why || '가공이 끝나기를 기다립니다.', 'ok');
  while (Date.now() < until) {
    if (qStop) return false;
    const left = Math.ceil((until - Date.now()) / 1000);
    setBusy(true, '가공 완료까지 ' + dur(left) + ' 대기 중… (취소 가능)');
    await sleep(Math.min(2000, until - Date.now()));
  }
  setBusy(false);
  return true;
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
