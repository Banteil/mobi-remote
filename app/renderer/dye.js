'use strict';
/**
 * 염색 도우미 — 팔레트를 찾고 원하는 색이 어디 있는지 짚는다.
 *
 * ── 이 파일이 하는 일 ──────────────────────────────────────
 * 화면 픽셀만 읽는다. 게임에 아무것도 보내지 않고 CLI도 거치지 않는다 —
 * 리모콘의 다른 기능과 달리 커넥터와 무관한 별개 도구다.
 * 계산만 하고 화면에 그리지는 않는다. 그래야 게임 없이도 시험할 수 있다.
 *
 * ── 왜 src/ 가 아니라 여기 있나 ────────────────────────────
 * 화면 픽셀은 렌더러의 canvas 에만 있다. 한 장이 8MB 라 IPC 로 메인에 넘기면
 * 초당 몇 장도 못 보낸다. 그래서 **픽셀이 있는 쪽에서** 계산한다.
 * 파일도 여기 한 벌만 둔다 — 같은 로직을 두 곳에 두면 반드시 한쪽만 고치게 된다.
 * Node 로도 require 할 수 있어(이중 모드) 게임 없이 시험이 된다.
 *
 * ── 팔레트를 어떻게 찾나 ───────────────────────────────────
 * 염색 팔레트는 화면에서 유일하게 **채도가 높으면서 옆 픽셀과 색이 확 다른** 덩어리다.
 * 실측 (1920x1080 스크린샷, 20px 칸 기준 이웃 색차의 중앙값):
 *
 *   팔레트 안        19.4
 *   화면 나머지       0.1
 *   캐릭터 미리보기   0.2
 *   팔레트 테두리     3.3
 *
 * 100배 차이라 임계값 하나로 갈린다.
 *
 * ── 해상도에 기대지 않는다 ─────────────────────────────────
 * 처음 만든 것은 1920x1080 에서만 맞았다. 두 군데가 해상도에 묶여 있었기 때문이다.
 *
 *   · 이웃 픽셀을 **바로 옆**과 비교했다. 해상도가 올라가면 소용돌이가 더 많은 픽셀에
 *     퍼져 그려지므로 바로 옆 픽셀은 오히려 비슷해진다 — 신호가 사라진다.
 *     그래서 비교 간격을 화면 폭에 비례시킨다 (1920 기준 2px).
 *   · 최소 크기를 칸 수(100칸)로 고정했다. 작은 창에서는 그만한 칸이 안 나온다.
 *     그래서 짧은 변의 비율로 본다.
 *
 * 칸 크기도 폭에 비례시켜, 어느 해상도에서든 같은 수의 칸으로 훑는다.
 */

/* ── 색 ─────────────────────────────────────────────────────── */

/**
 * sRGB → CIE Lab (D65).
 *
 * RGB 거리로 "가까운 색"을 고르면 사람 눈과 어긋난다. 어두운 쪽에서는 큰 차이를 작게 보고,
 * 초록 언저리에서는 작은 차이를 크게 본다. Lab 은 수식 몇 줄이라 비용이 같은데 결과가 다르다.
 */
// 0~255 값은 256가지뿐이라 미리 구해 둔다. 픽셀마다 pow 를 세 번 부르는 것이
// 이 파일에서 가장 비싼 일이었다 (실측 — 이 표 하나로 탐색이 절반 아래로 떨어진다).
const LINEAR = new Float32Array(256);
for (let i = 0; i < 256; i++) {
  const v = i / 255;
  LINEAR[i] = v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
}

function toLab(r, g, b) {
  const R = LINEAR[r], G = LINEAR[g], B = LINEAR[b];
  let X = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047;
  let Y = (R * 0.2126 + G * 0.7152 + B * 0.0722);
  let Z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883;
  const k = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  X = k(X); Y = k(Y); Z = k(Z);
  return [116 * Y - 16, 500 * (X - Y), 200 * (Y - Z)];
}

/** "#RRGGBB" → [r,g,b]. 잘못된 값이면 null. */
function hexToRgb(s) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(s || '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, '0')).join('').toUpperCase();
}

/**
 * 두 색의 차이 (CIE76).
 * 2 이하면 거의 구분 못 하고, 5 이하면 비슷하며, 10을 넘으면 다른 색이다.
 */
function deltaE(labA, labB) {
  const dL = labA[0] - labB[0], da = labA[1] - labB[1], db = labA[2] - labB[2];
  return Math.sqrt(dL * dL + da * da + db * db);
}

/**
 * 화면에서 읽은 색을 목표로 삼을 수 있게 정리한다.
 *
 * 허용 오차는 **색마다** 갖고 다닌다. 머리색처럼 딱 맞아야 하는 것과 배경처럼 비슷하면
 * 되는 것이 한 조합 안에 섞이는데, 기준이 하나면 한쪽에 다른 쪽이 끌려간다.
 */
function target(hex, tol) {
  const rgb = hexToRgb(hex);
  if (!rgb) return null;
  return {
    hex: rgbToHex(rgb[0], rgb[1], rgb[2]),
    rgb: rgb,
    lab: toLab(rgb[0], rgb[1], rgb[2]),
    tol: typeof tol === 'number' ? tol : undefined,
  };
}

/* ── 프레임 ─────────────────────────────────────────────────── */

/**
 * 캡처한 한 장. 픽셀은 BGRA 순서다 (nativeImage.toBitmap, canvas 는 RGBA 라 order 로 구분).
 * @param order 'bgra' | 'rgba'
 */
function frame(buf, w, h, order) {
  const bgr = order !== 'rgba';
  return {
    buf: buf, w: w, h: h,
    r: bgr ? 2 : 0,
    b: bgr ? 0 : 2,
  };
}

/** 해상도가 달라도 같은 것을 보도록, 1920 기준 값을 폭에 맞춰 늘린다. */
function scaleOf(f) {
  return Math.max(1, Math.round(f.w / 960));   // 1920 → 2
}

/* ── 팔레트 찾기 ─────────────────────────────────────────────── */

const DIFF_MIN = 4;      // 팔레트 안 19.4 / 바깥 0.1~0.2

/**
 * 칸이 "색이 있다"고 볼 최소 채도.
 *
 * 한때 0.20 이었다. **틀렸다.** 팔레트는 온통 회색일 수도 있다 — 실측한 화면 하나는
 * 왼쪽 2/3 이 회색 소용돌이라 그 칸의 80% 가 0.20 을 못 넘었고, 알록달록한 오른쪽
 * 1/3 만 덩어리로 잡혀 280x750 이 되어 탈락했다.
 *
 * 채도로는 팔레트와 게임 UI 를 **가를 수 없다**. 오히려 가짜가 더 높다.
 *
 *   회색 팔레트 0.14   알록 팔레트 0.41   아이템 패널 0.43   평범한 게임 화면 0.39
 *
 * 그래서 여기는 "새까맣지만 않으면 된다" 수준으로만 남기고, 진짜 판별은 이웃 색차와
 * 어두운 비율, 테두리, 크기, 정사각형 여부에 맡긴다.
 */
const SAT_MIN = 0.06;

/**
 * 팔레트로 보이는 사각형을 찾는다. 못 찾으면 null.
 *
 * @returns {{x,y,w,h,fill,ratio}} fill = 덩어리가 사각형을 채운 비율, ratio = 가로/세로
 */
/**
 * @param opts.exclude [{x,y,w,h}] 이 사각형들 안은 보지 않는다.
 *   우리 앱 창이 들어간다 — 히트맵과 색 견본이 팔레트만큼 알록달록해서,
 *   빼 주지 않으면 앱 창과 팔레트가 한 덩어리로 붙어 엉뚱한 사각형이 나온다 (실측).
 */
