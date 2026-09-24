'use strict';
/**
 * 가공 재료표(CSV) → alter-recipes.json
 *
 * ── 왜 필요한가 ────────────────────────────────────────────
 * 게임은 **지금 만들 수 없는** 레시피의 **모자란 재료만** 알려준다. 그래서 장부
 * (recipe-book.json)는 아무리 모아도 군데군데 비어 있고, 필요한 시설 레벨은 아예 알 수 없다.
 * 사람이 정리한 표가 있으면 그 두 구멍이 한 번에 메워진다.
 *
 * ── 표의 생김새 ────────────────────────────────────────────
 *   가공품,조건,시간,재료
 *   철괴 x3,금속 가공 시설 Lv.1,30초,광석 x20
 *   강철괴 x3,금속 가공 시설 Lv.1,5분,"철괴 x3
 *   석탄 x4"
 *
 * 재료 칸은 여러 줄이 따옴표로 묶여 온다. 줄마다 "이름 x개수".
 * 칸의 자리는 **머리말을 보고 찾는다.** 표에 칸이 하나 늘어난 적이 있어서,
 * 순서를 코드에 박아 두면 그때마다 조용히 어긋난다.
 *
 * ── 같은 이름이 여러 갈래일 수 있다 ────────────────────────
 * 같은 물건을 다른 재료로도 만들 수 있다. 실측 — 은합금괴는 Lv.4(특수강괴)와
 * Lv.6(마력 깃든 돌) 두 갈래다. 이름 하나에 재료를 몰아 담으면 둘을 합친 가짜
 * 레시피가 되므로 갈래(variant)를 따로 담는다. 장부가 바로 그 실수를 하고 있다.
 *
 * 쓰는 법:  node tools/parse-alter-csv.js "<csv 경로>" [출력 경로]
 */
const fs = require('fs');
const path = require('path');

/* ── CSV 읽기 ──────────────────────────────────────────────
 * 따옴표 안에 줄바꿈과 쉼표가 들어오므로 줄 단위로 자를 수 없다. 한 글자씩 본다. */
function parseCsv(text) {
  const rows = [];
  let row = [], cell = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; }   // "" 는 따옴표 한 개
        else quoted = false;
      } else cell += c;
      continue;
    }
    if (c === '"') { quoted = true; continue; }
    if (c === ',') { row.push(cell); cell = ''; continue; }
    if (c === '\r') continue;
    if (c === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; continue; }
    cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

/**
 * 표의 이름을 **게임이 쓰는 이름**으로 바로잡는다.
 *
 * 앱은 아이템을 이름으로 정확히 대조해 재고를 찾는다. 한 글자만 달라도 "없다"가 되어
 * 계획이 통째로 어긋난다. 그래서 어긋난 것이 확인되면 여기서 고친다.
 *
 * ── 지금 고치는 것 ─────────────────────────────────────
 * 표에 `단단한 통나무+` / `부드러운 통나무+` 로 적힌 것. **그런 아이템은 없다.**
 *
 *   게임이 말한 부족 재료   단단한 목재 ← 단단한 통나무 30   (표는 단단한 통나무+ 30)
 *   채집 목록              통나무 · 단단한 통나무 · 부드러운 통나무 · 상급 통나무 ·
 *                         상급 통나무+ · 최상급 통나무 · 최상급 통나무+ · 특급 통나무
 *                         → 단단한/부드러운 쪽에는 + 가 아예 없다
 *   소지품                 단단한 통나무 95 · 부드러운 통나무 55 · + 는 둘 다 없음
 *
 * 부드러운 목재는 그 재료가 모자란 목록에 안 뜨는데(55개를 갖고 있으니 당연하다),
 * + 쪽은 0개이므로 표가 맞았다면 모자란 목록에 떴어야 한다. 그래서 같은 오타로 본다.
 *
 * CSV 를 고치면 이 표는 지워도 된다. 지워도 결과가 같은지 아래 CHECK 로 확인한다.
 */
const RENAME = {
  '단단한 통나무+': '단단한 통나무',
  '부드러운 통나무+': '부드러운 통나무',
};

/** "철괴 x3" → { name: '철괴', count: 3 } · 개수가 없으면 1 */
function parseAmount(s) {
  const t = String(s || '').trim();
  if (!t) return null;
  const m = /^(.*?)\s*[xX×]\s*([0-9,]+)$/.exec(t);
  const fix = (n) => RENAME[n] || n;
  if (!m) return { name: fix(t), count: 1 };
  return { name: fix(m[1].trim()), count: parseInt(m[2].replace(/,/g, ''), 10) };
}

/**
 * "1시간 30분" → 5400 · "30초" → 30 · "6시간" → 21600
 *
 * 단위를 여러 개 이어 붙인 형태라 하나씩 긁어 더한다. 하나도 못 읽으면 null 을 준다 —
 * 0 으로 두면 "즉시 끝남"으로 잘못 읽히기 때문이다.
 */
