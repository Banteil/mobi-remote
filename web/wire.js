'use strict';
/* 탭 전환 (LOADERS — 다른 파일이 자기 탭을 더한다) · 이벤트 배선 wire() (main.js 가 시작할 때 부른다).
 * app.js 에서 나눔 — 같은 전역을 쓴다 (index.html 의 script 순서 참고). */

/* ── 탭 ─────────────────────────────────────────── */

/* 탭 이름 → 불러오기(refresh). 탭을 열 때는 refresh 없이 (받아 둔 게 있으면 그대로 그림), 새로 고침(refreshActive)은
 * refresh = true 로 부른다. 칸마다 화살표로 감싸 두어 이 파일보다 뒤에 읽히는 함수도 쓸 수 있다. */
const LOADERS = {
  dash: () => loadDash(),
  craft: (refresh) => (!refresh && craftCache ? renderCraft() : loadCraft(refresh)),
  alter: (refresh) => loadAlter(refresh),
  gather: (refresh) => (!refresh && gatherCache ? renderGather() : loadGather(refresh)),
  items: (refresh) => (!refresh && itemsCache ? renderItems() : loadItems(refresh)),
  mission: (refresh) => loadMission(refresh),
  music: (refresh) => loadMusic(refresh),
  social: (refresh) => loadSocial(refresh),
  dye: () => loadDye(),
};

let activeTab = 'chars';

async function showTab(name) {
  activeTab = name;
  // 연주 진행바는 그 탭을 보고 있을 때만 돈다
  stopPerfWatch();
  // 염색도 마찬가지다. 다만 표시가 켜져 있으면 그대로 둔다 —
  // 게임을 보면서 쓰는 기능이라 탭을 옮겼다고 꺼지면 곤란하다.
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.panel').forEach((p) => p.classList.toggle('active', p.id === 'panel-' + name));
  say(name + ' 불러오는 중…');
  try { await LOADERS[name](); say('준비됨'); }
  catch (err) { say('오류: ' + err.message); }
}

function refreshActive() {
  refreshTopbar();
  return LOADERS[activeTab](true);
}

/* 상태바 '취소' 때 할 일 — 여러 단계짜리 작업(가공 채우기·연주·큐)이 자기 멈춤을 등록한다 (onCancel) */
const CANCELERS = [];
function onCancel(fn) { CANCELERS.push(fn); }

/* ── 이벤트 배선 ────────────────────────────────── */

/** 지금 테마와, 누르면 어떻게 되는지를 버튼에 적는다. */
function paintThemeBtn() {
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  const btn = $('#btn-theme');
  if (!btn) return;
  btn.textContent = light ? '☀' : '☾';
  btn.title = light ? '밝은 테마 — 누르면 어둡게' : '어두운 테마 — 누르면 밝게';
}

