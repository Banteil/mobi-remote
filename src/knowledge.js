'use strict';
/**
 * 커넥터가 알려주지 않는 정보를 모아 두는 곳.
 *
 * 게임은 여러 조건을 종합해 ✔/✘ 결론만 주고, 판정에 쓰인 값은 대부분 감춘다.
 * 시설 레벨·가공 큐 칸 수·아이템이 어느 시설 소속인지 등이 그렇다.
 * 그런 것들을 **관측해서 쌓아 두고**, 필요하면 사용자가 직접 고칠 수 있게 한다.
 *
 * ── 왜 필요한가 ────────────────────────────────────────────
 * 가공 큐가 꽉 찬 상태에서 등록을 시도하면 이렇게 된다 (실측).
 *   { error: 'blocked', kind: 'unknown_modal', cost: '정령의 날개 5 spent, ...' }
 * 이동까지 진행된 뒤 막히므로 **날개 5가 이미 나간다.** 거부가 공짜가 아니다.
 * 그래서 "일단 시도해 보고 실패하면 멈춘다"는 전략을 쓸 수 없고,
 * 시도 전에 칸이 남았는지 알아야 한다. 그 근거가 여기 쌓인다.
 */
const fs = require('fs');
const path = require('path');
const gamerules = require('./gamerules');
const recipebook = require('./recipebook');
const facilitymap = require('./facilitymap');
const paths = require('./paths');

const FILE = paths.dataPath('knowledge.json');

/** 관측 정보가 하나도 없을 때 쓰는 값. 사용자가 확인해 준 수치다. */
/**
 * 아무것도 모를 때 쓰는 칸 수 = **최고 레벨의 칸 수**.
 *
 * 적게 잡으면 시설이 남아도는데 덜 채우게 되고, 사용자는 왜 안 채워지는지 알기 어렵다.
 * 크게 잡으면 한 번은 막혀 날개 5가 나가지만, 그 한 번으로 레벨이 확정되어 다시는 안 나간다.
 * 레벨을 직접 정해 두면 애초에 막힐 일도 없다 — 그쪽이 권장 경로다.
 */
function defaultSlots() {
  return gamerules.slotsForLevel(gamerules.maxLevel());
}

function empty() {
  return {
    version: 1,
    /** 시설명 → { maxSlots, observedMax, manual, updatedAt } */
    facilities: {},
    /** 아이템명 → 시설명. get_altering_works에서만 알 수 있다. */
    itemFacility: {},
    /** 제작 레시피명 → { maxCount, at }. invalid_count 응답에서 배운다. */
    craftLimits: {},
    /** 레시피명 → { kind, produced, ingredients, confidence, ... }. 아래 "레시피" 절 참고. */
    recipes: {},
    /** 레시피명 → { item, at }. 이름이 곧 산출물은 아니다 — 아래 "레시피 → 산출물" 절 참고. */
    recipeProduct: {},
    updatedAt: null,
  };
}

function load() {
  try {
    const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    return Object.assign(empty(), d);
  } catch (_) {
    return empty();
  }
}

function save(state) {
  state.updatedAt = new Date().toISOString();
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify(state, null, 2), 'utf8');
  } catch (_) {
    /* 저장 실패해도 동작은 계속된다 */
  }
  return state;
}

/* ── 가공 시설 ──────────────────────────────────────────────── */

function facilityEntry(state, name) {
  if (!state.facilities[name]) {
    state.facilities[name] = {
      level: null,
      autoLevel: false,
      maxSlots: null,
      observedMax: 0,
      manual: false,
      fullAt: null,
      updatedAt: null,
    };
  }
  return state.facilities[name];
}

/**
 * get_altering_works 응답에서 배운다.
 *  · 아이템이 어느 시설 소속인지 (다른 어떤 조회로도 알 수 없다)
 *  · 시설별 동시 작업 수의 최대치 (칸 수의 하한이 된다)
 */