const TIME_UNIT = { 일: 86400, 시간: 3600, 시: 3600, 분: 60, 초: 1 };
function parseDuration(s) {
  const t = String(s || '').trim();
  if (!t) return null;
  let sec = 0, hit = false;
  const re = /([0-9]+)\s*(일|시간|시|분|초)/g;
  let m;
  while ((m = re.exec(t))) { sec += parseInt(m[1], 10) * TIME_UNIT[m[2]]; hit = true; }
  return hit ? sec : null;
}

/** "금속 가공 시설 Lv.4" → { facility: '금속 가공 시설', level: 4 } */
function parseCondition(s) {
  const t = String(s || '').trim();
  const m = /^(.*?)\s*Lv\.?\s*([0-9]+)$/i.exec(t);
  if (!m) return { facility: t, level: null };
  return { facility: m[1].trim(), level: parseInt(m[2], 10) };
}

function build(csvPath) {
  const raw = fs.readFileSync(csvPath, 'utf8').replace(/^﻿/, '');
  const rows = parseCsv(raw).filter((r) => r.some((c) => String(c).trim() !== ''));
  const head = (rows.shift() || []).map((h) => String(h).trim());

  // 칸 자리는 머리말에서 찾는다. 이름이 바뀌면 여기만 고치면 된다.
  const col = (...want) => {
    for (const w of want) {
      const i = head.indexOf(w);
      if (i >= 0) return i;
    }
    return -1;
  };
  const iProd = col('가공품', '결과물'), iCond = col('조건'), iMat = col('재료'), iTime = col('시간', '소요 시간');
  if (iProd < 0 || iCond < 0 || iMat < 0) {
    throw new Error('머리말에서 칸을 못 찾았다 — ' + JSON.stringify(head));
  }

  const recipes = {};
  const problems = [];
  let lineNo = 1;

  for (const r of rows) {
    lineNo++;
    const prodCell = r[iProd], condCell = r[iCond], matCell = r[iMat];
    const sec = iTime >= 0 ? parseDuration(r[iTime]) : null;
    if (iTime >= 0 && sec === null && String(r[iTime] || '').trim()) {
      problems.push(lineNo + '행: 시간을 못 읽음 "' + r[iTime] + '"');
    }
    const prod = parseAmount(prodCell);
    if (!prod) { problems.push(lineNo + '행: 가공품 칸이 비었다'); continue; }
    const cond = parseCondition(condCell);

    const ingredients = {};
    let bad = false;
    for (const line of String(matCell || '').split(/\r?\n/)) {
      if (!line.trim()) continue;
      const it = parseAmount(line);
      if (!it || !it.name) { problems.push(lineNo + '행: 재료를 못 읽음 "' + line + '"'); bad = true; continue; }
      if (ingredients[it.name] !== undefined) {
        problems.push(lineNo + '행: ' + prod.name + ' 에 ' + it.name + ' 이 두 번 나온다');
      }
      ingredients[it.name] = it.count;
    }
    if (bad) continue;
    if (!Object.keys(ingredients).length) {
      problems.push(lineNo + '행: ' + prod.name + ' 에 재료가 없다');
      continue;
    }

    const entry = recipes[prod.name] || (recipes[prod.name] = { via: 'alter', per: prod.count, variants: [] });
    if (entry.per !== prod.count) {
      problems.push(lineNo + '행: ' + prod.name + ' 의 산출량이 갈래마다 다르다 (' + entry.per + ' vs ' + prod.count + ')');
    }

    // 재료가 완전히 같은 줄이 또 오면 갈래를 늘리지 않는다
    const key = JSON.stringify(ingredients);
    const twin = entry.variants.find((v) => JSON.stringify(v.ingredients) === key);
    if (twin) {
      if (twin.facility !== cond.facility || twin.level !== cond.level || twin.sec !== sec) {
        problems.push(lineNo + '행: ' + prod.name + ' 같은 재료인데 조건이 다르다');
      }
      continue;
    }

    entry.variants.push({
      facility: cond.facility,
      level: cond.level,
      sec: sec,
      ingredients: ingredients,
      complete: true,      // 사람이 정리한 표다. 게임이 흘린 것과 달리 빠진 재료가 없다.
    });
  }

  return { recipes, problems, header: head };
}

