'use strict';
/* 표 공통 — 정렬 · 즐겨찾기 · 페이저. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

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
  sel.innerHTML = selectOptions((SORT_MENU[key] || []).map((k) => [k, over[k] || SORTS[k].label]), cur);
}

/** 저장해 둔 정렬 기준을 읽어 온다. 앱을 다시 켜도 고른 대로 보이게. */
async function loadSortPrefs() {
  const saved = pref('sort', {});  // 시작할 때 읽어 둔 설정 (main.js)
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
      uiPrefs.sort = Object.assign({}, uiPrefs.sort, { [key]: sel.value });
      try { await mm.cfg.sort(key, sel.value); } catch (_) { /* 저장 실패가 화면을 막지 않는다 */ }
    });
  }
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
    selectOptions(PAGE_SIZES.map((n) => [n, n + '줄']), p.per) +
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