function detectPalette(f, opts) {
  const o = opts || {};
  const step = scaleOf(f);
  const cell = Math.max(8, step * 10);              // 1920 → 20px
  const cx = Math.floor(f.w / cell), cy = Math.floor(f.h / cell);
  if (cx < 4 || cy < 4) return null;

  const on = new Uint8Array(cx * cy);
  const { buf, w, r: RI, b: BI } = f;

  // 제외 구역을 칸 단위로 미리 칠해 둔다
  const skip = new Uint8Array(cx * cy);
  for (const e of (o.exclude || [])) {
    if (!e) continue;
    const gx0 = Math.max(0, Math.floor(e.x / cell)), gx1 = Math.min(cx - 1, Math.floor((e.x + e.w) / cell));
    const gy0 = Math.max(0, Math.floor(e.y / cell)), gy1 = Math.min(cy - 1, Math.floor((e.y + e.h) / cell));
    for (let gy = gy0; gy <= gy1; gy++) for (let gx = gx0; gx <= gx1; gx++) skip[gy * cx + gx] = 1;
  }

  for (let gy = 0; gy < cy; gy++) {
    for (let gx = 0; gx < cx; gx++) {
      const bx = gx * cell, by = gy * cell;
      let sat = 0, diff = 0, n = 0, dn = 0;
      for (let y = by; y < by + cell; y += step) {
        for (let x = bx; x < bx + cell; x += step) {
          const i = (y * w + x) * 4;
          const rr = buf[i + RI], gg = buf[i + 1], bb = buf[i + BI];
          const mx = Math.max(rr, gg, bb), mn = Math.min(rr, gg, bb);
          sat += mx ? (mx - mn) / mx : 0;
          n++;
          if (x + step < bx + cell) {
            const j = i + 4 * step;
            diff += (Math.abs(buf[j + RI] - rr) + Math.abs(buf[j + 1] - gg) + Math.abs(buf[j + BI] - bb)) / 3;
            dn++;
          }
        }
      }
      on[gy * cx + gx] = (!skip[gy * cx + gx] && dn && diff / dn >= DIFF_MIN && sat / n >= SAT_MIN) ? 1 : 0;
    }
  }

  // 팔레트 안에도 넓은 단색 소용돌이가 있어 몇 칸은 빠진다. 사방이 차 있으면 메운다.
  const fill = Uint8Array.from(on);
  for (let gy = 1; gy < cy - 1; gy++) {
    for (let gx = 1; gx < cx - 1; gx++) {
      const i = gy * cx + gx;
      if (on[i] || skip[i]) continue;
      let around = 0;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) around += on[(gy + dy) * cx + (gx + dx)];
      if (around >= 3) fill[i] = 1;
    }
  }

  const best = bestBlob(fill, cx, cy);
  if (!best) return null;

  // 지시선이나 말풍선처럼 가늘게 삐져나온 것이 경계를 부풀린다.
  // 줄마다 채워진 비율을 보고, 절반도 안 차는 줄은 경계에서 잘라 낸다.
  let { x0, y0, x1, y1 } = best;
  const rowFill = (y) => { let c = 0; for (let x = x0; x <= x1; x++) c += fill[y * cx + x]; return c / (x1 - x0 + 1); };
  const colFill = (x) => { let c = 0; for (let y = y0; y <= y1; y++) c += fill[y * cx + x]; return c / (y1 - y0 + 1); };
  // 가장자리를 자를 때 0.5 는 너무 매서웠다. 팔레트 안에도 넓은 단색 소용돌이가 있어서
  // 멀쩡한 줄이 잘려 나간다 (실측 — 755px 팔레트가 380px 로 줄었다).
  while (y0 < y1 && rowFill(y0) < 0.3) y0++;
  while (y1 > y0 && rowFill(y1) < 0.3) y1--;
  while (x0 < x1 && colFill(x0) < 0.3) x0++;
  while (x1 > x0 && colFill(x1) < 0.3) x1--;

  // 자른 뒤, 바깥쪽이 아직 어느 정도 차 있으면 다시 넓힌다. 자르기는 튀어나온 지시선을
  // 떼려는 것이지 팔레트를 깎으려는 것이 아니다.
  while (y0 > best.y0 && rowFill(y0 - 1) >= 0.2) y0--;
  while (y1 < best.y1 && rowFill(y1 + 1) >= 0.2) y1++;
  while (x0 > best.x0 && colFill(x0 - 1) >= 0.2) x0--;
  while (x1 < best.x1 && colFill(x1 + 1) >= 0.2) x1++;

  let filled = 0;
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) filled += fill[y * cx + x];

  const box = {
    x: x0 * cell, y: y0 * cell,
    w: (x1 - x0 + 1) * cell, h: (y1 - y0 + 1) * cell,
  };
  box.fill = filled / ((x1 - x0 + 1) * (y1 - y0 + 1));
  box.ratio = box.w / box.h;

  // 팔레트는 화면에서 아주 큰 물건이다. 짧은 변 대비 실측 — 1920x1080 에서 749px 니까
  // 0.694, 잘라 낸 그림에서는 0.966. 반면 염색할 옷을 고르는 화면의 아이콘 뭉치는
  // 0.259 였다. 0.40 에 선을 그으면 진짜는 1.7배 여유로 통과하고 아이콘 뭉치는 걸린다.
  const minSide = Math.min(f.w, f.h) * (o.minSide || 0.40);
  if (box.w < minSide || box.h < minSide) return null;
  if (box.fill < (o.minFill || 0.45)) return null;
  // 팔레트는 거의 정사각형이다. 1.5:1 같은 것은 팔레트가 아니라 무언가 붙은 것이다.
  if (box.ratio < 0.75 || box.ratio > 1.33) return null;

  // 색만으로 잡은 경계는 실제 팔레트보다 넓다. 어두운 테두리를 찾아 다듬는다.
  //
  // 테두리를 못 찾으면 **팔레트가 아니다.** 예전에는 색으로 잡은 사각형을 그대로 썼는데,
  // 그래서 길드홀 같은 평범한 게임 화면에서도 "팔레트 감지"가 떴다 (실측 — 600,0 620x760).
  // 팔레트는 테두리 있는 상자라는 것이 그 물건의 정의다. 없으면 없는 것이다.
  const edged = snapToBorder(f, box, minSide);
  if (!edged) return null;

  // 마지막으로 그 안이 정말 소용돌이인지 본다. 테두리 비슷한 것을 우연히 찾을 수는 있어도,
  // 안쪽까지 소용돌이일 수는 없다.
  //
  // 실측 — 진짜 팔레트 안쪽의 이웃 색차
  //          알록달록 37.0 / 28.7 / 22.6,  온통 회색인 것도 26.3 (그 중 회색 부분만 22.0)
  //        잘못 잡은 것
  //          평범한 게임 화면 12.8,  아이템 고르는 판 14.2
  //        → 18 에 선을 긋는다.
  //
  // ── 어두운 곳이 얼마나 되는가 ──────────────────────────
  // 이게 가장 잘 갈린다. 팔레트는 색상환이 네모를 꽉 채우므로 **안에 어두운 자리가
  // 거의 없다**. 게임 UI 판은 무엇이든 어두운 바탕 위에 물건을 얹은 것이라 반대다.
  //
  // 실측 (밝기 60 미만인 자리의 비율)
  //   진짜 팔레트      1% / 1% / 2% / 2% / 2%
  //   아이템 패널 전체 62%   아이콘 격자 49%   아이콘 3x3 42%   아이콘 한 칸 15%
  const tex = texture(f, edged);
  // 채도는 보지 않는다 — 위 SAT_MIN 에 적어 둔 대로, 진짜가 가짜보다 낮을 수 있다.
  if (tex.diff < 18) return null;
  if (tex.dark > (o.maxDark || 0.12)) return null;
  edged.texture = tex;
  return edged;
}

/** 사각형 안이 얼마나 알록달록하고 잘게 변하는가. 팔레트인지 가리는 마지막 관문. */
function texture(f, b) {
  const { buf, w, r: RI, b: BI } = f;
  // 비교 간격은 **상자 크기**에 맞춘다. 화면 폭에 맞추면, 같은 팔레트인데도 잘라 낸
  // 그림에서는 간격이 절반이 되어 색차가 낮게 나온다 (실측 — 749px 팔레트가 전체 화면에서
  // 37.0, 잘라 낸 839px 그림에서 15.7. 기준 18 에 걸려 멀쩡한 팔레트를 놓쳤다).
  const step = Math.max(2, Math.round(Math.min(b.w, b.h) / 190));
  let sat = 0, diff = 0, dark = 0, n = 0, dn = 0;
  for (let y = b.y; y < b.y + b.h; y += step) {
    for (let x = b.x; x < b.x + b.w - step; x += step) {
      const i = (y * w + x) * 4, j = i + 4 * step;
      const rr = buf[i + RI], gg = buf[i + 1], bb = buf[i + BI];
      const mx = Math.max(rr, gg, bb), mn = Math.min(rr, gg, bb);
      sat += mx ? (mx - mn) / mx : 0;
      if (mx < DIM_MAX) dark++;
      n++;
      diff += (Math.abs(buf[j + RI] - rr) + Math.abs(buf[j + 1] - gg) + Math.abs(buf[j + BI] - bb)) / 3;
      dn++;
    }
  }
  return { sat: n ? sat / n : 0, diff: dn ? diff / dn : 0, dark: n ? dark / n : 0 };
}

/* ── 어두운 테두리로 경계 맞추기 ─────────────────────────────── */

const DARK_MAX = 70;        // 이보다 어두우면 테두리 후보
const DARK_RATIO = 0.75;    // 그 줄의 이 비율 이상이 어두우면 테두리
const DIM_MAX = 60;         // 상자 속을 볼 때, 이보다 어두우면 "배경"으로 센다

/* 게임의 색 선택 UI — 흰 지시선과 그 끝의 동그라미 */
/**
 * UI 흰색 판정.
 *
 * 이 UI 는 **순백**으로 그려져 있다. 반면 소용돌이의 "희끄무레한" 줄기는 순백이 아니다.
 * 기준을 조이면 둘이 깨끗하게 갈린다.
 *
 *   기준 200/22   지시선 통과 100%   팔레트(UI 제외) 통과 1.2~2.1%
 *   기준 248/6    지시선 통과 100%   팔레트(UI 제외) 통과 0.00~0.01%
 *
 * 느슨하면 **흰 테와 그 안쪽 색이 구분되지 않는다.** 고른 색이 흰 계열일 때 동그라미
 * 측정이 통째로 어긋나 가림막이 아예 안 생겼다.
 */
const WHITE_MIN = 248;
const WHITE_TINT = 6;
const LEADER_WIDE = 20;     // 이보다 굵으면 지시선이 아니다 (실측 4~5px)
const LEADER_PAD = 3;       // 가장자리 번짐 여유
const RING_REACH = 20;      // 동그라미를 찾을 때 좌우로 이만큼까지 본다
const RING_LOOK = 40;       // 넓어지기 시작한 곳에서 이만큼 아래까지 복판을 찾는다
const RING_MIN = 8;         // 바깥 반지름이 이보다 작으면 동그라미가 아니다
const RING_MAX = 25;        // 이보다 크면 무언가 섞인 것이다 (실측 13~15)
const RING_SHARE = 0.5;     // 안쪽에서 으뜸 색이 이만큼은 돼야 믿는다 (커서가 덮었나)
const RING_INK = 7;         // 바깥 반지름에서 이만큼 안쪽까지가 색 칠해진 부분 (테 5 + 여유 2)

/* 염색이 끝났을 때 뜨는 확정 단추 — 한 색으로 꽉 찬 초록 면 */
const DONE_RGB = [13, 179, 118];
const DONE_TOL = 24;        // 세 채널 차이의 합
const RING_PAD = 5;         // 동그라미 둘레 여유 — 섞인 가장자리까지 덮는다
const LEADER_GAP = 4;       // 이만큼까지 끊겨도 같은 선으로 본다

/**
 * 색으로 잡은 사각형을, 팔레트의 **어두운 테두리**에 맞춰 다듬는다.
 *
 * ── 왜 필요한가 ──────────────────────────────────────────
 * 소용돌이는 팔레트 상자 **바깥에도 깔려 있다.** 상자는 그 위에 얹힌 창일 뿐이라,
 * "알록달록한 곳"만 찾으면 배경까지 함께 잡혀 실제보다 크게 나온다
 * (실측 — 755px 팔레트가 1000px 로 잡혔다).
 *
 * 상자에는 두꺼운 **거의 검은 테두리**가 있고, 그것이 진짜 경계다.
 * 실측 (1920x1080) — 세로 테두리 줄의 어두운 비율 **100%**, 안쪽은 0~8%.
 *
 * ── 어떻게 찾나 ──────────────────────────────────────────
 * 한가운데에서 바깥으로 한 줄씩 나가다가 처음 만나는 어두운 줄이 테두리다.
 * 가운데를 가로지르므로 둥근 모서리에 걸리지 않고, 바깥의 어두운 배경보다
 * **안쪽 테두리를 먼저** 만나므로 배경과 헷갈리지도 않는다.
 */
/**
 * 색으로 잡은 경계를 실제 테두리에 맞춘다.
 *
 * @param minSide  이보다 작은 네모는 팔레트가 아니다. 안 주면 40px.
 *                 테두리를 안쪽에서 찾으면 큰 덩어리가 작은 네모로 줄어들 수 있다 —
 *                 아이콘 격자처럼 **칸 사이가 다 어두운** 화면에서 특히 그렇다.
 *                 그래서 줄인 뒤에도 크기를 다시 본다.
 */
