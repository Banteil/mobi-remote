'use strict';
/**
 * 조회 필터 계층.
 *
 * 원본 응답을 그대로 흘리지 않고 로컬에서 걸러 요약만 낸다.
 * 예) get_craftable_items는 1834건/444KB지만, craftFind('못')은 한 줄이다.
 */
const cache = require('./cache');
const richtext = require('./richtext');
const knowledge = require('./knowledge');
const altertable = require('./altertable');
const recipebook = require('./recipebook');
const settings = require('./settings');
const errors = require('./errors');

/**
 * 한글/영문 부분 일치. 공백 무시, 대소문자 무시.
 * 이름에 <color=...> 같은 태그가 섞여 있으면 검색이 안 되므로 먼저 벗긴다.
 */
function matches(haystack, needle) {
  if (!needle) return true;
  const h = richtext.strip(String(haystack || '')).toLowerCase().replace(/\s+/g, '');
  const n = String(needle).toLowerCase().replace(/\s+/g, '');
  return h.includes(n);
}

function fail(res) {
  return { error: res.error, message: res.message };
}

/**
 * 이름을 표시용/원문으로 나눈다.
 * 게임에 되돌려 보낼 때는 반드시 nameRaw를 쓴다 — 태그를 벗긴 이름은 식별자가 아니다.
 * 지금은 get_items에만 태그가 있지만, 다른 목록에 생겨도 깨지지 않게 공통으로 적용한다.
 */
function nameFields(displayName) {
  const tagged = richtext.hasTags(displayName);
  return {
    name: tagged ? richtext.strip(displayName) : displayName,
    nameRaw: displayName,
    seg: tagged ? richtext.segments(displayName) : null,
  };
}

/* ── 제작 ───────────────────────────────────────────────────── */

/**
 * 아이템 이름 → 총 보유량(가방+보관함) 맵.
 *
 * 중요: MissingIngredients의 Owned는 **가방 수량만** 센다. 반면 Craftable/Alterable
 * 판정은 보관함까지 본다(게임에서 보관함 재료를 원격으로 쓸 수 있기 때문).
 * 그래서 Owned만 보여주면 "보관함에 잔뜩 있는데 부족하다"고 오해하게 된다.
 */
async function ownedTotals(opts) {
  const res = await cache.get('get_items', opts);
  const map = new Map();
  const add = (key, n) => map.set(key, (map.get(key) || 0) + n);
  for (const it of Array.isArray(res.data) ? res.data : []) {
    add(it.DisplayName, it.Count);
    // 재료 이름은 태그가 없을 수 있으므로 벗긴 형태로도 찾을 수 있게 해 둔다
    const bare = richtext.strip(it.DisplayName);
    if (bare !== it.DisplayName) add(bare, it.Count);
  }
  return map;
}

/**
 * MissingIngredients를 실제 기준으로 정리한다.
 * @returns {{missing: string[], covered: string[]}}
 *   missing = 보관함까지 합쳐도 모자란 것 (진짜 막고 있는 재료)
 *   covered = 가방엔 없지만 보관함 재고로 충당되는 것
 */
function splitIngredients(list, totals) {
  const missing = [];
  const covered = [];
  for (const m of list || []) {
    const label = richtext.strip(m.DisplayName);
    const total = totals ? totals.get(m.DisplayName) || totals.get(label) || 0 : m.Owned;
    if (total < m.Required) missing.push(label + ' ' + total + '/' + m.Required);
    else if (m.Owned < m.Required) covered.push(label + ' ' + total);
  }
  return { missing, covered };
}

/**
 * 이미 배워 둔 레시피만 게임이 준 숫자와 대조한다.
 *
 * MissingIngredients는 게임이 직접 말한 값이라 diff로 역산한 값보다 믿을 수 있다.
 * 다만 부족분만 오므로 새 레시피를 여기서 만들지는 않는다 — 아는 것을 검증할 뿐이다.
 * 전체(1,800여 종)를 매번 기록하면 조회 한 번이 파일 쓰기 수백 번이 된다.
 */
