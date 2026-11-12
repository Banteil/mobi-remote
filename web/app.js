'use strict';
/* 모비 커넥터 리모콘 렌더러. window.mm(preload)을 통해서만 메인과 통신한다.
 * 여기는 화면 어디서나 쓰는 공통 부품 — $·esc·검색·<option>·시간 글자·토스트·모달·화면 기억값(pref)·버튼 돌림.
 * 기능별 화면은 actions·topbar·dash·tables·lists·options·wire 와 craft·queue·music·dye-ui·daily·chars 로 나뉘어 있다. 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const num = (n) => Number(n || 0).toLocaleString('ko-KR');
const esc = (s) =>
  String(s === undefined || s === null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/** 검색어 정규화 — 공백·대소문자 무시 */
const normSearch = (s) => String(s === undefined || s === null ? '' : s).toLowerCase().replace(/\s+/g, '');
/** text 가 검색어 q(normSearch 한 것)를 담나. q 가 비면 늘 참 */
function hit(text, q) { return !q || normSearch(text).includes(q); }

/** <select> 의 <option> 줄. items: 값 또는 [값, 글자] (글자가 없으면 값 그대로), cur 와 같은 값을 고른다 */
function selectOptions(items, cur) {
  return items.map((o) => {
    const [v, label] = Array.isArray(o) ? o : [o, o];
    return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(label) + '</option>';
  }).join('');
}

/* 캐릭터 고르기 (숙제·어비스·레이드 탭, 큐 카드의 '할 캐릭터') — c: {slot, name}. 글자는 '슬롯. 이름' */
function charLabel(c) { return c.slot + '. ' + c.name; }

/** 캐릭터 <option> 줄. 맨 앞은 0 = zeroLabel (지금 접속한 캐릭터) */
function charOptions(chars, cur, zeroLabel) {
  return selectOptions([[0, zeroLabel]].concat(chars.map((c) => [c.slot, charLabel(c)])), cur);
}

/** 캐릭터 체크박스 하나. attr: input 에 붙일 속성 이름 (값은 슬롯), cls: label 에 더할 클래스 */
function charCheck(c, on, attr, cls) {
  return '<label class="chk' + (cls ? ' ' + cls : '') + '"><input type="checkbox" ' + attr + '="' + c.slot + '"' +
    (on ? ' checked' : '') + '>' + esc(charLabel(c)) + '</label>';
}

/* ── 시간 글자 (화면 어디서나 이것으로) ── */

/** 걸린·걸릴 시간 — 1분 안이면 '40초', 그 위는 분으로 반올림해 '12분' · '1시간 5분' · '2시간' */
function fmtDur(sec) {
  const s = Math.max(0, Number(sec) || 0);
  if (s < 60) return Math.round(s) + '초';
  const m = Math.round(s / 60);
  return m >= 60 ? Math.floor(m / 60) + '시간' + (m % 60 ? ' ' + (m % 60) + '분' : '') : m + '분';
}

/** 남은 시간 — 다 됐으면 '완료' */
function dur(sec) { return sec > 0 ? fmtDur(sec) : '완료'; }

const pad2 = (n) => String(n).padStart(2, '0');

/** 흐르는 시간을 시계 모양으로 — 'm:ss', 한 시간이 넘으면 'h:mm:ss' (초 아래는 버림) */
function fmtClock(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return (h ? h + ':' + pad2(m) : m) + ':' + pad2(s % 60);
}

/** 시각(ms) → 'HH:MM' */
function fmtHM(t) { const d = new Date(t); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()); }

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

/**
 * 모달 하나 (#modal) — 열고, 확인·취소·Esc·Enter 를 받아 닫고 값을 돌려준다. 모달 창은 모두 이 위에 얹는다.
 *   title · body(HTML) · ok · cancel  제목·내용·버튼 글자 (버튼 기본 '확인'·'취소' — 매번 다시 적는다)
 *   value()  확인(Enter)일 때 돌려줄 값 (없으면 true)
 *   no       취소(Esc)일 때 돌려줄 값 (없으면 false)
 * 내용에 #modal-input 이 있으면 거기에, 없으면 확인 버튼에 포커스. Promise
 */
