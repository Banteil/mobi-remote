'use strict';
/**
 * 일일 숙제 · 숙제 기록 탭 (파이썬판에서 새로 생긴 화면). app.js 의 $, esc, num, toast, say, LOADERS 를 같이 쓴다.
 *
 * 숙제는 파이썬(mabi/runner)이 돌리고, 진행 이벤트를 mm.daily.onEvent 로 받는다:
 *   start · character · task_start · task_end{status, summary, seconds} · done · failed
 */
const ST_TEXT = {
  OK: '완료', DONE: '완료', TODO: '아직 안 함', CHECK: '남음', MANUAL: '남음(직접)', FAIL: '실패', ERROR: '오류', HEAVY: '가방 무게',
  SKIP: '건너뜀', STOP: '중단', RUN: '진행 중',
};
const INHERIT = 'inherit';
const dl = { st: null, settings: null, pickedChars: null, pickedTasks: null, logN: 0 };

/* ── 오늘 진행 표 ── */

async function loadDaily() {
  dl.st = await mm.daily.state();
  dl.settings = await mm.daily.settings();
  if (!dl.pickedChars) dl.pickedChars = new Set(dl.st.chars.map((c) => c.slot));
  if (!dl.pickedTasks) dl.pickedTasks = new Set(dl.st.order);
  $('#dl-date').textContent = '게임 날짜 ' + dl.st.date + ' (오전 6시에 바뀜)';
  paintDailyTable();
  paintDailyRunning(dl.st.running);
  paintDailySettings();
  $('#dl-fit').checked = dl.settings.fit_display !== false;
}

function stateOf(v) {
  if (!v) return null;
  return v === 'done' ? 'DONE' : String(v).split(':')[0].trim().toUpperCase();
}

function paintDailyTable() {
  const st = dl.st;
  const cols = ['login', ...st.order];
  // 이번 실행에 넣을 캐릭터·숙제는 체크박스로 고른다 (맨 왼쪽 위 = 캐릭터 전체). 접속은 늘 한다
  const box = (attr, on) => '<input type="checkbox" ' + attr + (on ? ' checked' : '') + '>';
  const allOn = st.chars.length > 0 && st.chars.every((c) => dl.pickedChars.has(c.slot));
  $('#dl-table thead').innerHTML = '<tr><th class="dl-name"><label class="chk dl-pick">' +
    box('data-dl-all', allOn) + '캐릭터</label></th>' + cols.map((t) => t === 'login'
    ? '<th class="dl-cell">' + esc(st.labels[t] || t) + '</th>'
    : '<th class="dl-cell' + (dl.pickedTasks.has(t) ? '' : ' off') + '"><label class="chk dl-pick">' +
      box('data-dl-task="' + esc(t) + '"', dl.pickedTasks.has(t)) + esc(st.labels[t] || t) + '</label></th>').join('') + '</tr>';
  $('#dl-table tbody').innerHTML = st.chars.map((c) => {
    const today = st.today[String(c.slot)] || {};
    const on = dl.pickedChars.has(c.slot);
    return '<tr class="' + (on ? '' : 'off') + '"><td class="dl-name"><label class="chk dl-pick">' +
      box('data-dl-char="' + c.slot + '"', on) + c.slot + '. ' + esc(c.name) + '</label></td>' + cols.map((t) => {
        if ((st.skip[String(c.slot)] || []).includes(t)) {
          return '<td class="dl-cell st-SKIP" title="캐릭터 탭에서 끔">안 함</td>';
        }
        const s = stateOf(today[t]);
        return '<td class="dl-cell st-' + (s || '') + '" id="dl-' + c.slot + '-' + t + '" title="' + esc(today[t] || '') + '">' +
          (s ? esc(ST_TEXT[s] || s) : '') + '</td>';
      }).join('') + '</tr>';
  }).join('') || '<tr><td class="muted">캐릭터 탭에서 캐릭터를 추가하세요</td></tr>';
  const n = dl.pickedChars.size, m = dl.pickedTasks.size;
  $('#dl-pick-note').textContent = n + '명 · 숙제 ' + m + '개';
}

function setCell(slot, task, status, tip) {
  const td = document.getElementById('dl-' + slot + '-' + task);
  if (!td) return;
  td.className = 'dl-cell st-' + status;
  td.textContent = ST_TEXT[status] || status;
  td.title = tip || '';
}