function learnFromAlteringWorks(data) {
  const works = (data && data.works) || [];
  if (!works.length) return load();

  const state = load();
  const count = new Map();
  for (const w of works) {
    if (!w.FacilityName) continue;
    state.itemFacility[w.DisplayName] = w.FacilityName;
    count.set(w.FacilityName, (count.get(w.FacilityName) || 0) + 1);
  }
  for (const [fac, n] of count) {
    const e = facilityEntry(state, fac);
    if (n > e.observedMax) {
      e.observedMax = n;
      e.updatedAt = new Date().toISOString();
    }
  }

  // 지금 큐에 없는 시설도 다시 본다. 관측 기록은 이미 남아 있으니,
  // 그 시설에 작업이 걸려 있는지와 무관하게 결론은 같다.
  for (const fac of Object.keys(state.facilities)) confirmTopLevel(state.facilities[fac]);

  return save(state);
}

/**
 * 큐에 최고 레벨의 칸 수만큼 올라갔다면 레벨이 확정된다.
 *
 * 칸 수는 레벨을 넘을 수 없으므로, 최고 레벨의 칸 수(지금은 7)를 채웠다는 것은
 * 그 시설이 최고 레벨이라는 뜻이다. 막혀 볼 필요가 없다 — 이미 답이 나와 있다.
 *
 * 중간 레벨은 이렇게 확정할 수 없다. 5칸까지 올라간 시설은 레벨 4일 수도, 그보다 높은데
 * 아직 5개만 넣어 본 것일 수도 있다. 그건 막히거나 사용자가 골라 줘야 알 수 있다.
 */
function confirmTopLevel(e) {
  if (e.manual) return;                       // 사용자가 고른 값이 우선이다
  const top = gamerules.maxLevel();
  const topSlots = gamerules.slotsForLevel(top);
  if (!(e.observedMax >= topSlots)) return;

  e.level = top;
  e.maxSlots = topSlots;
  e.manual = true;
  e.autoLevel = true;
  e.updatedAt = new Date().toISOString();
}

/** 칸이 꽉 차서 거부당한 시점을 기록한다. 그때의 작업 수가 곧 칸 수다. */
function learnFacilityFull(facility, usedSlots) {
  const state = load();
  const e = facilityEntry(state, facility);
  const n = Math.round(Number(usedSlots));

  // 칸 수가 지금까지 본 최대 큐보다 작을 수는 없다.
  // blocked 가 늘 "칸 부족"인 것은 아니라서(다른 팝업일 수도 있다) 이 검사로 오염을 막는다.
  // 7개까지 올라갔던 시설이 2에서 막혔다면 그건 칸 문제가 아니다.
  if (!(n > 0) || n < (e.observedMax || 0)) return state;

  e.fullAt = { slots: n, at: new Date().toISOString() };
  if (n > e.observedMax) e.observedMax = n;

  // 사용자가 직접 지정하지 않았다면, 꽉 찬 시점의 수를 칸 수로 본다.
  // 칸 수가 정해지면 레벨도 정해진다 — 표에서 거꾸로 찾는다.
  if (!e.manual) {
    e.maxSlots = n;
    const lv = gamerules.levelForSlots(n);
    if (lv) {
      e.level = lv;
      e.manual = true;   // 이제 확정값이다. 더 유추하지 않는다.
      e.autoLevel = true;
    }
  }
  e.updatedAt = new Date().toISOString();
  return save(state);
}

/** 막혀서 자동으로 정해진 레벨인가. 화면에 "직접 지정"과 구분해 적을 때 쓴다. */
function facilityLevelAuto(facility, state) {
  const e = (state || load()).facilities[facility];
  return !!(e && e.autoLevel);
}

/** 사용자가 직접 칸 수를 지정한다. 시설 레벨을 올렸을 때 등. */
function setFacilitySlots(facility, slots) {
  const state = load();
  const e = facilityEntry(state, facility);
  e.maxSlots = slots > 0 ? slots : null;
  e.manual = slots > 0;
  e.updatedAt = new Date().toISOString();
  return save(state);
}

