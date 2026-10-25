'use strict';
/**
 * 캐릭터 탭 — 게임의 캐릭터 선택 화면처럼 카드로 보여 주고, 카드를 누르면 캐릭터별 숙제 설정을 열고, 오른쪽 위 ✕ 로 숙제 목록에서 제외한다.
 * app.js 의 $, esc, toast, say, confirmModal, LOADERS 를 같이 쓴다.
 *
 * 설정 창에는 '기본값' 대신 실제로 적용되는 값을 보여 준다. 저장하면 파이썬이 공통 설정과 다른 값만 남긴다.
 * '자동 설정' 은 게임을 캐릭터 선택 화면으로 내보내 카드를 읽고 그 화면에 머문다 (사람이 누를 때만, 확인을 받고).
 */
const ch = { data: null, here: null, edit: null, review: null };
const FIELD_RUNS = [0, 1, 2, 3, 4, 5];

async function loadChars() {
  ch.data = await mm.chars.list();
  paintChars();
  paintScanning(ch.data.scanning);
}

function floorText(n) {
  return (ch.data && ch.data.floors[String(n)]) || n + '층';
}

/** 카드 아래 한 줄 요약: 사냥터 · 던전 · 검은 구멍 */
function tagsOf(c) {
  const t = [];
  t.push(c.field_runs > 0 ? '<span>' + esc(c.field) + ' ' + c.field_runs + '회</span>' : '<span class="off">사냥터 안 감</span>');
  t.push(c.dungeon ? '<span>' + esc(c.dungeon) + ' ' + esc(floorText(c.floor)) + '</span>' : '<span class="off">던전 안 감</span>');
  t.push(c.black_hole ? '<span>검은 구멍</span>' : '<span class="off">검은 구멍 안 감</span>');
  if (c.arbeit) t.push('<span>아르바이트</span>');
  t.push('<span>일요일 ' + esc(c.sunday || '') + '</span>');
  return t.join('');
}

/** 오늘 숙제 진행: 다 끝났으면 '오늘 클리어', 하다 만 것이면 'n/m' */
function todayOf(c) {
  const t = c.today;
  if (!t || !t.total || !t.done) return '';
  return t.done >= t.total ? ' · <span class="ch-today ok">오늘 클리어</span>'
    : ' · <span class="ch-today part">숙제 ' + t.done + '/' + t.total + '</span>';
}

/** 지금 게임에 접속 중인 캐릭터인가 (상단바가 읽어 둔 이름 — 띄어쓰기 무시) */
function isNow(c) {
  const now = typeof topName === 'string' ? topName.replace(/\s/g, '') : '';
  return !!now && (c.name || '').replace(/\s/g, '') === now;
}

function paintChars() {
  const d = ch.data;
  $('#ch-grid').innerHTML = d.chars.map((c) =>
    '<div class="ch-card' + (isNow(c) ? ' ch-now' : '') + '" data-slot="' + c.slot + '"' +
      (isNow(c) ? ' title="지금 접속 중"' : '') + '>' +
      (c.portrait ? '<img class="ch-art" src="' + c.portrait + '" alt="">'
        : '<div class="ch-art ch-noart">' + esc((c.name || '?').slice(0, 1)) + '</div>') +
      '<div class="ch-head">' +
        (c.level ? '<span class="ch-lv">' + c.level + '</span>' : '') +
        '<span class="ch-job">' + esc(c.job || '') + '</span>' +
        '<button class="ch-del" data-ch-del="' + c.slot + '" title="캐릭터 제외">✕</button>' +
      '</div>' +
      '<div class="ch-foot">' +
        '<div class="ch-name">' + esc(c.name) + '</div>' +
        '<div class="ch-slot">슬롯 ' + c.slot + todayOf(c) + '</div>' +
        '<div class="ch-tags">' + tagsOf(c) + '</div>' +
      '</div>' +
    '</div>').join('') +
    '<button class="ch-card ch-add" id="ch-add" title="캐릭터 선택 화면 순서대로 다음 슬롯을 추가">' +
      '<span class="ch-plus">+</span><span>캐릭터 추가</span></button>';
}

