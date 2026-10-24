'use strict';
/* 제작 · 목표 걸기 · 가공 탭. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

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
    '1회당 ' + per + '개 · 재료가 모자라면 날개 소모 없이 거부'
  );
  if (!times) return;
  actNow({ act: 'craft', command: 'execute_crafting', body: { displayName: name, craftCount: times },
    label: name + ' 제작 x' + times, detail: '제작 ' + times + '회',
    note: '이동 → 제작 → 결과 수령까지 한 번에 진행되며, 몇 분 걸릴 수 있습니다. ' +
          'craftCount가 몇이든 호출은 1회라 날개는 5만 듭니다.' });
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
  const it = await qAdd({
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
    if (!qFind(it.id)) return;         // 그새 지워졌다
    if (r.error) { qNote(it, fallback); return; }
    mm.queue.patch(it.id, {
      wings: r.estimate ? r.estimate.wings : 0,
      partial: !!(r.estimate && r.estimate.partial),
      note: r.step && r.step.kind === 'blocked' ? '막힘 — ' + (r.step.message || r.step.reason || '') : fallback,
    });
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
      // 수령·목표는 세로로 쌓고, 완료분이 없어도 같은 폭을 비워 둔다 (시설마다 줄이 들쭉날쭉하지 않게)
      '<span class="fac-act">' + (f.completed.length
        ? '<button class="btn btn-tiny btn-primary" data-collect="' + esc(f.completed[0].name) + '">수령</button>' +
          '<button class="btn btn-tiny" data-collect-goal="' + esc(f.completed[0].name) + '" title="작업 큐 맨 아래에 담기">목표</button>'
        : '') + '</span>' +
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
    '<p>설정보다 <b>작업이 더 많이</b> 올라가 있습니다.</p>' +
    '<div class="tablewrap"><table><thead><tr>' +
    '<th>시설</th><th class="w-sm num">지금 작업</th><th class="w-sm num">설정</th><th class="w-sm num">맞춰 보면</th>' +
    '</tr></thead><tbody>' +
    rows.map((x) =>
      '<tr><td>' + esc(x.room.facility) + '</td>' +
      '<td class="num">' + x.room.used + '건</td>' +
      '<td class="num muted">Lv' + x.room.level + ' (' + x.room.slots + '칸)</td>' +
      '<td class="num mark-ok">Lv' + x.level + ' (' + x.slots + '칸)</td></tr>').join('') +
    '</tbody></table></div>' +
    '<p class="hint">맞춰 보면 = 지금 작업 수를 담는 <b>최소 레벨</b></p>' +
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
      (w.facilities || []).filter((f) => f.completed.length).length + '개 시설)</button> ' +
      '<button class="btn btn-tiny" id="collect-all-goal" title="작업 큐 맨 아래에 담기">목표</button>'
    : '';

  $('#alter-works').innerHTML =
    facilityMiniHtml(w) +
    facilitySlotsHtml(w) +
    (w.completedCount > 0
      ? '<p class="hint">완료 작업도 칸을 차지합니다 — 먼저 수령하세요 (꽉 차면 날개 5만 나감)</p>'
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
    toast('소속 시설을 모릅니다', '한 번 가공하면 배웁니다', 'bad');
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
