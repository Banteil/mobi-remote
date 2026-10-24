'use strict';
/* 연주 · 소셜 · 재생목록 · 재생 엔진. app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 연주 · 소셜 ────────────────────────────────── */

let musicCache = null, socialCache = null, instrumentCache = null;

async function loadMusic(refresh) {
  const r = await mm.queryMany(['instruments', 'musicScores'], {
    instruments: { refresh: !!refresh },
    musicScores: { refresh: !!refresh },
  });

  if (!r.instruments.error) { instrumentCache = r.instruments; renderInstruments(); }
  if (!r.musicScores.error) { musicCache = r.musicScores; renderMusic(); }
  await loadPlaylists();
  startPerfWatch();
}

async function loadSocial(refresh) {
  const r = await mm.query('socialActions', { refresh: !!refresh });
  if (!r.error) { socialCache = r; renderSocial(); }
}

/** 검색어 정규화 — 공백 무시, 대소문자 무시 */
function normQ(sel) {
  return $(sel).value.trim().toLowerCase().replace(/\s+/g, '');
}
function hit(text, q) {
  return !q || String(text).toLowerCase().replace(/\s+/g, '').includes(q);
}

/**
 * 악보 제목 앞의 "악보: " 를 뗀다.
 *
 * 게임이 주는 DisplayTitle 은 전부 "악보: 흰 사슴 이야기" 꼴이다. 악보 목록에 있는 것이
 * 악보인 줄은 아니까 화면에서는 뗀다. 다만 play_music_score 는 이 제목을 그대로 받고
 * 재생목록도 이 값으로 저장돼 있으므로, 명령과 저장에는 언제나 원본을 쓴다.
 */
const SCORE_PREFIX = /^악보\s*:\s*/;
function scoreLabel(title) { return String(title).replace(SCORE_PREFIX, ''); }

/**
 * 악기는 버튼 격자로 늘어놓는다.
 *
 * 17개뿐이라 한 줄짜리 목록으로 세로를 길게 먹을 이유가 없고, 장착 중인 것을 색으로
 * 칠해 두면 "지금 뭘 들고 있나"가 한눈에 보인다. 장착 중인 버튼은 누를 것이 없어 꺼 두되,
 * 흐려지면 오히려 눈에 안 띄므로 색은 그대로 둔다.
 */
function renderInstruments() {
  if (!instrumentCache) return;
  const rows = sortRows('instrument', instrumentCache.items);

  $('#instrument-count').textContent = instrumentCache.total + '개';
  $('#instrument-list').innerHTML = rows.length
    ? rows.map((i) => {
        const dur = i.durability === null ? '무한' : num(i.durability);
        return '<button class="btn inst' + (i.equipped ? ' inst-on' : '') + '"' +
          (i.equipped ? ' disabled' : '') +
          ' data-instrument="' + esc(i.name) + '"' +
          ' title="' + esc(i.name + ' — 내구도 ' + dur) + '">' +
          (i.equipped ? '✔ ' : '') + esc(i.name) +
          (i.durability === null ? '' : ' <small>' + dur + '</small>') +
          '</button>';
      }).join('')
    : '<span class="muted">보유 악기 없음</span>';
}

function renderMusic() {
  if (!musicCache) return;
  const q = normQ('#music-search');
  // 제목 전부가 "악보:" 로 시작하므로 검색도 뗀 제목에 건다
  const rows = sortRows('music', musicCache.items.filter((x) => hit(scoreLabel(x.title), q)));

  $('#music-count').textContent = q ? rows.length + ' / ' + musicCache.total : musicCache.total + '개';
  $('#music-list').innerHTML = rows.length
    ? rows.map((x) =>
        '<div class="mission"><span class="t">' + esc(scoreLabel(x.title)) + '</span>' +
        '<button class="btn btn-tiny" data-pl-add="' + esc(x.title) + '" title="재생목록에 담기">+</button> ' +
        '<button class="btn btn-tiny btn-primary" data-play="' + esc(x.title) + '">연주</button>' +
        '<button class="btn btn-tiny" data-play-goal="' + esc(x.title) + '" title="작업 큐 맨 아래에 담기">목표</button></div>').join('')
    : '<span class="muted">결과 없음</span>';
}

