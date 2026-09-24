'use strict';
/* 모비 커넥터 리모콘 렌더러. window.mm(preload)을 통해서만 메인과 통신한다. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const num = (n) => Number(n || 0).toLocaleString('ko-KR');
const esc = (s) =>
  String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/** 남은 초를 사람이 읽는 형태로 */
function dur(sec) {
  if (!sec || sec <= 0) return '완료';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return h + '시간 ' + m + '분';
  if (m > 0) return m + '분';
  return sec + '초';
}

/* ── 토스트 / 모달 / 상태바 ─────────────────────── */

function toast(head, msg, kind) {
  const d = document.createElement('div');
  d.className = 'toast ' + (kind || '');
  d.innerHTML = '<div class="h">' + esc(head) + '</div>' + (msg ? '<div class="m">' + esc(msg) + '</div>' : '');
  $('#toasts').appendChild(d);
  setTimeout(() => d.remove(), kind === 'bad' ? 7000 : 4000);
}

function say(msg) {
  $('#sb-msg').textContent = msg;
}

function setBusy(on, text) {
  $('#sb-busy').classList.toggle('hidden', !on);
  if (text) $('#sb-busy-text').textContent = text;
}

/** 모달 확인. Promise<boolean> */
function confirmModal(title, bodyHtml, okLabel) {
  return new Promise((resolve) => {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML = bodyHtml;
    $('#modal-ok').textContent = okLabel || '실행';
    $('#modal').classList.remove('hidden');

    const done = (v) => {
      $('#modal').classList.add('hidden');
      $('#modal-ok').removeEventListener('click', onOk);
      $('#modal-cancel').removeEventListener('click', onNo);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    };
    const onOk = () => done(true);
    const onNo = () => done(false);
    const onKey = (e) => {
      if (e.key === 'Escape') done(false);
      if (e.key === 'Enter') done(true);
    };
    $('#modal-ok').addEventListener('click', onOk);
    $('#modal-cancel').addEventListener('click', onNo);
    document.addEventListener('keydown', onKey);
    $('#modal-ok').focus();
  });
}

/**
 * 숫자 입력 모달. Electron은 window.prompt()를 지원하지 않으므로 직접 만든다.
 * Promise<number|null>
 */
function promptNumber(title, label, defaultValue, hint) {
  return new Promise((resolve) => {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML =
      '<p>' + esc(label) + '</p>' +
      '<input id="modal-input" type="number" min="1" step="1" value="' + esc(defaultValue) + '" class="w-full">' +
      (hint ? '<p class="hint">' + esc(hint) + '</p>' : '');
    $('#modal-ok').textContent = '확인';
    $('#modal').classList.remove('hidden');

    const input = $('#modal-input');
    input.focus();
    input.select();

    const done = (v) => {
      $('#modal').classList.add('hidden');
      $('#modal-ok').removeEventListener('click', onOk);
      $('#modal-cancel').removeEventListener('click', onNo);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    };
    const onOk = () => {
      const n = parseInt(input.value, 10);
      done(Number.isFinite(n) && n > 0 ? n : null);
    };
    const onNo = () => done(null);
    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter') { e.preventDefault(); onOk(); }
    };
    $('#modal-ok').addEventListener('click', onOk);
    $('#modal-cancel').addEventListener('click', onNo);
    document.addEventListener('keydown', onKey);
  });
}

/**
 * 목록에서 하나 고르는 모달.
 * 레벨처럼 값이 정해져 있는 것은 숫자를 타이핑하게 하는 것보다 고르게 하는 편이 빠르고 덜 틀린다.
 * @param {Array<{value:*, label:string}>} options
 */
function promptSelect(title, label, options, current, hint) {
  return new Promise((resolve) => {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML =
      '<p>' + esc(label) + '</p>' +
      '<select id="modal-input" class="w-full">' +
      options.map((o) =>
        '<option value="' + esc(o.value) + '"' + (String(o.value) === String(current) ? ' selected' : '') + '>' +
        esc(o.label) + '</option>').join('') +
      '</select>' +
      (hint ? '<p class="hint">' + esc(hint) + '</p>' : '');
    $('#modal-ok').textContent = '확인';
    $('#modal').classList.remove('hidden');

    const input = $('#modal-input');
    input.focus();

    const done = (v) => {
      $('#modal').classList.add('hidden');
      $('#modal-ok').removeEventListener('click', onOk);
      $('#modal-cancel').removeEventListener('click', onNo);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    };
    const onOk = () => done(input.value);
    const onNo = () => done(null);
    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter') { e.preventDefault(); onOk(); }
    };
    $('#modal-ok').addEventListener('click', onOk);
    $('#modal-cancel').addEventListener('click', onNo);
    document.addEventListener('keydown', onKey);
  });
}

/** 문자열 입력 모달. promptNumber의 텍스트판. */
function promptText(title, label, defaultValue, hint) {
  return new Promise((resolve) => {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML =
      '<p>' + esc(label) + '</p>' +
      '<input id="modal-input" type="text" maxlength="40" value="' + esc(defaultValue || '') + '" class="w-full">' +
      (hint ? '<p class="hint">' + esc(hint) + '</p>' : '');
    $('#modal-ok').textContent = '확인';
    $('#modal').classList.remove('hidden');
    const input = $('#modal-input');
    input.focus(); input.select();
    const done = (v) => {
      $('#modal').classList.add('hidden');
      $('#modal-ok').removeEventListener('click', onOk);
      $('#modal-cancel').removeEventListener('click', onNo);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    };
    const onOk = () => done(input.value.trim() || null);
    const onNo = () => done(null);
    const onKey = (e) => {
      if (e.key === 'Escape') done(null);
      if (e.key === 'Enter') { e.preventDefault(); onOk(); }
    };
    $('#modal-ok').addEventListener('click', onOk);
    $('#modal-cancel').addEventListener('click', onNo);
    document.addEventListener('keydown', onKey);
  });
}

/* ── 명령 실행 (비용 확인 포함) ─────────────────── */

let busy = false;
/** 마지막으로 확인된 연결 상태. 꺼져 있으면 5초짜리 호출을 피한다. */
let online = true;

async function runAction(command, body, opts) {
  const o = opts || {};
  if (busy) {
    toast('실행 중', '이전 명령이 끝난 뒤 다시 시도하세요.', 'bad');
    return null;
  }

  const cost = await mm.costOf(command, o.times || 1);

  if (cost.costed && !o.skipConfirm) {
    const enough = cost.enough;
    const cur = cost.currency || '정령의 날개';
    const html =
      '<p>' + esc(o.label || command) + '</p>' +
      '<div class="cost">' +
        '<div>소모 <span class="big">' + num(cost.total) + '</span> ' + esc(cur) +
          (o.times > 1 ? ' <span class="muted">(' + cost.perCall + ' × ' + o.times + '회)</span>' : '') + '</div>' +
        '<div class="muted">보유 ' + num(cost.balance) + ' → 실행 후 ' + num(cost.balance - cost.total) + '</div>' +
        (enough ? '' : '<div class="bad">' + esc(cur) + '이(가) 부족합니다.</div>') +
      '</div>' +
      (o.note ? '<p class="hint">' + esc(o.note) + '</p>' : '');

    if (!enough) {
      await confirmModal('실행 불가', html, '닫기');
      return null;
    }
    if (!(await confirmModal('실행 확인', html))) return null;
  } else if (o.confirmText && !o.skipConfirm) {
    if (!(await confirmModal('확인', '<p>' + esc(o.confirmText) + '</p>'))) return null;
  }

  busy = true;
  setBusy(true, (o.label || command) + ' 실행 중…');
  say(command + ' 호출…');

  let r;
  try {
    r = await mm.exec(command, body);
  } catch (err) {
    // IPC 자체가 실패한 경우. finally가 없으면 busy가 true로 남아
    // 이후 모든 명령이 "다른 명령이 실행 중"으로 막힌다.
    r = { ok: false, error: 'ipc_failed', message: String((err && err.message) || err), durationMs: 0 };
  } finally {
    busy = false;
    setBusy(false);
  }

  if (r.ok) {
    const extra = r.wingsSpent ? ' · ' + (cost.currency || '날개') + ' ' + r.wingsSpent + ' 소모' : '';
    toast('완료 — ' + (o.label || command), describeResult(command, r.data) + ' (' + r.durationMs + 'ms)' + extra, 'ok');
    say('완료: ' + command);
  } else {
    // 메인이 붙여 준 한국어 해설을 우선 쓰고, 없으면 원문을 보여준다
    const ko = r.ko;
    const head = '실패 — ' + (o.label || command);
    if (ko) {
      // 번역이 있으면 영어 원문은 굳이 띄우지 않는다. 필요하면 콘솔 탭 응답에서 볼 수 있다.
      toast(head + ': ' + ko.text, ko.hint || '', 'bad');
      say('실패: ' + ko.text);
    } else {
      toast(head, (r.error || '') + (r.message ? ' · ' + r.message : ''), 'bad');
      say('실패: ' + command + ' (' + (r.error || '') + ')');
    }
  }

  logCall(command, r);
  refreshTopbar();
  return r;
}

function describeResult(command, d) {
  if (!d) return '응답 없음';
  if (command === 'execute_gathering') {
    if (d.result === 'started') return '자동 낚시 시작';
    if (d.gained !== undefined) return '획득 ' + d.gained + (d.target ? '/' + d.target : '');
    if (d.result) return String(d.result);
  }
  if (command === 'execute_crafting' && d.craftCount) return d.craftCount + '회 제작 완료';
  if (command === 'execute_altering') return '가공 큐 등록됨';
  if (d.message) return String(d.message);
  if (Array.isArray(d)) return d.length + '건';
  return '성공';
}

function logCall(command, r) {
  const box = $('#call-log');
  const d = document.createElement('div');
  const t = new Date().toLocaleTimeString('ko-KR');
  const why = r.ok ? '' : ' · ' + esc(r.ko ? r.ko.text : r.error || '');
  d.innerHTML =
    '<span class="t">' + t + '</span>' +
    '<span class="' + (r.ok ? 'mark-ok' : 'mark-bad') + '">' + (r.ok ? '✔' : '✘') + '</span> ' +
    esc(command) + ' <span class="muted">' + r.durationMs + 'ms' + why +
    (r.ok || !r.error ? '' : ' <span class="sub">[' + esc(r.error) + ']</span>') + '</span>';
  box.insertBefore(d, box.firstChild);
  while (box.children.length > 200) box.removeChild(box.lastChild);
}

/* ── 상단바 ─────────────────────────────────────── */

/**
 * 연결이 끊겼을 때 무엇을 해야 하는지 알린다.
 * 화면은 캐시로 계속 채워지므로, 그 값이 실시간이 아니라는 점도 함께 밝힌다.
 */
function setOffline(st) {
  const banner = $('#offline-banner');
  if (!st || st.connected) {
    banner.classList.add('hidden');
    return;
  }
  // 커넥터를 아예 못 찾은 것은 "게임이 꺼져 있다"와 전혀 다른 상황이다.
  // 처음 받은 사람이 여기 걸리므로, 무엇이 없는지와 무엇을 하면 되는지를 같이 준다.
  if (st.reason === 'no_connector') {
    $('#offline-text').textContent =
      '마비노기 모바일 커넥터를 찾지 못했습니다. 이 프로그램은 게임에 딸려 오는 ' +
      'MabinogiMobile_CLI.exe 가 있어야 동작합니다 — 게임을 설치한 뒤 다시 찾아 주세요.';
    $('#offline-retry').textContent = '커넥터 찾기';
    banner.classList.remove('hidden');
    return;
  }
  $('#offline-retry').textContent = '다시 확인';

  const what = st.reason === 'game_off'
      ? '마비노기 모바일이 실행되어 있지 않습니다.'
    : st.reason === 'option_off'
      ? '게임 설정에서 "MM AI 에이전트 활성화"가 꺼져 있습니다.'
      : '게임에 연결할 수 없습니다.';
  $('#offline-text').textContent = what + ' 표시된 값은 마지막으로 받아 둔 정보이며 실시간이 아닙니다.';
  banner.classList.remove('hidden');
}

/** 이미 받아 둔 값으로 상단바만 그린다 (조회는 하지 않는다). */
function paintTopbar(st, me, wings) {
  online = !!(st && st.connected);
  setOffline(st);
  const pill = $('#conn');
  if (!st || !st.connected) {
    const why = st && st.reason === 'game_off' ? '게임 미실행'
              : st && st.reason === 'option_off' ? 'AI 옵션 꺼짐' : '연결 안 됨';
    pill.textContent = '● ' + why;
    pill.className = 'pill pill-bad';
    $('#charname').textContent = '—';
    $('#charsub').textContent = '';
    $('#wings').textContent = '—';
    $('#weight').textContent = '—';
    return false;
  }
  pill.textContent = '● 연결됨';
  pill.className = 'pill pill-ok';

  if (me && !me.error) {
    // get_my_info는 캐릭터명을 주지 않는다. Title은 착용 타이틀, RealmName은 서버다.
    $('#charname').textContent = 'Lv.' + me.level + ' ' + me.job;
    $('#charsub').textContent = (me.title ? '「' + me.title + '」 · ' : '') + me.realm;
    $('#weight').textContent = me.weightPct + '%';
  }
  if (wings && !wings.error) $('#wings').textContent = num(wings.amount);
  return true;
}

async function refreshTopbar() {
  const st = await mm.status();
  if (!st.connected) return paintTopbar(st);
  const r = await mm.queryMany(['me', 'wings'], dashOpts());
  return paintTopbar(st, r.me, r.wings);
}

/* ── 대시보드 ───────────────────────────────────── */

/* ── 자동 갱신 ──────────────────────────────────── */

/**
 * 게임은 변경을 알려주지 않는다(푸시/구독 명령이 없다). 그래서 폴링뿐인데,
 * 조회는 로컬 클라이언트 메모리에서 나오므로 게임 서버에는 부담이 없다.
 * 대신 다음을 지켜 불필요한 호출과 화면 튐을 막는다.
 *   - 창이 숨겨져 있으면(최소화·트레이) 건너뛴다
 *   - 대시보드 탭이 아닐 때는 상단바만 갱신한다
 *   - 명령 실행 중에는 건너뛴다 (CLI가 동시 호출을 거부한다)
 *   - 값이 그대로면 DOM을 건드리지 않는다 (paint 참고)
 * setInterval이 아니라 setTimeout 연쇄라, 한 번이 느려도 호출이 겹치지 않는다.
 */
const AUTO_KEY = 'mobi-remote.interval';
let autoTimer = null;
let autoRunning = false;

function autoIntervalMs() {
  const v = parseInt($('#auto-interval').value, 10);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

function autoStatus(text) {
  $('#auto-status').textContent = text;
}

/** 연결이 끊겼을 때의 최소 간격. 실패 판정에만 약 5초가 걸려 자주 찔러도 소용이 없다. */
const OFFLINE_MIN_MS = 20000;

function scheduleAuto() {
  clearTimeout(autoTimer);
  const ms = autoIntervalMs();
  if (!ms) {
    autoStatus('');
    return;
  }
  autoTimer = setTimeout(tickAuto, online ? ms : Math.max(ms, OFFLINE_MIN_MS));
}

async function tickAuto() {
  if (!autoIntervalMs()) return;
  if (autoRunning) return scheduleAuto();

  if (document.hidden) {
    autoStatus('창이 가려져 멈춤');
    return scheduleAuto();
  }
  if (busy) {
    autoStatus('명령 실행 중 — 대기');
    return scheduleAuto();
  }

  autoRunning = true;
  const t = Date.now();
  try {
    const st = await mm.status();
    if (!st.connected) {
      paintTopbar(st);
      autoStatus('게임 연결 끊김 — ' + Math.round(OFFLINE_MIN_MS / 1000) + '초마다 재확인');
    } else {
      // 상단바와 대시보드가 같은 조회를 나눠 쓴다 (me를 두 번 받지 않도록)
      const onDash = activeTab === 'dash';
      const names = onDash ? DASH_QUERIES.concat(['wings']) : ['me', 'wings'];
      const r = await mm.queryMany(names, dashOpts());
      paintTopbar(st, r.me, r.wings);
      if (onDash) loadDash({ data: r });
      autoStatus('갱신 ' + new Date().toLocaleTimeString('ko-KR') + ' · ' + (Date.now() - t) + 'ms');
    }
  } catch (err) {
    autoStatus('갱신 실패');
  } finally {
    autoRunning = false;
  }
  scheduleAuto();
}

function initAuto() {
  let saved = null;
  // 이름을 바꾸기 전 키도 한 번 본다. 안 그러면 쓰던 설정이 조용히 초기화된다.
  try { saved = localStorage.getItem(AUTO_KEY); } catch (_) { /* 접근 불가해도 무시 */ }
  if (saved !== null && $('#auto-interval').querySelector('option[value="' + saved + '"]')) {
    $('#auto-interval').value = saved;
  }
  $('#auto-interval').addEventListener('change', () => {
    try { localStorage.setItem(AUTO_KEY, $('#auto-interval').value); } catch (_) {}
    autoStatus(autoIntervalMs() ? '' : '꺼짐');
    scheduleAuto();
  });
  // 창이 다시 보이면 기다리지 않고 바로 한 번 갱신한다
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && autoIntervalMs()) {
      clearTimeout(autoTimer);
      tickAuto();
    }
  });
  scheduleAuto();
}

/**
 * 화면 일부를 필요할 때만 다시 그린다.
 * 자동 갱신은 값이 그대로일 때가 대부분인데, 매번 innerHTML을 갈아끼우면
 * 글자를 드래그하거나 읽는 중에 화면이 튄다.
 */
const dashSig = {};
function paint(id, html) {
  if (dashSig[id] === html) return false;
  dashSig[id] = html;
  $(id).innerHTML = html;
  return true;
}

// 주변 둘도 여기 포함한다. 조회는 로컬 클라이언트 메모리에서 나와 서버 부담이 없고,
// 주변은 계속 변하는 값이라 대시보드 주기에 같이 따라가는 편이 자연스럽다.
const DASH_QUERIES = ['me', 'activity', 'environment', 'currencies', 'nearPcs', 'nearNpcs'];

/**
 * 조회 옵션. 게임이 꺼진 걸 이미 알면 offline을 실어 보낸다.
 * 연결 실패 판정에만 약 5초가 걸리므로, 캐시가 있으면 호출 자체를 건너뛴다.
 */
function dashOpts() {
  const off = !online;
  return {
    me: { refresh: true, offline: off },
    wings: { refresh: true, offline: off },
    activity: { refresh: true, offline: off },
    environment: { refresh: true, offline: off },
    currencies: { nonZero: true, refresh: true, offline: off },
  };
}

/**
 * @param opts.data 이미 받아 둔 응답. 자동 갱신에서 상단바와 조회를 공유해
 *                  같은 명령을 두 번 부르지 않도록 넘겨준다.
 */
async function loadDash(opts) {
  const o = opts || {};
  const r = o.data || (await mm.queryMany(DASH_QUERIES, dashOpts()));

  const m = r.me || {};
  // 주의: CLI는 캐릭터명을 제공하지 않는다 (Title=타이틀, RealmName=서버)
  paint('#dash-char', m.error ? '<dt class="muted">조회 실패</dt><dd></dd>' : [
    ['타이틀', m.title || '(없음)'], ['레벨', m.level], ['직업', m.job], ['서버(렐름)', m.realm],
    ['전투력', num(m.combat)], ['생활력', num(m.living)],
    ['HP', m.hp], ['포만도', m.satiety], ['무게', m.weight + ' (' + m.weightPct + '%)'],
    ['버프', m.buffs + '개'],
  ].map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join(''));

  const e = r.environment || {};
  paint('#dash-env', e.error ? '<dt class="muted">조회 실패</dt><dd></dd>' : [
    ['위치', e.space], ['채널', e.channel], ['날씨', e.weather], ['에린 시각', e.erinnTime],
    ['좌표', e.pos ? e.pos.x.toFixed(1) + ', ' + e.pos.y.toFixed(1) : '—'],
    ['하우징', e.housing && e.housing.inside ? '내부' : '외부'],
  ].map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join(''));

  const a = r.activity || {};
  const flags = [
    ['자동 진행', a.autoPlaying, 1], ['자동 이동', a.autoTraveling, 1], ['전투 중', a.inCombat, 1],
    ['연주 중', a.performing, 1], ['대화 대기', a.dialogue, 1], ['앉음', a.sitting, 0], ['사망', a.dead, 1],
  ];
  paint('#dash-act',
    flags.map(([k, v, isBusy]) =>
      '<span class="flag ' + (v ? (isBusy ? 'busy' : 'on') : '') + '">' + esc(k) + '</span>').join('') +
    '<span class="flag">던전 ' + esc(a.dungeon || '-') + '</span>' +
    '<span class="flag">버튼 ' + esc(a.mainButton || '-') + '</span>' +
    '<span class="flag ' + (a.busy ? 'busy' : 'on') + '">' + (a.busy ? '바쁨' : '대기') + '</span>');

  const cur = (r.currencies && r.currencies.items) || [];
  paint('#dash-cur', cur.map((x) =>
    '<span class="chip"><em>' + esc(x.name) + '</em><b>' + num(x.amount) + '</b></span>').join('')
    || '<span class="muted">없음</span>');

  paintNear(r);
}

/* ── 정렬 ───────────────────────────────────────── */

/**
 * 표를 다시 줄 세운다. 게임 호출은 한 번도 늘지 않는다 — 이미 받아 둔 목록을 정렬할 뿐이다.
 *
 * **기본값은 CLI가 준 순서다.** 그게 게임 화면 순서라, 가나다순으로 덮어 버리면
 * 인게임과 나란히 놓고 볼 수가 없다. 그래서 기본을 항상 첫 항목에 둔다.
 *
 * 이름 비교는 `localeCompare(ko)`를 쓴다. 코드포인트로 비교하면 한글 자모가
 * 엉뚱하게 섞이고, 색상 태그가 붙은 이름(`<color=#...>★8</color>철검`)은
 * 태그 때문에 전혀 다른 자리로 간다 — 그래서 벗긴 이름(`name`)으로 비교한다.
 */
const SORTS = {
  // 이름이 길면 고르는 칸이 늘어나 줄이 넘친다. "게임과 동일"은 도움말에 있으면 된다.
  none: { label: '기본 순서', cmp: null },
  name: { label: '가나다순', cmp: (a, b) => nameCmp(a, b) },
  nameDesc: { label: '가나다 역순', cmp: (a, b) => nameCmp(b, a) },
  okFirst: { label: '가능한 것 먼저', cmp: (a, b) => (b.ok ? 1 : 0) - (a.ok ? 1 : 0) || nameCmp(a, b) },
  toolFirst: { label: '도구 있는 것 먼저', cmp: (a, b) => (b.tool ? 1 : 0) - (a.tool ? 1 : 0) || nameCmp(a, b) },
  perDesc: { label: '산출 많은 순', cmp: (a, b) => (b.per || 0) - (a.per || 0) || nameCmp(a, b) },
  totalAsc: { label: '수량 적은 순', cmp: (a, b) => (a.total || 0) - (b.total || 0) || nameCmp(a, b) },
  bagDesc: { label: '가방에 많은 순', cmp: (a, b) => (b.at ? b.at.bag : 0) - (a.at ? a.at.bag : 0) || nameCmp(a, b) },
  storeDesc: {
    label: '창고에 많은 순',
    cmp: (a, b) => storeOf(b) - storeOf(a) || nameCmp(a, b),
  },
  equippedFirst: { label: '장착 중 먼저', cmp: (a, b) => (b.equipped ? 1 : 0) - (a.equipped ? 1 : 0) || nameCmp(a, b) },
};

/** 캐릭·계정 창고를 합친 수량. 정렬에서만 쓴다. */
function storeOf(x) {
  return x.at ? x.at.charStore + x.at.accStore : 0;
}

/** 표마다 고를 수 있는 것이 다르다. CLI가 주지 않는 값으로는 정렬할 수 없다. */
const SORT_MENU = {
  craft: ['none', 'name', 'nameDesc', 'okFirst', 'perDesc'],
  alter: ['none', 'name', 'nameDesc', 'okFirst', 'perDesc'],
  gather: ['none', 'name', 'nameDesc', 'toolFirst'],
  instrument: ['none', 'name', 'nameDesc', 'equippedFirst'],
  music: ['none', 'name', 'nameDesc'],
  // 표정과 행동은 카드가 따로라 정렬도 따로 고른다
  facial: ['none', 'name', 'nameDesc'],
  behaviour: ['none', 'name', 'nameDesc'],
  items: ['none', 'name', 'nameDesc', 'totalAsc', 'bagDesc', 'storeDesc'],
};

