"""
Build the runtime English->Chinese dictionary the renderer proxy matches against.

Two sections keyed by the EXACT runtime English (no stripping):
  - MAIN: plain strings, exact match (binary search).
  - FMT : templates with a format spec (%1!d!, %s...), matched as patterns with the
          captured value(s) back-filled into the Chinese template.

Intel strings are stored as "Title@Body"; the game shows the title (in the intel list)
and the body (on the note) separately, so we ALSO emit the pre-@ and post-@ halves as
their own entries. Degenerate format templates (too little literal text to anchor on)
are dropped so they can't match arbitrary text.

File NOLF2CN_STRINGS.bin:
  magic "CNS2", uint32 main_count, uint32 fmt_count
  MAIN records (sorted by english): u16 en_len, en, u16 m, m*u32 codepoints
  FMT  records:                     u16 en_len, en, u16 m, m*u32 codepoints
"""
import csv
import struct
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TSVS = [
    ROOT / "_work" / "translation" / "nolf2_cn_strings.tsv",
]
OUT = ROOT / "_work" / "build_cn_renderer" / "stage" / "Interface" / "Fonts" / "NOLF2CN_STRINGS.bin"

SPEC_RE = re.compile(r"%\d+![^!]*!|%[0-9.+\-# lhL]*[a-zA-Z]|%%")


def unescape(text):
    return text.replace("\\n", "\n").replace("\\t", "\t").replace("＂", '"')


def literal_len(en):
    return len(SPEC_RE.sub("", en))


def add(pairs, en, zh):
    if not en.strip() or not zh or zh == en:
        return
    if en in pairs:
        return
    pairs[en] = zh


def load_pairs():
    pairs = {}
    for path in TSVS:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                en = unescape(row.get("english") or "")
                zh = unescape((row.get("zh") or "").strip())
                if not en.strip() or not zh or zh == en:
                    continue
                add(pairs, en, zh)
                # intel "Title@Body": also expose each half so the list title and the
                # on-screen note body (shown without the other half) both translate.
                if "@" in en and "@" in zh:
                    et, eb = en.split("@", 1)
                    zt, zb = zh.split("@", 1)
                    add(pairs, et, zt)
                    add(pairs, eb, zb)
    return pairs


def rec(en, zh):
    enb = en.encode("latin-1", "replace")
    cps = [ord(c) for c in zh]
    out = struct.pack("<H", len(enb)) + enb + struct.pack("<H", len(cps))
    for cp in cps:
        out += struct.pack("<I", cp)
    return out


def main():
    pairs = load_pairs()
    main = {en: zh for en, zh in pairs.items() if "%" not in en}
    fmt = [(en, zh) for en, zh in pairs.items() if "%" in en and literal_len(en) >= 3]
    dropped = sum(1 for en, zh in pairs.items() if "%" in en and literal_len(en) < 3)
    main_items = sorted(main.items(), key=lambda kv: kv[0].encode("latin-1", "replace"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("wb") as f:
        f.write(b"CNS2")
        f.write(struct.pack("<II", len(main_items), len(fmt)))
        for en, zh in main_items:
            f.write(rec(en, zh))
        for en, zh in fmt:
            f.write(rec(en, zh))
    print(f"main entries: {len(main_items)}")
    print(f"fmt  entries: {len(fmt)} (dropped {dropped} degenerate)")
    print(f"out: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