/**
 * 이 시설의 칸 수. 확실한 순서대로 고른다.
 * 사용자 지정 > 꽉 참이 관측된 수 > 관측 최대치 > 기본값
 */
function facilitySlots(facility, state) {
  const s = state || load();
  const e = s.facilities[facility];
  const base = defaultSlots();
  if (!e) return { slots: base, source: '레벨 미설정', level: null };

  // 1) 사용자가 고른 레벨. 게임 화면을 보는 사람만 아는 값이라 무엇보다 우선한다.
  if (e.level > 0) {
    return { slots: gamerules.slotsForLevel(e.level), source: '레벨 ' + e.level, level: e.level, levelSet: true };
  }
  // 2) 레벨 기능을 넣기 전에 칸 수를 직접 넣어 둔 기록
  if (e.manual && e.maxSlots) {
    return { slots: e.maxSlots, source: '직접 입력', level: gamerules.levelForSlots(e.maxSlots) };
  }
  // 3) 꽉 차서 막혔던 적이 있으면 그때의 작업 수가 곧 칸 수다
  if (e.fullAt) {
    return { slots: e.fullAt.slots, source: '확인됨', level: gamerules.levelForSlots(e.fullAt.slots) };
  }
  // 4) 아무것도 모른다. 최고 레벨인 셈 치고 진행하다가, 막히면 그때 확정된다.
  //    관측치로 낮춰 잡으면 "아직 몇 개 안 넣어 봤다"는 이유로 시설이 작아 보인다.
  return { slots: base, source: '레벨 미설정', level: gamerules.levelForSlots(base) };
}

/**
 * 지금 이 시설에 더 넣을 수 있는가.
 *
 * 레벨을 정해 둔 시설은 그 칸 수가 **상한**이다. 넘겨서 시도하면 게임이 막으면서
 * 날개 5를 가져가므로, 보내기 전에 여기서 걸러야 한다.
 *
 * @returns {{ ok: boolean, slots: number, used: number, free: number, source: string }}
 */
function facilityRoom(facility, used, state) {
  const cap = facilitySlots(facility, state);
  const u = Math.max(0, Math.round(Number(used) || 0));
  return {
    ok: u < cap.slots,
    slots: cap.slots,
    used: u,
    free: Math.max(0, cap.slots - u),
    source: cap.source,
    levelSet: !!cap.levelSet,
  };
}

/** 시설 레벨을 지정한다. 0이나 null을 주면 지정을 지운다. */
function setFacilityLevel(facility, level) {
  const state = load();
  const e = facilityEntry(state, facility);
  const n = Math.round(Number(level));
  if (n >= 1) {
    e.level = Math.min(n, gamerules.maxLevel());
    e.maxSlots = gamerules.slotsForLevel(e.level);
    e.manual = true;
    e.autoLevel = false;   // 사람이 고른 값이 자동 감지보다 우선이다
  } else {
    e.level = null;
    e.manual = false;
    e.autoLevel = false;
    e.fullAt = null;       // 지정을 지우면 옛 감지 결과도 같이 지운다
  }
  e.updatedAt = new Date().toISOString();
  return save(state);
}

/**
 * 이 레시피가 어느 시설 것인가.
 *
 * 실제로 큐에서 본 값이 먼저다. 없으면 facility-map.json 의 표를 본다 —
 * 한 번도 안 돌려 본 레시피도 "그 시설이 꽉 찼는지"를 미리 검사할 수 있게 하려는 것이다.
 * 한 번 돌리면 관측값이 쌓여 그쪽이 쓰이므로, 표가 틀려도 저절로 고쳐진다.
 */
function facilityOf(itemName, state) {
  const s = state || load();
  return s.itemFacility[itemName] || facilitymap.facilityOf(itemName) || null;
}

/**
 * 지금 각 시설에 몇 칸이 남았는지.
 * 완료된 작업도 칸을 차지하므로 함께 센다 (수령해야 비워진다).
 */
