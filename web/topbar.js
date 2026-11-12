'use strict';
/* 상단바 (연결·캐릭터·날개·무게) · 자동 갱신. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

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
  if (topName !== before && ch.data) paintChars();  // 시작이 끝난 뒤에만 불린다 (main.js · 자동 갱신)
}

/* ── 자동 갱신 ──────────────────────────────────── */

/**
 * 게임은 변경을 알려주지 않는다(푸시/구독 명령이 없다). 그래서 폴링뿐인데,
 * 조회는 로컬 클라이언트 메모리에서 나오므로 게임 서버에는 부담이 없다.
 * 대신 다음을 지켜 불필요한 호출과 화면 튐을 막는다.
 *   - 창이 숨겨져 있으면(최소화·트레이) 건너뛴다
 *   - 창에 포커스가 없고 마지막 조작에서 IDLE_MS 가 지났으면 건너뛴다 (보는 사람이 없다)
 *     게임은 AI 에이전트를 오래 쉬지 않고 쓰면 행동 명령을 막는다 — 2026-11-13 밤새 10초마다 조회가 이어진 뒤
 *     04:45 가공 수령이 막혔다 (blocked · continuous_run_limit)
 *   - 대시보드 탭이 아닐 때는 상단바만 갱신한다
 *   - 명령 실행 중에는 건너뛴다 (CLI가 동시 호출을 거부한다)
 *   - 값이 그대로면 DOM을 건드리지 않는다 (paint 참고)
 * setInterval이 아니라 setTimeout 연쇄라, 한 번이 느려도 호출이 겹치지 않는다.
 */
let autoTimer = null;
let autoRunning = false;

/** 창을 안 보고 있다고 볼 때까지의 시간. 포커스가 없어도 이 시간 안에 조작했으면 계속 갱신한다 (옆 모니터에 띄워 둔 경우). */
const IDLE_MS = 5 * 60 * 1000;
let lastSeen = Date.now();

function watching() {
  return document.hasFocus() || Date.now() - lastSeen < IDLE_MS;
}

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
  if (!watching()) {
    autoStatus('보고 있지 않아 멈춤 — 창을 누르면 다시');
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
  const saved = pref('autoInterval', null);
  if (saved !== null && $('#auto-interval').querySelector('option[value="' + saved + '"]')) {
    $('#auto-interval').value = saved;
  }
  $('#auto-interval').addEventListener('change', () => {
    setPref('autoInterval', $('#auto-interval').value);
    autoStatus(autoIntervalMs() ? '' : '꺼짐');
    scheduleAuto();
  });
  // 창이 다시 보이거나 다시 잡으면 기다리지 않고 바로 한 번 갱신한다
  const back = () => {
    const idle = !watching();
    lastSeen = Date.now();
    if (idle && !document.hidden && autoIntervalMs()) {
      clearTimeout(autoTimer);
      tickAuto();
    }
  };
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && autoIntervalMs()) {
      lastSeen = Date.now();
      clearTimeout(autoTimer);
      tickAuto();
    }
  });
  window.addEventListener('focus', back);
  for (const ev of ['pointerdown', 'keydown', 'wheel']) document.addEventListener(ev, back, { passive: true });
  scheduleAuto();
}
