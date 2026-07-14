"""
Assemble the integrated release: Modernizer 2 core + Simplified-Chinese renderer.

Run this AFTER `python _work\\tools\\build_phase1_renderer.py` (which recompiles the proxy
with the NOLF2_CN\\ paths and produces the REZ + NOLF2_CN\\ runtime files).

For a translation-only update (proxy + glyph atlas unchanged, e.g. only edited zh with no
new glyphs), you can skip the phase1 rebuild entirely: this script falls back to the REZ
already installed in NOLF2_CN\\ and just repackages it with the freshly-built STRINGS.bin.

Output: <game root>\\NOLF2_简体中文汉化_v1.1.zip
The zip contents overlay directly onto a CLEAN NOLF2 1.3 install (Modernizer is bundled).
"""
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "v1.1"
REL_NAME = f"NOLF2_简体中文汉化_{VERSION}"
STAGE = ROOT / "_work" / "release_stage" / REL_NAME
OUT_ZIP = ROOT / f"{REL_NAME}.zip"

CN_DIR_SRC = ROOT / "NOLF2_CN"          # produced by build_phase1_renderer stage()
# Prefer a fresh phase1 build; if absent (e.g. a translation-only update where the proxy
# and glyph atlas are unchanged), reuse the already-installed REZ in NOLF2_CN\.
CN_REZ_SRC = ROOT / "_work" / "build_phase1_renderer" / "NOLF2_CN_PHASE1.rez"
if not CN_REZ_SRC.exists():
    CN_REZ_SRC = CN_DIR_SRC / "NOLF2_CN.rez"

# Modernizer 2 Beta 2c core files (added/replaced on top of vanilla 1.3). Missing ones are
# skipped with a warning (e.g. optional readmes).
MODERNIZER_ROOT_FILES = [
    "Lithtech.exe", "SDL2.dll", "NOLF2Srv.exe", "osslicenses.txt",
    "Update_v1x3_GUI.REZ", "ModernizerReadme.txt", "readmy_Modernizer2_Beta_2GUI_EN.txt",
    "JServerDir.dll", "JServerInfo.txt",
]
MODERNIZER_SUBPATHS = [
    "Custom/Mods/Modernizer/MODERNIZER.REZ",
]

# runtime files the proxy reads from NOLF2_CN\ (produced by the build)
CN_RUNTIME = ["NOLF2CN_ATLAS.MET", "NOLF2CN_STRINGS.bin", "CSHELL_MODERNIZER_ORIG.DLL"]

LAUNCHER_BAT = (
    "@echo off\r\n"
    "setlocal\r\n"
    'cd /d "%~dp0"\r\n'
    'if not exist "Lithtech.exe" (\r\n'
    "  echo [!] Copy this package into the NOLF2 game folder first.\r\n"
    "  pause\r\n"
    "  exit /b 1\r\n"
    ")\r\n"
    'if not exist "NOLF2_CN\\launchcmds_cn.txt" (\r\n'
    "  echo [!] NOLF2_CN\\launchcmds_cn.txt missing - re-extract the package.\r\n"
    "  pause\r\n"
    "  exit /b 1\r\n"
    ")\r\n"
    'del "NOLF2_CN\\runtime.log" 2>nul\r\n'
    'start "" ".\\Lithtech.exe" -cmdfile "NOLF2_CN\\launchcmds_cn.txt"\r\n'
)

README = """\
====================================================================
 无人永生 2（No One Lives Forever 2）简体中文汉化  v1.1
 （已内置 Modernizer 2 Beta 2c 核心）
====================================================================

本版更新（v1.1）
--------------------------------------------------------------------
- 统一了句尾标点风格，并修订了部分措辞，使译文更自然。

一、前置要求
--------------------------------------------------------------------
1. 原版游戏 No One Lives Forever 2  1.3 版（纯净安装即可）。
2. 已安装 VC++ 运行库（Modernizer 需要；Win10/11 一般自带）。
   * 本包已内置 Modernizer 2 核心，无需另外安装 Modernizer。

二、安装（覆盖到游戏根目录）
--------------------------------------------------------------------
把本文件夹里的【全部内容】复制到游戏根目录（与 GAME.REZ、NOLF2.exe 同层），
遇到 Custom 文件夹提示合并、Lithtech.exe/SDL2.dll 等提示覆盖，全部选“是”。
（这些会用 Modernizer 版本替换原版对应文件，属正常操作。）

三、启动游戏
--------------------------------------------------------------------
双击【启动汉化版.bat】。
- 自动加载 Modernizer + 简体中文，无需再去 NOLF2.exe 里手动选模组。
- 游戏以窗口 1280x720 启动；想要更大画面，进游戏后从“选项→显示”调高分辨率。
- 请勿使用“独占全屏”：本引擎在部分机型上独占全屏启动会崩溃；窗口模式下把
  分辨率调到与桌面一致即可接近全屏。

四、用 Steam 启动（可选，方便截图）
--------------------------------------------------------------------
Steam → 添加非 Steam 游戏 → 选游戏根目录的 Lithtech.exe；
该条目属性 → 启动选项填：  -cmdfile "NOLF2_CN\\launchcmds_cn.txt"
（起始位置保持游戏根目录）。之后从 Steam 启动即可用覆盖层 + F12 截图。

五、卸载
--------------------------------------------------------------------
删除 NOLF2_CN 文件夹、启动汉化版.bat、以及本包带入的 Modernizer 文件即可。
若要彻底回到原版，请重装游戏。

六、已知情况
--------------------------------------------------------------------
- 少量文本尚未翻译（漏译），不影响流程。
- 不支持独占全屏启动（引擎限制），请用窗口模式。
- 汉化以“运行时自绘中文”实现，不修改游戏基础文本文件，随时删文件即可卸载。
- 内置的 Modernizer 2 版权归其作者所有；本汉化仅为方便安装而一并附带。

====================================================================
"""


