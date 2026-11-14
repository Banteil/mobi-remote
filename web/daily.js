'use strict';
/**
 * 일일 숙제 · 숙제 기록 탭 (파이썬판에서 새로 생긴 화면). app.js 의 $, esc, num, toast, say 와 wire.js 의 LOADERS 를 같이 쓴다.
 *
 * 숙제는 파이썬(mabi/runner)이 돌리고, 진행 이벤트를 mm.daily.onEvent 로 받는다:
 *   start · character · task_start · task_end{status, summary, seconds} · done · failed
 */
const ST_TEXT = {
  OK: '완료', DONE: '완료', TODO: '아직 안 함', CHECK: '남음', MANUAL: '넘김(조건)', FAIL: '실패', ERROR: '오류', HEAVY: '가방 무게',
  SKIP: '건너뜀', STOP: '중단', RUN: '진행 중',
};
const INHERIT = 'inherit';
const dl = { st: null, settings: null, fb: null, wk: null, pickedChars: null, pickedTasks: null, logN: 0 };

/* ── 오늘 진행 표 ── */

async function loadDaily() {
  // 함께 묻는다 (필드 보스 목록은 바뀌지 않으므로 처음 한 번만. 주말 어비스·레이드는 이번 주 목록·오늘이 주말인지가 바뀌어 매번)
  [dl.st, dl.settings, dl.fb, dl.wk] = await Promise.all([mm.daily.state(), mm.daily.settings(),
    dl.fb || mm.daily.fieldBossSettings(), mm.daily.weekendSettings()]);
  if (!dl.pickedChars) dl.pickedChars = new Set(dl.st.chars.map((c) => c.slot));
  if (!dl.pickedTasks) dl.pickedTasks = new Set(dl.st.order);
  $('#dl-date').textContent = '게임 날짜 ' + dl.st.date + ' (오전 6시에 바뀜)';
  paintDailyTable();
  paintDrillChars();
  paintFieldBoss();
  paintPick('vg', 'vgChars');
  paintWeekend();
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
    return '<tr class="' + (on ? '' : 'off') + '"><td class="dl-name">' + charCheck(c, on, 'data-dl-char', 'dl-pick') + '</td>' + cols.map((t) => {
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

/* 버튼 세 상태: 쉬는 중(시작) · 실행 중(일시정지) · 일시정지(이어 하기). 그만두려면 작업 큐에서 카드를 뺀다.
 * 일시정지는 큐의 숙제 카드가 일시정지(pause)인 것으로 안다 — 큐 그림이 바뀔 때마다 다시 칠한다 (queue.js paintQueue → qOnPaint) */
function dlPausedCard() {
  return qItems.find((x) => x.kind === 'daily' && x.status === 'pause');
}

function paintDailyRunning(on) {
  dl.running = on;
  const paused = !on && !!dlPausedCard();
  $('#dl-start').textContent = paused ? '이어 하기 (' + stopKey() + ')' : '시작';
  $('#dl-start').classList.toggle('hidden', on);
  $('#dl-stop').classList.toggle('hidden', !on);
  const p = $('#dl-state');
  p.textContent = on ? '실행 중' : '일시정지';
  p.className = 'pill ' + (on ? 'pill-ok' : 'pill-warn');
  p.classList.toggle('hidden', !on && !paused);
}

qOnPaint(() => paintDailyRunning(!!dl.running));

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

/* 일일 숙제는 작업 큐(queue.js)의 한 항목으로 돈다. 두 가지로 넣는다 (어비스와 같다):
 *  '시작' = 지금 바로 — 맨 위에 넣고 바로 시작한다. 돌던 작업은 뒤로 밀렸다가 끝나면 이어서 (queue.js qStart)
 *  '목표'     = 큐 맨 아래에 담기만 한다 (재생을 눌러야 진행) — 제작·채집 목표와 같은 방식 (qEnqueue)
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

/* 기타 숙제 — 나이트메어 드릴. 일일 숙제와 같은 큐 카드(kind 'daily')에 only=['drill'] 로 담는다.
 * 깬 구역은 저장하지 않고 들어갈 때마다 패킷·드릴 창으로 확인하므로 늘 force (오늘 한 번 했어도 다시 확인) */
/* 캐릭터 고르기 칸 (기타·주간 숙제 카드가 같이 씀) — pre: 요소 id 앞말 ('dr' · 'fb'), key: dl 안의 고른 슬롯 Set 이름 */
function paintPick(pre, key) {
  const chars = (dl.st && dl.st.chars) || [];
  // 캐릭터 탭에서 뺀 캐릭터는 고른 목록에서도 지운다 (숙제 탭을 열 때마다 캐릭터 목록을 새로 받아 다시 그린다)
  dl[key] = new Set([...(dl[key] || [])].filter((s) => chars.some((c) => c.slot === s)));
  const allOn = chars.length > 0 && chars.every((c) => dl[key].has(c.slot));
  $('#' + pre + '-all').checked = allOn;
  $('#' + pre + '-all').disabled = !chars.length;
  $('#' + pre + '-chars').innerHTML = chars.length
    ? chars.map((c) => charCheck(c, dl[key].has(c.slot), 'data-pick-char')).join('')
    : '<span class="muted">캐릭터 탭에서 캐릭터를 추가하세요</span>';
  $('#' + pre + '-pick-note').textContent = dl[key].size + '명';
}

function bindPick(pre, key) {
  $('#' + pre + '-chars').addEventListener('change', (e) => {
    const s = Number(e.target.dataset.pickChar);
    if (!s) return;
    e.target.checked ? dl[key].add(s) : dl[key].delete(s);
    paintPick(pre, key);
  });
  $('#' + pre + '-all').addEventListener('change', (e) => {
    dl[key] = new Set(e.target.checked ? dl.st.chars.map((c) => c.slot) : []);
    paintPick(pre, key);
  });
}

function pickedSlots(key) {
  const chars = (dl.st.chars || []).map((c) => c.slot).filter((s) => dl[key].has(s));
  if (!chars.length) toast('캐릭터를 하나 이상 고르세요', '', 'bad');
  return chars;
}

/* 숙제 카드(kind 'daily')를 지금 바로 — 진행 중이던 것은 뒤로. replacePaused: 멈춰 둔 숙제 카드를 새 것으로 바꾼다 (일일 숙제 '시작') */
function startHomework(it, replacePaused) {
  qStart(it, { title: it.label + ' 시작', hint: stopKey() + ' = 일시정지 · 다시 누르면 재개', busy: '이미 숙제가 실행 중입니다', replacePaused });
}

/** 탭의 '시작'·'목표' 버튼 짝 (pre: 요소 id 앞말). spec() 이 null 이면(고른 게 없음) 아무것도 안 한다.
 * first: '시작' 을 먼저 가로채는 일 (true 를 돌려주면 그것으로 끝 — 일일 숙제의 이어 하기) */
function bindStartQueue(pre, spec, start, first) {
  $('#' + pre + '-start').addEventListener('click', () => {
    if (first && first()) return;
    const it = spec();
    if (it) start(it);
  });
  $('#' + pre + '-queue').addEventListener('click', () => { const it = spec(); if (it) qEnqueue(it); });
}

function paintDrillChars() { paintPick('dr', 'drillChars'); }

function drillSpec() {
  const chars = pickedSlots('drillChars');
  return chars.length ? { kind: 'daily', label: '나이트메어 드릴', chars: chars, only: ['drill'], force: true } : null;
}

/* 기타 숙제 — 각인 강화 반복. 열어 둔 창에서 바로 하는 일이라 큐 맨 아래에 담지 않고, 다른 작업이 돌면 시작하지 않는다
 * (그 작업을 밀어내면 게임 화면이 바뀐다). 실행은 파이썬 (gui_app/queue_api.py EnhanceKind) */
function startEnhance() {
  const cur = qItems.find((x) => x.status === 'run');
  if (cur) { toast('다른 작업이 도는 중입니다', '"' + cur.label + '" 이 끝난 뒤 각인 강화 창을 열고 시작하세요', 'bad'); return; }
  toast('각인 강화 반복 시작', '성공할 때까지 Space · ' + stopKey() + ' = 일시정지', 'ok');
  qStartNow({ kind: 'enhance', label: '각인 강화 반복' }, false);
}

qRegisterKind('enhance', { amount: () => '성공할 때까지' });

/* 주간 숙제 — 뱅가드 브리치. 이번 주에 했는지는 들어가기 전에 게임(성장 가이드)으로 보므로 늘 force */
function vanguardSpec() {
  const chars = pickedSlots('vgChars');
  return chars.length ? { kind: 'daily', label: '뱅가드 브리치', chars: chars, only: ['vanguard'], force: true } : null;
}

/* 주간 숙제 — 필드 보스. 일일 숙제 카드(kind 'daily')에 only=['field_boss'] 로, 고른 보스·난이도는 카드의 fieldBoss.
 * 이번 주에 잡았는지는 들어가기 전에 게임(성장 가이드)으로 보므로 늘 force. 열린 시간(12·18·20·22시부터 30분)이
 * 아니면 큐에서 비켜 있다가 열리면 돈다 (gui_app DailyKind.ready).
 * 보스·난이도 목록과 기본값은 파이썬이 준다 (mm.daily.fieldBossSettings ← mabi/tasks/field_boss.choices) */
function paintFieldBoss() {
  paintPick('fb', 'fbChars');
  const boss = $('#fb-boss');
  if (!boss.options.length && dl.fb) {
    const saved = pref('fieldBoss', {});
    boss.innerHTML = selectOptions(dl.fb.bosses, dl.fb.bosses.includes(saved.boss) ? saved.boss : dl.fb.boss);
    paintFieldBossLevels(saved.difficulty || dl.fb.difficulty);
  }
}

/** 난이도 칸 (필드 보스·레이드 공통) — want 가 목록에 없으면 highest 면 가장 높은 것, 아니면 맨 앞 */
function paintLevels(sel, list, want, highest) {
  sel.innerHTML = selectOptions(list, want);
  if (highest && list.length && !list.includes(want)) sel.value = list[list.length - 1];
}

function paintFieldBossLevels(want) {
  paintLevels($('#fb-level'), dl.fb.difficulties[$('#fb-boss').value] || [], want, true);  // 없으면 그 보스의 가장 높은 난이도
}

function fieldBossSpec() {
  const chars = pickedSlots('fbChars');
  if (!chars.length) return null;
  const pick = { boss: $('#fb-boss').value, difficulty: $('#fb-level').value };
  setPref('fieldBoss', pick);
  return { kind: 'daily', label: '필드 보스 · ' + pick.boss, chars: chars, only: ['field_boss'], force: true, fieldBoss: pick };
}

/* 주간 숙제 — 주말 어비스·레이드 ('주말에는 어비스!'·'주말에는 레이드!', 토·일요일에만). 일일 숙제 카드(kind 'daily')에
 * only=['weekend_abyss', 'weekend_raid'] (끈 쪽은 뺌)로, 고른 던전·레이드·난이도·방식은 카드의 weekend.
 * 캐릭터마다 어비스 → 레이드 순서로 하고 다음 캐릭터로 (실행기 runner). 깼는지는 들어가기 전에 퀘스트 창으로 보므로 늘 force.
 * 주말이 아니면 큐에서 기다렸다가 토요일에 돈다 (mabi/tasks SEASON). 목록·기본값은 파이썬이 준다
 * (mm.daily.weekendSettings ← mabi/tasks/weekend.choices) */
function paintWeekend() {
  paintPick('wk', 'wkChars');
  const w = dl.wk;
  if (!w) return;
  $('#wk-ab-runs').textContent = w.runs.abyss + '판';
  $('#wk-rd-runs').textContent = w.runs.raid + '판';
  $('#wk-note').textContent = w.notNow ? '오늘은 주말이 아님 — 담아 두면 토요일에 돕니다' : '';
  if ($('#wk-rd-raid').options.length) return;  // 고르던 것을 덮지 않게 칸은 처음 한 번만 채운다
  const saved = pref('weekend', {});
  const ab = Object.assign({}, w.pick.abyss, saved.abyss), rd = Object.assign({}, w.pick.raid, saved.raid);
  $('#wk-ab-mode').value = ab.mode === 'solo' ? 'solo' : 'party';
  $('#wk-rd-mode').value = rd.mode === 'solo' ? 'solo' : 'party';
  paintWeekendAbyss(ab.dungeon, ab.difficulty);
  const raids = Object.keys(w.raids);
  $('#wk-rd-raid').innerHTML = selectOptions(raids, raids.includes(rd.raid) ? rd.raid : raids[0]);
  paintWeekendRaidLevels(rd.difficulty);
  const on = saved.on || {};
  $('#wk-ab-on').checked = on.abyss !== false;
  $('#wk-rd-on').checked = on.raid !== false;
  paintWeekendOn();
}

/** 고를 난이도 — want 가 목록에 없으면 설정 기본값, 그것도 없으면 맨 앞 (가장 높은 것으로 올리지 않는다 — 어비스 함께하기는 지옥4 까지 있다) */
function weekendLevel(list, want, fallback) {
  return list.includes(want) ? want : list.includes(fallback) ? fallback : list[0];
}

/* 어비스 던전·난이도 칸 — 방식(함께하기·혼자하기)마다 열린 난이도가 다르다 */
function paintWeekendAbyss(want, wantLevel) {
  const by = dl.wk.abyss[$('#wk-ab-mode').value] || {};
  const list = Object.keys(by);
  $('#wk-ab-dungeon').innerHTML = selectOptions(list, list.includes(want) ? want : list[0]);
  const levels = by[$('#wk-ab-dungeon').value] || [];
  $('#wk-ab-level').innerHTML = selectOptions(levels, weekendLevel(levels, wantLevel, dl.wk.pick.abyss.difficulty));
}

function paintWeekendRaidLevels(want) {
  const levels = dl.wk.raids[$('#wk-rd-raid').value] || [];
  $('#wk-rd-level').innerHTML = selectOptions(levels, weekendLevel(levels, want, dl.wk.pick.raid.difficulty));
}

/* 끈 쪽(어비스·레이드)의 고르는 칸은 흐리게 */
function paintWeekendOn() {
  [['ab', ['dungeon', 'level', 'mode']], ['rd', ['raid', 'level', 'mode']]].forEach(([k, ids]) => {
    const on = $('#wk-' + k + '-on').checked;
    ids.forEach((id) => { $('#wk-' + k + '-' + id).disabled = !on; });
  });
}

function weekendSpec() {
  const chars = pickedSlots('wkChars');
  if (!chars.length) return null;
  const on = { abyss: $('#wk-ab-on').checked, raid: $('#wk-rd-on').checked };
  const only = [on.abyss && 'weekend_abyss', on.raid && 'weekend_raid'].filter(Boolean);
  if (!only.length) { toast('어비스·레이드 중 하나 이상 고르세요', '', 'bad'); return null; }
  const pick = {
    abyss: { dungeon: $('#wk-ab-dungeon').value, difficulty: $('#wk-ab-level').value, mode: $('#wk-ab-mode').value },
    raid: { raid: $('#wk-rd-raid').value, difficulty: $('#wk-rd-level').value, mode: $('#wk-rd-mode').value },
  };
  setPref('weekend', Object.assign({ on }, pick));
  return { kind: 'daily', label: '주말 어비스·레이드', chars: chars, only: only, force: true, weekend: pick };
}

/* 카드 줄: '6명 · 어비스 허상의 정박지 매우 어려움2 함께하기 · 레이드 …' */
function weekendAmount(x) {
  const w = x.weekend || {};
  const one = (t, k, place) => (x.only.includes('weekend_' + k) && w[k]
    ? t + ' ' + w[k][place] + ' ' + w[k].difficulty + (MODE_NAME[w[k].mode] ? ' ' + MODE_NAME[w[k].mode] : '') : '');
  return [(x.chars || []).length + '명', one('어비스', 'abyss', 'dungeon'), one('레이드', 'raid', 'raid')].filter(Boolean).join(' · ');
}

function dailyAmount(x) {
  if (x.only && x.only.length && x.only.every((t) => t.startsWith('weekend_'))) return weekendAmount(x);
  if (x.only && x.only.length === 1 && ['drill', 'vanguard'].includes(x.only[0])) return (x.chars || []).length + '명';
  if (x.only && x.only.length === 1 && x.only[0] === 'field_boss') {
    return (x.chars || []).length + '명' + (x.fieldBoss ? ' · ' + x.fieldBoss.difficulty : '');
  }
  return (x.chars || []).length + '명 · ' + (x.only ? '숙제 ' + x.only.length + '개' : '전체') + (x.force ? ' · 다시' : '');
}

/* 작업 큐 카드 종류 (queue.js qRegisterKind) — 화면 쪽 표시만. 실행·멈춤·화면 설정은 파이썬 (gui_app/queue_api.py) */
qRegisterKind('daily', { amount: dailyAmount });

/* ── 설정 ── */

const FIELD_RUNS = [0, 1, 2, 3, 4, 5];  // 사냥터 출장 횟수 (캐릭터 탭 설정 창도 같이 쓴다)

function paintDailySettings() {
  const s = dl.settings;
  $('#dl-field-runs').innerHTML = selectOptions(FIELD_RUNS, s.silver.field_runs);
  $('#dl-field').innerHTML = selectOptions(s.fields, s.field);
  $('#dl-dungeon').innerHTML = selectOptions(s.dungeons, s.silver.dungeon);
  $('#dl-floor').innerHTML = selectOptions(Object.entries(mm.labels.floors || {}), s.silver.floor);
  const f = s.follow || {};
  const fol = (n) => (f.total ? n + '명 적용' : '');
  $('#dl-follow-field').textContent = fol(f.field);
  $('#dl-follow-dungeon').textContent = fol(f.dungeon);
  $('#dl-sunday').innerHTML = selectOptions(s.sundays, s.sunday);
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

/** 옵션 창의 숙제 쪽 칸 (일시정지·염색 키, 화면 맞추기, 폴더, 게임 단축키) — 설정을 한 번 읽어 나눠 그린다 */
async function loadOptionSettings() {
  const s = await mm.daily.settings();
  paintPathSettings(s);
  paintGameKeys(s.game_keys || []);
}

function paintPathSettings(s) {
  dl.settings = Object.assign(dl.settings || {}, { stop_key: s.stop_key });
  const fkeys = (cur) => selectOptions(Array.from({ length: 12 }, (_, i) => ['f' + (i + 1), 'F' + (i + 1)]), cur);
  $('#opt-stop-key').innerHTML = fkeys(s.stop_key);
  $('#opt-dye-key').innerHTML = fkeys(s.dye_key);
  $('#opt-fit-display').checked = s.fit_display !== false;
  $('#opt-restart-auto').checked = s.restart_auto !== false;
  ['data', 'logs', 'shots'].forEach((k) => { $('#dl-p-' + k).value = s.paths[k] || ''; });
  $('#dl-p-now').textContent = '지금: ' + s.current.data + ' (바꾸면 다음 실행부터)';
}

async function saveRemoteKeys() {
  const r = await mm.daily.saveSettings({ stop_key: $('#opt-stop-key').value, dye_key: $('#opt-dye-key').value });
  if (!(r && r.error)) { dl.settings = Object.assign(dl.settings || {}, { stop_key: $('#opt-stop-key').value }); paintStopKey(); }
  $('#opt-rkeys-msg').textContent = r && r.error ? r.error : '저장했습니다';
  if (!(r && r.error)) paintPathSettings(await mm.daily.settings());
}

async function savePathSettings() {
  const r = await mm.daily.saveSettings({
    paths: { data: $('#dl-p-data').value, logs: $('#dl-p-logs').value, shots: $('#dl-p-shots').value },
  });
  $('#opt-paths-msg').textContent = r && r.error ? r.error : '저장했습니다';
  if (!(r && r.error)) paintPathSettings(await mm.daily.settings());
}

/* 게임 단축키 — 칸을 누르고 키를 누르면 그 키 (한글 입력 상태에서도 되게 e.code 로) */
function keyName(e) {
  const c = e.code || '';
  if (/^Key[A-Z]$/.test(c)) return c.slice(3).toLowerCase();
  if (/^Digit\d$/.test(c)) return c.slice(5);
  if (/^F([1-9]|1[0-2])$/.test(c)) return c.toLowerCase();
  if (/^Numpad\d$/.test(c)) return 'num' + c.slice(6);
  return {
    Slash: '/', Period: '.', Comma: ',', Minus: '-', Equal: '=', Semicolon: ';', Quote: "'",
    BracketLeft: '[', BracketRight: ']', Backslash: '\\', Backquote: '`',
    Home: 'home', End: 'end', Insert: 'insert', Delete: 'delete', PageUp: 'pageup', PageDown: 'pagedown',
    ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
  }[c] || null;
}

function paintGameKeys(list) {
  $('#opt-game-keys').innerHTML = list.map((k) => {
    const [name, hint] = k.label.split(' — ');
    return '<dt>' + esc(name) + '</dt><dd><input class="mono game-key" data-name="' + esc(k.name) + '"'
      + ' data-default="' + esc(k.default) + '" value="' + esc(k.key.toUpperCase()) + '" readonly>'
      + (hint ? '<div class="hint">' + esc(hint) + '</div>' : '') + '</dd>';
  }).join('');
}

async function saveGameKeys() {
  const v = {};
  document.querySelectorAll('#opt-game-keys .game-key').forEach((i) => { v[i.dataset.name] = i.value.toLowerCase(); });
  const r = await mm.daily.saveSettings({ game_keys: v });
  $('#opt-keys-msg').textContent = r && r.error ? r.error : '저장했습니다';
  if (!(r && r.error)) paintGameKeys((await mm.daily.settings()).game_keys || []);
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
    ['남음', n((s) => s === 'CHECK'), 'pill-warn'],
    // 진행 조건이 안 돼 넘긴 일(아르바이트 구매·긴 가공 등)은 실패·남음과 따로 센다 (2026-11-06 사용자)
    ['넘김', n((s) => s === 'MANUAL'), 'pill-muted'],
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
  $('#ab-dungeon').innerHTML = selectOptions(a.dungeons, a.dungeon);
  $('#ab-difficulty').innerHTML = selectOptions(a.difficulties, a.difficulty);
  $('#ab-char').innerHTML = charOptions(a.chars, a.slot, '지금 접속한 캐릭터');
  $('#ab-runs').value = a.runs;
  $('#ab-minutes').value = a.minutes;
  $('#ab-revive').checked = a.revive !== false;
  $('#ab-mode').value = a.mode;
  abyssFrontOnly = a.frontOnly || [];
  paintAbyssBg();
  paintAbyssRunning(a.running);
  loadRaid(a.chars);
  loadBoss();
}

/* 고른 던전이 뒤에서 돌 수 있나 — 흩어진 물길은 패턴 이동 때문에 게임을 앞에 두고만 돈다 (abyss.FRONT_ONLY) */
let abyssFrontOnly = [];
function paintAbyssBg() {
  const front = abyssFrontOnly.includes($('#ab-dungeon').value);
  const el = $('#ab-bg');
  el.textContent = front ? '백그라운드 불가' : '백그라운드 가능';
  el.className = 'pill ab-bg ' + (front ? 'pill-warn' : 'pill-ok');
  el.title = front
    ? '패턴(투창·틱택토) 때 캐릭터를 직접 움직여야 해서 게임을 앞에 둔 채로 돕니다'
    : '입장할 때만 게임을 앞으로 가져오고, 그 뒤로는 다른 창에 가려져 있어도 됩니다 (작업 표시줄로 내리면 안 됨)';
}

/* 보스전 기본값 (궁극기·팔라딘 변신) — 숙제 기본값처럼 캐릭터 탭에서 따로 정하지 않은 캐릭터에 */
async function loadBoss() {
  const b = await mm.daily.bossSettings();
  if (!b) return;
  $('#ab-def-ult').checked = !!b.ultimate;
  $('#ab-def-pal').checked = !!b.paladin;
  const f = b.follow || {};
  const fol = (n) => (f.total ? n + '명 적용' : '');
  $('#ab-follow-ult').textContent = fol(f.ultimate);
  $('#ab-follow-pal').textContent = fol(f.paladin);
}

async function saveBoss() {
  const r = await mm.daily.saveBoss({ ultimate: $('#ab-def-ult').checked, paladin: $('#ab-def-pal').checked });
  $('#ab-boss-msg').textContent = r && r.error ? r.error : '저장했습니다';
  if (!(r && r.error)) await loadBoss();
}

/** 어비스·레이드 탭 공통: 시작/멈춤 버튼 (pre = '#ab' · '#rd') */
function paintRepeatRunning(pre, on) {
  $(pre + '-start').classList.toggle('hidden', on);
  $(pre + '-stop').classList.toggle('hidden', !on);
}

function paintAbyssRunning(on) { paintRepeatRunning('#ab', on); }

/* 어비스 반복도 작업 큐의 한 항목으로 돈다 (일일 숙제와 같은 방식). '시작' = 큐 맨 앞에 넣고 돌리기,
 * '목표' = 탭에서 고른 그대로(판 수·분 제한 포함) 큐 뒤에 담기만 한다 (재생을 눌러야 진행)
 * → 'A 캐릭터 3판 → B 캐릭터 3판' 처럼 미리 걸어 둘 수 있다. */
/** 어비스·레이드 탭에서 고른 그대로 큐 카드 (pre = '#ab' · '#rd', place = 장소 칸 이름 — dungeon · raid) */
function repeatSpec(kind, pre, title, place) {
  const sel = $(pre + '-char');
  const slot = Number(sel.value) || 0;
  const name = slot ? sel.options[sel.selectedIndex].textContent.replace(/^\d+\.\s*/, '') : '';
  return {
    kind, label: title + ' · ' + (name || '지금 캐릭터'),
    slot, [place]: $(pre + '-' + place).value, difficulty: $(pre + '-difficulty').value, mode: $(pre + '-mode').value,
    runs: Number($(pre + '-runs').value) || 0, minutes: Number($(pre + '-minutes').value) || 0,
    revive: $(pre + '-revive').checked,
  };
}

function startRepeat(it, title) {
  qStart(it, { title: title + ' 반복 시작', hint: stopKey() + ' = 멈춤', busy: '이미 ' + title + ' 반복 중입니다' });
}

function abyssSpec() { return repeatSpec('abyss', '#ab', '어비스', 'dungeon'); }

const MODE_NAME = { solo: '혼자하기', party: '함께하기' };

function abyssAmount(x) {
  const lim = [x.runs ? x.runs + '판' + (x.doneRuns ? ' (' + x.doneRuns + '판 함)' : '') : '',
    x.minutes ? x.minutes + '분' : ''].filter(Boolean).join(' · ');
  return x.dungeon + ' ' + x.difficulty + (x.mode ? ' ' + MODE_NAME[x.mode] : '') + ' · ' + (lim || '멈출 때까지') + (x.revive === false ? ' · 쓰러지면 나감' : '');
}


qRegisterKind('abyss', {
  amount: (x) => abyssAmount(x),
  doneToast: (x) => ['어비스 반복 끝', x.label + ' · ' + abyssAmount(x)],
});

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
  $('#rd-raid').innerHTML = selectOptions(r.raids, r.raid);
  paintRaidDiffs(r.difficulty);
  $('#rd-char').innerHTML = charOptions(chars, r.slot, '지금 접속한 캐릭터');
  $('#rd-runs').value = r.runs;
  $('#rd-minutes').value = r.minutes;
  $('#rd-revive').checked = r.revive !== false;
  $('#rd-mode').value = r.mode;
  paintRaidRunning(r.running);
}

function paintRaidDiffs(want) {
  paintLevels($('#rd-difficulty'), raidDiffs[$('#rd-raid').value] || [], want);
}

function paintRaidRunning(on) { paintRepeatRunning('#rd', on); }

function raidSpec() { return repeatSpec('raid', '#rd', '레이드', 'raid'); }

function raidAmount(x) {
  return abyssAmount({ ...x, dungeon: x.raid });
}

qRegisterKind('raid', {
  amount: (x) => raidAmount(x),
  doneToast: (x) => ['레이드 반복 끝', x.label + ' · ' + raidAmount(x)],
});

mm.daily.onRaid(onRepeatEvent('raid', '#rd', '레이드'));

/* ── 배선 ── */

LOADERS.daily = () => loadDaily();
LOADERS.abyss = () => loadAbyss();

bindStartQueue('dl', dailySpec, (it) => startHomework(it, true), () => {
  const card = dlPausedCard();
  if (card) qPlayOne(card.id);  // 일시정지 중이면 이어 하기 (F12 와 같다)
  return !!card;
});
$('#opt-fit-display').addEventListener('change', () => mm.daily.saveSettings({ fit_display: $('#opt-fit-display').checked }));
$('#opt-restart-auto').addEventListener('change', () => mm.daily.saveSettings({ restart_auto: $('#opt-restart-auto').checked }));
$('#ab-dungeon').addEventListener('change', paintAbyssBg);
bindStartQueue('ab', abyssSpec, (it) => startRepeat(it, '어비스'));
$('#ab-stop').addEventListener('click', () => mm.daily.abyssStop());
$('#rd-raid').addEventListener('change', () => paintRaidDiffs($('#rd-difficulty').value));
bindStartQueue('rd', raidSpec, (it) => startRepeat(it, '레이드'));
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
$('#opt-game-keys').addEventListener('keydown', (e) => {
  const i = e.target.closest('.game-key');
  if (!i || e.key === 'Tab') return;
  e.preventDefault();
  if (e.key === 'Escape') { e.stopPropagation(); i.blur(); return; }  // 옵션 창은 닫지 않는다
  if (e.key === 'Backspace') { i.value = ''; return; }
  const k = keyName(e);
  if (k) i.value = k.toUpperCase();
  $('#opt-keys-msg').textContent = k ? '' : '그 키는 쓸 수 없습니다 (Shift·Ctrl·Alt·Space·Enter·Esc 는 안 됨)';
});
$('#opt-keys-save').addEventListener('click', saveGameKeys);
$('#opt-keys-reset').addEventListener('click', () => {
  document.querySelectorAll('#opt-game-keys .game-key').forEach((i) => { i.value = i.dataset.default.toUpperCase(); });
  $('#opt-keys-msg').textContent = '저장을 눌러야 적용됩니다';
});
$('#ab-boss-save').addEventListener('click', saveBoss);
$('#opt-paths-save').addEventListener('click', savePathSettings);
$('#opt-rkeys-save').addEventListener('click', saveRemoteKeys);
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
bindPick('dr', 'drillChars');
bindStartQueue('dr', drillSpec, startHomework);
$('#en-start').addEventListener('click', startEnhance);
bindPick('fb', 'fbChars');
$('#fb-boss').addEventListener('change', () => paintFieldBossLevels($('#fb-level').value));
bindStartQueue('fb', fieldBossSpec, startHomework);
bindPick('vg', 'vgChars');
bindStartQueue('vg', vanguardSpec, startHomework);
bindPick('wk', 'wkChars');
$('#wk-ab-mode').addEventListener('change', () => paintWeekendAbyss($('#wk-ab-dungeon').value, $('#wk-ab-level').value));
$('#wk-ab-dungeon').addEventListener('change', () => paintWeekendAbyss($('#wk-ab-dungeon').value, $('#wk-ab-level').value));
$('#wk-rd-raid').addEventListener('change', () => paintWeekendRaidLevels($('#wk-rd-level').value));
$('#wk-ab-on').addEventListener('change', paintWeekendOn);
$('#wk-rd-on').addEventListener('change', paintWeekendOn);
bindStartQueue('wk', weekendSpec, startHomework);
