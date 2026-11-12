'use strict';
/* 대시보드 탭 · 주변 카드. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 대시보드 ───────────────────────────────────── */

/**
 * 화면 일부를 필요할 때만 다시 그린다.
 * 자동 갱신은 값이 그대로일 때가 대부분인데, 매번 innerHTML을 갈아끼우면
 * 글자를 드래그하거나 읽는 중에 화면이 튄다.
 */
const dashSig = {};
function paint(id, html) {
  if (dashSig[id] === html) return false;
  dashSig[id] = html;
  $(id).innerHTML = html;
  return true;
}

// 주변 둘도 여기 포함한다. 조회는 로컬 클라이언트 메모리에서 나와 서버 부담이 없고,
// 주변은 계속 변하는 값이라 대시보드 주기에 같이 따라가는 편이 자연스럽다.
const DASH_QUERIES = ['me', 'activity', 'environment', 'currencies', 'nearPcs', 'nearNpcs'];

/**
 * 조회 옵션. 게임이 꺼진 걸 이미 알면 offline을 실어 보낸다.
 * 연결 실패 판정에만 약 5초가 걸리므로, 캐시가 있으면 호출 자체를 건너뛴다.
 */
function dashOpts() {
  const off = !online;
  return {
    me: { refresh: true, offline: off },
    wings: { refresh: true, offline: off },
    activity: { refresh: true, offline: off },
    environment: { refresh: true, offline: off },
    currencies: { nonZero: true, refresh: true, offline: off },
  };
}

/**
 * @param opts.data 이미 받아 둔 응답. 자동 갱신에서 상단바와 조회를 공유해
 *                  같은 명령을 두 번 부르지 않도록 넘겨준다.
 */
async function loadDash(opts) {
  const o = opts || {};
  const r = o.data || (await mm.queryMany(DASH_QUERIES, dashOpts()));

  const m = r.me || {};
  // 주의: CLI는 캐릭터명을 제공하지 않는다 (Title=타이틀, RealmName=서버)
  paint('#dash-char', m.error ? '<dt class="muted">' + (m.error === 'not_in_game' ? '접속 중인 캐릭터 없음' : '조회 실패') +
    '</dt><dd></dd>' : [
    ['이름', topName || '—'], ['타이틀', m.title || '(없음)'], ['레벨', m.level], ['직업', m.job], ['서버(렐름)', m.realm],
    ['전투력', num(m.combat)], ['생활력', num(m.living)],
    ['HP', m.hp], ['포만도', m.satiety], ['무게', m.weight + ' (' + m.weightPct + '%)'],
    ['버프', m.buffs + '개'],
  ].map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join(''));

  const e = r.environment || {};
  paint('#dash-env', e.error ? '<dt class="muted">조회 실패</dt><dd></dd>' : [
    ['위치', e.space], ['채널', e.channel], ['날씨', e.weather], ['에린 시각', e.erinnTime],
    ['좌표', e.pos ? e.pos.x.toFixed(1) + ', ' + e.pos.y.toFixed(1) : '—'],
    ['하우징', e.housing && e.housing.inside ? '내부' : '외부'],
  ].map(([k, v]) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>').join(''));

  const a = r.activity || {};
  const flags = [
    ['자동 진행', a.autoPlaying, 1], ['자동 이동', a.autoTraveling, 1], ['전투 중', a.inCombat, 1],
    ['연주 중', a.performing, 1], ['대화 대기', a.dialogue, 1], ['앉음', a.sitting, 0], ['사망', a.dead, 1],
  ];
  paint('#dash-act',
    flags.map(([k, v, isBusy]) =>
      '<span class="flag ' + (v ? (isBusy ? 'busy' : 'on') : '') + '">' + esc(k) + '</span>').join('') +
    '<span class="flag">던전 ' + esc(a.dungeon || '-') + '</span>' +
    '<span class="flag">버튼 ' + esc(a.mainButton || '-') + '</span>' +
    '<span class="flag ' + (a.busy ? 'busy' : 'on') + '">' + (a.busy ? '바쁨' : '대기') + '</span>');

  const cur = (r.currencies && r.currencies.items) || [];
  paint('#dash-cur', cur.map((x) =>
    '<span class="chip"><em>' + esc(x.name) + '</em><b>' + num(x.amount) + '</b></span>').join('')
    || '<span class="muted">없음</span>');

  paintNear(r);
}

/* ── 주변 ───────────────────────────────────────── */

/** 대시보드의 주변 카드. loadDash가 이미 받아 둔 응답을 넘겨 준다. */
function paintNear(r) {
  const pcs = r.nearPcs || { items: [], total: 0 };
  $('#pc-count').textContent = '플레이어 ' + pcs.total;
  $('#pc-table tbody').innerHTML = pcs.items.length
    ? pcs.items.map((p) =>
        '<tr><td>' + esc(p.name) + (p.title ? ' <span class="sub">' + esc(p.title) + '</span>' : '') + '</td>' +
        '<td class="num">' + p.distance + '</td><td class="num">' + p.level + '</td>' +
        '<td class="sub">' + esc(p.job) + '</td><td class="num">' + num(p.combat) + '</td>' +
        '<td class="sub">' + [p.inCombat ? '전투' : '', p.playing ? '연주' : '', p.friend ? '친구' : '', p.party ? '파티' : '']
            .filter(Boolean).join(', ') + '</td></tr>').join('')
    : '<tr><td colspan="6" class="empty">주변에 플레이어가 없습니다</td></tr>';

  const npcs = r.nearNpcs || { items: [], total: 0 };
  $('#npc-count').textContent = 'NPC ' + npcs.total;
  $('#npc-list').innerHTML = npcs.total
    ? npcs.items.map((n) => '<div class="mission"><span class="t">' + esc(n.DisplayName || n.name || JSON.stringify(n)) + '</span></div>').join('')
    : '<span class="muted">대화 가능한 NPC가 주변에 없습니다</span>';
}
