'use strict';
/**
 * Electron 메인 프로세스.
 *
 * 기존 src/ 코어를 그대로 재사용한다. 렌더러에는 Node를 노출하지 않고
 * preload의 contextBridge를 통해 정해진 IPC 채널만 연다.
 */
const path = require('path');
const fs = require('fs');
const { app, BrowserWindow, Tray, Menu, ipcMain, Notification, shell, nativeImage, dialog,
  desktopCapturer, screen } = require('electron');

const connector = require('../src/connector');
const query = require('../src/query');
const cache = require('../src/cache');
const routines = require('../src/routines');
const version = require('../src/version');
const errors = require('../src/errors');
const settings = require('../src/settings');
const plan = require('../src/plan');
const goal = require('../src/goal');
const playlist = require('../src/playlist');
const knowledge = require('../src/knowledge');
const gamerules = require('../src/gamerules');
const log = require('../src/log');
const favorites = require('../src/favorites');
const queueStore = require('../src/queue');
const recipebook = require('../src/recipebook');
const dyeprefs = require('../src/dyeprefs');

let win = null;
let tray = null;
let quitting = false;

/** 실행 중인 CLI 호출 핸들. 취소를 위해 하나만 들고 있는다. */
let currentAction = null;

/* ── 조회 라우팅 ────────────────────────────────────────────── */

const QUERIES = {
  me: query.me,
  activity: query.activity,
  environment: query.environment,
  inventory: query.inventory,
  currencies: query.currencies,
  wings: query.wings,
  items: query.items,
  itemCount: (o) => query.itemCount(o && o.name, o),
  craft: query.craft,
  craftFind: (o) => query.craftFind(o && o.name, o),
  alter: query.alter,
  alteringWorks: query.alteringWorks,
  gather: query.gather,
  daily: query.daily,
  weekly: query.weekly,
  quests: query.quests,
  nearNpcs: query.nearNpcs,
  nearPcs: query.nearPcs,
  instruments: query.instruments,
  musicScores: query.musicScores,
  socialActions: query.socialActions,
};

/* ── 염색 오버레이 ──────────────────────────────────────────── */

/**
 * 게임 위에 겹쳐 그리는 창.
 *
 * 화면 전체를 덮고, 클릭은 전부 통과시키며(setIgnoreMouseEvents), **화면 캡처에는 잡히지
 * 않는다**(setContentProtection). 마지막 것이 중요하다 — 우리가 화면을 캡처해 팔레트를
 * 찾는데 우리 표시가 그 캡처에 섞이면, 다음 번에는 제가 그린 것을 팔레트로 오인한다.
 */
let overlayWin = null;

function ensureOverlay() {
  if (overlayWin && !overlayWin.isDestroyed()) return overlayWin;
  const b = screen.getPrimaryDisplay().bounds;
  overlayWin = new BrowserWindow({
    x: b.x, y: b.y, width: b.width, height: b.height,
    transparent: true, frame: false, resizable: false, movable: false,
    skipTaskbar: true, focusable: false, show: false,
    hasShadow: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: false },
  });
  overlayWin.setIgnoreMouseEvents(true, { forward: true });
  overlayWin.setAlwaysOnTop(true, 'screen-saver');
  overlayWin.setVisibleOnAllWorkspaces(true);
  try { overlayWin.setContentProtection(true); } catch (_) { /* 구형 윈도우 */ }
  overlayWin.loadFile(path.join(__dirname, 'overlay', 'index.html'));
  // 만들 때 준 크기가 작업 영역으로 깎인다 (실측 — 1920x1080 을 줬는데 1920x1032).
  // 작업 표시줄 위에도 그려야 하므로 만든 뒤 다시 박는다.
  overlayWin.setBounds(b);
  overlayWin.on('closed', () => { overlayWin = null; });
  return overlayWin;
}

async function overlayDraw(payload) {
  const win = ensureOverlay();
  if (!win.isVisible()) win.showInactive();
  try {
    await win.webContents.executeJavaScript(
      'window.__dyeDraw && window.__dyeDraw(' + JSON.stringify(payload || {}) + ')');
  } catch (_) { /* 아직 안 뜬 상태면 다음 번에 그려진다 */ }
}

function overlayHide() {
  if (overlayWin && !overlayWin.isDestroyed()) overlayWin.hide();
}

/* ── 창 / 트레이 ────────────────────────────────────────────── */

/**
 * 기본 응용 프로그램 메뉴를 없앤다.
 *
 * autoHideMenuBar 는 **숨길 뿐이라** Alt 를 누르면 File / Edit / View / Window 가 튀어나온다.
 * 이 앱에는 그 메뉴가 할 일이 하나도 없다 — 새 창도, 인쇄도, 확대도 쓰지 않고 종료는
 * 트레이에서 한다. 게임을 앞에 두고 Alt 를 자주 누르는 쓰임이라 더 거슬린다.
 *
 * Chromium 이 편집 단축키(Ctrl+C/V/X/A, 실행 취소)는 메뉴 없이도 그대로 처리하므로
 * 입력란에서 잃는 것은 없다. 개발자 도구는 MM_DEBUG 로 띄웠을 때만 남긴다.
 */
