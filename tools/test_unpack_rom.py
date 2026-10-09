#!/usr/bin/env python3
"""Known-answer test for tools/unpack_rom.py (ground rule 4).

Builds a synthetic ROM in memory with a stream table and known payloads, and
checks the unpacker appends exactly those payloads. Uses no real ROM data.

Usage:
  python3 tools/test_unpack_rom.py
"""

import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import unpack_rom
from unpack_rom import UnpackError

# One fake 16-instruction function: addiu sp,sp,-24; 12 nops; jr ra; addiu sp,sp,24; nop.
FAKE_FUNC = bytes.fromhex("27BDFFE8") + bytes(48) + bytes.fromhex("03E00008" "27BD0018") + bytes(4)
TABLE = 0x400
PAYLOADS = {
    "a": FAKE_FUNC * 50 + b"\x01\x02\x03",          # odd length: forces padding before the next one
    "b": FAKE_FUNC * 200 + bytes(range(256)) * 8,   # code then data
    "c": FAKE_FUNC * 20,
}
# Table order differs from segment order on purpose, and a and b overlap in RAM.
SEGMENTS = [
    {"name": "a", "table_index": 2, "vram": 0x80010000, "site": 0, "code_size": None},
    {"name": "b", "table_index": 0, "vram": 0x80100000, "site": 0, "code_size": 0x3200},
    {"name": "c", "table_index": 3, "vram": 0x80100400, "site": 0, "code_size": 0x500},
]


def rare_stream(payload: bytes) -> bytes:
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    return b"\x11\x72" + comp.compress(payload) + comp.flush()


def build() -> bytes:
    rom = bytearray(bytes.fromhex("80371240"))
    rom += bytes(0x1000 - len(rom))
    entries = {}
    # Table index 1 is a data stream the unpacker must leave alone.
    for index, payload in ((0, PAYLOADS["b"]), (1, bytes(512)), (2, PAYLOADS["a"]), (3, PAYLOADS["c"])):
        start = len(rom)
        rom += rare_stream(payload)
        rom += bytes(-len(rom) % 16)     # table ends include alignment padding, as in the real ROM
        entries[index] = (start, len(rom))
    rom += b"\xFF" * (0x4000 - len(rom))
    for index, (start, end) in entries.items():
        struct.pack_into(">II", rom, TABLE + index * 8, start, end)
    return bytes(rom)


def fails(rom: bytes) -> bool:
    try:
        unpack_rom.unpack(rom, SEGMENTS, TABLE)
    except UnpackError:
        return True
    return False


def main() -> int:
    rom = build()
    out, layout = unpack_rom.unpack(rom, SEGMENTS, TABLE)
    seg = {s["name"]: s for s in layout}
    parsed = tomllib.loads(unpack_rom.layout_toml(layout, len(rom), len(out)))

    bad_magic = bytearray(rom)
    bad_magic[seg["a"]["compressed_rom"]] = 0x12
    cut_off = bytearray(rom)
    struct.pack_into(">I", cut_off, TABLE + 0 * 8 + 4, seg["b"]["compressed_rom"] + 20)
    bad_table = bytearray(rom)
    struct.pack_into(">I", bad_table, TABLE + 3 * 8, len(rom) + 0x100)

    checks = [
        ("original ROM is unchanged at the start", out[:len(rom)] == rom),
        ("segments come out in the order asked for", [s["name"] for s in layout] == ["a", "b", "c"]),
        ("first segment starts right after the original ROM", seg["a"]["rom"] == 0x4000),
        ("every segment is 16-byte aligned", all(s["rom"] % 16 == 0 for s in layout)),
        ("second segment follows the first with padding", seg["b"]["rom"] == 0x4000 + 0xC90),
        ("segments don't overlap in the ROM",
         all(a["rom"] + a["size"] <= b["rom"] for a, b in zip(layout, layout[1:]))),
        ("each segment holds exactly its payload",
         all(out[s["rom"]:s["rom"] + s["size"]] == PAYLOADS[s["name"]] for s in layout)),
        ("sizes are the payload sizes", all(s["size"] == len(PAYLOADS[s["name"]]) for s in layout)),
        ("output ends 16-byte aligned, right after the last segment",
         len(out) == seg["c"]["rom"] + seg["c"]["size"] and len(out) % 16 == 0),
        ("compressed offsets come from the table",
         all(rom[s["compressed_rom"]:s["compressed_rom"] + 2] == b"\x11\x72" for s in layout)),
        ("RAM addresses are passed through", [s["vram"] for s in layout] == [0x80010000, 0x80100000, 0x80100400]),
        ("code check counts jr ra in the first 64 KB", [s["jr_ra_early"] for s in layout] == [50, 200, 20]),
        ("code segments pass the code check", all(s["looks_like_code"] for s in layout)),
        ("a data-only segment fails the code check",
         not unpack_rom.unpack(rom, [dict(SEGMENTS[0], table_index=1)], TABLE)[1][0]["looks_like_code"]),
        ("RAM overlap between b and c is reported", unpack_rom.overlaps(layout) == [("b", "c")]),
        ("layout file parses and matches",
         [(s["name"], s["rom"], s["vram"], s["size"]) for s in parsed["segment"]]
         == [(s["name"], s["rom"], s["vram"], s["size"]) for s in layout]
         and parsed["original_size"] == len(rom) and parsed["total_size"] == len(out)),
        ("layout file leaves out an unknown code size",
         "code_size" not in parsed["segment"][0] and parsed["segment"][1]["code_size"] == 0x3200),
        ("a wrong 1172 header is rejected", fails(bytes(bad_magic))),
        ("a cut-off stream is rejected", fails(bytes(cut_off))),
        ("a table entry outside the ROM is rejected", fails(bytes(bad_table))),
    ]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