/**
 * 탭마다 "기본"의 뜻이 다르다.
 * 제작·가공·채집·행동은 CLI가 준 순서지만, 소지품은 query.js가 이미 수량순으로 정렬해 준다.
 * 같은 라벨을 붙이면 거짓말이 된다.
 */
const SORT_LABEL = {
  items: { none: '수량 많은 순' },
};

const sortState = {};   // 표 이름 → 정렬 키

/* ── 즐겨찾기 ───────────────────────────────────── */

/**
 * 별표한 것은 같은 표 안의 "즐겨찾기" 구역으로 올라간다.
 *
 * 즐겨찾기를 맨 위로 올리는 정렬을 하나 더 만들 수도 있었지만, 그러면 "가나다순인데
 * 즐겨찾기만 위"처럼 두 기준이 섞여 무엇을 보고 있는지 알기 어려워진다. 구역을 나누면
 * 각 구역 안에서는 고른 정렬이 그대로 지켜진다.
 *
 * 키는 표시 이름이 아니라 원본 이름(nameRaw)이다. 게임 이름에 섞인 <color=…> 태그가
 * 붙고 떨어질 때마다 별표가 풀리지 않게.
 */
let favCache = {};      // 목록 이름 → Set

async function loadFavorites() {
  let all = null;
  try { all = await mm.fav.all(); } catch (_) { return; }   // 못 읽어도 화면은 돈다
  favCache = {};
  for (const k of Object.keys(all)) favCache[k] = new Set(all[k]);
}

function favKey(x) { return String(x.nameRaw || x.name || x.title || ''); }
function isFav(list, x) { const set = favCache[list]; return !!set && set.has(favKey(x)); }

/** 별표 버튼. 켜진 것만 색이 들어간다. */
function starBtn(list, x) {
  const on = isFav(list, x);
  return '<button class="star' + (on ? ' on' : '') + '" data-fav="' + list + '"' +
    ' data-fav-name="' + esc(favKey(x)) + '"' +
    ' title="' + (on ? '즐겨찾기에서 빼기' : '즐겨찾기에 넣기') + '">' + (on ? '★' : '☆') + '</button>';
}

/** 즐겨찾기와 나머지로 가른다. 정렬이 끝난 배열을 넣어야 구역 안 순서가 유지된다. */
function splitFav(list, rows) {
  const favs = [], rest = [];
  for (const r of rows) (isFav(list, r) ? favs : rest).push(r);
  return { favs: favs, rest: rest };
}

function secRow(label, cols, n) {
  return '<tr class="sec"><td colspan="' + cols + '">' + label +
    ' <span class="muted">' + n + '</span></td></tr>';
}

/**
 * 즐겨찾기 구역을 얹은 표 본문을 만든다.
 *
 * 쪽 나누기는 **나머지에만** 건다. 즐겨찾기가 3쪽으로 밀려나면 올려 둔 뜻이 없다.
 * 즐겨찾기가 하나도 없으면 구역 머리도 그리지 않는다 — 빈 칸만 차지한다.
 *
 * @param key 표 이름 (즐겨찾기 목록 이름이자 쪽 나누기 키)
 * @param sorted 정렬까지 끝난 전체 행
 * @param cols colspan
 * @param row 행 하나를 그리는 함수
 * @param usePager false 면 쪽을 나누지 않는다 (채집처럼 페이저가 없는 표)
 */
function favTableBody(key, sorted, cols, row, usePager) {
  const split = splitFav(key, sorted);
  const pg = usePager === false ? null : paged(key, split.rest);
  const shown = pg ? pg.rows : split.rest;

  let html = '';
  if (split.favs.length) {
    html += secRow('★ 즐겨찾기', cols, split.favs.length) + split.favs.map(row).join('');
    if (split.rest.length) html += secRow('전체', cols, split.rest.length);
  }
  if (shown.length) html += shown.map(row).join('');
  else if (!split.favs.length) html += '<tr><td colspan="' + cols + '" class="empty">결과 없음</td></tr>';

  return { html: html, pg: pg, rest: split.rest.length };
}

/** 칩 목록용. 표와 달리 구역 머리가 한 줄을 통째로 차지하는 칩이다. */
function favChips(list, rows, chip) {
  if (!rows.length) return '<span class="muted">결과 없음</span>';
  const split = splitFav(list, rows);
  let html = '';
  if (split.favs.length) {
    html += '<span class="grp">★ 즐겨찾기</span>' + split.favs.map(chip).join('');
    if (split.rest.length) html += '<span class="grp">전체</span>';
  }
  html += split.rest.map(chip).join('');
  return html;
}

function nameCmp(a, b) {
  // 악보만 name 이 아니라 title 이다. 접두("악보: ")가 전부 같아 떼고 비교하지 않아도 결과는 같다.
  return String(a.name || a.title || '').localeCompare(String(b.name || b.title || ''), 'ko');
}

function sortKey(key) {
  return sortState[key] || 'none';
}

/**
 * 정렬해서 돌려준다. 원본 배열은 건드리지 않는다 —
 * 캐시를 그대로 뒤집으면 "기본 순서"로 되돌릴 방법이 사라진다.
 */
function sortRows(key, rows) {
  const s = SORTS[sortKey(key)];
  if (!s || !s.cmp) return rows;
  return rows.slice().sort(s.cmp);
}

/** 툴바의 드롭다운을 채운다. */
function paintSortMenu(key) {
  const sel = $('#' + key + '-sort');
  if (!sel) return;
  const cur = sortKey(key);
  const over = SORT_LABEL[key] || {};
  sel.innerHTML = (SORT_MENU[key] || []).map((k) =>
    '<option value="' + k + '"' + (k === cur ? ' selected' : '') + '>' +
    esc(over[k] || SORTS[k].label) + '</option>').join('');
}

/** 저장해 둔 정렬 기준을 읽어 온다. 앱을 다시 켜도 고른 대로 보이게. */
async function loadSortPrefs() {
  let cfg = null;
  try { cfg = await mm.cfg.get(); } catch (_) { /* 설정을 못 읽어도 기본값으로 돈다 */ }
  const saved = (cfg && cfg.sort) || {};
  for (const key of Object.keys(SORT_MENU)) {
    // 저장된 값이 그 표에서 고를 수 없는 것이면 무시한다 (메뉴가 바뀌었을 수 있다)
    if (SORT_MENU[key].indexOf(saved[key]) !== -1) sortState[key] = saved[key];
    paintSortMenu(key);
  }
}

/** 정렬 드롭다운을 연결한다. 바뀌면 1쪽으로 되돌린다 — 3쪽에서 정렬하면 엉뚱한 데를 보게 된다. */
function wireSort() {
  for (const key of Object.keys(SORT_MENU)) {
    const sel = $('#' + key + '-sort');
    if (!sel) continue;
    sel.addEventListener('change', async () => {
      sortState[key] = sel.value;
      resetPage(key);
      const fn = PAGE_RENDER[key];
      if (fn) fn();
      try { await mm.cfg.sort(key, sel.value); } catch (_) { /* 저장 실패가 화면을 막지 않는다 */ }
    });
  }
}

/** 지금 테마와, 누르면 어떻게 되는지를 버튼에 적는다. */
function paintThemeBtn() {
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  const btn = $('#btn-theme');
  if (!btn) return;
  btn.textContent = light ? '☀' : '☾';
  btn.title = light ? '밝은 테마 — 누르면 어둡게' : '어두운 테마 — 누르면 밝게';
}

/**
 * 버튼을 "일하는 중"으로 바꾼다. 되돌릴 함수를 돌려준다.
 *
 * 상태바에도 진행이 뜨지만 화면 반대쪽 구석이라, 방금 누른 버튼이 도는 중인지가 눈에 안 들어온다.
 * 누른 자리에서 보여 주는 편이 확실하다. 진행 중 다시 눌리지 않도록 잠그는 역할도 겸한다.
 */
function btnBusy(el, text) {
  if (!el) return () => {};
  const html = el.innerHTML;
  const was = el.disabled;
  el.disabled = true;
  el.classList.add('busy');
  el.innerHTML = '<i class="spin"></i>' + esc(text || '진행 중…');
  return (nextText) => {
    el.disabled = was;
    el.classList.remove('busy');
    el.innerHTML = nextText === undefined ? html : esc(nextText);
  };
}

/** 진행 중인 버튼의 글자만 갈아 끼운다 (스피너는 그대로 둔다). */
function btnBusyText(el, text) {
  if (!el || !el.classList.contains('busy')) return;
  el.innerHTML = '<i class="spin"></i>' + esc(text);
}

/**
 * 시설 레벨을 고르게 한다. 가공 탭의 칸 표시와 콘솔 탭이 같이 쓴다.
 * @returns 바꿨으면 true
 */
async function askFacilityLevel(fac, currentLevel) {
  const rules = await mm.knowledge.rules();
  const a = rules.altering;

  const opts = [{ value: 0, label: '모름 (지정 안 함)' }];
  for (let lv = 1; lv <= a.maxLevel; lv++) {
    const slots = a.slotsByLevel[lv] || a.slotsByLevel[String(lv)];
    opts.push({ value: lv, label: '레벨 ' + lv + ' — ' + slots + '칸' });
  }

  const picked = await promptSelect('시설 레벨', fac + ' 의 레벨을 골라 주세요',
    opts, currentLevel || 0,
    '게임에서 시설 레벨을 확인하고 골라 주세요. 칸 수는 레벨에 따라 정해집니다.' +
    (rules.fallback ? ' (game-rules.json 을 읽지 못해 기본 표로 보여 주는 중입니다)' : ''));
  if (picked === null) return false;

  const lv = parseInt(picked, 10);
  await mm.knowledge.setLevel(fac, lv);
  toast('저장했습니다', lv >= 1 ? fac + ' → 레벨 ' + lv : fac + ' 레벨 지정을 지웠습니다', 'ok');
  return true;
}

/* ── 페이저 ─────────────────────────────────────── */

/**
 * 표를 쪽 단위로 끊어 보여준다.
 *
 * 제작 레시피가 1,800건이 넘는다. 전부 그리면 느리고, 앞 400건만 그리고 마는 것은
 * **이름을 모르는 레시피를 영영 못 보게 만든다.** 검색은 아는 것을 찾을 때나 쓸모가 있다.
 *
 * 쪽 번호는 표마다 따로 기억하고, 검색어나 필터가 바뀌면 1쪽으로 되돌린다.
 * 목록이 줄어 현재 쪽이 사라졌을 때도 마지막 쪽으로 당겨 준다 — 빈 화면을 보여주지 않는다.
 */
const PAGE_SIZES = [50, 100, 200, 500];
const pageState = {};   // 표 이름 → { page, per }

function pageOf(key) {
  if (!pageState[key]) pageState[key] = { page: 1, per: 100 };
  return pageState[key];
}

/** 검색·필터가 바뀌면 1쪽으로. 3쪽을 보다 검색하면 결과가 없는 것처럼 보인다. */
function resetPage(key) {
  pageOf(key).page = 1;
}

/**
 * 이번 쪽에 보일 부분만 잘라 낸다.
 * 쪽 번호가 범위를 벗어나 있으면 여기서 바로잡는다.
 */
function paged(key, rows) {
  const st = pageOf(key);
  const pages = Math.max(1, Math.ceil(rows.length / st.per));
  if (st.page > pages) st.page = pages;
  if (st.page < 1) st.page = 1;
  const from = (st.page - 1) * st.per;
  return { rows: rows.slice(from, from + st.per), from: from, pages: pages, page: st.page, per: st.per };
}

/** 페이저 막대. 표 아래에 붙인다. */
function pagerHtml(key, p, total) {
  if (!total) return '';
  const btn = (to, label, on, title) =>
    '<button class="btn btn-tiny" data-pg="' + key + ':' + to + '"' +
    (on ? '' : ' disabled') + (title ? ' title="' + esc(title) + '"' : '') + '>' + label + '</button>';

  const first = p.page > 1, last = p.page < p.pages;
  const to = Math.min(total, p.from + p.rows.length);

  const per = '<select data-pg-per="' + key + '" title="한 쪽에 보일 줄 수">' +
    PAGE_SIZES.map((n) => '<option value="' + n + '"' + (n === p.per ? ' selected' : '') + '>' + n + '줄</option>').join('') +
    '</select>';

  // 한 쪽뿐이면 넘길 곳이 없다. 죽은 버튼 넷을 늘어놓지 않는다.
  if (p.pages <= 1) {
    return '<div class="pager"><span class="at">' + num(total) + '건</span>' +
      '<span class="gap"></span>' + per + '</div>';
  }

  return '<div class="pager">' +
    btn(1, '«', first, '첫 쪽') +
    btn(p.page - 1, '‹ 이전', first) +
    '<span class="at"><b>' + p.page + '</b> / ' + p.pages + ' 쪽' +
      ' <span class="muted">(' + num(p.from + 1) + '–' + num(to) + ' / ' + num(total) + ')</span></span>' +
    btn(p.page + 1, '다음 ›', last) +
    btn(p.pages, '»', last, '마지막 쪽') +
    '<span class="gap"></span>' +
    '<input class="jump" type="text" inputmode="numeric" data-pg-jump="' + key + '" ' +
      'value="' + p.page + '" title="쪽 번호를 입력하고 Enter">' +
    per +
    '</div>';
}

/** 표 바로 아래에 페이저를 놓는다 (없으면 만들고, 있으면 갈아 끼운다). */
function paintPager(tableId, key, p, total) {
  const wrap = $('#' + tableId).closest('.tablewrap');
  let bar = wrap.nextElementSibling;
  if (!bar || !bar.classList.contains('pager-slot')) {
    bar = document.createElement('div');
    bar.className = 'pager-slot';
    wrap.parentNode.insertBefore(bar, wrap.nextSibling);
  }
  bar.innerHTML = pagerHtml(key, p, total);
}

/** 페이저 클릭·입력을 한곳에서 받는다. 표마다 따로 붙이면 금방 어긋난다. */
function wirePager(onChange) {
  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-pg]');
    if (!t || t.disabled) return;
    const [key, to] = t.dataset.pg.split(':');
    pageOf(key).page = parseInt(to, 10);
    onChange(key);
  });

  document.addEventListener('change', (e) => {
    const sel = e.target.closest('[data-pg-per]');
    if (!sel) return;
    const key = sel.dataset.pgPer;
    const st = pageOf(key);
    // 보던 줄이 화면에서 사라지지 않도록, 줄 수를 바꿔도 같은 위치를 유지한다
    const anchor = (st.page - 1) * st.per;
    st.per = parseInt(sel.value, 10);
    st.page = Math.floor(anchor / st.per) + 1;
    onChange(key);
  });

  document.addEventListener('keydown', (e) => {
    const inp = e.target.closest('[data-pg-jump]');
    if (!inp || e.key !== 'Enter') return;
    const n = parseInt(inp.value.replace(/[^0-9]/g, ''), 10);
    if (!n) { inp.value = pageOf(inp.dataset.pgJump).page; return; }
    pageOf(inp.dataset.pgJump).page = n;
    onChange(inp.dataset.pgJump);
  });
}

/** 페이저가 쪽을 바꿨을 때 다시 그릴 표 */
const PAGE_RENDER = {
  craft: () => renderCraft(),
  alter: () => renderAlter(),
  items: () => renderItems(),
  // 아래 둘은 페이저가 없지만 정렬이 바뀌면 다시 그려야 한다
  gather: () => renderGather(),
  instrument: () => renderInstruments(),
  music: () => renderMusic(),
  facial: () => renderSocial(),
  behaviour: () => renderSocial(),
};

/* ── 제작 ───────────────────────────────────────── */

/**
 * 게임 이름에 섞인 <color=…> 를 살려서 그린다.
 *
 * 임의 HTML을 넣지 않는다 — 메인이 쪼개 준 {text,color} 조각만 쓰고 텍스트는 이스케이프한다.
 * 색은 인라인 style로 줄 수 없다. CSP의 style-src 'self'가 style= 속성을 막기 때문이다
 * (span은 그려지는데 색만 사라진다). 그래서 CSSOM insertRule로 색상별 클래스를 만들어 쓴다.
 * insertRule은 문자열 파싱이 아니라 스크립트 호출이라 CSP에 걸리지 않는다.
 */
const SAFE_COLOR = /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$/;
const colorClasses = new Map();

function colorClass(color) {
  if (!SAFE_COLOR.test(color)) return null;
  const key = color.toLowerCase();
  if (colorClasses.has(key)) return colorClasses.get(key);

  const cls = 'gc-' + key.replace(/[^0-9a-z]/g, '');
  let ok = null;
  try {
    const sheet = document.styleSheets[0];
    sheet.insertRule('.' + cls + '{color:' + color + '}', sheet.cssRules.length);
    ok = cls;
  } catch (_) {
    ok = null; // 등록 실패하면 색 없이 글자만 보여준다
  }
  colorClasses.set(key, ok);
  return ok;
}

/** 같은 방식으로 배경색 클래스도 만든다. 염색 탭의 색 견본이 쓴다. */
const bgClasses = new Map();
function bgClass(color) {
  if (!SAFE_COLOR.test(color)) return '';
  const key = color.toLowerCase();
  if (bgClasses.has(key)) return bgClasses.get(key);
  const cls = 'gb-' + key.replace(/[^0-9a-z]/g, '');
  let ok = '';
  try {
    const sheet = document.styleSheets[0];
    sheet.insertRule('.' + cls + '{background:' + color + '}', sheet.cssRules.length);
    ok = cls;
  } catch (_) { ok = ''; }
  bgClasses.set(key, ok);
  return ok;
}

/** 테두리색도 마찬가지. 염색 칸의 색 네모가 제 번호 색을 두르는 데 쓴다. */
const lineClasses = new Map();
function lineClass(color) {
  if (!SAFE_COLOR.test(color)) return '';
  const key = color.toLowerCase();
  if (lineClasses.has(key)) return lineClasses.get(key);
  const cls = 'ln-' + key.replace(/[^0-9a-z]/g, '');
  let ok = '';
  try {
    const sheet = document.styleSheets[0];
    sheet.insertRule('.' + cls + '{border-color:' + color + '}', sheet.cssRules.length);
    ok = cls;
  } catch (_) { ok = ''; }
  lineClasses.set(key, ok);
  return ok;
}

/** 진행바 폭도 인라인 style을 쓸 수 없어 클래스로 만든다. 0~100 정수 퍼센트. */
function widthClass(pct) {
  const n = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
  const key = 'w' + n;
  if (!colorClasses.has(key)) {
    let ok = null;
    try {
      const sheet = document.styleSheets[0];
      sheet.insertRule('.gw-' + n + '{width:' + n + '%}', sheet.cssRules.length);
      ok = 'gw-' + n;
    } catch (_) { ok = null; }
    colorClasses.set(key, ok);
  }
  return colorClasses.get(key) || '';
}

function richName(item) {
  if (!item || !item.seg) return esc(item && item.name);
  return item.seg.map((p) => {
    const t = esc(p.text);
    if (!p.color) return t;
    const cls = colorClass(p.color);
    return cls ? '<span class="' + cls + '">' + t + '</span>' : t;
  }).join('');
}

/**
 * 재료 칸.
 * missing에는 보관함까지 합쳐 "진짜 모자란 것"만 들어 있다.
 * covered는 가방엔 없지만 보관함 재고로 충당되는 것 — 부족으로 오해하지 않게 따로 보여준다.
 */
function ingredientCell(x, okText) {
  if (x.ok) return okText + ' <span class="muted">(1회 기준)</span>';
  const parts = [];
  if (x.missing && x.missing.length) parts.push(esc(x.missing.slice(0, 4).join(', ')));
  else if (x.reason) parts.push(esc(x.reason));
  if (x.covered && x.covered.length) {
    parts.push('<span class="muted">· 보관함에서 충당: ' + esc(x.covered.slice(0, 3).join(', ')) + '</span>');
  }
  return parts.join(' ');
}

let craftCache = null;

async function loadCraft(refresh) {
  const r = await mm.query('craft', { refresh: !!refresh, detail: true });
  if (r.error) { toast('제작 목록 조회 실패', r.message || r.error, 'bad'); return; }
  craftCache = r;
  renderCraft();
}

function renderCraft() {
  if (!craftCache) return;
  const q = $('#craft-search').value.trim();
  const onlyOk = $('#craft-only-ok').checked;

  let rows = craftCache.items;
  if (onlyOk) rows = rows.filter((x) => x.ok);
  if (q) {
    const n = q.toLowerCase().replace(/\s+/g, '');
    rows = rows.filter((x) => x.name.toLowerCase().replace(/\s+/g, '').includes(n));
  }

  $('#craft-count').textContent =
    '전체 ' + craftCache.total + ' · 가능 ' + craftCache.craftable + ' · 조건에 맞는 것 ' + rows.length;

  const row = (x) =>
    '<tr>' +
    '<td class="' + (x.ok ? 'mark-ok' : 'mark-bad') + '">' + (x.ok ? '✔' : '✘') + '</td>' +
    '<td>' + starBtn('craft', x) + richName(x) + '</td>' +
    '<td class="num">' + x.per + '</td>' +
    '<td class="sub">' + ingredientCell(x, '제작 가능') + '</td>' +
    '<td>' + (x.ok
        ? '<button class="btn btn-tiny btn-primary" data-craft="' + esc(x.nameRaw || x.name) + '" data-per="' + x.per + '">제작</button> '
        : '') +
    '<button class="btn btn-tiny" data-plan="' + esc(x.nameRaw || x.name) + '" data-plan-label="' + esc(x.name) + '">목표</button>' +
    '</td>' +
    '</tr>';

  const body = favTableBody('craft', sortRows('craft', rows), 5, row);
  $('#craft-table tbody').innerHTML = body.html;
  paintPager('craft-table', 'craft', body.pg, body.rest);
}

async function doCraft(name, per) {
  // 게임은 제작 가능한 레시피의 재료 목록을 주지 않는다. 그래서 N회분 재료가
  // 충분한지 미리 알 수 없다 — 이 사실을 숨기지 말고 그대로 알린다.
  const times = await promptNumber(
    '제작 횟수',
    '"' + name + '" 를 몇 회 제작할까요?',
    1,
    '1회당 ' + per + '개가 나옵니다. 목록의 ✔는 1회 기준이라, 여러 회분 재료가 되는지는 미리 알 수 없습니다. ' +
    '재료나 상한이 모자라면 시작 전에 거부되고 정령의 날개는 소모되지 않습니다.'
  );
  if (!times) return;
  await runAction('execute_crafting', { displayName: name, craftCount: times },
    { label: name + ' 제작 x' + times, times: 1,
      note: '이동 → 제작 → 결과 수령까지 한 번에 진행되며, 몇 분 걸릴 수 있습니다. ' +
            'craftCount가 몇이든 호출은 1회라 날개는 5만 듭니다.' });
  loadCraft(true);
}


/* ── 목표 걸기 ──────────────────────────────────── */

/**
 * 목표를 물어보고 바로 작업 큐에 넣는다.
 *
 * 전에는 화면 위쪽에 재료 표가 달린 큰 계획 카드를 펼치고, 거기서 "자동 진행"을 한 번 더
 * 눌러야 큐로 들어갔다. 큐가 생긴 뒤로는 그 카드가 하는 일이 큐 카드와 겹친다 —
 * 게다가 목표를 두 개 걸려면 카드를 닫고 다시 여는 수밖에 없었다.
 *
 * 지금은 수량만 묻고 곧장 큐에 담는다. **담는 것 자체는 공짜다.** 날개가 나가는 것은
 * 재생을 누른 뒤부터라, 담기 전에 비용을 확인시킬 이유도 없다. 예상 비용과 막힌 이유는
 * 담은 뒤 카드에 채워 넣는다.
 */
/**
 * 사슬 끝까지 세운 계획을 사람이 읽게 편다.
 *
 * 여기서 보여 주는 값은 전부 **무료 조회**로 나온 것이다. 날개는 한 개도 안 썼다.
 * 그래서 담기 전에 "그래서 뭘 얼마나 캐야 하나"를 미리 보여 줄 수 있다.
 */
