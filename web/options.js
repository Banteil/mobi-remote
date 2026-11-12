'use strict';
/* 옵션 창 — 버전·호환성 · 패킷 감시(Npcap) · 설정 · 작업 큐 오버레이 · 콘솔. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

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

/** 패킷 감시 상태. 없어도 리모콘은 화면·CLI 로 돌고, 있으면 상태를 더 빨리 안다 */
function packetHtml(st) {
  const npcap = ' <button class="btn btn-tiny" data-npcap>Npcap 받기</button>';
  return ({
    running: '<span class="mark-ok">✔ 켜짐</span>',
    starting: '<span class="muted">켜는 중…</span>',
    no_npcap: '<span class="mark-warn">Npcap 이 없습니다</span>' + npcap +
      ' <button class="btn btn-tiny" data-packet-retry>다시 확인</button>' +
      '<div class="hint">설치한 뒤 다시 확인을 누르면 켜집니다. 없어도 화면·CLI 로 돕니다.</div>',
    no_table: '<span class="mark-warn">패킷 표·키가 없어 꺼져 있습니다</span>',
    stale_table: '<span class="mark-warn">게임이 업데이트돼 패킷 표가 맞지 않아 꺼 두었습니다</span>' +
      '<div class="hint">CLI·화면으로 돕니다. 새 판 리모콘을 받으면 다시 켜집니다.</div>',
    off: '<span class="muted">설정에서 꺼 둠</span>',
  })[st] || '<span class="mark-warn">켜지 못했습니다 (로그 확인)</span>';
}

/** 켤 때 Npcap 이 없으면 위에 띠를 띄운다 (포터블판은 설치 화면이 없어 여기서 알린다). '다시 묻지 않기' 면 옵션 창에만 */
async function wireNpcap() {
  const hide = () => $('#npcap-banner').classList.add('hidden');
  $('#npcap-later').addEventListener('click', hide);
  $('#npcap-noask').addEventListener('click', async () => {
    setPref('npcapNoAsk', true);
    hide();
    toast('다시 묻지 않습니다', '옵션 창 버전 칸의 패킷 감시 줄에서 언제든 받을 수 있습니다.', 'ok');
  });
  document.addEventListener('click', async (e) => {
    if (e.target.closest('[data-npcap]')) { mm.version.npcap(); return; }
    const b = e.target.closest('[data-packet-retry]');
    if (!b) return;
    b.disabled = true;
    const r = await mm.version.packetRetry().catch(() => null);
    b.disabled = false;
    const st = r && r.status;
    if (st === 'running' || st === 'starting') {
      hide();
      toast('패킷 감시를 켰습니다', '', 'ok');
    } else {
      toast('아직 Npcap 을 찾지 못했습니다', '설치를 마친 뒤 다시 눌러 주세요.', 'bad');
    }
    if (!$('#options').classList.contains('hidden')) loadCompat(false);
  });
  setTimeout(async () => {
    const info = await mm.version.info().catch(() => null);
    if (!pref('npcapNoAsk', false) && info && info.packet === 'no_npcap') $('#npcap-banner').classList.remove('hidden');
  }, 5000);
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
    '<dt>' + esc(k) + '</dt><dd' + (tip ? ' title="' + esc(tip) + '"' : '') + '>' + esc(v) + '</dd>').join('') +
    '<dt>새 판</dt><dd><button class="btn btn-tiny" id="upd-check">새 판 확인</button> <span class="muted" id="upd-msg"></span>' +
      ' <button class="btn btn-tiny btn-ghost" id="upd-notes">패치 내역</button></dd>' +
    '<dt>패킷 감시</dt><dd>' + packetHtml(info.packet) + '</dd>';

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
    try { await loadOptionSettings(); } catch (_) {}  // 숙제 쪽 키·폴더·게임 단축키 (daily.js)
    if (!caps.length) await loadCaps();
    await loadFileLog();
    say('준비됨');
  } catch (err) {
    say('오류: ' + err.message);
  }
}

/** 옵션 창 탭. 마지막에 본 탭을 기억한다 (이 PC 에서만). */
function showOptionPane(name, remember = true) {
  if (!$('.opt-pane[data-pane="' + name + '"]')) name = 'general';
  $$('.opt-tab').forEach((t) => t.classList.toggle('active', t.dataset.pane === name));
  $$('.opt-pane').forEach((p) => p.classList.toggle('hidden', p.dataset.pane !== name));
  $('#options .modal-scroll').scrollTop = 0;
  if (remember) setPref('optPane', name);
}

/** 숙제 탭 안쪽 탭 (일일 · 주간 · 기타). 마지막에 본 탭을 기억한다 (remember — 시작할 때 되살리는 것은 다시 적지 않는다). */
function showHomeworkPane(name, remember = true) {
  if (!$('.hw-pane[data-hw="' + name + '"]')) name = 'daily';
  $$('.hw-tab').forEach((t) => t.classList.toggle('active', t.dataset.hw === name));
  $$('.hw-pane').forEach((p) => p.classList.toggle('hidden', p.dataset.hw !== name));
  if (remember) setPref('hwPane', name);
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
  paintOverlayOptions(await mm.cfg.overlay().catch(() => null));
}

/* 작업 큐 오버레이 (gui_app/queue_overlay.py) — 바꾸는 즉시 저장하고 오버레이에 반영한다 */
const OV_KEYS = ['when', 'bg', 'size', 'corner', 'dx', 'dy', 'next', 'alpha'];
const OV_NUM = ['dx', 'dy', 'next', 'alpha'];

function paintOverlayOptions(o) {
  if (!o) return;
  $('#ov-on').checked = !!o.on;
  OV_KEYS.forEach((k) => { $('#ov-' + k).value = String(o[k]); });
  $('#ov-alpha-n').textContent = o.alpha + '%';
  $('.ov-alpha').classList.toggle('hidden', o.bg !== 'panel');
}

async function saveOverlayOptions() {
  const v = { on: $('#ov-on').checked };
  OV_KEYS.forEach((k) => { v[k] = OV_NUM.includes(k) ? Number($('#ov-' + k).value) : $('#ov-' + k).value; });
  paintOverlayOptions(await mm.cfg.overlay(v));
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