/* 버튼 세 상태: 쉬는 중(숙제 시작) · 실행 중(일시정지) · 일시정지(이어 하기). 그만두려면 작업 큐에서 카드를 뺀다.
 * 일시정지는 큐의 숙제 카드가 일시정지(pause)인 것으로 안다 — 큐 그림이 바뀔 때마다 다시 칠한다 (app.js paintQueue → dlRefresh) */
function dlPausedCard() {
  return qItems.find((x) => x.kind === 'daily' && x.status === 'pause');
}

function paintDailyRunning(on) {
  dl.running = on;
  const paused = !on && !!dlPausedCard();
  $('#dl-start').textContent = paused ? '이어 하기 (' + stopKey() + ')' : '숙제 시작';
  $('#dl-start').classList.toggle('hidden', on);
  $('#dl-stop').classList.toggle('hidden', !on);
  const p = $('#dl-state');
  p.textContent = on ? '실행 중' : '일시정지';
  p.className = 'pill ' + (on ? 'pill-ok' : 'pill-warn');
  p.classList.toggle('hidden', !on && !paused);
}

function dlRefresh() {
  paintDailyRunning(!!dl.running);
}

mm.daily.onEvent((e) => {
  if (!e) return;
  const qi = qItems.find((x) => x.kind === 'daily' && x.status === 'run');
  if (e.type === 'task_start') {
    setCell(e.slot, e.task, 'RUN', e.label);
    say('진행 중: ' + e.label);
    if (qi) qNote(qi, e.label);
  } else if (e.type === 'task_end') {
    setCell(e.slot, e.task, e.status, (e.summary || '') + ' (' + e.seconds + '초)');
  } else if (e.type === 'done') {
    paintDailyRunning(false);
    // 일시정지(F12)로 멈춘 것이면 보고서는 끝까지 간 뒤에. '결과 보기' 와 같은 오늘 하루 전체 결과로 띄운다
    // (이번 실행분만 보이면 끊어 돌린 날 앞 실행 결과가 빠진다)
    if (!(e.results || []).some((x) => x[1] === 'STOP')) showTodayReport(true);
  } else if (e.type === 'paused') {
    const p = $('#dl-state');
    p.textContent = '일시정지 · ' + stopKey() + '로 재개';
    p.className = 'pill pill-warn';
    say('일시정지 — ' + stopKey() + '를 누르면 이어 합니다');
  } else if (e.type === 'resume') {
    // 일시정지 중 F12 → 큐의 숙제 카드를 다시 돌린다 (카드를 지웠으면 = 종료, 아무것도 안 함).
    // 다른 작업이 돌고 있으면 그 F12 는 그 작업의 것이다 — 숙제를 깨우지 않는다
    const card = qItems.find((x) => x.kind === 'daily');
    if (card && !qItems.some((x) => x.status === 'run')) qPlayOne(card.id);
  } else if (e.type === 'failed') {
    paintDailyRunning(false);
    toast('일일 숙제를 시작하지 못했습니다', e.message, 'bad');
  }
  if ((e.type === 'done' || e.type === 'failed') && dlWaiter) dlWaiter(e);
});

// 로그는 일일 숙제 · 어비스 탭 둘 다에 (같은 로그 — 어느 쪽에서 돌렸든 보이게)
mm.daily.onLog((m) => {
  if (!m) return;
  for (const pre of [$('#dl-log'), $('#ab-log')]) {
    if (!pre) continue;
    const line = document.createElement('div');
    if (m.level === 'WARNING') line.className = 'w';
    if (m.level === 'ERROR') line.className = 'e';
    line.textContent = m.text;
    pre.appendChild(line);
    if (pre.childElementCount > 1500) pre.removeChild(pre.firstChild);
    pre.scrollTop = pre.scrollHeight;
  }
  $('#dl-log-n').textContent = ++dl.logN + '줄';
});

/* 숙제 시작 전 게임 화면 설정 확인. 기준과 다르면 묻지 않고 자동으로 맞춘 뒤 그대로 이어서 시작한다. */
function paintDisplayState(text) {
  if (!text) { dlRefresh(); return; }
  const p = $('#dl-state');
  p.textContent = text;
  p.className = 'pill pill-warn';
}