function wire() {
  $$('.tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));
  $$('.hw-tab').forEach((t) => t.addEventListener('click', () => showHomeworkPane(t.dataset.hw)));
  showHomeworkPane(pref('hwPane', 'daily'), false);

  // 테마 — 지금 값은 <html data-theme>에 이미 붙어 있다(theme.js). 여기서는 뒤집기만 한다.
  paintThemeBtn();
  $('#btn-theme').addEventListener('click', async () => {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    paintThemeBtn();
    try { await mm.cfg.theme(next); } catch (_) { /* 저장 실패가 화면을 막지 않는다 */ }
  });

  $('#alter-works-fold').addEventListener('click', async () => {
    worksFolded = !worksFolded;
    applyWorksFold();
    setPref('alterWorksFolded', worksFolded);
  });

  const toggleQueue = async () => {
    const content = $('#content');
    pinContent(content.getBoundingClientRect().width);
    try {
      const before = $('#queue').getBoundingClientRect().width;
      queueFolded = !queueFolded;
      applyQueueFold();
      const after = $('#queue').getBoundingClientRect().width;
      // 큐가 줄어든 만큼 창도 좁힌다. 본문 폭은 붙들어 두었으므로 그대로다.
      try { await mm.win.narrow(before - after); } catch (_) {}
      // 창이 실제로 다 그려진 다음에 놓아준다
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    } finally {
      unpinContent();
    }
    setPref('queueFolded', queueFolded);
  };
  $('#q-fold').addEventListener('click', toggleQueue);
  $('#q-tag').addEventListener('click', toggleQueue);

  /**
   * 게임 화면과 우리 표시를 **함께** 한 장 찍는다.
   *
   * 평소 오버레이는 화면 캡처에서 빠지도록 해 두었다. 우리가 그린 것이 다음 캡처에 섞여
   * 팔레트로 오인되는 것을 막으려고 그런 것인데, 그 바람에 **사용자의 스크린샷에도 안
   * 찍힌다.** 무엇이 그려지고 있는지 남에게 보여 주려면 모니터를 카메라로 찍어야 했다.
   *
   * 이 버튼은 그 한 장을 위해서만 잠깐 보호를 풀고 찍는다.
   */
  $('#dye-shot').addEventListener('click', async (e) => {
    const done = btnBusy(e.target, '찍는 중…');
    let r = null;
    try { r = await mm.dye.shot(); } catch (err) { r = { error: err.message }; }
    done();
    if (!r || r.error) {
      toast('찍지 못했습니다', (r && (r.message || r.error)) || '', 'bad');
      return;
    }

    // 클립보드는 여기서 넣는다. 메인 쪽 clipboard 는 이 빌드에서 비동기 웹 API 라
    // writeImage 가 없다. 렌더러는 평범한 웹 문맥이라 그냥 된다.
    // 파이썬판은 파이썬이 이미 클립보드에 넣고 copied 로 알려 준다
    let copied = r.copied === true;
    if (r.png) {
      try {
        const blob = new Blob([r.png], { type: 'image/png' });
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        copied = true;
      } catch (_) { /* 창에 초점이 없거나 막혀 있으면 파일만 남는다 */ }
    }

    toast(
      copied ? '클립보드에 복사했습니다' : '파일로 저장했습니다',
      (copied ? '붙여넣기로 바로 쓸 수 있습니다 · ' : '클립보드 복사는 실패했습니다 · ') + r.path,
      'ok');
  });

  wireColorPicker();

  /*
   * 화살표 키로 커서 1px.
   *
   * 켜 두는 동안 화살표를 **전역으로** 가로채므로, 켜고 끄는 것은 사람이 쥔다.
   * 설정에는 남기지 않는다 — 다음에 켰을 때 저도 모르게 화살표가 안 듣는 상태로
   * 시작하면 무엇이 문제인지 알아내기 어렵다.
   */
  /*
   * Ctrl+WASD 로 커서 1px.
   *
   * 전역 단축키라 걸어 둔 동안 다른 프로그램에서 이 조합을 못 쓴다. 그래서 켜 둬도 실제로는
   * 염색 팔레트가 떠 있는 동안만 건다 (파이썬 _dye_active). 설정에 남아 다음에도 그대로.
   */
  $('#dye-nudge').addEventListener('change', async (e) => {
    const on = e.target.checked;
    await setPref('dyeNudge', on);
    const r = await mm.cursorNudge(on).catch(() => null);
    if (on && (!r || !r.ok)) {
      e.target.checked = false;
      await setPref('dyeNudge', false);
      $('#dye-nudge-msg').textContent = (r && r.error) || '켜지 못했습니다';
      return;
    }
    $('#dye-nudge-msg').textContent = '';
  });

  // 켜 둔 채로 떴으면 바로 걸어 둔다.
  (async () => {
    if (pref('dyeNudge') !== true) return;
    $('#dye-nudge').checked = true;
    const r = await mm.cursorNudge(true).catch(() => null);
    if (!r || !r.ok) $('#dye-nudge-msg').textContent = (r && r.error) || '켜지 못했습니다';
  })();

  /*
   * 보기 설정 — 흑백 강조·밝기·팔레트 자리. 파이썬이 저장하고 돌던 도우미에 바로 건다.
   */
  function paintDyeView(v) {
    if (!v) return;
    $('#dye-gray').checked = !!v.gray;
    $('#dye-still').checked = !!v.still;
    $('#dye-light').value = v.light;
    $('#dye-light').disabled = !v.gray;
    $('#dye-light-v').textContent = v.light + '%';
    $('#dye-area').textContent = v.area ? '직접 정한 자리' : '기본 자리';
    $('#dye-area-reset').disabled = !v.area;
    if (v.marks && v.marks.join() !== dyeUI.marks.join()) { dyeUI.marks = v.marks.slice(); paintDyeSlots(); }
  }
  mm.dye.view().then(paintDyeView).catch(() => {});
  mm.dye.onView(paintDyeView);
  $('#dye-gray').addEventListener('change', (e) => mm.dye.view({ gray: e.target.checked }));
  $('#dye-still').addEventListener('change', (e) => mm.dye.view({ still: e.target.checked }));
  $('#dye-light').addEventListener('input', (e) => { $('#dye-light-v').textContent = e.target.value + '%'; });
  $('#dye-light').addEventListener('change', (e) => mm.dye.view({ light: Number(e.target.value) }));
  $('#dye-area-edit').addEventListener('click', async () => {
    const r = await mm.dye.editArea().catch((err) => ({ error: err.message }));
    if (r && r.error) toast('자리를 고칠 수 없습니다', r.error, 'bad');
  });
  $('#dye-area-reset').addEventListener('click', () => mm.dye.view({ area: null }));

  $('#dye-start').addEventListener('click', startDye);
  $('#dye-stop').addEventListener('click', stopDye);
  $('#dye-preset').addEventListener('change', async (e) => {
    dyeUI.prefs = await mm.dye.select(e.target.value);
    paintDyeSlots();
  });
  $('#dye-new').addEventListener('click', async () => {
    const name = await promptText('새 색 조합', '이름을 정하세요', '내 색');
    if (!name) return;
    dyeUI.prefs = await mm.dye.add(name, ['', '', '']);
    paintDyePresets(); paintDyeSlots();
  });
  $('#dye-rename').addEventListener('click', async () => {
    const cur = dyeCurrent();
    if (!cur) return;
    const name = await promptText('이름 변경', '새 이름', cur.name);
    if (!name) return;
    dyeUI.prefs = await mm.dye.update(cur.id, { name: name });
    paintDyePresets();
  });
  $('#dye-del').addEventListener('click', async () => {
    const cur = dyeCurrent();
    if (!cur) return;
    if (!(await confirmModal('색 조합 삭제', '<p>"' + esc(cur.name) + '" 을(를) 지울까요?</p>', '삭제'))) return;
    dyeUI.prefs = await mm.dye.remove(cur.id);
    paintDyePresets(); paintDyeSlots();
  });
  // 오차 슬라이더·숫자 칸은 칸마다 새로 그려지므로 위임으로 받는다. 끄는 동안은 숫자만 따라가고 놓으면 저장.
  document.addEventListener('input', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement) || t.dataset.dyeTol === undefined) return;
    const v = $('[data-dye-toln="' + t.dataset.dyeTol + '"]');
    if (v) v.value = t.value;
  });
  document.addEventListener('change', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;
    if (t.dataset.dyeTol !== undefined) setDyeTol(+t.dataset.dyeTol, t.value);
    else if (t.dataset.dyeToln !== undefined) setDyeTol(+t.dataset.dyeToln, t.value);
  });

  $('#q-play').addEventListener('click', qPlayAll);
  $('#q-pause').addEventListener('click', qPause);
  $('#q-halt').addEventListener('click', qHalt);
  $('#q-tidy').addEventListener('click', qTidy);
  $('#q-history').addEventListener('click', showQueueHistory);
  $('#q-report-btn').addEventListener('click', showLastQueueReport);
  $('#q-hist-close').addEventListener('click', () => $('#q-hist').classList.add('hidden'));
  $('#q-clear').addEventListener('click', qClear);

  $('#btn-options').addEventListener('click', openOptions);
  $('#options-close').addEventListener('click', closeOptions);
  $$('.opt-tab').forEach((t) => t.addEventListener('click', () => showOptionPane(t.dataset.pane)));
  showOptionPane(pref('optPane', 'general'), false);
  // 바깥을 눌러도 닫는다. 창이 커서 닫기 버튼까지 가기 번거롭다.
  $('#options').addEventListener('click', (e) => { if (e.target.id === 'options') closeOptions(); });
  // Esc 로도 닫는다. 확인 모달이 떠 있을 때는 그쪽이 먼저 받아야 하므로 건너뛴다.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!$('#modal').classList.contains('hidden')) return;
    // 색 편집이 떠 있으면 그쪽이 먼저다. 스포이드 화면이면 고르기로만 돌아간다.
    if (!$('#cpick').classList.contains('hidden')) {
      if (!$('#cpick-shot').classList.contains('hidden')) closeCpickShot();
      else closeColorPicker(null);
      return;
    }
    if (!$('#options').classList.contains('hidden')) closeOptions();
  });
  $('#opt-ask-mismatch').addEventListener('change', async (e) => {
    setPref('askFacilityLevelMismatch', e.target.checked);
    toast('저장했습니다', e.target.checked ? '어긋나면 물어봅니다.' : '묻지 않습니다.', 'ok');
  });

  $('#opt-close-to-tray').addEventListener('change', async (e) => {
    setPref('closeToTray', e.target.checked);
    toast('저장했습니다', e.target.checked
      ? '창을 닫으면 트레이에 남습니다.'
      : '창을 닫으면 프로그램도 함께 끝납니다.', 'ok');
  });

  ['on', ...OV_KEYS].forEach((k) => $('#ov-' + k).addEventListener('change', saveOverlayOptions));
  $('#ov-alpha').addEventListener('input', (e) => { $('#ov-alpha-n').textContent = e.target.value + '%'; });

  $('#btn-refresh').addEventListener('click', refreshActive);
  $('#btn-stop').addEventListener('click', () =>
    runAction('stop_action', undefined, { label: '행동 정지', skipConfirm: true }));

  $('#sb-cancel').addEventListener('click', async () => {
    // 실행 중인 명령 하나만 죽이면 여러 단계짜리 작업은 다음 단계로 넘어가 버린다.
    // 반복 루프에도 중단 신호를 같이 보낸다 (각 파일이 onCancel 로 등록).
    CANCELERS.forEach((fn) => fn());
    await mm.cancel();
    say('취소 요청을 보냈습니다.');
  });

  // 게임을 켠 뒤 기다리지 않고 바로 다시 붙을 수 있게 한다
  $('#pl-select').addEventListener('change', (e) => selectPlaylist(e.target.value));
  $('#pl-new').addEventListener('click', async () => {
    const name = await promptText('새 재생목록', '이름을 정하세요', '내 재생목록',
      '캐릭터별로 쓰려면 이름으로 구분 (예: 궁수용)');
    if (!name) return;
    const made = await mm.pl.create(name);
    await refreshPlaylists(made.id);
    setPref('playlist', made.id);
  });
  $('#pl-rename').addEventListener('click', async () => {
    if (!plCurrent) return;
    const name = await promptText('이름 변경', '새 이름', plCurrent.name);
    if (!name) return;
    await mm.pl.update(plCurrent.id, { name });
    await refreshPlaylists(plCurrent.id);
  });
  $('#pl-delete').addEventListener('click', async () => {
    if (!plCurrent) return;
    if (!(await confirmModal('재생목록 삭제', '<p>"' + esc(plCurrent.name) + '" 을(를) 지울까요?</p>', '삭제'))) return;
    await mm.pl.remove(plCurrent.id);
    plCurrent = null;
    await refreshPlaylists();
  });
  $('#pl-loop').addEventListener('change', async (e) => {
    if (!plCurrent) return;
    await mm.pl.update(plCurrent.id, { loop: e.target.checked });
    await refreshPlaylists(plCurrent.id);
  });
  $('#pl-shuffle').addEventListener('change', async (e) => {
    if (!plCurrent) return;
    await mm.pl.update(plCurrent.id, { shuffle: e.target.checked });
    await refreshPlaylists(plCurrent.id);
  });
  $('#pl-play').addEventListener('click', playPlaylist);
  $('#pl-stop').addEventListener('click', stopPlaylist);


  wireUpdate();
  wireNpcap();

  $('#offline-launch').addEventListener('click', launchGame);

  $('#offline-retry').addEventListener('click', async () => {
    // 커넥터를 못 찾은 상태에서는 '다시 확인'이 아무 소용이 없다. 찾기부터 시킨다.
    if ($('#offline-retry').textContent === '커넥터 찾기') {
      say('커넥터를 찾는 중…');
      const loc = await mm.cli.locate(true);
      if (!loc || !loc.found) {
        toast('커넥터를 찾지 못했습니다',
          '게임이 설치되어 있는지 확인하세요. 옵션에서 위치를 직접 지정할 수도 있습니다.', 'bad');
        say('준비됨');
        return;
      }
      toast('커넥터를 찾았습니다', loc.path, 'ok');
    }

    say('연결 확인 중…');
    const ok = await refreshTopbar();
    if (ok) {
      toast('연결됨', '게임에 다시 연결되었습니다.', 'ok');
      await refreshActive();
    } else {
      toast('아직 연결되지 않았습니다', '게임 실행과 "MM AI 에이전트 활성화"를 확인하세요.', 'bad');
    }
    say('준비됨');
  });

  // 채팅
  const sendChat = async () => {
    const msg = $('#chat-input').value.trim();
    if (!msg) return;
    const r = await runAction('write_chat', msg, { label: '채팅 전송', skipConfirm: true });
    if (r && r.ok) $('#chat-input').value = '';
  };
  $('#chat-send').addEventListener('click', sendChat);
  $('#chat-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendChat(); });

  // 검색/필터 — 조건이 바뀌면 1쪽으로 되돌린다.
  // 3쪽을 보다 검색하면 결과가 3쪽까지 없어서 "없음"처럼 보인다.
  const refilter = (key, render) => () => { resetPage(key); render(); };

  $('#craft-search').addEventListener('input', debounce(refilter('craft', renderCraft)));
  $('#craft-only-ok').addEventListener('change', refilter('craft', renderCraft));
  $('#alter-search').addEventListener('input', debounce(refilter('alter', renderAlter)));
  $('#alter-only-ok').addEventListener('change', refilter('alter', renderAlter));
  $('#alter-facility').addEventListener('change', refilter('alter', renderAlter));
  $('#alter-level').addEventListener('change', refilter('alter', renderAlter));
  $('#gather-search').addEventListener('input', debounce(renderGather));
  $('#gather-only-ok').addEventListener('change', renderGather);
  $('#items-search').addEventListener('input', debounce(refilter('items', renderItems)));
  $('#items-cat').addEventListener('change', refilter('items', renderItems));
  $('#items-loc').addEventListener('change', refilter('items', renderItems));

  // 페이저는 표마다 붙이지 않고 한곳에서 위임받는다 — 다시 그릴 때마다 사라지는 요소다
  wirePager((key) => { const fn = PAGE_RENDER[key]; if (fn) fn(); });
  wireSort();
  $('#mission-only-open').addEventListener('change', () => loadMission());
  $('#music-search').addEventListener('input', debounce(renderMusic));
  $('#social-search').addEventListener('input', debounce(renderSocial));

  // hex 를 직접 쳐 넣는 경우. 여섯 자리가 다 찼을 때만 저장한다 —
  // 한 글자 칠 때마다 저장하면 파일이 매번 쓰인다.
  document.addEventListener('change', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement) || t.dataset.dyeHex === undefined) return;
    const v = String(t.value || '').trim();
    const hex = /^#?[0-9a-f]{6}$/i.test(v) ? (v[0] === '#' ? v : '#' + v).toUpperCase() : '';
    setDyeColor(+t.dataset.dyeHex, hex);
  });

  $$('[data-refresh]').forEach((b) => b.addEventListener('click', refreshActive));

  // 콘솔
  $('#cmd-select').addEventListener('change', onCmdChange);
  $('#cmd-run').addEventListener('click', runRawCommand);
  $('#caps-refresh').addEventListener('click', () => loadCaps(true));
  $('#log-refresh').addEventListener('click', loadFileLog);
  $('#log-open').addEventListener('click', () => mm.log.open());

  // 호환성
  $('#compat-recheck').addEventListener('click', async () => {
    say('호환성 검사 중…');
    const r = await loadCompat(true);
    toast('호환성 검사', (LEVEL_STYLE[r.levelName] || {}).text || r.levelName, r.ok ? 'ok' : 'bad');
    say('준비됨');
  });
  $('#compat-accept').addEventListener('click', async () => {
    const res = await mm.version.check(false);
    const body = res.changes && res.changes.length
      ? '<p>아래 변경을 정상으로 인정하고 기준선을 갱신합니다.</p><div class="compat-scroll">' + changesHtml(res.changes) + '</div>'
      : '<p>현재 상태를 기준선으로 저장합니다.</p>';
    if (!(await confirmModal('기준선 갱신', body, '저장'))) return;
    await mm.version.accept('사용자가 앱에서 승인');
    await loadCompat(true);
    toast('기준선 갱신됨', '이제부터 이 상태를 기준으로 비교합니다.', 'ok');
  });

  // 표/카드 안의 동작 버튼은 위임으로 처리한다
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (!(t instanceof HTMLElement)) return;

    // 별표가 먼저다. 칩 안에 들어 있어서, 뒤로 밀리면 표정을 실행해 버린다.
    if (t.dataset.dyePick !== undefined) return void pickDyeColor(+t.dataset.dyePick);
    if (t.dataset.dyeMark !== undefined) return void pickDyeMark(+t.dataset.dyeMark);
    if (t.dataset.dyeClear !== undefined) return void setDyeColor(+t.dataset.dyeClear, '');

    if (t.dataset.qDel !== undefined) return void qRemove(t.dataset.qDel);
    if (t.dataset.qPlay !== undefined) return void qPlayOne(t.dataset.qPlay);
    if (t.dataset.qPause !== undefined) return void qPauseOne(t.dataset.qPause);
    if (t.dataset.qEdit !== undefined) return void qEdit(t.dataset.qEdit);
    if (t.dataset.qWho !== undefined) return void qWho(t.dataset.qWho);
    if (t.dataset.qUp !== undefined) return void qMove(t.dataset.qUp, -1);
    if (t.dataset.qDn !== undefined) return void qMove(t.dataset.qDn, 1);

    if (t.dataset.fav) {
      return void (async () => {
        const r = await mm.fav.toggle(t.dataset.fav, t.dataset.favName);
        if (!r || !r.ok) return;
        favCache[r.list] = new Set(r.favorites[r.list]);
        const fn = PAGE_RENDER[r.list];
        if (fn) fn();
      })();
    }

    if (t.dataset.craft) return void doCraft(t.dataset.craft, t.dataset.per);
    if (t.dataset.plan) return void makePlan(t.dataset.plan, t.dataset.planLabel);

    if (t.dataset.gather) return void doGather(t.dataset.gather);
    if (t.dataset.fill) return void fillAltering(t.dataset.fill, t.dataset.fillLabel);
    if (t.dataset.alter) {
      return void actNow({ act: 'alter', command: 'execute_altering', body: { displayName: t.dataset.alter },
        label: t.dataset.alter + ' 가공', detail: '가공 1회 등록', note: '칸이 꽉 차면 날개만 나갑니다 — 여유 칸 확인' });
    }
    if (t.dataset.collect || t.dataset.collectGoal) {
      const name = t.dataset.collect || t.dataset.collectGoal;
      return void (t.dataset.collect ? actNow : actGoal)({ act: 'collect', command: 'complete_altering_work',
        body: { displayName: name }, label: name + ' 수령', detail: '가공 완료분 수령', skipConfirm: true });
    }
    if (t.dataset.roomLevel) {
      return void (async () => {
        if (await askFacilityLevel(t.dataset.roomLevel, parseInt(t.dataset.roomLv, 10))) loadAlter(true);
      })();
    }
    if (t.id === 'collect-all' || t.id === 'collect-all-goal') {
      return void (t.id === 'collect-all' ? actNow : actGoal)({ act: 'collectAll', label: '가공 완료분 전체 수령',
        detail: '완료된 시설 모두', skipConfirm: true });
    }
    if (t.id === 'cli-detect') {
      return void (async () => {
        const done = btnBusy(t, '찾는 중…');
        let loc = null;
        try { loc = await mm.cli.locate(true); }
        catch (err) { done(); toast('찾지 못했습니다', err.message, 'bad'); return; }
        done();
        await loadCompat(true);
        await refreshTopbar();
        if (loc.found) {
          toast('커넥터를 찾았습니다', loc.path, 'ok');
        } else {
          // 여기까지 왔으면 경로보다 설치 여부부터 의심하는 것이 맞다
          toast('커넥터를 찾지 못했습니다',
            '마비노기 모바일이 설치되어 있지 않은 것 같습니다.', 'bad');
        }
      })();
    }
    if (t.id === 'cli-change') {
      return void (async () => {
        const r = await mm.cli.choose();
        if (r.canceled) return;
        if (r.error === 'wrong_file') {
          toast('다른 파일입니다', r.expected + ' 를 선택하세요.', 'bad');
          return;
        }
        if (r.ok) {
          toast('커넥터 위치를 지정했습니다', r.path, 'ok');
          await loadCompat(true);
          await refreshTopbar();
        } else {
          toast('지정한 위치에서 실행 파일을 찾을 수 없습니다', '', 'bad');
        }
      })();
    }
    if (t.dataset.instrument) {
      return void runAction('change_instrument', { name: t.dataset.instrument },
        { label: t.dataset.instrument + ' 장착', skipConfirm: true }).then(() => loadMusic(true));
    }
    if (t.dataset.plAdd) {
      return void (async () => {
        if (!plCurrent) { toast('재생목록이 없습니다', '먼저 새로 만들기를 누르세요.', 'bad'); return; }
        await mm.pl.addTrack(plCurrent.id, t.dataset.plAdd);
        await refreshPlaylists();
        say('담았습니다: ' + t.dataset.plAdd);
      })();
    }
    if (t.dataset.plDel !== undefined) {
      return void (async () => {
        await mm.pl.removeTrack(plCurrent.id, parseInt(t.dataset.plDel, 10));
        await refreshPlaylists();
      })();
    }
    if (t.dataset.plMove !== undefined) {
      return void (async () => {
        await mm.pl.moveTrack(plCurrent.id, parseInt(t.dataset.plMove, 10), parseInt(t.dataset.plDelta, 10));
        await refreshPlaylists();
      })();
    }
    if (t.dataset.play || t.dataset.playGoal) {
      const title = t.dataset.play || t.dataset.playGoal;
      return void (t.dataset.play ? actNow : actGoal)({ act: 'play', command: 'play_music_score', body: { title },
        label: '연주: ' + scoreLabel(title), detail: '연주 1곡', skipConfirm: true });
    }
    // 일어서기처럼 전용 명령을 쓰는 항목. 목록에서는 다른 행동과 같은 자리에 있다.
    if (t.dataset.socialRun) {
      return void runAction(t.dataset.socialRun, undefined,
        { label: t.dataset.socialName || t.dataset.socialRun, skipConfirm: true });
    }
    if (t.dataset.socialCmd) {
      return void runAction('write_chat', t.dataset.socialCmd,
        { label: '소셜: ' + t.dataset.socialCmd, skipConfirm: true });
    }
    // 표정은 이름이 아니라 이모지를 보내야 한다.
    // 행동은 /전통댄스 같은 ChatCommands를 쓰지만, 표정에는 ChatCommands가 아예 없고
    // EmojiText만 있다. "/미소"처럼 보내면 unsupported_command로 거부된다.
    if (t.dataset.socialEmoji) {
      return void runAction('write_chat', t.dataset.socialEmoji,
        { label: '표정: ' + (t.dataset.socialName || t.dataset.socialEmoji), skipConfirm: true });
    }
  });

}