/**
 * 목록을 볼 때마다 레시피 표를 채운다.
 *
 * 게임은 **지금 만들 수 없는** 레시피에만 재료를 알려 준다. 전에는 그중에서도
 * "이미 아는 레시피"만 골라 검증에 쓰고 나머지 900줄 가까이를 그냥 버렸다.
 * 버릴 이유가 없다 — 전부 게임이 직접 준 숫자고, 조회는 어차피 하고 있다.
 *
 *   · 아는 레시피  → 값을 대조해 confidence 를 올린다 (전과 같음)
 *   · 모르는 레시피 → 레시피 장부에 담는다 (새로 하는 일)
 */
function harvestRecipes(rows, kind, okKey, perKey) {
  let known = null;
  for (const r of rows) {
    if (r[okKey]) continue;
    if (!r.MissingIngredients || !r.MissingIngredients.length) continue;
    if (known === null) known = knowledge.load().recipes || {};
    if (!known[r.DisplayName]) continue;
    try {
      knowledge.learnRecipeFromMissing(r.DisplayName, kind, r.MissingIngredients, r[perKey]);
    } catch (_) { /* 검증 실패가 조회를 막으면 안 된다 */ }
  }
  try {
    recipebook.harvestRows(rows, kind, okKey, perKey, known || knowledge.load().recipes || {});
  } catch (_) { /* 수확 실패도 조회를 막지 않는다 */ }
}

async function craft(opts) {
  const o = opts || {};
  const res = await cache.get('get_craftable_items', o);
  if (!res.data) return fail(res);
  const totals = o.detail ? await ownedTotals(o) : null;

  const all = res.data.items || [];
  let rows = all;
  if (o.search) rows = rows.filter((r) => matches(r.DisplayName, o.search));
  if (o.onlyOk) rows = rows.filter((r) => r.Craftable);

  // 검색으로 좁히기 전의 전체 목록으로 수확한다. 걸러진 결과만 보면 표가 안 찬다.
  harvestRecipes(all, 'craft', 'Craftable', 'ProducedPerCraft');

  const out = rows.map((r) => {
    const row = nameFields(r.DisplayName);
    row.ok = !!r.Craftable;
    row.per = r.ProducedPerCraft;
    if (!r.Craftable) {
      // 코드 그대로 두면 화면에 insufficient_living_skill_level 이 뜬다
      row.reason = errors.reasonText(r.Reason);
      row.reasonCode = r.Reason;
      // 부족분만 남긴다. 전체 재료 목록이 응답 용량의 대부분이다.
      if (o.detail && r.MissingIngredients) {
        const s = splitIngredients(r.MissingIngredients, totals);
        row.missing = s.missing;
        if (s.covered.length) row.covered = s.covered;
      }
    }
    return row;
  });

  return {
    unlocked: res.data.craftingUnlocked,
    total: all.length,
    craftable: all.filter((r) => r.Craftable).length,
    matched: out.length,
    cached: res.cached,
    stale: !!res.stale,
    ageSec: Math.round(res.ageMs / 1000),
    items: o.limit ? out.slice(0, o.limit) : out,
  };
}

/** 이름 하나를 짚어 제작 가능 여부와 부족 재료를 낸다. */
async function craftFind(name, opts) {
  return craft(Object.assign({}, opts, { search: name, detail: true, limit: 20 }));
}

/* ── 가공 ───────────────────────────────────────────────────── */

