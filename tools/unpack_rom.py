#!/usr/bin/env python3
"""Build a decompressed ROM for N64Recomp and splat.

KI Gold keeps most of its code in three Rare "1172" streams (2-byte header
11 72, then raw deflate). N64Recomp needs plain MIPS code at known ROM offsets,
so this tool:
  1. Checks the ROM's SHA1 against tools/rom.sha1.
  2. Reads the stream table in the boot code and inflates the three code streams.
  3. Writes a new ROM: the original 12 MB unchanged, with the three inflated
     images appended after it (16-byte aligned).
  4. Writes a layout file with each segment's ROM offset, RAM address and size.

The original bytes stay where they are because the game still reads its data
streams from their original offsets.

Usage:
  python3 tools/unpack_rom.py                 # writes build/kigold.decompressed.z64
  python3 tools/test_unpack_rom.py            # known-answer test on a synthetic ROM

Both outputs go in build/ (git-ignored). The output ROM is game data: never
commit it. Never prints ROM bytes.
"""

import argparse
import hashlib
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import romcheck
import scan_rom

ROM_PATH = romcheck.ROM_PATH
DEFAULT_OUT = Path("build/kigold.decompressed.z64")
DEFAULT_LAYOUT = Path("build/unpack_layout.toml")

# Table of (start, end) ROM offset pairs, one per 1172 stream the game loads.
# Evidence: the boot function at RAM 0x80000520 reads entry 0 from RAM
# 0x800071E0, which is ROM 0x7DE0 (boot code is ROM 0x1000 = RAM 0x80000400).
TABLE_ROM = 0x7DE0
ALIGN = 0x10
CODE_CHECK_BYTES = 0x10000  # window for the "starts with code" check (4 KB was too small:
                            # stream1 opens with two large functions)

# The three code streams. Names are neutral on purpose (ground rule 5): what
# each one does is not known yet. See NOTES.md, "Boot code traced".
#   vram:      where the game inflates it. Evidence is the destination argument
#              of the inflate call (RAM 0x80000900) at the address in "site".
#   code_size: where code ends and data begins, from the cache flush ranges at
#              the load site. Not known yet for stream1 (its tail is microcode).
SEGMENTS = [
    {"name": "stream1", "table_index": 0, "vram": 0x8000F960, "site": 0x800005C4, "code_size": None},
    {"name": "stream2", "table_index": 1, "vram": 0x801ACB20, "site": 0x8001236C, "code_size": 0x219E0},
    {"name": "stream3", "table_index": 2, "vram": 0x801AD900, "site": 0x8000FC90, "code_size": 0x16760},
]


class UnpackError(Exception):
    pass


def align_up(value: int, align: int = ALIGN) -> int:
    return (value + align - 1) & ~(align - 1)


def read_table_entry(rom: bytes, table_rom: int, index: int) -> tuple[int, int]:
    """Return the (start, end) ROM offsets of one table entry."""
    start, end = struct.unpack_from(">II", rom, table_rom + index * 8)
    if not 0 < start < end <= len(rom):
        raise UnpackError(f"table entry {index} is not a valid ROM range (0x{start:X} to 0x{end:X})")
    return start, end


def inflate_stream(rom: bytes, start: int, end: int) -> bytes:
    """Inflate one 1172 stream that lies inside rom[start:end]."""
    if rom[start:start + 2] != scan_rom.RARE_MAGIC:
        raise UnpackError(f"no 1172 header at ROM 0x{start:X}")
    decomp = zlib.decompressobj(-15)
    try:
        out = decomp.decompress(rom[start + 2:end])
    except zlib.error as err:
        raise UnpackError(f"stream at ROM 0x{start:X} doesn't inflate: {err}") from err
    if not decomp.eof:
        raise UnpackError(f"stream at ROM 0x{start:X} is cut off before its end")
    return out


