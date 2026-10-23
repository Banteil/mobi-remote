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
    // 일시정지(F12)로 멈춘 것이면 보고서는 끝까지 간 뒤에. '결과 보기' 와 같은 오늘 하루 전체 결과로 띄운다
    // (이번 실행분만 보이면 끊어 돌린 날 앞 실행 결과가 빠진다)
    if (!(e.results || []).some((x) => x[1] === 'STOP')) showTodayReport(true);
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
  // 고른 숙제가 오늘 다 끝났으면 화면 설정은 보지 않는다 (ok) — 숙제는 '오늘 완료' 만 알린다
  const d = await mm.daily.displayCheck({ chars, only, force: $('#dl-force').checked });
  if (d && d.ok) { paintDisplayState(''); await runDaily(chars, only); return; }
  // 기준과 다르면 묻지 않고 자동으로 맞춘 뒤 이어서 시작한다 (끝나면 원래대로 되돌린다)
  say('화면 설정 맞추는 중: ' + ((d && d.problems) || ['확인 실패']).join(', '));
  dl.pendingStart = { chars, only };
  paintDisplayState('화면 설정 맞추는 중');
  const r = await mm.daily.displayFix();
  if (r && r.error) { dl.pendingStart = null; paintDisplayState(''); toast('맞추지 못했습니다', r.error, 'bad'); }
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
  paintAbyssRunning(a.running);
}

function paintAbyssRunning(on) {
  $('#ab-start').classList.toggle('hidden', on);
  $('#ab-stop').classList.toggle('hidden', !on);
}

async function startAbyss() {
  const r = await mm.daily.abyssStart({
    slot: Number($('#ab-char').value) || 0, dungeon: $('#ab-dungeon').value, difficulty: $('#ab-difficulty').value,
    runs: Number($('#ab-runs').value) || 0, minutes: Number($('#ab-minutes').value) || 0,
  });
  if (r && r.error) { toast('시작하지 못했습니다', r.error, 'bad'); return; }
  paintAbyssRunning(true);
  $('#ab-msg').textContent = '시작';
  toast('어비스 반복 시작', stopKey() + ' = 멈춤', 'ok');
}

mm.daily.onAbyss((e) => {
  if (!e) return;
  const t = e.seconds != null ? ' · ' + Math.floor(e.seconds / 60) + '분' : '';
  if (e.clears != null) $('#ab-stat').textContent = '클리어 ' + e.clears + ' · 사망 ' + e.deaths + t;
  if (e.type === 'abyss') {
    $('#ab-msg').textContent = { match: '매칭 중', play: '진행 중', clear: '클리어' }[e.stage] || '';
  } else if (e.type === 'done') {
    paintAbyssRunning(false);
    $('#ab-msg').textContent = e.stopped ? '멈춤' : '끝';
  } else if (e.type === 'failed') {
    paintAbyssRunning(false);
    $('#ab-msg').textContent = '';
    toast('어비스 반복이 멈췄습니다', e.message, 'bad');
  }
});

/* ── 배선 ── */

LOADERS.daily = loadDaily;
LOADERS.abyss = loadAbyss;

$('#dl-start').addEventListener('click', startDaily);
$('#ab-start').addEventListener('click', startAbyss);
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