function setupMenu() {
  if (process.env.MM_DEBUG) return;   // 디버그 모드에서는 기본 메뉴(재실행·개발자 도구)를 둔다
  Menu.setApplicationMenu(null);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 980,
    minHeight: 640,
    title: '모비 커넥터 리모콘',
    // 페이지가 뜨기 전 잠깐 보이는 바탕이다. 테마와 어긋나면 흰/검은 판이 번쩍인다.
    backgroundColor: settings.load().theme === 'light' ? '#f1f3f7' : '#14161a',
    // 메뉴는 setupMenu() 에서 아예 없앤다. 이 옵션은 그래도 켜 둔다 —
    // 디버그 모드로 띄웠을 때 메뉴가 화면을 밀어 내리지 않게.
    autoHideMenuBar: true,
    icon: path.join(__dirname, 'renderer', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      // 창이 뒤에 있어도 자동 갱신 타이머가 느려지지 않게 한다.
      // (게임을 앞에 두고 보조 모니터에서 보는 쓰임새가 기본이다)
      backgroundThrottling: false,
    },
  });

  // MM_DEBUG=1 로 띄우면 렌더러 콘솔(및 CSP 위반)을 터미널에서 볼 수 있다.
  if (process.env.MM_DEBUG) {
    const LEVEL = ['log', 'warn', 'error', 'debug'];
    win.webContents.on('console-message', (_e, level, message, line, sourceId) => {
      const src = String(sourceId || '').split(/[\\/]/).pop();
      console.log('[renderer:' + (LEVEL[level] || level) + '] ' + message + (src ? '  (' + src + ':' + line + ')' : ''));
    });
  }

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // 창을 닫아도 트레이에 남는다. 완전 종료는 트레이 메뉴에서.
  win.on('close', (e) => {
    if (!quitting) {
      e.preventDefault();
      win.hide();
    }
  });

  // 외부 링크는 기본 브라우저로
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

/**
 * 트레이 아이콘.
 *
 * 트레이는 16~32px로 그려진다. 창 아이콘(256px)을 그대로 주면 Electron이 매번 줄여야 하므로
 * 미리 줄여 둔 tray.png 를 먼저 쓴다. 없으면 창 아이콘으로, 그것도 없으면 빈 이미지로 떨어진다
 * (파일이 없다고 앱이 못 뜨면 안 된다).
 */
function trayIcon() {
  for (const name of ['tray.png', 'icon.png']) {
    const img = nativeImage.createFromPath(path.join(__dirname, 'renderer', name));
    if (!img.isEmpty()) return img;
  }
  return nativeImage.createEmpty();
}

async function buildTrayMenu() {
  let statusLabel = '연결 확인 중...';
  let wingsLabel = '';
  try {
    const st = await connector.status();
    statusLabel = st.connected ? '● 연결됨' : '● 연결 안 됨';
    if (st.connected) {
      const w = await query.wings();
      wingsLabel = '정령의 날개 ' + Number(w.amount || 0).toLocaleString('ko-KR');
    }
  } catch (_) {
    statusLabel = '● 상태 확인 실패';
  }

  const items = [
    { label: statusLabel, enabled: false },
  ];
  if (wingsLabel) items.push({ label: wingsLabel, enabled: false });
  items.push(
    { type: 'separator' },
    { label: '창 열기', click: () => { win.show(); win.focus(); } },
    { type: 'separator' },
    { label: '종료', click: () => { quitting = true; app.quit(); } }
  );
  return Menu.buildFromTemplate(items);
}

async function createTray() {
  tray = new Tray(trayIcon());
  tray.setToolTip('모비 커넥터 리모콘');
  tray.setContextMenu(await buildTrayMenu());
  tray.on('double-click', () => { win.show(); win.focus(); });

  // 메뉴를 열 때마다 최신 상태로 갱신
  tray.on('right-click', async () => {
    tray.setContextMenu(await buildTrayMenu());
    tray.popUpContextMenu();
  });
}

function notify(title, body) {
  if (!Notification.isSupported()) return;
  // 알림에도 아이콘을 붙인다. 여러 프로그램의 알림이 쌓일 때 어느 것인지 바로 보인다.
  new Notification({ title, body, icon: path.join(__dirname, 'renderer', 'icon.png') }).show();
}

/* ── 레시피 학습 ────────────────────────────────────────────── */

/**
 * 레시피를 배울 수 있는 명령인가.
 *
 * 게임이 재료를 알려주지 않는 레시피는 실행 전후 인벤을 비교하는 수밖에 없다.
 * 1회 실행일 때만 배운다 — 여러 회 diff를 횟수로 나누면 중간에 낀 잡음이 소수점으로 번진다.
 */
function recipeLearnKind(command, body) {
  if (command === 'execute_crafting') {
    const n = body && body.craftCount;
    return (n === undefined || n === 1) ? 'craft' : null;
  }
  // 가공은 큐에 올리는 시점에 재료가 빠진다. 산출물은 수령 때 들어오지만
  // 그쪽 수치는 get_alterable_items의 ProducedPerWork로 공짜로 알 수 있다.
  if (command === 'execute_altering') return 'alter';
  return null;
}