function needsHtml(p) {
  const dur = (s) => s == null ? '?' :
    s >= 3600 ? Math.floor(s / 3600) + '시간' + (s % 3600 ? ' ' + Math.round((s % 3600) / 60) + '분' : '') :
    s >= 60 ? Math.round(s / 60) + '분' : s + '초';
  const out = [];

  if (p.blocked && p.blocked.length) {
    out.push('<p class="mark-warn">시설 레벨이 모자랍니다 — ' +
      p.blocked.map((b) => esc(b.product) + ' ' + esc(b.facility.replace(' 가공 시설', '')) +
        ' Lv.' + b.needLevel + ' (지금 ' + (b.haveLevel == null ? '모름' : 'Lv.' + b.haveLevel) + ')').join(', ') + '</p>');
  }

  if (p.gather && p.gather.length) {
    const calls = p.gather.reduce((a, g) => a + g.calls, 0);
    out.push('<h4 class="mt10">먼저 캘 것 <small>' + calls + '번 호출</small></h4>');
    out.push('<div class="tablewrap"><table><thead><tr><th>재료</th><th class="num">필요</th>' +
      '<th class="num">가진 것</th><th class="num">캘 횟수</th></tr></thead><tbody>' +
      p.gather.map((g) => '<tr><td>' + esc(g.name) + '</td><td class="num">' + g.need +
        '</td><td class="num">' + g.have + '</td><td class="num">' + g.calls + '</td></tr>').join('') +
      '</tbody></table></div>');
  } else {
    out.push('<p class="mark-ok mt10">캘 것 없음 — 지금 가진 것으로 됩니다.</p>');
  }

  if (p.missing && p.missing.length) {
    out.push('<p class="mark-warn">채집으로도 못 구하는 것 — ' +
      p.missing.map((m) => esc(m.name) + ' ' + m.need).join(', ') + '</p>');
  }

  if (p.steps && p.steps.length) {
    out.push('<h4 class="mt10">가공 차례 <small>' + p.totalRuns + '회</small></h4>');
    out.push('<ol class="plan-steps">' + p.steps.map((s) =>
      '<li>' + esc(s.recipe) + ' <b>x' + s.runs + '</b> <span class="muted">' +
      esc(s.facility.replace(' 가공 시설', '')) + ' Lv.' + s.level + ' · ' + dur(s.sec) + '</span>' +
      (s.ambiguous ? ' <span class="muted">갈래 둘 · 첫 줄</span>' : '') + '</li>').join('') + '</ol>');
  }

  const t = p.time || {};
  out.push('<p class="hint">가공에 걸리는 시간 — 한 칸으로 줄줄이 돌리면 ' + dur(t.serial) +
    (t.parallel != null ? ', 칸을 나눠 쓰면 대략 ' + dur(t.parallel) : '') + '</p>');

  if (p.ambiguous && p.ambiguous.length) {
    out.push('<p class="hint"><b>갈래 둘 · 첫 줄</b>로 표시된 것은 게임이 두 조합을 ' +
      '<b>같은 이름</b>으로 내놓는 레시피입니다. 시키면 언제나 <b>낮은 레벨 쪽</b>이 도는 것을 ' +
      '확인했으므로, 계획도 그쪽으로 세웠습니다 — ' + p.ambiguous.map(esc).join(', ') + '</p>');
  }
  return out.join('');
}

async function makePlan(name, label) {
  const target = await promptNumber(
    '목표 수량',
    '"' + (label || name) + '" 를 몇 개 새로 만들까요?',
    100,
    '지금 갖고 있는 것과 무관하게, 여기 적은 만큼 새로 만듭니다. ' +
      '작업 큐에 담기만 하고, 재생을 눌러야 실제로 진행합니다.'
  );
  if (!target) return;

  // 가공 재료표에 있는 것이면 사슬 끝까지 미리 보여 준다. 전부 무료 조회라 공짜다.
  //
  // 표는 **산출물 이름**으로 적혀 있고 게임은 "철괴(광석)" 처럼 재료를 괄호로 붙여
  // 부른다. 어느 쪽인지 미리 알 수 없으므로 둘 다 넣어 보고 되는 쪽을 쓴다.
  say('필요량 계산 중…');
  let deep = null;
  const bare = String(name).replace(/<[^>]*>/g, '').trim();
  const par = /^(.*?)\s*\((.+)\)$/.exec(bare);
  for (const cand of [bare, par && par[1].trim()]) {
    if (!cand) continue;
    try { deep = await mm.planNeeds(cand, target, { refresh: true }); } catch (_) { deep = null; }
    if (deep && deep.ok) break;
    deep = null;
  }
  if (deep) {
    const go = await confirmModal(
      esc(label || name) + ' ' + target + '개 — 필요량',
      needsHtml(deep),
      '작업 큐에 담기');
    if (!go) { say('준비됨'); return; }
  }

  say('확인 중…');
  let p = null;
  try { p = await mm.planCraft(name, target, { refresh: true }); }
  catch (err) { toast('목표를 걸 수 없습니다', err.message, 'bad'); return; }

  if (p.error) {
    toast('목표를 걸 수 없습니다',
      p.error === 'not_found'
        ? '이 이름으로는 제작·가공·채집 어느 목록에서도 찾지 못했습니다.'
        : (p.message || p.error), 'bad');
    say('준비됨');
    return;
  }

  // 가공만 레시피 이름과 산출물 이름이 다르다. 큐는 산출물 기준으로 판단한다.
  const it = qAdd({
    via: p.kind === 'alter' ? '가공' : p.kind === 'gather' ? '채집' : '제작',
    name: p.product || p.name,
    label: p.productName || p.displayName,
    recipe: (p.product && p.product !== p.name) ? p.displayName : '',
    target: target,
    per: p.producedPerCraft,
    runs: p.runs,
    startHave: p.have,
  });
  say('준비됨');

  // 자동으로 못 구하는 재료는 지금 바로 알 수 있다. 비용 계산이 끝난 뒤에도 남겨 둔다.
  const blocked = (p.blockers && p.blockers.length)
    ? '직접 구해야 함 — ' + p.blockers.map((x) => x.displayName + ' ' + num(x.lack) + '개').join(', ')
    : '';
  qEstimate(it, blocked);
}

/**
 * 담은 뒤에 예상 비용과 막힌 이유를 채운다.
 *
 * 조회만 하므로 공짜지만 몇 초가 걸린다. 그동안 카드는 이미 목록에 있고, 계산이 끝나면
 * 조용히 값이 채워진다. 담는 순간 몇 초 멈춰 세우는 것보다 낫다.
 */
async function qEstimate(it, keepNote) {
  const fallback = keepNote || '';
  qNote(it, '예상 비용 계산 중…');
  try {
    const r = await mm.goal.next(it.name, (it.startHave || 0) + it.target);
    if (!qItems.includes(it)) return;         // 그새 지워졌다
    if (r.error) { qNote(it, fallback); return; }
    it.wings = r.estimate ? r.estimate.wings : 0;
    it.partial = !!(r.estimate && r.estimate.partial);
    qNote(it, r.step && r.step.kind === 'blocked'
      ? '막힘 — ' + (r.step.message || r.step.reason || '')
      : fallback);
    saveQueue();
  } catch (_) { qNote(it, fallback); }
}
/* ── 가공 ───────────────────────────────────────── */

let alterCache = null;
/** 칸이 꽉 찬 가공 시설. 여기에 등록하면 날개만 날아간다. */
let fullFacilities = new Set();
let itemFacility = {};


/**
 * 접었을 때 보이는 한 줄 요약.
 *
 * 칸을 다 그리면 여섯 줄이다. 레시피를 훑는 동안에는 "어디에 자리가 남았나"만 알면 되므로,
 * 접힌 상태에서는 시설별 사용/전체만 칩으로 늘어놓는다.
 */
function facilityMiniHtml(w) {
  const rooms = (w.room || []).slice().sort((a, b) => a.facility.localeCompare(b.facility, 'ko'));
  if (!rooms.length) return '';
  return '<div class="fac-mini">' + rooms.map((r) => {
    const full = r.used >= r.slots;
    return '<span class="chip' + (full ? ' chip-full' : '') + '">' +
      esc(r.facility.replace(' 가공 시설', '')) +
      ' <b>' + r.used + '/' + r.slots + '</b></span>';
  }).join('') + '</div>';
}

/** 접힘 상태를 화면에 반영한다. 값은 설정에 남아 다음에 켤 때도 그대로다. */
function applyWorksFold() {
  const card = $('#alter-works-card');
  if (!card) return;
  card.classList.toggle('folded', !!worksFolded);
  const btn = $('#alter-works-fold');
  // 세모는 **내용이 있는 쪽**을 가리킨다. 접혀 있으면 아래로 펴진다는 뜻에서 ▾,
  // 펼쳐져 있으면 위로 접힌다는 뜻에서 ▴. (작업 큐의 ◂ ▸ 와 같은 규칙, 축만 다르다)
  if (btn) { btn.textContent = worksFolded ? '▾' : '▴'; btn.title = worksFolded ? '펼치기' : '접기'; }
}

let worksFolded = false;

/**
 * 접고 펴는 **동안만** 본문 폭을 붙들어 둔다.
 *
 * 큐 폭은 렌더러가 바로 바꾸지만 창 폭은 메인에 부탁해야 해서 한 박자 늦다. 게다가
 * 실측해 보니 **창 쪽이 먼저 반영된다** — 그 한 프레임 동안 본문이 남는 자리를 다
 * 차지했다가 되돌아와, 화면이 쭉 늘어났다 줄어드는 것처럼 보였다.
 *
 *   접기   본문 714 → 972      펴기   본문 1230 → 972
 *
 * 본문을 원래 폭에 못 박아 두면 어느 쪽이 먼저 오든 글이 흐르지 않는다. 대신 그 사이
 * 큐 옆에 잠깐 빈 자리가 생기거나 큐가 살짝 삐져나오는데, 배경색이 같아 거의 안 보인다.
 *
 * CSP 때문에 인라인 style 을 못 써서, 규칙을 하나 넣어 두고 그 폭만 고쳐 쓴다.
 */
let contentPin = null;
function pinContent(px) {
  if (!contentPin) {
    try {
      const sheet = document.styleSheets[0];
      const i = sheet.insertRule('#content.pinned{flex:none;width:0}', sheet.cssRules.length);
      contentPin = sheet.cssRules[i];
    } catch (_) { return false; }
  }
  contentPin.style.width = Math.round(px) + 'px';
  $('#content').classList.add('pinned');
  return true;
}

function unpinContent() { $('#content').classList.remove('pinned'); }

/** 펼쳤을 때의 큐 폭. CSS 가 정한 값을 그대로 읽는다. */
function queueWideWidth() {
  const v = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--queue-w'), 10);
  return v > 0 ? v : 292;
}

/** 작업 큐를 접고 편다. 접으면 세로 라벨만 남기고 34px 로 줄인다. */
function applyQueueFold() {
  const box = $('#queue');
  if (!box) return;
  box.classList.toggle('folded', !!queueFolded);
  const btn = $('#q-fold');
  // 세모는 **창이 움직이는 쪽**을 가리킨다. 접으면 오른쪽 끝이 왼쪽으로 당겨지므로 ◂,
  // 펼치면 오른쪽으로 다시 나가므로 ▸. (홑화살괄호 ‹ › 는 가늘어서 단추 안에서 안 보였다.)
  if (btn) { btn.textContent = queueFolded ? '▸' : '◂'; btn.title = queueFolded ? '펼치기' : '접기'; }
}
let queueFolded = false;

/**
 * 시설별 슬롯 줄.
 *
 * 게임에서 가공 시설이 슬롯으로 보이니 여기서도 같은 모양으로 그린다.
 * "4/7" 같은 숫자보다 칸이 몇 개 비었는지가 한눈에 들어오고,
 * 무엇을 걸어 뒀는지 확인하러 게임을 켤 일도 줄어든다.
 *
 * 칸 순서는 완료 → 진행 중 → 빈칸이다. 게임의 실제 배치와 같다는 보장은 없지만,
 * 수령할 것이 왼쪽에 모여 있는 편이 읽기 쉽다.
 */
function facilitySlotsHtml(w) {
  const rooms = (w.room || []).slice().sort((a, b) => a.facility.localeCompare(b.facility, 'ko'));
  if (!rooms.length) return '<p class="muted">가공 시설 정보가 없습니다.</p>';

  const worksOf = (fac) => (w.facilities || []).find((f) => f.facility === fac) || { completed: [], inProgress: [] };

  return '<div class="fac-list">' + rooms.map((r) => {
    const f = worksOf(r.facility);
    const cells = [];

    // 칸에는 **이름만** 넣는다. 62x28 짜리 칸에 남은 시간까지 밀어 넣었더니 정작
    // 무엇이 가공 중인지가 몇 글자 만에 잘렸다. 시간과 상태는 마우스를 올리면 나온다.
    // 완료인지 진행 중인지는 칸의 바탕색과 테두리로 이미 구분된다.
    for (const x of f.completed) {
      cells.push('<span class="slot slot-done" title="' + esc(x.name + ' — 완료, 수령 대기') + '">' +
        '<em>' + esc(x.name) + '</em></span>');
    }
    for (const x of f.inProgress) {
      cells.push('<span class="slot slot-busy" title="' + esc(x.name + ' — ' + dur(x.remainingSec) + ' 남음') + '">' +
        '<em>' + esc(x.name) + '</em></span>');
    }
    for (let i = cells.length; i < r.slots; i++) {
      cells.push('<span class="slot slot-free" title="빈 칸"></span>');
    }
    // 레벨을 실제보다 낮게 잡아 둔 경우, 칸보다 작업이 많을 수 있다
    const over = cells.length > r.slots ? cells.length - r.slots : 0;

    return '<div class="fac">' +
      '<span class="fac-name">' + esc(r.facility.replace(' 가공 시설', '')) +
        // 칸 수는 레벨에서 나온다. 그 칸들 바로 옆에서 고칠 수 있어야 찾기 쉽다.
        // 직접 고른 값인지 앱이 유추한 값인지 구분해, 유추한 쪽에는 ? 를 붙인다.
        '<button class="chip-lv' + (r.levelSet ? '' : ' chip-lv-unset') + '" ' +
          'data-room-level="' + esc(r.facility) + '" data-room-lv="' + (r.levelSet ? r.level : 0) + '" ' +
          'title="' + esc(r.levelSet
            ? '레벨 ' + r.level + ' (직접 지정) — 눌러서 바꾸기'
            : '레벨을 아직 정하지 않았습니다. 지금은 ' + r.slots + '칸으로 보고 있습니다 — 눌러서 지정') + '">' +
          'Lv' + (r.level || '?') + (r.levelSet ? '' : '?') + '</button>' +
      '</span>' +
      '<span class="slots">' + cells.join('') + '</span>' +
      (over ? '<span class="sub mark-warn">+' + over + '</span>' : '') +
      (f.completed.length
        ? '<button class="btn btn-tiny btn-primary" data-collect="' + esc(f.completed[0].name) + '">수령</button>'
        : '') +
      '</div>';
  }).join('') + '</div>';
}

/**
 * 정해 둔 레벨이 실제와 어긋나는지 본다.
 *
 * 칸에 올라가 있는 작업 수가 그 레벨의 칸 수보다 많으면, 정해 둔 값이 틀린 것이다.
 * 작업 수는 게임이 준 사실이라 이 판단에는 의심의 여지가 없다.
 *
 * 그래도 **마음대로 고치지는 않는다.** 레벨을 낮게 잡아 두는 것은 "여기까지만 맡기겠다"는
 * 뜻일 수 있어서, 앱이 임의로 올리면 그 의도를 깨뜨린다. 그래서 물어본다.
 *
 * 탭에 들어올 때마다 묻지 않도록, 사용자가 "다시 묻지 않기"를 고르면 설정에 남긴다.
 */
let mismatchAsking = false;

async function checkLevelMismatch(w) {
  if (mismatchAsking) return;

  const bad = (w.room || []).filter((r) => r.levelSet && r.used > r.slots);
  if (!bad.length) return;

  let cfg = null;
  try { cfg = await mm.cfg.get(); } catch (_) { return; }
  if (cfg && cfg.askFacilityLevelMismatch === false) return;

  let rules = null;
  try { rules = await mm.knowledge.rules(); } catch (_) { return; }
  const a = rules.altering;

  // 지금 올라가 있는 개수를 담을 수 있는 가장 낮은 레벨
  const levelFor = (used) => {
    for (let lv = 1; lv <= a.maxLevel; lv++) {
      const slots = a.slotsByLevel[lv] || a.slotsByLevel[String(lv)];
      if (slots >= used) return { level: lv, slots: slots };
    }
    const top = a.slotsByLevel[a.maxLevel] || a.slotsByLevel[String(a.maxLevel)];
    return { level: a.maxLevel, slots: top };
  };

  const rows = bad.map((r) => Object.assign({ room: r }, levelFor(r.used)));

  mismatchAsking = true;
  const ok = await confirmModal('시설 레벨이 실제와 다릅니다',
    '<p>정해 두신 레벨보다 <b>더 많은 작업이 올라가 있습니다.</b> 실제 레벨이 더 높은 것 같습니다.</p>' +
    '<div class="tablewrap"><table><thead><tr>' +
    '<th>시설</th><th class="w-sm num">지금 작업</th><th class="w-sm num">설정</th><th class="w-sm num">맞춰 보면</th>' +
    '</tr></thead><tbody>' +
    rows.map((x) =>
      '<tr><td>' + esc(x.room.facility) + '</td>' +
      '<td class="num">' + x.room.used + '건</td>' +
      '<td class="num muted">Lv' + x.room.level + ' (' + x.room.slots + '칸)</td>' +
      '<td class="num mark-ok">Lv' + x.level + ' (' + x.slots + '칸)</td></tr>').join('') +
    '</tbody></table></div>' +
    '<p class="hint">맞춰 보면 값은 지금 올라가 있는 작업 수를 담을 수 있는 <b>가장 낮은 레벨</b>입니다. ' +
    '실제 레벨은 그보다 높을 수 있고, 그건 칸이 더 찰 때 드러납니다.<br>' +
    '<b>아니오</b>를 고르면 지금 설정을 그대로 둡니다 — 일부러 낮게 잡아 두신 것이라면 그대로가 맞습니다.</p>' +
    '<label class="chk mt10"><input type="checkbox" id="mismatch-dontask"> 다시 묻지 않기</label>',
    '맞춰 주세요');

  // 모달을 닫아도 내용은 남아 있어 체크 상태를 읽을 수 있다
  let dontAsk = false;
  try { dontAsk = !!($('#mismatch-dontask') || {}).checked; } catch (_) {}
  mismatchAsking = false;

  if (dontAsk) {
    try { await mm.cfg.set('askFacilityLevelMismatch', false); } catch (_) {}
    toast('다시 묻지 않습니다', '나중에 옵션에서 되돌릴 수 있습니다.', 'ok');
  }
  if (!ok) return;

  for (const x of rows) {
    try { await mm.knowledge.setLevel(x.room.facility, x.level); } catch (_) {}
  }
  toast('레벨을 맞췄습니다',
    rows.map((x) => x.room.facility.replace(' 가공 시설', '') + ' Lv' + x.level).join(' · '), 'ok');
  loadAlter(true);
}

async function loadAlter(refresh) {
  // 표를 그리기 전에 아이템↔시설 매핑을 먼저 받아야 한다.
  // 이게 있어야 "채우기" 버튼을 붙일지, 칸이 꽉 찬 시설을 막을지 판단할 수 있다.
  const [r, w, kn] = await Promise.all([
    mm.query('alter', { refresh: !!refresh }),
    mm.query('alteringWorks', { refresh: true }),
    mm.knowledge.get().catch(() => null),
  ]);
  if (kn) itemFacility = kn.itemFacility || {};
  if (!r.error) alterCache = r;

  if (w.error) {
    // 작업 큐를 못 읽어도 가공 목록 자체는 보여 준다.
    fullFacilities = new Set();
    renderAlter();
    $('#alter-works').innerHTML = '<span class="muted">조회 실패</span>';
    return;
  }

  // 칸이 꽉 찬 시설에 등록하면 이동까지 진행된 뒤 막혀서 날개 5가 그냥 나간다(실측).
  // 그래서 여유 칸을 먼저 보여 주고, 없는 시설은 버튼 자체를 막는다.
  fullFacilities = new Set((w.room || []).filter((r) => r.free <= 0).map((r) => r.facility));
  // 게임의 가공 시설이 슬롯으로 보이므로 여기서도 칸을 그대로 그린다.
  // 몇 칸을 쓰는지, 무엇이 들어 있는지, 어느 것이 다 됐는지를 숫자가 아니라 모양으로 본다.
  // 개수와 수령 버튼은 머리말 줄로 올린다. 시설 칸만으로도 세로가 충분히 길어서,
  // 그 아래에 줄을 더 붙이면 정작 봐야 할 레시피 표가 화면 밖으로 밀린다.
  $('#alter-works-count').textContent = '완료 ' + w.completedCount + ' · 진행 중 ' + w.inProgressCount;
  $('#alter-works-act').innerHTML = w.completedCount > 0
    ? '<button class="btn btn-tiny btn-primary" id="collect-all">완료분 전체 수령 (' +
      (w.facilities || []).filter((f) => f.completed.length).length + '개 시설)</button>'
    : '';

  $('#alter-works').innerHTML =
    facilityMiniHtml(w) +
    facilitySlotsHtml(w) +
    (w.completedCount > 0
      ? '<p class="hint">완료된 작업도 칸을 차지합니다. 꽉 찬 시설에 등록하면 정령의 날개 5가 그냥 나가니 먼저 수령하세요 — 수령은 무료입니다.</p>'
      : '');

  applyWorksFold();

  paintAlterFacilities();
  paintAlterLevels();
  checkLevelMismatch(w);

  // 표는 itemFacility · fullFacilities 가 모두 정해진 뒤에 그려야 한다.
  // 먼저 그리면 "채우기" 버튼이 하나도 안 붙는다.
  renderAlter();
}

/**
 * 시설 드롭다운을 채운다.
 * 목록에 실제로 나오는 시설만 넣는다 — 게임이 안 주는 시설을 선택지에 두면 빈 결과만 나온다.
 */
function paintAlterFacilities() {
  const sel = $('#alter-facility');
  if (!sel || !alterCache) return;
  const cur = sel.value;
  const count = {};
  for (const x of alterCache.items) if (x.facility) count[x.facility] = (count[x.facility] || 0) + 1;
  const names = Object.keys(count).sort((a, b) => a.localeCompare(b, 'ko'));

  sel.innerHTML = '<option value="">모든 시설</option>' +
    names.map((f) =>
      '<option value="' + esc(f) + '">' + esc(f.replace(' 가공 시설', '')) + ' (' + count[f] + ')</option>').join('');
  if (names.indexOf(cur) !== -1) sel.value = cur;
}

/**
 * 필요 시설 레벨로 고르는 칸을 채운다.
 *
 * 레벨은 게임이 알려주지 않아 가공 재료표에서 온다. 표에 없는 레시피는 레벨을 모르므로
 * 따로 묶어 둔다 — 안 보이게 숨기면 "없어진 줄" 알게 된다.
 */
function paintAlterLevels() {
  const sel = $('#alter-level');
  if (!sel || !alterCache) return;
  const cur = sel.value;
  const count = {};
  let unknown = 0;
  for (const x of alterCache.items) {
    if (x.level == null) unknown++;
    else count[x.level] = (count[x.level] || 0) + 1;
  }
  const lv = Object.keys(count).map(Number).sort((a, b) => a - b);
  sel.innerHTML = '<option value="">모든 레벨</option>' +
    lv.map((n) => '<option value="' + n + '">Lv.' + n + ' (' + count[n] + ')</option>').join('') +
    (unknown ? '<option value="?">레벨 모름 (' + unknown + ')</option>' : '');
  // 고른 값이 사라졌으면 모든 레벨로 돌아간다
  sel.value = [...sel.options].some((o) => o.value === cur) ? cur : '';
}

/**
 * 이름 옆에 붙는 꼬리표 — 필요한 시설 레벨.
 *
 * 은합금괴처럼 **이름이 똑같은 줄이 둘** 오는 레시피가 있다. 레벨이 다르므로 이것만
 * 붙여도 어느 쪽인지 갈린다. 걸리는 시간은 칸을 따로 두었다 — 이름 뒤에 둘 다 달면
 * 이름보다 꼬리표가 길어진다.
 * (시켰을 때 실제로 도는 것은 언제나 위쪽 줄이다 — 실측)
 */
function alterTag(x) {
  if (x.level == null) return '';
  return ' <span class="muted sub">Lv.' + x.level + '</span>';
}

