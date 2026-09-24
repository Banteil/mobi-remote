'use strict';
/**
 * 목표 제작 루프 — "다음 한 걸음"을 정하는 곳.
 *
 * 여기서는 **결정만 한다.** CLI를 부르지도, 사람에게 묻지도 않는다.
 * 실행과 사람 개입(확인 창 대기, 재료 직접 구해 오기)은 렌더러가 맡는다.
 * 그래야 게임 없이도 판단 로직을 시험할 수 있다.
 *
 * ── 왜 한 걸음씩인가 ────────────────────────────────────────
 * 미리 전체 계획을 짜 두면 금방 어긋난다. 채집은 한 번에 100개까지 들어오고,
 * 가공은 큐에 넣고 몇 분 뒤에야 결과가 나오며, 그 사이 시설 칸이 찬다.
 * 상태를 다시 읽고 그때 가장 나은 한 걸음을 고르는 편이 훨씬 덜 틀린다.
 *
 * ── 순서가 곧 정책이다 ──────────────────────────────────────
 * 1. 목표 달성 확인
 * 2. 목표에 쓰이는 재료가 완성돼 있으면 수령 — 공짜이고 칸도 비운다
 * 3. 자동으로 못 구하는 재료가 있으면 멈추고 사람에게 넘긴다
 * 4. 부족분을 채집/가공/하위 제작으로 채운다 (가장 많이 모자란 것부터)
 * 5. 재료가 차면 제작
 * 6. 기다려야 한다면, 그 시간에 남은 완료분을 거둔다
 *
 * ── 비용 구조 (실측) ───────────────────────────────────────
 * 날개 5는 **호출당**이지 개수당이 아니다. 그래서 묶을 수 있는 건 최대한 묶는다.
 *   제작  craftCount N회를 한 번에 → 날개 5   (실측: craftCount 3 → 철괴 6 소모, 날개 5)
 *   채집  한 호출에 최대 100개     → 날개 5
 *   가공  한 호출에 1건뿐           → 날개 5   (묶을 방법이 없다)
 *   수령  무료
 *
 * 제작 상한은 종류를 따지지 않고 **한 호출에 10회**다. 100개면 10개씩 열 번이다.
 * 다른 레시피가 나오더라도 큰 수를 넣어 거부당하면 게임이 알려주고(무료에 0.2초, 실측),
 * 그 값은 knowledge에 쌓여 규칙보다 앞선다.
 */
const query = require('./query');
const cache = require('./cache');
const knowledge = require('./knowledge');
const richtext = require('./richtext');
const errors = require('./errors');

/** 재료 조달 경로 */
const VIA = {
  GATHER: '채집',
  ALTER: '가공',
  CRAFT: '제작',
  NONE: '자동불가',
};

/** 재귀 깊이 상한. 철괴 ← 철 광석 정도가 현실적인 최대다. */
const MAX_DEPTH = 4;

/* ── 상태 수집 ──────────────────────────────────────────────── */

/**
 * 판단에 필요한 조회를 한 번에 모은다. 전부 무료다.
 * 한 걸음 실행한 뒤에는 반드시 새로 읽어야 한다 — 그래서 refresh가 기본값이다.
 */
async function snapshot(opts) {
  const o = Object.assign({ refresh: true }, opts || {});
  // 원본 응답을 그대로 읽는다. query 계층은 화면용으로 가공하면서 Required를 문자열로 접어 버린다.
  const [items, craft, alter, gather, works] = await Promise.all([
    cache.get('get_items', { refresh: o.refresh }),
    cache.get('get_craftable_items', { refresh: o.refresh }),
    cache.get('get_alterable_items', { refresh: o.refresh }),
    cache.get('get_gatherable_items', { refresh: o.refresh }),
    query.alteringWorks({ refresh: o.refresh }),
  ]);

  const missing = [items, craft, alter, gather].find((r) => !r || !r.data);
  if (missing) return { error: 'query_failed', message: '조회에 실패했습니다. 게임이 켜져 있는지 확인하세요.' };
  if (works.error) return { error: works.error, message: works.message };

  const kn = knowledge.load();
  const snap = {
    owned: ownedMap(items.data),
    craft: recipeMap(craft.data, 'Craftable', 'ProducedPerCraft'),
    alter: recipeMap(alter.data, 'Alterable', 'ProducedPerWork'),
    gather: gatherMap(gather.data),
    works: works,
    recipes: kn.recipes || {},
    kn: kn,
    stale: !!(items.stale || craft.stale || alter.stale || gather.stale),
  };
  snap.makers = makerIndex(snap, kn);
  return snap;
}