async function alter(opts) {
  const o = opts || {};
  const res = await cache.get('get_alterable_items', o);
  if (!res.data) return fail(res);

  const all = res.data.items || [];
  let rows = all;
  if (o.search) rows = rows.filter((r) => matches(r.DisplayName, o.search));
  if (o.onlyOk) rows = rows.filter((r) => r.Alterable);
  const totals = await ownedTotals(o);

  harvestRecipes(all, 'alter', 'Alterable', 'ProducedPerWork');

  // 같은 이름이 몇 번째로 나왔는지 세어 둔다 (갈래를 차례로 맞추려고)
  const seen = new Map();

  return {
    total: all.length,
    alterable: all.filter((r) => r.Alterable).length,
    matched: rows.length,
    cached: res.cached,
    stale: !!res.stale,
    items: (o.limit ? rows.slice(0, o.limit) : rows).map((r) => {
      const row = nameFields(r.DisplayName);
      row.ok = !!r.Alterable;
      row.per = r.ProducedPerWork;
      // 어느 시설에서 만드는지. 관측값이 없으면 facility-map.json 의 표를 본다.
      row.facility = knowledge.facilityOf(r.DisplayName);

      // 필요한 시설 레벨과 걸리는 시간. 게임은 둘 다 알려주지 않아 가공 재료표에서 온다.
      //
      // 이름이 같은 줄이 여럿 올 수 있다(은합금괴는 Lv.4 와 Lv.6 두 줄). 줄마다 제
      // 갈래를 찾아야 한다 — 이름만 보고 첫 갈래로 몰면 둘이 똑같아 보인다.
      const seenKey = richtext.strip(r.DisplayName);
      const nth = seen.get(seenKey) || 0;
      seen.set(seenKey, nth + 1);
      const hit = altertable.matchRow(
        r.DisplayName,
        (r.MissingIngredients || []).map((m) => richtext.strip(m.DisplayName)),
        nth);
      if (hit && hit.variant) {
        row.level = hit.variant.level;
        row.sec = hit.variant.sec;
        row.variant = hit.index;
        row.variants = altertable.get(hit.product).variants.length;
        if (!row.facility) row.facility = hit.variant.facility;
      }
      if (!r.Alterable) {
        row.reason = errors.reasonText(r.Reason);
        row.reasonCode = r.Reason;
        // 제작과 마찬가지로 보관함까지 합쳐 진짜 부족한 것만 남긴다
        if (r.MissingIngredients) {
          const s = splitIngredients(r.MissingIngredients, totals);
          row.missing = s.missing;
          if (s.covered.length) row.covered = s.covered;
        }
      }
      return row;
    }),
  };
}

/* ── 채집 ───────────────────────────────────────────────────── */

async function gather(opts) {
  const o = opts || {};
  const res = await cache.get('get_gatherable_items', o);
  if (!res.data) return fail(res);

  const all = res.data.items || [];
  let rows = all;
  if (o.search) rows = rows.filter((r) => matches(r.DisplayName, o.search));
  if (o.onlyOk) rows = rows.filter((r) => r.ToolOk);

  return {
    total: all.length,
    toolOk: all.filter((r) => r.ToolOk).length,
    matched: rows.length,
    cached: res.cached,
    stale: !!res.stale,
    items: (o.limit ? rows.slice(0, o.limit) : rows).map((r) =>
      Object.assign(nameFields(r.DisplayName), { tool: !!r.ToolOk })),
  };
}

/* ── 소지품 ─────────────────────────────────────────────────── */

const LOCATION_LABEL = {
  inventory: '가방',
  account_storage: '계정창고',
  character_storage: '캐릭창고',
};

/**
 * 보관처를 고정된 칸으로 나눈다.
 *
 * "가방 48, 계정창고 3"처럼 한 칸에 몰아 적으면 눈으로 훑기 어렵고,
 * 어디에 없는지(0인지)가 아예 보이지 않는다. 제작·가공은 보관함 재고까지 쓰지만
 * **무게는 가방만** 차지하므로, 셋을 구분해서 보는 것이 실제로 중요하다.
 */
const LOCATION_KEY = {
  inventory: 'bag',
  character_storage: 'charStore',
  account_storage: 'accStore',
};

