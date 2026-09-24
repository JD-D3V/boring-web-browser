# Capture the real browser window, frame and all, to a PNG.
#
#   powershell -ExecutionPolicy Bypass -File capture_native.ps1 `
#       -Out shot.png [-Url chrome://boring-newtab] [-Width 1404] [-Height 631]
#       [-Profile E:\tmp\p] [-Dark] [-Scale 100] [-ExtraArgs "--foo"] [-Wait 6]
#
# Uses PrintWindow with PW_RENDERFULLCONTENT so the GPU-composited page
# comes out too. The window is left running only for the capture.

param(
  [string]$Out = "shot.png",
  [string]$Url = "chrome://boring-newtab",
  [int]$Width = 1404,
  [int]$Height = 631,
  [string]$ProfileDir = "",
  [switch]$Dark,
  [int]$Wait = 7,
  [string[]]$ExtraArgs = @(),
  [string]$Chrome = "E:\ung\build\src\out\Default\chrome.exe",
  [switch]$Keep
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int t, bool repaint);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  public static System.Collections.Generic.List<IntPtr> Windows() {
    var found = new System.Collections.Generic.List<IntPtr>();
    EnumWindows(delegate(IntPtr h, IntPtr p) { found.Add(h); return true; }, IntPtr.Zero);
    return found;
  }
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int v);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

try { [Win]::SetProcessDpiAwareness(2) | Out-Null } catch {}

if ($ProfileDir -eq "") {
  $ProfileDir = Join-Path $env:TEMP ("boring-shot-" + [guid]::NewGuid().ToString("N").Substring(0,8))
}
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$argv = @(
  "--user-data-dir=$ProfileDir",
  "--no-first-run",
  "--no-default-browser-check",
  "--window-size=$Width,$Height",
  "--window-position=40,40"
)
if ($Dark) { $argv += "--force-dark-mode"; $argv += "--enable-features=WebContentsForceDark" }
$argv += $ExtraArgs
$argv += $Url

$proc = Start-Process -FilePath $Chrome -ArgumentList $argv -PassThru
Start-Sleep -Seconds $Wait

# The window we want is the browser frame of the build we just started,
# never another Chrome the person happens to have open. Match on the
# executable path, and take the biggest visible titled window.
$h = [IntPtr]::Zero
for ($i = 0; $i -lt 25; $i++) {
  $ours = @{}
  foreach ($c in (Get-Process -Name chrome -ErrorAction SilentlyContinue)) {
    try { if ($c.Path -eq $Chrome) { $ours[[uint32]$c.Id] = $true } } catch {}
  }
  $best = 0
  foreach ($w in [Win]::Windows()) {
    if (-not [Win]::IsWindowVisible($w)) { continue }
    if ([Win]::GetWindowTextLength($w) -eq 0) { continue }
    $pid32 = [uint32]0
    [Win]::GetWindowThreadProcessId($w, [ref]$pid32) | Out-Null
    if (-not $ours.ContainsKey($pid32)) { continue }
    $r = New-Object Win+RECT
    if (-not [Win]::GetWindowRect($w, [ref]$r)) { continue }
    $area = ($r.Right - $r.Left) * ($r.Bottom - $r.Top)
    if (($r.Right - $r.Left) -gt 400 -and $area -gt $best) { $best = $area; $h = $w }
  }
  if ($h -ne [IntPtr]::Zero) { break }
  Start-Sleep -Milliseconds 700
}
if ($h -eq [IntPtr]::Zero) { Write-Error "no browser window appeared" }

[Win]::ShowWindow($h, 9) | Out-Null   # SW_RESTORE
[Win]::SetForegroundWindow($h) | Out-Null
[Win]::MoveWindow($h, 40, 40, $Width, $Height, $true) | Out-Null
Start-Sleep -Seconds 2

$r = New-Object Win+RECT
[Win]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left
$t = $r.Bottom - $r.Top

$bmp = New-Object System.Drawing.Bitmap($w, $t)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
[Win]::PrintWindow($h, $dc, 2) | Out-Null   # PW_RENDERFULLCONTENT
$g.ReleaseHdc($dc)
$g.Dispose()

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

Write-Output ("saved {0} {1}x{2}" -f $Out, $w, $t)

if (-not $Keep) {
  try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
  Get-Process -Name chrome -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -eq $Chrome } | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1
  Remove-Item -Recurse -Force $ProfileDir -ErrorAction SilentlyContinue
}