function renderAlter() {
  if (!alterCache) return;
  const q = $('#alter-search').value.trim();
  const onlyOk = $('#alter-only-ok').checked;

  let rows = alterCache.items;
  if (onlyOk) rows = rows.filter((x) => x.ok);
  const facPick = $('#alter-facility').value;
  if (facPick) rows = rows.filter((x) => x.facility === facPick);
  const lvPick = $('#alter-level').value;
  if (lvPick === '?') rows = rows.filter((x) => x.level == null);
  else if (lvPick) rows = rows.filter((x) => x.level === Number(lvPick));
  if (q) {
    const n = q.toLowerCase().replace(/\s+/g, '');
    rows = rows.filter((x) => x.name.toLowerCase().replace(/\s+/g, '').includes(n));
  }

  // 거르지 않았으면 "조건에 맞는 것"은 전체와 같다 — 같은 수를 두 번 적을 이유가 없고,
  // 그 한 토막이 도구줄에서 자리를 꽤 먹는다.
  $('#alter-count').textContent =
    '전체 ' + alterCache.total + ' · 가능 ' + alterCache.alterable +
    (rows.length === alterCache.total ? '' : ' · 맞는 것 ' + rows.length);

  const row = (x) =>
    '<tr>' +
        '<td class="' + (x.ok ? 'mark-ok' : 'mark-bad') + '">' + (x.ok ? '✔' : '✘') + '</td>' +
        '<td>' + starBtn('alter', x) + richName(x) + alterTag(x) + '</td>' +
        '<td class="num">' + x.per + '</td>' +
        '<td class="num sub">' + (x.sec != null ? esc(dur(x.sec)) : '') + '</td>' +
        '<td class="sub">' + ingredientCell(x, '가공 가능') + '</td>' +
        '<td>' + (() => {
          if (!x.ok) return '';
          const fac = x.facility;
          // 소속 시설을 아직 모르면 막지 않는다 — 표에도 관측에도 없는 레시피다
          if (fac && fullFacilities.has(fac)) {
            return '<button class="btn btn-tiny" disabled title="' + esc(fac) + ' 칸이 가득 찼습니다. 먼저 수령하세요.">칸 없음</button>';
          }
          return '<button class="btn btn-tiny btn-primary" data-alter="' + esc(x.nameRaw || x.name) + '">가공</button> ' +
            (x.facility
              ? '<button class="btn btn-tiny" data-fill="' + esc(x.nameRaw || x.name) + '" data-fill-label="' + esc(x.name) + '">채우기</button> '
              : '');
        })() +
        // 목표는 지금 가공이 되든 안 되든 세울 수 있다. 재료가 없어서 못 하는 것이야말로
        // 자동 진행이 채워 줄 일이다.
        '<button class="btn btn-tiny" data-plan="' + esc(x.nameRaw || x.name) + '" data-plan-label="' + esc(x.name) + '">목표</button>' +
        '</td>' +
        '</tr>';

  const body = favTableBody('alter', sortRows('alter', rows), 5, row);
  $('#alter-table tbody').innerHTML = body.html;
  paintPager('alter-table', 'alter', body.pg, body.rest);
}

/**
 * 게임에 사용자 입력이 필요한 창이 떠 있으면 닫힐 때까지 기다린다.
 *
 * 커넥터에는 대화/팝업을 누르는 명령이 없다(28개 어디에도 없음). 그래서 확인 버튼은
 * 사람이 눌러야 하는데, 그때마다 앱이 실패로 끝나면 처음부터 다시 시켜야 한다.
 * 대신 여기서 지켜보다가 창이 닫히면 알아서 이어간다.
 *
 * @returns true = 정리됨, false = 시간 초과 또는 사용자가 중단
 */
async function waitForUserInput(label, timeoutMs) {
  const limit = timeoutMs || 120000;
  const startedAt = Date.now();
  let notified = false;

  while (Date.now() - startedAt < limit) {
    if (collectAll.aborted) return false;
    const a = await mm.query('activity', {});
    // IsReviving 은 여기서 보지 않는다. 살아 있는데도 켜져 있는 것을 확인해서,
    // 그걸 기다리면 아무 일도 없는데 2분을 버린다.
    if (!a.dialogue) return true;

    if (!notified) {
      notified = true;
      toast('게임에서 확인이 필요합니다', (label ? label + ' — ' : '') +
        '게임 창에서 확인을 눌러 주세요. 닫히면 자동으로 이어갑니다.', 'bad');
    }
    const left = Math.round((limit - (Date.now() - startedAt)) / 1000);
    setBusy(true, '게임에서 확인을 눌러 주세요… (' + left + '초 내)');
    await sleep(2000);
  }
  return false;
}

async function collectAll() {
  const w = await mm.query('alteringWorks', { refresh: true });
  const targets = w.facilities.filter((f) => f.completed.length).map((f) => f.completed[0].name);
  if (!targets.length) { toast('수령할 작업 없음', '', 'ok'); return; }

  // 확인 창을 띄우지 않는다. 수령은 비용이 없고 되돌릴 것도 없어서, 물어봐야 할 이유가 없다.
  // 확인 창을 눌러 달라는 안내도 하지 않는다 — 실측(6개 시설 29건 연속)에서 한 번도 뜨지 않았다.
  // 그래도 막히면 아래 waitForUserInput 이 그때 알려 준다.
  toast(targets.length + '개 시설 수령 시작',
    '시설마다 이동이 있어 시간이 걸립니다. 상태바의 취소로 멈출 수 있습니다.', 'ok');

  collectAll.aborted = false;
  let done = 0, failed = 0;

  // 누른 버튼 자리에서 진행을 보여 준다. 끝나면 loadAlter가 다시 그리므로 복구는 보험이다.
  const restore = btnBusy($('#collect-all'), '수령 중… (0/' + targets.length + ')');

  for (let i = 0; i < targets.length; i++) {
    if (collectAll.aborted) break;
    const name = targets[i];
    const label = '(' + (i + 1) + '/' + targets.length + ') ' + name + ' 시설';
    btnBusyText($('#collect-all'), '수령 중… (' + (i + 1) + '/' + targets.length + ') ' + name);

    // 앞 시설의 보상 창이 남아 있으면 먼저 정리될 때까지 기다린다
    if (i > 0 && !(await waitForUserInput(label))) {
      toast('중단', '확인 창이 닫히지 않아 멈췄습니다.', 'bad');
      break;
    }

    let r = await runAction('complete_altering_work', { displayName: name },
      { label: label + ' 수령', skipConfirm: true });

    // 진행 중 창이 떠서 막혔으면, 사람이 닫기를 기다렸다가 한 번 더 시도한다
    if (r && !r.ok && r.error === 'blocked') {
      if (await waitForUserInput(label)) {
        r = await runAction('complete_altering_work', { displayName: name },
          { label: label + ' 수령(재시도)', skipConfirm: true });
      }
    }

    if (r && r.ok) done++;
    else failed++;
  }

  setBusy(false);
  restore();
  toast('전체 수령 종료', '완료 ' + done + '곳' + (failed ? ' · 실패 ' + failed + '곳' : ''), failed ? 'bad' : 'ok');
  loadAlter(true);
}


/**
 * 가공 큐 자동 채우기.
 *
 * 칸이 꽉 찬 상태에서 등록하면 이동까지 진행된 뒤 막혀서 **날개 5가 그냥 나간다**(실측).
 * 그래서 "실패할 때까지 반복"은 쓸 수 없고, 남은 칸만큼만 정확히 돌린다.
 *
 * 매 등록 뒤 큐를 다시 읽어 실제로 늘었는지 확인하고, 안 늘었으면 즉시 멈춘다.
 * 헛돌면서 날개를 태우는 것이 가장 나쁜 실패다.
 */
async function fillAltering(name, label) {
  if (busy) { toast('실행 중', '이전 명령이 끝난 뒤 시도하세요.', 'bad'); return; }

  const fac = itemFacility[name];
  if (!fac) {
    toast('소속 시설을 모릅니다', '이 아이템을 한 번 가공해 보면 시설을 배웁니다. 그 뒤에 자동 채우기를 쓸 수 있습니다.', 'bad');
    return;
  }

  const w = await mm.query('alteringWorks', { refresh: true });
  const room = (w.room || []).find((r) => r.facility === fac);
  if (!room || room.free <= 0) {
    toast(fac + ' 칸이 없습니다', '완료분을 먼저 수령하세요. (' + (room ? room.used + '/' + room.slots : '?') + ')', 'bad');
    return;
  }

  const want = await promptNumber(
    '자동 채우기',
    '"' + (label || name) + '" 를 몇 건 등록할까요?',
    room.free,
    fac + ' — 최대 ' + room.slots + '칸 중 ' + room.used + '칸 사용 중, ' + room.free + '칸 비어 있습니다.'
  );
  if (!want) return;

  const n = Math.min(want, room.free);
  const cost = await mm.costOf('execute_altering', 1);
  const total = cost.perCall * n;

  const okGo = await confirmModal('자동 채우기 확인',
    '<p>' + esc(label || name) + ' × ' + n + '건 — ' + esc(fac) + '</p>' +
    '<div class="cost">' +
      '<div>소모 <span class="big">' + num(total) + '</span> ' + esc(cost.currency || '정령의 날개') +
      ' <span class="muted">(' + cost.perCall + ' × ' + n + '건)</span></div>' +
      '<div class="muted">보유 ' + num(cost.balance) + ' → ' + num(cost.balance - total) + '</div>' +
    '</div>' +
    (want > room.free ? '<p class="hint">여유 칸이 ' + room.free + '개라 ' + n + '건으로 줄였습니다.</p>' : '') +
    '<p class="hint">칸이 꽉 찬 뒤에 시도하면 이동만 하고 막혀서 날개가 그냥 나갑니다. ' +
    '그래서 매 등록 후 큐를 다시 확인하고, 늘지 않으면 즉시 멈춥니다.</p>');
  if (!okGo) return;

  fillAltering.aborted = false;
  let queued = 0, spent = 0;
  let prevUsed = room.used;

  for (let i = 0; i < n; i++) {
    if (fillAltering.aborted) break;

    const r = await runAction('execute_altering', { displayName: name },
      { label: '(' + (i + 1) + '/' + n + ') ' + (label || name) + ' 등록', skipConfirm: true });

    if (r && r.wingsSpent) spent += r.wingsSpent;

    if (!r || !r.ok) {
      // 막힘 처리(칸 수·레벨 확정)는 메인이 한곳에서 한다. 여기서는 멈추기만 한다.
      if (r && r.error === 'blocked') {
        toast(fac + ' 칸이 가득 찼습니다', '자동 채우기를 멈춥니다.', 'bad');
      }
      break;
    }

    // 정말 큐에 들어갔는지 확인한다. 성공 응답만 믿고 반복하면 헛돌 수 있다.
    const w2 = await mm.query('alteringWorks', { refresh: true });
    const r2 = (w2.room || []).find((x) => x.facility === fac);
    const nowUsed = r2 ? r2.used : prevUsed;
    if (nowUsed <= prevUsed) {
      toast('큐가 늘지 않았습니다', '등록이 반영되지 않아 멈췄습니다. 게임 상태를 확인하세요.', 'bad');
      break;
    }
    prevUsed = nowUsed;
    queued++;
    if (r2 && r2.free <= 0) break;
  }

  setBusy(false);
  toast('자동 채우기 종료', '등록 ' + queued + '건 · ' + (cost.currency || '날개') + ' ' + spent + ' 소모',
    queued === n ? 'ok' : 'bad');
  loadAlter(true);
}

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
    if (qAbort) break;

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
let qAbort = false;
/** 생활 스킬 레벨이 모자라 멈춘 것인가. { what, level, message } */
let qSkillHalt = null;
let qSeq = 1;

const Q_STATE = {
  wait:  { label: '대기', cls: 'q-wait' },
  run:   { label: '진행 중', cls: 'q-run' },
  pause: { label: '보류', cls: 'q-pause' },
  done:  { label: '완료', cls: 'q-done' },
  fail:  { label: '중단', cls: 'q-fail' },
};

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
  if (it.status === 'run') { qAbort = true; qNote(it, '멈추는 중…'); }
  qItems = qItems.filter((x) => x !== it);
  paintQueue();
  saveQueue();
}

