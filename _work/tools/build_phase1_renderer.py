"""
Phase 1 build: compile the renderer proxy, stage CSHELL + glyph-atlas DTX, pack a REZ,
and write a run script. Windows-only (needs MSVC + LithRez).

Run order:
  1. python _work\\tools\\build_cn_glyph_atlas.py     (produces the atlas DTX/MET)
  2. python _work\\tools\\build_phase1_renderer.py     (this script)
  3. _work\\run_phase1_renderer.bat                    (launch and look for one Chinese
                                                        glyph near the top-left of the screen)
"""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROXY_DIR = ROOT / "_work" / "proxy_cshell_renderer"
PROXY_DLL = PROXY_DIR / "bin" / "CSHELL.DLL"
BASE_CSHELL = ROOT / "_work" / "extract_modernizer" / "CSHELL.DLL"
# The proxy reads MET/STRINGS/CSHELL_ORIG and writes runtime.log from <root>\NOLF2_CN\
# (clean layout, no _work cruft in a release). Keep these in sync with the paths hardcoded
# in cshell_proxy_renderer.cpp.
CN_DIR = ROOT / "NOLF2_CN"
ORIG_CSHELL_COPY = CN_DIR / "CSHELL_MODERNIZER_ORIG.DLL"
FONTS_SRC = ROOT / "_work" / "build_cn_renderer" / "stage" / "Interface" / "Fonts"
ATLAS_DTX = FONTS_SRC / "NOLF2CN_ATLAS.DTX"
ATLAS_MET = FONTS_SRC / "NOLF2CN_ATLAS.MET"
STRINGS_BIN = FONTS_SRC / "NOLF2CN_STRINGS.bin"
OUT_DIR = ROOT / "_work" / "build_phase1_renderer"
STAGE = OUT_DIR / "stage"
OUT_REZ = OUT_DIR / "NOLF2_CN_PHASE1.rez"
LITHREZ = ROOT / "Tools" / "Bin" / "LithRez.exe"


def build_assets():
    # regenerate the glyph atlas (DTX/MET) and the English->Chinese dictionary (.bin)
    import sys
    for tool in ("build_cn_glyph_atlas.py", "build_cn_dict.py"):
        subprocess.run([sys.executable, str(ROOT / "_work" / "tools" / tool)], cwd=ROOT, check=True)


def build_proxy():
    subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(PROXY_DIR / "build_proxy.ps1")],
        cwd=ROOT, check=True,
    )


def stage():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (STAGE / "Interface" / "Fonts").mkdir(parents=True, exist_ok=True)
    for f in (ATLAS_DTX, ATLAS_MET, STRINGS_BIN):
        if not f.exists():
            raise SystemExit(f"missing asset: {f}\n  run build_cn_glyph_atlas.py + build_cn_dict.py first")
    # REZ payload: proxy CSHELL + atlas DTX (DTX is loaded via the engine VFS)
    shutil.copy2(PROXY_DLL, STAGE / "CSHELL.DLL")
    shutil.copy2(ATLAS_DTX, STAGE / "Interface" / "Fonts" / "NOLF2CN_ATLAS.DTX")
    # NOLF2_CN\ : files the proxy reads directly from disk at runtime
    CN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ATLAS_MET, CN_DIR / "NOLF2CN_ATLAS.MET")
    shutil.copy2(STRINGS_BIN, CN_DIR / "NOLF2CN_STRINGS.bin")
    shutil.copy2(BASE_CSHELL, ORIG_CSHELL_COPY)


def pack():
    if OUT_REZ.exists():
        OUT_REZ.unlink()
    subprocess.run([str(LITHREZ), "cv", str(OUT_REZ), "."], cwd=STAGE, check=True)
    listing = subprocess.run([str(LITHREZ), "v", str(OUT_REZ)], cwd=ROOT, check=True,
                             capture_output=True, text=True, errors="replace")
    (OUT_DIR / "listing.txt").write_text(listing.stdout, encoding="utf-8", newline="")


def write_run_script():
    script = ROOT / "_work" / "run_phase1_renderer.bat"
    cmd_name = OUT_DIR / "launchcmds_phase1.txt"
    rel_rez = OUT_REZ.relative_to(ROOT)
    rel_cmd = cmd_name.relative_to(ROOT)
    # The engine picks window/fullscreen + resolution from the COMMAND LINE at boot (not from
    # autoexec.cfg). build_launch_cmdfile.ps1 strips the launcher's display-override tail
    # (esp. "+RestoreDefaults 1", which resets the whole profile every launch) and re-applies
    # the player's saved display settings from autoexec.cfg. See chinese_note.md 2026-07-13.
    script.write_text(
        '@echo off\r\n'
        'setlocal\r\n'
        'cd /d "%~dp0.."\r\n'
        'del "NOLF2_CN\\runtime.log" 2>nul\r\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -File "_work\\tools\\build_launch_cmdfile.ps1"\r\n'
        f'start "" ".\\Lithtech.exe" -cmdfile "{rel_cmd}"\r\n',
        encoding="ascii", newline="",
    )
    return script


def main():
    build_assets()
    build_proxy()
    stage()
    pack()
    script = write_run_script()
    print(f"proxy:  {PROXY_DLL}")
    print(f"rez:    {OUT_REZ}")
    print(f"run:    {script}")
    print("launch the bat; the game starts with its own DISPLAY.CFG settings (fullscreen if set).")


if __name__ == "__main__":
    main()
