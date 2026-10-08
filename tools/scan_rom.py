#!/usr/bin/env python3
"""Recon scan of baserom.us.z64 for Phase 1.

Answers three early questions without disassembling anything:
  1. Which graphics and audio microcode does the game use?
     (looks for microcode name strings like "F3DEX" or "RSP Gfx ucode")
  2. Does the game use Rare's "1172" compression?
     (finds 11 72 headers and test-inflates the raw deflate stream after them)
  3. Are there plain gzip streams?

Usage:
  python tools/scan_rom.py                 # print a summary
  python tools/scan_rom.py --out FILE      # also write the full report to FILE

The full report goes in build/ by default (git-ignored), because it quotes
strings from the ROM. Summarize findings in NOTES.md in your own words.
"""

import argparse
import re
import sys
import zlib
from pathlib import Path

ROM_PATH = Path("baserom.us.z64")
DEFAULT_OUT = Path("build/scan_report.txt")

# Case-sensitive on purpose: real microcode IDs are written exactly like this,
# and case-insensitive matching flags random bytes in compressed data.
MICROCODE_HINTS = re.compile(
    rb"RSP|F3DEX|F3DLX|F3DLP|L3DEX|S2DEX|Fast3D|Turbo3D|ucode|SW Version|aspMain|gspF|rspboot",
)
PRINTABLE = re.compile(rb"[\x20-\x7e]{10,}")
RARE_MAGIC = b"\x11\x72"
GZIP_MAGIC = b"\x1f\x8b\x08"
MIN_INFLATED = 64           # ignore tiny accidental "successes"
MAX_INPUT = 4 * 1024 * 1024  # never feed more than this into one inflate attempt


def find_microcode_strings(rom: bytes) -> list[tuple[int, str]]:
    hits = []
    for match in PRINTABLE.finditer(rom):
        text = match.group()
        if MICROCODE_HINTS.search(text):
            hits.append((match.start(), text.decode("ascii")[:100]))
    return hits


def try_inflate(rom: bytes, start: int, wbits: int) -> tuple[int, int] | None:
    """Return (compressed_size, inflated_size) if a complete stream starts here."""
    decomp = zlib.decompressobj(wbits)
    chunk = rom[start:start + MAX_INPUT]
    try:
        out = decomp.decompress(chunk)
    except zlib.error:
        return None
    if not decomp.eof or len(out) < MIN_INFLATED:
        return None
    return len(chunk) - len(decomp.unused_data), len(out)


def find_streams(rom: bytes, magic: bytes, skip: int, wbits: int) -> list[tuple[int, int, int]]:
    found = []
    pos = rom.find(magic)
    while pos != -1:
        result = try_inflate(rom, pos + skip, wbits)
        if result:
            comp, inflated = result
            found.append((pos, comp + skip, inflated))
            pos = rom.find(magic, pos + skip + comp)  # skip past this stream
        else:
            pos = rom.find(magic, pos + 1)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rom", type=Path, default=ROM_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.rom.exists():
        print(f"FAIL: {args.rom} not found. Run tools/romcheck.py first.")
        return 1
    rom = args.rom.read_bytes()
    if rom[:4] != bytes.fromhex("80371240"):
        print("FAIL: ROM isn't in z64 byte order. Run tools/romcheck.py for the fix.")
        return 1

    ucode = find_microcode_strings(rom)
    rare = find_streams(rom, RARE_MAGIC, skip=2, wbits=-15)  # 11 72 + raw deflate
    gzip = find_streams(rom, GZIP_MAGIC, skip=0, wbits=31)   # standard gzip

    rare_in = sum(c for _, c, _ in rare)
    rare_out = sum(i for _, _, i in rare)

    print("== Microcode and RSP strings ==")
    print(f"{len(ucode)} string(s) found" + (" (first 15 below, all in the report)" if len(ucode) > 15 else ""))
    for off, text in ucode[:15]:
        print(f"  0x{off:07X}  {text}")

    print("\n== Rare 1172 compression ==")
    if rare:
        print(f"{len(rare)} valid stream(s): {rare_in:,} bytes compressed, {rare_out:,} bytes inflated")
        print(f"  first at 0x{rare[0][0]:07X}, last at 0x{rare[-1][0]:07X}")
    else:
        print("None found. KI Gold may use a different or earlier compression scheme.")

    print("\n== Standard gzip streams ==")
    print(f"{len(gzip)} found" if gzip else "None found.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as report:
        report.write("# KI Gold recon scan (contains ROM strings: keep out of git)\n\n")
        report.write("## Microcode and RSP strings\n")
        for off, text in ucode:
            report.write(f"0x{off:07X}  {text}\n")
        report.write("\n## Rare 1172 streams (offset, compressed size, inflated size)\n")
        for off, comp, inflated in rare:
            report.write(f"0x{off:07X}  {comp:>9,}  {inflated:>9,}\n")
        report.write("\n## gzip streams (offset, compressed size, inflated size)\n")
        for off, comp, inflated in gzip:
            report.write(f"0x{off:07X}  {comp:>9,}  {inflated:>9,}\n")
    print(f"\nFull report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