function snapToBorder(f, box, minSide) {
  const { buf, w, r: RI, b: BI } = f;
  const isDark = (x, y) => {
    const i = (y * w + x) * 4;
    return Math.max(buf[i + RI], buf[i + 1], buf[i + BI]) < DARK_MAX;
  };

  const cx = box.x + (box.w >> 1), cy = box.y + (box.h >> 1);
  // 가운데 60% 구간만 본다. 끝자락은 둥근 모서리라 어차피 어둡다.
  const bandY0 = Math.round(box.y + box.h * 0.2), bandY1 = Math.round(box.y + box.h * 0.8);
  const bandX0 = Math.round(box.x + box.w * 0.2), bandX1 = Math.round(box.x + box.w * 0.8);
  const stepY = Math.max(1, Math.round((bandY1 - bandY0) / 40));
  const stepX = Math.max(1, Math.round((bandX1 - bandX0) / 40));

  const colDark = (x) => {
    let c = 0, n = 0;
    for (let y = bandY0; y < bandY1; y += stepY) { if (isDark(x, y)) c++; n++; }
    return n ? c / n : 0;
  };
  const rowDark = (y) => {
    let c = 0, n = 0;
    for (let x = bandX0; x < bandX1; x += stepX) { if (isDark(x, y)) c++; n++; }
    return n ? c / n : 0;
  };

  // 가운데에서 바깥으로. 사각형 크기의 60% 밖까지는 안 나간다 — 못 찾으면 포기.
  const reach = Math.round(Math.max(box.w, box.h) * 0.6);
  const scan = (from, dir, limit, probe) => {
    for (let k = 1; k < reach; k++) {
      const v = from + dir * k;
      if (v < 1 || v > limit - 2) return null;
      if (probe(v) >= DARK_RATIO) return v;
    }
    return null;
  };

  const left = scan(cx, -1, f.w, colDark);
  const right = scan(cx, 1, f.w, colDark);
  const top = scan(cy, -1, f.h, rowDark);
  const bottom = scan(cy, 1, f.h, rowDark);
  if (left === null || right === null || top === null || bottom === null) return null;

  const out = { x: left, y: top, w: right - left, h: bottom - top };
  const min = Math.max(40, minSide || 0);
  if (out.w < min || out.h < min) return null;
  out.ratio = out.w / out.h;
  if (out.ratio < 0.8 || out.ratio > 1.25) return null;
  out.fill = box.fill;
  out.snapped = true;
  return out;
}

/**
 * 팔레트다운 덩어리를 고른다.
 *
 * 예전에는 무조건 가장 큰 것을 골랐다. 그러다 우리 앱 창과 팔레트가 붙은 덩어리를
 * 집어서 엉뚱한 사각형이 나왔다. 팔레트는 **거의 정사각형**이라, 크기에 네모반듯한
 * 정도를 곱해서 고른다. 붙어서 길쭉해진 덩어리는 그만큼 점수가 깎인다.
 */
function bestBlob(on, cx, cy) {
  const seen = new Uint8Array(cx * cy);
  let best = null;
  for (let i = 0; i < on.length; i++) {
    if (!on[i] || seen[i]) continue;
    const st = [i]; seen[i] = 1;
    let n = 0, x0 = cx, y0 = cy, x1 = -1, y1 = -1;
    while (st.length) {
      const p = st.pop(); n++;
      const px = p % cx, py = (p / cx) | 0;
      if (px < x0) x0 = px;
      if (px > x1) x1 = px;
      if (py < y0) y0 = py;
      if (py > y1) y1 = py;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nx = px + dx, ny = py + dy;
        if (nx < 0 || ny < 0 || nx >= cx || ny >= cy) continue;
        const q = ny * cx + nx;
        if (on[q] && !seen[q]) { seen[q] = 1; st.push(q); }
      }
    }
    const bw = x1 - x0 + 1, bh = y1 - y0 + 1;
    const square = Math.min(bw, bh) / Math.max(bw, bh);   // 1이면 정사각형
    const score = n * square * square;
    if (!best || score > best.score) best = { n, x0, y0, x1, y1, score };
  }
  return best;
}

/* ── 색 찾기 ─────────────────────────────────────────────────── */

/**
 * 목표색마다 가장 가까운 지점을 찾는다.
 *
 * 2픽셀씩 건너뛰어도 결과가 거의 같다 (실측 — 전수 158ms ΔE 0.4 / 2px 37ms ΔE 0.8).
 * 그래서 기본은 건너뛰기고, 찾은 자리 주변만 원해상도로 다시 본다.
 *
 * @returns 목표마다 {hex, found, x, y, color, delta} — found 는 tolerance 안에 들었는지
 */
/**
 * 게임의 색 선택 UI 를 찾아, 색을 볼 때 건너뛸 자리를 돌려준다.
 *
 * 팔레트 위쪽에서 **흰 선이 곧게 내려와 작은 동그라미로 한 점을 가리킨다.** 염색 파트
 * 수만큼 1~3개 뜨고, 가로 자리는 파트 수에 따라 고정, 세로(동그라미) 자리는 시도할 때마다
 * 다르다. 팔레트를 돌리고 옮겨서 저 동그라미 아래에 원하는 색을 갖다 대는 것이 이 게임의
 * 염색 방식이다.
 *
 * 이 선은 **팔레트 색이 아니다.** 흰색을 목표로 잡으면 선을 따라 점이 줄줄이 찍힌다.
 *
 * 실측 (팔레트 749x749, 파트 3개)
 *   선의 가로 자리   폭 대비 0.167 / 0.500 / 0.833  (= 1/6, 3/6, 5/6)
 *   선 굵기          4~5px
 *   동그라미 지름    안쪽 18~19 · 바깥 27~28 (흰 테 두께 5)
 *
 * 자리를 붙박이로 적어 두지 않고 매번 찾는다 — 파트 수가 바뀌면 자리도 바뀌고,
 * 찾는 값이 워낙 뚜렷해서 굳이 기댈 이유가 없다.
 *
 * 돌려주는 것은 두 가지다 — 건너뛸 네모들(skip)과, 동그라미의 자리·크기·안쪽 색(rings).
 * 안쪽 색은 **그 파트가 지금 고른 색** 그 자체다. 게임이 위 딱지에 적어 두는 그 값이다.
 *
 * 선은 **가는 띠로 세로 전체**를, 동그라미는 **그 자리만 네모로** 지운다. 통째로 넓게
 * 지우면 팔레트의 13% 가 날아간다 — 동그라미는 한 줄에만 있으므로 거기만 도려낸다.
 */
function findLeaders(f, box) {
  const { buf, w, r: RI, b: BI } = f;
  const isWhite = (x, y) => {
    const i = (y * w + x) * 4;
    const rr = buf[i + RI], gg = buf[i + 1], bb = buf[i + BI];
    const mx = Math.max(rr, gg, bb), mn = Math.min(rr, gg, bb);
    return mn >= WHITE_MIN && mx - mn <= WHITE_TINT;
  };

  // 맨 위에서 아래로, 끊기지 않고 흰 줄이 몇 개나 이어지는가.
  // 소용돌이에도 흰 줄기가 있지만 휘어 있어서 같은 칸에 오래 머물지 못한다.
  const band = Math.max(24, Math.round(Math.min(box.h * 0.16, 160)));
  const need = Math.round(band * 0.7);
  const run = new Int32Array(box.w);
  for (let dx = 0; dx < box.w; dx++) {
    let c = 0, miss = 0;
    for (let dy = 2; dy < band; dy++) {
      if (isWhite(box.x + dx, box.y + dy)) { c++; miss = 0; continue; }
      // 몇 줄쯤 끊겨도 같은 선으로 본다. 우리가 그린 표시가 지나가거나 가장자리가
      // 번지면 한두 줄이 빠진다 — 그 한 줄 때문에 선을 통째로 놓치면 안 된다.
      if (++miss > LEADER_GAP) break;
    }
    run[dx] = c;
  }

  const lines = [];
  let st = -1;
  for (let dx = 0; dx <= box.w; dx++) {
    const on = dx < box.w && run[dx] >= need;
    if (on && st < 0) st = dx;
    if (!on && st >= 0) {
      if (dx - st <= LEADER_WIDE) lines.push({ a: st, z: dx - 1 });
      st = -1;
    }
  }
  // 파트는 많아야 셋이다. 더 잡혔으면 굵은 것부터 셋만 남긴다.
  if (lines.length > 3) {
    lines.sort((p, q) => (q.z - q.a) - (p.z - p.a));
    lines.length = 3;
  }
  lines.sort((p, q) => p.a - q.a);

  // ── 놓친 선 채우기 ────────────────────────────────────
  // 가로 자리는 파트 수에 따라 붙박이다 — n개면 (2k+1)/2n 자리에 고르게 선다.
  // 실측으로 3개짜리가 0.167 / 0.500 / 0.833 (= 1/6, 3/6, 5/6) 이었다.
  //
  // 그래서 하나만 확실히 찾아도 나머지 자리를 안다. 선 위로 무언가 지나가 한 개를
  // 놓치는 일이 실제로 있었다 — 그때 그 자리만 그대로 남아 점이 줄줄이 찍힌다.
  //
  // 들어맞는 **가장 작은 n** 을 고른다. 선 하나가 한가운데 있으면 n=1 로 보고 아무것도
  // 더하지 않는다 — n=3 의 가운데일 수도 있지만, 없는 선을 지어내는 쪽이 더 나쁘다.
  const ratio = (g) => ((g.a + g.z) / 2) / box.w;
  const wideOf = lines.length ? Math.round(lines.reduce((a, g) => a + (g.z - g.a + 1), 0) / lines.length) : 5;
  for (let n = 1; n <= 3 && lines.length; n++) {
    const slots = [];
    for (let k = 0; k < n; k++) slots.push((2 * k + 1) / (2 * n));
    const fits = lines.every((g) => slots.some((v) => Math.abs(ratio(g) - v) < 0.025));
    if (!fits || n < lines.length) continue;
    for (const v of slots) {
      if (lines.some((g) => Math.abs(ratio(g) - v) < 0.025)) continue;
      const c = Math.round(box.w * v);
      lines.push({ a: c - (wideOf >> 1), z: c - (wideOf >> 1) + wideOf - 1, guessed: true });
    }
    break;
  }
  lines.sort((p, q) => p.a - q.a);

  const skip = [];
  const rings = [];
  for (const g of lines) {
    const cx = box.x + ((g.a + g.z) >> 1);
    const wide = g.z - g.a + 1;
    skip.push({ x: box.x + g.a - LEADER_PAD, y: box.y, w: wide + LEADER_PAD * 2, h: box.h });

    // ── 스포이드 동그라미 ────────────────────────────────
    // 선을 따라 내려가다 **가로로 가장 넓게 퍼지는 줄**이 동그라미 복판이다.
    //
    // 가운데 칸이 흰지로 따라가면 안 된다. 테 안쪽은 고른 색으로 차 있어서 흰색이 아니고,
    // 그러면 테의 윗머리에서 멈춘다. 대신 **좌우 ±20 안에 흰 점이 하나라도 있으면** 계속
    // 따라가고, 줄마다 그 흰 점들의 가장 왼쪽~가장 오른쪽 폭을 잰다. 속이 비었든 찼든
    // 복판에서 폭이 최대가 된다.
    //
    // 이 방법은 흰색 기준이 빡빡해야 쓸 수 있다. 느슨하면 옆 소용돌이의 흰 줄기가 폭에
    // 섞여 들어와 지름이 55px 로 튀었다.
    //
    // 실측 — 바깥 지름 27~28, 테 두께 5
    const extent = (y) => {
      let l = 99, r = -99;
      for (let dx = -RING_REACH; dx <= RING_REACH; dx++) {
        const x = cx + dx;
        if (x < box.x || x >= box.x + box.w || !isWhite(x, y)) continue;
        if (dx < l) l = dx;
        if (dx > r) r = dx;
      }
      return r < l ? 0 : r - l + 1;
    };

    // 선을 따라 내려가 흰색이 마지막으로 보이는 줄. 동그라미를 못 쟀을 때 그 언저리로 삼는다.
    const lastWhite = (x) => {
      let seen = box.y + 2, gap = 0;
      for (let y = box.y + 2; y < box.y + box.h - 2; y++) {
        if (extent(y)) { seen = y; gap = 0; continue; }
        if (++gap > LEADER_GAP * 3) break;
      }
      return seen;
    };

    let grow = -1, miss = 0;
    for (let y = box.y + 2; y < box.y + box.h - 2; y++) {
      const e = extent(y);
      if (!e) { if (grow >= 0 || miss > LEADER_GAP) { if (grow >= 0) break; } miss++; continue; }
      miss = 0;
      if (e > wide + 6) { grow = y; break; }
    }
    // 넓어지는 자리를 못 찾아도 동그라미는 **반드시 있다.** 선 끝에 달려 있으니까.
    // 못 찾은 채로 넘어가면 그 프레임에서 흰 테가 통째로 노출돼 색으로 잡힌다.
    if (grow < 0) grow = lastWhite(cx);

    // 복판은 **가장 넓은 한 줄**이 아니라 **넓은 줄들이 이어진 구간의 한가운데**다.
    // 한 줄만 보면 소용돌이가 한 픽셀 스쳐도 그쪽으로 끌려간다 — 실제로 표시가 동그라미
    // 에서 반쯤 어긋나는 일이 있었다. 구간으로 보면 위아래 오차가 서로 상쇄된다.
    let last = -1, peak = 0;
    for (let y = grow; y <= grow + RING_LOOK && y < box.y + box.h; y++) {
      const e = extent(y);
      if (e <= wide + 6) break;
      last = y;
      if (e > peak) peak = e;
    }
    if (last < 0) last = grow;
    const cy = Math.round((grow + last) / 2);
    // 세로 길이와 가로 폭 중 큰 쪽을 지름으로 본다. 위아래 끝의 얇은 호는 기준에 못 미쳐
    // 잘려 나가므로 세로가 조금 짧게 나온다.
    // 잰 값이 이상해도 **버리지 않고 가둔다.** 배경이 밝으면 흰 테가 주변 소용돌이와
    // 이어져 지름이 터무니없이 크게 나오는데, 그때 버리면 테가 그대로 노출된다.
    // 엉뚱한 크기로 가리는 것이 안 가리는 것보다 낫다.
    let outR = Math.round(Math.max(last - grow + 1, peak) / 2);
    if (!(outR >= RING_MIN && outR <= RING_MAX)) outR = defaultRingR(box);

    const seen = ringColor(f, { x: cx, y: cy, r: outR });
    if (!seen) continue;
    rings.push({ x: cx, y: cy, r: outR, rgb: seen.rgb, share: seen.share });
    // 가장자리는 배경과 섞여 흐릿하다 — 실측으로 바깥 반지름 +1~2px 까지 흰기가 남는다.
    // 동그라미는 동그랗게 가린다. 네모로 가리면 모서리 네 곳이 공연히 지워진다.
    skip.push({ cx: cx, cy: cy, r: outR + RING_PAD });
  }
  return { skip: skip, rings: rings };
}