function roomReport(worksData) {
  const state = load();
  const works = (worksData && worksData.works) || [];
  const used = new Map();
  const completed = new Map();
  for (const w of works) {
    used.set(w.FacilityName, (used.get(w.FacilityName) || 0) + 1);
    if (w.IsCompleted) completed.set(w.FacilityName, (completed.get(w.FacilityName) || 0) + 1);
  }
  const names = new Set([...used.keys(), ...Object.keys(state.facilities)]);
  return Array.from(names).map((fac) => {
    const cap = facilitySlots(fac, state);
    const u = used.get(fac) || 0;
    return {
      facility: fac,
      used: u,
      completed: completed.get(fac) || 0,
      slots: cap.slots,
      free: Math.max(0, cap.slots - u),
      source: cap.source,
      level: cap.level,
      levelSet: !!cap.levelSet,
      levelAuto: !!(state.facilities[fac] && state.facilities[fac].autoLevel),
    };
  }).sort((a, b) => b.free - a.free);
}

/* ── 제작 상한 ──────────────────────────────────────────────── */

/** invalid_count 응답의 maxCount를 기억해 둔다. 다음부터 미리 맞출 수 있다. */
function learnCraftLimit(recipe, maxCount) {
  if (!recipe || !(maxCount > 0)) return load();
  const state = load();
  state.craftLimits[recipe] = { maxCount: maxCount, at: new Date().toISOString() };
  return save(state);
}

/**
 * 한 번의 제작 호출로 만들 수 있는 최대 횟수.
 *
 * **종류를 따지지 않고 10이다.** 100개를 만들려면 10개씩 열 번 부른다.
 * 실제로 부딪혀 알아낸 값도 전부 10이었다 (못 · 탁월한 회복 물약 · 탁월한 자동회복 물약).
 */
const CRAFT_LIMIT = 10;

/**
 * 배운 값이 있으면 그쪽이 먼저다 — 규칙과 다른 레시피가 있으면 게임이 invalid_count로
 * 알려주고, 그 값이 여기 쌓여 규칙을 이긴다. 없으면 규칙값(10)을 쓴다.
 */
function craftLimit(recipe, state) {
  const e = (state || load()).craftLimits[recipe];
  return e ? e.maxCount : CRAFT_LIMIT;
}

/* ── 레시피 ─────────────────────────────────────────────────── */

/**
 * 레시피를 관측해서 쌓아 둔다.
 *
 * 게임은 **제작 불가능한** 레시피에만 MissingIngredients를 붙이고, 그것도
 * "가방 기준으로 모자란 재료"만 담는다. 달걀프라이가 달걀은 빼고 소금만 적어 오는 식이다.
 * 그래서 만들 수 있는 레시피일수록 재료를 하나도 모른다 — 정작 계획을 세워야 할 때다.
 *
 * 유일한 방법이 실행 전후의 인벤 비교다. 실측 — 못 1회 제작: 철괴 2 소모, 못 10 산출.
 * 조회로는 볼 수 없던 값이다.
 *
 * ── 출처가 둘이고 성격이 정반대다 ──────────────────────────
 *   MissingIngredients : 부족분만 담아 **불완전**하지만, 게임이 직접 말한 **정확한** 숫자
 *   인벤 diff          : 재료 **전체**를 보지만, 36초짜리 제작 중에 다른 일이 끼면 **오염**된다
 *
 * 그래서 게임이 준 숫자를 항상 우선한다(confidence: 'confirmed').
 * diff로 배운 값은 나중에 Required와 어긋나면 게임 쪽으로 덮어쓴다.
 *
 * ── 오염을 어떻게 거르는가 ────────────────────────────────
 *   · 줄어든 것만 재료 후보로 본다. 늘어난 것은 응답의 rewards가 말한 것만 인정한다.
 *   · 재화(정령의 날개 등)는 비용이지 재료가 아니다 — 제외한다.
 *   · 1회 실행일 때만 배운다. 여러 회를 나누면 중간에 낀 노이즈가 소수점으로 번진다.
 *   · 값이 다르면 덮어쓰지 않고 conflicts에 쌓는다. 같은 값이 두 번 나오면 그때 확정한다.
 *     (대성공·스킬 레벨로 소모가 달라질 가능성을 미리 부정하지 않는다)
 */