async function items(opts) {
  const o = opts || {};
  const res = await cache.get('get_items', o);
  if (!res.data) return fail(res);

  const all = Array.isArray(res.data) ? res.data : [];
  let rows = all;
  if (o.search) rows = rows.filter((r) => matches(r.DisplayName, o.search));
  if (o.category) rows = rows.filter((r) => matches(r.CategoryDisplayName, o.category));

  // 같은 이름이 보관처별로 쪼개져 있으므로 합산한다.
  // 키는 원문(식별자), 표시는 태그를 벗긴 값. seg는 GUI가 색을 살릴 때 쓴다.
  const byName = new Map();
  for (const r of rows) {
    if (!byName.has(r.DisplayName)) {
      byName.set(r.DisplayName, {
        name: richtext.strip(r.DisplayName),
        nameRaw: r.DisplayName,
        seg: richtext.hasTags(r.DisplayName) ? richtext.segments(r.DisplayName) : null,
        category: r.CategoryDisplayName,
        total: 0,
        where: {},                                   // CLI 표시용 (라벨 → 수량)
        at: { bag: 0, charStore: 0, accStore: 0 },   // GUI 표시용 (칸이 고정돼야 한다)
        locked: false,
      });
    }
    const e = byName.get(r.DisplayName);
    e.total += r.Count;
    const label = LOCATION_LABEL[r.Location] || r.Location;
    e.where[label] = (e.where[label] || 0) + r.Count;
    const key = LOCATION_KEY[r.Location];
    if (key) e.at[key] += r.Count;
    if (r.IsLocked) e.locked = true;
  }

  const out = Array.from(byName.values()).sort((a, b) => b.total - a.total);

  // 필터 메뉴를 만들 때 쓴다. 필터를 건 뒤의 목록이 아니라 **전체** 기준이어야
  // 고른 분류가 메뉴에서 사라지지 않는다.
  const cats = {};
  for (const r of all) {
    const c = r.CategoryDisplayName;
    if (c) cats[c] = (cats[c] || 0) + 1;
  }

  return {
    totalRows: all.length,
    matched: out.length,
    categories: Object.keys(cats).sort((a, b) => a.localeCompare(b, 'ko')),
    cached: res.cached,
    stale: !!res.stale,
    items: o.limit ? out.slice(0, o.limit) : out,
  };
}

/** 이름 하나의 총 보유 수량. 없으면 0. */
async function itemCount(name, opts) {
  const r = await items(Object.assign({}, opts, { search: name }));
  if (r.error) return r;
  // 태그가 붙은 원문으로 물어봐도, 벗긴 이름으로 물어봐도 찾히게 한다
  const bare = richtext.strip(String(name || ''));
  const exact =
    r.items.find((i) => i.nameRaw === name || i.name === name || i.name === bare) || r.items[0];
  return exact
    ? { name: exact.name, count: exact.total, where: exact.where }
    : { name: bare, count: 0, where: {} };
}

/* ── 재화 ───────────────────────────────────────────────────── */

async function currencies(opts) {
  const o = opts || {};
  const res = await cache.get('get_currencies', o);
  if (!res.data) return fail(res);
  let rows = Array.isArray(res.data) ? res.data : [];
  if (o.search) rows = rows.filter((r) => matches(r.DisplayName, o.search));
  if (o.nonZero) rows = rows.filter((r) => r.Amount > 0);
  return {
    cached: res.cached,
    stale: !!res.stale,
    items: rows.map((r) => ({ name: r.DisplayName, amount: r.Amount })),
  };
}

/** 정령의 날개 잔량. execute_gathering / execute_crafting 1회당 5 소모. */
async function wings(opts) {
  const r = await currencies(Object.assign({}, opts, { search: '정령의 날개' }));
  if (r.error) return r;
  const w = r.items.find((i) => i.name === '정령의 날개');
  return { amount: w ? w.amount : 0, cached: r.cached };
}

/* ── 캐릭터 / 미션 / 활동 ───────────────────────────────────── */

/**
 * 캐릭터 요약.
 *
 * 주의: get_my_info는 캐릭터명을 주지 않는다. 헷갈리기 쉬운 두 필드가 있다.
 *   Title     = 착용 중인 타이틀
 *   RealmName = 서버(렐름) 이름
 *
 * RealmName을 캐릭터명으로 오해하기 쉽다. 던전처럼 서버를 섞어 매칭하는 곳에서는
 * get_near_pcs에 서로 다른 RealmName이 섞여 나오기 때문이다. 일반 필드에서는
 * 주변 플레이어 전원이 나와 같은 값을 갖는다.
 *
 * 캐릭터명은 28개 명령 어디에서도 제공되지 않으므로 화면에 띄우려 하지 말 것.
 */
