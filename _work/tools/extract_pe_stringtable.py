import argparse
import csv
import struct
from pathlib import Path


RT_STRING = 6


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def read_c_string(data, off):
    end = data.index(b"\0", off)
    return data[off:end].decode("ascii", errors="replace")


def parse_sections(data):
    if data[:2] != b"MZ":
        raise ValueError("Not an MZ executable")
    pe_off = u32(data, 0x3C)
    if data[pe_off : pe_off + 4] != b"PE\0\0":
        raise ValueError("Not a PE executable")

    coff = pe_off + 4
    section_count = u16(data, coff + 2)
    optional_size = u16(data, coff + 16)
    optional = coff + 20
    magic = u16(data, optional)
    if magic == 0x10B:
        resource_rva = u32(data, optional + 96 + 8 * 2)
        resource_size = u32(data, optional + 96 + 8 * 2 + 4)
    elif magic == 0x20B:
        resource_rva = u32(data, optional + 112 + 8 * 2)
        resource_size = u32(data, optional + 112 + 8 * 2 + 4)
    else:
        raise ValueError(f"Unknown PE optional header magic: 0x{magic:04x}")

    sections = []
    table = optional + optional_size
    for i in range(section_count):
        off = table + i * 40
        name = data[off : off + 8].split(b"\0", 1)[0].decode("ascii", errors="replace")
        virtual_size = u32(data, off + 8)
        virtual_addr = u32(data, off + 12)
        raw_size = u32(data, off + 16)
        raw_ptr = u32(data, off + 20)
        sections.append((name, virtual_addr, max(virtual_size, raw_size), raw_ptr, raw_size))
    return sections, resource_rva, resource_size


def rva_to_file(sections, rva):
    for _name, va, vsize, raw_ptr, raw_size in sections:
        if va <= rva < va + vsize:
            delta = rva - va
            if delta >= raw_size:
                raise ValueError(f"RVA 0x{rva:x} points past raw section data")
            return raw_ptr + delta
    raise ValueError(f"RVA 0x{rva:x} not found in PE sections")


def resource_name(data, base, value):
    if value & 0x80000000:
        off = base + (value & 0x7FFFFFFF)
        length = u16(data, off)
        raw = data[off + 2 : off + 2 + length * 2]
        return raw.decode("utf-16le", errors="replace")
    return value


def walk_resource_dir(data, base, rel_off=0, level=0, path=()):
    dir_off = base + rel_off
    named = u16(data, dir_off + 12)
    ids = u16(data, dir_off + 14)
    entries = named + ids
    for i in range(entries):
        entry_off = dir_off + 16 + i * 8
        name_value = u32(data, entry_off)
        target = u32(data, entry_off + 4)
        name = resource_name(data, base, name_value)
        if target & 0x80000000:
            yield from walk_resource_dir(data, base, target & 0x7FFFFFFF, level + 1, path + (name,))
        else:
            data_entry = base + target
            yield path + (name,), u32(data, data_entry), u32(data, data_entry + 4), u32(data, data_entry + 8)


def decode_string_block(data):
    strings = []
    off = 0
    for _ in range(16):
        if off + 2 > len(data):
            strings.append("")
            continue
        length = u16(data, off)
        off += 2
        raw = data[off : off + length * 2]
        strings.append(raw.decode("utf-16le", errors="replace"))
        off += length * 2
    return strings


def extract(path):
    data = Path(path).read_bytes()
    sections, resource_rva, _resource_size = parse_sections(data)
    if resource_rva == 0:
        return []
    resource_base = rva_to_file(sections, resource_rva)

    rows = []
    for res_path, data_rva, size, _codepage in walk_resource_dir(data, resource_base):
        if len(res_path) < 3 or res_path[0] != RT_STRING:
            continue
        block_id = int(res_path[1])
        lang = res_path[2]
        block = data[rva_to_file(sections, data_rva) : rva_to_file(sections, data_rva) + size]
        for index, text in enumerate(decode_string_block(block)):
            string_id = (block_id - 1) * 16 + index
            if text:
                rows.append({"id": string_id, "lang": lang, "text": text})
    rows.sort(key=lambda row: (row["id"], str(row["lang"])))
    return rows


def main():
    parser = argparse.ArgumentParser(description="Extract PE RT_STRING resources to CSV.")
    parser.add_argument("dll", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = extract(args.dll)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "lang", "text"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"extracted {len(rows)} strings -> {args.out}")


if __name__ == "__main__":
    main()