/**
 * 산출물 → 그것을 만드는 레시피들.
 *
 * 레시피 이름이 곧 산출물 이름인 것은 아니다. 철괴(광석)과 철괴(철 광석)은
 * 둘 다 철괴를 만든다. 이름으로 찾으면 "철괴는 만들 방법이 없다"고 엉뚱하게 막힌다.
 * 만드는 길이 여럿이면 **지금 당장 가능한 것**을 먼저 쓴다.
 */
function makerIndex(snap, kn) {
  const m = new Map();
  const add = (product, entry) => {
    if (!m.has(product)) m.set(product, []);
    m.get(product).push(entry);
  };
  for (const [name, e] of snap.alter) {
    if (e.name !== name) continue;   // 태그를 벗긴 별칭 키는 건너뛴다
    add(knowledge.productOf(name, kn), { recipe: name, via: VIA.ALTER, ok: e.ok, per: e.per, missing: e.missing });
  }
  for (const [name, e] of snap.craft) {
    if (e.name !== name) continue;
    add(knowledge.productOf(name, kn), { recipe: name, via: VIA.CRAFT, ok: e.ok, per: e.per, missing: e.missing });
  }
  // 만드는 길이 여럿이면 **호출당 더 많이 나오는 쪽**을 고른다. 날개는 호출당 5라
  // 호출 수가 곧 비용이다. 제작은 craftCount 로 묶이므로 상한까지 곱해서 세고,
  // 가공은 한 호출에 1건이라 묶을 수가 없다.
  //
  // 실측 — 만드는 길이 둘 이상인 산출물 92종 중 산출 개수가 다른 것은 1종뿐이고
  // (최상급 붕대 ×10 / ×5), 제작·가공이 섞인 것은 없었다. 지금은 거의 쓰이지 않는
  // 판단이지만, 업데이트로 그런 레시피가 생겼을 때 조용히 비싼 쪽을 고르지 않게 해 둔다.
  const yieldPerCall = (e) =>
    (e.per || 1) * (e.via === VIA.CRAFT ? knowledge.craftLimit(e.recipe, kn) : 1);

  for (const list of m.values()) {
    list.sort((a, b) =>
      (b.ok ? 1 : 0) - (a.ok ? 1 : 0) ||
      yieldPerCall(b) - yieldPerCall(a));
  }
  return m;
}

/**
 * 이름 → 총 개수. 가방·보관함을 **합친다**.
 * 제작·가공 판정이 양쪽을 보기 때문이다 (MissingIngredients의 Owned는 가방만 센다 — 쓰지 않는다).
 */
function ownedMap(data) {
  const m = new Map();
  const add = (n, c) => {
    m.set(n, (m.get(n) || 0) + c);
    const bare = richtext.strip(n);
    if (bare !== n) m.set(bare, (m.get(bare) || 0) + c);
  };
  for (const x of listOf(data)) if (x.DisplayName) add(x.DisplayName, x.Count || 0);
  return m;
}

function listOf(data) {
  if (Array.isArray(data)) return data;
  return (data && (data.items || data.Items)) || [];
}

/**
 * 레시피 목록을 이름으로 찾을 수 있게 편다.
 * 색상 태그가 붙은 이름은 벗긴 키도 함께 넣어 둔다 — 재료 이름과 맞춰야 하기 때문이다.
 */