/** 비용으로 나가는 재화. 재료가 아니므로 diff에서 뺀다. */
const CURRENCIES = ['정령의 날개', '골드', '두카트'];

/**
 * get_items 응답을 { 이름 → 총 개수 }로 접는다.
 * 보관함·가방을 합치는 이유: 제작이 가방에서 먼저 빼 가지만(실측), 어느 쪽이 줄었는지는
 * 레시피와 무관하다. 총량 변화만이 실제 소모량이다.
 */
function itemTotals(itemsData) {
  const list = Array.isArray(itemsData)
    ? itemsData
    : (itemsData && (itemsData.items || itemsData.Items)) || [];
  const m = new Map();
  for (const x of list) {
    const n = x.DisplayName;
    if (!n) continue;
    m.set(n, (m.get(n) || 0) + (x.Count || 0));
  }
  return m;
}

/** 두 스냅샷의 차이. { 이름 → 증감 }, 변화 없는 것은 빼고 준다. */
function diffItems(before, after) {
  const out = {};
  const keys = new Set();
  for (const k of before.keys()) keys.add(k);
  for (const k of after.keys()) keys.add(k);
  for (const k of keys) {
    const d = (after.get(k) || 0) - (before.get(k) || 0);
    if (d !== 0) out[k] = d;
  }
  return out;
}

function recipeEntry(state, name) {
  if (!state.recipes[name]) {
    state.recipes[name] = {
      kind: null,
      produced: null,
      ingredients: null,
      confidence: null,   // 'diff' | 'confirmed' | 'partial'
      observed: 0,
      conflicts: [],
      updatedAt: null,
    };
  }
  return state.recipes[name];
}

function sameIngredients(a, b) {
  if (!a || !b) return false;
  const ka = Object.keys(a), kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => a[k] === b[k]);
}

/**
 * 실행 전후 인벤 비교로 레시피를 배운다.
 *
 * @param {string}  name      레시피명 (displayName 원문)
 * @param {string}  kind      'craft' | 'alter'
 * @param {object}  opts
 * @param {object}  opts.diff      diffItems() 결과
 * @param {number}  opts.runs      실행 횟수. 1이 아니면 배우지 않는다.
 * @param {Array}   opts.rewards   응답의 rewards. 산출량 확인용(없으면 생략)
 * @param {number}  opts.produced  ProducedPerCraft / ProducedPerWork (알면 교차 확인)
 */