function main() {
  const csvPath = process.argv[2];
  if (!csvPath) {
    console.error('쓰는 법: node tools/parse-alter-csv.js "<csv 경로>" [출력 경로]');
    process.exit(1);
  }
  const outPath = process.argv[3] || path.join(__dirname, '..', 'alter-recipes.json');
  const { recipes, problems } = build(csvPath);

  const names = Object.keys(recipes).sort((a, b) => a.localeCompare(b, 'ko'));
  const out = {
    _설명: '마비노기 모바일 가공 재료표. 사람이 정리한 것이라 재료가 빠짐없이 들어 있고, 필요한 시설과 레벨도 있다.',
    _필드: {
      per: '한 번 가공에 나오는 개수',
      variants: '같은 이름을 만드는 서로 다른 조합. facility/level 은 그 조합에 필요한 시설과 레벨.',
      sec: '한 번 가공에 걸리는 시간(초). 표에 없으면 null.',
      complete: '재료가 빠짐없이 적혀 있는가. 이 표는 전부 true.',
    },
    _출처: path.basename(csvPath),
    _만든시각: new Date().toISOString(),
    recipes: {},
  };
  for (const n of names) out.recipes[n] = recipes[n];

  fs.writeFileSync(outPath, JSON.stringify(out, null, 1) + '\n', 'utf8');

  /* ── 요약 ── */
  const variants = names.reduce((a, n) => a + recipes[n].variants.length, 0);
  const facilities = new Map();
  const levels = new Map();
  const ingSet = new Map();
  for (const n of names) {
    for (const v of recipes[n].variants) {
      facilities.set(v.facility, (facilities.get(v.facility) || 0) + 1);
      const k = v.facility + ' Lv.' + v.level;
      levels.set(k, (levels.get(k) || 0) + 1);
      for (const [ing, cnt] of Object.entries(v.ingredients)) {
        ingSet.set(ing, (ingSet.get(ing) || 0) + 1);
      }
    }
  }
  const multi = names.filter((n) => recipes[n].variants.length > 1);
  const madeHere = new Set(names);
  const rawOnly = [...ingSet.keys()].filter((i) => !madeHere.has(i));

  // 어떤 이름을 바로잡았는지 — CSV 원문을 그대로 뒤져 센다
  const rawText = fs.readFileSync(csvPath, 'utf8');
  const renamed = Object.keys(RENAME)
    .map((from) => {
      const n = rawText.split(from).length - 1;
      return n ? from + " → " + RENAME[from] + " (" + n + "곳)" : null;
    })
    .filter(Boolean);
  console.log('저장 ' + outPath);
  console.log('가공품 ' + names.length + '가지 · 조합 ' + variants + '개 · 갈래가 둘 이상인 것 ' + multi.length + '가지');
  if (renamed.length) console.log('게임 표기로 바로잡은 재료 이름: ' + [...new Set(renamed)].join(', '));
  console.log('재료 이름 ' + ingSet.size + '가지 (그중 가공으로 만드는 것 ' + (ingSet.size - rawOnly.length) +
    ', 밖에서 구하는 것 ' + rawOnly.length + ')');

  const secs = [];
  let noSec = 0;
  for (const n of names) for (const v of recipes[n].variants) {
    if (v.sec == null) noSec++; else secs.push(v.sec);
  }
  if (secs.length) {
    secs.sort((a, b) => a - b);
    const fmt = (x) => x >= 3600 ? (x / 3600).toFixed(x % 3600 ? 1 : 0) + '시간' : (x >= 60 ? (x / 60) + '분' : x + '초');
    console.log('가공 시간 ' + fmt(secs[0]) + ' ~ ' + fmt(secs[secs.length - 1]) +
      ' · 가운데값 ' + fmt(secs[secs.length >> 1]) +
      (noSec ? ' · 시간 없는 조합 ' + noSec + '개' : ''));
  }
  console.log('');
  console.log('시설별');
  for (const [f, c] of [...facilities].sort((a, b) => b[1] - a[1])) {
    const lv = [...levels].filter(([k]) => k.startsWith(f + ' Lv.'))
      .map(([k, n]) => k.slice(f.length + 4) + '(' + n + ')')
      .sort((a, b) => parseInt(a) - parseInt(b));
    console.log('  ' + f.padEnd(14) + String(c).padStart(4) + '개   레벨 ' + lv.join(' '));
  }
  if (multi.length) {
    console.log('');
    console.log('갈래가 둘 이상인 가공품');
    for (const n of multi) {
      console.log('  ' + n + ' — ' + recipes[n].variants
        .map((v) => 'Lv.' + v.level + ' [' + Object.entries(v.ingredients).map(([k, c]) => k + ' ' + c).join(', ') + ']')
        .join('  /  '));
    }
  }
  if (problems.length) {
    console.log('');
    console.log('살펴볼 것 ' + problems.length + '건');
    for (const p of problems.slice(0, 40)) console.log('  ' + p);
    if (problems.length > 40) console.log('  … 그 밖 ' + (problems.length - 40) + '건');
  }
}

if (require.main === module) main();
module.exports = { parseCsv, parseAmount, parseCondition, build };