def unpack(rom: bytes, segments: list[dict] = SEGMENTS, table_rom: int = TABLE_ROM) -> tuple[bytes, list[dict]]:
    """Return (decompressed_rom, layout). Kept separate from file handling so
    tools/test_unpack_rom.py can check it against a synthetic ROM."""
    out = bytearray(rom)
    layout = []
    for seg in segments:
        start, end = read_table_entry(rom, table_rom, seg["table_index"])
        data = inflate_stream(rom, start, end)
        out += bytes(align_up(len(out)) - len(out))
        window = min(len(data), CODE_CHECK_BYTES) & ~3
        layout.append({
            "name": seg["name"],
            "table_index": seg["table_index"],
            "compressed_rom": start,
            "compressed_size": end - start,
            "rom": len(out),
            "vram": seg["vram"],
            "size": len(data),
            "code_size": seg["code_size"],
            "jr_ra_early": scan_rom.count_jr_ra(data, 0, window),
            "looks_like_code": scan_rom.classify(scan_rom.count_jr_ra(data, 0, window), window) == "code",
        })
        out += data
    out += bytes(align_up(len(out)) - len(out))
    return bytes(out), layout


def overlaps(layout: list[dict]) -> list[tuple[str, str]]:
    """Return pairs of segments that share RAM addresses (overlays)."""
    pairs = []
    for i, a in enumerate(layout):
        for b in layout[i + 1:]:
            if a["vram"] < b["vram"] + b["size"] and b["vram"] < a["vram"] + a["size"]:
                pairs.append((a["name"], b["name"]))
    return pairs


def layout_toml(layout: list[dict], original_size: int, total_size: int) -> str:
    lines = [
        "# Written by tools/unpack_rom.py. Addresses and sizes only, no ROM data.",
        "# rom: offset in the decompressed ROM. vram: RAM address the game loads it at.",
        f"original_size = 0x{original_size:X}",
        f"total_size = 0x{total_size:X}",
    ]
    for seg in layout:
        lines += [
            "",
            "[[segment]]",
            f'name = "{seg["name"]}"',
            f"table_index = {seg['table_index']}",
            f"compressed_rom = 0x{seg['compressed_rom']:X}",
            f"compressed_size = 0x{seg['compressed_size']:X}",
            f"rom = 0x{seg['rom']:X}",
            f"vram = 0x{seg['vram']:X}",
            f"size = 0x{seg['size']:X}",
        ]
        if seg["code_size"] is not None:
            lines.append(f"code_size = 0x{seg['code_size']:X}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rom", type=Path, default=ROM_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    args = parser.parse_args()

    if not args.rom.exists():
        print(f"FAIL: {args.rom} not found. Run tools/romcheck.py first.")
        return 1
    rom = args.rom.read_bytes()
    want = romcheck.expected_sha1()
    if want is None:
        print("FAIL: tools/rom.sha1 has no SHA1 in it. Run tools/romcheck.py first.")
        return 1
    if hashlib.sha1(rom).hexdigest() != want:
        print("FAIL: ROM SHA1 doesn't match tools/rom.sha1. The addresses in this tool only fit that ROM.")
        return 1

    try:
        out, layout = unpack(rom)
    except UnpackError as err:
        print(f"FAIL: {err}")
        return 1

    print(f"Original ROM: 0x{len(rom):X} bytes, kept unchanged at the start")
    print("Appended code segments:")
    ok = True
    for seg in layout:
        looks = seg["looks_like_code"]
        ok = ok and looks
        print(f"  {seg['name']}: ROM 0x{seg['rom']:07X}, RAM 0x{seg['vram']:08X} to "
              f"0x{seg['vram'] + seg['size']:08X}, 0x{seg['size']:X} bytes, "
              f"{seg['jr_ra_early']} jr ra in the first 64 KB "
              f"({'looks like code' if looks else 'DOES NOT look like code'})")
    for a, b in overlaps(layout):
        print(f"  note: {a} and {b} share RAM addresses (overlays)")
    if not ok:
        print("FAIL: a segment doesn't start with code. Nothing written.")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(out)
    args.layout.parent.mkdir(parents=True, exist_ok=True)
    args.layout.write_text(layout_toml(layout, len(rom), len(out)))
    print(f"\nDecompressed ROM: {args.out} (0x{len(out):X} bytes). Game data: never commit it.")
    print(f"Layout file: {args.layout}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