function learnRecipeFromDiff(name, kind, opts) {
  const o = opts || {};
  if (!name || !o.diff) return load();
  // 1회 실행만 신뢰한다
  if (o.runs !== undefined && o.runs !== 1) return load();

  // 이 레시피가 만드는 것. 이름이 곧 산출물은 아니다 (철괴(광석) → 철괴).
  const product = productFromRewards(name, o.rewards) || productOf(name);

  const ingredients = {};
  for (const k of Object.keys(o.diff)) {
    const d = o.diff[k];
    if (d >= 0) continue;                 // 늘어난 것은 산출물이거나 잡음이다
    if (CURRENCIES.indexOf(k) !== -1) continue;  // 비용은 재료가 아니다
    if (k === name || k === product) continue;   // 자기 자신은 재료가 아니다
    ingredients[k] = -d;
  }
  if (!Object.keys(ingredients).length) return load();  // 배울 게 없다

  // 산출량 — rewards가 사실이고, 없으면 diff의 증가분으로 때운다
  let produced = null;
  if (Array.isArray(o.rewards)) {
    const hit = o.rewards.filter((r) => (r.Name || r.DisplayName) === product);
    if (hit.length) produced = hit.reduce((s, r) => s + (r.Amount || 0), 0);
  }
  if (produced === null && o.diff[product] > 0) produced = o.diff[product];
  if (produced === null && o.produced) produced = o.produced;

  // rewards가 산출물을 직접 말해 줬다면 추측을 사실로 바꾼다
  if (productFromRewards(name, o.rewards)) learnProduct(name, product);

  const state = load();
  const e = recipeEntry(state, name);
  e.kind = kind || e.kind;
  e.observed += 1;
  e.updatedAt = new Date().toISOString();
  if (produced) e.produced = produced;
  e.product = product;

  if (!e.ingredients) {
    e.ingredients = ingredients;
    e.confidence = 'diff';
  } else if (sameIngredients(e.ingredients, ingredients)) {
    // 같은 값을 다시 봤다 — 충돌로 쌓아 둔 것이 있으면 정리한다
    if (e.confidence !== 'confirmed') e.confidence = 'diff';
    e.conflicts = [];
  } else if (e.confidence === 'confirmed') {
    // 게임이 직접 준 값이 이미 있다. 덮어쓰지 않고 기록만 남긴다.
    e.conflicts.push({ ingredients: ingredients, at: e.updatedAt, from: 'diff' });
  } else {
    // 같은 충돌을 두 번 봤으면 그쪽이 맞다고 본다
    const twice = e.conflicts.some((c) => sameIngredients(c.ingredients, ingredients));
    e.conflicts.push({ ingredients: ingredients, at: e.updatedAt, from: 'diff' });
    if (twice) {
      e.ingredients = ingredients;
      e.conflicts = [];
    }
  }
  return save(state);
}

/**
 * get_craftable_items / get_alterable_items의 MissingIngredients에서 배운다.
 *
 * 이쪽은 게임이 직접 준 숫자라 **정확하지만 부족분만** 온다. 그래서 단독으로는
 * 레시피를 완성할 수 없고, diff로 배운 값을 검증하는 데 쓴다.
 *   · diff 값과 일치 → confidence를 'confirmed'로 올린다
 *   · 어긋남        → 게임 쪽으로 고친다 (diff가 오염됐다고 본다)
 *   · 아는 게 없음  → 부분 정보로만 저장한다 (confidence: 'partial')
 */
function learnRecipeFromMissing(name, kind, missing, produced) {
  if (!name || !Array.isArray(missing) || !missing.length) return load();

  const state = load();
  const e = recipeEntry(state, name);
  e.kind = kind || e.kind;
  e.updatedAt = new Date().toISOString();
  if (produced) e.produced = produced;

  if (!e.ingredients) {
    const partial = {};
    for (const m of missing) partial[m.DisplayName] = m.Required;
    e.ingredients = partial;
    e.confidence = 'partial';   // 전체 레시피가 아니다 — 부족했던 재료뿐
    return save(state);
  }

  // 아는 값과 대조한다. 게임이 말한 숫자가 이긴다.
  let fixed = false;
  for (const m of missing) {
    if (e.ingredients[m.DisplayName] !== m.Required) {
      e.ingredients[m.DisplayName] = m.Required;
      fixed = true;
    }
  }

  // 게임은 **부족한** 재료만 말한다. 아는 재료를 전부 짚어 줬을 때만 확정으로 올린다.
  // 일부만 맞았다고 전체를 믿으면, 검증 안 된 나머지가 확정으로 둔갑한다.
  const named = {};
  for (const m of missing) named[m.DisplayName] = true;
  const allNamed = Object.keys(e.ingredients).every((k) => named[k]);

  if (fixed) {
    e.conflicts.push({ fixedBy: 'MissingIngredients', at: e.updatedAt });
    // 하나가 틀렸다면 같은 diff에서 나온 나머지도 의심해야 한다
    e.confidence = allNamed ? 'confirmed' : 'partial';
  } else if (allNamed) {
    e.confidence = 'confirmed';
    e.conflicts = [];
  }
  return save(state);
}