/** 이 항목부터 돌린다. 대기 줄의 맨 앞으로 올리고 큐를 깨운다. */
function qPlayOne(id) {
  const it = qFind(id);
  if (!it) return;
  if (it.status === 'run') return;
  // 이미 끝난 것을 다시 거는 것이면 기준점을 새로 잡는다.
  // 보류였다면 그대로 둬야 하던 자리에서 이어간다.
  if (it.status === 'done' || it.status === 'fail') {
    delete it.base;
    delete it.made;
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
 * 이 항목을 보류한다.
 *
 * 진행 중이면 지금 걸음을 마치고 빠진다. 보류된 항목은 큐가 지나칠 뿐 지워지지는 않아서,
 * ▶ 를 누르면 하던 자리에서 이어간다 (기준점을 다시 잡지 않는다).
 */
function qPauseOne(id) {
  const it = qFind(id);
  if (!it) return;
  if (it.status === 'run') { it.pauseAfter = true; qAbort = true; qNote(it, '이번 걸음을 마치고 멈춥니다…'); return; }
  if (it.status === 'wait') { it.status = 'pause'; paintQueue(); saveQueue(); }
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
  if (!it) return;
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
  qAbort = true;
  qItems = [];
  paintQueue();
  saveQueue();
}

/** 부드럽게 멈춘다. 항목 상태는 그대로라 재생을 누르면 이어진다. */
function qPause() {
  if (!qRunning) return;
  qAbort = true;
  say('이번 걸음을 마치고 멈춥니다.');
}

/**
 * 지금 명령까지 끊고 멈춘다.
 *
 * 일시정지와 다른 점은 둘이다. 돌고 있는 CLI 호출에 취소를 보내고, 진행하던 항목을
 * **보류**로 둔다. 재생을 눌러도 그 항목은 건너뛰므로, 잘못 건 목표를 세울 때 쓴다.
 */
async function qHalt() {
  const it = qItems.find((x) => x.status === 'run');
  if (it) it.pauseAfter = true;
  qAbort = true;
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
  qAbort = false;
  paintQueue();

  try {
    while (!qAbort) {
      const it = qItems.find((x) => x.status === 'wait');
      if (!it) break;                 // 보류(pause)는 여기서 걸리지 않으므로 자연히 건너뛴다
      it.status = 'run';
      qNote(it, '시작');
      saveQueue();

      let ok = false;
      try { ok = await runGoalItem(it); }
      catch (err) { qNote(it, '오류 — ' + (err && err.message)); }

      // 도중에 지워졌으면 상태를 되살리지 않는다
      if (!qItems.includes(it)) continue;

      // 다 만든 카드는 치운다. 남겨 두면 할 일 목록에 "할 일이 아닌 것"이 쌓이고,
      // 정작 다음에 뭘 할 차례인지가 안 보인다. 기록은 토스트와 파일 로그에 남는다.
      if (ok) {
        qItems = qItems.filter((x) => x !== it);
        toast('목표 달성', it.label + ' 새로 ' + num(it.target) + '개' +
          (it.spent ? ' · 날개 ' + num(it.spent) : ''), 'ok');
        paintQueue();
        saveQueue();
        continue;
      }

      // 사람이 멈춘 것은 실패가 아니다. 이 항목만 보류하라고 했으면 보류로,
      // 큐 전체를 멈춘 것이면 대기로 되돌린다 — 어느 쪽이든 하던 자리에서 이어갈 수 있다.
      if (qSkillHalt) {
        // 스킬 레벨은 시간이 지난다고 오르지 않는다. 대기로 되돌리면 재생을 누를 때마다
        // 같은 거절을 다시 받으므로, 중단으로 못 박고 이유를 카드에 적는다.
        it.status = 'fail';
        qNote(it, '생활 스킬 레벨 부족 — ' + qSkillHalt.what +
          (qSkillHalt.level ? ' (필요 Lv.' + qSkillHalt.level + ')' : '') + ' · 날개는 쓰이지 않았습니다.');
        toast('생활 스킬 레벨이 모자랍니다',
          qSkillHalt.what + ' 을(를) 캘 수 없어 작업 큐를 세웠습니다.' +
          (qSkillHalt.level ? ' 필요 레벨 ' + qSkillHalt.level + '.' : ''), 'bad');
      } else if (it.pauseAfter) {
        it.status = 'pause';
        qNote(it, '보류 — ▶ 를 누르면 이어서 진행합니다.');
      } else if (qAbort) {
        it.status = 'wait';
        qNote(it, '멈춤 — 재생을 누르면 이어서 진행합니다.');
      } else it.status = 'fail';
      delete it.pauseAfter;
      paintQueue();
      saveQueue();
    }
  } finally {
    qRunning = false;
    qAbort = false;
    qSkillHalt = null;
    paintQueue();
    // 큐가 비면 화면을 한 번 새로 고친다. 수량이 많이 바뀌어 있다.
    try { await refreshActive(); } catch (_) {}
  }
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

  $('#q-play').disabled = qRunning || !waiting;
  $('#q-pause').disabled = !qRunning;
  $('#q-halt').disabled = !qRunning;
  $('#q-tidy').disabled = !qItems.some((x) => x.status === 'done' || x.status === 'fail');
  $('#q-clear').disabled = !qItems.length;

  if (!qItems.length) {
    list.innerHTML = '<p class="q-empty">비어 있습니다.<br>제작 · 가공 · 채집 탭의 <b>목표</b>로 ' +
      '무엇을 얼마나 만들지 정해 두면 여기에 추가됩니다.</p>';
    return;
  }

  list.innerHTML = qItems.map((x, i) => {
    const st = Q_STATE[x.status] || Q_STATE.wait;
    const run = x.status === 'run';
    const ended = x.status === 'done' || x.status === 'fail';

    // 진행 중에는 ⏸ 만, 끝난 것에는 ▶(다시 걸기)만 낸다. 지금 누를 수 없는 버튼을
    // 흐리게 늘어놓는 것보다 아예 없는 편이 무엇을 할 수 있는지 분명하다.
    const btns =
      (run ? '<button class="q-btn" data-q-pause="' + x.id + '" title="이번 걸음을 마치고 보류">⏸</button>' : '') +
      (!run ? '<button class="q-btn" data-q-play="' + x.id + '" title="' + (ended ? '다시 걸기' : '이것부터 진행') + '">▶</button>' : '') +
      (x.status === 'wait' ? '<button class="q-btn" data-q-pause="' + x.id + '" title="보류">⏸</button>' : '') +
      '<button class="q-btn" data-q-edit="' + x.id + '" title="수량 바꾸기">✎</button>' +
      '<button class="q-btn" data-q-del="' + x.id + '" title="큐에서 빼기">✕</button>';

    // 이름은 길면 잘린다. 잘린 것을 확인할 길이 title 말고 없다.
    const nowHave = x.have !== undefined ? x.have : x.startHave;

    return '<div class="q-item ' + st.cls + '">' +
      '<div class="q-top"><span class="q-badge">' + st.label + '</span>' +
      '<b title="' + esc(x.label) + '">' + esc(x.label) + '</b>' +
      '<span class="spacer"></span>' + btns +
      '</div>' +
      // 수량은 이름 옆이 아니라 아래 줄에 둔다. "새로 100개"만으로는 지금 몇 개를 들고
      // 있는지 알 수 없어, 목표를 얼마로 잡을지 판단할 근거가 되지 못한다.
      '<div class="q-amt">목표 <b>' + num(x.target) + '</b>개' +
      (nowHave !== undefined ? ' · 현재 <b>' + num(nowHave) + '</b>개' : '') +
      (x.made ? ' <span class="muted">(만든 ' + num(x.made) + ')</span>' : '') +
      '</div>' +
      '<div class="q-sub">' + esc(x.via || '') +
      (x.recipe ? ' · ' + esc(x.recipe) : '') +
      (x.spent ? ' · 날개 ' + num(x.spent) : '') +
      (!x.spent && x.wings ? ' · 예상 ' + num(x.wings) + (x.partial ? '+' : '') : '') +
      '</div>' +
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
      qSkillHalt = {
        what: st.name,
        level: r.requiredLevel || (r.data && r.data.requiredLevel) || null,
        message: r.message || null,
      };
      qAbort = true;
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
    if (qAbort) return false;
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

/* ── 채집 ───────────────────────────────────────── */

let gatherCache = null;

async function loadGather(refresh) {
  const r = await mm.query('gather', { refresh: !!refresh });
  if (r.error) { toast('채집 목록 조회 실패', r.message || r.error, 'bad'); return; }
  gatherCache = r;
  renderGather();
}

function renderGather() {
  if (!gatherCache) return;
  const q = $('#gather-search').value.trim();
  const onlyOk = $('#gather-only-ok').checked;

  let rows = gatherCache.items;
  if (onlyOk) rows = rows.filter((x) => x.tool);
  if (q) {
    const n = q.toLowerCase().replace(/\s+/g, '');
    rows = rows.filter((x) => x.name.toLowerCase().replace(/\s+/g, '').includes(n));
  }

  $('#gather-count').textContent = '전체 ' + gatherCache.total + ' · 도구 보유 ' + gatherCache.toolOk + ' · 표시 ' + rows.length;

  const row = (x) =>
    '<tr>' +
    '<td class="' + (x.tool ? 'mark-ok' : 'mark-warn') + '">' + (x.tool ? '✔' : '△') + '</td>' +
    '<td>' + starBtn('gather', x) + richName(x) + (x.tool ? '' : ' <span class="sub">도구 없음/손상</span>') + '</td>' +
    '<td><button class="btn btn-tiny btn-primary" data-gather="' + esc(x.nameRaw || x.name) + '">채집</button> ' +
    // 채집도 "달걀 1000개"처럼 목표를 걸 수 있다. 한 번에 100개씩이라 10번 부르면 된다 —
    // 그 셈을 사람이 하고 버튼을 열 번 누를 이유가 없다.
    '<button class="btn btn-tiny" data-plan="' + esc(x.nameRaw || x.name) + '" data-plan-label="' + esc(x.name) + '">목표</button></td>' +
    '</tr>';

  // 채집은 페이저가 없다. 쪽을 나누면 즐겨찾기 아래가 잘린 채 넘길 곳이 없어진다.
  $('#gather-table tbody').innerHTML = favTableBody('gather', sortRows('gather', rows), 3, row, false).html;
}

async function doGather(name) {
  await runAction('execute_gathering', { displayName: name },
    { label: name + ' 채집',
      note: '1회 호출로 최대 100개까지 모읍니다. 더 필요하면 다시 누르세요. 낚시 전용 항목은 자동 낚시가 켜진 채 즉시 반환됩니다.' });
}

/* ── 소지품 ─────────────────────────────────────── */

let itemsCache = null;

async function loadItems(refresh) {
  const r = await mm.query('items', { refresh: !!refresh });
  if (r.error) { toast('소지품 조회 실패', r.message || r.error, 'bad'); return; }
  itemsCache = r;
  paintItemCats();
  renderItems();
}

/**
 * 보관처 필터.
 *
 * 단순히 "가방에 있는 것"만으로는 부족하다. 실제로 궁금한 건
 * "창고에만 있어서 가방에는 없는 것" — 꺼내 와야 쓰는 것이다.
 */
const LOC_FILTER = {
  bag: (x) => x.at.bag > 0,
  charStore: (x) => x.at.charStore > 0,
  accStore: (x) => x.at.accStore > 0,
  storeOnly: (x) => x.at.bag === 0 && (x.at.charStore > 0 || x.at.accStore > 0),
};

/** 0은 숫자로 적지 않는다. 있는 곳만 눈에 들어와야 훑기 쉽다. */
function atCell(n) {
  return n > 0
    ? '<td class="num">' + num(n) + '</td>'
    : '<td class="num muted">·</td>';
}

/** 분류 메뉴를 채운다. 목록이 바뀌어도 고른 값이 남아 있으면 유지한다. */
function paintItemCats() {
  const sel = $('#items-cat');
  if (!sel || !itemsCache) return;
  const cur = sel.value;
  const cats = itemsCache.categories || [];
  sel.innerHTML = '<option value="">분류 전체</option>' +
    cats.map((c) => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join('');
  if (cats.indexOf(cur) !== -1) sel.value = cur;
}

function renderItems() {
  if (!itemsCache) return;
  const q = $('#items-search').value.trim();
  const cat = $('#items-cat').value;
  const loc = $('#items-loc').value;

  let rows = itemsCache.items;
  if (cat) rows = rows.filter((x) => x.category === cat);
  if (loc && LOC_FILTER[loc]) rows = rows.filter(LOC_FILTER[loc]);
  if (q) {
    const n = q.toLowerCase().replace(/\s+/g, '');
    rows = rows.filter((x) => x.name.toLowerCase().replace(/\s+/g, '').includes(n));
  }

  // 보이는 것들의 보관처별 합계도 같이 알려준다 — "계정창고에 뭐가 얼마나 있나"가 한 줄로 나온다
  const sum = rows.reduce((s, x) => {
    s.bag += x.at.bag; s.charStore += x.at.charStore; s.accStore += x.at.accStore;
    return s;
  }, { bag: 0, charStore: 0, accStore: 0 });

  // 도구줄에서 이 한 줄이 가장 길다(실측 373px, 줄의 40%). 거르지 않았으면 같은 수를
  // 두 번 적지 않고, 창고 이름도 줄인다 — 옆 칸 이름이 "캐릭창고"인 표 위에 있어 뜻은 통한다.
  $('#items-count').textContent =
    (rows.length === itemsCache.matched ? '' : rows.length + ' / ') + itemsCache.matched + '종' +
    (rows.length ? '  ·  가방 ' + num(sum.bag) + ' · 캐릭 ' + num(sum.charStore) + ' · 계정 ' + num(sum.accStore) : '');

  const row = (x) =>
    '<tr><td>' + starBtn('items', x) + richName(x) +
    (x.locked ? ' <span class="sub" title="잠긴 아이템이 포함돼 있습니다">🔒</span>' : '') + '</td>' +
    '<td class="sub">' + esc(x.category) + '</td>' +
    '<td class="num">' + num(x.total) + '</td>' +
    atCell(x.at.bag) + atCell(x.at.charStore) + atCell(x.at.accStore) +
    '</tr>';

  const body = favTableBody('items', sortRows('items', rows), 6, row);
  $('#items-table tbody').innerHTML = body.html;
  paintPager('items-table', 'items', body.pg, body.rest);
}

/* ── 미션 ───────────────────────────────────────── */

const MISSION_MARK = {
  done: '<span class="mark-ok">✔</span>',
  unclaimed: '<span class="mark-warn">◆</span>',
  open: '<span class="muted">·</span>',
};

function missionHtml(list) {
  if (!list.length) return '<span class="muted">없음</span>';
  return list.map((m) => {
    const [cur, goal] = String(m.progress).split('/').map(Number);
    const pct = goal > 0 ? Math.min(100, Math.round((cur / goal) * 100)) : (m.done ? 100 : 0);
    return '<div class="mission">' +
      (MISSION_MARK[m.state] || MISSION_MARK.open) +
      '<span class="t">' + esc(m.title) +
      '<br><span class="d">' + esc(m.desc) + '</span></span>' +
      '<span class="bar"><i class="' + widthClass(pct) + '"></i></span>' +
      '<span class="p">' + esc(m.progress) + '</span></div>';
  }).join('');
}

/** "진행 2 · 수령 대기 1 / 11" — 수령 대기가 있으면 눈에 띄게 적는다. */
function missionCountText(r) {
  const parts = ['진행 ' + r.open];
  if (r.unclaimed) parts.push('수령 대기 ' + r.unclaimed);
  return parts.join(' · ') + ' / ' + r.total;
}

/** 받지 않은 보상 건수만 한 줄로. 없으면 줄 자체를 감춘다. */
function paintMissionTodo(r) {
  const n = ((r.daily && r.daily.unclaimed) || 0) + ((r.weekly && r.weekly.unclaimed) || 0);
  const el = $('#mission-todo');
  if (!el) return;
  el.className = n ? 'note note-warn' : 'note hidden';
  el.textContent = n ? '받지 않은 보상이 ' + n + '건 있습니다.' : '';
}

async function loadMission(refresh) {
  const onlyOpen = $('#mission-only-open').checked;
  const r = await mm.queryMany(['daily', 'weekly', 'quests'], {
    daily: { onlyOpen, refresh: !!refresh },
    weekly: { onlyOpen, refresh: !!refresh },
    quests: { refresh: !!refresh },
  });

  if (!r.daily.error) {
    $('#daily-count').textContent = missionCountText(r.daily);
    $('#daily-list').innerHTML = missionHtml(r.daily.items);
  }
  if (!r.weekly.error) {
    $('#weekly-count').textContent = missionCountText(r.weekly);
    $('#weekly-list').innerHTML = missionHtml(r.weekly.items);
  }
  paintMissionTodo(r);
  if (!r.quests.error) {
    $('#quest-count').textContent = r.quests.total + '건';
    $('#quest-list').innerHTML = r.quests.items.length
      ? r.quests.items.map((q) =>
          '<div class="mission"><span class="t">' +
          richName({ name: q.title, seg: q.titleSeg }) +
          '<br><span class="d">' + esc(q.source) + ' · ' +
          q.objectives.map((o) =>
            richName({ name: o.desc, seg: o.seg }) +
            (o.progress ? ' ' + esc(o.progress) : '') +
            (o.done ? ' <span class="mark-ok">✔</span>' : '')).join(' / ') +
          '</span></span></div>').join('')
      // 비어 오는 것이 오류는 아니다. 명세상 **게임에서 열려 있는 트래커 탭**의 항목만 온다.
      // 실측 — 같은 자리에서 연속 조회해도 0건과 7건이 번갈아 나온다.
      : '<span class="muted">표시할 항목이 없습니다. 게임에서 퀘스트 트래커에 올라와 있는 것만 조회됩니다.</span>';
  }
}

/* ── 연주 · 소셜 ────────────────────────────────── */

let musicCache = null, socialCache = null, instrumentCache = null;

async function loadMusic(refresh) {
  const r = await mm.queryMany(['instruments', 'musicScores'], {
    instruments: { refresh: !!refresh },
    musicScores: { refresh: !!refresh },
  });

  if (!r.instruments.error) { instrumentCache = r.instruments; renderInstruments(); }
  if (!r.musicScores.error) { musicCache = r.musicScores; renderMusic(); }
  await loadPlaylists();
  startPerfWatch();
}

async function loadSocial(refresh) {
  const r = await mm.query('socialActions', { refresh: !!refresh });
  if (!r.error) { socialCache = r; renderSocial(); }
}

/** 검색어 정규화 — 공백 무시, 대소문자 무시 */
function normQ(sel) {
  return $(sel).value.trim().toLowerCase().replace(/\s+/g, '');
}
function hit(text, q) {
  return !q || String(text).toLowerCase().replace(/\s+/g, '').includes(q);
}

/**
 * 악보 제목 앞의 "악보: " 를 뗀다.
 *
 * 게임이 주는 DisplayTitle 은 전부 "악보: 흰 사슴 이야기" 꼴이다. 악보 목록에 있는 것이
 * 악보인 줄은 아니까 화면에서는 뗀다. 다만 play_music_score 는 이 제목을 그대로 받고
 * 재생목록도 이 값으로 저장돼 있으므로, 명령과 저장에는 언제나 원본을 쓴다.
 */
const SCORE_PREFIX = /^악보\s*:\s*/;
function scoreLabel(title) { return String(title).replace(SCORE_PREFIX, ''); }

/**
 * 악기는 버튼 격자로 늘어놓는다.
 *
 * 17개뿐이라 한 줄짜리 목록으로 세로를 길게 먹을 이유가 없고, 장착 중인 것을 색으로
 * 칠해 두면 "지금 뭘 들고 있나"가 한눈에 보인다. 장착 중인 버튼은 누를 것이 없어 꺼 두되,
 * 흐려지면 오히려 눈에 안 띄므로 색은 그대로 둔다.
 */
function renderInstruments() {
  if (!instrumentCache) return;
  const rows = sortRows('instrument', instrumentCache.items);

  $('#instrument-count').textContent = instrumentCache.total + '개';
  $('#instrument-list').innerHTML = rows.length
    ? rows.map((i) => {
        const dur = i.durability === null ? '무한' : num(i.durability);
        return '<button class="btn inst' + (i.equipped ? ' inst-on' : '') + '"' +
          (i.equipped ? ' disabled' : '') +
          ' data-instrument="' + esc(i.name) + '"' +
          ' title="' + esc(i.name + ' — 내구도 ' + dur) + '">' +
          (i.equipped ? '✔ ' : '') + esc(i.name) +
          (i.durability === null ? '' : ' <small>' + dur + '</small>') +
          '</button>';
      }).join('')
    : '<span class="muted">보유 악기 없음</span>';
}

function renderMusic() {
  if (!musicCache) return;
  const q = normQ('#music-search');
  // 제목 전부가 "악보:" 로 시작하므로 검색도 뗀 제목에 건다
  const rows = sortRows('music', musicCache.items.filter((x) => hit(scoreLabel(x.title), q)));

  $('#music-count').textContent = q ? rows.length + ' / ' + musicCache.total : musicCache.total + '개';
  $('#music-list').innerHTML = rows.length
    ? rows.map((x) =>
        '<div class="mission"><span class="t">' + esc(scoreLabel(x.title)) + '</span>' +
        '<button class="btn btn-tiny" data-pl-add="' + esc(x.title) + '" title="재생목록에 담기">+</button> ' +
        '<button class="btn btn-tiny btn-primary" data-play="' + esc(x.title) + '">연주</button></div>').join('')
    : '<span class="muted">결과 없음</span>';
}

function renderSocial() {
  if (!socialCache) return;
  const q = normQ('#social-search');

  // 표정과 행동은 카드가 따로 있으니 정렬도 카드마다 따로 고른다.
  const facials = sortRows('facial', socialCache.facials.filter((x) => hit(x.name, q)));
  const behaviours = sortRows('behaviour', socialCache.behaviours.filter((x) => hit(x.name, q)));

  $('#facial-count').textContent = q
    ? facials.length + ' / ' + socialCache.facials.length
    : facials.length + '개';
  $('#behaviour-count').textContent = q
    ? behaviours.length + ' / ' + socialCache.behaviours.length
    : behaviours.length + '개';

  // 이모지가 없는 표정은 보낼 방법이 없으므로 버튼으로 만들지 않는다
  const facialChip = (x) => x.emoji
    ? '<span class="chip chip-btn" data-social-emoji="' + esc(x.emoji) + '" data-social-name="' + esc(x.name) + '">' +
      starBtn('facial', x) + esc(x.emoji) + ' ' + esc(x.name) + '</span>'
    : '<span class="chip" title="이모지가 없어 실행할 수 없습니다">' +
      starBtn('facial', x) + esc(x.name) + '</span>';

  $('#social-facials').innerHTML = favChips('facial', facials, facialChip);
  const behaviourChip = (x) => {
    // 일어서기만 채팅이 아니라 전용 명령으로 나간다. 목록에서는 같은 줄에 둔다.
    const star = starBtn('behaviour', x);
    if (x.via === 'command') {
      return '<span class="chip chip-btn" data-social-run="' + esc(x.command) + '" ' +
        'data-social-name="' + esc(x.name) + '" title="전용 명령 ' + esc(x.command) + '">' +
        star + esc(x.name) + '</span>';
    }
    const cmd = (x.commands && x.commands[0]) || '';
    return cmd
      ? '<span class="chip chip-btn" data-social-cmd="' + esc(cmd) + '" title="' + esc(x.commands.join(' ')) + '">' + star + esc(x.name) + '</span>'
      : '<span class="chip" title="채팅 명령이 없어 실행할 수 없습니다">' + star + esc(x.name) + '</span>';
  };

  $('#social-list').innerHTML = favChips('behaviour', behaviours, behaviourChip);
}


/* ── 재생목록 ───────────────────────────────────── */

/**
 * 커넥터가 캐릭터를 구분해 주지 않으므로(이름도 ID도 없음) 목록은 사용자가 관리한다.
 * 대신 재생 시점에 현재 보유 악보와 대조해 가진 곡만 튼다 — 캐릭터를 바꿔도 목록이 안 깨진다.
 */
let playlists = [];
let plCurrent = null;

/** 재생 상태. setInterval 대신 루프 안에서 플래그를 보고 멈춘다. */
const player = { active: false, stopping: false, index: 0, title: null };

const PL_KEY = 'mobi-remote.playlist';

function ownedTitles() {
  return new Set((musicCache && musicCache.items ? musicCache.items : []).map((x) => x.title));
}

function plStatus(text) {
  $('#pl-status').textContent = text || '';
}

function renderPlaylists() {
  const sel = $('#pl-select');
  sel.innerHTML = playlists.length
    ? playlists.map((p) => '<option value="' + esc(p.id) + '">' + esc(p.name) + ' (' + p.tracks.length + '곡)</option>').join('')
    : '<option value="">(목록 없음 — 새로 만들기)</option>';
  if (plCurrent) sel.value = plCurrent.id;

  $('#pl-count').textContent = playlists.length ? playlists.length + '개' : '';
  $('#pl-loop').checked = !!(plCurrent && plCurrent.loop);
  $('#pl-shuffle').checked = !!(plCurrent && plCurrent.shuffle);

  const owned = ownedTitles();
  const box = $('#pl-tracks');
  if (!plCurrent) {
    box.innerHTML = '<span class="muted">재생목록을 만들고 악보 목록에서 <b>+</b>를 눌러 담으세요.</span>';
    return;
  }
  if (!plCurrent.tracks.length) {
    box.innerHTML = '<span class="muted">비어 있습니다. 위 악보 목록에서 <b>+</b>를 눌러 담으세요.</span>';
    return;
  }
  const missing = plCurrent.tracks.filter((t) => !owned.has(t)).length;
  box.innerHTML = plCurrent.tracks.map((t, i) => {
    const has = owned.has(t);
    const playing = player.active && player.title === t;
    return '<div class="mission' + (playing ? ' pl-playing' : '') + '">' +
      '<span class="' + (has ? 'mark-ok' : 'mark-bad') + '">' + (has ? (playing ? '▶' : '✔') : '✘') + '</span>' +
      '<span class="t">' + esc(scoreLabel(t)) + (has ? '' : ' <span class="sub">이 캐릭터에 없음 — 건너뜁니다</span>') + '</span>' +
      '<button class="btn btn-tiny" data-pl-move="' + i + '" data-pl-delta="-1" title="위로">↑</button>' +
      '<button class="btn btn-tiny" data-pl-move="' + i + '" data-pl-delta="1" title="아래로">↓</button>' +
      '<button class="btn btn-tiny" data-pl-del="' + i + '" title="목록에서 제거">×</button>' +
      '</div>';
  }).join('') +
  (missing ? '<p class="hint">' + missing + '곡은 이 캐릭터가 갖고 있지 않아 재생에서 제외됩니다.</p>' : '');
}

async function loadPlaylists() {
  playlists = await mm.pl.list();
  let savedId = null;
  try { savedId = localStorage.getItem(PL_KEY); } catch (_) {}
  plCurrent = playlists.find((p) => p.id === savedId) || playlists[0] || null;
  renderPlaylists();
}

function selectPlaylist(id) {
  plCurrent = playlists.find((p) => p.id === id) || null;
  try { if (plCurrent) localStorage.setItem(PL_KEY, plCurrent.id); } catch (_) {}
  renderPlaylists();
}

async function refreshPlaylists(keepId) {
  playlists = await mm.pl.list();
  plCurrent = playlists.find((p) => p.id === (keepId || (plCurrent && plCurrent.id))) || playlists[0] || null;
  renderPlaylists();
}

/* ── 재생 엔진 ──────────────────────────────────── */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 지금 무엇을 연주 중인지. 곡이 끝났는지 판단하는 유일한 근거다. */
/**
 * 지금 연주 중인가, 그리고 어디까지 왔나.
 *
 * 시간은 게임이 재서 준다 (TotalDuration / Elapsed / Remaining). 앱이 시작 시각을 재는
 * 방식이었다면 게임에서 직접 연주를 시작한 경우를 놓쳤겠지만, 이 값은 누가 시작했든 맞다.
 * 부르는 쪽이 여럿이라 (재생 루프, 진행바 타이머) 본 것을 nowPlaying 에 남겨 같이 쓴다.
 */
async function performance() {
  const a = await mm.query('activity', {});
  const p = (a && a.perf) || {};
  const out = {
    playing: !!(a && a.performing),
    busy: !!(a && a.busy),
    dead: !!(a && a.dead),
    title: p.title || '',
    instrument: p.instrument || '',
    loop: !!p.loop,
    total: p.total || 0,
    elapsed: p.elapsed || 0,
    remaining: p.remaining || 0,
    channels: p.channels || 0,
  };
  nowPlaying.last = out;
  nowPlaying.at = Date.now();
  paintNowPlaying();
  return out;
}

/** 초를 m:ss 로. 한 시간 넘는 악보는 없으니 분까지면 충분하다. */
function mmss(sec) {
  const n = Math.max(0, Math.round(Number(sec) || 0));
  return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0');
}

/* ── 연주 진행 상황 ────────────────────────────── */

/**
 * 연주 탭에 머무는 동안만 돈다.
 *
 * 게임에 물어보는 것은 2.5초에 한 번이고 (연주 중이 아니면 6초로 늦춘다), 그 사이는
 * 마지막으로 받은 값에 흐른 시간을 더해 메운다. 진행바를 매끄럽게 하려고 초당 몇 번씩
 * CLI를 부르는 것은 낭비다.
 */
const nowPlaying = { on: false, timer: null, tick: null, last: null, at: 0 };

function startPerfWatch() {
  if (nowPlaying.on) return;
  nowPlaying.on = true;
  nowPlaying.tick = setInterval(paintNowPlaying, 500);
  pollPerf();
}

function stopPerfWatch() {
  nowPlaying.on = false;
  clearTimeout(nowPlaying.timer);
  clearInterval(nowPlaying.tick);
  nowPlaying.timer = nowPlaying.tick = null;
}

async function pollPerf() {
  if (!nowPlaying.on) return;
  try { await performance(); } catch (_) { /* 잠깐 못 읽어도 다음 차례에 다시 본다 */ }
  if (!nowPlaying.on) return;
  const playing = !!(nowPlaying.last && nowPlaying.last.playing);
  nowPlaying.timer = setTimeout(pollPerf, playing ? 2500 : 6000);
}

/** 마지막으로 받은 값 + 그 뒤로 흐른 시간. 폴링 사이를 메운다. */
function paintNowPlaying() {
  const box = $('#pl-now');
  if (!box) return;
  const p = nowPlaying.last;
  if (!p || !p.playing) { box.classList.add('hidden'); box.innerHTML = ''; return; }

  const drift = (Date.now() - nowPlaying.at) / 1000;
  const total = p.total || 0;
  // ElapsedSeconds 는 곡이 끝나도 멈추지 않고 계속 올라간다. 게임 쪽 반복이 켜져 있으면
  // 62.4초짜리가 70초, 80초까지 간다. 그래서 총 길이로 나눠 이번 바퀴의 위치를 쓴다.
  const raw = (p.elapsed || 0) + drift;
  const pass = total ? Math.floor(raw / total) : 0;
  const elapsed = total ? raw - pass * total : raw;
  const left = total ? Math.max(0, total - elapsed) : 0;
  const pct = total ? (elapsed / total) * 100 : 0;

  box.classList.remove('hidden');
  box.innerHTML =
    '<div class="now-head"><span class="mark-ok">▶</span> ' +
    '<b>' + esc(scoreLabel(p.title) || '연주 중') + '</b>' +
    (p.instrument ? ' <span class="muted">' + esc(p.instrument) + '</span>' : '') +
    (p.loop ? ' <span class="muted">게임 반복 켜짐</span>' : '') +
    '<span class="spacer"></span>' +
    '<span class="now-time">' + mmss(elapsed) +
    (total ? ' / ' + mmss(total) : '') + '</span></div>' +
    (total
      ? '<div class="bar bar-wide"><i class="' + widthClass(pct) + '"></i></div>' +
        '<div class="now-foot muted">남은 시간 ' + mmss(left) +
        (pass ? ' · ' + (pass + 1) + '바퀴째' : '') +
        (p.channels ? ' · ' + p.channels + '화음' : '') + '</div>'
      : '');
}

function nextIndex(list, from) {
  return from + 1 < list.length ? from + 1 : (plCurrent && plCurrent.loop ? 0 : -1);
}

async function playPlaylist() {
  if (player.active) { toast('이미 재생 중입니다', '', 'bad'); return; }
  if (!plCurrent || !plCurrent.tracks.length) { toast('재생목록이 비어 있습니다', '', 'bad'); return; }

  // 보유한 곡만 추린다. 캐릭터가 바뀌어도 목록을 고칠 필요가 없게 하는 핵심.
  await loadMusic(true);
  const owned = ownedTitles();
  let queue = plCurrent.tracks.filter((t) => owned.has(t));
  if (!queue.length) {
    toast('재생할 곡이 없습니다', '이 캐릭터가 목록의 악보를 하나도 갖고 있지 않습니다.', 'bad');
    return;
  }
  if (plCurrent.shuffle) {
    for (let i = queue.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [queue[i], queue[j]] = [queue[j], queue[i]];
    }
  }

  player.active = true;
  player.stopping = false;
  player.index = 0;
  $('#pl-play').disabled = true;

  let played = 0, skipped = 0;
  try {
    while (player.active && !player.stopping && player.index >= 0) {
      const title = queue[player.index];
      player.title = title;
      renderPlaylists();
      plStatus('(' + (player.index + 1) + '/' + queue.length + ') ' + scoreLabel(title));

      const r = await mm.exec('play_music_score', { title: title });
      if (!r.ok) {
        skipped++;
        const why = r.ko ? r.ko.text : r.error;
        noteLine('연주 실패 — ' + scoreLabel(title) + ' (' + why + ')');
        // 전투·사망·탑승 중이면 뒤 곡도 마찬가지이므로 멈춘다
        if (['not_available_on_combat', 'not_available_on_dead', 'not_available_on_riding'].indexOf(r.error) >= 0) {
          toast('연주를 계속할 수 없습니다', why, 'bad');
          break;
        }
        player.index = nextIndex(queue, player.index);
        continue;
      }

      played++;
      // 연주가 실제로 시작될 때까지 잠깐 기다린 뒤, 끝날 때까지 지켜본다
      await sleep(2000);
      while (player.active && !player.stopping) {
        const p = await performance();
        if (!p.playing) break;

        // 게임 안에서 "반복"을 켜 두면 곡이 끝나도 IsPlaying 이 내려오지 않고 처음부터 다시
        // 돈다. 그것만 기다리면 재생목록이 첫 곡에서 영영 멈춘다. 총 길이를 넘어선 것을
        // 한 곡이 끝난 것으로 보고, 직접 멈춘 뒤 다음 곡으로 넘어간다.
        if (p.total && p.elapsed >= p.total - 0.5) {
          await mm.exec('stop_action');
          break;
        }

        plStatus('(' + (player.index + 1) + '/' + queue.length + ') ' + scoreLabel(title) +
          (p.total ? ' — ' + mmss(p.elapsed) + ' / ' + mmss(p.total) : ''));
        await sleep(3000);
      }
      if (player.stopping) break;
      player.index = nextIndex(queue, player.index);
    }
  } finally {
    player.active = false;
    player.title = null;
    $('#pl-play').disabled = false;
    plStatus('');
    renderPlaylists();
  }

  toast('재생목록 종료', '연주 ' + played + '곡' + (skipped ? ' · 실패 ' + skipped + '곡' : ''), skipped ? 'bad' : 'ok');
}

async function stopPlaylist() {
  if (!player.active) {
    // 재생 중이 아니어도 수동 정지는 허용한다
    await runAction('stop_action', undefined, { label: '연주 정지', skipConfirm: true });
    return;
  }
  player.stopping = true;
  plStatus('정지하는 중…');
  await runAction('stop_action', undefined, { label: '연주 정지', skipConfirm: true });
}

/**
 * 자동 진행 중에 남기는 한 줄.
 *
 * 전에는 루틴 탭의 로그 상자로 갔다. 그 탭을 없앤 뒤로는 상태바가 유일한 자리다.
 */
function noteLine(text) {
  say(text);
}

/* ── 주변 ───────────────────────────────────────── */

/** 대시보드의 주변 카드. loadDash가 이미 받아 둔 응답을 넘겨 준다. */
function paintNear(r) {
  const pcs = r.nearPcs || { items: [], total: 0 };
  $('#pc-count').textContent = '플레이어 ' + pcs.total;
  $('#pc-table tbody').innerHTML = pcs.items.length
    ? pcs.items.map((p) =>
        '<tr><td>' + esc(p.name) + (p.title ? ' <span class="sub">' + esc(p.title) + '</span>' : '') + '</td>' +
        '<td class="num">' + p.distance + '</td><td class="num">' + p.level + '</td>' +
        '<td class="sub">' + esc(p.job) + '</td><td class="num">' + num(p.combat) + '</td>' +
        '<td class="sub">' + [p.inCombat ? '전투' : '', p.playing ? '연주' : '', p.friend ? '친구' : '', p.party ? '파티' : '']
            .filter(Boolean).join(', ') + '</td></tr>').join('')
    : '<tr><td colspan="6" class="empty">주변에 플레이어가 없습니다</td></tr>';

  const npcs = r.nearNpcs || { items: [], total: 0 };
  $('#npc-count').textContent = 'NPC ' + npcs.total;
  $('#npc-list').innerHTML = npcs.total
    ? npcs.items.map((n) => '<div class="mission"><span class="t">' + esc(n.DisplayName || n.name || JSON.stringify(n)) + '</span></div>').join('')
    : '<span class="muted">대화 가능한 NPC가 주변에 없습니다</span>';
}


/* ── 염색 도우미 ────────────────────────────────────────── */

/**
 * 게임 화면을 읽어 원하는 색이 팔레트 어디에 있는지 짚어 준다.
 *
 * ── 리모콘의 다른 기능과 다른 점 ────────────────────────────
 * 커넥터를 전혀 쓰지 않는다. 화면 픽셀만 읽고 게임에는 아무것도 보내지 않으며,
 * 찍는 것은 사람이 찍는다. 정령의 날개도 들지 않는다.
 *
 * ── 왜 여기(렌더러)에서 계산하나 ────────────────────────────
 * 화면 한 장이 8MB 다. 메인으로 넘겨 계산하면 초당 몇 장도 못 보낸다.
 * 그래서 픽셀이 있는 이 자리에서 dye.js 로 계산하고, 결과(점 세 개)만 메인에 넘긴다.
 *
 * ── 언제 다시 훑나 ──────────────────────────────────────────
 * 소용돌이는 사용자가 끌거나 돌리거나 확대할 때만 바뀐다. 그래서 초당 몇 번씩 전부
 * 훑지 않고, **격자 몇백 점으로 지문을 떠서 달라졌을 때만** 다시 찾는다 (1ms 미만).
 */

const dyeUI = {
  on: false,
  stream: null,
  timer: null,
  video: null,
  canvas: null,
  ctx: null,
  box: null,         // 찾아 둔 팔레트 (캡처 좌표)
  lead: null,        // 찾아 둔 색 선택 UI — 자리는 붙박이라 한 번만 찾는다
  bands: null,       // 파트별로 색을 고를 수 있는 가로 범위 (염색 타입이 다르면 갈린다)
  doneSeen: 0,       // 확정 화면을 몇 바퀴 이어서 봤나
  sig: null,         // 마지막 지문
  scale: 1,          // 캡처 → 화면 좌표 배율
  origin: { x: 0, y: 0 },
  prefs: null,
  misses: 0,
};

function dyeCurrent() {
  const p = dyeUI.prefs;
  if (!p) return null;
  return p.presets.find((x) => x.id === p.currentId) || p.presets[0] || null;
}

async function loadDye() {
  dyeUI.prefs = await mm.dye.prefs();
  paintDyePresets();
  paintDyeSlots();
  paintDyeState();
}

function paintDyePresets() {
  const p = dyeUI.prefs;
  const sel = $('#dye-preset');
  sel.innerHTML = p.presets.map((x) =>
    '<option value="' + esc(x.id) + '"' + (x.id === p.currentId ? ' selected' : '') + '>' +
    esc(x.name) + '</option>').join('');
}

function paintDyeSlots() {
  const cur = dyeCurrent();
  const colors = (cur && cur.colors) || ['', '', ''];
  const tols = (cur && cur.tol) || [5, 5, 5];
  $('#dye-slots').innerHTML = colors.map((c, i) => {
    const ok = /^#[0-9a-f]{6}$/i.test(c);
    const slot = (window.dyeDraw.SLOT[i] || {}).line || '#888';
    return '<div class="dye-slot">' +
      '<b class="dye-no ' + bgClass(slot) + '">' + (i + 1) + '</b>' +
      // 네모를 누르면 색 편집이 열린다. 버튼을 따로 두면 줄만 길어지고, 누를 곳이 색 옆에
      // 있는 편이 "이 칸의 색을 정한다"는 뜻에 더 가깝다.
      '<button class="dye-chip' + (ok ? '' : ' empty') + ' ' + lineClass(slot) + '"' +
      ' data-dye-pick="' + i + '" data-dye-chip="' + i + '"' +
      ' title="눌러서 색 편집 — 스포이드로 화면에서 집을 수도 있습니다"></button>' +
      '<input class="mono" data-dye-hex="' + i + '" value="' + esc(c) + '" placeholder="#RRGGBB" maxlength="7">' +
      '<span class="dye-tol">' +
      '<input type="range" min="0" max="20" step="1" data-dye-tol="' + i + '" value="' + tols[i] + '">' +
      '<b class="mono" data-dye-tolv="' + i + '">' + tols[i] + '</b>' +
      '</span>' +
      '<button class="q-btn" data-dye-clear="' + i + '" title="비우기">✕</button>' +
      '</div>';
  }).join('');
  // 색 미리보기는 CSP 때문에 인라인 style 을 못 쓴다 — 클래스로 만들어 붙인다.
  // className 을 통째로 갈아엎으면 테두리색까지 날아가므로 더하기만 한다.
  colors.forEach((c, i) => {
    const chip = $('[data-dye-chip="' + i + '"]');
    if (chip && /^#[0-9a-f]{6}$/i.test(c)) {
      const cls = bgClass(c);
      if (cls) chip.classList.add(cls);
    }
  });
}

function paintDyeState() {
  const pill = $('#dye-state');
  const st = !dyeUI.on ? ['꺼짐', 'pill-muted']
    : dyeUI.box ? ['팔레트 찾음', 'pill-ok']
    : ['팔레트 기다리는 중', 'pill-warn'];
  pill.textContent = st[0];
  pill.className = 'pill ' + st[1];
  $('#dye-start').classList.toggle('hidden', dyeUI.on);
  $('#dye-stop').classList.toggle('hidden', !dyeUI.on);
}

function dyeTargets() {
  const cur = dyeCurrent();
  if (!cur) return [];
  const tols = cur.tol || [];
  return (cur.colors || [])
    .map((c, i) => dye.target(c, tols[i]))
    .filter(Boolean);
}

/* ══ 새 판 알림 ═════════════════════════════════════════════════
 *
 * 켤 때 한 번 조용히 확인하고, 있으면 위에 띠를 하나 띄운다. 누르기 전에는
 * 아무것도 받지 않고 아무것도 끄지 않는다 — 게임을 켜 둔 채로 쓰는 프로그램이라
 * 작업 도중에 저 혼자 꺼지면 곤란하다.
 */
const updUI = { info: null, file: null, busy: false };

function showUpdate(text, canGo) {
  $('#update-text').textContent = text;
  $('#update-go').classList.toggle('hidden', !canGo);
  $('#update-banner').classList.remove('hidden');
}

async function wireUpdate() {
  $('#update-later').addEventListener('click', () => $('#update-banner').classList.add('hidden'));

  mm.update.onProgress((p) => {
    if (!updUI.busy) return;
    const mb = (n) => (n / 1048576).toFixed(1);
    $('#update-text').textContent = '받는 중 ' + p.pct + '%  (' + mb(p.got) + ' / ' + mb(p.total) + 'MB)';
  });

  $('#update-go').addEventListener('click', async () => {
    const info = updUI.info;
    if (!info || updUI.busy) return;

    // 받아 둔 것이 있으면 바로 설치로 간다.
    if (updUI.file) return mm.update.install(updUI.file);

    // 설치 파일이 없는 릴리즈(무설치판만 올린 경우)는 받을 자리를 알 수 없다.
    if (!info.asset) { mm.update.page(); return; }

    updUI.busy = true;
    $('#update-go').disabled = true;
    const r = await mm.update.download(info.asset);
    updUI.busy = false;
    $('#update-go').disabled = false;

    if (!r || !r.ok) {
      showUpdate('받지 못했습니다 — ' + ((r && r.error) || '알 수 없음') + '. 눌러서 받는 곳을 엽니다.', true);
      updUI.info = Object.assign({}, info, { asset: null });
      return;
    }
    updUI.file = r.file;
    $('#update-go').textContent = '설치하고 다시 켜기';
    showUpdate('내려받았습니다 — 누르면 프로그램이 꺼지고 설치가 시작됩니다.', true);
  });

  // 켜자마자 묻지 않는다. 첫 화면이 다 그려진 뒤에 조용히 확인한다.
  setTimeout(async () => {
    const r = await mm.update.check().catch(() => null);
    if (!r || !r.ok || !r.newer) return;      // 못 물어봤거나 최신이면 아무 말도 안 한다
    updUI.info = r;
    showUpdate('새 판이 나왔습니다 — ' + r.version, true);
  }, 4000);
}

/* ══ 새 판 알림 끝 ══════════════════════════════════════════════ */

/* ── 시작 / 중지 ── */

async function startDye() {
  if (dyeUI.on) return;
  const src = await mm.dye.source();
  if (!src || src.error) { toast('화면을 읽을 수 없습니다', src && src.error, 'bad'); return; }

  try {
    dyeUI.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        mandatory: {
          chromeMediaSource: 'desktop',
          chromeMediaSourceId: src.id,
          minWidth: src.bounds.width, maxWidth: src.bounds.width,
          minHeight: src.bounds.height, maxHeight: src.bounds.height,
        },
      },
    });
  } catch (err) {
    toast('화면 캡처가 거부되었습니다', err.message, 'bad');
    return;
  }

  dyeUI.video = $('#dye-video');
  dyeUI.canvas = $('#dye-canvas');
  dyeUI.video.srcObject = dyeUI.stream;
  await dyeUI.video.play().catch(() => {});

  // 우리 창을 캡처에서 뺀다. 리모콘의 히트맵과 색 견본이 팔레트만큼 알록달록해서,
  // 그대로 두면 앱 창과 팔레트가 한 덩어리로 붙어 엉뚱한 사각형이 잡힌다.
  await mm.dye.protect(true).catch(() => {});

  dyeUI.origin = { x: src.bounds.x, y: src.bounds.y };
  dyeUI.on = true;
  dyeUI.box = null;
  dyeUI.sig = null;
  dyeUI.lead = null;
  dyeUI.bands = null;
  dyeUI.doneSeen = 0;
  dyeUI.misses = 0;
  paintDyeState();
  say('염색 대기 — 팔레트가 뜨면 표시합니다.');

  dyeUI.timer = setInterval(dyeTick, 120);
}

async function stopDye() {
  dyeUI.on = false;
  clearInterval(dyeUI.timer);
  dyeUI.timer = null;
  if (dyeUI.stream) { dyeUI.stream.getTracks().forEach((t) => t.stop()); dyeUI.stream = null; }
  if (dyeUI.video) dyeUI.video.srcObject = null;
  dyeUI.box = null;
  dyeUI.lead = null;
  await mm.dye.hide().catch(() => {});
  await mm.dye.protect(false).catch(() => {});
  paintDyePreview(null);
  paintDyeState();
  paintDyeInfo(null);
  say('염색 도우미를 껐습니다.');
}

/* ── 한 바퀴 ── */

function grabFrame() {
  const v = dyeUI.video;
  if (!v || !v.videoWidth) return null;
  const c = dyeUI.canvas;
  if (c.width !== v.videoWidth) { c.width = v.videoWidth; c.height = v.videoHeight; dyeUI.ctx = null; }
  if (!dyeUI.ctx) dyeUI.ctx = c.getContext('2d', { willReadFrequently: true });
  dyeUI.ctx.drawImage(v, 0, 0, c.width, c.height);
  const d = dyeUI.ctx.getImageData(0, 0, c.width, c.height);
  // 캡처가 화면보다 크거나 작을 수 있다 (배율). 화면 좌표로 옮길 때 쓴다.
  dyeUI.scale = window.screen.width / c.width;
  return dye.frame(d.data, c.width, c.height, 'rgba');
}

async function dyeTick() {
  if (!dyeUI.on) return;
  const f = grabFrame();
  if (!f) return;

  // 아직 팔레트를 못 찾았으면 찾는다
  if (!dyeUI.box) {
    const box = dye.detectPalette(f);
    if (!box) {
      // 염색이 끝나면 확정 단추가 있는 화면으로 넘어간다. 그때는 할 일이 끝난 것이다.
      // 팔레트가 없을 때만 본다 — 염색 화면에도 같은 색 단추("이대로 염색하기")가 있다.
      if (dye.findDoneButton(f)) {
        // 한 번 스친 것으로 끄지 않는다. 두 바퀴 이어질 때만.
        if (++dyeUI.doneSeen >= 2) {
          await stopDye();
          toast('염색이 끝나 도우미를 껐습니다', '확정 화면이 떠서 자동으로 중지했습니다.', 'ok');
          return;
        }
      } else {
        dyeUI.doneSeen = 0;
      }
      paintDyeInfo(null);
      // 게임을 보고 있는 동안에도 상태가 보여야 한다. 리모콘 창이 아니라 화면 위에 띄운다.
      const wait = { status: '염색 감지 중…', tone: 'wait' };
      await mm.dye.draw(wait).catch(() => {});
      paintDyePreview(wait);
      return;
    }
    dyeUI.box = box;
    dyeUI.sig = null;
    dyeUI.lead = null;
    paintDyeState();
    return;
  }

  // 찾아 뒀으면, 달라졌을 때만 다시 훑는다
  const sig = dye.signature(f, dyeUI.box);
  const moved = dye.signatureDiff(dyeUI.sig, sig);
  if (dyeUI.sig && moved < 1) return;          // 그대로면 아무것도 안 한다
  dyeUI.sig = sig;

  // 팔레트가 사라졌는지 가끔 확인 — 염색 창을 닫으면 대기로 돌아가야 한다
  if (++dyeUI.misses % 25 === 0) {
    const again = dye.detectPalette(f);
    if (!again) {
      dyeUI.box = null;
      await mm.dye.hide().catch(() => {});
      paintDyeState();
      paintDyeInfo(null);
      return;
    }
    dyeUI.box = again;
    dyeUI.lead = null;   // 팔레트를 다시 봤으니 UI 자리도 다시 찾는다
    dyeUI.bands = null;
  }

  // 캡처 좌표 → 화면 좌표. 배율이 1이 아닌 화면에서도 자리가 맞게.
  const toScreen = (v, axis) => Math.round(v * dyeUI.scale + dyeUI.origin[axis]);
  const box = {
    x: toScreen(dyeUI.box.x, 'x'), y: toScreen(dyeUI.box.y, 'y'),
    w: Math.round(dyeUI.box.w * dyeUI.scale), h: Math.round(dyeUI.box.h * dyeUI.scale),
  };
  const status = '팔레트 감지 — ' + dyeUI.box.w + ' × ' + dyeUI.box.h;

  const targets = dyeTargets();
  if (!targets.length) {
    // 색을 아직 안 정했어도 **어디를 팔레트로 보고 있는지**는 보여 준다.
    // 여기서 그냥 돌아가면 화면에는 아까 띄운 "감지 중" 띠가 그대로 남아,
    // 잘 찾아 놓고도 못 찾은 것처럼 보인다.
    const bare = { status: status + ' · 색을 정해 주세요', tone: 'ok', box: box };
    await mm.dye.draw(bare).catch(() => {});
    paintDyePreview(bare);
    paintDyeInfo({ box: dyeUI.box, marks: [] });
    return;
  }

  // 게임의 색 선택 UI(흰 지시선과 동그라미)는 팔레트 색이 아니다. 찾아서 빼 둔다 —
  // 안 그러면 흰색을 목표로 잡았을 때 선을 따라 점이 줄줄이 찍힌다.
  //
  // 자리는 **한 번만** 찾는다. 이 UI 는 화면에 붙박이고 움직이는 것은 그 아래 팔레트다.
  // 매 바퀴 다시 찾으면 한두 픽셀씩 떨려서 표시가 동그라미에서 어긋난다.
  // 팔레트를 다시 확인할 때(25바퀴마다) 같이 다시 찾으므로, 새 염색 시도로 자리가
  // 바뀌어도 곧 따라간다.
  if (!dyeUI.lead) dyeUI.lead = dye.findLeaders(f, dyeUI.box);

  // 파트마다 염색 타입(천·가죽·금속·나무)이 다르면 팔레트가 세로로 갈라진다.
  // 그러면 **1번 스포이드는 1번 구역 안에서만** 색을 고를 수 있다 — 끌어도 무늬가
  // 칸 경계를 넘어오지 않는다. 구역도 UI 라 붙박이이므로 자리와 함께 한 번만 찾는다.
  if (!dyeUI.bands && dyeUI.lead.rings.length) {
    dyeUI.bands = dye.findBands(f, dyeUI.box, dyeUI.lead.rings.length);
  }

  const lead = { skip: dyeUI.lead.skip, rings: dye.readRings(f, dyeUI.lead.rings) };

  const found = dye.findColors(f, dyeUI.box, targets, { skip: lead.skip });
  const regionSets = dye.findRegions(f, dyeUI.box, targets, { skip: lead.skip, bands: dyeUI.bands });

  const marks = found.map((r) => ({
    x: toScreen(r.x, 'x'), y: toScreen(r.y, 'y'),
    hex: r.hex, color: r.color, delta: r.delta, found: r.found,
  }));

  // 선분 [x1,y1,x2,y2,...] 을 화면 좌표로. 색은 오버레이가 칸 번호로 정한다 —
  // 찾는 색 그 자체로 그으면 같은 색 위에서 안 보인다.
  const regions = regionSets.map((segs) => {
    const out = new Array(segs.length);
    for (let k = 0; k < segs.length; k += 2) { out[k] = toScreen(segs[k], 'x'); out[k + 1] = toScreen(segs[k + 1], 'y'); }
    return out;
  });

  /**
   * 스포이드 동그라미 안쪽 색 = **그 파트가 지금 고른 색.** 게임이 위 딱지에 적어 두는
   * 그 값이다(실측으로 딱지의 HEX 와 정확히 일치했다).
   *
   * 목표 오차 안에 들면 어느 칸인지 알려 준다. 둘 이상 맞으면 더 가까운 쪽.
   */
  const picks = lead.rings.map((ring) => {
    const lab = dye.toLab(ring.rgb[0], ring.rgb[1], ring.rgb[2]);
    let slot = -1, best = Infinity;
    targets.forEach((t, i) => {
      const dL = lab[0] - t.lab[0], da = lab[1] - t.lab[1], db = lab[2] - t.lab[2];
      const d = Math.sqrt(dL * dL + da * da + db * db);
      const tol = t.tol === undefined ? 5 : t.tol;
      if (d <= tol && d < best) { best = d; slot = i; }
    });
    return {
      x: toScreen(ring.x, 'x'), y: toScreen(ring.y, 'y'),
      r: Math.max(6, Math.round(ring.r * dyeUI.scale)),
      slot: slot,
      hex: dye.rgbToHex(ring.rgb[0], ring.rgb[1], ring.rgb[2]),
      delta: slot < 0 ? null : Math.round(best * 10) / 10,
    };
  });

  /**
   * 세 색을 한 번에 잡을 자리 찾기 — **3파트일 때만.**
   *
   * 1·2파트는 손으로도 어렵지 않아서 안 그린다. 못 찾으면 아무것도 안 그린다 —
   * "지금은 안 된다"를 알리는 것보다 화면이 조용한 편이 낫다.
   */
  // 셋 다 이미 잡았으면 안내는 할 일이 끝났다. 그리지 않고, 쫓던 자리도 버린다 —
  // 다음에 다시 어긋나면 그때 새로 찾는 것이 맞다.
  const allCaught = targets.length >= 3 &&
    [0, 1, 2].every((i) => picks.some((p) => p.slot === i));

  /**
   * 스포이드 셋을 잇는 점선 삼각형.
   *
   * 세 스포이드의 상대 자리는 시도하는 동안 안 바뀐다. 그 모양이 눈에 들어와 있으면
   * "이 배치로 세 색을 어떻게 걸칠까"를 가늠하기 쉬워진다.
   *
   * 예전에는 여기서 **세 색을 한 번에 잡을 자리**를 찾아 삼각형으로 그렸다. 계산은
   * 맞았지만(닮은꼴 오차 0.2% 이내, 꼭짓점 색도 전부 오차 안) 쓰기에는 아직 거칠어서
   * 접었다. 찾는 코드와 따라가는 코드는 dye.js 에 그대로 있다 — 사정은 findTriangle
   * 머리말에 적어 두었다.
   */
  const tri = lead.rings.length === 3
    ? { pins: lead.rings.map((r) => ({ x: toScreen(r.x, 'x'), y: toScreen(r.y, 'y') })) }
    : null;
  // 화면 맨 위에 찾는 세 색을 적는다. 잡힌 칸은 또렷하게.
  const chips = targets.map((t, i) => ({
    hex: t.hex,
    on: picks.some((p) => p.slot === i),
  }));

  const payload = {
    status: status + (allCaught ? '  ·  셋 다 잡았습니다' : ''),
    tone: 'ok', chips: chips,
    // marks 는 리모콘 창에 글로 적으려고 같이 보낸다. 화면 위에는 안 그린다.
    box: box, regions: regions, tri: tri, marks: marks, picks: picks,
  };
  await mm.dye.draw(payload).catch(() => {});
  paintDyePreview(payload);

  paintDyeInfo({ box: dyeUI.box, marks: found, picks: picks });
  paintHeat(f, targets);
}

/* ── 화면 ── */

function paintDyeInfo(st) {
  const box = st && st.box;
  $('#dye-info').innerHTML = [
    ['팔레트', box ? box.w + ' × ' + box.h : '아직 못 찾음'],
    ['위치', box ? box.x + ', ' + box.y : '—'],
  ].map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join('');

  const marks = (st && st.marks) || [];
  // 지금 그 칸의 스포이드가 목표를 물고 있는가. 팔레트를 맞추는 동안 볼 값은 이것뿐이다.
  const picks = (st && st.picks) || [];
  $('#dye-found').innerHTML = marks.length
    ? marks.map((m, i) =>
        '<div class="dye-hit' + (m.found ? '' : ' miss') + '">' +
        '<span class="dye-chip ' + bgClass(m.color) + '"></span>' +
        '<b class="mono">' + esc(m.color) + '</b>' +
        '<span class="muted">목표 ' + esc(m.hex) + '</span>' +
        '<span class="spacer"></span>' +
        '<span class="' + (m.found ? 'mark-ok' : 'mark-warn') + '">ΔE ' + m.delta +
        ' <span class="muted">/ ' + m.tol + '</span></span>' +
        (picks.some((p) => p.slot === i)
          ? '<span class="mark-ok">스포이드 물림</span>'
          : '<span class="muted">—</span>') +
        '</div>').join('')
    : '<p class="muted">표시할 것이 없습니다.</p>';
}

/**
 * 오버레이에 그려지는 것과 **같은 그림**을 리모콘 안에 작게 그린다.
 *
 * 오버레이 창은 캡처에서 빠지도록 해 두어서 사용자의 스크린샷에도 안 찍힌다.
 * 무엇이 그려지고 있는지 확인할 방법이 없으면 고칠 수도 없다.
 */
function paintDyePreview(payload) {
  const c = $('#dye-preview');
  if (!c) return;
  const W = window.screen.width, H = window.screen.height;
  const box = c.getBoundingClientRect();
  const k = (box.width || 640) / W;
  const r = window.devicePixelRatio || 1;
  c.width = Math.round(box.width * r);
  c.height = Math.round(box.width * (H / W) * r);
  const ctx = c.getContext('2d');
  ctx.setTransform(r * k, 0, 0, r * k, 0, 0);
  // 미리보기는 작아서, 선을 같은 비율로 줄이면 안 보인다. 조금 두껍게 그린다.
  window.dyeDraw.draw(ctx, W, H, payload, 1 / k * 0.8);
  const note = $('#dye-prev-note');
  if (note) note.textContent = payload && payload.box ? '실시간' : '대기';
}

/** 일치도 그림 — 목표색에 가까울수록 밝다. */
function paintHeat(f, targets) {
  const row = $('#dye-heats');
  if (!row.childElementCount || row.childElementCount !== targets.length) {
    row.innerHTML = targets.map((t, i) =>
      '<figure class="heat"><canvas data-heat="' + i + '" width="64" height="64"></canvas>' +
      '<figcaption class="mono">' + esc(t.hex) + '</figcaption></figure>').join('');
  }
  targets.forEach((t, i) => {
    const c = $('[data-heat="' + i + '"]');
    if (!c) return;
    const hm = dye.heatmap(f, dyeUI.box, t, 64);
    const ctx = c.getContext('2d');
    const img = ctx.createImageData(64, 64);
    for (let p = 0; p < hm.data.length; p++) {
      const v = hm.data[p];
      img.data[p * 4] = v; img.data[p * 4 + 1] = v; img.data[p * 4 + 2] = v; img.data[p * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  });
}

/* ── 스포이드 ── */

/**
 * 화면에서 색을 집는다.
 *
 * 따로 확대경을 띄우지 않고, 캡처가 도는 동안 **팔레트 한가운데 색**을 집어 온다.
 * 정확히 한 점을 찍고 싶으면 게임에서 원하는 자리로 팔레트를 옮긴 뒤 누르면 된다.
 */
/* ── 색 편집 ──────────────────────────────────────────────────
 *
 * 그림판의 "색 편집"과 같은 꼴 — 네모에서 채도·명도, 옆 띠에서 색상, 오른쪽에 HEX 와 RGB.
 *
 * ── 왜 canvas 로만 그리나 ─────────────────────────────────
 * CSP 가 style-src 'self' 라 인라인 style 을 못 쓴다. 무지개 그라데이션을 클래스로 미리
 * 만들어 둘 수도 없다(색상마다 다르다). 그래서 두 판은 전부 캔버스에 직접 그린다.
 *
 * ── 스포이드 ──────────────────────────────────────────────
 * 누르면 그 순간의 화면을 **한 장 찍어서** 대화상자 안에 띄우고, 거기를 눌러 색을 고른다.
 * 화면 위에 덧창을 띄워 집게 하는 방법도 있지만, 이쪽이 낫다.
 *
 *   - 염색 시작을 안 눌러도 쓸 수 있다. 그때그때 한 장만 찍으면 되니까.
 *   - 찍는 순간 우리 창을 캡처에서 빼므로(setContentProtection), 리모콘에 가려 있던
 *     **게임 화면이 그대로 찍힌다.** 창을 치웠다 되돌릴 필요가 없다.
 *   - 그림이 멈춰 있으니 천천히 확대해 가며 고를 수 있다. 게임 위에서 집으려면
 *     마우스를 움직이는 동안 팔레트도 같이 움직여서 오히려 어렵다.
 */

const cpick = { h: 0, s: 0, v: 1, done: null, shot: null, drag: null };

function hsvToRgb(h, s, v) {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  const k = Math.floor((((h % 360) + 360) % 360) / 60);
  const t = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][k];
  return [Math.round((t[0] + m) * 255), Math.round((t[1] + m) * 255), Math.round((t[2] + m) * 255)];
}

function rgbToHsv(r, g, b) {
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) {
    if (mx === r) h = ((g - b) / d + (g < b ? 6 : 0));
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return [h, mx ? d / mx : 0, mx / 255];
}

function cpickHex() {
  const c = hsvToRgb(cpick.h, cpick.s, cpick.v);
  return dye.rgbToHex(c[0], c[1], c[2]);
}

function cpickRing(g, x, y, r) {
  g.lineWidth = 3; g.strokeStyle = 'rgba(0,0,0,.65)';
  g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
  g.lineWidth = 1.5; g.strokeStyle = '#ffffff';
  g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
}

/** 두 판과 오른쪽 숫자를 지금 색에 맞춰 다시 그린다. */
function paintCpick() {
  const sv = $('#cpick-sv'), g = sv.getContext('2d');
  const W = sv.width, H = sv.height;
  g.fillStyle = 'hsl(' + Math.round(cpick.h) + ',100%,50%)';
  g.fillRect(0, 0, W, H);
  let lin = g.createLinearGradient(0, 0, W, 0);
  lin.addColorStop(0, 'rgba(255,255,255,1)');
  lin.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = lin; g.fillRect(0, 0, W, H);
  lin = g.createLinearGradient(0, 0, 0, H);
  lin.addColorStop(0, 'rgba(0,0,0,0)');
  lin.addColorStop(1, 'rgba(0,0,0,1)');
  g.fillStyle = lin; g.fillRect(0, 0, W, H);
  cpickRing(g, cpick.s * W, (1 - cpick.v) * H, 6);

  const hue = $('#cpick-hue'), g2 = hue.getContext('2d');
  const W2 = hue.width, H2 = hue.height;
  const bar = g2.createLinearGradient(0, 0, 0, H2);
  for (let i = 0; i <= 6; i++) bar.addColorStop(i / 6, 'hsl(' + (i * 60) + ',100%,50%)');
  g2.fillStyle = bar; g2.fillRect(0, 0, W2, H2);
  const y = (cpick.h / 360) * H2;
  g2.lineWidth = 3; g2.strokeStyle = 'rgba(0,0,0,.65)';
  g2.beginPath(); g2.moveTo(0, y); g2.lineTo(W2, y); g2.stroke();
  g2.lineWidth = 1.5; g2.strokeStyle = '#ffffff';
  g2.beginPath(); g2.moveTo(0, y); g2.lineTo(W2, y); g2.stroke();

  // 숫자 칸은 사용자가 치는 중이면 건드리지 않는다 — 한 글자 칠 때마다 되돌려 버린다.
  const c = hsvToRgb(cpick.h, cpick.s, cpick.v);
  const hex = dye.rgbToHex(c[0], c[1], c[2]);
  $('#cpick-new').className = bgClass(hex);
  const put = (sel, v) => { const el = $(sel); if (el && document.activeElement !== el) el.value = v; };
  put('#cpick-hex', hex);
  put('#cpick-r', c[0]); put('#cpick-g', c[1]); put('#cpick-b', c[2]);
}

function setCpickRgb(r, g, b) {
  const hsv = rgbToHsv(r, g, b);
  // 검정·흰색은 색상이 정해지지 않는다. 그때는 쓰던 색상을 그대로 둔다 —
  // 안 그러면 명도를 0 으로 내렸다 올리는 사이에 색이 빨강으로 튄다.
  if (hsv[1] > 0.001 && hsv[2] > 0.001) cpick.h = hsv[0];
  cpick.s = hsv[1];
  cpick.v = hsv[2];
  paintCpick();
}

/**
 * 색 편집을 띄운다. 확인이면 '#rrggbb', 취소면 null 로 끝난다.
 * @param {string} hex    처음 색
 * @param {string} title  머리말 (예: '1번 색 편집')
 */
function openColorPicker(hex, title) {
  const rgb = dye.hexToRgb(hex) || [255, 255, 255];
  $('#cpick-title').textContent = title || '색 편집';
  $('#cpick-old').className = bgClass(dye.rgbToHex(rgb[0], rgb[1], rgb[2]));
  cpick.h = 0;
  setCpickRgb(rgb[0], rgb[1], rgb[2]);
  closeCpickShot();
  $('#cpick').classList.remove('hidden');
  // 일부러 아무 칸에도 초점을 주지 않는다. HEX 칸에 초점이 있으면
  // "치는 중에는 안 건드린다"는 규칙에 걸려 판을 눌러도 그 칸만 옛 값에 멈춰 있다.
  return new Promise((resolve) => { cpick.done = resolve; });
}

function closeColorPicker(hex) {
  $('#cpick').classList.add('hidden');
  closeCpickShot();
  cpick.shot = null;
  const done = cpick.done;
  cpick.done = null;
  if (done) done(hex || null);
}

/* ── 스포이드 ── */

/**
 * 지금 화면을 한 장 찍는다.
 *
 * 찍는 일은 메인이 한다 — 리모콘 창을 잠깐 비켜야 뒤에 있는 게임이 찍히기 때문이다.
 * 왜 캡처 제외로는 안 되는지는 메인의 dye:snap 에 적어 두었다.
 */
async function grabScreenShot() {
  const r = await mm.dye.snap();
  if (!r || r.error) throw new Error((r && r.error) || '화면을 찍지 못했습니다');

  const img = new Image();
  img.src = r.dataUrl;
  await img.decode();

  const w = img.naturalWidth, h = img.naturalHeight;
  if (!w || !h) throw new Error('빈 그림이 왔습니다');
  const cv = document.createElement('canvas');
  cv.width = w; cv.height = h;
  const g = cv.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  // 픽셀은 한 번만 읽어 둔다. 마우스를 움직일 때마다 읽으면 8MB 를 매번 긁는 꼴이다.
  return {
    canvas: cv, data: g.getImageData(0, 0, w, h).data, w: w, h: h,
    origin: { x: r.bounds.x, y: r.bounds.y },
  };
}

function closeCpickShot() {
  $('#cpick-shot').classList.add('hidden');
  $('#cpick-main').classList.remove('hidden');
  document.querySelector('.cpick-box').classList.remove('wide');
  const lo = document.querySelector('.cpick-loupe');
  if (lo) lo.classList.remove('on');
}

function showCpickShot(shot) {
  const cv = $('#cpick-screen');
  // 대화상자 폭에 맞춰 줄여 그린다. 원본 픽셀은 따로 들고 있으므로 색은 손해 보지 않는다.
  const w = Math.min(shot.w, 1200);
  cv.width = w;
  cv.height = Math.max(1, Math.round(shot.h * (w / shot.w)));
  cv.getContext('2d').drawImage(shot.canvas, 0, 0, cv.width, cv.height);
  document.querySelector('.cpick-box').classList.add('wide');
  $('#cpick-main').classList.add('hidden');
  $('#cpick-shot').classList.remove('hidden');
}

/** 찍어 둔 그림 위의 마우스 자리를 원본 픽셀 좌표로 바꾼다. */
function cpickShotAt(e) {
  const shot = cpick.shot;
  const r = $('#cpick-screen').getBoundingClientRect();
  const x = Math.round(((e.clientX - r.left) / r.width) * shot.w);
  const y = Math.round(((e.clientY - r.top) / r.height) * shot.h);
  return {
    x: Math.max(0, Math.min(shot.w - 1, x)),
    y: Math.max(0, Math.min(shot.h - 1, y)),
  };
}

function cpickShotRgb(x, y) {
  const d = cpick.shot.data, i = (y * cpick.shot.w + x) * 4;
  return [d[i], d[i + 1], d[i + 2]];
}

/** 돋보기 — 화면을 줄여 놓았으니 한 픽셀을 확인할 방법이 있어야 한다. */
function paintCpickLoupe(x, y) {
  const z = $('#cpick-zoom'), g = z.getContext('2d');
  const n = 11, cell = z.width / n, mid = (n - 1) / 2;
  g.imageSmoothingEnabled = false;
  g.clearRect(0, 0, z.width, z.height);
  g.drawImage(cpick.shot.canvas, x - mid, y - mid, n, n, 0, 0, z.width, z.height);
  g.strokeStyle = 'rgba(0,0,0,.85)'; g.lineWidth = 2;
  g.strokeRect(mid * cell, mid * cell, cell, cell);
  g.strokeStyle = '#ffffff'; g.lineWidth = 1;
  g.strokeRect(mid * cell + 1, mid * cell + 1, cell - 2, cell - 2);
  const c = cpickShotRgb(x, y);
  $('#cpick-zoom-hex').textContent = dye.rgbToHex(c[0], c[1], c[2]);
  document.querySelector('.cpick-loupe').classList.add('on');
}

/** 색 편집 대화상자 배선. 처음 한 번만 부른다. */
function wireColorPicker() {
  const sv = $('#cpick-sv'), hue = $('#cpick-hue');

  const fromSV = (e) => {
    const r = sv.getBoundingClientRect();
    cpick.s = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    cpick.v = 1 - Math.max(0, Math.min(1, (e.clientY - r.top) / r.height));
    paintCpick();
  };
  const fromHue = (e) => {
    const r = hue.getBoundingClientRect();
    cpick.h = Math.max(0, Math.min(359.9, ((e.clientY - r.top) / r.height) * 360));
    paintCpick();
  };

  for (const pair of [[sv, fromSV], [hue, fromHue]]) {
    const el = pair[0], fn = pair[1];
    el.addEventListener('pointerdown', (e) => {
      // 창 밖으로 끌어도 계속 따라오게. 합성 이벤트로는 실패할 수 있어 감싼다.
      try { el.setPointerCapture(e.pointerId); } catch (_) {}
      cpick.drag = fn;
      fn(e);
    });
    el.addEventListener('pointermove', (e) => { if (cpick.drag === fn) fn(e); });
    el.addEventListener('pointerup', () => { cpick.drag = null; });
    el.addEventListener('pointercancel', () => { cpick.drag = null; });
  }

  $('#cpick-hex').addEventListener('input', (e) => {
    const c = dye.hexToRgb(e.target.value);
    if (c) setCpickRgb(c[0], c[1], c[2]);
  });
  for (const id of ['r', 'g', 'b']) {
    $('#cpick-' + id).addEventListener('input', () => {
      const v = (k) => Math.max(0, Math.min(255, parseInt($('#cpick-' + k).value, 10) || 0));
      setCpickRgb(v('r'), v('g'), v('b'));
    });
  }

  $('#cpick-eye').addEventListener('click', async (e) => {
    const done = btnBusy(e.target, '화면 읽는 중…');
    let shot = null;
    try { shot = await grabScreenShot(); }
    catch (err) { toast('화면을 읽지 못했습니다', err.message, 'bad'); }
    done();
    if (!shot) return;
    cpick.shot = shot;
    showCpickShot(shot);
  });

  const stage = $('#cpick-screen');
  stage.addEventListener('mousemove', (e) => {
    if (!cpick.shot) return;
    const p = cpickShotAt(e);
    paintCpickLoupe(p.x, p.y);
  });
  stage.addEventListener('mouseleave', () => {
    document.querySelector('.cpick-loupe').classList.remove('on');
  });
  stage.addEventListener('click', (e) => {
    if (!cpick.shot) return;
    const p = cpickShotAt(e);
    const c = cpickShotRgb(p.x, p.y);
    setCpickRgb(c[0], c[1], c[2]);
    closeCpickShot();
  });

  $('#cpick-ok').addEventListener('click', () => closeColorPicker(cpickHex()));
  $('#cpick-cancel').addEventListener('click', () => closeColorPicker(null));
  $('#cpick-close').addEventListener('click', () => closeColorPicker(null));
  // 바깥을 눌러도 닫는다
  $('#cpick').addEventListener('click', (e) => { if (e.target.id === 'cpick') closeColorPicker(null); });
  // 엔터로 확인
  $('#cpick').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); closeColorPicker(cpickHex()); }
  });
}