/**
 * 동그라미 안쪽 색.
 *
 * 안쪽은 **한 가지 색으로 칠해진 원**이다. 그런데 게임 마우스 커서(흰 화살표)가 그 위를
 * 지나가면 안을 덮는다. 평균을 내면 색이 흰쪽으로 끌려가고, 심하면 아예 다른 색이 된다.
 *
 * 그래서 평균 대신 **가장 많은 색**을 고른다. 커서가 절반 넘게 덮지 않는 한 진짜 색이
 * 이긴다. 그마저 넘으면 share 가 떨어지고, 그때는 호출 쪽이 직전 값을 그대로 쓴다.
 */
function ringColor(f, ring) {
  const { buf, w, h, r: RI, b: BI } = f;
  const rad = Math.max(2, ring.r - RING_INK);
  const count = new Map();
  let n = 0, bestKey = -1, bestN = 0;
  for (let dy = -rad; dy <= rad; dy++) {
    for (let dx = -rad; dx <= rad; dx++) {
      if (dx * dx + dy * dy > rad * rad) continue;
      const x = ring.x + dx, y = ring.y + dy;
      if (x < 0 || y < 0 || x >= w || y >= h) continue;
      const i = (y * w + x) * 4;
      const key = (buf[i + RI] << 16) | (buf[i + 1] << 8) | buf[i + BI];
      const c = (count.get(key) || 0) + 1;
      count.set(key, c);
      n++;
      if (c > bestN) { bestN = c; bestKey = key; }
    }
  }
  if (!n || bestKey < 0) return null;
  return {
    rgb: [(bestKey >> 16) & 255, (bestKey >> 8) & 255, bestKey & 255],
    share: bestN / n,
  };
}

/**
 * 이미 찾아 둔 동그라미의 **안쪽 색만** 다시 읽는다.
 *
 * 색 선택 UI 는 화면에 붙박이다 — 움직이는 것은 그 아래 팔레트다. 그러니 자리를 매번
 * 다시 찾을 이유가 없고, 다시 찾으면 프레임마다 한두 픽셀씩 떨리기만 한다.
 * 자리는 고정해 두고 색만 새로 읽는다.
 */
function readRings(f, rings) {
  return rings.map((ring) => {
    const seen = ringColor(f, ring);
    // 커서에 가려 무슨 색인지 못 믿겠으면 직전 값을 그대로 쓴다.
    // 안쪽은 원래 한 가지 색이므로, 그 색이 절반도 안 되면 무언가 덮고 있는 것이다.
    if (!seen || seen.share < RING_SHARE) return ring;
    return { x: ring.x, y: ring.y, r: ring.r, rgb: seen.rgb, share: seen.share };
  });
}

/**
 * 염색이 끝났을 때 뜨는 **염색 확정** 단추를 찾는다. 찾으면 염색 도우미를 끌 때다.
 *
 * ── 왜 초록만으로는 안 되나 ────────────────────────────
 * 염색 화면에도 같은 초록 단추가 있다 — "이대로 염색하기". 색이 똑같으니 색으로는 못
 * 가른다. 다행히 **크기와 자리**가 확연히 다르다.
 *
 *   이대로 염색하기   폭 748 (화면의 0.39)   한가운데 x 0.255
 *   염색 확정         폭 350 (화면의 0.18)   한가운데 x 0.565   높이 76 (0.07)
 *
 * 단추는 **한 색으로 꽉 찬 면**이라 소용돌이와 헷갈릴 일은 없다. 팔레트의 초록은 픽셀마다
 * 값이 달라서 같은 색이 수백 픽셀 이어지지 않는다.
 */
function findDoneButton(f, opts) {
  const o = opts || {};
  const { buf, w, h, r: RI, b: BI } = f;
  const C = o.color || DONE_RGB;
  const same = (x, y) => {
    const k = (y * w + x) * 4;
    return Math.abs(buf[k + RI] - C[0]) + Math.abs(buf[k + 1] - C[1]) + Math.abs(buf[k + BI] - C[2]) <= DONE_TOL;
  };

  for (let y = Math.round(h * 0.78); y < h; y += 2) {
    let run = 0, start = 0;
    for (let x = 0; x <= w; x += 2) {
      if (x < w && same(x, y)) { if (!run) start = x; run += 2; continue; }
      if (run) {
        const mid = start + run / 2;
        if (run / w >= 0.13 && run / w <= 0.26 && mid / w >= 0.45 && mid / w <= 0.70) {
          // 세로로도 단추다운 높이인지
          let top = y, bot = y;
          const cx = Math.round(mid);
          while (top > 0 && same(cx, top - 1)) top--;
          while (bot < h - 1 && same(cx, bot + 1)) bot++;
          const bh = bot - top + 1;
          if (bh / h >= 0.04 && bh / h <= 0.11) {
            return { x: start, y: top, w: run, h: bh };
          }
        }
        run = 0;
      }
    }
  }
  return null;
}

/**
 * 동그라미 크기를 못 쟀을 때 쓸 값. 팔레트 크기에 비례한다.
 * 실측 — 749px 팔레트에서 바깥 반지름 13~14 이므로 대략 1/54 이다.
 */
function defaultRingR(box) {
  return Math.max(RING_MIN, Math.min(RING_MAX, Math.round(Math.min(box.w, box.h) / 54)));
}

/** 건너뛸 네모들. 없으면 null 을 돌려 호출 쪽이 검사 자체를 생략하게 한다. */
/**
 * 가릴 자리를 판정하는 함수를 만든다.
 *
 * 모양이 두 가지다. 안내선은 세로로 길쭉하니 **네모**로 가리고, 스포이드는 동그라미이니
 * **원**으로 가린다. 예전에는 스포이드도 네모(외접 사각형)로 가렸는데, 그러면 원보다
 * 21% 넓게 지워져 모서리 네 곳의 팔레트가 괜히 사라졌다 — 색을 고를 자리가 그만큼 준다.
 */
function skipper(shapes) {
  if (!shapes || !shapes.length) return null;
  return (x, y) => {
    for (let i = 0; i < shapes.length; i++) {
      const s = shapes[i];
      if (s.r !== undefined) {
        const dx = x - s.cx, dy = y - s.cy;
        if (dx * dx + dy * dy <= s.r * s.r) return true;
      } else if (x >= s.x && x < s.x + s.w && y >= s.y && y < s.y + s.h) return true;
    }
    return false;
  };
}