function recipe(name, state) {
  const s = state || load();
  return s.recipes[name] || null;
}

/** 이 레시피로 N회분 계산을 해도 되는가. partial은 재료가 빠져 있어 안 된다. */
function recipeIsComplete(r) {
  return !!(r && r.ingredients && (r.confidence === 'diff' || r.confidence === 'confirmed'));
}

/**
 * 이 레시피의 1회분 재료를, 아는 것 중 가장 믿을 만한 곳에서 찾는다.
 *
 *   1. 직접 만들어 보고 인벤 변화로 알아낸 값 (diff / confirmed)
 *   2. 레시피 장부 — 게임이 알려 준 부족 재료를 모아 둔 표 (recipe-book.json)
 *   3. 아직 검증 안 된 부분 정보 (partial)
 *
 * 1번이 없을 때 2번이 있다는 것이 이 함수의 요점이다. 전에는 1번이 없으면 곧바로
 * "모릅니다"였고, 알아내려면 날개 5를 태워 한 번 만들어 보는 수밖에 없었다.
 *
 * @param have {(name)=>number} 보유량. 장부에 조합이 여럿일 때 가까운 쪽을 고르는 데 쓴다.
 * @returns {{ingredients, complete, source, variants}} 또는 null
 */
/**
 * 이 레시피에 드는 재료 **이름** 전부. 개수는 모를 수 있다.
 *
 * 재료 훑기(tools/sweep-ingredients.js)로 알아낸 것까지 포함한다. 개수를 몰라도
 * "이 재료가 든다"는 사실만으로 할 수 있는 말이 있다 — 자동으로 못 구하는 재료가 끼어
 * 있으면 시작하기 전에 알려 줄 수 있다.
 */
function recipeMaterials(name, opts) {
  const o = opts || {};
  const mine = recipe(name, o.state);
  if (recipeIsComplete(mine)) return Object.keys(mine.ingredients);
  const b = recipebook.pick(name, o.have);
  if (b) return Object.keys(b.ingredients);
  return mine && mine.ingredients ? Object.keys(mine.ingredients) : [];
}

function recipeIngredients(name, opts) {
  const o = opts || {};
  const mine = recipe(name, o.state);

  if (recipeIsComplete(mine)) {
    return { ingredients: mine.ingredients, complete: true, source: 'observed', variants: 1 };
  }

  const b = recipebook.pick(name, o.have);
  if (b) {
    // 장부에는 **이름만 아는** 재료가 섞여 있다 (개수 null). 그것으로 N회분을 곱하면
    // NaN 이 되므로, 계산에는 개수를 아는 것만 넘기고 이름은 따로 알려 준다.
    const known = {}; const unknown = [];
    for (const k of Object.keys(b.ingredients)) {
      const v = b.ingredients[k];
      if (v === null || v === undefined) unknown.push(k);
      else known[k] = v;
    }
    if (Object.keys(known).length) {
      return { ingredients: known, unknownAmounts: unknown,
        complete: !!b.complete && !unknown.length,
        source: 'book', variants: b.count };
    }
    // 개수를 아는 재료가 하나도 없으면 수량 계산에는 쓸 수 없다.
    // 이름은 recipeMaterials() 로 따로 꺼내 쓴다.
  }

  if (mine && mine.ingredients) {
    return { ingredients: mine.ingredients, complete: false, source: 'partial', variants: 1 };
  }
  return null;
}

/** 잘못 배운 것을 지운다. 관측이 틀렸을 때 사용자가 직접 지울 수 있어야 한다. */
function forgetRecipe(name) {
  const state = load();
  delete state.recipes[name];
  return save(state);
}

/* ── 레시피 → 산출물 ────────────────────────────────────────── */