/* ── 캐릭터별 설정 창 ── */

function options(list, cur) {
  return list.map(([v, label]) =>
    '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(label) + '</option>').join('');
}

function openEdit(slot) {
  const d = ch.data;
  const c = slot == null ? null : d.chars.find((x) => x.slot === slot);
  const used = new Set(d.chars.map((x) => x.slot));
  let n = 1; while (used.has(n)) n++;
  // 새 캐릭터는 공통 설정 값으로 시작한다
  ch.edit = c ? { ...c } : { slot: n, name: '', ...d.defaults, portrait: null, isNew: true };
  const e = ch.edit;
  $('#ch-e-slot').textContent = '슬롯 ' + e.slot + (e.level ? ' · Lv.' + e.level + ' ' + (e.job || '') : '');
  $('#ch-e-name').value = e.name || '';
  $('#ch-e-field').innerHTML = options(d.fields.map((f) => [f, f]), e.field);
  $('#ch-e-runs').innerHTML = options(FIELD_RUNS.map((r) => [r, r === 0 ? '안 감' : r + '회']), e.field_runs);
  $('#ch-e-dungeon').innerHTML = options([['', '던전 안 감']].concat(d.dungeons.map((x) => [x, x])), e.dungeon);
  $('#ch-e-floor').innerHTML = options(Object.entries(d.floors), e.floor);
  $('#ch-e-bh').checked = e.black_hole !== false;
  $('#ch-e-sun').innerHTML = options(d.sundays.map((x) => [x, x]), e.sunday);
  $('#ch-e-arb').checked = !!e.arbeit;
  $('#ch-e-del').classList.toggle('hidden', !!e.isNew);
  paintEditArt();
  syncEditFields();
  $('#ch-edit').classList.remove('hidden');
  $('#ch-e-name').focus();
}

function paintEditArt() {
  const e = ch.edit;
  $('#ch-e-art').innerHTML = e.portrait ? '<img src="' + e.portrait + '" alt="">'
    : '<div class="ch-noart">' + esc((e.name || '?').slice(0, 1)) + '</div>';
  $('#ch-e-unpic').classList.toggle('hidden', !e.portrait);
}

/** 횟수 0 이면 사냥터 고르기를, 던전 안 감이면 층 고르기를 흐리게 */
function syncEditFields() {
  $('#ch-e-field').disabled = $('#ch-e-runs').value === '0';
  $('#ch-e-floor').disabled = $('#ch-e-dungeon').value === '';
}

/** 설정 창의 값을 숙제 기본값으로 채운다 (저장은 따로). 아르바이트는 기본값이 없어 그대로 둔다 */
function resetEdit() {
  const d = ch.data.defaults;
  $('#ch-e-field').value = d.field;
  $('#ch-e-runs').value = String(d.field_runs);
  $('#ch-e-dungeon').value = d.dungeon;
  $('#ch-e-floor').value = String(d.floor);
  $('#ch-e-bh').checked = d.black_hole !== false;
  $('#ch-e-sun').value = d.sunday;
  syncEditFields();
}

/** 모든 캐릭터를 숙제 기본값으로 (묻고 나서). 이름·그림·아르바이트는 그대로 */
async function resetAll() {
  const ok = await confirmModal('모두 기본값으로',
    '<p>모든 캐릭터의 사냥터 · 은동전 던전 · 검은 구멍 · 일요일 요일 던전을 숙제 기본값으로 되돌릴까요?</p>' +
    '<p class="hint">캐릭터별로 따로 정한 값이 지워집니다. 아르바이트는 그대로 둡니다.</p>', '되돌리기');
  if (!ok) return;
  const d = ch.data.defaults;
  if (await saveCharList(ch.data.chars.map((c) => ({
    ...c, field: d.field, field_runs: d.field_runs, dungeon: d.dungeon, floor: d.floor,
    black_hole: d.black_hole !== false, sunday: d.sunday,
  })))) toast('모든 캐릭터를 기본값으로 되돌렸습니다', '', 'ok');
}

function closeEdit() {
  $('#ch-edit').classList.add('hidden');
  ch.edit = null;
}

function collectEdit() {
  return {
    slot: ch.edit.slot, name: $('#ch-e-name').value.trim(),
    field: $('#ch-e-field').value, field_runs: Number($('#ch-e-runs').value),
    dungeon: $('#ch-e-dungeon').value, floor: Number($('#ch-e-floor').value),
    black_hole: $('#ch-e-bh').checked,
    arbeit: $('#ch-e-arb').checked,
    sunday: $('#ch-e-sun').value,
  };
}

async function saveCharList(list) {
  const r = await mm.chars.save(list.map((c) => ({
    slot: c.slot, name: c.name, field: c.field, field_runs: c.field_runs, dungeon: c.dungeon, floor: c.floor,
    black_hole: c.black_hole, arbeit: !!c.arbeit, sunday: c.sunday,
  })));
  if (r && r.error) { toast('저장하지 못했습니다', r.error, 'bad'); return false; }
  dl.pickedChars = null;  // 일일 숙제 탭의 고른 캐릭터를 새로
  await loadChars();
  return true;
}

async function saveEdit() {
  const v = collectEdit();
  if (!v.name) { toast('이름을 적어 주세요', '', 'bad'); return; }
  const list = ch.data.chars.filter((c) => c.slot !== v.slot).concat([v]).sort((a, b) => a.slot - b.slot);
  if (await saveCharList(list)) closeEdit();
}

/** 숙제 목록에서 제외한다 (묻고 나서). 제외했으면 true */
async function removeChar(c) {
  const ok = await confirmModal('캐릭터 제외', '<p><b>' + esc(c.name) + '</b> 캐릭터를 제외하시겠습니까?</p>', '제외');
  return ok && saveCharList(ch.data.chars.filter((x) => x.slot !== c.slot));
}

async function deleteEdit() {
  if (await removeChar(ch.edit)) closeEdit();
}

/* ── 자동 설정 ── */

function paintScanning(on, text) {
  $('#ch-scan').classList.toggle('hidden', !!on);
  $('#ch-scan-stop').classList.toggle('hidden', !on);
  $('#ch-scan-state').textContent = on ? (text || '캐릭터 선택 화면을 읽는 중…') : '';
}

async function startScan() {
  const ok = await confirmModal('캐릭터 자동 설정',
    '<p>캐릭터 선택 화면으로 나가 이름·레벨·직업·얼굴을 읽어 옵니다 (1~2분).</p>' +
    '<p class="hint">던전·사냥터 안에서는 하지 마세요 · 멈춤 ' + stopKey() + '</p>', '시작');
  if (!ok) return;
  const r = await mm.chars.scan();
  if (r && r.error) { toast('시작하지 못했습니다', r.error, 'bad'); return; }
  paintScanning(true);
}

mm.chars.onScan((m) => {
  if (!m) return;
  if (m.stage) { paintScanning(true, m.stage); return; }
  paintScanning(false);
  if (m.error) { toast('자동 설정 실패', m.error, 'bad'); return; }
  if (m.done) openReview(m);
});

function openReview(m) {
  const byslot = new Map(((ch.data && ch.data.chars) || []).map((c) => [c.slot, c]));
  ch.review = m.cards;
  $('#ch-rv-list').innerHTML = m.cards.map((c, i) => {
    const old = byslot.get(c.slot);
    const name = old ? old.name : c.name;
    const differs = old && c.name && old.name !== c.name;
    return '<div class="ch-rv" data-i="' + i + '">' +
      (c.portrait ? '<img src="' + c.portrait + '" alt="">' : '<div class="ch-noart">?</div>') +
      '<div class="ch-rv-body">' +
        '<div class="muted">슬롯 ' + c.slot + (c.level ? ' · Lv.' + c.level : '') + (c.job ? ' ' + esc(c.job) : '') +
          (old ? '' : ' · <b class="ch-new">새 캐릭터</b>') + '</div>' +
        '<input type="text" data-k="name" value="' + esc(name || '') + '" placeholder="이름">' +
        '<div class="ch-rv-read">읽은 이름: <b>' + esc(c.name || '(못 읽음)') + '</b>' +
          (c.score ? ' <span class="muted">' + Math.round(c.score * 100) + '%</span>' : '') +
          (differs ? ' <button class="btn btn-tiny" data-use="' + esc(c.name) + '">이걸로</button>' : '') + '</div>' +
        '<label class="chk"><input type="checkbox" data-k="pic"' + (c.portrait ? ' checked' : ' disabled') + '> 그림 바꾸기</label>' +
      '</div></div>';
  }).join('') + (m.total > m.cards.length
    ? '<p class="hint">캐릭터가 ' + m.total + '명인데 ' + m.cards.length + '명만 읽었습니다 (세 줄 이상은 가운데 줄을 못 읽습니다).</p>' : '');
  $('#ch-review').classList.remove('hidden');
}

async function applyReview() {
  const items = [...document.querySelectorAll('#ch-rv-list .ch-rv')].map((el) => {
    const c = ch.review[Number(el.dataset.i)];
    return {
      slot: c.slot, name: el.querySelector('[data-k="name"]').value.trim(),
      portrait: el.querySelector('[data-k="pic"]').checked, level: c.level, job: c.job,
    };
  });
  const r = await mm.chars.applyScan(items);
  if (r && r.error) { toast('적용하지 못했습니다', r.error, 'bad'); return; }
  $('#ch-review').classList.add('hidden');
  dl.pickedChars = null;
  await loadChars();
  toast('캐릭터를 채웠습니다', items.length + '명', 'ok');
}

/* ── 배선 ── */

LOADERS.chars = loadChars;

$('#ch-grid').addEventListener('click', (e) => {
  const del = e.target.closest('[data-ch-del]');
  if (del) {
    const c = ch.data.chars.find((x) => x.slot === Number(del.dataset.chDel));
    if (c) removeChar(c);
    return;
  }
  if (e.target.closest('#ch-add')) { openEdit(null); return; }
  const card = e.target.closest('.ch-card[data-slot]');
  if (card) openEdit(Number(card.dataset.slot));
});
$('#ch-e-runs').addEventListener('change', syncEditFields);
$('#ch-e-dungeon').addEventListener('change', syncEditFields);
$('#ch-e-cancel').addEventListener('click', closeEdit);
$('#ch-e-reset').addEventListener('click', resetEdit);
$('#ch-reset-all').addEventListener('click', resetAll);
$('#ch-e-save').addEventListener('click', saveEdit);
$('#ch-e-del').addEventListener('click', deleteEdit);
$('#ch-e-pic').addEventListener('click', async () => {
  const r = await mm.chars.pickPortrait(ch.edit.slot);
  if (!r || r.canceled) return;
  if (r.error) { toast('그림을 넣지 못했습니다', r.error, 'bad'); return; }
  ch.edit.portrait = r.portrait;
  paintEditArt();
  loadChars();
});
$('#ch-e-unpic').addEventListener('click', async () => {
  await mm.chars.clearPortrait(ch.edit.slot);
  ch.edit.portrait = null;
  paintEditArt();
  loadChars();
});
$('#ch-edit').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeEdit();
  if (e.key === 'Enter' && e.target.tagName === 'INPUT' && e.target.type === 'text') saveEdit();
});
$('#ch-scan').addEventListener('click', startScan);
$('#ch-scan-stop').addEventListener('click', () => { mm.chars.scanStop(); paintScanning(true, '멈추는 중…'); });
$('#ch-rv-cancel').addEventListener('click', () => $('#ch-review').classList.add('hidden'));
$('#ch-rv-ok').addEventListener('click', applyReview);
$('#ch-rv-list').addEventListener('click', (e) => {
  const b = e.target.closest('[data-use]');
  if (b) b.closest('.ch-rv').querySelector('[data-k="name"]').value = b.dataset.use;
});
