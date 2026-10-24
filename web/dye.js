'use strict';
/* 색 코드 변환 (염색 탭의 색 편집이 쓴다).
 * 예전 리모콘은 여기서 화면 판정(팔레트·색 찾기·추적)까지 했지만, 지금 판정은 파이썬(mabi/dye)이 하고
 * 화면은 결과만 받아 그린다 (gui_app/dye_service.py). */

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

const DYE_API = { hexToRgb, rgbToHex };

if (typeof module !== 'undefined' && module.exports) module.exports = DYE_API;
else if (typeof window !== 'undefined') window.dye = DYE_API;