/* 일일 숙제는 작업 큐(app.js)의 한 항목으로 돈다. 두 가지로 넣는다 (어비스와 같다):
 *  '숙제 시작' = 지금 바로 — 맨 위에 넣고 바로 시작한다. 돌던 작업은 뒤로 밀렸다가 끝나면 이어서 (qStartNow)
 *  '목표'     = 큐 맨 아래에 담기만 한다 (재생을 눌러야 진행) — 제작·채집 목표와 같은 방식
 * 게임 캐릭터는 하나라 둘이 동시에 돌면 안 되는데, 큐가 하나씩만 돌리므로 막힌다. */
function dailySpec() {
  const chars = [...dl.pickedChars];
  const only = dl.st.order.filter((t) => dl.pickedTasks.has(t));
  if (!chars.length || !only.length) { toast('캐릭터와 숙제를 하나 이상 고르세요', '', 'bad'); return null; }
  return {
    id: qSeq++, kind: 'daily', status: 'wait', note: '', label: '일일 숙제',
    chars: chars, only: only.length === dl.st.order.length ? null : only, force: $('#dl-force').checked,
    fit: $('#dl-fit').checked,
  };
}

function startDaily() {
  if (qItems.some((x) => x.kind === 'daily' && x.status === 'run')) { toast('이미 실행 중입니다', '', 'bad'); return; }
  const it = dailySpec();
  if (!it) return;
  qItems = qItems.filter((x) => !(x.kind === 'daily' && x.status === 'pause'));  // 멈춰 둔 숙제 카드는 새 것으로 바꾼다
  const cur = qItems.find((x) => x.status === 'run');
  toast('일일 숙제 시작', stopKey() + ' = 일시정지 · 다시 누르면 재개' +
    (cur ? ' · 진행 중이던 "' + cur.label + '" 은 뒤로 미룹니다' : ''), 'ok');
  qStartNow(it);
}

function queueDaily() {
  const it = dailySpec();
  if (!it) return;
  qItems.push(it);
  paintQueue();
  saveQueue();
  toast('큐에 담았습니다', '일일 숙제 — ' + it.chars.length + '명 · ' + (it.only ? '숙제 ' + it.only.length + '개' : '전체') +
    ' · 재생을 누르면 진행합니다.', 'ok');
}

/* 숙제를 시작하기 전 게임 화면 설정 확인. 기준과 다르면 묻지 않고 자동으로 맞춘 뒤 이어서 시작한다
 * (끝나면 원래대로 되돌린다). '숙제 시작' 이든 '목표' 로 담은 카드든 큐가 숙제를 꺼낼 때 한다. */
let dlDisplayWaiter = null;

/* 작업 큐 한 번 도는 동안의 화면 설정 — 처음 한 번만 확인·맞추고(screen), 인터페이스도 한 번만(iface).
 * 큐가 다 끝나면(app.js qTick) 맞춘 적이 있을 때 한 번 되돌린다 (qDisplayEnd). 일시정지·멈춤은 끝이 아니다. */
const qDisplay = { screen: false, iface: false, used: false };

function qDisplayEnd() {
  if (!qDisplay.used) return;
  qDisplay.screen = qDisplay.iface = qDisplay.used = false;
  mm.daily.displayRestore().catch(() => {});
}

mm.daily.onDisplay((m) => {
  if (m && m.restored && m.message) toast(m.ok ? '화면 설정을 되돌렸습니다' : '화면 설정을 되돌리지 못했습니다', m.message, m.ok ? 'ok' : 'bad');
});