/**
 * 염색 칸의 색 네모를 눌렀을 때. 색 편집을 띄우고, 확인하면 그 칸에 넣는다.
 *
 * 염색 시작과 상관없이 쓸 수 있다 — 색은 미리 정해 두고 나중에 찾는 것이 자연스럽다.
 */
async function pickDyeColor(slot) {
  const cur = dyeCurrent();
  const now = ((cur && cur.colors) || [])[slot] || '#ffffff';
  const hex = await openColorPicker(now, (slot + 1) + '번 색 편집');
  if (hex) await setDyeColor(slot, hex);
}

async function setDyeColor(slot, hex) {
  const cur = dyeCurrent();
  if (!cur) return;
  const colors = cur.colors.slice();
  colors[slot] = hex;
  dyeUI.prefs = await mm.dye.update(cur.id, { colors: colors });
  paintDyeSlots();
  dyeUI.sig = null;   // 목표가 바뀌었으니 다음 바퀴에 다시 찾는다
}

async function setDyeTol(slot, v) {
  const cur = dyeCurrent();
  if (!cur) return;
  const tol = (cur.tol || [5, 5, 5]).slice();
  tol[slot] = Number(v);
  dyeUI.prefs = await mm.dye.update(cur.id, { tol: tol });
  dyeUI.sig = null;
}