async function me(opts) {
  const res = await cache.get('get_my_info', opts);
  if (!res.data) return fail(res);
  const d = res.data;
  const v = d.Vitals || {};
  return {
    title: d.Title,
    realm: d.RealmName,
    level: d.Level,
    job: d.EnabledCombatJobDisplayName,
    combat: d.CombatScore && d.CombatScore.Value,
    living: d.LivingScore && d.LivingScore.Value,
    hp: v.HealthCurrent + '/' + v.HealthMax,
    satiety: v.SatietyValue + '/' + v.SatietyMax,
    weight: Math.round(v.InventoryWeightCurrent) + '/' + Math.round(v.InventoryWeightMax),
    weightPct: Math.round((v.InventoryWeightCurrent / v.InventoryWeightMax) * 100),
    buffs: v.ActiveBuffCount,
    cached: res.cached,
    stale: !!res.stale,
    stale: !!res.stale,
  };
}

/**
 * 미션 한 건의 상태는 셋이다. 커넥터에 **수령 명령이 없으므로**(28개 어디에도 없다)
 * 셋을 뭉뚱그리면 "지금 게임에서 뭘 해야 하는가"가 사라진다.
 *
 *   진행 중   — 더 해야 한다
 *   수령 대기 — 다 했는데 보상을 안 받았다. **게임에서 직접 눌러야 한다**
 *   끝        — 받았다
 */
function missionState(m) {
  if (!m.IsCompleted) return 'open';
  return m.IsRewardReceived ? 'done' : 'unclaimed';
}

/**
 * 게임에 없는 미션이 섞여 오는 것을 걸러 낸다.
 *
 * 실측 — 주간 "이 구역은 내가 접수한다"가 두 건으로 온다.
 *   { 필드 보스 1회 토벌, 1/1, 완료, 수령함   }  ← 게임에 있는 것
 *   { 필드 보스 2회 토벌, 2/2, 완료, 수령 안 함 }  ← 게임에는 없다
 * 응답 필드가 일곱뿐이라(id·주기·티어 없음) 둘을 구별할 단서가 이름밖에 없다.
 *
 * 그래서 규칙을 하나로 좁힌다 — **제목이 같은 묶음에 수령까지 끝난 건이 있으면,
 * 같은 묶음의 "완료했는데 수령 안 함"은 지난 주기의 잔재로 보고 버린다.**
 * 이 게임의 단계형 미션은 한 번에 한 단계만 보여 주므로, 아래 단계를 수령한 상태에서
 * 위 단계가 수령 대기로 남아 있을 수는 없다.
 *
 * 진행 중인 건은 건드리지 않는다. 그것은 진짜 다음 단계일 수 있다.
 */
function dropPhantoms(arr) {
  const rows = Array.isArray(arr) ? arr : [];
  const claimed = Object.create(null);
  for (const m of rows) if (m.IsCompleted && m.IsRewardReceived) claimed[m.Title] = true;
  return rows.filter((m) => !(claimed[m.Title] && m.IsCompleted && !m.IsRewardReceived));
}

function missionRows(arr, onlyOpen) {
  let rows = dropPhantoms(arr);
  if (onlyOpen) rows = rows.filter((m) => missionState(m) !== 'done');
  return rows.map((m) => ({
    title: m.Title,
    desc: m.Description,
    progress: m.CurrentCount + '/' + m.GoalCount,
    state: missionState(m),
    done: !!m.IsCompleted,
    claimed: !!m.IsRewardReceived,
    // 게임 안에 바로가기가 있는 미션인지. 커넥터로는 누를 수 없지만, 게임에서 찾기는 쉽다.
    shortcut: !!m.HasShortcut,
  }));
}

