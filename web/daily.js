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
  if (e.type === 'start') {
    paintDailyRunning(true);
  } else if (e.type === 'task_start') {
    setCell(e.slot, e.task, 'RUN', e.label);
    say('진행 중: ' + e.label);
  } else if (e.type === 'task_end') {
    setCell(e.slot, e.task, e.status, (e.summary || '') + ' (' + e.seconds + '초)');
  } else if (e.type === 'done') {
    paintDailyRunning(false);  // 결과 창은 작업 큐가 다 비었을 때 큐 전체 결과로 (queue.js showQueueReport)
  } else if (e.type === 'paused') {
    const p = $('#dl-state');
    p.textContent = '일시정지 · ' + stopKey() + '로 재개';
    p.className = 'pill pill-warn';
    say('일시정지 — ' + stopKey() + '를 누르면 이어 합니다');
  } else if (e.type === 'failed') {
    paintDailyRunning(false);
    toast('일일 숙제를 시작하지 못했습니다', e.message, 'bad');
  }
  // 일시정지 중 F12 → 이어 하기는 파이썬 작업 큐가 한다 (다른 작업이 돌고 있으면 그 F12 는 그 작업의 것)
});

// 로그는 남긴 쪽 탭에만 — 숙제는 일일 숙제 탭, 어비스는 어비스 탭, 공통(F12·화면 설정 되돌리기 등)은 둘 다 (m.ch)
mm.daily.onLog((m) => {
  if (!m) return;
  const tabs = m.ch === 'abyss' ? [$('#ab-log')] : m.ch === 'daily' ? [$('#dl-log')] : [$('#dl-log'), $('#ab-log')];
  for (const pre of tabs) {
    if (!pre) continue;
    const line = document.createElement('div');
    if (m.level === 'WARNING') line.className = 'w';
    if (m.level === 'ERROR') line.className = 'e';
    line.textContent = m.text;
    pre.appendChild(line);
    if (pre.childElementCount > 1500) pre.removeChild(pre.firstChild);
    pre.scrollTop = pre.scrollHeight;
  }
  if (m.ch !== 'abyss') $('#dl-log-n').textContent = ++dl.logN + '줄';
});

/* 화면 설정 맞추기·되돌리기는 작업 큐(파이썬)가 한다. 큐가 다 끝나 되돌렸으면 알린다 */
mm.daily.onDisplay((m) => {
  if (m && m.restored && m.message) toast(m.ok ? '화면 설정을 되돌렸습니다' : '화면 설정을 되돌리지 못했습니다', m.message, m.ok ? 'ok' : 'bad');
});

/* 일일 숙제는 작업 큐(app.js)의 한 항목으로 돈다. 두 가지로 넣는다 (어비스와 같다):
 *  '숙제 시작' = 지금 바로 — 맨 위에 넣고 바로 시작한다. 돌던 작업은 뒤로 밀렸다가 끝나면 이어서 (qStartNow)
 *  '목표'     = 큐 맨 아래에 담기만 한다 (재생을 눌러야 진행) — 제작·채집 목표와 같은 방식
 * 게임 캐릭터는 하나라 둘이 동시에 돌면 안 되는데, 큐가 하나씩만 돌리므로 막힌다. */
function dailySpec() {
  const chars = [...dl.pickedChars];
  const only = dl.st.order.filter((t) => dl.pickedTasks.has(t));
  if (!chars.length || !only.length) { toast('캐릭터와 숙제를 하나 이상 고르세요', '', 'bad'); return null; }
  return {
    kind: 'daily', label: '일일 숙제',
    chars: chars, only: only.length === dl.st.order.length ? null : only, force: $('#dl-force').checked,
  };
}

function startDaily() {
  if (qItems.some((x) => x.kind === 'daily' && x.status === 'run')) { toast('이미 실행 중입니다', '', 'bad'); return; }
  const it = dailySpec();
  if (!it) return;
  const cur = qItems.find((x) => x.status === 'run');
  toast('일일 숙제 시작', stopKey() + ' = 일시정지 · 다시 누르면 재개' +
    (cur ? ' · 진행 중이던 "' + cur.label + '" 은 뒤로 미룹니다' : ''), 'ok');
  qStartNow(it, true);  // 멈춰 둔 숙제 카드는 새 것으로 바꾼다
}

async function queueDaily() {
  const it = dailySpec();
  if (!it) return;
  await mm.queue.add(it, 'end');
  toast('큐에 담았습니다', '일일 숙제 — ' + it.chars.length + '명 · ' + (it.only ? '숙제 ' + it.only.length + '개' : '전체') +
    ' · 재생을 누르면 진행합니다.', 'ok');
}