/**
 * 레시피 이름이 곧 산출물 이름인 것은 아니다.
 *
 * 실측 — 가공 91종 중 8종이 `산출물(원료)` 꼴이다.
 *   철괴(광석), 철괴(철 광석)        → 둘 다 철괴를 만든다
 *   광휘의 결정(유령 반딧불이) 등     → 결정류도 원료별로 레시피가 갈린다
 *
 * 그런데 응답 어디에도 "이 레시피가 무엇을 만드는가" 필드가 없다. 이름이 유일한 단서다.
 * 그래서 괄호를 벗겨 추측하되(`guess`), 실제로 관측하면 그쪽으로 확정한다(`observed`).
 * 추측을 사실처럼 쓰면 "철괴가 필요한데 만들 방법이 없다"고 엉뚱하게 막힌다.
 */

/** 괄호 안은 원료를 구분하려고 붙은 것이다. 벗기면 산출물 이름이 된다. */
function guessProduct(recipeName) {
  return String(recipeName || '').replace(/\s*\([^()]*\)$/, '').trim() || recipeName;
}

/** 이 레시피가 만드는 것. 관측한 적 없으면 이름에서 추측한다. */
function productOf(recipeName, state) {
  const s = state || load();
  const e = (s.recipeProduct || {})[recipeName];
  return e ? e.item : guessProduct(recipeName);
}

/** 추측이 아니라 실제로 본 값인가. 화면에 근거를 적을 때 쓴다. */
function productIsObserved(recipeName, state) {
  const s = state || load();
  return !!(s.recipeProduct || {})[recipeName];
}

/** 보상으로 실제 무엇이 들어왔는지 봤을 때 기록한다. */
function learnProduct(recipeName, item) {
  if (!recipeName || !item) return load();
  const state = load();
  if (!state.recipeProduct) state.recipeProduct = {};
  const prev = state.recipeProduct[recipeName];
  if (prev && prev.item === item) return state;
  state.recipeProduct[recipeName] = { item: item, at: new Date().toISOString() };
  return save(state);
}

/**
 * 응답의 rewards에서 산출물을 고른다.
 * 한 종류만 왔으면 그것이고, 여럿이면 이름으로 추측한 것과 맞는 쪽을 택한다.
 * 어느 쪽도 아니면 고르지 않는다 — 틀린 확정보다 모르는 편이 낫다.
 */
function productFromRewards(recipeName, rewards) {
  if (!Array.isArray(rewards) || !rewards.length) return null;
  const names = rewards.map((r) => r.Name || r.DisplayName).filter(Boolean);
  if (!names.length) return null;
  if (names.length === 1) return names[0];
  const guess = guessProduct(recipeName);
  return names.indexOf(guess) !== -1 ? guess : null;
}

/* ── 비용 ───────────────────────────────────────────────────── */

/**
 * 응답의 cost 문장에서 실제 소모량을 뽑는다.
 * 예: "정령의 날개 5 spent, 52510 left."
 * 성공이든 blocked든 비용이 나갔으면 이 필드가 붙는다.
 */
function parseCost(data) {
  if (!data || typeof data.cost !== 'string') return null;
  const m = /([^\s]+(?:\s[^\s]+)*?)\s+(\d+)\s+spent(?:,\s*(\d+)\s+left)?/i.exec(data.cost);
  if (!m) return null;
  return {
    currency: m[1].trim(),
    amount: parseInt(m[2], 10),
    left: m[3] !== undefined ? parseInt(m[3], 10) : null,
    raw: data.cost,
  };
}

module.exports = {
  load, save, FILE, empty,
  learnFromAlteringWorks, learnFacilityFull, setFacilitySlots,
  facilitySlots, facilityRoom, setFacilityLevel, facilityLevelAuto, facilityOf, roomReport,
  learnCraftLimit, craftLimit,
  itemTotals, diffItems,
  learnRecipeFromDiff, learnRecipeFromMissing, recipe, forgetRecipe, recipeIsComplete,
  recipeIngredients, recipeMaterials,
  guessProduct, productOf, productIsObserved, learnProduct, productFromRewards,
  parseCost,
  defaultSlots,
};
