$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$OutDir = Join-Path $Root "_work\proxy_cshell_renderer\bin"
$ObjDir = Join-Path $Root "_work\proxy_cshell_renderer\obj"
$Src = Join-Path $Root "_work\proxy_cshell_renderer\cshell_proxy_renderer.cpp"
$VcVars = "C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars32.bat"

New-Item -ItemType Directory -Force -Path $OutDir, $ObjDir | Out-Null

$Cmd = 'call "' + $VcVars + '" && cl /nologo /utf-8 /W3 /O2 /EHsc- /MT /LD "' + $Src + '" /Fo"' + $ObjDir + '\\" /Fe"' + $OutDir + '\CSHELL.DLL" /link /NOLOGO user32.lib /MACHINE:X86 /BASE:0x50000000 /MAP:"' + $OutDir + '\CSHELL.map" /OUT:"' + $OutDir + '\CSHELL.DLL"'

cmd.exe /c $Cmd
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Host "Built $OutDir\CSHELL.DLL"
