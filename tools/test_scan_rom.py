#!/usr/bin/env python3
"""Known-answer test for tools/scan_rom.py (ground rule 4).

Builds a synthetic ROM in memory with known contents and checks the scanner
reports exactly those. Uses no real ROM data.

Usage:
  python3 tools/test_scan_rom.py
"""

import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scan_rom

# One fake 16-instruction function: addiu sp,sp,-24; 12 nops; jr ra; addiu sp,sp,24; nop.
FAKE_FUNC = bytes.fromhex("27BDFFE8") + bytes(48) + bytes.fromhex("03E00008" "27BD0018") + bytes(4)
FAKE_UCODE = b"RSP Gfx ucode TEST fifo 0.00 synthetic"


def rare_stream(payload: bytes) -> bytes:
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    return scan_rom.RARE_MAGIC + comp.compress(payload) + comp.flush()


def pad(rom: bytearray, size: int) -> None:
    rom += bytes(size - len(rom))


def build() -> tuple[bytes, dict]:
    rom = bytearray(bytes.fromhex("80371240"))
    pad(rom, 0x1000)
    rom += FAKE_FUNC * 1024          # 64 KB of code, 1024 jr ra, at 0x1000
    pad(rom, 0x20000)
    rom += b"\x00\x00" + scan_rom.JR_RA  # misaligned jr ra: must not be counted
    pad(rom, 0x24000)
    offsets = {}
    for name, payload in (
        ("data", bytes(range(256)) * 16),
        ("code", FAKE_FUNC * 100),
        ("ucode", bytes(256) + FAKE_UCODE + bytes(256)),
        ("maybe", bytes(8192) + scan_rom.JR_RA),
    ):
        offsets[name] = len(rom)
        rom += rare_stream(payload)
        pad(rom, (len(rom) + 0x100) & ~0xF)
    pad(rom, 0x41000)                # on a 16 KB block boundary (blocks start at 0x1000)
    rom += FAKE_FUNC * 256           # 16 KB of code after the streams
    return bytes(rom), offsets


def main() -> int:
    rom, offsets = build()
    found = scan_rom.analyze(rom)
    rare = {s["offset"]: s for s in found["rare"]}
    checks = [
        ("finds exactly the 4 planted streams", sorted(rare) == sorted(offsets.values())),
        ("no microcode string in the raw ROM", found["ucode"] == []),
        ("no gzip streams", found["gzip"] == []),
        ("data stream is data", rare[offsets["data"]]["kind"] == "data"),
        ("data stream inflated size", rare[offsets["data"]]["inflated"] == 4096),
        ("code stream is code", rare[offsets["code"]]["kind"] == "code"),
        ("code stream has 100 jr ra", rare[offsets["code"]]["jr_ra"] == 100),
        ("sparse stream is maybe", rare[offsets["maybe"]]["kind"] == "maybe"),
        ("microcode string found inside its stream",
         rare[offsets["ucode"]]["ucode"] == [(256, FAKE_UCODE.decode())]),
        ("no microcode string in the other streams",
         all(not s["ucode"] for off, s in rare.items() if off != offsets["ucode"])),
        ("region before first stream ends at it", found["before_end"] == offsets["data"]),
        ("region before first stream has 1024 aligned jr ra", found["before_jr_ra"] == 1024),
        ("code ranges are the two planted ones",
         found["code_ranges"] == [(0x1000, 0x11000, 1024), (0x41000, 0x45000, 256)]),
        ("zero jr ra is classified as data", scan_rom.classify(0, 4096) == "data"),
    ]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