function openModal(o) {
  return new Promise((resolve) => {
    $('#modal-title').textContent = o.title;
    $('#modal-body').innerHTML = o.body;
    $('#modal-ok').textContent = o.ok || '확인';
    $('#modal-cancel').textContent = o.cancel || '취소';
    $('#modal').classList.remove('hidden');

    const done = (v) => {
      $('#modal').classList.add('hidden');
      $('#modal-ok').removeEventListener('click', onOk);
      $('#modal-cancel').removeEventListener('click', onNo);
      document.removeEventListener('keydown', onKey);
      resolve(v);
    };
    const onOk = () => done(o.value ? o.value() : true);
    const onNo = () => done(o.no === undefined ? false : o.no);
    const onKey = (e) => {
      if (e.key === 'Escape') onNo();
      if (e.key === 'Enter') { e.preventDefault(); onOk(); }
    };
    $('#modal-ok').addEventListener('click', onOk);
    $('#modal-cancel').addEventListener('click', onNo);
    document.addEventListener('keydown', onKey);

    const input = $('#modal-input');
    if (!input) { $('#modal-ok').focus(); return; }
    input.focus();
    if (input.tagName === 'INPUT') input.select();
  });
}

/** 모달 확인. Promise<boolean> */
function confirmModal(title, bodyHtml, okLabel, cancelLabel) {
  return openModal({ title, body: bodyHtml, ok: okLabel || '실행', cancel: cancelLabel });
}

const hintHtml = (hint) => (hint ? '<p class="hint">' + esc(hint) + '</p>' : '');

/**
 * 숫자 입력 모달. Electron은 window.prompt()를 지원하지 않으므로 직접 만든다.
 * Promise<number|null>
 */
function promptNumber(title, label, defaultValue, hint) {
  return openModal({
    title, no: null,
    body: '<p>' + esc(label) + '</p>' +
      '<input id="modal-input" type="number" min="1" step="1" value="' + esc(defaultValue) + '" class="w-full">' + hintHtml(hint),
    value: () => {
      const n = parseInt($('#modal-input').value, 10);
      return Number.isFinite(n) && n > 0 ? n : null;
    },
  });
}

/**
 * 목록에서 하나 고르는 모달.
 * 레벨처럼 값이 정해져 있는 것은 숫자를 타이핑하게 하는 것보다 고르게 하는 편이 빠르고 덜 틀린다.
 * @param {Array<{value:*, label:string}>} options
 */
function promptSelect(title, label, options, current, hint) {
  return openModal({
    title, no: null,
    body: '<p>' + esc(label) + '</p>' +
      '<select id="modal-input" class="w-full">' + selectOptions(options.map((o) => [o.value, o.label]), current) + '</select>' +
      hintHtml(hint),
    value: () => $('#modal-input').value,
  });
}

/** 문자열 입력 모달. promptNumber의 텍스트판. */
function promptText(title, label, defaultValue, hint) {
  return openModal({
    title, no: null,
    body: '<p>' + esc(label) + '</p>' +
      '<input id="modal-input" type="text" maxlength="40" value="' + esc(defaultValue || '') + '" class="w-full">' + hintHtml(hint),
    value: () => $('#modal-input').value.trim() || null,
  });
}

/* 화면에서 고른 것 기억 (다시 켜도 그대로) — 파이썬 settings 파일에 둔다 (mm.cfg.set, 허용 키는 api.CFG_KEYS).
 * 웹 화면 저장소(localStorage)는 화면 프로필이 기록을 남기지 않아(off-the-record) 켤 때마다 비므로 쓰지 않는다.
 * uiPrefs 는 시작할 때(main.js) 한 번 읽는다. 저장은 반드시 setPref 로 — 그래야 uiPrefs 가 늘 지금 값이다.
 * setPref 는 저장이 끝나면 풀리는 Promise 를 돌려준다 (실패해도 던지지 않는다). */
let uiPrefs = {};
function pref(key, fallback) { return uiPrefs[key] !== undefined && uiPrefs[key] !== null ? uiPrefs[key] : fallback; }
function setPref(key, value) {
  uiPrefs[key] = value;
  return mm.cfg.set(key, value).catch(() => { /* 저장 실패가 화면을 막지 않는다 */ });
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

function debounce(fn, ms) {
  let t;
  return () => { clearTimeout(t); t = setTimeout(fn, ms || 160); };
}