function renderSocial() {
  if (!socialCache) return;
  const q = normQ('#social-search');

  // 표정과 행동은 카드가 따로 있으니 정렬도 카드마다 따로 고른다.
  const facials = sortRows('facial', socialCache.facials.filter((x) => hit(x.name, q)));
  const behaviours = sortRows('behaviour', socialCache.behaviours.filter((x) => hit(x.name, q)));

  $('#facial-count').textContent = q
    ? facials.length + ' / ' + socialCache.facials.length
    : facials.length + '개';
  $('#behaviour-count').textContent = q
    ? behaviours.length + ' / ' + socialCache.behaviours.length
    : behaviours.length + '개';

  // 이모지가 없는 표정은 보낼 방법이 없으므로 버튼으로 만들지 않는다
  const facialChip = (x) => x.emoji
    ? '<span class="chip chip-btn" data-social-emoji="' + esc(x.emoji) + '" data-social-name="' + esc(x.name) + '">' +
      starBtn('facial', x) + esc(x.emoji) + ' ' + esc(x.name) + '</span>'
    : '<span class="chip" title="이모지가 없어 실행할 수 없습니다">' +
      starBtn('facial', x) + esc(x.name) + '</span>';

  $('#social-facials').innerHTML = favChips('facial', facials, facialChip);
  const behaviourChip = (x) => {
    // 일어서기만 채팅이 아니라 전용 명령으로 나간다. 목록에서는 같은 줄에 둔다.
    const star = starBtn('behaviour', x);
    if (x.via === 'command') {
      return '<span class="chip chip-btn" data-social-run="' + esc(x.command) + '" ' +
        'data-social-name="' + esc(x.name) + '" title="전용 명령 ' + esc(x.command) + '">' +
        star + esc(x.name) + '</span>';
    }
    const cmd = (x.commands && x.commands[0]) || '';
    return cmd
      ? '<span class="chip chip-btn" data-social-cmd="' + esc(cmd) + '" title="' + esc(x.commands.join(' ')) + '">' + star + esc(x.name) + '</span>'
      : '<span class="chip" title="채팅 명령이 없어 실행할 수 없습니다">' + star + esc(x.name) + '</span>';
  };

  $('#social-list').innerHTML = favChips('behaviour', behaviours, behaviourChip);
}


/* ── 재생목록 ───────────────────────────────────── */

/**
 * 커넥터가 캐릭터를 구분해 주지 않으므로(이름도 ID도 없음) 목록은 사용자가 관리한다.
 * 대신 재생 시점에 현재 보유 악보와 대조해 가진 곡만 튼다 — 캐릭터를 바꿔도 목록이 안 깨진다.
 */
let playlists = [];
let plCurrent = null;

/** 재생 상태. setInterval 대신 루프 안에서 플래그를 보고 멈춘다. */
const player = { active: false, stopping: false, index: 0, title: null };

const PL_KEY = 'mobi-remote.playlist';

function ownedTitles() {
  return new Set((musicCache && musicCache.items ? musicCache.items : []).map((x) => x.title));
}

function plStatus(text) {
  $('#pl-status').textContent = text || '';
}