/**
 * 수령 직전, 그 시설에서 완료된 가공이 **한 종류뿐인지** 확인한다.
 *
 * 한 종류만 완료돼 있고 보상도 한 종류라면, 그 레시피가 무엇을 만드는지 확정할 수 있다.
 * 여러 종류가 섞여 있으면 어느 보상이 어느 레시피 것인지 알 수 없으므로 배우지 않는다.
 * (철괴(광석)과 철괴(철 광석)처럼 이름만으로는 산출물을 알 수 없는 레시피가 있다)
 */
async function soleCompletedRecipe(displayName) {
  try {
    const r = await connector.run('get_altering_works');
    if (!r.ok) return null;
    const works = (r.data && r.data.works) || [];
    const mine = works.find((w) => w.DisplayName === displayName);
    if (!mine) return null;
    const done = works.filter((w) => w.IsCompleted && w.FacilityName === mine.FacilityName);
    if (!done.length) return null;
    const names = {};
    for (const w of done) names[w.DisplayName] = true;
    const keys = Object.keys(names);
    return keys.length === 1 ? keys[0] : null;
  } catch (_) {
    return null;
  }
}

/** 가공 1건이 몇 개를 내놓는가. 캐시된 조회에서 꺼내 온다 (호출 없음). */
function producedPerWork(displayName) {
  try {
    // 산출량은 자주 바뀌는 값이 아니다. TTL 때문에 못 읽느니 오래된 것이라도 쓴다.
    const c = cache.read('get_alterable_items', 24 * 3600 * 1000);
    const items = (c && c.data && c.data.items) || [];
    const hit = items.find((x) => x.DisplayName === displayName);
    return hit ? hit.ProducedPerWork : undefined;
  } catch (_) {
    return undefined;
  }
}

/**
 * 그 시설 큐에 지금 몇 건이 올라가 있는지. 못 세면 null.
 * 완료된 작업도 칸을 차지하므로 IsCompleted 여부와 무관하게 전부 센다.
 */
async function facilityUsed(facility) {
  try {
    const r = await connector.run('get_altering_works');
    if (!r.ok) return null;
    const works = (r.data && r.data.works) || [];
    return works.filter((w) => w.FacilityName === facility).length;
  } catch (_) {
    return null;
  }
}

/** 인벤 스냅샷. 실패하면 null — 학습을 포기할 뿐 실행에는 영향이 없다. */
async function itemSnapshot() {
  try {
    const r = await connector.run('get_items');
    return r.ok ? knowledge.itemTotals(r.data) : null;
  } catch (_) {
    return null;
  }
}

/* ── IPC ────────────────────────────────────────────────────── */