async function ensureDisplay(it) {
  if (it.fit === false) return true;  // 이 카드는 화면 설정을 건드리지 않는다
  qDisplay.used = true;
  if (qDisplay.screen) return true;  // 이번 큐에서 이미 확인·맞춤
  mm.daily.displayWaitCancel();
  paintDisplayState('화면 설정 확인 중');
  // 고른 숙제가 오늘 다 끝났으면 화면 설정은 보지 않는다 (ok) — 숙제는 '오늘 완료' 만 알린다
  // only 가 없으면 전체 (파이썬이 그렇게 받는다) — 일일 숙제 탭을 안 열었으면 dl.st 가 아직 없다
  const d = await mm.daily.displayCheck({ chars: it.chars, only: it.only, force: it.force });
  if (d && d.ok) { paintDisplayState(''); qDisplay.screen = !d.idle; return true; }
  say('화면 설정 맞추는 중: ' + ((d && d.problems) || ['확인 실패']).join(', '));
  paintDisplayState('화면 설정 맞추는 중');
  qNote(it, '화면 설정 맞추는 중');
  const done = new Promise((res) => { dlDisplayWaiter = res; });
  const r = await mm.daily.displayFix();
  if (r && r.error) {
    dlDisplayWaiter = null;
    paintDisplayState('');
    toast('맞추지 못했습니다', r.error, 'bad');
    qNote(it, '화면 설정 실패 — ' + r.error);
    return false;
  }
  const m = await done;
  paintDisplayState('');
  if (!m.ok) { toast('화면 설정을 맞추지 못했습니다', m.message, 'bad'); qNote(it, '화면 설정 실패 — ' + (m.message || '')); return false; }
  toast(m.running === false ? '화면 설정을 파일로 맞췄습니다' : '화면 설정을 맞췄습니다', m.message, 'ok');
  qDisplay.screen = m.running !== false;
  return true;
}

mm.daily.onDisplay((m) => {
  if (!m) return;
  const w = dlDisplayWaiter;
  if (m.resume) {  // 직접 맞춘 뒤 F12
    if (w) { dlDisplayWaiter = null; w({ ok: true, done: true }); } else startDaily();
    return;
  }
  if (!m.done) return;
  if (w) { dlDisplayWaiter = null; w(m); return; }
  paintDisplayState('');
  if (!m.ok) toast('화면 설정을 맞추지 못했습니다', m.message, 'bad');
});

let dlWaiter = null;

/** 큐가 부른다. 숙제를 시작하고 끝날 때까지 기다린다. 끝까지 돌았으면 true (실패한 숙제가 있어도 — 결과는 보고서로 본다). */
async function runDailyItem(it) {
  if (!(await ensureDisplay(it))) return false;
  const fit = it.fit !== false;
  const r = await mm.daily.start({
    chars: it.chars, only: it.only, force: it.force,
    display: fit, interface_ready: qDisplay.iface, restore: false,  // 되돌리기는 큐가 끝날 때 한 번 (qDisplayEnd)
  });
  if (fit && !(r && r.error)) qDisplay.iface = true;
  if (r && r.error) { qNote(it, '시작 못 함 — ' + r.error); return false; }
  paintDailyRunning(true);
  const e = await new Promise((res) => { dlWaiter = res; });
  dlWaiter = null;
  if (e.type === 'failed') { qNote(it, '실패 — ' + (e.message || '')); return false; }
  const res = e.results || [];
  if (res.some((x) => x[1] === 'STOP')) {  // 일시정지(F12·버튼): 카드를 일시정지로 두고 뒤 작업도 세운다. F12 로 이어 함
    it.pauseAfter = true;
    qAbort = true;
    return false;
  }
  return true;
}

/** 큐의 ⏸·■ → 숙제 일시정지 (F12 나 ▶ 로 이어 함). 어비스는 멈춤 (▶ 로 다시). */
function qPauseDaily() {
  if (qItems.some((x) => x.kind === 'daily' && x.status === 'run')) mm.daily.stop(false);
  if (qItems.some((x) => x.kind === 'abyss' && x.status === 'run')) mm.daily.abyssStop();
}

/** 큐에서 숙제 카드를 빼거나 큐를 비우면 숙제는 종료 (F12 로 이어 하지 않음). 어비스 카드면 멈춤. */
function qStopDaily() {
  if (qItems.some((x) => x.kind === 'daily' && x.status === 'run')) mm.daily.stop(true);
  else mm.daily.pauseCancel();
  if (qItems.some((x) => x.kind === 'abyss' && x.status === 'run')) mm.daily.abyssStop();
}

/* ── 설정 ── */