function renderPlaylists() {
  const sel = $('#pl-select');
  sel.innerHTML = playlists.length
    ? playlists.map((p) => '<option value="' + esc(p.id) + '">' + esc(p.name) + ' (' + p.tracks.length + '곡)</option>').join('')
    : '<option value="">(목록 없음 — 새로 만들기)</option>';
  if (plCurrent) sel.value = plCurrent.id;

  $('#pl-count').textContent = playlists.length ? playlists.length + '개' : '';
  $('#pl-loop').checked = !!(plCurrent && plCurrent.loop);
  $('#pl-shuffle').checked = !!(plCurrent && plCurrent.shuffle);

  const owned = ownedTitles();
  const box = $('#pl-tracks');
  if (!plCurrent) {
    box.innerHTML = '<span class="muted">재생목록을 만들고 악보 목록에서 <b>+</b>를 눌러 담으세요.</span>';
    return;
  }
  if (!plCurrent.tracks.length) {
    box.innerHTML = '<span class="muted">비어 있습니다. 위 악보 목록에서 <b>+</b>를 눌러 담으세요.</span>';
    return;
  }
  const missing = plCurrent.tracks.filter((t) => !owned.has(t)).length;
  box.innerHTML = plCurrent.tracks.map((t, i) => {
    const has = owned.has(t);
    const playing = player.active && player.title === t;
    return '<div class="mission' + (playing ? ' pl-playing' : '') + '">' +
      '<span class="' + (has ? 'mark-ok' : 'mark-bad') + '">' + (has ? (playing ? '▶' : '✔') : '✘') + '</span>' +
      '<span class="t">' + esc(scoreLabel(t)) + (has ? '' : ' <span class="sub">이 캐릭터에 없음 — 건너뜁니다</span>') + '</span>' +
      '<button class="btn btn-tiny" data-pl-move="' + i + '" data-pl-delta="-1" title="위로">↑</button>' +
      '<button class="btn btn-tiny" data-pl-move="' + i + '" data-pl-delta="1" title="아래로">↓</button>' +
      '<button class="btn btn-tiny" data-pl-del="' + i + '" title="목록에서 제거">×</button>' +
      '</div>';
  }).join('') +
  (missing ? '<p class="hint">' + missing + '곡은 이 캐릭터가 갖고 있지 않아 재생에서 제외됩니다.</p>' : '');
}

async function loadPlaylists() {
  playlists = await mm.pl.list();
  let savedId = null;
  try { savedId = localStorage.getItem(PL_KEY); } catch (_) {}
  plCurrent = playlists.find((p) => p.id === savedId) || playlists[0] || null;
  renderPlaylists();
}

function selectPlaylist(id) {
  plCurrent = playlists.find((p) => p.id === id) || null;
  try { if (plCurrent) localStorage.setItem(PL_KEY, plCurrent.id); } catch (_) {}
  renderPlaylists();
}

async function refreshPlaylists(keepId) {
  playlists = await mm.pl.list();
  plCurrent = playlists.find((p) => p.id === (keepId || (plCurrent && plCurrent.id))) || playlists[0] || null;
  renderPlaylists();
}

/* ── 재생 엔진 ──────────────────────────────────── */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 지금 무엇을 연주 중인지. 곡이 끝났는지 판단하는 유일한 근거다. */
/**
 * 지금 연주 중인가, 그리고 어디까지 왔나.
 *
 * 시간은 게임이 재서 준다 (TotalDuration / Elapsed / Remaining). 앱이 시작 시각을 재는
 * 방식이었다면 게임에서 직접 연주를 시작한 경우를 놓쳤겠지만, 이 값은 누가 시작했든 맞다.
 * 부르는 쪽이 여럿이라 (재생 루프, 진행바 타이머) 본 것을 nowPlaying 에 남겨 같이 쓴다.
 */
async function performance() {
  const a = await mm.query('activity', {});
  const p = (a && a.perf) || {};
  const out = {
    playing: !!(a && a.performing),
    busy: !!(a && a.busy),
    dead: !!(a && a.dead),
    title: p.title || '',
    instrument: p.instrument || '',
    loop: !!p.loop,
    total: p.total || 0,
    elapsed: p.elapsed || 0,
    remaining: p.remaining || 0,
    channels: p.channels || 0,
  };
  nowPlaying.last = out;
  nowPlaying.at = Date.now();
  paintNowPlaying();
  return out;
}