function findColors(f, rect, targets, opts) {
  const o = opts || {};
  const box = clampRect(rect, f);
  // 건너뛰기 폭은 해상도가 아니라 **뽑을 샘플 수**에서 거꾸로 정한다.
  // 그래야 팔레트가 크든 작든 걸리는 시간이 같다. 15만 점이면 전수와 결과가 거의 같다
  // (실측 — 전수 ΔE 0.4 / 15만 점 ΔE 0.8, 사람 눈으로는 둘 다 구분 불가).
  const want = o.samples || 150000;
  const s = Math.max(1, Math.round(Math.sqrt((box.w * box.h) / want)));
  const { buf, w, r: RI, b: BI } = f;

  const best = targets.map(() => ({ d: Infinity, x: 0, y: 0, rgb: [0, 0, 0] }));
  const skip = skipper(o.skip);

  for (let y = box.y; y < box.y + box.h; y += s) {
    const row = y * w;
    for (let x = box.x; x < box.x + box.w; x += s) {
      if (skip && skip(x, y)) continue;
      const i = (row + x) * 4;
      const rr = buf[i + RI], gg = buf[i + 1], bb = buf[i + BI];
      const L = toLab(rr, gg, bb);
      for (let t = 0; t < targets.length; t++) {
        const T = targets[t].lab;
        const dL = L[0] - T[0], da = L[1] - T[1], db = L[2] - T[2];
        const d = dL * dL + da * da + db * db;
        if (d < best[t].d) { best[t].d = d; best[t].x = x; best[t].y = y; best[t].rgb = [rr, gg, bb]; }
      }
    }
  }

  return targets.map((t, i) => {
    const b = best[i];
    // 건너뛰며 찾은 자리 주변을 원해상도로 한 번 더 본다. 몇백 픽셀이라 공짜에 가깝다.
    const fine = refine(f, b, t, s, skip);
    const delta = Math.sqrt(fine.d);
    // 목표가 제 오차를 들고 있으면 그것을 쓰고, 없으면 호출 쪽 기본값을 쓴다
    const tol = t.tol !== undefined ? t.tol : (o.tolerance === undefined ? 5 : o.tolerance);
    return {
      hex: t.hex,
      x: fine.x, y: fine.y,
      color: rgbToHex(fine.rgb[0], fine.rgb[1], fine.rgb[2]),
      delta: Math.round(delta * 10) / 10,
      tol: tol,
      found: delta <= tol,
    };
  });
}

function refine(f, b, t, s, skip) {
  if (s <= 1) return b;
  const { buf, w, h, r: RI, b: BI } = f;
  let best = b;
  const x0 = Math.max(0, b.x - s), x1 = Math.min(w - 1, b.x + s);
  const y0 = Math.max(0, b.y - s), y1 = Math.min(h - 1, b.y + s);
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      if (skip && skip(x, y)) continue;
      const i = (y * w + x) * 4;
      const rr = buf[i + RI], gg = buf[i + 1], bb = buf[i + BI];
      const L = toLab(rr, gg, bb);
      const dL = L[0] - t.lab[0], da = L[1] - t.lab[1], db = L[2] - t.lab[2];
      const d = dL * dL + da * da + db * db;
      if (d < best.d) best = { d, x, y, rgb: [rr, gg, bb] };
    }
  }
  return best;
}

/**
 * 허용 오차 안에 드는 **모든** 지점을 모은다.
 *
 * 가장 가까운 한 점만 찍어 주면 "이 색이 여기밖에 없나?" 하고 헷갈린다. 실제로는 같은 색이
 * 여러 군데 흩어져 있고, 어디를 찍느냐에 따라 주변 색이 달라서 고를 여지가 있다.
 * 그래서 조건에 드는 자리를 전부 점으로 뿌려 준다.
 *
 * 너무 많으면 그리는 쪽이 느려지므로 상한을 두고, 넘치면 고르게 솎아 낸다.
 */
/**
 * 오차 안에 드는 **구역의 테두리**를 선분으로 돌려준다.
 *
 * 점을 촘촘히 뿌리면 도트 무늬가 되어 정작 소용돌이가 안 보인다. 대신 격자마다
 * "오차 안인가"를 재고, 안과 밖이 갈리는 자리를 따라 선을 긋는다(마칭 스퀘어).
 * 칸 모서리가 아니라 **모서리 한가운데**를 잇기 때문에 45도 대각선이 나와 부드럽다.
 *
 * 그리는 양이 넓이가 아니라 **둘레**에 비례하므로 점을 뿌리는 것보다 오히려 가볍다.
 *
 * @returns 목표마다 [x1,y1,x2,y2, ...] 선분 묶음 (캡처 좌표)
 */
function findRegions(f, rect, targets, opts) {
  const o = opts || {};
  const box = clampRect(rect, f);
  const base = Math.max(2, Math.round(Math.min(box.w, box.h) / (o.cells || 180)));
  // 오차를 크게 잡으면 구역이 넓어져 테두리도 길어진다. 너무 많으면 격자를 키워 다시
  // 잰다 — 잘라내면 테두리가 중간에 끊겨 보이지만, 성기게 그리면 모양은 남는다.
  const bandOf = o.bands
    ? (t, x) => !o.bands[t] || (x >= o.bands[t].x0 && x < o.bands[t].x1)
    : null;
  for (const mul of [1, 2, 4]) {
    const got = marchOnce(f, box, targets, skipper(o.skip), base * mul, o.max || 2000, bandOf);
    if (got) return got;
  }
  return marchOnce(f, box, targets, skipper(o.skip), base * 8, 1e9, bandOf) ||
    { segs: targets.map(() => []), fills: targets.map(() => []) };
}

function marchOnce(f, box, targets, skip, step, cap, bandOf) {
  const gw = Math.floor(box.w / step), gh = Math.floor(box.h / step);
  const { buf, w, r: RI, b: BI } = f;
  if (gw < 3 || gh < 3) return targets.map(() => []);

  // 1) 격자마다 목표별로 오차 안인지.
  //
  // 가린 자리(UI)는 **"아님"이 아니라 "모름"** 으로 둔다. 아님으로 두면 그 둘레가
  // 안팎의 경계가 되어 **UI 를 빙 두르는 가짜 테두리**가 그려진다 — 스포이드 동그라미가
  // 초록 테로 감싸여 보이던 것이 그것이다.
  const masks = targets.map(() => new Uint8Array(gw * gh));
  const blocked = new Uint8Array(gw * gh);
  for (let gy = 0; gy < gh; gy++) {
    for (let gx = 0; gx < gw; gx++) {
      const x = box.x + gx * step + (step >> 1);
      const y = box.y + gy * step + (step >> 1);
      if (skip && skip(x, y)) { blocked[gy * gw + gx] = 1; continue; }
      const i = (y * w + x) * 4;
      const L = toLab(buf[i + RI], buf[i + 1], buf[i + BI]);
      for (let t = 0; t < targets.length; t++) {
        const T = targets[t];
        const tol = T.tol === undefined ? 5 : T.tol;
        if (!tol) continue;                       // 오차 0 이면 구역을 그리지 않는다
        const dL = L[0] - T.lab[0], da = L[1] - T.lab[1], db = L[2] - T.lab[2];
        // 제 구역 밖에 있는 색은 그 스포이드가 못 잡는다 — 보여 주면 헛걸음을 시킨다
        if (bandOf && !bandOf(t, x)) continue;
        if (dL * dL + da * da + db * db <= tol * tol) masks[t][gy * gw + gx] = 1;
      }
    }
  }

  // 1-b) 가린 자리를 한 칸씩 넓힌다.
  //
  // 칸 한가운데로만 재므로, 가장자리 칸은 한가운데가 UI 밖이어도 몸통은 UI 에 걸친다.
  // 그 칸에서 선이 나가면 UI 를 스치듯 몇 점이 남는다. 한 칸(약 4px) 여유를 준다.
  {
    const grown = Uint8Array.from(blocked);
    for (let gy = 0; gy < gh; gy++) {
      for (let gx = 0; gx < gw; gx++) {
        if (!blocked[gy * gw + gx]) continue;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            const nx = gx + dx, ny = gy + dy;
            if (nx >= 0 && ny >= 0 && nx < gw && ny < gh) grown[ny * gw + nx] = 1;
          }
        }
      }
    }
    blocked.set(grown);
  }

  /*
   * 2) 채울 자리 — 켜진 칸을 가로로 이어 띠로 묶는다.
   *
   * 칸을 하나씩 내보내면 격자가 촘촘할 때 수천 개가 된다. 한 줄에서 이어진 칸은
   * 어차피 같은 네모로 칠하므로 [x0,y0,x1,y1] 하나로 묶어 보낸다 — 그리는 쪽도
   * 네모 한 번이면 끝이고, 오버레이로 넘길 글자 수도 크게 준다.
   */
  const fills = masks.map((m) => {
    const runs = [];
    for (let gy = 0; gy < gh; gy++) {
      let from = -1;
      for (let gx = 0; gx <= gw; gx++) {
        const on = gx < gw && m[gy * gw + gx] && !blocked[gy * gw + gx];
        if (on && from < 0) from = gx;
        if (!on && from >= 0) {
          const x0 = box.x + from * step + (step >> 1);
          const y0 = box.y + gy * step + (step >> 1);
          runs.push(x0, y0, x0 + (gx - from) * step, y0 + step);
          from = -1;
        }
      }
    }
    return runs;
  });

  // 3) 마칭 스퀘어 — 네 칸의 켜짐꼴에 따라 정해진 선분을 낸다
  const all = [];
  for (const m of masks) {
    const out = [];
    for (let gy = 0; gy + 1 < gh; gy++) {
      for (let gx = 0; gx + 1 < gw; gx++) {
        const i0 = gy * gw + gx, i1 = i0 + 1, i2 = (gy + 1) * gw + gx, i3 = i2 + 1;
        // 네 귀 중 하나라도 모르는 칸이면 이 자리에는 선을 긋지 않는다
        if (blocked[i0] || blocked[i1] || blocked[i2] || blocked[i3]) continue;
        const tl = m[i0], tr = m[i1], bl = m[i2], br = m[i3];
        const idx = (tl << 3) | (tr << 2) | (br << 1) | bl;
        if (idx === 0 || idx === 15) continue;
        const X = box.x + gx * step + (step >> 1);
        const Y = box.y + gy * step + (step >> 1);
        // 좌표는 정수로. 2px 선을 그을 자리라 소수점은 쓸모가 없고 글자 수만 늘린다.
        const hx = X + (step >> 1), hy = Y + (step >> 1);
        const T = [hx, Y], R = [X + step, hy], B = [hx, Y + step], L2 = [X, hy];
        const seg = (a, b) => { out.push(a[0], a[1], b[0], b[1]); };
        switch (idx) {
          case 1: case 14: seg(L2, B); break;
          case 2: case 13: seg(B, R); break;
          case 3: case 12: seg(L2, R); break;
          case 4: case 11: seg(T, R); break;
          case 6: case 9: seg(T, B); break;
          case 7: case 8: seg(L2, T); break;
          case 5: seg(L2, T); seg(B, R); break;
          case 10: seg(T, R); seg(L2, B); break;
        }
      }
      if (out.length > cap * 4) return null;   // 너무 많다 — 더 성긴 격자로 다시
    }
    all.push(out);
  }
  return { segs: all, fills: fills };
}

