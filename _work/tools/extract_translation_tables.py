import csv
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "_work" / "analysis"
OUT_DIR = ROOT / "_work" / "translation"

HEADER_FILES = [
    ROOT / "_work" / "source" / "Game" / "ClientRes" / "TO2" / "ClientRes.h",
    ROOT / "_work" / "source" / "Game" / "ClientRes" / "Shared" / "ClientResShared.h",
]

RC_FILES = [
    ("to2", ROOT / "_work" / "source" / "Game" / "ClientRes" / "TO2" / "Lang" / "EN" / "ClientRes.rc"),
    ("shared", ROOT / "_work" / "source" / "Game" / "ClientRes" / "Shared" / "Lang" / "EN" / "ClientResShared.rc"),
]

KNOWN_ZH = {
    2500: "第1章 凯特必须死!",
    2551: "直觉而已.",
    2700: "UNITY派凯特到日本调查犯罪会议, 并暗中拍下与会者.\n\n先找Hatori取得情报. 他在村里等候.",
    3101: "提示: 不知下一步时按Tab看目标. 右上罗盘会指路.",
    11001: "服部先生在村里某处等你.",
    11002: "找找他留下的信息.",
    11003: "找到服部先生. 他能帮你完成任务.",
    11004: "祝你好运!",
}

SKIP_MARKER_RE = re.compile(r"^<[^<>]+>$")

STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
RC_ROW_RE = re.compile(r"^\s*(IDS_[A-Za-z0-9_]+)\s+(.+?)\s*$")
DEFINE_RE = re.compile(r"^\s*#define\s+(IDS_[A-Za-z0-9_]+)\s+(\d+)\b")


