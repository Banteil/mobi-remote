# 스크린샷에서 글자를 읽어 낸다.
#
# 윈도우가 들고 있는 OCR(Windows.Media.Ocr)을 쓴다. 한국어 인식기가 이미 깔려 있어
# 따로 설치할 것이 없다 — 받아 올 것도, 의존성도 없다.
#
#   powershell -NoProfile -File tools/ocr.ps1 -Dir <폴더> [-Left 1200 -Top 380 -Width 700 -Height 460] [-Scale 2]
#   powershell -NoProfile -File tools/ocr.ps1 -Path <png> ...
#
# 그림 하나마다 JSON 한 줄을 내보낸다(JSON Lines). 줄마다 글자와 그 자리(x, y)가 들어 있고,
# 자리는 **원본 그림 기준**으로 되돌려 준다 — 잘라내거나 키워도 좌표는 원본 그대로다.
#
# 자리를 주지 않으면 그림 전체를 읽는다. Scale은 확대 배율이다. 게임 글씨가 작아
# 2배로 키워 읽으면 눈에 띄게 정확해진다.

param(
  [string]$Path,
  [string]$Dir,
  [int]$Left = 0, [int]$Top = 0, [int]$Width = 0, [int]$Height = 0,
  [double]$Scale = 1.0,
  [string]$Lang = 'ko'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null

# WinRT의 비동기 호출을 기다리는 도구. PowerShell 5.1에는 await가 없어 이렇게 푼다.
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
  $task = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
  $task.Wait(-1) | Out-Null
  $task.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime] | Out-Null

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage((New-Object Windows.Globalization.Language $Lang))
if ($null -eq $engine) { throw "OCR 인식기가 없습니다: $Lang" }

function Read-Shot($p) {
  $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
  $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
  $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])

  $w = $Width; $h = $Height
  if ($w -le 0) { $w = $decoder.PixelWidth - $Left }
  if ($h -le 0) { $h = $decoder.PixelHeight - $Top }

  # 확대가 먼저, 잘라내기가 나중이다 — Bounds는 확대된 그림 기준으로 준다.
  $tr = New-Object Windows.Graphics.Imaging.BitmapTransform
  $tr.ScaledWidth = [uint32]([Math]::Round($decoder.PixelWidth * $Scale))
  $tr.ScaledHeight = [uint32]([Math]::Round($decoder.PixelHeight * $Scale))
  $tr.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Fant
  $bounds = New-Object Windows.Graphics.Imaging.BitmapBounds
  $bounds.X = [uint32]([Math]::Round($Left * $Scale))
  $bounds.Y = [uint32]([Math]::Round($Top * $Scale))
  $bounds.Width = [uint32]([Math]::Round($w * $Scale))
  $bounds.Height = [uint32]([Math]::Round($h * $Scale))
  $tr.Bounds = $bounds

  $bmp = Await ($decoder.GetSoftwareBitmapAsync(
    [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
    $tr,
    [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])

  $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
  $stream.Dispose()

  $out = New-Object System.Collections.ArrayList
  foreach ($line in $res.Lines) {
    $words = New-Object System.Collections.ArrayList
    foreach ($wd in $line.Words) {
      [void]$words.Add([pscustomobject]@{
        t = $wd.Text
        x = [int][Math]::Round($Left + $wd.BoundingRect.X / $Scale)
        y = [int][Math]::Round($Top + $wd.BoundingRect.Y / $Scale)
        w = [int][Math]::Round($wd.BoundingRect.Width / $Scale)
        h = [int][Math]::Round($wd.BoundingRect.Height / $Scale)
      })
    }
    if ($words.Count -eq 0) { continue }
    [void]$out.Add([pscustomobject]@{
      text = $line.Text
      x = $words[0].x
      y = $words[0].y
      h = ($words | Measure-Object -Property h -Maximum).Maximum
      words = $words
    })
  }

  ConvertTo-Json @{ file = (Split-Path $p -Leaf); lines = $out } -Depth 6 -Compress
}

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($Dir) {
  foreach ($f in (Get-ChildItem -Path $Dir -Filter *.png | Sort-Object Name)) { Read-Shot $f.FullName }
} elseif ($Path) {
  Read-Shot (Resolve-Path $Path).Path
} else {
  throw '-Path 또는 -Dir 가 필요합니다.'
}