/* ── 버전 · 호환성 ──────────────────────────────── */

const LEVEL_STYLE = {
  ok: { cls: 'mark-ok', mark: '✔', text: '호환 확인됨' },
  info: { cls: 'muted', mark: '·', text: '참고할 변경 있음' },
  warn: { cls: 'mark-warn', mark: '▲', text: '주의 — 동작이 달라질 수 있음' },
  error: { cls: 'mark-bad', mark: '✘', text: '위험 — 기능이 깨졌거나 비용이 바뀜' },
};

function changesHtml(changes) {
  if (!changes || !changes.length) return '<p class="muted">차이 없음</p>';
  return changes.map((c) => {
    const s = LEVEL_STYLE[c.level] || LEVEL_STYLE.info;
    return '<div class="compat-item">' +
      '<div><span class="' + s.cls + '">' + s.mark + '</span> <b>' + esc(c.title) + '</b></div>' +
      '<pre class="compat-detail">' + esc(c.detail) + '</pre></div>';
  }).join('');
}

/**
 * 커넥터를 어디서 찾았는지 보여준다.
 *
 * 첫 줄은 왼쪽 버전 표의 첫 줄과 높이를 맞춘다 (.cli-line 은 위 여백이 없다).
 * 못 찾았을 때 앞세우는 것은 "직접 지정"이 아니라 다시 찾기다. 경로를 손으로 짚는 것은
 * 사용자가 할 일이 아니고, 자동 탐색이 실패한다는 것 자체가 대개 마비노기 모바일이
 * 설치되어 있지 않다는 뜻이라 그 답을 먼저 준다.
 */
function paintCliPath(loc) {
  if (!loc) return;
  $('#cli-path-box').innerHTML = loc.found
    ? '<div class="cli-line"><span class="muted">커넥터 위치</span> ' +
      '<span class="mark-ok">✔</span> ' + esc(loc.source) + '</div>' +
      '<p class="hint mono-path">' + esc(loc.path) + '</p>' +
      '<button class="btn btn-tiny" id="cli-detect">다시 찾기</button>'
    : '<div class="cli-line"><span class="muted">커넥터 위치</span> ' +
      '<span class="mark-bad">✘ 찾지 못했습니다</span></div>' +
      '<p class="hint">마비노기 모바일이 설치되어 있으면 아래 버튼으로 찾아냅니다.</p>' +
      '<div class="row-tight">' +
      '<button class="btn btn-primary btn-tiny" id="cli-detect">커넥터 찾기</button>' +
      '<button class="btn btn-tiny" id="cli-change">위치 직접 지정</button></div>' +
      '<details class="mt10"><summary class="hint">찾아본 위치 ' + loc.tried.length + '곳</summary>' +
      '<pre class="compat-detail">' + esc(loc.tried.join('\n')) + '</pre></details>';
}

async function loadCompat(refresh) {
  const [info, res] = await Promise.all([mm.version.info(), mm.version.check(!!refresh)]);

  paintCliPath(info.cliPath);

  // 두 줄이면 충분하다. 제작사(항상 Devcat)나 Electron·Node 버전은 사용자가 할 일이 없는 값이라
  // 자리만 차지한다. 빌드 해시가 필요하면 값에 마우스를 올리면 나온다.
  $('#ver-info').innerHTML = [
    ['모비 커넥터 리모콘', info.app, ''],
    ['MM CLI', info.cliVersion || '읽을 수 없음', info.cliFull || ''],
  ].map(([k, v, tip]) =>
    '<dt>' + esc(k) + '</dt><dd' + (tip ? ' title="' + esc(tip) + '"' : '') + '>' + esc(v) + '</dd>').join('');

  const s = LEVEL_STYLE[res.levelName] || LEVEL_STYLE.info;
  const baseAt = res.baseline && res.baseline.verifiedAt
    ? new Date(res.baseline.verifiedAt).toLocaleString('ko-KR') : null;
  $('#compat-status').innerHTML =
    '<p><span class="' + s.cls + '">' + s.mark + ' ' + esc(s.text) + '</span></p>' +
    (baseAt ? '<p class="muted">기준선 검증 시각: ' + esc(baseAt) + '</p>' : '');
  $('#compat-changes').innerHTML = changesHtml(res.changes);
  return res;
}

/** 시작할 때 한 번. warn 이상이면 모달로 막아 세운다. */
async function startupCompatCheck(opts) {
  const o = opts || {};
  let res;
  try { res = await mm.version.check(o.refresh !== false); }
  catch (_) { return; }

  if (res.firstRun) {
    // 기준선이 없으면 지금 상태를 기준으로 삼는다 (최초 설치)
    await mm.version.accept('최초 실행 시 자동 저장');
    return;
  }
  if (res.levelName === 'ok') return;

  if (res.levelName === 'info') {
    toast('호환성 참고', res.changes.map((c) => c.title).join(' · '));
    return;
  }

  const s = LEVEL_STYLE[res.levelName];
  const ok = await confirmModal(
    (res.levelName === 'error' ? '⚠ 호환성 경고' : '호환성 주의'),
    '<p><span class="' + s.cls + '">' + s.mark + ' ' + esc(s.text) + '</span></p>' +
    '<p class="hint">검증된 기준선과 현재 환경이 다릅니다. 특히 <b>비용이 바뀐 경우 실행 전 확인 창의 금액을 반드시 다시 보세요.</b></p>' +
    '<div class="compat-scroll">' + changesHtml(res.changes) + '</div>',
    '확인하고 계속'
  );
  if (!ok) {
    // 계속하지 않겠다면 옵션 창의 호환성 화면을 보여 준다
    await openOptions();
  }
}

/* ── 옵션 창 ────────────────────────────────────── */

/**
 * 옵션 창.
 *
 * 전에는 "콘솔" 탭이었다. 실제로 쓰이는 방식이 탭보다는 설정 창에 가까워서 —
 * 매일 보는 화면이 아니라 필요할 때 열어 보는 것들이라 — 창으로 옮겼다.
 * 탭 하나가 줄어 매일 쓰는 탭들이 그만큼 가까워진다.
 */
async function openOptions() {
  $('#options').classList.remove('hidden');
  say('옵션 불러오는 중…');
  try {
    await paintOptionSettings();
    if (!caps.length) await loadCaps();
    await loadFileLog();
    say('준비됨');
  } catch (err) {
    say('오류: ' + err.message);
  }
}

function closeOptions() {
  $('#options').classList.add('hidden');
}

/** 설정 카드의 값을 지금 상태로 맞춘다. */
async function paintOptionSettings() {
  let cfg = null;
  try { cfg = await mm.cfg.get(); } catch (_) { return; }
  const el = $('#opt-ask-mismatch');
  if (el) el.checked = cfg.askFacilityLevelMismatch !== false;
}

/* ── 콘솔 ───────────────────────────────────────── */

let caps = [];

async function loadCaps(refresh) {
  caps = await mm.capabilities(!!refresh);
  $('#cmd-select').innerHTML = caps.map((c) => {
    const tag = c.cost ? '  [' + c.cost.currency + ' ' + c.cost.amount + ']' : c.action ? '  [실행]' : '';
    return '<option value="' + esc(c.command) + '">' + esc(c.command) + esc(tag) + '</option>';
  }).join('');
  onCmdChange();
  loadCompat(false);
}

function onCmdChange() {
  const c = caps.find((x) => x.command === $('#cmd-select').value);
  if (!c) return;
  $('#cmd-body').value = c.bodyExample || '';
  $('#cmd-desc').textContent = c.description + (c.note ? ' — ' + c.note.slice(0, 200) : '');
}