/** 초를 m:ss 로. 한 시간 넘는 악보는 없으니 분까지면 충분하다. */
function mmss(sec) {
  const n = Math.max(0, Math.round(Number(sec) || 0));
  return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0');
}

/* ── 연주 진행 상황 ────────────────────────────── */

/**
 * 연주 탭에 머무는 동안만 돈다.
 *
 * 게임에 물어보는 것은 2.5초에 한 번이고 (연주 중이 아니면 6초로 늦춘다), 그 사이는
 * 마지막으로 받은 값에 흐른 시간을 더해 메운다. 진행바를 매끄럽게 하려고 초당 몇 번씩
 * CLI를 부르는 것은 낭비다.
 */
const nowPlaying = { on: false, timer: null, tick: null, last: null, at: 0 };

function startPerfWatch() {
  if (nowPlaying.on) return;
  nowPlaying.on = true;
  nowPlaying.tick = setInterval(paintNowPlaying, 500);
  pollPerf();
}

function stopPerfWatch() {
  nowPlaying.on = false;
  clearTimeout(nowPlaying.timer);
  clearInterval(nowPlaying.tick);
  nowPlaying.timer = nowPlaying.tick = null;
}

async function pollPerf() {
  if (!nowPlaying.on) return;
  try { await performance(); } catch (_) { /* 잠깐 못 읽어도 다음 차례에 다시 본다 */ }
  if (!nowPlaying.on) return;
  const playing = !!(nowPlaying.last && nowPlaying.last.playing);
  nowPlaying.timer = setTimeout(pollPerf, playing ? 2500 : 6000);
}

/** 마지막으로 받은 값 + 그 뒤로 흐른 시간. 폴링 사이를 메운다. */
function paintNowPlaying() {
  const box = $('#pl-now');
  if (!box) return;
  const p = nowPlaying.last;
  if (!p || !p.playing) { box.classList.add('hidden'); box.innerHTML = ''; return; }

  const drift = (Date.now() - nowPlaying.at) / 1000;
  const total = p.total || 0;
  // ElapsedSeconds 는 곡이 끝나도 멈추지 않고 계속 올라간다. 게임 쪽 반복이 켜져 있으면
  // 62.4초짜리가 70초, 80초까지 간다. 그래서 총 길이로 나눠 이번 바퀴의 위치를 쓴다.
  const raw = (p.elapsed || 0) + drift;
  const pass = total ? Math.floor(raw / total) : 0;
  const elapsed = total ? raw - pass * total : raw;
  const left = total ? Math.max(0, total - elapsed) : 0;
  const pct = total ? (elapsed / total) * 100 : 0;

  box.classList.remove('hidden');
  box.innerHTML =
    '<div class="now-head"><span class="mark-ok">▶</span> ' +
    '<b>' + esc(scoreLabel(p.title) || '연주 중') + '</b>' +
    (p.instrument ? ' <span class="muted">' + esc(p.instrument) + '</span>' : '') +
    (p.loop ? ' <span class="muted">게임 반복 켜짐</span>' : '') +
    '<span class="spacer"></span>' +
    '<span class="now-time">' + mmss(elapsed) +
    (total ? ' / ' + mmss(total) : '') + '</span></div>' +
    (total
      ? '<div class="bar bar-wide"><i class="' + widthClass(pct) + '"></i></div>' +
        '<div class="now-foot muted">남은 시간 ' + mmss(left) +
        (pass ? ' · ' + (pass + 1) + '바퀴째' : '') +
        (p.channels ? ' · ' + p.channels + '화음' : '') + '</div>'
      : '');
}

function nextIndex(list, from) {
  return from + 1 < list.length ? from + 1 : (plCurrent && plCurrent.loop ? 0 : -1);
}

