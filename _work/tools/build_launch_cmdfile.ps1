# Build the -cmdfile for the CN renderer launch (SAFE WINDOWED mode).
#
# History: forcing "+Windowed 0" (exclusive fullscreen) at boot crashes this game on the
# user's GPU, so we do NOT use it. We launch WINDOWED at a modest, proven-stable size; the
# player can raise the resolution from the in-game video menu afterwards if they want.
#
# What we do:
#   1. inherit the base launchcmds.txt (rez / mod list),
#   2. strip the launcher's display-override tail -- especially "+RestoreDefaults 1", which
#      resets the whole profile (controls, sound, display) to defaults on EVERY launch,
#   3. force a safe windowed mode (+Windowed 1 at 1280x720),
#   4. append the CN renderer REZ.

$ErrorActionPreference = 'Stop'
$Root = (Get-Location).Path

$base = Get-Content -Raw (Join-Path $Root 'launchcmds.txt')
foreach ($p in '\+RestoreDefaults\s+\S+', '\+ScreenWidth\s+\S+', '\+ScreenHeight\s+\S+', '\+BitDepth\s+\S+', '\+Windowed\s+\S+') {
    $base = $base -replace $p, ''
}
$base = ($base -replace '\s+', ' ').Trim()

$win = '1'
$sw  = '1280'
$sh  = '720'
$bd  = '32'

$rez  = '_work\build_phase1_renderer\NOLF2_CN_PHASE1.rez'
$line = "$base +Windowed $win +ScreenWidth $sw +ScreenHeight $sh +BitDepth $bd -rez $rez"
$out  = Join-Path $Root '_work\build_phase1_renderer\launchcmds_phase1.txt'
Set-Content -NoNewline -Encoding ASCII -Path $out -Value $line
Write-Output ("[launch] windowed {0}x{1} (raise resolution in-game if you want)" -f $sw, $sh)
