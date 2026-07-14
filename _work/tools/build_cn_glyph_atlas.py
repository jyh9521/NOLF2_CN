"""
Build the Simplified-Chinese glyph atlas for the self-drawn text renderer.

Phase 0 of the "custom renderer" localization approach (see chinese_note.md,
2026-07-12 自绘中文渲染器). Instead of the carrier-byte + subset-font trick (locale-locked,
breaks on CP936 systems), the CSHELL proxy draws Chinese text itself with ILTDrawPrim,
sampling glyphs from ONE texture atlas. This script produces:

  1. the atlas texture as an uncompressed BGRA8888 DTX (ILTTexInterface::CreateTextureFromName)
  2. a compact binary metrics table the proxy reads: codepoint -> atlas UV rect + advance.

Atlas is white RGB with per-pixel coverage in alpha, so drawing with COLOROP=MODULATE and a
per-string vertex color reproduces any text color.

Dependencies: Pillow only (bundles FreeType). If missing:  pip install Pillow
Runs on Windows with real SimHei; falls back to a bundled CJK font for sandbox verification.
"""
import csv
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
TSVS = [
    ROOT / "_work" / "translation" / "nolf2_cn_strings.tsv",
]
OUT_DIR = ROOT / "_work" / "build_cn_renderer"
ATLAS_DTX = OUT_DIR / "stage" / "Interface" / "Fonts" / "NOLF2CN_ATLAS.DTX"
ATLAS_PNG = OUT_DIR / "NOLF2CN_ATLAS_preview.png"
METRICS_BIN = OUT_DIR / "stage" / "Interface" / "Fonts" / "NOLF2CN_ATLAS.MET"

# (path, ttc_index). First existing wins. SimHei is a plain .ttf (index 0).
FONT_CANDIDATES = [
    (Path(r"C:\Windows\Fonts\simhei.ttf"), 0),
    (Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), 0),
    (Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"), 0),
]

ATLAS_W = 2048
ATLAS_H = 2048
CELL = 40          # atlas cell size px (51x51 = 2601 glyph capacity)
GLYPH_PX = 34      # rendered glyph pixel size
COLS = ATLAS_W // CELL


def unescape(text):
    return text.replace("\\n", "\n").replace("\\t", "\t")


def collect_codepoints():
    cps = set(range(0x21, 0x7F))  # ASCII printables, so translations mixing digits/
    #                               Latin (numbers, "UNITY", "H.A.R.M.") also render.
    for path in TSVS:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                zh = unescape((row.get("zh") or "").strip())
                for ch in zh:
                    o = ord(ch)
                    if o > 0x7F and not ch.isspace():
                        cps.add(o)
    return sorted(cps)


def pick_font():
    for cand, idx in FONT_CANDIDATES:
        if cand.exists():
            return cand, idx
    raise SystemExit("no source font found; install SimHei or a Noto CJK font")


def build_atlas(codepoints, font_path, font_index):
    font = ImageFont.truetype(str(font_path), GLYPH_PX, index=font_index)
    ascent, _ = font.getmetrics()
    cap = COLS * (ATLAS_H // CELL)
    if len(codepoints) > cap:
        raise SystemExit(f"{len(codepoints)} glyphs exceed atlas capacity {cap}")

    cover = Image.new("L", (ATLAS_W, ATLAS_H), 0)  # coverage channel
    draw = ImageDraw.Draw(cover)
    metrics = []
    for i, cp in enumerate(codepoints):
        col, row = i % COLS, i // COLS
        cx, cy = col * CELL, row * CELL
        ch = chr(cp)
        try:
            l, t, r, b = font.getbbox(ch)
        except Exception:
            l = t = 0
            r = b = GLYPH_PX
        gw = r - l
        # LEFT-align the glyph origin at the cell's left edge so the proxy can crop
        # the UV to the glyph's advance width for proportional (non-monospace) layout.
        ox = cx - min(0, l)
        oy = cy + max(0, (CELL - GLYPH_PX) // 2)
        draw.text((ox, oy), ch, font=font, fill=255, anchor="la")
        try:
            adv = int(round(font.getlength(ch)))
        except Exception:
            adv = GLYPH_PX
        u0, v0 = cx / ATLAS_W, cy / ATLAS_H
        u1, v1 = (cx + CELL) / ATLAS_W, (cy + CELL) / ATLAS_H
        metrics.append((cp, u0, v0, u1, v1, adv if adv else GLYPH_PX))

    white = Image.new("L", (ATLAS_W, ATLAS_H), 255)
    img = Image.merge("RGBA", (white, white, white, cover))
    return img, metrics


def write_dtx_bgra(img, path):
    """Minimal uncompressed BGRA8888 DTX (no mips). Header fields to be cross-checked
    against the game's own DTX textures during Phase 1."""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = img.size
    r, g, b, a = img.split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    header = bytearray(164)
    struct.pack_into("<I", header, 0, 0)       # resource type
    struct.pack_into("<i", header, 4, -5)      # DTX version
    struct.pack_into("<HH", header, 8, w, h)
    struct.pack_into("<HH", header, 12, 1, 1)  # mipmaps, sections
    struct.pack_into("<i", header, 16, 0)      # iFlags
    struct.pack_into("<i", header, 20, 0)      # nUserFlags
    header[24] = 5                             # extra[0] BPPIdent 5 => 32-bit BGRA
    with path.open("wb") as f:
        f.write(header)
        f.write(bgra)


def write_metrics(metrics, path):
    """magic 'CNMA', count, atlas WxH, then records:
    <uint32 codepoint, float u0,v0,u1,v1, float advance_norm(=advance/CELL)>."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"CNMA")
        f.write(struct.pack("<I", len(metrics)))
        f.write(struct.pack("<HH", ATLAS_W, ATLAS_H))
        for cp, u0, v0, u1, v1, adv in metrics:
            f.write(struct.pack("<I5f", cp, u0, v0, u1, v1, adv / CELL))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cps = collect_codepoints()
    font_path, font_index = pick_font()
    img, metrics = build_atlas(cps, font_path, font_index)
    img.save(ATLAS_PNG)
    write_dtx_bgra(img, ATLAS_DTX)
    write_metrics(metrics, METRICS_BIN)
    print(f"font:        {font_path}")
    print(f"glyphs:      {len(cps)}  (atlas capacity {COLS * (ATLAS_H // CELL)})")
    print(f"atlas:       {ATLAS_W}x{ATLAS_H} cell={CELL} glyph={GLYPH_PX}")
    print(f"dtx:         {ATLAS_DTX}  ({ATLAS_DTX.stat().st_size} bytes)")
    print(f"metrics:     {METRICS_BIN}  ({METRICS_BIN.stat().st_size} bytes)")
    print(f"png preview: {ATLAS_PNG}")


if __name__ == "__main__":
    main()