/**
 * 세 색을 **한 번에** 잡을 수 있는 자리를 찾는다. (3파트 염색 전용)
 *
 * ── 지금은 쓰지 않는다 ─────────────────────────────────────
 * 화면에는 안 그린다. 계산은 맞는다 — 찾아낸 삼각형은 스포이드 삼각형과 닮은꼴이고
 * (변 길이비 흩어짐 0.2% 이내) 꼭짓점 세 곳의 실제 픽셀 색도 전부 오차 안이었다.
 * 따라가기도 끌기·회전·줌 모두 0~2px 로 따라붙는다(trackPatches).
 *
 * 그런데도 실제로 쓰기에는 거칠었다. 팔레트를 끌고 돌리는 동안 삼각형이 튀거나
 * 피하는 것처럼 보이는 문제를 여러 번 고쳤지만 끝내 매끄러워지지 않았다.
 *
 * 코드는 남겨 둔다. 다시 손볼 때를 위해 무엇이 이미 해결됐는지 적어 둔다.
 *
 *   · 구역(findBands) — 파트마다 염색 타입이 다르면 팔레트가 세로로 갈라지고,
 *     그러면 1번 스포이드는 1번 구역 안에서만 고를 수 있다. 이건 반영돼 있다.
 *   · 꼭짓점 색은 격자가 아니라 **그 픽셀을 직접** 확인한다. 격자만 믿으면
 *     ΔE 75 짜리 자리를 "찾았다"고 내놓는다.
 *   · 남은 숙제는 "찾은 뒤 어떻게 보여 줄 것인가" 쪽이다. 계산이 아니라 다루는 맛.
 *
 * ── 무엇을 푸는가 ──────────────────────────────────────────
 * 스포이드 셋은 화면에 붙박이고, 셋이 이루는 삼각형은 시도하는 동안 모양이 안 바뀐다.
 * 움직이는 것은 그 아래 소용돌이뿐이다 — 끌고, 돌리고, 확대·축소한다.
 *
 * 그래서 이렇게 바꿔 읽을 수 있다.
 *
 *   "소용돌이 위에서, **스포이드 삼각형과 닮은** 삼각형을 찾아라.
 *    단 꼭짓점 셋의 색이 각각 1·2·3번 목표 오차 안이어야 한다."
 *
 * 찾으면 그 삼각형을 그려 준다. 그것이 스포이드 밑으로 오도록 끌고 돌리고 줌을 맞추면
 * 세 색이 동시에 잡힌다.
 *
 * ── 왜 각도와 배율을 훑지 않아도 되나 ──────────────────────
 * 훑으면 (자리 2 × 각도 1 × 배율 1) 네 겹이라 수천만 번이 된다.
 *
 * 그럴 필요가 없다. **꼭짓점 두 개를 고르면 나머지가 전부 정해진다.**
 * 1번 자리 a 와 2번 자리 b 를 고르면, a→b 가 S1→S2 로 가야 하므로
 * 회전각과 배율이 하나로 결정되고, 3번 꼭짓점 c 도 계산으로 나온다.
 * c 자리의 색만 확인하면 끝이다.
 *
 * 그래서 비용이 |A| × |B| 로 떨어진다. 점을 400개씩만 뽑으면 16만 번이다.
 *
 * ── 지금 보이는 것만 쓴다 ──────────────────────────────────
 * 끌면 바깥에서 새 무늬가 들어오는데 그것은 읽을 방법이 없다. 그래서 답은 언제나
 * "지금 보이는 범위 안에서 가능한가"이다. 세 꼭짓점 모두 보이는 곳에서 뽑는다.
 *
 * ── 어느 답을 고르나 ───────────────────────────────────────
 * 답이 여럿이면 **손이 가장 덜 가는 것**을 고른다. 아무것도 안 해도 되는 상태
 * (배율 1, 회전 0, 이동 0)에서 얼마나 먼지로 값을 매긴다.
 *
 *   줌   |log2(배율)|        — 두 배/절반이 1.0
 *   회전 |각도| / 90도
 *   이동 거리 / (팔레트 폭의 절반)   — 셋 중 가장 쉬우므로 가중치를 낮게
 */
/**
 * 팔레트가 세로로 몇 구역으로 갈라져 있는지 — 그리고 어느 스포이드가 어느 구역에 묶이는지.
 *
 * ── 왜 필요한가 ────────────────────────────────────────────
 * 파트마다 염색 **타입**(천·가죽·금속·나무)이 다를 수 있다. 타입이 다르면 그 칸의 소용돌이
 * 자체가 다른 것으로 채워지고, 팔레트는 세로로 갈라진 별개의 판이 된다.
 *
 * 그러면 **1번 스포이드는 1번 판 안에서만** 색을 고를 수 있다. 끌어도 무늬가 칸 경계를
 * 넘어오지 않는다. 그래서 삼각형을 찾을 때 "1번 꼭짓점이 3번 판에 있는" 답을 내놓으면
 * 아무리 끌어도 맞출 수 없는 거짓말이 된다.
 *
 * ── 경계는 늘 3등분이 아니다 ───────────────────────────────
 * **이웃한 파트의 타입이 같으면 그 둘은 이어져 있다.** 그래서 경계는 있을 수도, 없을 수도
 * 있다. 실측 (경계 후보 자리의 열 차이 / 팔레트 평균)
 *
 *   세 타입이 다 다른 화면   0.333 에서 7.6배 · 0.667 에서 5.0배   → 구역 셋
 *   1·2 가 같은 타입        0.333 에서 0.9배 · 0.667 에서 7.5배   → 구역 둘
 *   셋 다 같은 타입         0.333 에서 1.3배 · 0.667 에서 1.3배   → 구역 하나
 *
 * 진짜 경계는 4.8~9.0배, 아닌 곳은 0.9~1.3배다. 3배에 선을 그으면 깨끗하게 갈린다.
 *
 * @param n  파트 수 (스포이드 개수)
 * @returns  파트마다 { x0, x1 } — 그 스포이드가 색을 고를 수 있는 가로 범위
 */
/** 조각이 어디로 갔나. 못 찾으면 null. */
function matchPatch(patch, f, opts) {
  const o = opts || {};
  if (!patch) return null;
  const { data, n, s, x0, y0 } = patch;
  const { buf, w, h, r: RI, b: BI } = f;
  // 한 바퀴 0.12초에 이만큼까지 따라간다 (약 750px/s)
  const range = o.range || 90;

  const sad = (dx, dy) => {
    let sum = 0;
    for (let j = 0; j < n; j += 2) {                 // 절반만 봐도 충분하다
      const yy = y0 + j * s + dy;
      if (yy < 0 || yy >= h) return Infinity;
      for (let i = 0; i < n; i += 2) {
        const xx = x0 + i * s + dx;
        if (xx < 0 || xx >= w) return Infinity;
        const k = (yy * w + xx) * 4;
        const v = (buf[k + RI] + buf[k + 1] + buf[k + BI]) / 3;
        sum += Math.abs(v - data[j * n + i]);
      }
    }
    return sum / ((n / 2) * (n / 2));
  };

  // 1) 성기게
  let bx = 0, by = 0, bs = Infinity;
  for (let dy = -range; dy <= range; dy += 6) {
    for (let dx = -range; dx <= range; dx += 6) {
      const v = sad(dx, dy);
      if (v < bs) { bs = v; bx = dx; by = dy; }
    }
  }
  // 2) 그 언저리를 촘촘히
  for (let dy = by - 5; dy <= by + 5; dy++) {
    for (let dx = bx - 5; dx <= bx + 5; dx++) {
      const v = sad(dx, dy);
      if (v < bs) { bs = v; bx = dx; by = dy; }
    }
  }

  // 아무 데도 잘 안 맞으면(돌렸거나 줌했거나) 옮기지 않는다
  // 잘 맞은 것과 아닌 것의 차이가 크다 — 실측으로 제대로 맞으면 0.2~0.3, 범위를 벗어나
  // 엉뚱한 데를 짚으면 14 였다. 8 에 선을 그으면 실제 화면의 번짐까지 감안해도 넉넉하다.
  if (bs > (o.maxScore || 8)) return null;
  return { dx: bx, dy: by, score: bs };
}

/**
 * 팔레트가 어떻게 움직였는지 — **끌기·회전·줌을 한꺼번에.**
 *
 * ── 왜 작은 조각을 여럿 쓰나 ───────────────────────────────
 * 조각 하나로는 "어디로 갔나"(끌기)밖에 모른다. 큰 조각은 돌리면 **제 안에서 찌그러져**
 * 아예 못 맞는다 — 한 변 104px 짜리로는 3도만 돌아도 모서리가 2.7px 밀려 실패했다.
 *
 * 작은 조각(한 변 32px)은 돌아도 거의 안 찌그러진다. 그런 조각을 팔레트 곳곳에서 아홉 개
 * 떠서 각각 "어디로 갔나"만 찾고, 그 아홉 쌍에 **닮음변환을 최소제곱으로 맞춘다.**
 * 조각 하나하나는 끌기만 알아도, 떨어진 자리들의 끌기를 모으면 회전과 배율이 나온다.
 *
 * 실측 (일부러 변형해 놓고 맞히기 — 잰 값 / 정답)
 *
 *   끌기 25,-18      1.000 / 0.0°    ←  1.000 / 0.0°
 *   회전 2도          1.000 / 2.0°    ←  1.000 / 2.0°
 *   회전 5도          1.005 / 4.8°    ←  1.000 / 5.0°
 *   줌 1.05          1.051 / -0.1°   ←  1.050 / 0.0°
 *   줌 0.95 + 회전 3도 0.952 / -2.8°   ←  0.950 / -3.0°
 *   전부 섞기         1.041 / 3.8°    ←  1.040 / 4.0°
 *
 * ── 무엇에 쓰나 ────────────────────────────────────────────
 * 한 번 찾은 삼각형의 꼭짓점을 **못 박아 두고** 이 변환으로 계속 옮긴다. 색 구역이
 * 모양을 바꾸든 잠깐 사라지든 상관없다 — 소용돌이 위의 그 점은 그대로 있으니까.
 */
const TRACK_N = 16;          // 조각 한 변의 표본 수
const TRACK_S = 2;           // 표본 간격 → 한 변 32px
const TRACK_SCORE = 18;      // 이보다 안 맞으면 그 조각은 버린다
const TRACK_MIN = 3;         // 최소 이만큼은 맞아야 변환을 낸다