function recipeMap(data, okKey, perKey) {
  const m = new Map();
  for (const r of listOf(data)) {
    const raw = r.DisplayName;
    if (!raw) continue;
    const e = {
      name: raw,
      ok: !!r[okKey],
      per: r[perKey] || 1,
      reason: r.Reason || null,
      // 게임이 준 부족분. 만들 수 없는 레시피에만 붙는다.
      missing: r.MissingIngredients || null,
    };
    m.set(raw, e);
    const bare = richtext.strip(raw);
    if (bare !== raw) m.set(bare, e);
  }
  return m;
}

function gatherMap(data) {
  const m = new Map();
  for (const r of listOf(data)) {
    if (!r.DisplayName) continue;
    m.set(r.DisplayName, { name: r.DisplayName, ok: !!r.ToolOk });
  }
  return m;
}

function have(snap, name) {
  return snap.owned.get(name) || 0;
}

/* ── 조달 경로 판정 ─────────────────────────────────────────── */

/**
 * 이 재료를 자동으로 구할 수 있는가, 있다면 어느 쪽인가.
 *
 * 채집을 가장 먼저 본다. 한 번에 100개까지 들어와서 호출당 효율이 제일 좋고,
 * 가공처럼 기다리거나 칸을 차지하지도 않는다.
 */
function viaOf(snap, name) {
  const g = snap.gather.get(name);
  // 도구가 없거나 내구도가 0이면 목록에 있어도 못 한다
  if (g) return g.ok ? VIA.GATHER : VIA.NONE;
  const made = makerFor(snap, name);
  return made ? made.via : VIA.NONE;
}

/** 이 아이템을 만드는 레시피 하나를 고른다. 지금 가능한 것이 앞에 온다. */
function makerFor(snap, name) {
  const list = snap.makers.get(name);
  return list && list.length ? list[0] : null;
}

/**
 * 이 레시피의 1회분 재료. 모르면 null.
 *
 * 게임은 만들 수 있는 레시피의 재료를 끝내 알려주지 않는다. 그래서 두 곳을 본다 —
 * 직접 만들어 보고 알아낸 값이 먼저고, 없으면 **레시피 장부**다. 장부의 값은
 * "적어도 이만큼"일 수 있어서 complete 를 같이 들고 다닌다.
 */
function recipeOf(snap, name) {
  const got = knowledge.recipeIngredients(name, {
    state: snap.kn,
    have: (n) => have(snap, n),
  });
  return got ? { ingredients: got.ingredients, complete: got.complete, source: got.source } : null;
}

/**
 * 게임이 말한 부족 재료를 { 이름: 1회분 요구량 }으로 바꾼다.
 *
 * 전체 레시피가 아니라 **모자란 것만** 온다. 그래서 이것만으로 N회분을 계산하면 모자라지만,
 * "다음에 무엇을 구해야 하는가"를 고르는 데는 충분하다. 구하고 나면 게임이 다음 부족분을 알려준다.
 */
function gameShortfall(maker) {
  const list = maker && maker.missing;
  if (!list || !list.length) return null;
  const out = {};
  for (const m of list) out[m.DisplayName] = m.Required;
  return out;
}

/* ── 다음 걸음 ──────────────────────────────────────────────── */

/**
 * 목표를 향한 다음 한 걸음.
 *
 * @param {object} snap   snapshot() 결과
 * @param {string} name   만들려는 것 (DisplayName 원문)
 * @param {number} target 목표 개수
 * @returns {object} kind: done | collect | craft | gather | alter | wait | learn | blocked
 */
