$ErrorActionPreference = "Stop"

function Write-Resolution($Width, $Height) {
    $w = [Math]::Max(640, [int]$Width)
    $h = [Math]::Max(480, [int]$Height)
    if (($w % 2) -ne 0) { $w -= 1 }
    if (($h % 2) -ne 0) { $h -= 1 }
    Write-Output "$w $h"
}

if ($env:NOLF2_CN_WIDTH -and $env:NOLF2_CN_HEIGHT) {
    Write-Resolution $env:NOLF2_CN_WIDTH $env:NOLF2_CN_HEIGHT
    exit 0
}

$configPath = Join-Path (Get-Location) "NOLF2_CN_Window.cfg"
if (Test-Path -LiteralPath $configPath) {
    $config = @{}
    foreach ($line in Get-Content -LiteralPath $configPath -ErrorAction Stop) {
        if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\d+)\s*$") {
            $config[$matches[1].ToLowerInvariant()] = [int]$matches[2]
        }
    }
    if ($config.ContainsKey("width") -and $config.ContainsKey("height")) {
        Write-Resolution $config["width"] $config["height"]
        exit 0
    }
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class Nolf2Screen {
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();

    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);
}
"@

try {
    [void][Nolf2Screen]::SetProcessDPIAware()
} catch {
}

$desktopW = [Nolf2Screen]::GetSystemMetrics(0)
$desktopH = [Nolf2Screen]::GetSystemMetrics(1)
if ($desktopW -le 0 -or $desktopH -le 0) {
    Write-Resolution 1280 720
    exit 0
}

# IMPORTANT (confirmed 2026-07-13): launching this game/Modernizer path directly at a
# HIGH windowed resolution crashes on level load (2800x1800 and 2500x1406 crashed;
# 1920x1200-class also proved unreliable). BUT raising the resolution from the in-game
# video menu -- which does a clean device reset -- works fine, even up to 4K. So always
# START SMALL and let the player bump it up in-game. Default startup = 1280x720 (clamped
# to the desktop). Override via NOLF2_CN_Window.cfg or NOLF2_CN_WIDTH/HEIGHT only if you
# know a larger launch mode is stable on your machine.
$startW = [Math]::Min(1280, $desktopW)
$startH = [Math]::Min(720, $desktopH)
Write-Resolution $startW $startH