/** 상태별 건수. 화면 머리말에 그대로 쓴다. */
function missionCounts(arr) {
  const rows = dropPhantoms(arr);
  let open = 0, unclaimed = 0;
  for (const m of rows) {
    const st = missionState(m);
    if (st === 'open') open++;
    else if (st === 'unclaimed') unclaimed++;
  }
  return { total: rows.length, open: open, unclaimed: unclaimed };
}

async function daily(opts) {
  const o = opts || {};
  const res = await cache.get('get_daily_missions', o);
  if (!res.data) return fail(res);
  const c = missionCounts(res.data);
  return {
    total: c.total,
    open: c.open,
    unclaimed: c.unclaimed,
    cached: res.cached,
    stale: !!res.stale,
    items: missionRows(res.data, o.onlyOpen),
  };
}

async function weekly(opts) {
  const o = opts || {};
  const res = await cache.get('get_weekly_missions', o);
  if (!res.data) return fail(res);
  const c = missionCounts(res.data);
  return {
    total: c.total,
    open: c.open,
    unclaimed: c.unclaimed,
    cached: res.cached,
    stale: !!res.stale,
    items: missionRows(res.data, o.onlyOpen),
  };
}

/** 지금 뭔가 진행 중인지. 루틴 실행 전 안전 점검에 쓴다. 항상 실시간. */
async function activity(opts) {
  const res = await cache.get('get_activity', Object.assign({ maxAgeMs: 0 }, opts));
  if (!res.data) return fail(res);
  const d = res.data;
  const perf = d.Performance || {};
  const mode = d.Mode || {};
  return {
    autoPlaying: !!d.IsAutoPlaying,
    autoTraveling: !!d.IsAutoTraveling,
    inCombat: !!d.IsInCombat,
    dead: !!d.IsDead,
    // 커넥터가 주기는 하는데 믿을 수 없는 값이다. 던바튼을 멀쩡히 돌아다니고 연주도 되는
    // 상태에서 계속 true 로 남아 있는 것을 확인했다. 그대로 노출만 하고 판단에는 쓰지 않는다.
    reviving: !!d.IsReviving,
    dialogue: !!d.IsDialoguePlaying || !!d.IsWaitingForSelection,
    performing: !!perf.IsPlaying,
    // 연주는 게임이 시간을 재서 준다. 진행바와 남은 시간을 그릴 수 있는 유일한 값이다.
    // 연주 중이 아니면 전부 0이고 MusicTitle 도 빈 문자열이다.
    perf: {
      playing: !!perf.IsPlaying,
      instrument: perf.InstrumentName || '',
      title: perf.MusicTitle || '',
      loop: !!perf.IsLoop,
      total: Number(perf.TotalDurationSeconds) || 0,
      elapsed: Number(perf.ElapsedSeconds) || 0,
      remaining: Number(perf.RemainingSeconds) || 0,
      channels: Number(perf.ChannelCount) || 0,
      startAt: perf.StartAt || '',
    },
    sitting: mode.SitState === 'Sitting',
    mainButton: mode.MainButtonState,
    dungeon: d.Dungeon && d.Dungeon.State,
    busy:
      !!d.IsAutoPlaying ||
      !!d.IsAutoTraveling ||
      !!d.IsInCombat ||
      !!perf.IsPlaying ||
      !!d.IsWaitingForSelection,
    cached: res.cached,
    stale: !!res.stale,
  };
}

