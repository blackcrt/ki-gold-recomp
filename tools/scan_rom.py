#!/usr/bin/env python3
"""Recon scan of baserom.us.z64 for Phase 1.

Answers these early questions without disassembling anything:
  1. Which graphics and audio microcode does the game use?
     (looks for microcode name strings like "F3DEX" or "RSP Gfx ucode",
     both in the raw ROM and inside inflated 1172 streams)
  2. Does the game use Rare's "1172" compression?
     (finds 11 72 headers and test-inflates the raw deflate stream after them)
  3. Are there plain gzip streams?
  4. Is any game code compressed? (counts "jr ra" in each inflated stream)
  5. Where is the uncompressed code? (counts "jr ra" per 16 KB block of ROM)

Usage:
  python3 tools/scan_rom.py                 # print a summary
  python3 tools/scan_rom.py --out FILE      # also write the full report to FILE
  python3 tools/test_scan_rom.py            # known-answer test on a synthetic ROM

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

# "jr ra" is how nearly every MIPS function returns. Compiled code has one every
# 50 to 100 instructions; a random 4-byte word matches once in 4 billion.
JR_RA = bytes.fromhex("03E00008")
CODE_MIN_JR_RA = 3          # fewer than this is never called "code"
CODE_MIN_PER_KWORD = 3.0    # jr ra per 1000 words (4-byte instructions)
BLOCK = 0x4000              # 16 KB blocks for the uncompressed code map
SCAN_START = 0x1000         # skip the ROM header and boot code


def find_microcode_strings(data: bytes) -> list[tuple[int, str]]:
    hits = []
    for match in PRINTABLE.finditer(data):
        text = match.group()
        if MICROCODE_HINTS.search(text):
            hits.append((match.start(), text.decode("ascii")[:100]))
    return hits


def try_inflate(rom: bytes, start: int, wbits: int) -> tuple[int, bytes] | None:
    """Return (compressed_size, inflated_bytes) if a complete stream starts here."""
    decomp = zlib.decompressobj(wbits)
    chunk = rom[start:start + MAX_INPUT]
    try:
        out = decomp.decompress(chunk)
    except zlib.error:
        return None
    if not decomp.eof or len(out) < MIN_INFLATED:
        return None
    return len(chunk) - len(decomp.unused_data), out


def find_streams(rom: bytes, magic: bytes, skip: int, wbits: int) -> list[tuple[int, int, bytes]]:
    """Return (offset, compressed_size, inflated_bytes) for each valid stream."""
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


def count_jr_ra(data: bytes, start: int = 0, end: int | None = None) -> int:
    """Count jr ra instructions at 4-byte-aligned offsets (start must be aligned)."""
    end = len(data) if end is None else end
    count = 0
    pos = data.find(JR_RA, start, end)
    while pos != -1:
        if pos % 4 == 0:
            count += 1
        pos = data.find(JR_RA, pos + 1, end)
    return count


def classify(jr_ra: int, size: int) -> str:
    """Return "code", "maybe" (a few jr ra, too sparse to be sure), or "data"."""
    if jr_ra == 0:
        return "data"
    per_kword = jr_ra / max(size / 4, 1) * 1000
    if jr_ra >= CODE_MIN_JR_RA and per_kword >= CODE_MIN_PER_KWORD:
        return "code"
    return "maybe"


def find_code_ranges(rom: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    """Return (start, end, jr_ra) for each run of code-like 16 KB blocks."""
    ranges = []
    for block in range(start, end, BLOCK):
        block_end = min(block + BLOCK, end)
        jr_ra = count_jr_ra(rom, block, block_end)
        if classify(jr_ra, block_end - block) != "code":
            continue
        if ranges and ranges[-1][1] == block:
            ranges[-1] = (ranges[-1][0], block_end, ranges[-1][2] + jr_ra)
        else:
            ranges.append((block, block_end, jr_ra))
    return ranges


def analyze(rom: bytes) -> dict:
    """Run every check and return the findings. Kept separate from printing so
    tools/test_scan_rom.py can check it against a synthetic ROM."""
    rare = []
    for off, comp, data in find_streams(rom, RARE_MAGIC, skip=2, wbits=-15):  # 11 72 + raw deflate
        jr_ra = count_jr_ra(data)
        rare.append({
            "offset": off,
            "comp": comp,
            "inflated": len(data),
            "jr_ra": jr_ra,
            "kind": classify(jr_ra, len(data)),
            "ucode": find_microcode_strings(data),
        })
    gzip = [(off, comp, len(data))
            for off, comp, data in find_streams(rom, GZIP_MAGIC, skip=0, wbits=31)]  # standard gzip
    before_end = rare[0]["offset"] if rare else len(rom)
    return {
        "ucode": find_microcode_strings(rom),
        "rare": rare,
        "gzip": gzip,
        "code_ranges": find_code_ranges(rom, SCAN_START, len(rom)),
        "before_end": before_end,
        "before_jr_ra": count_jr_ra(rom, SCAN_START, before_end),
    }


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

    found = analyze(rom)
    ucode, rare, gzip = found["ucode"], found["rare"], found["gzip"]
    rare_in = sum(s["comp"] for s in rare)
    rare_out = sum(s["inflated"] for s in rare)
    rare_ucode = [(s["offset"], off, text) for s in rare for off, text in s["ucode"]]

    print("== Microcode and RSP strings (raw ROM) ==")
    print(f"{len(ucode)} string(s) found" + (" (first 15 below, all in the report)" if len(ucode) > 15 else ""))
    for off, text in ucode[:15]:
        print(f"  0x{off:07X}  {text}")

    print("\n== Microcode and RSP strings (inside inflated 1172 streams) ==")
    print(f"{len(rare_ucode)} string(s) found" + (" (first 15 below, all in the report)" if len(rare_ucode) > 15 else ""))
    for stream, off, text in rare_ucode[:15]:
        print(f"  stream 0x{stream:07X} +0x{off:X}  {text}")

    print("\n== Rare 1172 compression ==")
    if rare:
        print(f"{len(rare)} valid stream(s): {rare_in:,} bytes compressed, {rare_out:,} bytes inflated")
        print(f"  first at 0x{rare[0]['offset']:07X}, last at 0x{rare[-1]['offset']:07X}")
        for kind, label in (("code", "look like MIPS code"), ("maybe", "have a few jr ra (unclear)"),
                            ("data", "look like data (no jr ra)")):
            group = [s for s in rare if s["kind"] == kind]
            print(f"  {len(group):>3} {label}: {sum(s['inflated'] for s in group):,} bytes inflated, "
                  f"{sum(s['jr_ra'] for s in group):,} jr ra")
    else:
        print("None found. KI Gold may use a different or earlier compression scheme.")

    print("\n== Standard gzip streams ==")
    print(f"{len(gzip)} found" if gzip else "None found.")

    print("\n== Uncompressed code (16 KB blocks dense in jr ra) ==")
    before_size = found["before_end"] - SCAN_START
    print(f"Before the first 1172 stream (0x{SCAN_START:07X} to 0x{found['before_end']:07X}): "
          f"{found['before_jr_ra']:,} jr ra in {before_size:,} bytes, "
          f"verdict: {classify(found['before_jr_ra'], before_size)}")
    print(f"{len(found['code_ranges'])} code-like range(s) in the whole ROM:")
    for start, end, jr_ra in found["code_ranges"]:
        print(f"  0x{start:07X} to 0x{end:07X}  {end - start:>9,} bytes  {jr_ra:>6,} jr ra")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as report:
        report.write("# KI Gold recon scan (contains ROM strings: keep out of git)\n\n")
        report.write("## Microcode and RSP strings (raw ROM)\n")
        for off, text in ucode:
            report.write(f"0x{off:07X}  {text}\n")
        report.write("\n## Microcode and RSP strings (inside inflated 1172 streams: stream, offset in stream)\n")
        for stream, off, text in rare_ucode:
            report.write(f"0x{stream:07X} +0x{off:X}  {text}\n")
        report.write("\n## Rare 1172 streams (offset, compressed size, inflated size, jr ra, verdict)\n")
        for s in rare:
            report.write(f"0x{s['offset']:07X}  {s['comp']:>9,}  {s['inflated']:>9,}  {s['jr_ra']:>6,}  {s['kind']}\n")
        report.write("\n## gzip streams (offset, compressed size, inflated size)\n")
        for off, comp, inflated in gzip:
            report.write(f"0x{off:07X}  {comp:>9,}  {inflated:>9,}\n")
        report.write("\n## Uncompressed code-like ranges (start, end, size, jr ra)\n")
        for start, end, jr_ra in found["code_ranges"]:
            report.write(f"0x{start:07X}  0x{end:07X}  {end - start:>9,}  {jr_ra:>6,}\n")
    print(f"\nFull report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