function nextStep(snap, name, target) {
  if (snap.error) {
    return { kind: 'blocked', reason: 'query_failed', message: snap.message || '조회에 실패했습니다.' };
  }

  // 1) 다 만들었나
  const madeNow = have(snap, name);
  if (madeNow >= target) return { kind: 'done', have: madeNow, target: target };

  // 2) 목표에 쓰이는 재료가 가공대에서 완성돼 있으면 먼저 가져온다.
  //    공짜인 데다 칸을 비우고, 기다리던 재료가 바로 손에 들어온다.
  //    반대로 목표와 무관한 시설까지 도는 것은 시간만 버린다 — 시설마다 이동이 붙는다.
  const wanted = treeItems(snap, name);
  const useful = (snap.works.facilities || []).find((f) =>
    f.completed && f.completed.length &&
    f.completed.some((w) => wanted[knowledge.productOf(w.name, snap.kn)]));
  if (useful) {
    return { kind: 'collect', facility: useful.facility, name: useful.completed[0].name,
      why: '목표에 쓰이는 재료가 완성돼 있습니다. 먼저 수령합니다 (무료).' };
  }

  const step = resolve(snap, name, target - madeNow, 0, []);

  // 3) 어차피 기다려야 한다면, 그 시간에 남은 완료분을 거둬 둔다. 공짜다.
  if (step.kind === 'wait') {
    const any = (snap.works.facilities || []).find((f) => f.completed && f.completed.length);
    if (any) {
      return Object.assign({ goal: name, target: target, have: madeNow }, {
        kind: 'collect', facility: any.facility, name: any.completed[0].name,
        why: '어차피 기다리는 중이라 완료된 가공을 거둡니다 (무료).' });
    }
  }

  return Object.assign({ goal: name, target: target, have: madeNow }, step);
}

/**
 * 목표에 쓰이는 아이템 전체(목표 자신 포함). 수령이 도움이 되는지 판단하는 데 쓴다.
 * 수량은 보지 않는다 — "쓰이긴 하는가"만 알면 된다.
 */
function treeItems(snap, name) {
  const seen = {};
  (function walk(n, depth) {
    if (depth > MAX_DEPTH || seen[n]) return;
    seen[n] = true;
    const maker = makerFor(snap, n);
    if (!maker) return;
    const rec = recipeOf(snap, maker.recipe);
    const per1 = rec ? rec.ingredients : gameShortfall(maker);
    if (!per1) return;
    for (const ing of Object.keys(per1)) walk(ing, depth + 1);
  })(name, 0);
  return seen;
}

/**
 * "이것을 need개 더 얻으려면 지금 무엇을 해야 하나"를 재귀로 푼다.
 *
 * 한 번에 한 걸음만 낸다. 부족한 재료가 여럿이면 **가장 많이 모자란 것부터** 손댄다.
 * 조금씩 여러 재료를 건드리면 어느 것도 완성되지 않은 채 날개만 나간다.
 */
