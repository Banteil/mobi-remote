'use strict';
/**
 * 창·트레이 아이콘을 원본 그림 한 장에서 만든다.
 *
 *   npx electron tools/make-icon.js <원본.png>
 *   npx electron tools/make-icon.js            (기본: app/renderer/icon-source.png)
 *
 * 결과
 *   app/renderer/icon.png    256×256  창 아이콘 · 나중에 .ico 를 뽑을 원본
 *   app/renderer/tray.png     32×32   트레이 아이콘
 *
 * ── 왜 Electron 으로 도나 ──────────────────────────────────
 * 이 프로젝트는 런타임 외부 패키지가 하나도 없다(dependencies: {}). 이미지 크기를 줄이려고
 * sharp 같은 것을 들이면 그 원칙이 깨진다. Electron 의 nativeImage 가 리사이즈를 해 주므로
 * 이미 갖고 있는 것으로 끝낸다. 이 파일은 빌드 도구라 배포물에는 들어가지 않는다.
 *
 * ── 왜 32px 를 따로 만드나 ────────────────────────────────
 * 트레이는 16~32px로 그려진다. 1254px 원본을 그대로 주면 Electron 이 매번 줄여야 하고,
 * 파일도 1.7MB라 앱 시작이 그만큼 느려진다. 미리 줄여 두면 그릴 때 손댈 게 없다.
 */
const fs = require('fs');
const path = require('path');
const { app, nativeImage } = require('electron');

const ROOT = path.join(__dirname, '..');
const OUT_DIR = path.join(ROOT, 'app', 'renderer');
const DEFAULT_SRC = path.join(OUT_DIR, 'icon-source.png');

const TARGETS = [
  { file: 'icon.png', size: 256 },
  { file: 'tray.png', size: 32 },
];

function main() {
  const src = process.argv[2] && !process.argv[2].startsWith('-')
    ? path.resolve(process.argv[2])
    : DEFAULT_SRC;

  if (!fs.existsSync(src)) {
    console.error('원본을 찾을 수 없습니다: ' + src);
    app.exit(1);
    return;
  }

  const img = nativeImage.createFromPath(src);
  if (img.isEmpty()) {
    console.error('이미지를 읽지 못했습니다 (PNG/JPEG만 됩니다): ' + src);
    app.exit(1);
    return;
  }

  const s = img.getSize();
  console.log('원본  ' + s.width + '×' + s.height + '  ' + Math.round(fs.statSync(src).size / 1024) + 'KB');

  if (s.width !== s.height) {
    console.log('  주의: 정사각형이 아닙니다. 아이콘이 찌그러집니다.');
  }
  if (s.width < 256) {
    console.log('  주의: 256px보다 작아 창 아이콘이 흐릿할 수 있습니다.');
  }

  for (const t of TARGETS) {
    // quality: 'best' 를 주지 않으면 축소 시 계단이 심하게 진다
    const out = img.resize({ width: t.size, height: t.size, quality: 'best' });
    const p = path.join(OUT_DIR, t.file);
    fs.writeFileSync(p, out.toPNG());
    console.log('  → ' + t.file + '  ' + t.size + '×' + t.size + '  ' + Math.round(fs.statSync(p).size / 1024) + 'KB');
  }

  app.exit(0);
}

app.whenReady().then(main);
