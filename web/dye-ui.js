'use strict';
/* 염색 도우미 탭. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 염색 도우미 ────────────────────────────────────────── */

/**
 * 게임 화면을 읽어 원하는 색이 팔레트 어디에 있는지 짚어 준다.
 *
 * 커넥터를 전혀 쓰지 않는다. 화면 픽셀만 읽고 게임에는 아무것도 보내지 않으며,
 * 찍는 것은 사람이 찍는다. 정령의 날개도 들지 않는다.
 * 화면 읽기·판정은 파이썬(gui_app/dye_service.py · mabi/dye)이 하고, 여기는 프리셋 편집과
 * 한 바퀴마다 오는 결과('mm:dye-state')를 그리기만 한다.
 */

const dyeUI = {
  on: false,
  box: null,        // 파이썬이 찾아 둔 팔레트 (상태 표시용)
  prefs: null,
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
    $('#update-go').textContent = r.kind === 'patch' ? '바꾸고 다시 켜기' : '설치하고 다시 켜기';
    showUpdate(r.kind === 'patch'
      ? '내려받았습니다 — 누르면 프로그램이 꺼졌다가 새 판으로 다시 켜집니다.'
      : '내려받았습니다 — 누르면 프로그램이 꺼지고 설치가 시작됩니다.', true);
  });

  // 켜자마자 묻지 않는다. 첫 화면이 다 그려진 뒤에 조용히 확인한다.
  setTimeout(checkUpdate, 4000);

  // 옵션 창 '새 판 확인' — 다시 켜지 않고 그 자리에서 묻는다 (버전 칸은 옵션을 열 때마다 새로 그려진다)
  document.addEventListener('click', async (e) => {
    if (e.target.closest('[data-upd-go]')) { $('#update-go').click(); return; }  // 위 알림 띠의 버튼과 같은 일
    if (!e.target.closest('#upd-check')) return;
    const msg = $('#upd-msg');
    msg.textContent = '확인 중…';
    const r = await checkUpdate();
    if (r && r.ok && r.newer) {
      msg.innerHTML = esc(r.version) + ' 이 나왔습니다 <button class="btn btn-tiny btn-primary" data-upd-go>받아서 설치</button>';
      return;
    }
    msg.textContent = !r || !r.ok ? '확인하지 못했습니다' + (r && r.error ? ' — ' + r.error : '') : '최신입니다';
  });
}

/** 새 판을 묻고, 있으면 위에 띠를 띄운다. 물어본 결과를 돌려준다 (받는 중이면 묻지 않는다) */
async function checkUpdate() {
  if (updUI.busy) return { ok: true, newer: true, version: updUI.info && updUI.info.version };
  const r = await mm.update.check().catch(() => null);
  if (!r || !r.ok || !r.newer) return r;      // 켤 때는 못 물어봤거나 최신이면 아무 말도 안 한다
  if (!updUI.info || updUI.info.version !== r.version) { updUI.info = r; updUI.file = null; }
  // 패치(코드만, 수 MB)인지 설치 파일 전체인지 크기로 알려 준다
  const a = r.asset;
  const size = a && a.size ? ' (' + (a.kind === 'patch' ? '패치 ' : '') + (a.size / 1048576).toFixed(1) + 'MB)' : '';
  if (!updUI.file) showUpdate('새 판이 나왔습니다 — ' + r.version + size, true);
  else $('#update-banner').classList.remove('hidden');
  return r;
}

/* ══ 새 판 알림 끝 ══════════════════════════════════════════════ */

/* ── 시작 / 중지 ── */

async function startDye() {
  if (dyeUI.on) return;
  // 캡처와 검출은 파이썬이 한다 (웹 화면에는 데스크톱 캡처가 없다). 여기는 받은 상태를 그리기만 한다.
  const r = await mm.dye.start().catch((e) => ({ error: e.message }));
  if (!r || r.error) { toast('염색 도우미를 켜지 못했습니다', r && r.error, 'bad'); return; }
  dyeUI.on = true;
  paintDyeState();
  say('염색 대기 — 팔레트가 뜨면 표시합니다.');
}

async function stopDye() {
  dyeUI.on = false;
  await mm.dye.stop().catch(() => {});
  paintDyePreview(null);
  paintDyeState();
  paintDyeInfo(null);
  say('염색 도우미를 껐습니다.');
}

/** 파이썬이 한 바퀴마다 보내는 상태 — payload 는 레거시 mm.dye.draw 와 같은 모양이다 */
function onDyeState(m) {
  if (!m) return;
  if (m.started) {
    if (!dyeUI.on) { dyeUI.on = true; paintDyeState(); say('염색 대기 — 팔레트가 뜨면 표시합니다.'); }
    return;
  }
  if (m.stopped) {
    if (dyeUI.on) { dyeUI.on = false; dyeUI.box = null; paintDyeState(); paintDyePreview(null); }
    return;
  }
  if (m.error) { say('염색 검출 오류: ' + m.error); return; }
  paintDyePreview(m.payload);
  paintDyeInfo(m.info && m.info.box ? m.info : null);
  const box = (m.info && m.info.box) || null;
  if (!box !== !dyeUI.box) { dyeUI.box = box; paintDyeState(); }  // '팔레트 찾음' ↔ '기다리는 중'
  if (m.done) {
    dyeUI.on = false;
    paintDyeState();
    toast('염색이 끝나 도우미를 껐습니다', '확정 화면이 떠서 자동으로 중지했습니다.', 'ok');
  }
}
mm.dye.onState(onDyeState);

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
  $('#dye-found').innerHTML = marks.some(Boolean)
    ? marks.map((m, i) => !m ? '' :
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
}

async function setDyeTol(slot, v) {
  const cur = dyeCurrent();
  if (!cur) return;
  const tol = (cur.tol || [5, 5, 5]).slice();
  tol[slot] = Number(v);
  dyeUI.prefs = await mm.dye.update(cur.id, { tol: tol });
}
