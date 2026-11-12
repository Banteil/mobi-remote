'use strict';
/* 채집 · 소지품 · 미션 탭. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

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
  if (q) { const n = normSearch(q); rows = rows.filter((x) => hit(x.name, n)); }

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
    label: name + ' 채집', detail: '1회 (최대 ' + mm.limits.gatherPerCall + '개)', note: '1회 최대 ' + mm.limits.gatherPerCall + '개' });
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
  if (q) { const n = normSearch(q); rows = rows.filter((x) => hit(x.name, n)); }

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
