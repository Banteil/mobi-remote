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
function confirmModal(title, bodyHtml, okLabel, cancelLabel) {
  return new Promise((resolve) => {
    $('#modal-title').textContent = title;
    $('#modal-body').innerHTML = bodyHtml;
    $('#modal-ok').textContent = okLabel || '실행';
    $('#modal-cancel').textContent = cancelLabel || '취소';
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

/** 날개가 드는 명령이면 비용을 보여 주고 묻는다. 해도 되면 cost 정보, 아니면 null. */
async function confirmCost(command, o) {
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
  return cost;
}

async function runAction(command, body, opts) {
  const o = opts || {};
  if (busy) {
    toast('실행 중', '이전 명령이 끝난 뒤 다시 시도하세요.', 'bad');
    return null;
  }
  const cost = await confirmCost(command, o);
  if (!cost) return null;

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

/* 작업 큐(파이썬)가 부른 명령: 시작·끝을 화면에서 runAction 과 똑같이 알린다 (origin 이 있는 것만 — 화면이 부른 것은 runAction 이 알린다) */
mm.onExecStart((m) => {
  if (m && m.origin) setBusy(true, (m.origin.label || m.command) + ' 실행 중…');
});
mm.onExecDone((m) => {
  if (!m || !m.origin) return;
  setBusy(false);
  const label = m.origin.label || m.command;
  if (!m.origin.quiet) {
    if (m.ok) {
      toast('완료 — ' + label, describeResult(m.command, m.data) + ' (' + m.durationMs + 'ms)' +
        (m.wingsSpent ? ' · 날개 ' + m.wingsSpent + ' 소모' : ''), 'ok');
    } else if (m.ko) {
      toast('실패 — ' + label + ': ' + m.ko.text, m.ko.hint || '', 'bad');
    } else {
      toast('실패 — ' + label, (m.error || '') + (m.message ? ' · ' + m.message : ''), 'bad');
    }
    logCall(m.command, m);
  }
  refreshTopbar();
  const re = typeof ACT_REFRESH !== 'undefined' && ACT_REFRESH[m.origin.act];
  if (re) re();
});

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
      '마비노기 모바일 커넥터를 찾지 못했습니다. 게임을 설치한 뒤 커넥터 찾기를 누르세요.';
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

  if (me && me.error) {
    // 로그인·캐릭터 선택 화면(not_in_game) — 접속 중인 캐릭터가 없다. 옛 이름·정보를 남기지 않는다
    $('#charname').textContent = me.error === 'not_in_game' ? '접속 중인 캐릭터 없음' : '—';
    $('#charname').title = me.message || '';
    $('#charsub').textContent = '';
    $('#weight').textContent = '—';
  }
  if (me && !me.error) {
    // get_my_info는 캐릭터명을 주지 않는다. Title은 착용 타이틀, RealmName은 서버다.
    // 이름은 게임 화면 왼쪽 위를 읽어 온다 (chars.nameNow) — 못 읽었으면 레벨·직업만.
    const lv = 'Lv.' + me.level + ' ' + me.job;
    $('#charname').textContent = topName || lv;
    $('#charname').title = topName ? '게임 화면에서 읽은 이름' : '';
    $('#charsub').textContent = (topName ? lv + ' · ' : '') + (me.title ? '「' + me.title + '」 · ' : '') + me.realm;
    $('#weight').textContent = me.weightPct + '%';
  }
  if (wings && !wings.error) $('#wings').textContent = num(wings.amount);
  return true;
}

/** 지금 캐릭터 이름 (게임 창 왼쪽 위 OCR, 15초마다). 게임이 꺼졌거나 접속 중이 아니면 ''. */
let topName = '';

async function refreshTopbar() {
  const st = await mm.status();
  if (!st.connected) { await updateNameNow(st); return paintTopbar(st); }
  const r = await mm.queryMany(['me', 'wings'], dashOpts());
  await updateNameNow(st, r.me);
  return paintTopbar(st, r.me, r.wings);
}

/** 지금 캐릭터 이름을 새로 받는다. 게임이 꺼졌거나 접속 중이 아니면(캐릭터 선택·로딩 = me 조회 실패) 지운다.
 * 바뀌면 캐릭터 탭 카드(노란 테두리)도 다시 그린다. */
async function updateNameNow(st, me) {
  const before = topName;
  if (!st || !st.connected || !me || me.error) topName = '';
  else { try { const n = await mm.chars.nameNow(); topName = n ? n.name || '' : topName; } catch (_) {} }
  if (topName !== before && typeof paintChars === 'function' && ch.data) paintChars();
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
      await updateNameNow(st);
      paintTopbar(st);
      autoStatus('게임 연결 끊김 — ' + Math.round(OFFLINE_MIN_MS / 1000) + '초마다 재확인');
    } else {
      // 상단바와 대시보드가 같은 조회를 나눠 쓴다 (me를 두 번 받지 않도록)
      const onDash = activeTab === 'dash';
      const names = onDash ? DASH_QUERIES.concat(['wings']) : ['me', 'wings'];
      const r = await mm.queryMany(names, dashOpts());
      await updateNameNow(st, r.me);
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
  paint('#dash-char', m.error ? '<dt class="muted">' + (m.error === 'not_in_game' ? '접속 중인 캐릭터 없음' : '조회 실패') +
    '</dt><dd></dd>' : [
    ['이름', topName || '—'], ['타이틀', m.title || '(없음)'], ['레벨', m.level], ['직업', m.job], ['서버(렐름)', m.realm],
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

function doGather(name) {
  actNow({ act: 'gather', command: 'execute_gathering', body: { displayName: name },
    label: name + ' 채집', detail: '1회 (최대 100개)', note: '1회 최대 100개' });
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
    '<p class="hint">기준선과 다릅니다 — <b>비용이 바뀌었으면 확인 창 금액을 꼭 보세요.</b></p>' +
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
    try { await loadPathSettings(); } catch (_) {}  // 일일 숙제 폴더 (daily.js)
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
  const tray = $('#opt-close-to-tray');
  if (tray) tray.checked = cfg.closeToTray === true;
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

let activeTab = 'chars';

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
    daily: () => LOADERS.daily(), abyss: () => LOADERS.abyss(), chars: () => LOADERS.chars(),
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
    // 파이썬판은 파이썬이 이미 클립보드에 넣고 copied 로 알려 준다
    let copied = r.copied === true;
    if (r.png) {
      try {
        const blob = new Blob([r.png], { type: 'image/png' });
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        copied = true;
      } catch (_) { /* 창에 초점이 없거나 막혀 있으면 파일만 남는다 */ }
    }

    toast(
      copied ? '클립보드에 복사했습니다' : '파일로 저장했습니다',
      (copied ? '붙여넣기로 바로 쓸 수 있습니다 · ' : '클립보드 복사는 실패했습니다 · ') + r.path,
      'ok');
  });

  wireColorPicker();

  /*
   * 화살표 키로 커서 1px.
   *
   * 켜 두는 동안 화살표를 **전역으로** 가로채므로, 켜고 끄는 것은 사람이 쥔다.
   * 설정에는 남기지 않는다 — 다음에 켰을 때 저도 모르게 화살표가 안 듣는 상태로
   * 시작하면 무엇이 문제인지 알아내기 어렵다.
   */
  /*
   * Ctrl+Alt+WASD 로 커서 1px.
   *
   * 전역 단축키라 켜 둔 동안 다른 프로그램에서도 이 조합을 못 쓴다. 그래서 켜고 끄는
   * 것을 사람이 쥔다. 설정에 남아 다음에 켤 때 그대로 걸린다.
   */
  $('#dye-nudge').addEventListener('change', async (e) => {
    const on = e.target.checked;
    await mm.cfg.set('dyeNudge', on);
    const r = await mm.cursorNudge(on).catch(() => null);
    if (on && (!r || !r.ok)) {
      e.target.checked = false;
      await mm.cfg.set('dyeNudge', false);
      $('#dye-nudge-msg').textContent = (r && r.error) || '켜지 못했습니다';
      return;
    }
    $('#dye-nudge-msg').textContent = '';
  });

  // 켜 둔 채로 떴으면 바로 걸어 둔다.
  (async () => {
    const c = await mm.cfg.get().catch(() => null);
    if (!c || c.dyeNudge !== true) return;
    $('#dye-nudge').checked = true;
    const r = await mm.cursorNudge(true).catch(() => null);
    if (!r || !r.ok) $('#dye-nudge-msg').textContent = (r && r.error) || '켜지 못했습니다';
  })();

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

  $('#q-play').addEventListener('click', qPlayAll);
  $('#q-pause').addEventListener('click', qPause);
  $('#q-halt').addEventListener('click', qHalt);
  $('#q-tidy').addEventListener('click', qTidy);
  $('#q-history').addEventListener('click', showQueueHistory);
  $('#q-hist-close').addEventListener('click', () => $('#q-hist').classList.add('hidden'));
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

  $('#opt-close-to-tray').addEventListener('change', async (e) => {
    await mm.cfg.set('closeToTray', e.target.checked);
    toast('저장했습니다', e.target.checked
      ? '창을 닫으면 트레이에 남습니다.'
      : '창을 닫으면 프로그램도 함께 끝납니다.', 'ok');
  });

  $('#btn-refresh').addEventListener('click', refreshActive);
  $('#btn-stop').addEventListener('click', () =>
    runAction('stop_action', undefined, { label: '행동 정지', skipConfirm: true }));

  $('#sb-cancel').addEventListener('click', async () => {
    // 실행 중인 명령 하나만 죽이면 여러 단계짜리 작업은 다음 단계로 넘어가 버린다.
    // 반복 루프에도 중단 신호를 같이 보낸다.
    waitForUserInput.aborted = true;
    fillAltering.aborted = true;
    if (qRunning) mm.queue.pause();  // 명령은 아래 mm.cancel 이 끊는다
    player.stopping = true;
    await mm.cancel();
    say('취소 요청을 보냈습니다.');
  });

  // 게임을 켠 뒤 기다리지 않고 바로 다시 붙을 수 있게 한다
  $('#pl-select').addEventListener('change', (e) => selectPlaylist(e.target.value));
  $('#pl-new').addEventListener('click', async () => {
    const name = await promptText('새 재생목록', '이름을 정하세요', '내 재생목록',
      '캐릭터별로 쓰려면 이름으로 구분 (예: 궁수용)');
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
          '게임이 설치되어 있는지 확인하세요. 옵션에서 위치를 직접 지정할 수도 있습니다.', 'bad');
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
      return void actNow({ act: 'alter', command: 'execute_altering', body: { displayName: t.dataset.alter },
        label: t.dataset.alter + ' 가공', detail: '가공 1회 등록', note: '칸이 꽉 차면 날개만 나갑니다 — 여유 칸 확인' });
    }
    if (t.dataset.collect || t.dataset.collectGoal) {
      const name = t.dataset.collect || t.dataset.collectGoal;
      return void (t.dataset.collect ? actNow : actGoal)({ act: 'collect', command: 'complete_altering_work',
        body: { displayName: name }, label: name + ' 수령', detail: '가공 완료분 수령', skipConfirm: true });
    }
    if (t.dataset.roomLevel) {
      return void (async () => {
        if (await askFacilityLevel(t.dataset.roomLevel, parseInt(t.dataset.roomLv, 10))) loadAlter(true);
      })();
    }
    if (t.id === 'collect-all' || t.id === 'collect-all-goal') {
      return void (t.id === 'collect-all' ? actNow : actGoal)({ act: 'collectAll', label: '가공 완료분 전체 수령',
        detail: '완료된 시설 모두', skipConfirm: true });
    }
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
    if (t.dataset.play || t.dataset.playGoal) {
      const title = t.dataset.play || t.dataset.playGoal;
      return void (t.dataset.play ? actNow : actGoal)({ act: 'play', command: 'play_music_score', body: { title },
        label: '연주: ' + scoreLabel(title), detail: '연주 1곡', skipConfirm: true });
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