/** 가공 작업 현황. 완료분은 시설별로 묶어야 complete_altering_work를 시설당 1회만 부른다. */
async function alteringWorks(opts) {
  const res = await cache.get('get_altering_works', opts);
  if (!res.data) return fail(res);
  const works = res.data.works || [];
  // 아이템↔시설 매핑과 시설별 칸 수는 여기서만 알 수 있다. 볼 때마다 쌓아 둔다.
  try { knowledge.learnFromAlteringWorks(res.data); } catch (_) { /* 학습 실패는 조회를 막지 않는다 */ }

  const byFacility = new Map();
  for (const w of works) {
    const key = w.FacilityName || '(시설 미상)';
    if (!byFacility.has(key)) byFacility.set(key, { facility: key, completed: [], inProgress: [] });
    const e = byFacility.get(key);
    const row = {
      name: w.DisplayName,
      state: w.State,
      remainingSec: w.RemainingSeconds,
    };
    if (w.IsCompleted) e.completed.push(row);
    else e.inProgress.push(row);
  }

  return {
    completedCount: res.data.completedCount || works.filter((w) => w.IsCompleted).length,
    inProgressCount: works.filter((w) => !w.IsCompleted).length,
    total: works.length,
    cached: res.cached,
    stale: !!res.stale,
    facilities: Array.from(byFacility.values()).sort((a, b) => b.completed.length - a.completed.length),
    room: knowledge.roomReport(res.data),
    works: works.map((w) => ({
      name: w.DisplayName,
      facility: w.FacilityName,
      state: w.State,
      done: !!w.IsCompleted,
      remainingSec: w.RemainingSeconds,
    })),
  };
}

/* ── 환경 / 주변 / 연주 / 퀘스트 ────────────────────────────── */

async function environment(opts) {
  const res = await cache.get('get_current_environment', opts);
  if (!res.data) return fail(res);
  const d = res.data;
  const h = d.Housing || {};
  return {
    channel: d.ChannelDisplayName,
    space: d.GameSpaceDisplayName,
    pos: d.WorldPosition ? { x: d.WorldPosition.X, y: d.WorldPosition.Y } : null,
    weather: d.Weather,
    erinnTime: d.ErinnNow,
    housing: { inside: !!h.IsInHousing, owned: !!h.IsOwnedHousing, canEnter: !!h.CanEnterHousing, canExit: !!h.CanExitHousing },
    cached: res.cached,
    stale: !!res.stale,
  };
}

async function inventory(opts) {
  const res = await cache.get('get_inventory', opts);
  if (!res.data) return fail(res);
  const d = res.data;
  return {
    current: d.CurrentInventoryWeightAsDecimal,
    max: d.MaxInventoryWeightAsDecimal,
    pct: Math.round((d.CurrentInventoryWeight / d.MaxInventoryWeight) * 100),
    cached: res.cached,
    stale: !!res.stale,
  };
}

async function quests(opts) {
  const res = await cache.get('get_quests', opts);
  if (!res.data) return fail(res);
  const rows = Array.isArray(res.data) ? res.data : [];
  return {
    total: rows.length,
    cached: res.cached,
    stale: !!res.stale,
    // 목표 설명에 <color=orange>…</color> 가 섞여 온다. 벗긴 값과 색 조각을 함께 넘겨
    // 화면은 색을 살리고, 터미널·검색은 글자만 쓰게 한다. (아이템 이름과 같은 방식)
    items: rows.map((q) => ({
      title: richtext.strip(q.QuestTitle),
      titleSeg: richtext.hasTags(q.QuestTitle) ? richtext.segments(q.QuestTitle) : null,
      source: q.SourceDisplayName || q.Source,
      objectives: (q.Objectives || []).map((o) => {
        const desc = richtext.strip(o.Description);
        // Goal이 0인 목표는 개수형이 아니라 단발성이다
        const prog = o.Goal > 0 ? o.Count + '/' + o.Goal : null;
        return {
          desc: desc,
          seg: richtext.hasTags(o.Description) ? richtext.segments(o.Description) : null,
          done: !!o.IsCompleted,
          // 설명 끝에 이미 같은 진행도가 붙어 오는 목표가 있다 ("심층 던전 클리어 2/3").
          // 그대로 또 붙이면 "2/3 2/3"이 된다.
          progress: prog && desc.indexOf(prog) === -1 ? prog : null,
        };
      }),
    })),
  };
}

async function nearNpcs(opts) {
  const res = await cache.get('get_near_npcs', Object.assign({ maxAgeMs: 0 }, opts));
  if (!res.data) return { total: 0, items: [] };
  const rows = Array.isArray(res.data) ? res.data : res.data.npcs || [];
  return { total: rows.length, items: rows };
}