function makePatches(f, box, opts) {
  const o = opts || {};
  const n = o.n || TRACK_N, s = o.s || TRACK_S;
  const half = (n * s) >> 1;
  const { buf, w, r: RI, b: BI } = f;
  const out = [];
  for (const fy of [0.25, 0.5, 0.75]) {
    for (const fx of [0.25, 0.5, 0.75]) {
      const cx = Math.round(box.x + box.w * fx), cy = Math.round(box.y + box.h * fy);
      const x0 = cx - half, y0 = cy - half;
      const data = new Uint8Array(n * n);
      for (let j = 0; j < n; j++) {
        for (let i = 0; i < n; i++) {
          const k = ((y0 + j * s) * w + (x0 + i * s)) * 4;
          data[j * n + i] = (buf[k + RI] + buf[k + 1] + buf[k + BI]) / 3;
        }
      }
      out.push({ data: data, n: n, s: s, x0: x0, y0: y0, cx: cx, cy: cy });
    }
  }
  return out;
}

/** 아홉 쌍에 닮음변환을 맞춘다. 너무 안 맞는 조각은 한 번 걸러내고 다시 맞춘다. */
function fitSimilarity(pairs) {
  let sx = 0, sy = 0, sxp = 0, syp = 0;
  for (const p of pairs) { sx += p.ax; sy += p.ay; sxp += p.bx; syp += p.by; }
  const n = pairs.length;
  const mx = sx / n, my = sy / n, mxp = sxp / n, myp = syp / n;
  let num1 = 0, num2 = 0, den = 0;
  for (const p of pairs) {
    const ux = p.ax - mx, uy = p.ay - my;
    const vx = p.bx - mxp, vy = p.by - myp;
    num1 += ux * vx + uy * vy;
    num2 += ux * vy - uy * vx;
    den += ux * ux + uy * uy;
  }
  if (den < 1) return null;
  const re = num1 / den, im = num2 / den;
  return { at: { x: mx, y: my }, to: { x: mxp, y: myp }, re: re, im: im };
}

function residual(m, p) {
  const dx = p.ax - m.at.x, dy = p.ay - m.at.y;
  const x = m.to.x + m.re * dx - m.im * dy;
  const y = m.to.y + m.re * dy + m.im * dx;
  return Math.hypot(x - p.bx, y - p.by);
}

function trackPatches(patches, f, opts) {
  const o = opts || {};
  if (!patches || patches.length < TRACK_MIN) return null;

  let pairs = [];
  for (const p of patches) {
    const m = matchPatch(p, f, { maxScore: o.maxScore || TRACK_SCORE, range: o.range || 60 });
    if (m) pairs.push({ ax: p.cx, ay: p.cy, bx: p.cx + m.dx, by: p.cy + m.dy });
  }
  if (pairs.length < TRACK_MIN) return null;

  let m = fitSimilarity(pairs);
  if (!m) return null;

  // 한 조각이 엉뚱한 데를 짚으면 전체가 틀어진다. 많이 어긋난 것을 빼고 다시 맞춘다.
  if (pairs.length > TRACK_MIN) {
    const keep = pairs.filter((p) => residual(m, p) <= (o.tol || 6));
    if (keep.length >= TRACK_MIN && keep.length < pairs.length) {
      pairs = keep;
      m = fitSimilarity(pairs) || m;
    }
  }

  const k = Math.hypot(m.re, m.im);
  // 한 바퀴(0.12초) 사이에 이만큼 변하는 것은 잘못 잰 것이다
  if (k < (o.minStep || 0.8) || k > (o.maxStep || 1.25)) return null;

  m.used = pairs.length;
  m.zoomStep = k;
  m.turnStep = (Math.atan2(m.im, m.re) * 180) / Math.PI;
  return m;
}

/** 변환을 점들에 먹인다. */
function moveBy(points, m) {
  if (!m) return points;
  return points.map((p) => {
    const dx = p.x - m.at.x, dy = p.y - m.at.y;
    return {
      x: Math.round(m.to.x + m.re * dx - m.im * dy),
      y: Math.round(m.to.y + m.re * dy + m.im * dx),
    };
  });
}

function findBands(f, box, n, opts) {
  const o = opts || {};
  const parts = Math.max(1, n | 0);
  const whole = [{ x0: box.x, x1: box.x + box.w }];
  if (parts < 2) return whole;

  const { buf, w, r: RI, b: BI } = f;

  /* 열과 바로 옆 열이 얼마나 다른가 */
  const colDiff = (x) => {
    let s = 0, c = 0;
    for (let y = box.y + 6; y < box.y + box.h - 6; y += 3) {
      const a = (y * w + x) * 4, b = a - 4;
      s += Math.abs(buf[a + RI] - buf[b + RI]) +
           Math.abs(buf[a + 1] - buf[b + 1]) +
           Math.abs(buf[a + BI] - buf[b + BI]);
      c++;
    }
    return c ? s / c : 0;
  };

  /* 팔레트 전체의 보통 값 — 이것과 견준다 */
  let sum = 0, cnt = 0;
  for (let x = box.x + 8; x < box.x + box.w - 8; x += 7) { sum += colDiff(x); cnt++; }
  const mean = cnt ? sum / cnt : 0;
  if (mean <= 0) return whole;

  /* 경계 후보 자리마다, 그 언저리에서 가장 튀는 값을 본다 */
  const cuts = [];
  for (let i = 1; i < parts; i++) {
    const at = Math.round(box.x + (box.w * i) / parts);
    let peak = 0, where = at;
    for (let x = at - 8; x <= at + 8; x++) {
      if (x <= box.x || x >= box.x + box.w) continue;
      const v = colDiff(x);
      if (v > peak) { peak = v; where = x; }
    }
    if (peak >= mean * (o.cutRatio || 3)) cuts.push(where);
  }

  /* 경계가 없는 이웃끼리는 한 구역이다 */
  const edges = [box.x].concat(cuts, [box.x + box.w]);
  const out = [];
  for (let i = 0; i < parts; i++) {
    const center = box.x + (box.w * (2 * i + 1)) / (2 * parts);
    let lo = box.x, hi = box.x + box.w;
    for (const e of edges) {
      if (e <= center && e > lo) lo = e;
      if (e >= center && e < hi) hi = e;
    }
    out.push({ x0: Math.round(lo), x1: Math.round(hi) });
  }
  return out;
}

