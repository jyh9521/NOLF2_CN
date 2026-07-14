import csv
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_DIR = ROOT / "_work" / "analysis"
TRANSLATION_DIR = ROOT / "_work" / "translation"

CHAPTER01_TSV = TRANSLATION_DIR / "chapter01_priority.tsv"
MODERNIZER_CRES_CSV = ANALYSIS_DIR / "CRES_modernizer_strings.csv"
OUT_TSV = TRANSLATION_DIR / "remaining_after_chapter01.tsv"
OUT_SUMMARY = TRANSLATION_DIR / "remaining_after_chapter01_summary.md"

HEADER_FILES = [
    ROOT / "_work" / "source" / "Game" / "ClientRes" / "TO2" / "ClientRes.h",
    ROOT / "_work" / "source" / "Game" / "ClientRes" / "Shared" / "ClientResShared.h",
]

RC_FILES = [
    ("to2", ROOT / "_work" / "source" / "Game" / "ClientRes" / "TO2" / "Lang" / "EN" / "ClientRes.rc"),
    ("shared", ROOT / "_work" / "source" / "Game" / "ClientRes" / "Shared" / "Lang" / "EN" / "ClientResShared.rc"),
]

DIALOGUE_INDEX = ANALYSIS_DIR / "dialogue_subtitle_index.csv"

FIELDS = ["id", "symbols", "category", "source", "source_lines", "english", "zh", "status", "note"]

DEFINE_RE = re.compile(r"^\s*#define\s+(IDS_[A-Za-z0-9_]+)\s+(\d+)\b")
RC_ROW_RE = re.compile(r"^\s*(IDS_[A-Za-z0-9_]+)\s+(.+?)\s*$")
STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
ANGLE_MARKER_RE = re.compile(r"^<[^<>]+>$")


def rc_unescape(literal):
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
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def plain_sheet_cell(text):
    return sheet_escape(text).replace('"', "＂")


def read_existing_ids(path):
    ids = set()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            value = (row.get("id") or "").strip()
            if value:
                ids.add(int(value))
    return ids


def read_headers():
    symbol_to_id = {}
    id_to_symbols = defaultdict(list)
    for path in HEADER_FILES:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                match = DEFINE_RE.match(line)
                if not match:
                    continue
                symbol = match.group(1)
                string_id = int(match.group(2))
                symbol_to_id.setdefault(symbol, string_id)
                if symbol not in id_to_symbols[string_id]:
                    id_to_symbols[string_id].append(symbol)
    return symbol_to_id, id_to_symbols


def read_rc_source_lines(symbol_to_id):
    source_lines = defaultdict(list)
    symbol_lines = defaultdict(list)
    for source_name, path in RC_FILES:
        with path.open("r", encoding="cp1252", errors="replace") as f:
            for line_no, line in enumerate(f, 1):
                match = RC_ROW_RE.match(line)
                if not match:
                    continue
                symbol = match.group(1)
                literals = STRING_RE.findall(match.group(2))
                if not literals:
                    continue
                string_id = symbol_to_id.get(symbol)
                if string_id is None:
                    continue
                source_lines[string_id].append(f"{source_name}:{line_no}")
                symbol_lines[string_id].append(symbol)
    return source_lines, symbol_lines


def read_dialogue_source_lines():
    source_lines = defaultdict(list)
    if not DIALOGUE_INDEX.exists():
        return source_lines
    with DIALOGUE_INDEX.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            value = (row.get("id") or "").strip()
            source = (row.get("source") or "").strip()
            if not value or not source:
                continue
            try:
                string_id = int(value)
            except ValueError:
                continue
            source_lines[string_id].append(source.replace("Game\\Attributes\\SERVERSND.TXT:", "serversnd:"))
    return source_lines


def read_cres_strings():
    rows = {}
    with MODERNIZER_CRES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows[int(row["id"])] = row["text"]
    return rows


def categorize(string_id, symbols, text):
    joined = ";".join(symbols)
    if 100 <= string_id <= 142 or "SCMD" in text:
        return "server_admin"
    if "DIALOGUE" in joined or 10000 <= string_id < 13000 or 32000 <= string_id < 34000:
        return "dialogue"
    if "MISSIONFAILURE" in joined:
        return "mission_failure"
    if "MISSION_OBJ" in joined:
        return "mission_objective"
    if "MISSION" in joined or 2500 <= string_id < 3200:
        return "mission"
    if "INTEL" in joined or 25000 <= string_id < 26000:
        return "intel"
    if "REWARD" in joined:
        return "reward"
    if "TRANSMISSION" in joined:
        return "transmission"
    if "WEAPON" in joined or "AMMO" in joined or "GEAR" in joined or "MOD_" in joined:
        return "equipment"
    if "NAMES" in joined:
        return "name"
    if "SCREEN" in joined or "TITLE" in joined or "MENU" in joined or "OPTION" in joined or "IDS_HELP" in joined:
        return "menu"
    if 500 <= string_id < 2500:
        return "menu"
    if not text.strip():
        return "empty"
    return "other"


