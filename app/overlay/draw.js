'use strict';
/**
 * 염색 표시를 그리는 곳 — 오버레이 창과 리모콘의 미리보기가 **같은 코드**를 쓴다.
 *
 * ── 왜 나눴나 ──────────────────────────────────────────────
 * 오버레이 창은 화면 캡처에 잡히지 않게 해 두었다(setContentProtection). 그래야 우리가
 * 그린 것이 다음 번 캡처에 섞여 팔레트로 오인되지 않는다. 그런데 그 설정은 **사용자의
 * 스크린샷에서도** 우리 표시를 지운다 — 무엇이 그려지고 있는지 남에게 보여 줄 방법이 없다.
 *
 * 그래서 리모콘 염색 탭에 같은 그림을 작게 다시 그린다. 두 벌로 만들면 반드시 어긋나므로
 * 그리는 코드는 여기 한 벌만 둔다.
 *
 * ── 화면에 그리는 것은 셋뿐 ────────────────────────────────
 * 맨 위 상태 띠와 찾는 색 딱지, 팔레트를 감싸는 빨간 박스, 오차 안에 드는 구역의 테두리,
 * 그리고 목표에 맞은 스포이드 동그라미의 테.
 * 그 이상은 그리지 않는다 — 고리·십자·번호를 얹어 봤더니 **정작 색을 고르는 데 방해가**
 * 됐다. 어느 점이 몇 번 칸인지는 점의 색으로 구분되고, 정확한 색과 차이는 리모콘 창에
 * 글로 적힌다. 게임 위에는 "여기 있다"까지만.
 *
 * ── 소용돌이 위에서 보이게 ─────────────────────────────────
 * 배경이 온갖 색이라 흰 선만 그으면 밝은 부분에서 사라진다. 모든 선은
 * **어두운 테두리 한 겹 → 밝은 선** 두 번 긋는다.
 */