function findTriangle(f, box, targets, pins, opts) {
  const o = opts || {};
  if (!targets || targets.length < 3 || !pins || pins.length < 3) return null;

  const step = Math.max(2, Math.round(Math.min(box.w, box.h) / (o.cells || 180)));
  const gw = Math.floor(box.w / step), gh = Math.floor(box.h / step);
  if (gw < 4 || gh < 4) return null;
  const { buf, w, r: RI, b: BI } = f;
  const skip = skipper(o.skip);
  const bandsIn = o.bands;
  const inBandAt = (t, x) => !bandsIn || !bandsIn[t] || (x >= bandsIn[t].x0 && x < bandsIn[t].x1);

  /* 1) 격자마다 목표별로 오차 안인지 */
  const mask = [new Uint8Array(gw * gh), new Uint8Array(gw * gh), new Uint8Array(gw * gh)];
  const pts = [[], [], []];
  for (let gy = 0; gy < gh; gy++) {
    for (let gx = 0; gx < gw; gx++) {
      const x = box.x + gx * step + (step >> 1);
      const y = box.y + gy * step + (step >> 1);
      if (skip && skip(x, y)) continue;
      const i = (y * w + x) * 4;
      const L = toLab(buf[i + RI], buf[i + 1], buf[i + BI]);
      for (let t = 0; t < 3; t++) {
        const T = targets[t];
        const tol = T.tol === undefined ? 5 : T.tol;
        if (!tol) continue;
        const dL = L[0] - T.lab[0], da = L[1] - T.lab[1], db = L[2] - T.lab[2];
        if (dL * dL + da * da + db * db <= tol * tol && inBandAt(t, x)) {
          mask[t][gy * gw + gx] = 1;
          pts[t].push(x, y);
        }
      }
    }
  }
  if (!pts[0].length || !pts[1].length || !pts[2].length) return null;

  /* 2) 1·2번 후보를 고르게 솎는다. 다 보면 제곱으로 늘어난다. */
  const thin = (arr, cap) => {
    const n = arr.length / 2;
    if (n <= cap) return arr;
    const out = [];
    for (let k = 0; k < cap; k++) {
      const i = Math.floor(k * (n / cap)) * 2;
      out.push(arr[i], arr[i + 1]);
    }
    return out;
  };
  const cap = o.cap || 420;
  const A = thin(pts[0], cap), B = thin(pts[1], cap);

  /* 3) 스포이드 삼각형 */
  const S1 = pins[0], S2 = pins[1], S3 = pins[2];
  const vx = S2.x - S1.x, vy = S2.y - S1.y;
  const vLen2 = vx * vx + vy * vy;
  if (vLen2 < 4) return null;
  const wx = S3.x - S1.x, wy = S3.y - S1.y;

  /**
   * 3번 꼭짓점은 **두 번** 본다.
   *
   * 격자는 칸 한가운데 색만 안다. 계산으로 나온 c 는 그 한가운데에서 최대 반 칸(2~3px)
   * 떨어질 수 있는데, 소용돌이는 경계가 날카로워서 그 정도만 어긋나도 다른 색이다.
   * 실제로 이것 때문에 ΔE 75 짜리 자리를 "찾았다"고 내놓은 적이 있다.
   *
   * 그래서 격자는 **빨리 걸러내는 데만** 쓰고(이웃 칸까지 넉넉히 본다), 남은 것만
   * 그 픽셀을 직접 읽어 확인한다. 격자로 거른 뒤라 확인하는 횟수가 얼마 안 된다.
   */
  const nearMask = (t, x, y) => {
    const gx = Math.floor((x - box.x) / step), gy = Math.floor((y - box.y) / step);
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const nx = gx + dx, ny = gy + dy;
        if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
        if (mask[t][ny * gw + nx]) return true;
      }
    }
    return false;
  };

  const exactOk = (t, x, y) => {
    const xi = Math.round(x), yi = Math.round(y);
    if (xi < box.x || yi < box.y || xi >= box.x + box.w || yi >= box.y + box.h) return false;
    if (skip && skip(xi, yi)) return false;
    const i = (yi * w + xi) * 4;
    const L = toLab(buf[i + RI], buf[i + 1], buf[i + BI]);
    const T = targets[t];
    const tol = T.tol === undefined ? 5 : T.tol;
    const dL = L[0] - T.lab[0], da = L[1] - T.lab[1], db = L[2] - T.lab[2];
    return dL * dL + da * da + db * db <= tol * tol;
  };

  const minK = o.minZoom || 0.4, maxK = o.maxZoom || 2.5;

  /**
   * ── 직전에 찾은 것을 놓치지 않는다 ──────────────────────
   * 매번 "가장 싼 답"을 새로 고르면, 팔레트를 조금만 끌어도 답이 **다른 자리로 튄다.**
   * 사용자 눈에는 삼각형이 사라졌다 나타났다 하는 것으로 보인다 — 쫓아갈 수가 없다.
   *
   * 그래서 직전 답(anchor)이 있으면 **그 근처부터** 본다. 한 바퀴가 0.12초라 그 사이
   * 팔레트가 멀리 가지 못하므로, 같은 자리를 다시 찾아 이어 그리게 된다.
   * 근처에서 못 찾았을 때만 전체를 다시 뒤진다.
   *
   * 가까운 범위에서는 점을 솎지 않고 다 본다. 솎아내면 바로 그 점이 빠져 깜빡인다.
   */
  const near = (arr, p, r) => {
    const out = [];
    const r2 = r * r;
    for (let i = 0; i < arr.length; i += 2) {
      const dx = arr[i] - p.x, dy = arr[i + 1] - p.y;
      if (dx * dx + dy * dy <= r2) out.push(arr[i], arr[i + 1]);
    }
    return out;
  };

  // 꼭짓점은 **제 구역 안에만** 있을 수 있다. 밖에 있는 답은 아무리 끌어도 못 맞춘다.
  const bands = o.bands;
  const inBand = (t, x) => !bands || !bands[t] || (x >= bands[t].x0 && x < bands[t].x1);

  const anchor = o.anchor && o.anchor.length === 3 ? o.anchor : null;
  /**
   * 따라갈 범위.
   *
   * 부르는 쪽이 앵커를 **소용돌이가 움직인 만큼 미리 옮겨** 준다. 그래서 범위는 넓을
   * 필요가 없다 — 오히려 넓으면 엉뚱한 덩어리로 옮겨붙는다. 옮겨 주지 못한 바퀴
   * (돌리거나 줌을 해서 못 쟀을 때)를 위해 그보다는 조금 여유를 둔다.
   *
   * 후보가 많아지면 제곱으로 무거워지므로 상한을 지킨다.
   */
  const R = o.follow || 120;
  const rounds = [];
  if (anchor) {
    rounds.push({
      A: thin(near(pts[0], anchor[0], R), 500),
      B: thin(near(pts[1], anchor[1], R), 500),
      anchor: anchor,
    });
  }
  rounds.push({ A: A, B: B, anchor: null });

  let best = null;
  for (const round of rounds) {
  const A = round.A, B = round.B, keep = round.anchor;

  for (let ia = 0; ia < A.length; ia += 2) {
    const ax = A[ia], ay = A[ia + 1];
    for (let ib = 0; ib < B.length; ib += 2) {
      const bx = B[ib], by = B[ib + 1];
      const ux = bx - ax, uy = by - ay;
      const uLen2 = ux * ux + uy * uy;
      if (uLen2 < 4) continue;

      // a→b 가 S1→S2 로 가는 닮음변환. 배율과 회전이 여기서 하나로 정해진다.
      const k = Math.sqrt(vLen2 / uLen2);
      if (k < minK || k > maxK) continue;

      // 화면→팔레트 방향(역변환)으로 S3 를 옮겨 c 를 얻는다.
      // 역회전·역배율을 복소수 곱 한 번으로 끝낸다: (w) * conj(v) / |v|^2 * (u)
      const rx = (wx * vx + wy * vy) / vLen2;     // v 기준 w 의 성분
      const ry = (wy * vx - wx * vy) / vLen2;
      const cx = ax + rx * ux - ry * uy;
      const cy = ay + rx * uy + ry * ux;
      if (!inBand(2, cx)) continue;            // 3번 구역 밖이면 못 맞춘다
      if (!nearMask(2, cx, cy)) continue;      // 빨리 거르고
      if (!exactOk(2, cx, cy)) continue;       // 그 픽셀을 직접 확인

      const theta = Math.abs(Math.atan2(vy, vx) - Math.atan2(uy, ux));
      const turn = Math.min(theta, Math.PI * 2 - theta);
      const pan = Math.hypot(ax - S1.x, ay - S1.y);

      // 직전 것을 쫓는 바퀴에서는 **직전과 가까운 것**이 이긴다. 손이 얼마나 가는지는
      // 그 다음 문제다 — 눈앞의 삼각형이 안 흔들리는 것이 먼저다.
      const cost = keep
        ? Math.hypot(ax - keep[0].x, ay - keep[0].y) + Math.hypot(bx - keep[1].x, by - keep[1].y)
        : Math.abs(Math.log2(k)) + (turn / (Math.PI / 2)) + 0.7 * (pan / (box.w / 2));
      if (best && cost >= best.cost) continue;

      best = {
        cost: cost,
        zoom: k,
        turn: (turn * 180) / Math.PI,
        turnSigned: ((Math.atan2(vy, vx) - Math.atan2(uy, ux)) * 180) / Math.PI,
        pan: pan,
        points: [{ x: ax, y: ay }, { x: bx, y: by }, { x: Math.round(cx), y: Math.round(cy) }],
        followed: !!keep,
      };
    }
  }
  if (best) break;        // 가까운 데서 찾았으면 전체를 뒤질 이유가 없다
  }
  return best;
}

function findSpots(f, rect, targets, opts) {
  const o = opts || {};
  const box = clampRect(rect, f);
  const want = o.samples || 60000;
  const s = Math.max(1, Math.round(Math.sqrt((box.w * box.h) / want)));
  const cap = o.max || 700;
  const { buf, w, r: RI, b: BI } = f;

  const hits = targets.map(() => []);
  const skip = skipper(o.skip);
  for (let y = box.y; y < box.y + box.h; y += s) {
    const row = y * w;
    for (let x = box.x; x < box.x + box.w; x += s) {
      if (skip && skip(x, y)) continue;
      const i = (row + x) * 4;
      const L = toLab(buf[i + RI], buf[i + 1], buf[i + BI]);
      for (let t = 0; t < targets.length; t++) {
        const T = targets[t];
        const tol = T.tol === undefined ? 5 : T.tol;
        if (!tol) continue;                       // 오차 0 이면 점을 뿌리지 않는다
        const dL = L[0] - T.lab[0], da = L[1] - T.lab[1], db = L[2] - T.lab[2];
        if (dL * dL + da * da + db * db <= tol * tol) hits[t].push(x, y);
      }
    }
  }

  // 넘치면 고르게 솎는다. 앞쪽만 자르면 팔레트 위쪽에만 몰린다.
  return hits.map((arr) => {
    const n = arr.length / 2;
    if (n <= cap) return arr;
    const keep = [];
    const stepN = n / cap;
    for (let k = 0; k < cap; k++) {
      const idx = Math.floor(k * stepN) * 2;
      keep.push(arr[idx], arr[idx + 1]);
    }
    return keep;
  });
}

/* ── 바뀌었는지 ─────────────────────────────────────────────── */

/**
 * 팔레트가 움직였는지 싸게 가늠한다.
 *
 * 소용돌이는 사용자가 끌거나 돌리거나 확대할 때만 바뀐다. 가만히 있는 동안 매번 다시
 * 훑는 것은 낭비라, 격자로 몇백 점만 찍어 지문을 만들고 그것만 비교한다.
 */
function signature(f, rect, n) {
  const box = clampRect(rect, f);
  const k = n || 16;
  const out = new Uint8Array(k * k * 3);
  const { buf, w, r: RI, b: BI } = f;
  let p = 0;
  for (let gy = 0; gy < k; gy++) {
    const y = box.y + Math.floor((gy + 0.5) * box.h / k);
    for (let gx = 0; gx < k; gx++) {
      const x = box.x + Math.floor((gx + 0.5) * box.w / k);
      const i = (y * w + x) * 4;
      out[p++] = buf[i + RI]; out[p++] = buf[i + 1]; out[p++] = buf[i + BI];
    }
  }
  return out;
}

/** 지문이 얼마나 달라졌나. 0이면 그대로. */
function signatureDiff(a, b) {
  if (!a || !b || a.length !== b.length) return Infinity;
  let s = 0;
  for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]);
  return s / a.length;
}

/* ── 히트맵 ─────────────────────────────────────────────────── */

/**
 * 목표색과 얼마나 가까운지를 밝기로 그린 작은 그림.
 *
 * 화면에 없는 색을 찾을 때, 어느 쪽으로 끌어야 가까워지는지 보여 준다.
 * @returns {{w,h,data}} data 는 0~255 밝기 (가까울수록 밝다)
 */
function heatmap(f, rect, t, size) {
  const box = clampRect(rect, f);
  const k = size || 64;
  const data = new Uint8Array(k * k);
  const { buf, w, r: RI, b: BI } = f;
  let p = 0;
  for (let gy = 0; gy < k; gy++) {
    const y = box.y + Math.floor((gy + 0.5) * box.h / k);
    for (let gx = 0; gx < k; gx++) {
      const x = box.x + Math.floor((gx + 0.5) * box.w / k);
      const i = (y * w + x) * 4;
      const d = deltaE(toLab(buf[i + RI], buf[i + 1], buf[i + BI]), t.lab);
      // ΔE 0 → 255, 40 이상 → 0. 그 사이는 선형.
      data[p++] = Math.max(0, 255 - Math.round(d * 255 / 40));
    }
  }
  return { w: k, h: k, data: data };
}

function clampRect(rect, f) {
  const r = rect || { x: 0, y: 0, w: f.w, h: f.h };
  const x = Math.max(0, Math.min(f.w - 1, r.x | 0));
  const y = Math.max(0, Math.min(f.h - 1, r.y | 0));
  return {
    x: x, y: y,
    w: Math.max(1, Math.min(f.w - x, r.w | 0)),
    h: Math.max(1, Math.min(f.h - y, r.h | 0)),
  };
}

/*
 * 메인(Node)과 렌더러(<script>) 양쪽에서 쓴다.
 *
 * 화면 픽셀은 렌더러의 canvas 에 있고, 그것을 IPC 로 메인에 보내면 한 장에 8MB 다.
 * 초당 몇 장씩 주고받을 수가 없어서 **계산을 픽셀이 있는 쪽에서** 한다.
 * 그래도 파일은 하나만 둔다 — 같은 로직을 두 벌 두면 반드시 한쪽만 고치게 된다.
 */
const DYE_API = {
  toLab, deltaE, hexToRgb, rgbToHex, target,
  frame, detectPalette, findLeaders, readRings, findColors, findSpots, findRegions, findTriangle,
  matchPatch, makePatches, trackPatches, moveBy,
  findBands, findDoneButton,
  signature, signatureDiff, heatmap,
};

if (typeof module !== 'undefined' && module.exports) module.exports = DYE_API;
else if (typeof window !== 'undefined') window.dye = DYE_API;