def make_note(text, category):
    notes = []
    if category == "server_admin":
        notes.append("SCMD/server admin text; low priority for single-player")
    if ANGLE_MARKER_RE.fullmatch(text.strip()):
        notes.append("keep angle brackets; translate visible label inside if needed")
    if re.search(r"%\d*!?[a-zA-Z]!?|%[a-zA-Z]", text):
        notes.append("preserve percent placeholders")
    if "@" in text:
        notes.append("preserve @ separators")
    if "\n" in text:
        notes.append("line breaks are escaped as \\n")
    return "; ".join(notes)


def unique_join(values):
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return ";".join(seen)


def build_rows():
    existing_ids = read_existing_ids(CHAPTER01_TSV)
    symbol_to_id, id_to_symbols = read_headers()
    rc_source_lines, rc_symbol_lines = read_rc_source_lines(symbol_to_id)
    dialogue_source_lines = read_dialogue_source_lines()
    cres_strings = read_cres_strings()

    rows = []
    for string_id in sorted(cres_strings):
        if string_id in existing_ids:
            continue
        text = cres_strings[string_id]
        symbols = list(id_to_symbols.get(string_id, []))
        for symbol in rc_symbol_lines.get(string_id, []):
            if symbol not in symbols:
                symbols.append(symbol)
        source_lines = []
        source_lines.extend(dialogue_source_lines.get(string_id, []))
        source_lines.extend(rc_source_lines.get(string_id, []))
        category = categorize(string_id, symbols, text)
        rows.append(
            {
                "id": string_id,
                "symbols": unique_join(symbols),
                "category": category,
                "source": "CRES_modernizer.DLL",
                "source_lines": unique_join(source_lines),
                "english": plain_sheet_cell(text),
                "zh": "",
                "status": "",
                "note": make_note(text, category),
            }
        )
    return rows, len(cres_strings), len(existing_ids)


def write_tsv(rows):
    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_TSV.open("w", encoding="utf-8-sig", newline="\n") as f:
        f.write("\t".join(FIELDS) + "\n")
        for row in rows:
            values = []
            for field in FIELDS:
                value = str(row.get(field, "")).replace("\t", " ").replace("\r", " ").replace("\n", " ")
                values.append(value)
            f.write("\t".join(values) + "\n")


def validate_tsv(path, excluded_ids):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    ids = [int(row["id"]) for row in rows]
    overlap = sorted(set(ids) & excluded_ids)
    if overlap:
        raise RuntimeError(f"unexpected overlap with chapter01 ids: {overlap[:10]}")
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate ids in export")
    return rows


def write_summary(rows, cres_count, excluded_count):
    counts = defaultdict(int)
    for row in rows:
        counts[row["category"]] += 1
    lines = [
        "# Remaining Translation Export",
        "",
        f"- source: {MODERNIZER_CRES_CSV}",
        f"- CRES rows: {cres_count}",
        f"- excluded IDs from chapter01_priority.tsv: {excluded_count}",
        f"- exported rows: {len(rows)}",
        "",
        "## Category Counts",
        "",
    ]
    for category in sorted(counts):
        lines.append(f"- {category}: {counts[category]}")
    lines.extend(
        [
            "",
            "## Editing Rules",
            "",
            "- Translate only the `zh` column.",
            "- Keep `%s`, `%d`, `%1!d!`, `@`, and similar placeholders intact.",
            "- Keep `<` and `>` around angle-bracket labels.",
            "- Newlines in `english` are escaped as `\\n`; use `\\n` in `zh` when you need a manual line break.",
            "- `server_admin` / SCMD rows are low priority for single-player testing.",
        ]
    )
    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    rows, cres_count, excluded_count = build_rows()
    write_tsv(rows)
    checked_rows = validate_tsv(OUT_TSV, read_existing_ids(CHAPTER01_TSV))
    write_summary(checked_rows, cres_count, excluded_count)
    print(f"out={OUT_TSV}")
    print(f"summary={OUT_SUMMARY}")
    print(f"cres_rows={cres_count}")
    print(f"excluded_chapter01_ids={excluded_count}")
    print(f"exported_rows={len(checked_rows)}")
    counts = defaultdict(int)
    for row in checked_rows:
        counts[row["category"]] += 1
    for category in sorted(counts):
        print(f"{category}={counts[category]}")


if __name__ == "__main__":
    main()
