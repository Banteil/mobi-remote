'use strict';
/**
 * 새 판이 나왔는지 본다.
 *
 * GitHub 릴리즈 목록을 읽어 지금 쓰는 판보다 높은 것이 있으면 알려 주고, 사람이
 * 누르면 설치 파일을 받아 실행한다. 몰래 받아서 몰래 바꾸는 일은 하지 않는다 —
 * 게임을 켜 둔 채로 쓰는 프로그램이라, 언제 꺼질지는 사람이 정해야 한다.
 *
 * ── 왜 electron-updater 를 안 쓰나 ────────────────────────
 * 이 프로젝트는 런타임 의존성이 하나도 없다(dependencies: {}). 그 하나를 들이면
 * 딸려 오는 것이 예닐곱 개다. 여기서 필요한 것은 "목록을 읽고, 파일 하나를 받고,
 * 실행한다" 뿐이라 Node 가 이미 가진 https 로 끝난다.
 *
 * ── 무설치판은 어떻게 하나 ────────────────────────────────
 * 무설치판(portable)은 덮어쓸 자리를 우리가 알 수 없다. 그래서 그쪽은 받지 않고
 * 릴리즈 쪽을 열어 준다. 사람이 받아서 쓰던 파일을 바꾸면 된다.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');

const OWNER = 'Banteil';
const REPO = 'mobi-remote';
const API = 'https://api.github.com/repos/' + OWNER + '/' + REPO + '/releases/latest';
const PAGE = 'https://github.com/' + OWNER + '/' + REPO + '/releases/latest';

/** GitHub 는 User-Agent 가 없으면 403 을 준다. */
const UA = 'mobi-remote-updater';

/* ── 판 번호 견주기 ─────────────────────────────────────────── */

/** '2.1.0' 이나 'v2.1.0' 을 [2,1,0] 으로. 숫자가 아닌 꼬리는 버린다. */
function parts(v) {
  return String(v || '').replace(/^v/i, '').split('.').map((x) => parseInt(x, 10) || 0);
}

/** a 가 b 보다 높으면 양수. */
function cmp(a, b) {
  const x = parts(a), y = parts(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] || 0) - (y[i] || 0);
    if (d) return d;
  }
  return 0;
}

/* ── 받기 ───────────────────────────────────────────────────── */

function get(url, opts) {
  const o = Object.assign({ headers: { 'User-Agent': UA } }, opts || {});
  return new Promise((resolve, reject) => {
    const req = https.get(url, o, (res) => {
      // 릴리즈 파일은 S3 로 넘겨준다. 몇 번이고 따라간다.
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return resolve(get(res.headers.location, o));
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error('HTTP ' + res.statusCode));
      }
      resolve(res);
    });
    req.setTimeout(20000, () => req.destroy(new Error('시간 초과')));
    req.on('error', reject);
  });
}

async function getJson(url) {
  const res = await get(url);
  let body = '';
  for await (const chunk of res) body += chunk;
  return JSON.parse(body);
}

/* ── 확인 ───────────────────────────────────────────────────── */

/**
 * @param {string} current 지금 쓰는 판 (package.json 의 version)
 * @returns {{ok:boolean, newer:boolean, version?:string, notes?:string, url?:string, asset?:object, page:string, error?:string}}
 */
async function check(current) {
  try {
    const r = await getJson(API);
    const version = String(r.tag_name || '').replace(/^v/i, '');
    if (!version) return { ok: false, newer: false, page: PAGE, error: '릴리즈가 아직 없습니다' };

    // 설치 파일을 고른다. 이름은 electron-builder 가 짓는 대로다.
    const assets = Array.isArray(r.assets) ? r.assets : [];
    const setup = assets.find((a) => /setup\.exe$/i.test(a.name || ''));

    return {
      ok: true,
      newer: cmp(version, current) > 0,
      version: version,
      notes: r.body || '',
      url: r.html_url || PAGE,
      page: PAGE,
      asset: setup ? { name: setup.name, url: setup.browser_download_url, size: setup.size } : null,
    };
  } catch (err) {
    return { ok: false, newer: false, page: PAGE, error: err.message };
  }
}

/**
 * 설치 파일을 임시 폴더에 받는다. onProgress(받은바이트, 전체바이트) 로 진행을 알린다.
 *
 * 받다 만 파일을 실행하는 일이 없도록 **다 받은 뒤에** 제 이름으로 바꾼다.
 */
async function download(asset, onProgress) {
  const dir = path.join(os.tmpdir(), 'mobi-remote-update');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, asset.name);
  const tmp = file + '.part';

  const res = await get(asset.url);
  const total = Number(res.headers['content-length']) || asset.size || 0;
  let got = 0;

  await new Promise((resolve, reject) => {
    const out = fs.createWriteStream(tmp);
    res.on('data', (c) => {
      got += c.length;
      if (onProgress) onProgress(got, total);
    });
    res.on('error', reject);
    out.on('error', reject);
    out.on('finish', resolve);
    res.pipe(out);
  });

  if (total && got !== total) {
    try { fs.unlinkSync(tmp); } catch (_) { /* 지우기 실패는 넘긴다 */ }
    throw new Error('받다가 끊겼습니다 (' + got + '/' + total + ')');
  }

  try { fs.unlinkSync(file); } catch (_) { /* 전에 받은 것이 있으면 치운다 */ }
  fs.renameSync(tmp, file);
  return file;
}

module.exports = { check, download, cmp, PAGE, OWNER, REPO };