function resolve(snap, name, need, depth, trail) {
  if (depth > MAX_DEPTH) {
    return { kind: 'blocked', reason: 'too_deep', name: name,
      message: name + ' 까지 가는 재료 단계가 너무 깊습니다.' };
  }
  if (trail.indexOf(name) !== -1) {
    // 재료가 서로를 요구하는 경우. 도는 것보다 멈추고 알리는 편이 낫다.
    return { kind: 'blocked', reason: 'cycle', name: name,
      message: '재료가 순환합니다: ' + trail.concat(name).join(' → ') };
  }

  const via = viaOf(snap, name);

  if (via === VIA.NONE) {
    return { kind: 'blocked', reason: 'not_obtainable', name: name, need: need,
      message: name + ' 은(는) 채집·가공·제작 어느 쪽으로도 구할 수 없습니다.' };
  }

  if (via === VIA.GATHER) {
    // 한 호출에 최대 100개. 필요한 만큼만 부른다 — 남는 것도 결국 가방을 먹는다.
    return { kind: 'gather', name: name, need: need, times: Math.ceil(need / 100),
      why: name + ' ' + need + '개를 채집합니다.' };
  }

  // 여기서부터는 "무엇을 얻고 싶은가"(name)와 "어느 레시피를 부르는가"(maker.recipe)가 다르다.
  // execute_* 에는 레시피 이름을 그대로 넘겨야 한다 — 산출물 이름을 보내면 not_found다.
  const maker = makerFor(snap, name);
  const recipeName = maker.recipe;
  const per = maker.per || 1;
  const runs = Math.ceil(need / per);
  // 재료 말고 다른 이유로 막혀 있다면 여기서 끝난다.
  // 생활 스킬·시설 레벨·데코 점수는 앱이 어떻게 해 줄 수 있는 게 아니다.
  // 이걸 먼저 걸러야 "재료를 모릅니다" 같은 엉뚱한 안내가 나가지 않는다.
  if (!maker.ok && maker.reason && maker.reason !== 'not_enough_ingredient') {
    const ko = errors.describe(via === VIA.ALTER ? 'execute_altering' : 'execute_crafting', maker.reason);
    return { kind: 'blocked', reason: maker.reason, name: recipeName, product: name,
      message: recipeName + ' — ' + ((ko && ko.text) || maker.reason) +
        ((ko && ko.hint) ? ' ' + ko.hint : '') };
  }

  // 1회분 재료를 어디서 얻는가:
  //   익힌 레시피 → 전체를 안다 (N회분 계산 가능)
  //   게임의 MissingIngredients → **지금 모자란 것만** 안다. 그래도 다음 걸음을 고르기엔 충분하다.
  const rec = recipeOf(snap, recipeName);
  const per1 = rec ? rec.ingredients : gameShortfall(maker);

  if (!per1) {
    // 어느 쪽도 없다. 지금 당장 가능하면 1회 해 보고 배우는 게 가장 싸다 (날개 5).
    if (maker.ok) {
      // 반드시 1회다. 묶어서 돌리면 대성공 보너스가 섞여 재료량을 나눌 수 없다.
      // (실측: craftCount 3 → rewards 10×3 에 criticalRewards 1이 더 붙어 31개)
      return { kind: 'learn', via: via, name: recipeName, product: name, need: need, per: per,
        why: recipeName + ' 의 재료를 아직 모릅니다. 1회만 만들어 보고 재료를 알아냅니다.' };
    }
    return { kind: 'blocked', reason: 'unknown_recipe', name: recipeName, product: name, need: need,
      message: recipeName + ' 의 재료를 모르고, 지금은 만들 수도 없어 알아낼 방법이 없습니다. ' +
        '재료를 갖춰 한 번 직접 만들어 보시면 그때 배웁니다.' };
  }

  // 재료가 모자란 것부터 해결한다.
  // 부족량은 게임의 Owned(가방만)가 아니라 우리 총량(가방+보관함)으로 센다.
  const short = [];
  for (const ing of Object.keys(per1)) {
    const want = per1[ing] * runs;
    const has = have(snap, ing);
    if (has < want) short.push({ name: ing, lack: want - has, want: want, has: has });
  }

  if (short.length) {
    short.sort((a, b) => b.lack - a.lack);
    const worst = short[0];
    const sub = resolve(snap, worst.name, worst.lack, depth + 1, trail.concat(name));
    // 막힌 이유는 최종 목표까지 그대로 올려 보낸다
    return Object.assign(sub, { forRecipe: recipeName, otherShort: short.slice(1) });
  }

  // 재료는 찼다. 그런데도 안 된다면 시설 레벨·생활 스킬·장식 점수 같은 조건이다.
  if (!maker.ok) {
    return { kind: 'blocked', reason: 'not_allowed', name: recipeName, product: name,
      message: recipeName + ' 은(는) 재료가 갖춰졌는데도 지금은 ' + via + '할 수 없습니다. ' +
        '시설 레벨이나 생활 스킬 조건일 수 있습니다.' };
  }

  if (via === VIA.CRAFT) {
    // 날개 5는 호출당이다. 한 번에 최대한 묶는다.
    const limit = knowledge.craftLimit(recipeName, snap.kn);
    const batch = Math.min(runs, limit);
    return { kind: 'craft', name: recipeName, product: name,
      runs: runs, batch: batch, limit: limit, calls: Math.ceil(runs / limit),
      per: per, need: need,
      why: recipeName + ' ' + batch + '회 제작 → ' + name + ' 약 ' + batch * per + '개' +
        (runs > limit ? ' (상한 ' + limit + '회라 나눠서 ' + Math.ceil(runs / limit) + '번 호출)' : '') };
  }

  // 가공은 칸이 있어야 한다. 꽉 찬 상태에서 등록하면 날개 5가 그냥 나간다(실측).
  const fac = knowledge.facilityOf(recipeName, snap.kn);
  const room = fac ? (snap.works.room || []).find((r) => r.facility === fac) : null;
  if (room && room.free <= 0) {
    // 그 시설에 수령할 것이 있으면 수령이 곧 칸을 비운다. 없으면 기다리는 수밖에 없다.
    const f = (snap.works.facilities || []).find((x) => x.facility === fac && x.completed.length);
    if (f) {
      return { kind: 'collect', facility: fac, name: f.completed[0].name,
        why: fac + ' 칸이 차 있습니다. 완료분을 수령하면 비워집니다 (무료).' };
    }
    return waitStep(snap, recipeName,
      '가공 칸이 모두 차 있습니다 (' + fac + ' ' + room.used + '/' + room.slots + ').');
  }

  // 가공은 한 호출에 **1건**만 큐에 들어간다. 묶을 방법이 없어서 건당 날개 5다.
  // 그래서 여기서는 "한 건"만 지시하고, 나머지는 다음 걸음에서 다시 판단한다.
  const free = room ? room.free : null;
  const queued = room ? room.used : 0;
  return { kind: 'alter', name: recipeName, product: name,
    runs: 1, wanted: runs, per: per, need: need, facility: fac, free: free, queued: queued,
    why: recipeName + ' 1건 등록 (' + name + ' ' + need + '개까지 총 ' + runs + '건 필요' +
      (free !== null ? ', 여유 ' + free + '칸' : '') + ')' };
}