function registerIpc() {
  // 연결 상태
  ipcMain.handle('status', async () => {
    try {
      return await connector.status();
    } catch (err) {
      return { connected: false, pipe: 'error', reason: null, message: String(err && err.message) };
    }
  });

  // 조회 - 이름으로 query.js 함수를 부른다
  ipcMain.handle('query', async (_e, name, opts) => {
    const fn = QUERIES[name];
    if (!fn) return { error: 'unknown_query', message: name };
    try {
      return await fn(opts || {});
    } catch (err) {
      return { error: 'query_failed', message: String(err && err.message) };
    }
  });

  // 여러 조회를 한 번에 (대시보드 새로고침용)
  ipcMain.handle('queryMany', async (_e, names, opts) => {
    const outv = {};
    await Promise.all(
      (names || []).map(async (n) => {
        const fn = QUERIES[n];
        if (!fn) {
          outv[n] = { error: 'unknown_query' };
          return;
        }
        try {
          outv[n] = await fn((opts && opts[n]) || {});
        } catch (err) {
          outv[n] = { error: 'query_failed', message: String(err && err.message) };
        }
      })
    );
    return outv;
  });

  // 명령 실행. 비용 있는 명령은 렌더러가 미리 확인을 받은 뒤 호출한다.
  ipcMain.handle('exec', async (_e, command, body) => {
    if (currentAction) return { ok: false, error: 'busy', message: '다른 명령이 실행 중입니다.' };

    const cost = connector.costOf(command);
    const started = Date.now();
    if (win) win.webContents.send('mm:exec-start', { command, body, costed: !!cost });

    // 레시피를 배울 명령이면 먼저 인벤을 찍어 둔다 (get_items는 무료, ~50ms)
    const learnKind = recipeLearnKind(command, body);
    const snapBefore = learnKind ? await itemSnapshot() : null;

    // 가공이 칸 부족으로 막히면, 그 순간의 큐 개수가 곧 그 시설의 칸 수다.
    // 미리 세어 둬야 "막힌 뒤에도 큐가 그대로인가"를 판단할 수 있다.
    // execute_altering 일 때만 센다 — 다른 명령에서 공짜 조회를 한 번씩 더 할 이유가 없다.
    const alterFacility = command === 'execute_altering' && body && body.displayName
      ? knowledge.facilityOf(body.displayName)
      : null;
    const usedBefore = alterFacility ? await facilityUsed(alterFacility) : null;

    // 칸이 없는데 보내면 게임이 이동까지 시킨 뒤 막으면서 **날개 5를 가져간다**(실측).
    // 그러니 커넥터에 넘기기 전에 여기서 끊는다. 레벨을 정해 둔 시설은 그 칸 수가 상한이다.
    // 레벨을 안 정했으면 최고 레벨인 셈 치므로, 진짜 상한이 더 낮다면 한 번은 막히고 그때 확정된다.
    if (alterFacility && usedBefore !== null) {
      const room = knowledge.facilityRoom(alterFacility, usedBefore);
      if (!room.ok) {
        const payload = {
          ok: false,
          code: 0,
          error: 'facility_full',
          message: alterFacility + ' ' + room.used + '/' + room.slots,
          data: null,
          durationMs: Date.now() - started,
          wingsSpent: 0,
          costInfo: null,
          ko: {
            code: 'facility_full',
            text: alterFacility + ' 칸이 가득 찼습니다',
            hint: '최대 ' + room.slots + '칸(' + room.source + ') 중 ' + room.used + '칸을 쓰고 있습니다. ' +
                  '완료분을 수령해 칸을 비우거나, 레벨을 다시 확인하세요.',
            known: true,
          },
        };
        log.command(command, body, payload);
        if (win) win.webContents.send('mm:exec-done', Object.assign({ command }, payload));
        return payload;
      }
    }

    // 가공 수령은 "이 레시피가 무엇을 만드는가"를 알 수 있는 유일한 순간이다.
    // 조회 어디에도 산출물 이름 필드가 없다.
    const soleRecipe = command === 'complete_altering_work' && body && body.displayName
      ? await soleCompletedRecipe(body.displayName)
      : null;

    const handle = connector.runCancelable(command, body);
    currentAction = handle;
    let r;
    try {
      r = await handle.promise;
    } finally {
      currentAction = null;
    }

    // 조회 명령이면 캐시를 갱신해 둔다
    if (r.ok && typeof command === 'string' && command.startsWith('get_')) cache.write(command, r.data);

    // 응답에서 배울 수 있는 것을 챙긴다
    let spent = null;
    try {
      // 게임이 실제 소모량을 알려준다. 추정치(costOf)보다 이쪽이 사실이다.
      spent = knowledge.parseCost(r.data);
      // 제작 시설 상한은 거부당할 때만 알려준다
      if (r.data && r.data.error === 'invalid_count' && r.data.maxCount) {
        knowledge.learnCraftLimit(body && body.displayName, r.data.maxCount);
      }
    } catch (_) { /* 학습 실패는 실행 결과에 영향을 주지 않는다 */ }

    // 인벤이 어떻게 변했는지로 레시피를 역산한다.
    // 게임은 만들 수 있는 레시피의 재료를 끝내 알려주지 않으므로 이게 유일한 경로다.
    if (learnKind && snapBefore && r.ok) {
      try {
        const snapAfter = await itemSnapshot();
        if (snapAfter) {
          knowledge.learnRecipeFromDiff(body && body.displayName, learnKind, {
            diff: knowledge.diffItems(snapBefore, snapAfter),
            runs: 1,
            rewards: r.data && r.data.rewards,
            // 가공은 등록 시점에 보상이 없다. 산출량은 조회가 공짜로 알려주므로 그걸 쓴다.
            produced: learnKind === 'alter' ? producedPerWork(body && body.displayName) : undefined,
          });
        }
      } catch (_) { /* 학습은 부가 기능이다 */ }
    }

    // 칸이 꽉 차서 막힌 것인지 확인한다.
    //
    // blocked 가 늘 "칸 부족"은 아니다 — 다른 팝업일 수도 있다. 그래서 두 가지를 같이 본다.
    //   · 큐가 늘지 않았는가 (등록이 실제로 실패했는가)
    //   · 지금까지 본 최대 큐보다 작지 않은가 (knowledge 쪽에서 한 번 더 거른다)
    // 통과하면 그 개수가 곧 칸 수이고, 칸 수가 정해지면 레벨도 정해진다.
    if (alterFacility && usedBefore > 0 && r.data && r.data.error === 'blocked') {
      try {
        const usedAfter = await facilityUsed(alterFacility);
        if (usedAfter === usedBefore) {
          const before = knowledge.facilitySlots(alterFacility);
          knowledge.learnFacilityFull(alterFacility, usedAfter);
          const after = knowledge.facilitySlots(alterFacility);
          if (after.level && after.level !== before.level && win) {
            win.webContents.send('mm:facility-level', {
              facility: alterFacility, level: after.level, slots: after.slots,
            });
          }
        }
      } catch (_) { /* 감지 실패는 실행 결과에 영향을 주지 않는다 */ }
    }

    // 수령한 시설에 한 종류만 완료돼 있었다면, 받은 보상이 곧 그 레시피의 산출물이다
    if (soleRecipe && r.ok) {
      try {
        const item = knowledge.productFromRewards(soleRecipe, r.data && r.data.rewards);
        if (item) knowledge.learnProduct(soleRecipe, item);
      } catch (_) { /* 학습은 부가 기능이다 */ }
    }

    const payload = {
      ok: r.ok,
      code: r.code,
      error: r.error,
      message: r.message,
      data: r.data,
      durationMs: Date.now() - started,
      // 게임이 알려준 실제 소모량을 우선한다. blocked로 끝나도 비용은 나갈 수 있다.
      wingsSpent: spent ? spent.amount : (cost && r.ok ? cost.amount : 0),
      costInfo: spent,
      // 렌더러는 Node를 못 쓰므로 한국어 해설을 여기서 붙여 보낸다
      ko: r.ok ? null : errors.describe(command, r.error, r.message, r.data),
    };
    log.command(command, body, payload);
    if (win) win.webContents.send('mm:exec-done', Object.assign({ command }, payload));
    return payload;
  });

  // 실행 중인 명령 취소
  ipcMain.handle('cancel', async () => {
    if (!currentAction) return { ok: false, error: 'idle' };
    currentAction.cancel();
    return { ok: true };
  });

  // 비용 조회 - 렌더러가 확인 문구를 만들 때 쓴다
  ipcMain.handle('costOf', async (_e, command, times) => {
    const n = Math.max(1, times || 1);
    const cost = connector.costOf(command);
    if (!cost) return { costed: false, perCall: 0, total: 0, currency: null, balance: 0, enough: true };
    const total = cost.amount * n;
    // 재화 이름으로 잔량을 찾는다. 비용 재화가 바뀌어도 따라간다.
    const cur = await query.currencies({ search: cost.currency, refresh: true });
    const row = (cur.items || []).find((x) => x.name === cost.currency) || (cur.items || [])[0];
    const balance = row ? row.amount : 0;
    return {
      costed: true,
      perCall: cost.amount,
      total,
      currency: cost.currency,
      balance,
      enough: balance >= total,
    };
  });

  // 명령 목록 (원시 콘솔 탭)
  ipcMain.handle('capabilities', async (_e, refresh) => {
    const cmds = refresh ? await connector.refreshCapabilities() : connector.loadCapabilities();
    return cmds.map((x) => ({
      command: x.Command,
      description: x.Description,
      bodyExample: x.BodyExample,
      note: x.Note || '',
      action: connector.ACTION_COMMANDS.has(x.Command),
      cost: connector.costOf(x.Command),
      costed: connector.isCosted(x.Command),
    }));
  });

  /* 로그 */
  ipcMain.handle('log:tail', async (_e, n) => log.tail(n));
  ipcMain.handle('log:files', async () => log.listFiles());
  ipcMain.handle('log:open', async () => { shell.openPath(log.DIR); });

  /* 학습된 지식 — CLI가 주지 않는 정보 */
  ipcMain.handle('kn:get', async () => knowledge.load());
  ipcMain.handle('kn:setSlots', async (_e, facility, slots) => knowledge.setFacilitySlots(facility, slots));
  ipcMain.handle('kn:setLevel', async (_e, facility, level) => knowledge.setFacilityLevel(facility, level));
  // 레벨별 칸 수는 game-rules.json 에서 온다. 화면이 선택지를 만들려면 이 표가 필요하다.
  ipcMain.handle('kn:rules', async () => ({
    altering: gamerules.alteringFacility(),
    fallback: gamerules.isFallback(),
  }));
  ipcMain.handle('kn:markFull', async (_e, facility, used) => knowledge.learnFacilityFull(facility, used));
  // 잘못 배운 레시피는 사용자가 지울 수 있어야 한다. 관측은 틀릴 수 있다.
  ipcMain.handle('kn:forgetRecipe', async (_e, name) => knowledge.forgetRecipe(name));

  // 화면 설정 (정렬 기준 등). 게임 호출과 무관하다.
  /* 염색 도우미 — CLI 와 무관하다. 화면 픽셀만 읽고 게임에 아무것도 보내지 않는다. */
  ipcMain.handle('dye:prefs', async () => dyeprefs.load());
  ipcMain.handle('dye:add', async (_e, name, colors) => dyeprefs.add(name, colors));
  ipcMain.handle('dye:update', async (_e, id, patch) => dyeprefs.update(id, patch));
  ipcMain.handle('dye:remove', async (_e, id) => dyeprefs.remove(id));
  ipcMain.handle('dye:select', async (_e, id) => dyeprefs.select(id));

  // 캡처할 화면 소스. getSources 는 한 번에 0.5초가 걸려서 **시작할 때 한 번만** 부른다.
  // 그 뒤로는 렌더러가 getUserMedia 로 실시간 스트림을 받아 직접 읽는다.
  ipcMain.handle('dye:source', async () => {
    const b = screen.getPrimaryDisplay().bounds;
    const srcs = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 1, height: 1 } });
    const s = srcs[0];
    if (!s) return { error: 'no_source' };
    return { id: s.id, name: s.name, bounds: b, scale: screen.getPrimaryDisplay().scaleFactor };
  });

  /**
   * 염색 중에는 **우리 창이 화면 캡처에 잡히지 않게** 한다.
   *
   * 리모콘 창에는 히트맵과 색 견본이 있어서 팔레트만큼 알록달록하다. 그대로 두면
   * 캡처에 섞여 들어가 앱 창과 팔레트가 한 덩어리로 붙고, 엉뚱한 사각형이 잡힌다
   * (실측 — 755px 팔레트가 380px 로 나왔다).
   *
   * 실측 — 보호를 켠 창은 캡처에서 **0픽셀**, 끈 창은 400x400 그대로 159,537픽셀이 잡힌다.
   * 염색을 끄면 되돌린다. 평소에는 사용자가 이 창을 스크린샷 찍을 수 있어야 한다.
   */
  ipcMain.handle('dye:protect', async (_e, on) => {
    try { if (win && !win.isDestroyed()) win.setContentProtection(!!on); } catch (_) {}
    return true;
  });

  /**
   * 스포이드용으로 화면을 한 장 찍는다.
   *
   * 리모콘 창과 덧창을 **잠깐 감췄다 되돌린다.** setContentProtection 으로는 안 된다 —
   * 실측했더니 제외한 창 자리는 뒤가 비치는 게 아니라 **검게 칠해진다.**
   *
   *   창 한가운데   제외 켬 rgb(12,12,12)   ·   끔 rgb(45,50,55)
   *
   * 뒤에 있는 게임을 찍는 것이 목적이므로 실제로 비켜야 한다. 덧창도 같이 감춘다 —
   * 팔레트 위에 우리가 그린 빨간 박스가 같이 찍히면 엉뚱한 색을 집게 된다.
   *
   * 찍는 일은 렌더러가 아니라 여기서 한다. 감춰진 창은 타이머가 느려져서,
   * 렌더러에서 흐름을 열어 기다리면 빈 장면이 오기 쉽다.
   */
  ipcMain.handle('dye:snap', async () => {
    const b = screen.getPrimaryDisplay().bounds;
    const winUp = win && !win.isDestroyed() && win.isVisible();
    const ovUp = overlayWin && !overlayWin.isDestroyed() && overlayWin.isVisible();
    if (ovUp) overlayWin.hide();
    if (winUp) win.hide();
    try {
      await new Promise((r) => setTimeout(r, 250));
      const srcs = await desktopCapturer.getSources({
        types: ['screen'], thumbnailSize: { width: b.width, height: b.height },
      });
      const s = srcs[0];
      if (!s || s.thumbnail.isEmpty()) return { error: 'no_source' };
      return { dataUrl: s.thumbnail.toDataURL(), bounds: b };
    } finally {
      if (winUp) win.show();
      if (ovUp) overlayWin.showInactive();
    }
  });

  /**
   * 작업 큐를 접고 펼 때 **창 자체의 폭**을 그만큼 줄이고 늘린다.
   *
   * 큐만 줄이고 본문을 넓히면 화면을 덜 쓰겠다는 뜻이 안 이뤄진다. 오른쪽 끝을 왼쪽으로
   * 당겨 창을 좁힌다 — 왼쪽 위 모서리는 그대로 두므로 창이 튀어 다니지 않는다.
   */
  ipcMain.handle('win:narrow', async (_e, px) => {
    if (!win || win.isDestroyed()) return null;
    const b = win.getBounds();
    // 최소 폭은 창에 이미 걸어 두었다(minWidth). setBounds 가 알아서 막는다.
    const next = b.width - Math.round(px || 0);
    if (next !== b.width) win.setBounds({ x: b.x, y: b.y, width: next, height: b.height });
    return win.getBounds().width;
  });

  /**
   * 게임 화면과 오버레이를 **함께** 한 장 찍어, 클립보드와 파일로 남긴다.
   *
   * dye:snap 과 반대다. 저쪽은 스포이드로 게임 색을 집으려는 것이라 우리 표시가 섞이면
   * 안 되고, 이쪽은 우리 표시를 보여 주려는 것이라 섞여야 한다.
   *
   * 리모콘 창만 비킨다 — 게임 위에 무엇이 그려지는지가 찍혀야 하니까.
   */
  ipcMain.handle('dye:shot', async () => {
    const b = screen.getPrimaryDisplay().bounds;
    const winUp = win && !win.isDestroyed() && win.isVisible();
    const ov = overlayWin && !overlayWin.isDestroyed() ? overlayWin : null;
    if (winUp) win.hide();
    try { if (ov) ov.setContentProtection(false); } catch (_) {}
    try {
      await new Promise((r) => setTimeout(r, 300));
      const srcs = await desktopCapturer.getSources({
        types: ['screen'], thumbnailSize: { width: b.width, height: b.height },
      });
      const s = srcs[0];
      if (!s || s.thumbnail.isEmpty()) return { error: 'no_source' };

      const dir = path.join(app.getPath('pictures'), '모비 커넥터 리모콘');
      fs.mkdirSync(dir, { recursive: true });
      const t = new Date();
      const pad = (v) => String(v).padStart(2, 0);
      const name = '염색 ' + t.getFullYear() + pad(t.getMonth() + 1) + pad(t.getDate()) +
        '-' + pad(t.getHours()) + pad(t.getMinutes()) + pad(t.getSeconds()) + '.png';
      const file = path.join(dir, name);
      const png = s.thumbnail.toPNG();
      fs.writeFileSync(file, png);
      // 클립보드는 렌더러가 넣는다. 이 빌드의 main 쪽 clipboard 는 비동기 웹 API 라
      // writeImage 가 없고 ClipboardItem 을 요구하는데, 그 생성자는 여기 없다.
      return { path: file, png: png };
    } finally {
      try { if (ov) ov.setContentProtection(true); } catch (_) {}
      if (winUp) win.show();
    }
  });

  ipcMain.handle('dye:draw', async (_e, payload) => { await overlayDraw(payload); return true; });
  ipcMain.handle('dye:hide', async () => { overlayHide(); return true; });

  /* 레시피 장부 — 게임이 알려 준 재료를 긁어모은다. 조회뿐이라 공짜다. */
  ipcMain.handle('book:stats', async () => recipebook.stats());
  ipcMain.handle('book:harvest', async () => {
    const recipes = JSON.parse(JSON.stringify(recipebook.load().recipes));   // 캐시를 건드리지 않는다
    const known = knowledge.load().recipes || {};
    const totals = { rows: 0, named: 0, lines: 0, newNames: 0, newVariants: 0, completed: 0 };

    for (const [command, via, okKey, perKey] of [
      ['get_craftable_items', 'craft', 'Craftable', 'ProducedPerCraft'],
      ['get_alterable_items', 'alter', 'Alterable', 'ProducedPerWork'],
    ]) {
      const r = await connector.run(command);
      if (!r.ok) return { error: r.error || 'query_failed', message: r.message };
      const rows = (r.data && r.data.items) || [];
      const s = recipebook.mergeRows(recipes, rows, via, okKey, perKey, known);
      for (const k of Object.keys(totals)) totals[k] += s[k];
    }

    recipebook.saveUser(recipes);
    return Object.assign({ ok: true }, totals, recipebook.stats());
  });

  /* 작업 큐 — 목록만 저장한다. 순서와 진행은 화면이 정한다. */
  ipcMain.handle('queue:load', async () => queueStore.load());
  ipcMain.handle('queue:save', async (_e, state) => queueStore.save(state));

  /* 즐겨찾기 — 목록별 별표. 화면에서 구역을 나누는 데만 쓴다. */
  ipcMain.handle('fav:all', async () => favorites.load());
  ipcMain.handle('fav:toggle', async (_e, list, name) => favorites.toggle(list, name));
  ipcMain.handle('fav:clear', async (_e, list) => favorites.clear(list));

  ipcMain.handle('cfg:get', async () => settings.load());
  ipcMain.handle('cfg:theme', async (_e, v) => settings.save({ theme: v === 'light' ? 'light' : 'dark' }));

  // 화면 설정 하나를 바꾼다. 아무 키나 받지 않고 정해진 것만 허용한다 —
  // 렌더러가 설정 파일 전체를 마음대로 쓰게 두면 나중에 무엇이 어디서 바뀌는지 알 수 없다.
  const CFG_KEYS = {
    askFacilityLevelMismatch: 'boolean',
    alterWorksFolded: 'boolean',
    queueFolded: 'boolean',
  };
  ipcMain.handle('cfg:set', async (_e, key, value) => {
    if (CFG_KEYS[key] !== typeof value) return settings.load();
    const patch = {};
    patch[key] = value;
    return settings.save(patch);
  });
  ipcMain.handle('cfg:sort', async (_e, tab, key) => {
    const s = settings.load();
    const next = Object.assign({}, s.sort || {});
    next[tab] = key;
    return settings.save({ sort: next });
  });

  // 목표 루프 — 한 걸음씩 물어보고 렌더러가 실행한다.
  // 상태를 매번 새로 읽는다. 한 걸음 돌린 뒤의 캐시는 이미 옛것이다.
  ipcMain.handle('goal:next', async (_e, name, target) => {
    try {
      const snap = await goal.snapshot({ refresh: true });
      if (snap.error) return { error: snap.error, message: snap.message };
      return {
        step: goal.nextStep(snap, name, target),
        estimate: goal.estimate(snap, name, target),
        have: snap.owned.get(name) || 0,
      };
    } catch (err) {
      return { error: 'goal_failed', message: String(err && err.message) };
    }
  });

  /* 재생목록 — 캐릭터 식별이 불가능해 사용자가 직접 관리한다 */
  ipcMain.handle('pl:list', async () => playlist.list());
  ipcMain.handle('pl:create', async (_e, name) => playlist.create(name));
  ipcMain.handle('pl:update', async (_e, id, patch) => playlist.update(id, patch));
  ipcMain.handle('pl:remove', async (_e, id) => playlist.remove(id));
  ipcMain.handle('pl:addTrack', async (_e, id, title) => playlist.addTrack(id, title));
  ipcMain.handle('pl:removeTrack', async (_e, id, i) => playlist.removeTrack(id, i));
  ipcMain.handle('pl:moveTrack', async (_e, id, i, d) => playlist.moveTrack(id, i, d));

  /**
   * 가공 목표를 **사슬 끝까지** 점검한다.
   *
   * 무엇을 몇 번 가공하고, 무엇을 몇 번 캐야 하는지까지 나온다. 전부 무료 조회다.
   */
  ipcMain.handle('plan:needs', async (_e, target, count, opts) => {
    try {
      return await plan.deepPlan(target, count, opts || {});
    } catch (err) {
      return { ok: false, error: 'plan_failed', message: String(err && err.message) };
    }
  });

  /* 제작 목표 사전 점검 — 전부 무료 조회라 날개를 쓰기 전에 판단한다 */
  ipcMain.handle('plan:craft', async (_e, name, target, opts) => {
    try {
      return await plan.makePlan(name, target, opts || {});
    } catch (err) {
      return { error: 'plan_failed', message: String(err && err.message) };
    }
  });

  /* CLI 경로 */

  ipcMain.handle('cli:locate', async (_e, force) => {
    const r = connector.resolveExe(!!force);
    return { path: r.path, source: r.source, found: r.found, tried: r.tried };
  });

  // 자동 탐색이 실패한 환경에서 사용자가 직접 지정한다
  ipcMain.handle('cli:choose', async () => {
    const res = await dialog.showOpenDialog(win, {
      title: 'MabinogiMobile_CLI.exe 위치를 선택하세요',
      properties: ['openFile'],
      filters: [{ name: '마비노기 모바일 커넥터', extensions: ['exe'] }],
    });
    if (res.canceled || !res.filePaths.length) return { canceled: true };

    const picked = res.filePaths[0];
    if (path.basename(picked).toLowerCase() !== connector.EXE_NAME.toLowerCase()) {
      return { canceled: false, ok: false, error: 'wrong_file', expected: connector.EXE_NAME };
    }
    settings.save({ cliPath: picked });
    const r = connector.resolveExe(true);
    return { canceled: false, ok: r.found, path: r.path, source: r.source };
  });

  ipcMain.handle('cli:clearPath', async () => {
    settings.save({ cliPath: '' });
    const r = connector.resolveExe(true);
    return { path: r.path, source: r.source, found: r.found };
  });

  /* 버전 · 호환성 */

  ipcMain.handle('version:info', async () => {
    const cli = version.cliVersion();
    return {
      app: version.appVersion(),
      // 화면에는 0.1.0 만 띄운다. 빌드 해시(+0487c3...)는 넥슨이 재빌드할 때마다 바뀌는
      // 값이라 사용자에게는 잡음이다. 필요한 사람만 보라고 툴팁으로만 남긴다.
      cliVersion: cli ? version.semverOf(cli.productVersion) : null,
      cliFull: cli ? cli.productVersion : null,
      cliPath: connector.resolveExe(),
    };
  });

  // 검사 전에 게임에서 최신 명령 목록을 받아온다 (게임이 꺼져 있으면 캐시본을 쓴다)
  ipcMain.handle('version:check', async (_e, refresh) => {
    if (refresh) {
      try { await connector.refreshCapabilities(); } catch (_) { /* 오프라인이면 캐시본으로 검사 */ }
    }
    return version.check();
  });

  ipcMain.handle('version:accept', async (_e, note) => {
    try { await connector.refreshCapabilities(); } catch (_) { /* 위와 동일 */ }
    const saved = version.saveBaseline(version.fingerprint(), note || '');
    return { ok: true, baseline: saved };
  });

  // 루틴
  ipcMain.handle('routines:list', async () =>
    routines.listRoutines().map((r) => ({
      id: r.id,
      name: r.name,
      description: r.description || '',
      steps: routines.expand(r).length,
      wings: routines.estimateCost(r).wings,
    }))
  );

  ipcMain.handle('routines:run', async (_e, id, opts) => {
    const routine = routines.loadRoutine(id);
    if (!routine) return { error: 'not_found' };
    const pre = await routines.preflight(routine, opts || {});
    if (!pre.ok) return { error: 'preflight', reasons: pre.reasons, cost: pre.cost, wings: pre.wings };

    const summary = await routines.run(routine, {
      onEvent: (ev) => {
        if (win) win.webContents.send('mm:routine-event', ev);
      },
      dryRun: opts && opts.dryRun,
    });
    notify(
      '모비 커넥터 리모콘 — ' + routine.name,
      summary.failCount === 0 ? '완료 · 날개 ' + summary.wingsSpent + ' 소모' : '실패 ' + summary.failCount + '건'
    );
    return { summary };
  });

  // 캐시
  ipcMain.handle('cache:list', async () => cache.list());
  ipcMain.handle('cache:clear', async (_e, command) => cache.clear(command));

  // 외부 링크
  ipcMain.handle('openExternal', async (_e, url) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
  });
}

/* ── 앱 생명주기 ────────────────────────────────────────────── */

// 인스턴스 하나만 띄운다. 두 번째 실행은 기존 창을 살린다.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      win.show();
      win.focus();
    }
  });

  app.whenReady().then(async () => {
    setupMenu();
    registerIpc();
    createWindow();
    await createTray();
  });

  app.on('window-all-closed', () => {
    // 트레이에 남아야 하므로 아무것도 하지 않는다.
  });

  app.on('before-quit', () => {
    quitting = true;
    if (currentAction) currentAction.cancel();
  });
}