function dailyAmount(x) {
  return (x.chars || []).length + '명 · ' + (x.only ? '숙제 ' + x.only.length + '개' : '전체') + (x.force ? ' · 다시' : '');
}

/* 작업 큐 카드 종류 (queue.js Q_KINDS) — 화면 쪽 표시만. 실행·멈춤·화면 설정은 파이썬 (gui_app/queue_api.py) */
Q_KINDS.daily = { amount: dailyAmount };

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
  $('#dl-sunday').innerHTML = opts(s.sundays, s.sunday);
  $('#dl-follow-sunday').textContent = fol(f.sunday);
  paintStopKey();
}

function collectDailySettings() {
  return {
    silver: { field_runs: Number($('#dl-field-runs').value), dungeon: $('#dl-dungeon').value, floor: Number($('#dl-floor').value) },
    field: $('#dl-field').value,
    sunday: $('#dl-sunday').value,
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
  const fkeys = (cur) => Array.from({ length: 12 }, (_, i) => 'f' + (i + 1)).map((k) =>
    '<option value="' + k + '"' + (k === cur ? ' selected' : '') + '>' + k.toUpperCase() + '</option>').join('');
  $('#opt-stop-key').innerHTML = fkeys(s.stop_key);
  $('#opt-dye-key').innerHTML = fkeys(s.dye_key);
  $('#opt-pause-touch').checked = s.pause_on_touch !== false;
  $('#opt-fit-display').checked = s.fit_display !== false;
  ['data', 'logs', 'shots'].forEach((k) => { $('#dl-p-' + k).value = s.paths[k] || ''; });
  $('#dl-p-now').textContent = '지금: ' + s.current.data + ' (바꾸면 다음 실행부터)';
}

async function savePathSettings() {
  const r = await mm.daily.saveSettings({
    stop_key: $('#opt-stop-key').value,
    dye_key: $('#opt-dye-key').value,
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

/* ── 숙제 결과 (작업 큐 결과 창의 일일 숙제 탭 — queue.js showQueueReport) ──
 * results: [[이름표, 상태, 요약]]. 이름표는 '[캐릭터] 숙제' 또는 '[캐릭터]'(캐릭터 전체 건너뜀).
 * 완료가 아닌 것은 원인(요약)을 목록으로 보이고, 요약에 화면 저장 파일이 있으면 눌러서 그 화면을 본다.
 * loots: 캐릭터마다 얻은 것 [{who, gained, used, cur}] — 그 캐릭터 칸에 같이 쓴다.
 * 돌려주는 것: { pills: 상태별 개수 HTML, body: 캐릭터별 HTML } */
function dailyReportHtml(results, loots) {
  const GOOD = new Set(['OK', 'DONE']);
  const chars = new Map();
  for (const [label, st, summary] of results || []) {
    const m = /^\[(.+?)\]\s*(.*)$/.exec(label || '');
    const who = m ? m[1] : (label || '실행');
    const task = m ? (m[2] || '전체') : '';
    if (!chars.has(who)) chars.set(who, []);
    chars.get(who).push({ task, st, summary: summary || '' });
  }
  const lootOf = new Map((loots || []).map((x) => [x.who, x]));
  for (const who of lootOf.keys()) if (!chars.has(who)) chars.set(who, []);
  const rows = (results || []).filter((r) => !/\]\s*접속$/.test(r[0] || ''));  // 접속은 세지 않는다
  const n = (f) => rows.filter((r) => f(r[1])).length;
  const pills = [
    ['완료', n((s) => s === 'OK' || s === 'DONE'), 'pill-ok'],
    ['남음', n((s) => s === 'CHECK' || s === 'MANUAL'), 'pill-warn'],
    ['중단', n((s) => s === 'STOP'), 'pill-muted'],  // 사람이 멈춘 것(F12·■)은 실패가 아니다 — 이어 하면 그 자리부터
    ['실패', n((s) => !GOOD.has(s) && !['CHECK', 'MANUAL', 'TODO', 'STOP'].includes(s)), 'pill-bad'],
  ].filter((x) => x[1]).map(([t, c, k]) => '<span class="pill ' + k + '">' + t + ' ' + c + '</span>').join('');
  const body = [...chars.entries()].map(([who, list]) => {
    const issues = list.filter((r) => !GOOD.has(r.st));
    const oks = list.filter((r) => GOOD.has(r.st) && r.task && r.task !== '접속');
    const head = '<h4>' + esc(who) + (list.length && !issues.length ? ' <span class="muted st-OK">모두 완료</span>' : '') + '</h4>';
    const lines = issues.map((r) => {
      const shot = r.summary.match(SHOT_RE);
      const why = r.summary.replace(/\s*→\s*\S+\.png/g, '').trim() || (r.st === 'TODO' ? '' : '(원인 기록 없음)');
      return '<div class="dl-rp-row' + (shot ? ' has-shot' : '') + '"' + (shot ? ' data-shot="' + esc(shot[0]) + '"' : '') + '>' +
        '<span>' + esc(r.task || '전체') + '</span><span class="st-' + r.st + '">' + esc(ST_TEXT[r.st] || r.st) + '</span>' +
        '<span class="dl-rp-why">' + esc(why) + '</span></div>';
    }).join('');
    const okline = oks.length ? '<div class="dl-rp-okline">' + (oks.some((r) => r.task === '전체') ? '오늘 완료'
      : '완료: ' + oks.map((r) => esc(r.task)).join(' · ')) + '</div>' : '';
    const lt = lootOf.get(who);
    return '<div class="dl-rp-char">' + head + lines + okline + (lt ? lootHtml(lt, true) : '') + '</div>';
  }).join('') || '<p class="muted">실행한 숙제가 없습니다.</p>';
  return { pills, body };
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
  paintAbyssRunning(a.running);
  loadRaid(a.chars);
}

/** 어비스·레이드 탭 공통: 시작/멈춤 버튼 (pre = '#ab' · '#rd') */
function paintRepeatRunning(pre, on) {
  $(pre + '-start').classList.toggle('hidden', on);
  $(pre + '-stop').classList.toggle('hidden', !on);
}

function paintAbyssRunning(on) { paintRepeatRunning('#ab', on); }

/* 어비스 반복도 작업 큐의 한 항목으로 돈다 (일일 숙제와 같은 방식). '반복 시작' = 큐 맨 앞에 넣고 돌리기,
 * '목표' = 탭에서 고른 그대로(판 수·분 제한 포함) 큐 뒤에 담기만 한다 (재생을 눌러야 진행)
 * → 'A 캐릭터 3판 → B 캐릭터 3판' 처럼 미리 걸어 둘 수 있다. */
/** 어비스·레이드 탭에서 고른 그대로 큐 카드 (pre = '#ab' · '#rd', place = 장소 칸 이름 — dungeon · raid) */
function repeatSpec(kind, pre, title, place) {
  const sel = $(pre + '-char');
  const slot = Number(sel.value) || 0;
  const name = slot ? sel.options[sel.selectedIndex].textContent.replace(/^\d+\.\s*/, '') : '';
  return {
    kind, label: title + ' · ' + (name || '지금 캐릭터'),
    slot, [place]: $(pre + '-' + place).value, difficulty: $(pre + '-difficulty').value,
    runs: Number($(pre + '-runs').value) || 0, minutes: Number($(pre + '-minutes').value) || 0,
    revive: $(pre + '-revive').checked,
  };
}

function startRepeat(it, title) {
  if (qItems.some((x) => x.kind === it.kind && x.status === 'run')) { toast('이미 ' + title + ' 반복 중입니다', '', 'bad'); return; }
  const cur = qItems.find((x) => x.status === 'run');
  toast(title + ' 반복 시작', stopKey() + ' = 멈춤' + (cur ? ' · 진행 중이던 "' + cur.label + '" 은 뒤로 미룹니다' : ''), 'ok');
  qStartNow(it);
}

async function queueRepeat(it, amount) {  // 탭에서 고른 그대로 (0판·0분 = 멈출 때까지)
  await mm.queue.add(it, 'end');
  toast('큐에 담았습니다', it.label + ' — ' + amount + ' · 재생을 누르면 진행합니다.', 'ok');
}

function abyssSpec() { return repeatSpec('abyss', '#ab', '어비스', 'dungeon'); }

function abyssAmount(x) {
  const lim = [x.runs ? x.runs + '판' + (x.doneRuns ? ' (' + x.doneRuns + '판 함)' : '') : '',
    x.minutes ? x.minutes + '분' : ''].filter(Boolean).join(' · ');
  return x.dungeon + ' ' + x.difficulty + ' · ' + (lim || '멈출 때까지') + (x.revive === false ? ' · 쓰러지면 나감' : '');
}


Q_KINDS.abyss = {
  amount: (x) => abyssAmount(x),
  doneToast: (x) => ['어비스 반복 끝', x.label + ' · ' + abyssAmount(x)],
};

/** 어비스·레이드 반복 진행 이벤트 (mm:abyss · mm:raid — 같은 틀 mabi/tasks/repeat.Repeat) → 탭의 진행 줄·버튼 */
const REPEAT_STAGES = { entry: '입장', match: '매칭 중', sail: '출항', play: '진행 중', clear: '클리어', repair: '장비 수리' };

function onRepeatEvent(kind, pre, title) {
  return (e) => {
    if (!e) return;
    const t = e.seconds != null ? ' · ' + Math.floor(e.seconds / 60) + '분' : '';
    const stat = e.clears != null ? '클리어 ' + e.clears + (e.revives ? ' · 부활 ' + e.revives : '') + ' · 쓰러져 나감 ' + e.deaths + t : '';
    if (stat) $(pre + '-stat').textContent = stat;
    if (e.type === 'start') {
      paintRepeatRunning(pre, true);
      $(pre + '-msg').textContent = '시작';
    } else if (e.type === kind) {
      $(pre + '-msg').textContent = REPEAT_STAGES[e.stage] || '';
    } else if (e.type === 'done') {
      paintRepeatRunning(pre, false);
      $(pre + '-msg').textContent = e.stopped ? '멈춤' : '끝';
      if (e.message) toast(title + ' 반복을 멈췄습니다', e.message, 'bad');  // 게임 꺼짐·연속 실행 제한 등
    } else if (e.type === 'failed') {
      paintRepeatRunning(pre, false);
      $(pre + '-msg').textContent = '';
      toast(title + ' 반복이 멈췄습니다', e.message, 'bad');
    }
  };
}

mm.daily.onAbyss(onRepeatEvent('abyss', '#ab', '어비스'));

/* ── 레이드 반복 (혼자하기) — 어비스와 같은 틀 ── */

let raidDiffs = {};

async function loadRaid(chars) {
  const r = await mm.daily.raidSettings();
  if (!r) return;
  raidDiffs = r.difficulties;
  $('#rd-raid').innerHTML = r.raids.map((d) => '<option' + (d === r.raid ? ' selected' : '') + '>' + esc(d) + '</option>').join('');
  paintRaidDiffs(r.difficulty);
  $('#rd-char').innerHTML = '<option value="0">지금 접속한 캐릭터</option>' + chars.map((c) =>
    '<option value="' + c.slot + '"' + (c.slot === r.slot ? ' selected' : '') + '>' + c.slot + '. ' + esc(c.name) + '</option>').join('');
  $('#rd-runs').value = r.runs;
  $('#rd-minutes').value = r.minutes;
  $('#rd-revive').checked = r.revive !== false;
  paintRaidRunning(r.running);
}

function paintRaidDiffs(want) {
  const list = raidDiffs[$('#rd-raid').value] || [];
  $('#rd-difficulty').innerHTML = list.map((d) => '<option' + (d === want ? ' selected' : '') + '>' + esc(d) + '</option>').join('');
}

function paintRaidRunning(on) { paintRepeatRunning('#rd', on); }

function raidSpec() { return repeatSpec('raid', '#rd', '레이드', 'raid'); }

function raidAmount(x) {
  return abyssAmount({ ...x, dungeon: x.raid });
}

Q_KINDS.raid = {
  amount: (x) => raidAmount(x),
  doneToast: (x) => ['레이드 반복 끝', x.label + ' · ' + raidAmount(x)],
};

mm.daily.onRaid(onRepeatEvent('raid', '#rd', '레이드'));

/* ── 배선 ── */

LOADERS.daily = loadDaily;
LOADERS.abyss = loadAbyss;

$('#dl-start').addEventListener('click', () => {
  const card = dlPausedCard();
  if (card) { qPlayOne(card.id); return; }  // 일시정지 중이면 이어 하기 (F12 와 같다)
  startDaily();
});
$('#dl-queue').addEventListener('click', queueDaily);
$('#opt-fit-display').addEventListener('change', () => mm.daily.saveSettings({ fit_display: $('#opt-fit-display').checked }));
$('#ab-start').addEventListener('click', () => startRepeat(abyssSpec(), '어비스'));
$('#ab-queue').addEventListener('click', () => { const it = abyssSpec(); queueRepeat(it, abyssAmount(it)); });
$('#ab-stop').addEventListener('click', () => mm.daily.abyssStop());
$('#rd-raid').addEventListener('change', () => paintRaidDiffs($('#rd-difficulty').value));
$('#rd-start').addEventListener('click', () => startRepeat(raidSpec(), '레이드'));
$('#rd-queue').addEventListener('click', () => { const it = raidSpec(); queueRepeat(it, raidAmount(it)); });
$('#rd-stop').addEventListener('click', () => mm.daily.raidStop());
$('#qr-close').addEventListener('click', () => $('#q-report').classList.add('hidden'));
$('#qr-logs').addEventListener('click', () => mm.daily.openFolder('logs'));
$('#qr-body').addEventListener('click', async (e) => {
  const row = e.target.closest('[data-shot]');
  if (!row) return;
  const url = await mm.daily.shot(row.dataset.shot);
  const img = $('#qr-shot');
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