async function playPlaylist() {
  if (player.active) { toast('이미 재생 중입니다', '', 'bad'); return; }
  if (!plCurrent || !plCurrent.tracks.length) { toast('재생목록이 비어 있습니다', '', 'bad'); return; }

  // 보유한 곡만 추린다. 캐릭터가 바뀌어도 목록을 고칠 필요가 없게 하는 핵심.
  await loadMusic(true);
  const owned = ownedTitles();
  let queue = plCurrent.tracks.filter((t) => owned.has(t));
  if (!queue.length) {
    toast('재생할 곡이 없습니다', '이 캐릭터가 목록의 악보를 하나도 갖고 있지 않습니다.', 'bad');
    return;
  }
  if (plCurrent.shuffle) {
    for (let i = queue.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [queue[i], queue[j]] = [queue[j], queue[i]];
    }
  }

  player.active = true;
  player.stopping = false;
  player.index = 0;
  $('#pl-play').disabled = true;

  let played = 0, skipped = 0;
  try {
    while (player.active && !player.stopping && player.index >= 0) {
      const title = queue[player.index];
      player.title = title;
      renderPlaylists();
      plStatus('(' + (player.index + 1) + '/' + queue.length + ') ' + scoreLabel(title));

      const r = await mm.exec('play_music_score', { title: title });
      if (!r.ok) {
        skipped++;
        const why = r.ko ? r.ko.text : r.error;
        noteLine('연주 실패 — ' + scoreLabel(title) + ' (' + why + ')');
        // 전투·사망·탑승 중이면 뒤 곡도 마찬가지이므로 멈춘다
        if (['not_available_on_combat', 'not_available_on_dead', 'not_available_on_riding'].indexOf(r.error) >= 0) {
          toast('연주를 계속할 수 없습니다', why, 'bad');
          break;
        }
        player.index = nextIndex(queue, player.index);
        continue;
      }

      played++;
      // 연주가 실제로 시작될 때까지 잠깐 기다린 뒤, 끝날 때까지 지켜본다
      await sleep(2000);
      while (player.active && !player.stopping) {
        const p = await performance();
        if (!p.playing) break;

        // 게임 안에서 "반복"을 켜 두면 곡이 끝나도 IsPlaying 이 내려오지 않고 처음부터 다시
        // 돈다. 그것만 기다리면 재생목록이 첫 곡에서 영영 멈춘다. 총 길이를 넘어선 것을
        // 한 곡이 끝난 것으로 보고, 직접 멈춘 뒤 다음 곡으로 넘어간다.
        if (p.total && p.elapsed >= p.total - 0.5) {
          await mm.exec('stop_action');
          break;
        }

        plStatus('(' + (player.index + 1) + '/' + queue.length + ') ' + scoreLabel(title) +
          (p.total ? ' — ' + mmss(p.elapsed) + ' / ' + mmss(p.total) : ''));
        await sleep(3000);
      }
      if (player.stopping) break;
      player.index = nextIndex(queue, player.index);
    }
  } finally {
    player.active = false;
    player.title = null;
    $('#pl-play').disabled = false;
    plStatus('');
    renderPlaylists();
  }

  toast('재생목록 종료', '연주 ' + played + '곡' + (skipped ? ' · 실패 ' + skipped + '곡' : ''), skipped ? 'bad' : 'ok');
}

async function stopPlaylist() {
  if (!player.active) {
    // 재생 중이 아니어도 수동 정지는 허용한다
    await runAction('stop_action', undefined, { label: '연주 정지', skipConfirm: true });
    return;
  }
  player.stopping = true;
  plStatus('정지하는 중…');
  await runAction('stop_action', undefined, { label: '연주 정지', skipConfirm: true });
}

/**
 * 자동 진행 중에 남기는 한 줄.
 *
 * 전에는 루틴 탭의 로그 상자로 갔다. 그 탭을 없앤 뒤로는 상태바가 유일한 자리다.
 */
function noteLine(text) {
  say(text);
}
