#!/usr/bin/env python3
"""Check that baserom.us.z64 is the right ROM, in the right byte order.

Usage:
  python3 tools/romcheck.py                      # check baserom.us.z64
  python3 tools/romcheck.py --convert FILE       # convert a .v64/.n64 ROM into baserom.us.z64

Prints the ROM header (name, region, revision, entry point, libultra
version) and compares the SHA1 with tools/rom.sha1. Never prints ROM bytes.
"""

import argparse
import hashlib
import struct
import sys
from pathlib import Path

ROM_PATH = Path("baserom.us.z64")
SHA1_FILE = Path("tools/rom.sha1")
EXPECTED_SIZE = 12 * 1024 * 1024  # KI Gold is a 96 megabit (12 MB) cart

ORDERS = {
    bytes.fromhex("80371240"): "z64",  # big-endian, what the tools want
    bytes.fromhex("37804012"): "v64",  # byte-swapped
    bytes.fromhex("40123780"): "n64",  # little-endian (word-swapped)
}

REGIONS = {"E": "USA", "J": "Japan", "P": "Europe", "D": "Germany", "F": "France", "U": "Australia"}


def to_z64(data: bytes, order: str) -> bytes:
    if order == "z64":
        return data
    out = bytearray(data)
    if order == "v64":
        out[0::2], out[1::2] = data[1::2], data[0::2]
    elif order == "n64":
        for i in range(0, len(out) - 3, 4):
            out[i:i + 4] = data[i:i + 4][::-1]
    return bytes(out)


def expected_sha1() -> str | None:
    if not SHA1_FILE.exists():
        return None
    for line in SHA1_FILE.read_text().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#") and len(line) == 40:
            return line
    return None


def convert(src: Path) -> int:
    data = src.read_bytes()
    order = ORDERS.get(data[:4])
    if order is None:
        print(f"FAIL: {src} doesn't start with an N64 ROM header.")
        return 1
    if ROM_PATH.exists():
        print(f"FAIL: {ROM_PATH} already exists. Move or delete it first if you really want to replace it.")
        return 1
    ROM_PATH.write_bytes(to_z64(data, order))
    print(f"Converted {src} ({order}) to {ROM_PATH} (z64). Now run: python3 tools/romcheck.py")
    return 0


def check() -> int:
    if not ROM_PATH.exists():
        print(f"FAIL: {ROM_PATH} not found. Copy your ROM into the repo root with that exact name.")
        return 1

    data = ROM_PATH.read_bytes()
    problems = 0

    order = ORDERS.get(data[:4])
    if order is None:
        print("FAIL: this file doesn't start with an N64 ROM header.")
        return 1
    if order != "z64":
        print(f"FAIL: ROM is in {order} byte order. Fix it with:")
        print(f"  mv {ROM_PATH} rom_original.{order} && python3 tools/romcheck.py --convert rom_original.{order}")
        return 1

    clock, entry, libver = struct.unpack_from(">III", data, 0x04)
    crc1, crc2 = struct.unpack_from(">II", data, 0x10)
    name = data[0x20:0x34].decode("ascii", "replace").strip()
    game_id = data[0x3B:0x3F].decode("ascii", "replace")
    revision = data[0x3F]
    region = REGIONS.get(game_id[3:4], f"unknown ({game_id[3:4]})")
    libultra = f"{(libver >> 8 & 0xFF) / 10:.1f}{chr(libver & 0xFF)}" if 0x41 <= (libver & 0xFF) <= 0x5A else f"0x{libver:08X}"

    print(f"Name:         {name}")
    print(f"Game ID:      {game_id}")
    print(f"Region:       {region}")
    print(f"Revision:     {revision} (V1.{revision})")
    print(f"Entry point:  0x{entry:08X}")
    print(f"libultra:     {libultra}")
    print(f"Header CRCs:  {crc1:08X} {crc2:08X}")
    print(f"Size:         {len(data):,} bytes ({len(data) / 1024 / 1024:.2f} MB)")

    if region != "USA":
        print("WARN: not a USA ROM. The project targets USA V1.2.")
        problems += 1
    if revision != 2:
        print("WARN: not revision 2. The project targets V1.2.")
        problems += 1
    if len(data) > EXPECTED_SIZE:
        print(f"WARN: bigger than 12 MB. This may be an overdump; trim to {EXPECTED_SIZE:,} bytes.")
        problems += 1
    elif len(data) < EXPECTED_SIZE:
        print("WARN: smaller than 12 MB. The dump may be incomplete.")
        problems += 1

    actual = hashlib.sha1(data).hexdigest()
    print(f"SHA1:         {actual}")
    want = expected_sha1()
    if want is None:
        print("NOTE: tools/rom.sha1 is empty. Paste the SHA1 above into it, then commit that file.")
    elif want == actual:
        print("OK: SHA1 matches tools/rom.sha1.")
    else:
        print(f"FAIL: SHA1 doesn't match tools/rom.sha1 ({want}).")
        problems += 1

    print("\nResult:", "all good" if problems == 0 else f"{problems} issue(s) above")
    return 0 if problems == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--convert", type=Path, metavar="FILE", help="convert a .v64/.n64 ROM to baserom.us.z64")
    args = parser.parse_args()
    return convert(args.convert) if args.convert else check()


if __name__ == "__main__":
    sys.exit(main())
