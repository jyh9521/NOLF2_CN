# NOLF2_CN — 《无人永生 2》简体中文汉化

> No One Lives Forever 2: A Spy in H.A.R.M.'s Way (2002) 的社区简体中文汉化。
> 基于社区现代化补丁 **Modernizer 2** 构建；已完整通关测试，除少量漏译外可稳定游玩。

这是**源码 / 开发仓库**。它包含从零重建整套汉化所需的全部源码、工具与译文，但**不包含**
任何游戏本体或第三方（Modernizer）文件——那些体积大、可重新生成、或受版权约束。

---

## ✨ 亮点：它是怎么做到的

NOLF2 用的是 2002 年的 LithTech (Jupiter) 引擎，天生对中文极不友好：界面文本走 ANSI/单字节
路径、UI 字体系统最多 255 个字形、文本经系统代码页转换后（简中 936 / 日文 932）还会变成乱码。
传统的"替换字符串 + 塞位图字体"路线全都撞墙（依赖区域设置、装不下长文本、与格式符冲突崩溃）。

本项目最终采用 **运行时自绘中文** 方案：

1. 一个 **CSHELL 代理 DLL** 转发原始 Modernizer CSHELL，同时挂钩引擎的文字渲染
   `CUIPolyString::Render`。
2. 用每条文本的**英文原文**（纯 ASCII，与系统区域设置无关）去匹配一张运行时"英文→中文"对照表。
3. 命中后，把中文字形从一张 **SimHei 字形图集纹理** 上取样，按比例重新排版，替换引擎即将绘制的
   四边形——引擎照常上屏，中文就出来了。

于是：**不改游戏任何基础文本文件、不分页、不用载体字节、与系统区域设置无关、随时删除即可完整卸载。**
完整的踩坑与推导过程（含逆向得到的 vtable/RVA 偏移）见 [`chinese_note.md`](chinese_note.md)——
强烈建议续开发前先读它。

---

## 🎮 我只想玩（面向玩家）

去 [Releases](../../releases) 下载打包好的汉化包，按包内 `安装说明.txt` 覆盖到一份纯净的
NOLF2 1.3，双击 `启动汉化版.bat` 即可。发布说明见 [`NOLF2_汉化_发布声明.md`](NOLF2_汉化_发布声明.md)。

- 游戏以**窗口 1280×720** 启动；想要更大画面，进游戏后在"选项→显示"调高分辨率。
- **请勿使用独占全屏**：本引擎在部分现代显卡上以独占全屏*启动*会崩溃（窗口模式安全）。

---

## 🛠 我要改 / 重建（面向开发者）

### 仓库结构

```
_work/proxy_cshell_renderer/
    cshell_proxy_renderer.cpp   渲染器代理（挂钩 + 自绘中文；含逆向偏移常量）
    build_proxy.ps1             用 MSVC 编译代理 DLL (x86)
_work/tools/
    build_phase1_renderer.py    一键：编译代理 + 生成图集/词典 + 打包 REZ + 生成启动脚本
    build_cn_glyph_atlas.py     译文 → 字形图集 (NOLF2CN_ATLAS.DTX/.MET)，用 SimHei
    build_cn_dict.py            译文 → 运行时英文→中文对照表 (NOLF2CN_STRINGS.bin)
    build_launch_cmdfile.ps1    启动时构建 -cmdfile（剥离启动器坏参数、窗口模式）
    make_cn_release.py          组装集成发布包（Modernizer 核心 + 汉化 → zip）
    extract_*.py                从游戏 CRES.DLL 抽取文本、生成翻译工作表
_work/translation/
    nolf2_cn_strings.tsv        全部译文（english → zh），已按游戏内 id 顺序排列
chinese_note.md                 完整开发日志（务必先读）
NOLF2_汉化_发布声明.md          发布声明
```

### 构建前置（Windows）

| 依赖 | 说明 |
|------|------|
| NOLF2 1.3 + Modernizer 2 Beta 2c | 可正常运行的安装，用于取 CSHELL、打包、测试 |
| MSVC (x86) | Visual Studio Build Tools；`build_proxy.ps1` 里的 `vcvars32.bat` 路径按你的 VS 版本改 |
| Python 3 + Pillow | `pip install Pillow` |
| SimHei 字体 | Windows 自带 `C:\Windows\Fonts\simhei.ttf` |
| LithRez.exe | 随游戏附带 `Tools\Bin\LithRez.exe` |
| Modernizer CSHELL.DLL | 放到 `_work\extract_modernizer\CSHELL.DLL`（从 `MODERNIZER.REZ` 解出）。**本仓库不含，第三方版权** |

### 构建步骤

```bat
:: 1) 把本仓库的 _work\ 及根目录文档覆盖到你的 NOLF2 游戏根目录
::    （脚本以"脚本位于 <游戏根>\_work\tools\"来定位游戏根）
:: 2) 备好 _work\extract_modernizer\CSHELL.DLL

python _work\tools\build_phase1_renderer.py     :: 编译+生成图集/词典+打包 REZ
_work\run_phase1_