def build_launch_cmdfile_text() -> str:
    base = (ROOT / "launchcmds.txt").read_text(encoding="ascii", errors="replace")
    # drop the launcher's "defaults" appendage (starts at +RestoreDefaults) and any stray
    # display/perf flags, plus any previously-appended CN rez.
    idx = base.find("+RestoreDefaults")
    if idx >= 0:
        base = base[:idx]
    for pat in (r"\+RestoreDefaults\s+\S+", r"\+ScreenWidth\s+\S+", r"\+ScreenHeight\s+\S+",
                r"\+BitDepth\s+\S+", r"\+Windowed\s+\S+", r"\+SetPerformanceLevel\s+\S+",
                r"\+GammaR\s+\S+", r"\+GammaG\s+\S+", r"\+GammaB\s+\S+",
                r"-rez\s+\S*NOLF2_CN[^\s]*\.rez"):
        base = re.sub(pat, "", base)
    base = " ".join(base.split())
    return base + " +Windowed 1 +ScreenWidth 1280 +ScreenHeight 720 +BitDepth 32 -rez NOLF2_CN\\NOLF2_CN.rez"


def main():
    # ---- verify prerequisites ----
    missing = []
    if not CN_REZ_SRC.exists():
        missing.append(f"{CN_REZ_SRC}  (run build_phase1_renderer.py first, or keep NOLF2_CN\\NOLF2_CN.rez)")
    for f in CN_RUNTIME:
        if not (CN_DIR_SRC / f).exists():
            missing.append(f"{CN_DIR_SRC / f}  (run build_phase1_renderer.py first)")
    if not (ROOT / "launchcmds.txt").exists():
        missing.append(f"{ROOT/'launchcmds.txt'}  (run NOLF2.exe once with Modernizer)")
    if missing:
        raise SystemExit("[!] missing required files:\n  " + "\n  ".join(missing))

    # ---- clean staging ----
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "NOLF2_CN").mkdir(parents=True)
    (STAGE / "Custom" / "Mods" / "Modernizer").mkdir(parents=True)

    # ---- Modernizer core ----
    warned = []
    for name in MODERNIZER_ROOT_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, STAGE / name)
        else:
            warned.append(name)
    for sub in MODERNIZER_SUBPATHS:
        src = ROOT / sub
        if src.exists():
            shutil.copy2(src, STAGE / sub)
        else:
            warned.append(sub)

    # ---- Chinese renderer payload (clean NOLF2_CN layout) ----
    shutil.copy2(CN_REZ_SRC, STAGE / "NOLF2_CN" / "NOLF2_CN.rez")
    for f in CN_RUNTIME:
        shutil.copy2(CN_DIR_SRC / f, STAGE / "NOLF2_CN" / f)
    (STAGE / "NOLF2_CN" / "launchcmds_cn.txt").write_text(
        build_launch_cmdfile_text(), encoding="ascii", newline="")

    # ---- launcher + readme ----
    (STAGE / "启动汉化版.bat").write_text(LAUNCHER_BAT, encoding="ascii", newline="")
    (STAGE / "安装说明.txt").write_text(README, encoding="utf-8", newline="")

    # ---- zip ----
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(STAGE.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(STAGE.parent))

    total = sum(f.stat().st_size for f in STAGE.rglob("*") if f.is_file())
    print(f"[ok] staged {REL_NAME}  ({total/1e6:.1f} MB uncompressed)")
    print(f"[ok] zip -> {OUT_ZIP}  ({OUT_ZIP.stat().st_size/1e6:.1f} MB)")
    if warned:
        print("[warn] Modernizer files not found (skipped): " + ", ".join(warned))


if __name__ == "__main__":
    main()