def rc_unescape(literal):
    if not (literal.startswith('"') and literal.endswith('"')):
        raise ValueError(f"not a string literal: {literal!r}")
    src = literal[1:-1]
    out = []
    i = 0
    while i < len(src):
        ch = src[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(src):
            out.append("\\")
            break
        esc = src[i]
        i += 1
        if esc == "n":
            out.append("\n")
        elif esc == "r":
            out.append("\r")
        elif esc == "t":
            out.append("\t")
        elif esc == "0":
            out.append("\0")
        elif esc in {'"', "\\"}:
            out.append(esc)
        else:
            out.append(esc)
    return "".join(out)


def sheet_escape(text):
    return text.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n").replace("\t", "\\t")


def editable_cell(text):
    return sheet_escape(text).replace('"', "＂")


def read_headers():
    symbol_to_id = {}
    id_to_symbols = defaultdict(list)
    for path in HEADER_FILES:
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            match = DEFINE_RE.match(line)
            if not match:
                continue
            symbol = match.group(1)
            string_id = int(match.group(2))
            symbol_to_id.setdefault(symbol, string_id)
            if symbol not in id_to_symbols[string_id]:
                id_to_symbols[string_id].append(symbol)
    return symbol_to_id, id_to_symbols


def read_rc_entries(symbol_to_id):
    entries = []
    for source_name, path in RC_FILES:
        for line_no, line in enumerate(path.read_text(encoding="cp1252", errors="replace").splitlines(), 1):
            match = RC_ROW_RE.match(line)
            if not match:
                continue
            symbol = match.group(1)
            literals = STRING_RE.findall(match.group(2))
            if not literals:
                continue
            text = "".join(rc_unescape(lit) for lit in literals)
            entries.append(
                {
                    "id": symbol_to_id.get(symbol),
                    "symbol": symbol,
                    "source": source_name,
                    "line": line_no,
                    "english": text,
                }
            )
    return entries


def read_cres_strings():
    path = ANALYSIS_DIR / "CRES_strings.csv"
    strings = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            strings[int(row["id"])] = row["text"]
    return strings


def categorize(string_id, symbols, text):
    joined = ";".join(symbols)
    if "DIALOGUE" in joined:
        return "dialogue"
    if "MISSIONFAILURE" in joined:
        return "mission_failure"
    if "MISSION_OBJ" in joined:
        return "mission_objective"
    if "MISSION" in joined:
        return "mission"
    if "INTEL" in joined:
        return "intel"
    if "WEAPON" in joined or "AMMO" in joined or "GEAR" in joined or "MOD_" in joined:
        return "equipment"
    if "TRANSMISSION" in joined:
        return "transmission"
    if "REWARD" in joined:
        return "reward"
    if "SCREEN" in joined or "TITLE" in joined or "MENU" in joined or "OPTION" in joined or "IDS_HELP" in joined:
        return "menu"
    if "NAMES" in joined:
        return "name"
    if 10000 <= string_id < 13000 or 32000 <= string_id < 34000:
        return "dialogue"
    if 25000 <= string_id < 26000:
        return "intel"
    if 2500 <= string_id < 3200:
        return "mission"
    if 500 <= string_id < 2500:
        return "menu"
    if not text.strip():
        return "empty"
    return "other"


def merge_rows(rc_entries, cres_strings, id_to_symbols):
    by_id = {}
    for string_id, text in cres_strings.items():
        symbols = list(id_to_symbols.get(string_id, []))
        by_id[string_id] = {
            "id": string_id,
            "symbols": symbols,
            "source": "CRES.DLL",
            "line": "",
            "english": text,
            "rc_english": "",
            "source_lines": [],
        }

    for entry in rc_entries:
        string_id = entry["id"]
        if string_id is None:
            continue
        row = by_id.setdefault(
            string_id,
            {
                "id": string_id,
                "symbols": [],
                "source": "rc_only",
                "line": "",
                "english": entry["english"],
                "rc_english": entry["english"],
                "source_lines": [],
            },
        )
        if entry["symbol"] not in row["symbols"]:
            row["symbols"].append(entry["symbol"])
        row["source_lines"].append(f"{entry['source']}:{entry['line']}")
        if not row["rc_english"]:
            row["rc_english"] = entry["english"]
        if string_id not in cres_strings:
            row["english"] = entry["english"]

    rows = []
    for string_id in sorted(by_id):
        row = by_id[string_id]
        symbols = row["symbols"]
        english = row["english"]
        category = categorize(string_id, symbols, english)
        status = "done" if string_id in KNOWN_ZH else ""
        note = ""
        if SKIP_MARKER_RE.fullmatch(english.strip()):
            status = "skip"
            note = "angle-bracket marker or placeholder; keep original"
        rows.append(
            {
                "id": string_id,
                "symbols": ";".join(symbols),
                "category": category,
                "source": row["source"],
                "source_lines": ";".join(row["source_lines"]),
                "english": english,
                "zh": KNOWN_ZH.get(string_id, ""),
                "status": status,
                "note": note,
            }
        )
    return rows


def write_csv(path, rows, escape=False):
    fields = ["id", "symbols", "category", "source", "source_lines", "english", "zh", "status", "note"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if escape:
                out["english"] = editable_cell(out["english"])
                out["zh"] = editable_cell(out["zh"])
            writer.writerow(out)


def write_tsv(path, rows):
    fields = ["id", "symbols", "category", "source", "source_lines", "english", "zh", "status", "note"]
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("\t".join(fields) + "\n")
        for row in rows:
            values = []
            for field in fields:
                value = str(row[field])
                if field in {"english", "zh"}:
                    value = editable_cell(value)
                else:
                    value = value.replace("\t", " ").replace("\n", " ")
                values.append(value)
            f.write("\t".join(values) + "\n")


def write_category_files(rows):
    for category in sorted({row["category"] for row in rows}):
        subset = [row for row in rows if row["category"] == category]
        write_csv(OUT_DIR / f"{category}.csv", subset, escape=True)
        write_tsv(OUT_DIR / f"{category}.tsv", subset)


def write_chapter1_file(rows):
    ids = set()
    ids.update(range(2500, 2527))
    ids.update(range(2550, 2600))
    ids.update(range(2700, 2710))
    ids.update(range(3100, 3110))
    ids.update(range(3300, 3320))
    ids.update(range(4750, 4760))
    ids.update(range(5000, 5020))
    ids.update(range(6500, 6530))
    ids.update(range(7000, 7060))
    ids.update(range(10000, 11200))
    ids.update(range(25000, 25060))
    ids.update(range(30000, 30010))
    subset = [row for row in rows if row["id"] in ids]
    write_csv(OUT_DIR / "chapter01_priority.csv", subset, escape=True)
    write_tsv(OUT_DIR / "chapter01_priority.tsv", subset)
    return len(subset)


def write_summary(rows, rc_count, cres_count, chapter1_count):
    counts = defaultdict(int)
    for row in rows:
        counts[row["category"]] += 1
    lines = [
        "# NOLF2 Translation Text Export",
        "",
        f"- merged rows: {len(rows)}",
        f"- RC string rows: {rc_count}",
        f"- CRES string rows: {cres_count}",
        f"- prefilled zh rows: {len(KNOWN_ZH)}",
        f"- chapter01 priority rows: {chapter1_count}",
        "",
        "## Categories",
        "",
    ]
    for category in sorted(counts):
        lines.append(f"- {category}: {counts[category]}")
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- all_text_for_translation.tsv: one physical row per string; newlines are escaped as \\n.",
            "- all_text_for_translation.csv: UTF-8 with BOM; text newlines are escaped as \\n; source double quotes are displayed as full-width ＂ for editor compatibility.",
            "- all_text_raw_multiline.csv: UTF-8 with BOM; text cells contain real line breaks.",
            "- category CSV/TSV files split the same rows by category.",
            "- chapter01_priority.tsv/csv contains the likely first-chapter work queue.",
            "",
            "Translate in the `zh` column. Keep placeholders such as `%s`, `%d`, `%1!d!`, and separators such as `@` intact.",
            "SCMD strings are server admin command/status text and can be skipped for single-player-first localization.",
        ]
    )
    (OUT_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    symbol_to_id, id_to_symbols = read_headers()
    rc_entries = read_rc_entries(symbol_to_id)
    cres_strings = read_cres_strings()
    rows = merge_rows(rc_entries, cres_strings, id_to_symbols)

    write_tsv(OUT_DIR / "all_text_for_translation.tsv", rows)
    write_csv(OUT_DIR / "all_text_for_translation.csv", rows, escape=True)
    write_csv(OUT_DIR / "all_text_raw_multiline.csv", rows, escape=False)
    write_category_files(rows)
    chapter1_count = write_chapter1_file(rows)
    write_summary(rows, len(rc_entries), len(cres_strings), chapter1_count)

    print(f"rows={len(rows)}")
    print(f"rc_entries={len(rc_entries)}")
    print(f"cres_entries={len(cres_strings)}")
    print(f"out={OUT_DIR}")
    print(f"chapter01_priority={chapter1_count}")
    for category in sorted({row["category"] for row in rows}):
        print(f"{category}={sum(1 for row in rows if row['category'] == category)}")


if __name__ == "__main__":
    main()
