'use strict';
/**
 * Ctrl+Alt+WASD 로 마우스 커서를 1px 옮긴다.
 *
 * 염색할 때 스포이드를 원하는 색에 정확히 얹으려면 한 점 차이를 다퉈야 하는데,
 * 손으로 마우스를 미는 것으로는 그 한 점이 잘 안 맞는다.
 *
 * 오른손으로 마우스를 쥔 채 왼손으로 누르는 쓰임이라 WASD 다. 화살표는 오른손 쪽에
 * 있어서 마우스를 놓아야 한다. Ctrl+Alt 를 얹은 것은 맨 Ctrl+WASD 가 전부 흔한
 * 단축키(전체선택·저장·닫기)와 겹치기 때문이다.
 *
 * ── 스스로 움직이지 않는다 ─────────────────────────────────
 * **사람이 누른 만큼만** 움직인다. 색을 찾아 저절로 가는 기능이 아니다.
 * 게임에 무언가를 시키는 일은 전부 공식 커넥터로만 한다.
 *
 * ── 왜 별도 프로세스인가 ───────────────────────────────────
 * 이 기능은 관리자 권한을 요구한다. 마비노기 모바일이 관리자로 돌기 때문에,
 * 권한이 낮은 쪽이 건 단축키는 게임이 앞에 있는 동안 아예 불리지 않는다(UIPI).
 * 실측 — 리모콘에 포커스가 있을 때는 먹고, 게임에 있을 때는 안 먹었다.
 *
 * 그렇다고 리모콘 전체를 관리자로 띄우면 **염색 화면 읽기가 죽는다.**
 * 실측 — getUserMedia 가 'Could not start video source' 로 실패한다. Chromium 의
 * 캡처 경로가 관리자 권한에서 제대로 서지 못한다.
 *
 * 그래서 나눈다. 리모콘 본체는 일반 권한 그대로 두고(캡처가 멀쩡하다),
 * **단축키를 잡고 커서를 옮기는 작은 조각만** 관리자로 띄운다. 켤 때 UAC 를 한 번
 * 묻고, 그 뒤로는 앱을 껐다 켜도 UAC 가 다시 뜨지 않는다.
 *
 * ── 어떻게 끄나 ────────────────────────────────────────────
 * 관리자로 뜬 프로세스는 권한이 낮은 이쪽에서 죽이지 못한다. 그래서 신호로 끈다 —
 * 켤 때 표시 파일을 만들어 두고, 끌 때 그 파일을 지운다. 헬퍼는 그 파일이 사라지거나
 * 리모콘이 죽으면 스스로 물러난다. 리모콘이 갑자기 죽어도 남지 않는다.
 */
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const paths = require('./paths');

/** 켜져 있다는 표시. 이 파일이 사라지면 헬퍼가 물러난다. */
const FLAG = paths.dataPath('nudge.on');
/** 헬퍼 본문. asar 안에서는 PowerShell 이 못 읽으므로 데이터 폴더에 풀어 둔다. */
const SCRIPT = paths.dataPath('nudge.ps1');

/**
 * 헬퍼가 할 일.
 *
 * RegisterHotKey 로 Ctrl+Alt+W/A/S/D 넷을 잡고, 메시지 고리를 돌며 WM_HOTKEY 를 받아
 * 커서를 민다. 화면에 뜨지 않는 메시지 전용 창을 쓴다 — 단축키를 받으려면 창 손잡이가 필요하다.
 *
 * 0.7초마다 물러날 때가 됐는지 본다. 표시 파일이 없어졌거나 리모콘이 죽었으면 끝낸다.
 */
