'use strict';
/**
 * 일일 숙제 · 숙제 기록 탭 (파이썬판에서 새로 생긴 화면). app.js 의 $, esc, num, toast, say, LOADERS 를 같이 쓴다.
 *
 * 숙제는 파이썬(mabi/runner)이 돌리고, 진행 이벤트를 mm.daily.onEvent 로 받는다:
 *   start · character · task_start · task_end{status, summary, seconds} · done · failed
 */
const ST_TEXT = {
  OK: '완료', DONE: '이미 완료', TODO: '아직 안 함', CHECK: '남음', MANUAL: '남음(직접)', FAIL: '실패', ERROR: '오류', HEAVY: '가방 무게',
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
}

function stateOf(v) {
  if (!v) return null;
  return v === 'done' ? 'DONE' : String(v).split(':')[0].trim().toUpperCase();
}

function paintDailyTable() {
  const st = dl.st;
  const cols = ['login', ...st.order];
  $('#dl-table thead').innerHTML = '<tr><th>캐릭터</th>' + cols.map((t) =>
    '<th class="dl-cell' + (t === 'login' || dl.pickedTasks.has(t) ? '' : ' off') + '" data-dl-task="' + esc(t) + '">' +
    esc(st.labels[t] || t) + '</th>').join('') + '</tr>';
  $('#dl-table tbody').innerHTML = st.chars.map((c) => {
    const today = st.today[String(c.slot)] || {};
    const on = dl.pickedChars.has(c.slot);
    return '<tr><td class="dl-cell dl-name' + (on ? '' : ' off') + '" data-dl-char="' + c.slot + '">' +
      c.slot + '. ' + esc(c.name) + '</td>' + cols.map((t) => {
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

function paintDailyRunning(on) {
  $('#dl-start').classList.toggle('hidden', on);
  $('#dl-stop').classList.toggle('hidden', !on);
  const p = $('#dl-state');
  p.textContent = on ? '실행 중' : '대기';
  p.className = 'pill ' + (on ? 'pill-ok' : 'pill-muted');
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
    // 일시정지(F12)로 멈춘 것이면 보고서는 끝까지 간 뒤에
    if (!(e.results || []).some((x) => x[1] === 'STOP')) showReport(e.results || []);
  } else if (e.type === 'paused') {
    const p = $('#dl-state');
    p.textContent = '일시정지 · ' + stopKey() + '로 재개';
    p.className = 'pill pill-warn';
    say('일시정지 — ' + stopKey() + '를 누르면 이어 합니다');
  } else if (e.type === 'resume') {
    // 일시정지 중 F12 → 큐의 숙제 카드를 다시 돌린다 (카드를 지웠으면 = 종료, 아무것도 안 함)
    const card = qItems.find((x) => x.kind === 'daily');
    if (card) qPlayOne(card.id);
  } else if (e.type === 'failed') {
    paintDailyRunning(false);
    toast('일일 숙제를 시작하지 못했습니다', e.message, 'bad');
  }
  if ((e.type === 'done' || e.type === 'failed') && dlWaiter) dlWaiter(e);
});

mm.daily.onLog((m) => {
  const pre = $('#dl-log');
  if (!pre || !m) return;
  const line = document.createElement('div');
  if (m.level === 'WARNING') line.className = 'w';
  if (m.level === 'ERROR') line.className = 'e';
  line.textContent = m.text;
  pre.appendChild(line);
  if (pre.childElementCount > 1500) pre.removeChild(pre.firstChild);
  pre.scrollTop = pre.scrollHeight;
  $('#dl-log-n').textContent = ++dl.logN + '줄';
});

/* 숙제 시작 전 게임 화면 설정 확인. 기준과 다르면 직접 맞출지 자동으로 맞출지 묻는다.
 * 자동: 맞추고 그대로 이어서 시작. 직접: 맞춘 뒤 F12 나 '숙제 시작' 을 누르면 다시 확인하고 시작. */
function paintDisplayState(text) {
  const p = $('#dl-state');
  p.textContent = text || '대기';
  p.className = 'pill ' + (text ? 'pill-warn' : 'pill-muted');
}

async function startDaily() {
  const chars = [...dl.pickedChars];
  const only = dl.st.order.filter((t) => dl.pickedTasks.has(t));
  if (!chars.length || !only.length) { toast('캐릭터와 숙제를 하나 이상 고르세요', '', 'bad'); return; }
  mm.daily.displayWaitCancel();
  paintDisplayState('화면 설정 확인 중');
  const d = await mm.daily.displayCheck();
  if (d && d.ok) { paintDisplayState(''); await runDaily(chars, only); return; }
  const problems = (d && d.problems) || ['확인 실패'];
  const auto = await confirmModal('게임 화면 설정이 기준과 다릅니다',
    '<p>기준: <b>' + esc((d && d.target) || '') + '</b></p>' +
    '<p>지금: ' + problems.map(esc).join(', ') + '</p>' +
    '<p class="hint">직접 맞춘 뒤 <b>' + stopKey() + '</b> 또는 <b>숙제 시작</b>을 누르세요.</p>',
    '자동으로 맞춰 주세요', '직접 맞출게요');
  if (auto) {
    dl.pendingStart = { chars, only };
    paintDisplayState('화면 설정 맞추는 중');
    const r = await mm.daily.displayFix();
    if (r && r.error) { dl.pendingStart = null; paintDisplayState(''); toast('맞추지 못했습니다', r.error, 'bad'); }
  } else {
    await mm.daily.displayWait();
    paintDisplayState('직접 맞춘 뒤 ' + stopKey() + ' 또는 숙제 시작');
    say('화면 설정을 맞춘 뒤 ' + stopKey() + ' 나 숙제 시작을 누르세요');
  }
}

mm.daily.onDisplay((m) => {
  if (!m) return;
  if (m.resume) { startDaily(); return; }  // 직접 맞춘 뒤 F12
  if (!m.done) return;
  const p = dl.pendingStart;
  dl.pendingStart = null;
  paintDisplayState('');
  if (!m.ok) { toast('화면 설정을 맞추지 못했습니다', m.message, 'bad'); return; }
  if (!m.running) { toast('화면 설정을 파일로 맞췄습니다', m.message, 'ok'); return; }
  toast('화면 설정을 맞췄습니다', m.message, 'ok');
  if (p) runDaily(p.chars, p.only);  // 자동이면 그대로 이어서 시작
});

/* 일일 숙제는 작업 큐(app.js)의 한 항목으로 돈다. 숙제 시작 = 큐 맨 앞에 넣고 큐를 돌린다 → 끝나면 뒤에 담아 둔
 * 채집·가공 목표가 이어서 진행된다. 게임 캐릭터는 하나라 둘이 동시에 돌면 안 되는데, 큐가 하나씩만 돌리므로 막힌다. */
function runDaily(chars, only) {
  if (qItems.some((x) => x.kind === 'daily' && x.status === 'run')) { toast('이미 실행 중입니다', '', 'bad'); return; }
  qItems = qItems.filter((x) => x.kind !== 'daily');  // 전에 멈춰 둔 숙제 카드는 새 것으로 바꾼다
  const it = {
    id: qSeq++, kind: 'daily', status: 'wait', note: '', label: '일일 숙제',
    chars: chars, only: only.length === dl.st.order.length ? null : only, force: $('#dl-force').checked,
  };
  qItems.unshift(it);
  const after = qItems.filter((x) => x !== it && x.status === 'wait').length;
  toast('일일 숙제 시작', stopKey() + ' = 일시정지 · 다시 누르면 재개' +
    (qRunning ? ' · 하던 작업 다음에 시작' : after ? ' · 끝나면 큐 ' + after + '건 이어서' : ''), 'ok');
  qPlayOne(it.id);
}

let dlWaiter = null;

/** 큐가 부른다. 숙제를 시작하고 끝날 때까지 기다린다. 끝까지 돌았으면 true (실패한 숙제가 있어도 — 결과는 보고서로 본다). */
async function runDailyItem(it) {
  const r = await mm.daily.start({ chars: it.chars, only: it.only, force: it.force });
  if (r && r.error) { qNote(it, '시작 못 함 — ' + r.error); return false; }
  paintDailyRunning(true);
  const e = await new Promise((res) => { dlWaiter = res; });
  dlWaiter = null;
  if (e.type === 'failed') { qNote(it, '실패 — ' + (e.message || '')); return false; }
  const res = e.results || [];
  if (res.some((x) => x[1] === 'STOP')) {  // 일시정지(F12·버튼): 카드를 보류로 두고 뒤 작업도 세운다. F12 로 이어 함
    it.pauseAfter = true;
    qAbort = true;
    return false;
  }
  return true;
}

/** 큐의 ⏸·■ → 숙제 일시정지 (F12 나 ▶ 로 이어 함). */
function qPauseDaily() {
  if (qItems.some((x) => x.kind === 'daily' && x.status === 'run')) mm.daily.stop(false);
}

/** 큐에서 숙제 카드를 빼거나 큐를 비우면 숙제는 종료 (F12 로 이어 하지 않음). */
function qStopDaily() {
  if (qItems.some((x) => x.kind === 'daily' && x.status === 'run')) mm.daily.stop(true);
  else mm.daily.pauseCancel();
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
  $('#dl-floor').value = String(s.silver.floor);
  $('#dl-weight').value = s.weight;
  paintStopKey();
}

function collectDailySettings() {
  return {
    silver: { field_runs: Number($('#dl-field-runs').value), dungeon: $('#dl-dungeon').value, floor: Number($('#dl-floor').value) },
    field: $('#dl-field').value,
    weight: Number($('#dl-weight').value),
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
  ['data', 'logs', 'shots'].forEach((k) => { $('#dl-p-' + k).value = s.paths[k] || ''; });
  $('#dl-p-now').textContent = '지금: ' + s.current.data + ' (바꾸면 다음 실행부터)';
}

async function savePathSettings() {
  const r = await mm.daily.saveSettings({
    stop_key: $('#opt-stop-key').value,
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

/* ── 기록 ── */

const hs = { runs: [], cur: null };

async function loadHistory() {
  hs.runs = await mm.daily.runs();
  $('#hs-runs').innerHTML = hs.runs.map((r, i) =>
    '<div class="hs-run" data-hs="' + i + '"><b>' + esc(r.started.slice(5, 16).replace('T', ' ')) + '</b> ' +
    esc(r.names.join(', ')) + '<br><span class="' + (r.ok < r.total ? 'bad' : 'muted') + '">' +
    r.ok + '/' + r.total + ' 성공' + (r.finished ? '' : ' · 중단됨') + '</span></div>').join('') ||
    '<p class="muted">기록이 없습니다.</p>';
  if (hs.runs.length) showRun(0);
}

const SHOT_RE = /\d{8}_\d{6}_[\w-]+\.png/;

async function showRun(i) {
  document.querySelectorAll('.hs-run').forEach((el) => el.classList.toggle('active', Number(el.dataset.hs) === i));
  const r = await mm.daily.run(hs.runs[i].file);
  $('#hs-shot').classList.add('hidden');
  if (!r) { $('#hs-detail').innerHTML = '<p class="muted">읽지 못했습니다.</p>'; return; }
  const env = r.env || {};
  $('#hs-env').textContent = 'v' + r.version + ' · 창 ' + (env.client_size || '?') + ' · 관리자 ' + env.admin + ' · CLI ' + env.cli;
  const labels = (dl.st && dl.st.labels) || {};
  $('#hs-detail').innerHTML = r.characters.map((c) =>
    '<h4>' + (c.slot || '-') + '. ' + esc(c.name || '현재 캐릭터') + '</h4>' + c.tasks.map((t) => {
      const st = t.status || 'STOP';
      const b = t.before || {}, a = t.after || {};
      const delta = ['silver', 'tribute'].filter((k) => b[k] != null && b[k] !== a[k])
        .map((k) => (k === 'silver' ? '은동전 ' : '공물 ') + b[k] + '→' + a[k]).join(' · ');
      const shot = (t.summary || '').match(SHOT_RE);
      return '<div class="hs-task' + (shot ? ' has-shot' : '') + '"' + (shot ? ' data-shot="' + esc(shot[0]) + '"' : '') + '>' +
        '<span>' + esc(labels[t.id] || t.id) + '</span><span class="st-' + st + '">' + esc(ST_TEXT[st] || st) + '</span>' +
        '<span class="muted">' + (t.seconds || 0) + 's</span><span>' + esc(t.summary || '') +
        (delta ? ' <span class="muted">(' + esc(delta) + ')</span>' : '') + '</span></div>' +
        (t.events || []).map((e) => {
          const s2 = (e.message || '').match(SHOT_RE);
          return '<div class="hs-ev' + (s2 ? ' has-shot' : '') + '"' + (s2 ? ' data-shot="' + esc(s2[0]) + '"' : '') + '>' +
            esc(e.time + ' ' + e.message) + '</div>';
        }).join('');
    }).join('')).join('');
}

/* ── 결과 보고 (숙제가 끝나면 팝업) ──
 * results: [[이름표, 상태, 요약]]. 이름표는 '[캐릭터] 숙제' 또는 '[캐릭터]'(캐릭터 전체 건너뜀).
 * 완료가 아닌 것은 원인(요약)을 목록으로 보이고, 요약에 화면 저장 파일이 있으면 눌러서 그 화면을 본다. */
/** '결과 보기': 오늘 기록(state/<날짜>.json)으로 지금까지의 결과를 같은 보고서로 (실행 중이어도 된다) */
async function showTodayReport() {
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
  showReport(results, '오늘 결과 (' + st.date + (st.running ? ', 실행 중' : '') + ')');
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
    ['완료', n((s) => s === 'OK'), 'pill-ok'], ['이미 완료', n((s) => s === 'DONE'), 'pill-muted'],
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
    const okline = oks.length ? '<div class="dl-rp-okline">' + (oks.some((r) => r.task === '전체') ? '오늘 이미 완료'
      : '완료: ' + oks.map((r) => esc(r.task)).join(' · ')) + '</div>' : '';
    return '<div class="dl-rp-char">' + head + list + okline + '</div>';
  }).join('') || '<p class="muted">실행한 숙제가 없습니다.</p>';
  $('#dl-rp-shot').classList.add('hidden');
  $('#dl-rp-scroll').scrollTop = 0;
  $('#dl-report').classList.remove('hidden');
}

async function showShot(name) {
  const url = await mm.daily.shot(name);
  const img = $('#hs-shot');
  if (!url) { img.classList.add('hidden'); return; }
  img.src = url;
  img.classList.remove('hidden');
}

/* ── 배선 ── */

LOADERS.daily = loadDaily;
LOADERS.history = async () => { if (!dl.st) dl.st = await mm.daily.state(); await loadHistory(); };

$('#dl-start').addEventListener('click', startDaily);
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
$('#dl-table').addEventListener('click', (e) => {
  const ch = e.target.closest('[data-dl-char]');
  const tk = e.target.closest('[data-dl-task]');
  if (ch) {
    const s = Number(ch.dataset.dlChar);
    dl.pickedChars.has(s) ? dl.pickedChars.delete(s) : dl.pickedChars.add(s);
  } else if (tk && tk.dataset.dlTask !== 'login') {
    const t = tk.dataset.dlTask;
    dl.pickedTasks.has(t) ? dl.pickedTasks.delete(t) : dl.pickedTasks.add(t);
  } else return;
  paintDailyTable();
});
$('#hs-runs').addEventListener('click', (e) => {
  const r = e.target.closest('[data-hs]');
  if (r) showRun(Number(r.dataset.hs));
});
$('#hs-detail').addEventListener('click', (e) => {
  const s = e.target.closest('[data-shot]');
  if (s) showShot(s.dataset.shot);
});
$('#hs-open').addEventListener('click', () => mm.daily.openFolder('logs'));
$('#hs-export').addEventListener('click', async () => {
  const r = await mm.daily.export($('#hs-anon').checked);
  if (r && r.error) toast('내보내지 못했습니다', r.error, 'bad');
  else toast('진단 파일을 만들었습니다', r && r.file, 'ok');
});