(function (root) {
  const FONT = '"Pretendard","Malgun Gothic",system-ui,sans-serif';

  /**
   * 1·2·3번 칸의 고유색.
   *
   * 찾는 색 그 자체로 점을 찍으면 안 된다 — 회색을 찾을 때 회색 소용돌이 위에 회색 점을
   * 뿌리는 꼴이라 아무것도 안 보인다. 대신 칸마다 **고정색**을 준다.
   *
   * sRGB 에서 더 진하게 만들 수 없는 세 색을 골랐다 — 마젠타·초록·시안. 빨강 계열은
   * 팔레트를 감싸는 박스가 쓰므로 비워 뒀다. 셋은 서로도 가장 멀리 떨어져 있어서
   * 나란히 찍혀도 어느 칸의 것인지 헷갈리지 않는다.
   */
  const SLOT = [
    { line: '#ff00ff', name: '마젠타' },   // 1번
    { line: '#00ff00', name: '초록' },     // 2번
    { line: '#00ffff', name: '시안' },     // 3번
  ];

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  /**
   * 어두운 테두리 한 겹 위에 밝은 선.
   *
   * `draw` 는 **경로만** 만든다(beginPath + rect/arc/moveTo). 긋는 것은 여기 책임이다 —
   * 예전에 여기서 stroke() 를 빠뜨려서 이 함수로 그리던 것이 **전부 안 보였다.**
   * 배너와 채운 원만 남아서 "박스가 안 나온다"로 보였다. 경로만 쌓고 끝내지 말 것.
   */
  function stroke2(ctx, draw, light, wide, thin) {
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(0,0,0,.6)';
    ctx.lineWidth = wide;
    draw();
    ctx.stroke();
    ctx.strokeStyle = light;
    ctx.lineWidth = thin;
    draw();
    ctx.stroke();
  }

  /**
   * 화면 맨 위 가운데. 지금 무엇을 하는 중인지 한 줄.
   * 게임을 보고 있는 동안에도 상태가 보여야 하므로 리모콘 창이 아니라 여기에 띄운다.
   */
  function banner(ctx, W, text, tone, k) {
    if (!text) return;
    ctx.font = '600 ' + Math.round(15 * k) + 'px ' + FONT;
    const w = ctx.measureText(text).width + 34 * k;
    const x = (W - w) / 2, y = 14 * k, h = 34 * k;

    ctx.fillStyle = 'rgba(16,19,26,.86)';
    roundRect(ctx, x, y, w, h, 17 * k);
    ctx.fill();
    ctx.strokeStyle = tone === 'ok' ? 'rgba(78,201,138,.9)' : 'rgba(210,170,70,.9)';
    ctx.lineWidth = 1.5 * k;
    roundRect(ctx, x, y, w, h, 17 * k);
    ctx.stroke();

    ctx.fillStyle = tone === 'ok' ? '#4ec98a' : '#d2aa46';
    ctx.beginPath();
    ctx.arc(x + 16 * k, y + h / 2, 4.5 * k, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#eef1f6';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, x + 27 * k, y + h / 2 + 1);
  }

  /** 어디를 팔레트로 보고 있는지. 잘못 잡았을 때 눈으로 바로 알 수 있어야 한다. */
  function paletteBox(ctx, b, k) {
    if (!b) return;
    // 소용돌이 위에 얹히므로 얇으면 묻힌다. 어두운 테두리를 두껍게 깔고 그 위에 빨간 선.
    stroke2(ctx, () => {
      ctx.beginPath();
      ctx.rect(b.x + 0.5, b.y + 0.5, b.w - 1, b.h - 1);
    }, '#ff2d2d', 8 * k, 3.5 * k);

    const L = Math.min(34 * k, b.w / 5, b.h / 5);
    const corner = (cx, cy, dx, dy) => {
      stroke2(ctx, () => {
        ctx.beginPath();
        ctx.moveTo(cx + dx * L, cy);
        ctx.lineTo(cx, cy);
        ctx.lineTo(cx, cy + dy * L);
      }, '#ff2d2d', 10 * k, 5 * k);
    };
    corner(b.x, b.y, 1, 1);
    corner(b.x + b.w, b.y, -1, 1);
    corner(b.x, b.y + b.h, 1, -1);
    corner(b.x + b.w, b.y + b.h, -1, -1);
  }

  /**
   * 지금 찾는 세 색을 화면 위에도 적는다.
   *
   * 게임을 보고 있는 동안에는 리모콘 창이 안 보인다. 무슨 색을 찾는 중인지, 그 색이
   * 지금 스포이드에 잡혔는지를 여기서 바로 알 수 있어야 한다.
   * 잡힌 칸은 글씨가 또렷하고, 아직이면 흐리다.
   */
  function chips(ctx, W, list, k, top) {
    if (!list || !list.length) return;
    ctx.font = '600 ' + Math.round(12 * k) + 'px ' + FONT;
    const h = 24 * k, gap = 6 * k, pad = 8 * k, sw = 13 * k;
    const ws = list.map((c) => pad * 2 + sw + 6 * k + ctx.measureText(c.hex).width);
    let x = (W - (ws.reduce((a, b) => a + b, 0) + gap * (list.length - 1))) / 2;

    list.forEach((c, i) => {
      const w = ws[i], slot = (SLOT[i] || SLOT[0]).line;
      ctx.fillStyle = 'rgba(16,19,26,.86)';
      roundRect(ctx, x, top, w, h, 6 * k); ctx.fill();
      ctx.strokeStyle = slot;
      ctx.lineWidth = (c.on ? 2 : 1) * k;
      roundRect(ctx, x, top, w, h, 6 * k); ctx.stroke();

      const sy = top + (h - sw) / 2;
      ctx.fillStyle = c.hex;
      roundRect(ctx, x + pad, sy, sw, sw, 3 * k); ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,.4)';
      ctx.lineWidth = 1 * k;
      roundRect(ctx, x + pad, sy, sw, sw, 3 * k); ctx.stroke();

      ctx.fillStyle = c.on ? '#ffffff' : 'rgba(238,241,246,.5)';
      ctx.textBaseline = 'middle';
      ctx.fillText(c.hex, x + pad + sw + 6 * k, top + h / 2 + 1);
      x += w + gap;
    });
  }

  /**
   * 오차 안에 드는 **구역의 테두리**.
   *
   * 예전에는 자리마다 작은 네모를 찍었다. 오차를 조금만 키워도 팔레트가 도트 무늬로
   * 덮여 정작 소용돌이가 안 보였다. 테두리만 그으면 구역의 모양이 그대로 드러나면서
   * 안쪽은 비어 있어 색을 그대로 볼 수 있다.
   */
  function regions(ctx, list, k) {
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    (list || []).forEach((segs, i) => {
      if (!segs || !segs.length) return;
      const trace = () => {
        ctx.beginPath();
        for (let p = 0; p < segs.length; p += 4) {
          ctx.moveTo(segs[p], segs[p + 1]);
          ctx.lineTo(segs[p + 2], segs[p + 3]);
        }
      };
      ctx.strokeStyle = 'rgba(0,0,0,.55)';
      ctx.lineWidth = 4 * k;
      trace(); ctx.stroke();
      ctx.strokeStyle = (SLOT[i] || SLOT[0]).line;
      ctx.lineWidth = 2 * k;
      trace(); ctx.stroke();
    });
  }

  /**
   * 오차 안에 든 자리를 전부. 칸마다 제 고유색으로 찍어 어느 목표의 것인지 구분한다.
   *
   * ── 어두운 받침을 먼저 까는 이유 ─────────────────────────
   * 아무리 진한 색을 골라도 팔레트는 색상환 전체를 덮는다 — 마젠타 점은 마젠타 구역
   * 위에서 그냥 사라진다. 그래서 점보다 한 겹 큰 **어두운 네모를 먼저 깔고** 그 위에
   * 색을 얹는다. 배경이 무슨 색이든 테두리가 생겨서 점이 떠 보인다.
   */
  function spots(ctx, list, k) {
    const s = Math.max(1.5, 3 * k);
    const pad = Math.max(1, k);
    (list || []).forEach((item, i) => {
      const pts = item.pts || [];
      if (!pts.length) return;

      ctx.fillStyle = 'rgba(0,0,0,.75)';
      const o = s + pad * 2;
      for (let p = 0; p < pts.length; p += 2) {
        ctx.fillRect(pts[p] - o / 2, pts[p + 1] - o / 2, o, o);
      }

      ctx.fillStyle = (SLOT[i] || SLOT[0]).line;
      for (let p = 0; p < pts.length; p += 2) {
        ctx.fillRect(pts[p] - s / 2, pts[p + 1] - s / 2, s, s);
      }
    });
  }

  /**
   * 스포이드 동그라미 — **지금 고른 색이 목표에 맞았을 때만** 안쪽에 테두리를 하나 넣는다.
   *
   * 동그라미 안쪽에는 그 자리의 팔레트 색이 그대로 비친다. 그러니 이 표시는 소용돌이에
   * 그리는 구역 테두리와 **같은 뜻**이다 — "여기가 오차 안"이다. 그래서 굵기도 색도
   * 구역 테두리와 똑같이 그린다. 다른 그림이 아니라 같은 그림이 거기까지 이어진 셈이다.
   *
   * ── 왜 구역 계산에 맡기지 않고 따로 그리나 ────────────
   * 흰 테는 팔레트가 아니므로 격자에서 **모름**으로 빼 둔다. 모름 칸에 닿는 자리에는
   * 선을 긋지 않으므로(그러지 않으면 UI 를 빙 두르는 가짜 테두리가 생긴다), 안쪽이
   * 맞아도 저절로는 아무 선도 나오지 않는다. 그래서 여기서 한 번 더 그린다.
   *
   * 모름을 빼고 흰 테를 "오차 밖"으로 두면 저절로 나오기는 한다. 하지만 흰색을 찾을 때
   * 흰 테 자체가 맞아 버려서, 팔레트가 무슨 색이든 모든 스포이드에 표시가 뜬다.
   */
  function picks(ctx, list, k) {
    for (const p of (list || [])) {
      if (!p || p.slot < 0) continue;
      // 흰 테 안쪽 — 색이 비치는 부분의 가장자리를 따라 긋는다
      const r = Math.max(3, p.r - 8 * k);
      const trace = () => { ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); };
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = 'rgba(0,0,0,.55)';
      ctx.lineWidth = 4 * k;
      trace(); ctx.stroke();
      ctx.strokeStyle = (SLOT[p.slot] || SLOT[0]).line;
      ctx.lineWidth = 2 * k;
      trace(); ctx.stroke();
    }
  }

  /**
   * 스포이드 셋을 잇는 삼각형 — 연한 점선.
   *
   * 세 스포이드의 상대 자리는 시도하는 동안 안 바뀐다. 그 모양이 눈에 들어와 있으면
   * "이 배치로 세 색을 어떻게 걸칠까"를 가늠하기 쉬워진다.
   *
   * 한때 여기에 **답이 되는 삼각형**까지 그렸다 — 소용돌이 위에서 이 삼각형과 닮은
   * 자리를 찾아 주는 기능이다. 계산은 맞았지만 쓸 만하지 않아 접었다. 자세한 사정은
   * dye.js 의 findTriangle 머리말에 적어 두었다.
   */
  function triangle(ctx, t, k) {
    if (!t || !t.pins || t.pins.length < 3) return;
    ctx.save();
    ctx.setLineDash([5 * k, 5 * k]);
    ctx.strokeStyle = 'rgba(0,0,0,.45)';
    ctx.lineWidth = 3.5 * k;
    ctx.beginPath();
    ctx.moveTo(t.pins[0].x, t.pins[0].y);
    ctx.lineTo(t.pins[1].x, t.pins[1].y);
    ctx.lineTo(t.pins[2].x, t.pins[2].y);
    ctx.closePath();
    ctx.stroke();
    ctx.strokeStyle = 'rgba(255,255,255,.55)';
    ctx.lineWidth = 1.5 * k;
    ctx.stroke();
    ctx.restore();
  }

  /**
   * @param ctx  캔버스 2d 문맥 (이미 배율이 걸려 있어도 된다)
   * @param W,H  그릴 영역 크기 (CSS 픽셀)
   * @param p    {status, tone, chips, box, regions, tri, picks} — 좌표는 화면 기준.
   *             marks 도 실려 오지만 화면에는 그리지 않는다 — 리모콘 창에만 글로 적는다.
   * @param k    축소 배율. 미리보기는 1보다 작다.
   */
  function draw(ctx, W, H, p, k) {
    const s = k || 1;
    ctx.clearRect(0, 0, W, H);
    const d = p || {};
    banner(ctx, W, d.status, d.tone, s);
    chips(ctx, W, d.chips, s, 54 * s);
    paletteBox(ctx, d.box, s);
    regions(ctx, d.regions, s);
    triangle(ctx, d.tri, s);
    picks(ctx, d.picks, s);
  }

  const API = { draw: draw, SLOT: SLOT };
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  else root.dyeDraw = API;
})(typeof window !== 'undefined' ? window : globalThis);