async function nearPcs(opts) {
  const res = await cache.get('get_near_pcs', Object.assign({ maxAgeMs: 0 }, opts));
  if (!res.data) return { total: 0, items: [] };
  const rows = Array.isArray(res.data) ? res.data : [];
  return {
    total: rows.length,
    items: rows
      .map((p) => ({
        name: p.RealmName,
        title: p.Title,
        distance: Math.round(p.Distance * 10) / 10,
        level: p.Level,
        job: p.EnabledCombatJobDisplayName,
        combat: p.CombatScore,
        living: p.LivingScore,
        friend: !!p.IsFriend,
        party: !!p.IsInParty,
        sameGuild: !!p.IsSameGuild,
        inCombat: !!p.IsInCombat,
        playing: !!(p.Performance && p.Performance.IsPlaying),
        musicTitle: (p.Performance && p.Performance.MusicTitle) || '',
      }))
      .sort((a, b) => a.distance - b.distance),
  };
}

async function instruments(opts) {
  const res = await cache.get('get_instruments', opts);
  if (!res.data) return fail(res);
  const rows = Array.isArray(res.data) ? res.data : [];
  return {
    total: rows.length,
    cached: res.cached,
    stale: !!res.stale,
    // 내구도 int 최대값은 사실상 무한(소모 없음)을 뜻한다
    items: rows.map((i) => ({
      name: i.Name,
      durability: i.Durability >= 2147483647 ? null : i.Durability,
      equipped: !!i.IsEquipped,
    })),
  };
}

async function musicScores(opts) {
  const o = opts || {};
  const res = await cache.get('get_music_scores', o);
  if (!res.data) return fail(res);
  let rows = Array.isArray(res.data) ? res.data : [];
  if (o.search) rows = rows.filter((r) => matches(r.DisplayTitle, o.search));
  return {
    total: (res.data || []).length,
    matched: rows.length,
    cached: res.cached,
    stale: !!res.stale,
    items: rows.map((s) => ({
      title: s.DisplayTitle,
      location: s.Location,
      copyable: !!s.IsCopyingAllowed,
      locked: !!s.IsLocked,
    })),
  };
}

/**
 * 목록에는 없지만 행동과 다를 바 없는 것.
 * get_social_actions 가 주지 않으므로 여기서 더한다 — via 로 출처를 구분해 둔다.
 */
const STAND_UP = { name: '일어서기', commands: [], via: 'command', command: 'stand_up' };

async function socialActions(opts) {
  const o = opts || {};
  const res = await cache.get('get_social_actions', o);
  if (!res.data) return fail(res);
  let behaviours = res.data.Behaviours || [];
  let facials = res.data.Facials || [];
  if (o.search) {
    behaviours = behaviours.filter((b) => matches(b.DisplayName, o.search));
    facials = facials.filter((f) => matches(f.DisplayName, o.search));
  }
  const rows = behaviours.map((b) => ({
    name: b.DisplayName,
    commands: b.ChatCommands || [],
    via: 'chat',
  }));

  // 일어서기는 목록에 없지만 게임에서 하는 일은 다른 행동과 같다.
  // 앉기(/앉기)는 목록에 있는데 짝인 일어서기만 빠져 있어서, 같은 자리에 얹어 준다.
  // 다른 점은 보내는 방식뿐이다 — 채팅 명령이 아니라 전용 명령(stand_up)이다.
  if (!o.search || matches(STAND_UP.name, o.search)) rows.push(STAND_UP);

  return {
    cached: res.cached,
    stale: !!res.stale,
    behaviours: rows,
    facials: facials.map((f) => ({ name: f.DisplayName, emoji: f.EmojiText })),
  };
}

module.exports = {
  craft,
  craftFind,
  alter,
  gather,
  items,
  itemCount,
  currencies,
  wings,
  me,
  daily,
  weekly,
  activity,
  alteringWorks,
  environment,
  inventory,
  quests,
  nearNpcs,
  nearPcs,
  instruments,
  musicScores,
  socialActions,
  matches,
};