const PS = `
param([int]$ParentPid, [string]$Flag)
Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition @"
using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

// 메시지만 받는 창. 화면에 뜨지 않는다.
//
// 처음에는 Form 을 쓰되 보이지 않게 막았는데, 그러면 **창 손잡이가 아예 안 만들어져서**
// 단축키 등록이 통째로 건너뛰어졌다. NativeWindow 로 손잡이만 직접 만들면 그럴 일이 없다.
public class Nudge : NativeWindow {
  [DllImport("user32.dll")] static extern bool RegisterHotKey(IntPtr h, int id, uint mod, uint vk);
  [DllImport("user32.dll")] static extern bool UnregisterHotKey(IntPtr h, int id);
  const uint MOD_ALT = 0x1, MOD_CONTROL = 0x2;
  const int WM_HOTKEY = 0x0312;

  int pid; string flag; Timer watch;
  public int Taken = 0;

  public Nudge(int parentPid, string flagPath) {
    pid = parentPid; flag = flagPath;
    CreateHandle(new CreateParams());

    uint mod = MOD_CONTROL | MOD_ALT;
    if (RegisterHotKey(Handle, 1, mod, 0x57)) Taken++;   // W
    if (RegisterHotKey(Handle, 2, mod, 0x53)) Taken++;   // S
    if (RegisterHotKey(Handle, 3, mod, 0x41)) Taken++;   // A
    if (RegisterHotKey(Handle, 4, mod, 0x44)) Taken++;   // D

    watch = new Timer();
    watch.Interval = 700;
    watch.Tick += delegate { Check(); };
    watch.Start();
  }

  // 표시 파일이 사라졌거나 리모콘이 죽었으면 물러난다.
  void Check() {
    bool alive = true;
    try { System.Diagnostics.Process.GetProcessById(pid); } catch { alive = false; }
    if (alive && System.IO.File.Exists(flag)) return;
    for (int i = 1; i <= 4; i++) UnregisterHotKey(Handle, i);
    watch.Stop();
    Application.ExitThread();
  }

  protected override void WndProc(ref Message m) {
    if (m.Msg == WM_HOTKEY) {
      Point p = Cursor.Position;
      switch (m.WParam.ToInt32()) {
        case 1: p.Y -= 1; break;
        case 2: p.Y += 1; break;
        case 3: p.X -= 1; break;
        case 4: p.X += 1; break;
      }
      Cursor.Position = p;
    }
    base.WndProc(ref m);
  }
}
"@
$n = New-Object Nudge($ParentPid, $Flag)
if ($n.Taken -lt 4) { [Console]::Error.WriteLine("hotkey " + $n.Taken + "/4") }
[System.Windows.Forms.Application]::Run()
`;

/**
 * 헬퍼를 관리자 권한으로 띄운다. UAC 창이 한 번 뜬다.
 *
 * Start-Process 를 시키는 바깥 PowerShell 은 **동기로** 부른다. 던져 놓고 넘어가면
 * 실제로 떴는지 알 수 없고, 거절당한 것도 모른 채 켜진 것처럼 보인다.
 *
 * @returns {{ok:boolean, error?:string}}
 */
function start() {
  try {
    fs.mkdirSync(path.dirname(FLAG), { recursive: true });
    fs.writeFileSync(SCRIPT, PS, 'utf8');
    fs.writeFileSync(FLAG, String(process.pid), 'utf8');
  } catch (err) {
    return { ok: false, error: '준비하지 못했습니다: ' + err.message };
  }

  const args = "'-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden'," +
    "'-File','" + SCRIPT.replace(/'/g, "''") + "'," +
    "'" + process.pid + "','" + FLAG.replace(/'/g, "''") + "'";
  const outer = 'try { Start-Process -FilePath powershell -ArgumentList ' + args +
    ' -Verb RunAs -WindowStyle Hidden; exit 0 } catch { exit 1 }';

  try {
    execFileSync('powershell', ['-NoProfile', '-NonInteractive', '-EncodedCommand',
      Buffer.from(outer, 'utf16le').toString('base64')],
    { stdio: 'ignore', windowsHide: true, timeout: 120000 });
    return { ok: true };
  } catch (_) {
    try { fs.unlinkSync(FLAG); } catch (__) { /* 넘긴다 */ }
    return { ok: false, error: '관리자 권한을 받지 못했습니다' };
  }
}

/** 표시 파일을 지운다. 헬퍼는 0.7초 안에 스스로 물러난다. */
function stop() {
  try { fs.unlinkSync(FLAG); } catch (_) { /* 이미 없다 */ }
}

function running() {
  try { return fs.existsSync(FLAG); } catch (_) { return false; }
}

module.exports = { start, stop, running, FLAG };