function opts(list, cur, extra) {
  return (extra || []).concat(list.map((v) => [v, v])).map(([v, label]) =>
    '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(label) + '</option>').join('');
}

function paintDailySettings() {
  const s = dl.settings;
  $('#dl-field-runs').innerHTML = opts(['0', '1', '2', '3', '4', '5'], s.silver.field_runs);
  $('#dl-field').innerHTML = opts(s.fields, s.field);
  $('#dl-dungeon').innerHTML = opts(s.dungeons, s.silver.dungeon);
  // [value, label] 짝을 바로 넘겨 값 목록(list)은 비운다
  $('#dl-floor').innerHTML = opts([], s.silver.floor, Object.entries(mm.labels.floors || {}));
  const f = s.follow || {};
  const fol = (n) => (f.total ? n + '명 적용' : '');
  $('#dl-follow-field').textContent = fol(f.field);
  $('#dl-follow-dungeon').textContent = fol(f.dungeon);
  paintStopKey();
}

function collectDailySettings() {
  return {
    silver: { field_runs: Number($('#dl-field-runs').value), dungeon: $('#dl-dungeon').value, floor: Number($('#dl-floor').value) },
    field: $('#dl-field').value,
  };
}

/* 일시정지 키·폴더 경로는 옵션 창에 있다 */
function stopKey() {
  return ((dl.settings && dl.settings.stop_key) || 'f12').toUpperCase();
}

function paintStopKey() {
  $('#dl-stop').textContent = '일시정지 (' + stopKey() + ')';
}

async function loadPathSettings() {
  const s = await mm.daily.settings();
  dl.settings = Object.assign(dl.settings || {}, { stop_key: s.stop_key });
  $('#opt-stop-key').innerHTML = Array.from({ length: 12 }, (_, i) => 'f' + (i + 1)).map((k) =>
    '<option value="' + k + '"' + (k === s.stop_key ? ' selected' : '') + '>' + k.toUpperCase() + '</option>').join('');
  $('#opt-pause-touch').checked = s.pause_on_touch !== false;
  ['data', 'logs', 'shots'].forEach((k) => { $('#dl-p-' + k).value = s.paths[k] || ''; });
  $('#dl-p-now').textContent = '지금: ' + s.current.data + ' (바꾸면 다음 실행부터)';
}

async function savePathSettings() {
  const r = await mm.daily.saveSettings({
    stop_key: $('#opt-stop-key').value,
    pause_on_touch: $('#opt-pause-touch').checked,
    paths: { data: $('#dl-p-data').value, logs: $('#dl-p-logs').value, shots: $('#dl-p-shots').value },
  });
  if (!(r && r.error)) { dl.settings = Object.assign(dl.settings || {}, { stop_key: $('#opt-stop-key').value }); paintStopKey(); }
  $('#opt-paths-msg').textContent = r && r.error ? r.error : '저장했습니다';
  if (!(r && r.error)) await loadPathSettings();
}

async function saveDailySettings() {
  const r = await mm.daily.saveSettings(collectDailySettings());
  if (r && r.error) { $('#dl-save-msg').textContent = r.error; return; }
  $('#dl-save-msg').textContent = '저장했습니다';
  dl.pickedChars = null;
  await loadDaily();
}

const SHOT_RE = /\d{8}_\d{6}_[\w-]+\.png/;

/* ── 결과 보고 (숙제가 끝나면 팝업) ──
 * results: [[이름표, 상태, 요약]]. 이름표는 '[캐릭터] 숙제' 또는 '[캐릭터]'(캐릭터 전체 건너뜀).
 * 완료가 아닌 것은 원인(요약)을 목록으로 보이고, 요약에 화면 저장 파일이 있으면 눌러서 그 화면을 본다. */
/** '결과 보기'·숙제 끝: 오늘 기록(state/<날짜>.json)으로 지금까지의 결과를 보고서로 (실행 중이어도 된다).
 * finished: 숙제가 막 끝났을 때 — 'done' 시점엔 실행 스레드가 아직 살아 있어 '실행 중' 으로 나오므로 떼어 낸다 */
async function showTodayReport(finished) {
  const st = await mm.daily.state();
  const results = [];
  for (const c of st.chars) {
    const today = st.today[String(c.slot)] || {};
    for (const t of (st.orders && st.orders[String(c.slot)]) || st.order) {
      const v = today[t];
      const s = v == null ? 'TODO' : v === 'done' ? 'OK' : String(v).split(':')[0].trim().toUpperCase();
      const sum = v == null || v === 'done' ? '' : String(v).slice(String(v).indexOf(':') + 1).trim();
      results.push(['[' + c.name + '] ' + (st.labels[t] || t), s, sum]);
    }
  }
  showReport(results, '오늘 결과 (' + st.date + (st.running && finished !== true ? ', 실행 중' : '') + ')');
}

function showReport(results, title) {
  const GOOD = new Set(['OK', 'DONE']);
  const chars = new Map();
  for (const [label, st, summary] of results) {
    const m = /^\[(.+?)\]\s*(.*)$/.exec(label || '');
    const who = m ? m[1] : (label || '실행');
    const task = m ? (m[2] || '전체') : '';
    if (!chars.has(who)) chars.set(who, []);
    chars.get(who).push({ task, st, summary: summary || '' });
  }
  const n = (f) => results.filter((r) => f(r[1])).length;
  const bad = n((s) => !GOOD.has(s));
  const todo = n((s) => s === 'TODO');
  const head = title || '일일 숙제 결과';
  $('#dl-rp-title').textContent = bad - todo ? head + ' — 확인이 필요한 것 ' + (bad - todo) + '건'
    : todo ? head + ' — 남은 숙제 ' + todo + '개' : head + ' — 모두 완료';
  $('#dl-rp-sum').innerHTML = [
    ['완료', n((s) => s === 'OK' || s === 'DONE'), 'pill-ok'],
    ['남음', n((s) => s === 'CHECK' || s === 'MANUAL'), 'pill-warn'],
    ['실패', n((s) => !GOOD.has(s) && !['CHECK', 'MANUAL', 'TODO'].includes(s)), 'pill-bad'],
    ['아직 안 함', todo, 'pill-muted'],
  ].filter((x) => x[1]).map(([t, c, k]) => '<span class="pill ' + k + '">' + t + ' ' + c + '</span>').join('');
  $('#dl-rp-body').innerHTML = [...chars.entries()].map(([who, rows]) => {
    const issues = rows.filter((r) => !GOOD.has(r.st));
    const oks = rows.filter((r) => GOOD.has(r.st) && r.task && r.task !== '접속');
    const head = '<h4>' + esc(who) + (issues.length ? '' : ' <span class="muted st-OK">모두 완료</span>') + '</h4>';
    const list = issues.map((r) => {
      const shot = r.summary.match(SHOT_RE);
      const why = r.summary.replace(/\s*→\s*\S+\.png/g, '').trim() || (r.st === 'TODO' ? '' : '(원인 기록 없음)');
      return '<div class="dl-rp-row' + (shot ? ' has-shot' : '') + '"' + (shot ? ' data-shot="' + esc(shot[0]) + '"' : '') + '>' +
        '<span>' + esc(r.task || '전체') + '</span><span class="st-' + r.st + '">' + esc(ST_TEXT[r.st] || r.st) + '</span>' +
        '<span class="dl-rp-why">' + esc(why) + '</span></div>';
    }).join('');
    const okline = oks.length ? '<div class="dl-rp-okline">' + (oks.some((r) => r.task === '전체') ? '오늘 완료'
      : '완료: ' + oks.map((r) => esc(r.task)).join(' · ')) + '</div>' : '';
    return '<div class="dl-rp-char">' + head + list + okline + '</div>';
  }).join('') || '<p class="muted">실행한 숙제가 없습니다.</p>';
  $('#dl-rp-shot').classList.add('hidden');
  $('#dl-rp-scroll').scrollTop = 0;
  $('#dl-report').classList.remove('hidden');
}

/* ── 어비스 반복 ── */

async function loadAbyss() {
  const a = await mm.daily.abyssSettings();
  if (!a) return;
  $('#ab-dungeon').innerHTML = a.dungeons.map((d) => '<option' + (d === a.dungeon ? ' selected' : '') + '>' + esc(d) + '</option>').join('');
  $('#ab-difficulty').innerHTML =
    a.difficulties.map((d) => '<option' + (d === a.difficulty ? ' selected' : '') + '>' + esc(d) + '</option>').join('');
  $('#ab-char').innerHTML = '<option value="0">지금 접속한 캐릭터</option>' + a.chars.map((c) =>
    '<option value="' + c.slot + '"' + (c.slot === a.slot ? ' selected' : '') + '>' + c.slot + '. ' + esc(c.name) + '</option>').join('');
  $('#ab-runs').value = a.runs;
  $('#ab-minutes').value = a.minutes;
  $('#ab-revive').checked = a.revive !== false;
  $('#ab-fit').checked = !!a.fit_display;
  paintAbyssRunning(a.running);
}

function paintAbyssRunning(on) {
  $('#ab-start').classList.toggle('hidden', on);
  $('#ab-stop').classList.toggle('hidden', !on);
}

/* 어비스 반복도 작업 큐의 한 항목으로 돈다 (일일 숙제와 같은 방식). '반복 시작' = 큐 맨 앞에 넣고 돌리기,
 * '목표' = 제작·채집 목표와 같은 방식 — 판 수를 물어 큐 뒤에 담기만 한다 (재생을 눌러야 진행)
 * → 'A 캐릭터 3판 → B 캐릭터 3판' 처럼 미리 걸어 둘 수 있다. */
function abyssSpec() {
  const sel = $('#ab-char');
  const slot = Number(sel.value) || 0;
  const name = slot ? sel.options[sel.selectedIndex].textContent.replace(/^\d+\.\s*/, '') : '';
  return {
    kind: 'abyss', status: 'wait', note: '', label: '어비스 · ' + (name || '지금 캐릭터'),
    slot, dungeon: $('#ab-dungeon').value, difficulty: $('#ab-difficulty').value,
    runs: Number($('#ab-runs').value) || 0, minutes: Number($('#ab-minutes').value) || 0,
    revive: $('#ab-revive').checked, fit: $('#ab-fit').checked,
  };
}

function abyssAmount(x) {
  const lim = [x.runs ? x.runs + '판' + (x.doneRuns ? ' (' + x.doneRuns + '판 함)' : '') : '',
    x.minutes ? x.minutes + '분' : ''].filter(Boolean).join(' · ');
  return x.dungeon + ' ' + x.difficulty + ' · ' + (lim || '멈출 때까지') + (x.revive === false ? ' · 쓰러지면 나감' : '') +
    (x.fit ? ' · 화면 맞춤' : '');
}

function startAbyss() {
  if (qItems.some((x) => x.kind === 'abyss' && x.status === 'run')) { toast('이미 어비스 반복 중입니다', '', 'bad'); return; }
  const it = Object.assign({ id: qSeq++ }, abyssSpec());
  const cur = qItems.find((x) => x.status === 'run');
  toast('어비스 반복 시작', stopKey() + ' = 멈춤' + (cur ? ' · 진행 중이던 "' + cur.label + '" 은 뒤로 미룹니다' : ''), 'ok');
  qStartNow(it);
}

async function queueAbyss() {
  const spec = abyssSpec();
  const runs = await promptNumber('목표 판 수',
    '"' + spec.label + '" 로 ' + spec.dungeon + ' ' + spec.difficulty + ' 를 몇 판 돌까요?',
    spec.runs || 3,
    '작업 큐에 담기만 하고, 재생을 눌러야 실제로 진행합니다. 캐릭터·던전·난이도·분 제한·부활은 지금 고른 대로 담습니다.');
  if (!runs) return;
  const it = Object.assign({ id: qSeq++ }, spec, { runs });
  qItems.push(it);
  paintQueue();
  saveQueue();
  toast('큐에 담았습니다', it.label + ' — ' + abyssAmount(it) + ' · 재생을 누르면 진행합니다.', 'ok');
}

let abWaiter = null;

/** 큐가 부른다. 반복을 시작하고 끝날 때까지 기다린다. 정한 판·분을 채웠으면 true.
 * 멈췄다(F12·지금 바로 시작에 밀림) 다시 돌 때는 이미 돈 판·시간을 빼고 남은 만큼만 (it.doneRuns · it.doneSecs). */
async function runAbyssItem(it) {
  const runs = it.runs ? Math.max(1, it.runs - (it.doneRuns || 0)) : 0;
  const minutes = it.minutes ? Math.max(1, Math.ceil(it.minutes - (it.doneSecs || 0) / 60)) : 0;
  it.lastClears = 0;
  it.lastSecs = 0;
  const fit = !!it.fit;
  if (fit && !(await ensureDisplay(it))) return false;
  const r = await mm.daily.abyssStart({
    slot: it.slot, dungeon: it.dungeon, difficulty: it.difficulty, runs, minutes, revive: it.revive !== false,
    fit_display: fit, interface: fit && !qDisplay.iface,
  });
  if (fit && !(r && r.error)) qDisplay.iface = true;
  if (r && r.error) { qNote(it, '시작 못 함 — ' + r.error); return false; }
  paintAbyssRunning(true);
  $('#ab-msg').textContent = '시작';
  const e = await new Promise((res) => { abWaiter = res; });
  abWaiter = null;
  it.doneRuns = (it.doneRuns || 0) + (it.lastClears || 0);
  it.doneSecs = (it.doneSecs || 0) + (it.lastSecs || 0);
  if (e.type === 'failed') { qNote(it, '실패 — ' + (e.message || '')); return false; }
  if (e.stopped) {  // F12·멈추기: 카드를 일시정지로 두고 뒤 작업도 세운다 (▶ 로 다시)
    it.pauseAfter = true;
    qAbort = true;
    return false;
  }
  return true;
}

mm.daily.onAbyss((e) => {
  if (!e) return;
  const t = e.seconds != null ? ' · ' + Math.floor(e.seconds / 60) + '분' : '';
  const stat = e.clears != null ? '클리어 ' + e.clears + (e.revives ? ' · 부활 ' + e.revives : '') + ' · 사망으로 나감 ' + e.deaths + t : '';
  if (stat) $('#ab-stat').textContent = stat;
  const qi = qItems.find((x) => x.kind === 'abyss' && x.status === 'run');
  if (qi && e.clears != null) { qi.lastClears = e.clears; qi.lastSecs = e.seconds || 0; }
  if (e.type === 'abyss') {
    const msg = { match: '매칭 중', play: '진행 중', clear: '클리어' }[e.stage] || '';
    $('#ab-msg').textContent = msg;
    if (qi) qNote(qi, msg + (stat ? ' · ' + stat : ''));
  } else if (e.type === 'done') {
    paintAbyssRunning(false);
    $('#ab-msg').textContent = e.stopped ? '멈춤' : '끝';
  } else if (e.type === 'failed') {
    paintAbyssRunning(false);
    $('#ab-msg').textContent = '';
    toast('어비스 반복이 멈췄습니다', e.message, 'bad');
  }
  if ((e.type === 'done' || e.type === 'failed') && abWaiter) abWaiter(e);
});

/* ── 배선 ── */

LOADERS.daily = loadDaily;
LOADERS.abyss = loadAbyss;

$('#dl-start').addEventListener('click', () => {
  const card = dlPausedCard();
  if (card) { qStartNow(card); return; }  // 일시정지 중이면 이어 하기 — 지금 바로 (F12 와 같다)
  startDaily();
});
$('#dl-queue').addEventListener('click', queueDaily);
$('#dl-fit').addEventListener('change', () => mm.daily.saveSettings({ fit_display: $('#dl-fit').checked }));
$('#ab-start').addEventListener('click', startAbyss);
$('#ab-queue').addEventListener('click', queueAbyss);
$('#ab-stop').addEventListener('click', () => mm.daily.abyssStop());
$('#dl-report-btn').addEventListener('click', showTodayReport);
$('#dl-rp-close').addEventListener('click', () => $('#dl-report').classList.add('hidden'));
$('#dl-rp-logs').addEventListener('click', () => mm.daily.openFolder('logs'));
$('#dl-rp-body').addEventListener('click', async (e) => {
  const row = e.target.closest('[data-shot]');
  if (!row) return;
  const url = await mm.daily.shot(row.dataset.shot);
  const img = $('#dl-rp-shot');
  if (!url) { img.classList.add('hidden'); toast('화면을 찾지 못했습니다', row.dataset.shot, 'bad'); return; }
  img.src = url;
  img.classList.remove('hidden');
  img.scrollIntoView({ block: 'nearest' });
});
$('#dl-stop').addEventListener('click', () => { mm.daily.stop(false); say('일시정지 — 지금 동작이 끝나면 멈춥니다'); });
$('#dl-save').addEventListener('click', saveDailySettings);
$('#opt-paths-save').addEventListener('click', savePathSettings);
$('#dl-table').addEventListener('change', (e) => {
  const b = e.target;
  if (b.dataset.dlChar) {
    const s = Number(b.dataset.dlChar);
    b.checked ? dl.pickedChars.add(s) : dl.pickedChars.delete(s);
  } else if (b.dataset.dlTask) {
    b.checked ? dl.pickedTasks.add(b.dataset.dlTask) : dl.pickedTasks.delete(b.dataset.dlTask);
  } else if ('dlAll' in b.dataset) {
    dl.pickedChars = new Set(b.checked ? dl.st.chars.map((c) => c.slot) : []);
  } else return;
  paintDailyTable();
});