async function runRawCommand() {
  const command = $('#cmd-select').value;
  const raw = $('#cmd-body').value.trim();
  let body;
  if (raw) {
    // JSON이면 객체로, 아니면 문자열 그대로 보낸다 (write_chat 같은 평문 본문)
    if (/^[[{]/.test(raw)) {
      try { body = JSON.parse(raw); }
      catch (err) { toast('본문 JSON 오류', String(err.message), 'bad'); return; }
    } else body = raw;
  }
  const c = caps.find((x) => x.command === command) || {};
  const r = await runAction(command, body, { label: command, skipConfirm: !c.costed });
  if (r) $('#cmd-out').textContent = JSON.stringify(r.data, null, 2);
}

async function loadFileLog() {
  const [lines, files] = await Promise.all([mm.log.tail(300), mm.log.files()]);
  $('#file-log').innerHTML = lines.length
    ? lines.slice().reverse().map((l) => {
        const cls = /ERROR/.test(l) ? 'mark-bad' : /WARN/.test(l) ? 'mark-warn' : '';
        return '<div class="' + cls + '">' + esc(l) + '</div>';
      }).join('')
    : '<div class="muted">기록 없음</div>';
  const total = files.reduce((a, f) => a + f.sizeKB, 0);
  $('#log-info').textContent = files.length + '개 파일 · ' + total + 'KB · 최근 ' + lines.length + '줄 표시';
}

/* ── 탭 ─────────────────────────────────────────── */

const LOADERS = {
  dash: loadDash,
  craft: () => (craftCache ? renderCraft() : loadCraft()),
  alter: () => loadAlter(),
  gather: () => (gatherCache ? renderGather() : loadGather()),
  items: () => (itemsCache ? renderItems() : loadItems()),
  mission: () => loadMission(),
  music: () => loadMusic(),
  social: () => loadSocial(),
  dye: () => loadDye(),
};

let activeTab = 'dash';

async function showTab(name) {
  activeTab = name;
  // 연주 진행바는 그 탭을 보고 있을 때만 돈다
  stopPerfWatch();
  // 염색도 마찬가지다. 다만 표시가 켜져 있으면 그대로 둔다 —
  // 게임을 보면서 쓰는 기능이라 탭을 옮겼다고 꺼지면 곤란하다.
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.panel').forEach((p) => p.classList.toggle('active', p.id === 'panel-' + name));
  say(name + ' 불러오는 중…');
  try { await LOADERS[name](); say('준비됨'); }
  catch (err) { say('오류: ' + err.message); }
}

function refreshActive() {
  const R = {
    dash: loadDash, craft: () => loadCraft(true), alter: () => loadAlter(true),
    gather: () => loadGather(true), items: () => loadItems(true), mission: () => loadMission(true),
    music: () => loadMusic(true), social: () => loadSocial(true), dye: () => loadDye(),
  };
  refreshTopbar();
  return R[activeTab]();
}

/* ── 이벤트 배선 ────────────────────────────────── */

function debounce(fn, ms) {
  let t;
  return () => { clearTimeout(t); t = setTimeout(fn, ms || 160); };
}

function wire() {
  $$('.tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));

  // 테마 — 지금 값은 <html data-theme>에 이미 붙어 있다(theme.js). 여기서는 뒤집기만 한다.
  paintThemeBtn();
  $('#btn-theme').addEventListener('click', async () => {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    paintThemeBtn();
    try { await mm.cfg.theme(next); } catch (_) { /* 저장 실패가 화면을 막지 않는다 */ }
  });

  $('#alter-works-fold').addEventListener('click', async () => {
    worksFolded = !worksFolded;
    applyWorksFold();
    try { await mm.cfg.set('alterWorksFolded', worksFolded); } catch (_) {}
  });

  const toggleQueue = async () => {
    const content = $('#content');
    pinContent(content.getBoundingClientRect().width);
    try {
      const before = $('#queue').getBoundingClientRect().width;
      queueFolded = !queueFolded;
      applyQueueFold();
      const after = $('#queue').getBoundingClientRect().width;
      // 큐가 줄어든 만큼 창도 좁힌다. 본문 폭은 붙들어 두었으므로 그대로다.
      try { await mm.win.narrow(before - after); } catch (_) {}
      // 창이 실제로 다 그려진 다음에 놓아준다
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    } finally {
      unpinContent();
    }
    try { await mm.cfg.set('queueFolded', queueFolded); } catch (_) {}
  };
  $('#q-fold').addEventListener('click', toggleQueue);
  $('#q-tag').addEventListener('click', toggleQueue);

  /**
   * 게임 화면과 우리 표시를 **함께** 한 장 찍는다.
   *
   * 평소 오버레이는 화면 캡처에서 빠지도록 해 두었다. 우리가 그린 것이 다음 캡처에 섞여
   * 팔레트로 오인되는 것을 막으려고 그런 것인데, 그 바람에 **사용자의 스크린샷에도 안
   * 찍힌다.** 무엇이 그려지고 있는지 남에게 보여 주려면 모니터를 카메라로 찍어야 했다.
   *
   * 이 버튼은 그 한 장을 위해서만 잠깐 보호를 풀고 찍는다.
   */
  $('#dye-shot').addEventListener('click', async (e) => {
    const done = btnBusy(e.target, '찍는 중…');
    let r = null;
    try { r = await mm.dye.shot(); } catch (err) { r = { error: err.message }; }
    done();
    if (!r || r.error) {
      toast('찍지 못했습니다', (r && (r.message || r.error)) || '', 'bad');
      return;
    }

    // 클립보드는 여기서 넣는다. 메인 쪽 clipboard 는 이 빌드에서 비동기 웹 API 라
    // writeImage 가 없다. 렌더러는 평범한 웹 문맥이라 그냥 된다.
    let copied = false;
    try {
      const blob = new Blob([r.png], { type: 'image/png' });
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      copied = true;
    } catch (_) { /* 창에 초점이 없거나 막혀 있으면 파일만 남는다 */ }

    toast(
      copied ? '클립보드에 복사했습니다' : '파일로 저장했습니다',
      (copied ? '붙여넣기로 바로 쓸 수 있습니다 · ' : '클립보드 복사는 실패했습니다 · ') + r.path,
      'ok');
  });

  wireColorPicker();

  $('#dye-start').addEventListener('click', startDye);
  $('#dye-stop').addEventListener('click', stopDye);
  $('#dye-preset').addEventListener('change', async (e) => {
    dyeUI.prefs = await mm.dye.select(e.target.value);
    paintDyeSlots();
    dyeUI.sig = null;
  });
  $('#dye-new').addEventListener('click', async () => {
    const name = await promptText('새 색 조합', '이름을 정하세요', '내 색');
    if (!name) return;
    dyeUI.prefs = await mm.dye.add(name, ['', '', '']);
    paintDyePresets(); paintDyeSlots();
  });
  $('#dye-rename').addEventListener('click', async () => {
    const cur = dyeCurrent();
    if (!cur) return;
    const name = await promptText('이름 변경', '새 이름', cur.name);
    if (!name) return;
    dyeUI.prefs = await mm.dye.update(cur.id, { name: name });
    paintDyePresets();
  });
  $('#dye-del').addEventListener('click', async () => {
    const cur = dyeCurrent();
    if (!cur) return;
    if (!(await confirmModal('색 조합 삭제', '<p>"' + esc(cur.name) + '" 을(를) 지울까요?</p>', '삭제'))) return;
    dyeUI.prefs = await mm.dye.remove(cur.id);
    paintDyePresets(); paintDyeSlots();
  });
  // 오차 슬라이더는 칸마다 새로 그려지므로 위임으로 받는다
  document.addEventListener('input', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement) || t.dataset.dyeTol === undefined) return;
    const v = $('[data-dye-tolv="' + t.dataset.dyeTol + '"]');
    if (v) v.textContent = t.value;
  });
  document.addEventListener('change', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement) || t.dataset.dyeTol === undefined) return;
    setDyeTol(+t.dataset.dyeTol, t.value);
  });

  $('#q-play').addEventListener('click', () => qTick());
  $('#q-pause').addEventListener('click', qPause);
  $('#q-halt').addEventListener('click', qHalt);
  $('#q-tidy').addEventListener('click', qTidy);
  $('#q-clear').addEventListener('click', qClear);

  $('#btn-options').addEventListener('click', openOptions);
  $('#options-close').addEventListener('click', closeOptions);
  // 바깥을 눌러도 닫는다. 창이 커서 닫기 버튼까지 가기 번거롭다.
  $('#options').addEventListener('click', (e) => { if (e.target.id === 'options') closeOptions(); });
  // Esc 로도 닫는다. 확인 모달이 떠 있을 때는 그쪽이 먼저 받아야 하므로 건너뛴다.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!$('#modal').classList.contains('hidden')) return;
    // 색 편집이 떠 있으면 그쪽이 먼저다. 스포이드 화면이면 고르기로만 돌아간다.
    if (!$('#cpick').classList.contains('hidden')) {
      if (!$('#cpick-shot').classList.contains('hidden')) closeCpickShot();
      else closeColorPicker(null);
      return;
    }
    if (!$('#options').classList.contains('hidden')) closeOptions();
  });
  $('#opt-ask-mismatch').addEventListener('change', async (e) => {
    await mm.cfg.set('askFacilityLevelMismatch', e.target.checked);
    toast('저장했습니다', e.target.checked ? '어긋나면 물어봅니다.' : '묻지 않습니다.', 'ok');
  });

  $('#btn-refresh').addEventListener('click', refreshActive);
  $('#btn-stop').addEventListener('click', () =>
    runAction('stop_action', undefined, { label: '행동 정지', skipConfirm: true }));

  $('#sb-cancel').addEventListener('click', async () => {
    // 실행 중인 명령 하나만 죽이면 여러 단계짜리 작업은 다음 단계로 넘어가 버린다.
    // 반복 루프에도 중단 신호를 같이 보낸다.
    collectAll.aborted = true;
    fillAltering.aborted = true;
    qAbort = true;
    player.stopping = true;
    await mm.cancel();
    say('취소 요청을 보냈습니다.');
  });

  // 게임을 켠 뒤 기다리지 않고 바로 다시 붙을 수 있게 한다
  $('#pl-select').addEventListener('change', (e) => selectPlaylist(e.target.value));
  $('#pl-new').addEventListener('click', async () => {
    const name = await promptText('새 재생목록', '이름을 정하세요', '내 재생목록',
      '커넥터가 캐릭터를 구분해 주지 않으므로, 캐릭터별로 쓰시려면 이름으로 구분하세요 (예: 궁수용).');
    if (!name) return;
    const made = await mm.pl.create(name);
    await refreshPlaylists(made.id);
    try { localStorage.setItem(PL_KEY, made.id); } catch (_) {}
  });
  $('#pl-rename').addEventListener('click', async () => {
    if (!plCurrent) return;
    const name = await promptText('이름 변경', '새 이름', plCurrent.name);
    if (!name) return;
    await mm.pl.update(plCurrent.id, { name });
    await refreshPlaylists(plCurrent.id);
  });
  $('#pl-delete').addEventListener('click', async () => {
    if (!plCurrent) return;
    if (!(await confirmModal('재생목록 삭제', '<p>"' + esc(plCurrent.name) + '" 을(를) 지울까요?</p>', '삭제'))) return;
    await mm.pl.remove(plCurrent.id);
    plCurrent = null;
    await refreshPlaylists();
  });
  $('#pl-loop').addEventListener('change', async (e) => {
    if (!plCurrent) return;
    await mm.pl.update(plCurrent.id, { loop: e.target.checked });
    await refreshPlaylists(plCurrent.id);
  });
  $('#pl-shuffle').addEventListener('change', async (e) => {
    if (!plCurrent) return;
    await mm.pl.update(plCurrent.id, { shuffle: e.target.checked });
    await refreshPlaylists(plCurrent.id);
  });
  $('#pl-play').addEventListener('click', playPlaylist);
  $('#pl-stop').addEventListener('click', stopPlaylist);


  wireUpdate();

  $('#offline-retry').addEventListener('click', async () => {
    // 커넥터를 못 찾은 상태에서는 '다시 확인'이 아무 소용이 없다. 찾기부터 시킨다.
    if ($('#offline-retry').textContent === '커넥터 찾기') {
      say('커넥터를 찾는 중…');
      const loc = await mm.cli.locate(true);
      if (!loc || !loc.found) {
        toast('커넥터를 찾지 못했습니다',
          '마비노기 모바일이 설치되어 있는지 확인하세요. 설치했는데도 안 잡히면 옵션에서 위치를 직접 지정할 수 있습니다.', 'bad');
        say('준비됨');
        return;
      }
      toast('커넥터를 찾았습니다', loc.path, 'ok');
    }

    say('연결 확인 중…');
    const ok = await refreshTopbar();
    if (ok) {
      toast('연결됨', '게임에 다시 연결되었습니다.', 'ok');
      await refreshActive();
    } else {
      toast('아직 연결되지 않았습니다', '게임 실행과 "MM AI 에이전트 활성화"를 확인하세요.', 'bad');
    }
    say('준비됨');
  });

  // 채팅
  const sendChat = async () => {
    const msg = $('#chat-input').value.trim();
    if (!msg) return;
    const r = await runAction('write_chat', msg, { label: '채팅 전송', skipConfirm: true });
    if (r && r.ok) $('#chat-input').value = '';
  };
  $('#chat-send').addEventListener('click', sendChat);
  $('#chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

  // 검색/필터 — 조건이 바뀌면 1쪽으로 되돌린다.
  // 3쪽을 보다 검색하면 결과가 3쪽까지 없어서 "없음"처럼 보인다.
  const refilter = (key, render) => () => { resetPage(key); render(); };

  $('#craft-search').addEventListener('input', debounce(refilter('craft', renderCraft)));
  $('#craft-only-ok').addEventListener('change', refilter('craft', renderCraft));
  $('#alter-search').addEventListener('input', debounce(refilter('alter', renderAlter)));
  $('#alter-only-ok').addEventListener('change', refilter('alter', renderAlter));
  $('#alter-facility').addEventListener('change', refilter('alter', renderAlter));
  $('#alter-level').addEventListener('change', refilter('alter', renderAlter));
  $('#gather-search').addEventListener('input', debounce(renderGather));
  $('#gather-only-ok').addEventListener('change', renderGather);
  $('#items-search').addEventListener('input', debounce(refilter('items', renderItems)));
  $('#items-cat').addEventListener('change', refilter('items', renderItems));
  $('#items-loc').addEventListener('change', refilter('items', renderItems));

  // 페이저는 표마다 붙이지 않고 한곳에서 위임받는다 — 다시 그릴 때마다 사라지는 요소다
  wirePager((key) => { const fn = PAGE_RENDER[key]; if (fn) fn(); });
  wireSort();
  $('#mission-only-open').addEventListener('change', () => loadMission());
  $('#music-search').addEventListener('input', debounce(renderMusic));
  $('#social-search').addEventListener('input', debounce(renderSocial));

  // hex 를 직접 쳐 넣는 경우. 여섯 자리가 다 찼을 때만 저장한다 —
  // 한 글자 칠 때마다 저장하면 파일이 매번 쓰인다.
  document.addEventListener('change', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement) || t.dataset.dyeHex === undefined) return;
    const v = String(t.value || '').trim();
    const hex = /^#?[0-9a-f]{6}$/i.test(v) ? (v[0] === '#' ? v : '#' + v).toUpperCase() : '';
    setDyeColor(+t.dataset.dyeHex, hex);
  });

  $$('[data-refresh]').forEach((b) => b.addEventListener('click', refreshActive));

  // 콘솔
  $('#cmd-select').addEventListener('change', onCmdChange);
  $('#cmd-run').addEventListener('click', runRawCommand);
  $('#caps-refresh').addEventListener('click', () => loadCaps(true));
  $('#log-refresh').addEventListener('click', loadFileLog);
  $('#log-open').addEventListener('click', () => mm.log.open());

  // 호환성
  $('#compat-recheck').addEventListener('click', async () => {
    say('호환성 검사 중…');
    const r = await loadCompat(true);
    toast('호환성 검사', (LEVEL_STYLE[r.levelName] || {}).text || r.levelName, r.ok ? 'ok' : 'bad');
    say('준비됨');
  });
  $('#compat-accept').addEventListener('click', async () => {
    const res = await mm.version.check(false);
    const body = res.changes && res.changes.length
      ? '<p>아래 변경을 정상으로 인정하고 기준선을 갱신합니다.</p><div class="compat-scroll">' + changesHtml(res.changes) + '</div>'
      : '<p>현재 상태를 기준선으로 저장합니다.</p>';
    if (!(await confirmModal('기준선 갱신', body, '저장'))) return;
    await mm.version.accept('사용자가 앱에서 승인');
    await loadCompat(true);
    toast('기준선 갱신됨', '이제부터 이 상태를 기준으로 비교합니다.', 'ok');
  });

  // 표/카드 안의 동작 버튼은 위임으로 처리한다
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;

    // 별표가 먼저다. 칩 안에 들어 있어서, 뒤로 밀리면 표정을 실행해 버린다.
    if (t.dataset.dyePick !== undefined) return void pickDyeColor(+t.dataset.dyePick);
    if (t.dataset.dyeClear !== undefined) return void setDyeColor(+t.dataset.dyeClear, '');

    if (t.dataset.qDel !== undefined) return void qRemove(t.dataset.qDel);
    if (t.dataset.qPlay !== undefined) return void qPlayOne(t.dataset.qPlay);
    if (t.dataset.qPause !== undefined) return void qPauseOne(t.dataset.qPause);
    if (t.dataset.qEdit !== undefined) return void qEdit(t.dataset.qEdit);
    if (t.dataset.qUp !== undefined) return void qMove(t.dataset.qUp, -1);
    if (t.dataset.qDn !== undefined) return void qMove(t.dataset.qDn, 1);

    if (t.dataset.fav) {
      return void (async () => {
        const r = await mm.fav.toggle(t.dataset.fav, t.dataset.favName);
        if (!r || !r.ok) return;
        favCache[r.list] = new Set(r.favorites[r.list]);
        const fn = PAGE_RENDER[r.list];
        if (fn) fn();
      })();
    }

    if (t.dataset.craft) return void doCraft(t.dataset.craft, t.dataset.per);
    if (t.dataset.plan) return void makePlan(t.dataset.plan, t.dataset.planLabel);

    if (t.dataset.gather) return void doGather(t.dataset.gather);
    if (t.dataset.fill) return void fillAltering(t.dataset.fill, t.dataset.fillLabel);
    if (t.dataset.alter) {
      return void (async () => {
        const name = t.dataset.alter;
        const r = await runAction('execute_altering', { displayName: name },
          { label: name + ' 가공',
            note: '가공은 비동기 큐입니다. 등록만 되고 완성까지 시간이 걸립니다. ' +
                  '칸이 꽉 찬 시설이면 이동 후 막혀서 날개만 나가므로 위의 여유 칸을 확인하세요.' });

        loadAlter(true);
      })();
    }
    if (t.dataset.collect) {
      return void (async () => {
        // 시설 하나만 수령해도 이동 때문에 6~10초가 걸린다. 누른 버튼에서 진행을 보여 준다.
        const restore = btnBusy(t, '수령 중…');
        await runAction('complete_altering_work', { displayName: t.dataset.collect },
          { label: '가공 수령', skipConfirm: true });
        restore();
        loadAlter(true);
      })();
    }
    if (t.dataset.roomLevel) {
      return void (async () => {
        if (await askFacilityLevel(t.dataset.roomLevel, parseInt(t.dataset.roomLv, 10))) loadAlter(true);
      })();
    }
    if (t.id === 'collect-all') return void collectAll();
    if (t.id === 'cli-detect') {
      return void (async () => {
        const done = btnBusy(t, '찾는 중…');
        let loc = null;
        try { loc = await mm.cli.locate(true); }
        catch (err) { done(); toast('찾지 못했습니다', err.message, 'bad'); return; }
        done();
        await loadCompat(true);
        await refreshTopbar();
        if (loc.found) {
          toast('커넥터를 찾았습니다', loc.path, 'ok');
        } else {
          // 여기까지 왔으면 경로보다 설치 여부부터 의심하는 것이 맞다
          toast('커넥터를 찾지 못했습니다',
            '마비노기 모바일이 설치되어 있지 않은 것 같습니다.', 'bad');
        }
      })();
    }
    if (t.id === 'cli-change') {
      return void (async () => {
        const r = await mm.cli.choose();
        if (r.canceled) return;
        if (r.error === 'wrong_file') {
          toast('다른 파일입니다', r.expected + ' 를 선택하세요.', 'bad');
          return;
        }
        if (r.ok) {
          toast('커넥터 위치를 지정했습니다', r.path, 'ok');
          await loadCompat(true);
          await refreshTopbar();
        } else {
          toast('지정한 위치에서 실행 파일을 찾을 수 없습니다', '', 'bad');
        }
      })();
    }
    if (t.dataset.instrument) {
      return void runAction('change_instrument', { name: t.dataset.instrument },
        { label: t.dataset.instrument + ' 장착', skipConfirm: true }).then(() => loadMusic(true));
    }
    if (t.dataset.plAdd) {
      return void (async () => {
        if (!plCurrent) { toast('재생목록이 없습니다', '먼저 새로 만들기를 누르세요.', 'bad'); return; }
        await mm.pl.addTrack(plCurrent.id, t.dataset.plAdd);
        await refreshPlaylists();
        say('담았습니다: ' + t.dataset.plAdd);
      })();
    }
    if (t.dataset.plDel !== undefined) {
      return void (async () => {
        await mm.pl.removeTrack(plCurrent.id, parseInt(t.dataset.plDel, 10));
        await refreshPlaylists();
      })();
    }
    if (t.dataset.plMove !== undefined) {
      return void (async () => {
        await mm.pl.moveTrack(plCurrent.id, parseInt(t.dataset.plMove, 10), parseInt(t.dataset.plDelta, 10));
        await refreshPlaylists();
      })();
    }
    if (t.dataset.play) {
      return void runAction('play_music_score', { title: t.dataset.play },
        { label: '연주: ' + scoreLabel(t.dataset.play), skipConfirm: true });
    }
    // 일어서기처럼 전용 명령을 쓰는 항목. 목록에서는 다른 행동과 같은 자리에 있다.
    if (t.dataset.socialRun) {
      return void runAction(t.dataset.socialRun, undefined,
        { label: t.dataset.socialName || t.dataset.socialRun, skipConfirm: true });
    }
    if (t.dataset.socialCmd) {
      return void runAction('write_chat', t.dataset.socialCmd,
        { label: '소셜: ' + t.dataset.socialCmd, skipConfirm: true });
    }
    // 표정은 이름이 아니라 이모지를 보내야 한다.
    // 행동은 /전통댄스 같은 ChatCommands를 쓰지만, 표정에는 ChatCommands가 아예 없고
    // EmojiText만 있다. "/미소"처럼 보내면 unsupported_command로 거부된다.
    if (t.dataset.socialEmoji) {
      return void runAction('write_chat', t.dataset.socialEmoji,
        { label: '표정: ' + (t.dataset.socialName || t.dataset.socialEmoji), skipConfirm: true });
    }
  });

}

/* ── 시작 ───────────────────────────────────────── */

(async function start() {
  wire();

  // 표를 그리기 전에 정렬 기준과 즐겨찾기를 읽어 둔다.
  // 나중에 읽으면 기본 순서로 한 번 그렸다가 튄다.
  await loadSortPrefs();
  await loadFavorites();
  try {
    const c = await mm.cfg.get();
    worksFolded = c.alterWorksFolded === true;
    queueFolded = c.queueFolded === true;
  } catch (_) { /* 설정을 못 읽어도 펼친 채로 돈다 */ }
  applyQueueFold();
  // 접힌 채로 뜬다면 창도 그만큼 좁혀 둔다. 창 크기는 저장하지 않으므로 기본 폭으로 뜬다.
  if (queueFolded) {
    const now = $('#queue').getBoundingClientRect().width;
    const wide = queueWideWidth();
    if (wide > now) {
      pinContent($('#content').getBoundingClientRect().width);
      try { await mm.win.narrow(wide - now); } catch (_) {}
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      unpinContent();
    }
  }
  await loadQueue();

  // 1단계 — 캐시만으로 화면을 즉시 띄운다.
  // 게임이 꺼져 있으면 CLI가 연결 실패를 판정하는 데만 약 5초가 걸린다.
  // 그 사이 빈 창을 보여주지 않으려고, 먼저 오프라인으로 가정하고 그린다.
  online = false;
  say('마지막 정보로 표시 중…');
  await showTab('dash');

  // 2단계 — 실제 연결 상태를 확인한다 (연결돼 있으면 100ms, 아니면 약 5초)
  const ok = await refreshTopbar();
  if (!ok) {
    say('게임에 연결되지 않았습니다.');
    toast('연결 안 됨', '게임 실행 및 "MM AI 에이전트 활성화" 설정을 확인하세요.', 'bad');
  }

  // 게임이 꺼져 있으면 capabilities를 새로 받을 수 없으므로 캐시된 목록으로 검사한다
  await startupCompatCheck({ refresh: ok });

  // 3단계 — 연결돼 있으면 실시간 값으로 다시 채운다 (바뀐 부분만 다시 그려진다)
  if (ok) {
    await refreshActive();
    say('준비됨');
  }

  // 가공이 칸 부족으로 막히면 메인이 칸 수를 확정하고 알려 준다.
  // 날개가 이미 나간 실패지만, 최소한 다음부터는 헛되이 넘치지 않는다.
  mm.onFacilityLevel((d) => {
    toast(d.facility + ' — 레벨 ' + d.level + ' 확인',
      '칸이 꽉 차서 막혔습니다. 최대 ' + d.slots + '칸으로 기록했습니다. 틀렸다면 Lv 배지에서 고치세요.', 'ok');
    if (activeTab === 'alter') loadAlter(true);
  });

  initAuto();
})();