/** 지금은 기다리는 것 말고 할 일이 없을 때. 언제 다시 볼지 함께 알려준다. */
function waitStep(snap, name, why) {
  const left = [];
  for (const f of snap.works.facilities || []) {
    for (const w of f.inProgress || []) left.push(w.remainingSec);
  }
  if (!left.length) {
    return { kind: 'blocked', reason: 'stuck', name: name,
      message: why + ' 그런데 진행 중인 작업도 없어 기다려도 풀리지 않습니다.' };
  }
  return { kind: 'wait', seconds: Math.max(5, Math.min.apply(null, left)), name: name, why: why };
}

/* ── 사전 견적 ──────────────────────────────────────────────── */

/**
 * 시작 전에 대략 얼마가 드는지.
 *
 * **어디까지나 하한이다.** 레시피를 모르는 단계가 있으면 그 아래는 셀 수 없고,
 * 채집이 한 번에 몇 개를 줄지도 해 봐야 안다. 화면에 그렇게 적어야 한다.
 */
function estimate(snap, name, target) {
  if (snap.error) return { calls: 0, wings: 0, partial: true };
  const seen = {};
  let calls = 0;
  let partial = false;

  (function walk(n, need, depth) {
    if (depth > MAX_DEPTH || need <= 0 || seen[n]) return;
    seen[n] = true;

    const via = viaOf(snap, n);
    if (via === VIA.NONE) { partial = true; return; }
    if (via === VIA.GATHER) { calls += Math.ceil(need / 100); return; }

    const maker = makerFor(snap, n);
    const per = (maker && maker.per) || 1;
    const runs = Math.ceil(need / per);
    // 제작만 묶을 수 있다 — 한 호출에 상한(기본 10)까지.
    if (via === VIA.CRAFT) {
      calls += Math.ceil(runs / knowledge.craftLimit(maker.recipe, snap.kn));
    } else {
      calls += runs;
    }

    const rec = maker ? recipeOf(snap, maker.recipe) : null;
    const per1 = rec ? rec.ingredients : gameShortfall(maker);
    if (!per1) { partial = true; return; }
    // 재료를 다 아는 것이 아니면 아래 단계는 과소 집계다.
    // 장부에서 온 값도 complete 가 아니면 마찬가지다 — 그때 모자랐던 재료만 담겨 있다.
    if (!rec || !rec.complete) partial = true;
    for (const ing of Object.keys(per1)) {
      const want = per1[ing] * runs;
      const has = have(snap, ing);
      if (has < want) walk(ing, want - has, depth + 1);
    }
  })(name, Math.max(0, target - have(snap, name)), 0);

  return { calls: calls, wings: calls * 5, partial: partial };
}

module.exports = { snapshot, nextStep, estimate, VIA, MAX_DEPTH };
