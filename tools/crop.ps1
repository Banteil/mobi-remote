# 그림의 한 조각을 잘라 저장한다. 눈으로 확인할 때, 그리고 OCR에 넘기기 전에 다듬을 때 쓴다.
#
#   powershell -NoProfile -File tools/crop.ps1 -Path <png> -Out <png> -Left 1190 -Top 380 -Width 720 -Height 480 [-Scale 2]
#
# 게임 화면은 어두운 바탕에 밝은 글씨다. OCR은 반대(밝은 바탕에 어두운 글씨)를 더 잘 읽는다.
# -Threshold 0.35 를 주면 그 밝기보다 밝은 점을 글씨로 보고 흑백으로 뒤집어 준다.
# 회색으로 흐릿하게 적힌 '필요 개수' 같은 것이 이 손질로 살아난다.

param(
  [Parameter(Mandatory = $true)][string]$Path,
  [Parameter(Mandatory = $true)][string]$Out,
  [int]$Left = 0, [int]$Top = 0, [int]$Width = 0, [int]$Height = 0,
  [double]$Scale = 1.0,
  [double]$Threshold = 0
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing | Out-Null

$src = [System.Drawing.Image]::FromFile((Resolve-Path $Path).Path)
try {
  if ($Width -le 0) { $Width = $src.Width - $Left }
  if ($Height -le 0) { $Height = $src.Height - $Top }
  $ow = [int][Math]::Round($Width * $Scale)
  $oh = [int][Math]::Round($Height * $Scale)
  $dst = New-Object System.Drawing.Bitmap $ow, $oh, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($dst)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.DrawImage($src, (New-Object System.Drawing.Rectangle 0, 0, $ow, $oh),
    (New-Object System.Drawing.Rectangle $Left, $Top, $Width, $Height), [System.Drawing.GraphicsUnit]::Pixel)
  $g.Dispose()

  if ($Threshold -gt 0) {
    $rect = New-Object System.Drawing.Rectangle 0, 0, $ow, $oh
    $data = $dst.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadWrite, $dst.PixelFormat)
    $n = [Math]::Abs($data.Stride) * $oh
    $buf = New-Object byte[] $n
    [System.Runtime.InteropServices.Marshal]::Copy($data.Scan0, $buf, 0, $n)
    $cut = $Threshold * 255
    for ($i = 0; $i -lt $n; $i += 4) {
      # 밝기는 사람 눈에 맞춘 가중치로 — 붉은 글씨도 충분히 밝게 잡힌다.
      $lum = 0.299 * $buf[$i + 2] + 0.587 * $buf[$i + 1] + 0.114 * $buf[$i]
      $v = if ($lum -ge $cut) { [byte]0 } else { [byte]255 }   # 밝은 점이 글씨 → 검게
      $buf[$i] = $v; $buf[$i + 1] = $v; $buf[$i + 2] = $v; $buf[$i + 3] = 255
    }
    [System.Runtime.InteropServices.Marshal]::Copy($buf, 0, $data.Scan0, $n)
    $dst.UnlockBits($data)
  }

  $dst.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
  $dst.Dispose()
  Write-Output "$Out ($ow x $oh)"
} finally { $src.Dispose() }
