#!/usr/bin/env python3
"""Report decomp progress: how much code is matched C vs still assembly.

How it works (splat layout):
  - splat writes every function to asm/nonmatchings/<path>/<func>.s
  - a C file still using assembly for a function has a line like
        INCLUDE_ASM("asm/nonmatchings/<path>", <func>);
  - a function counts as MATCHED when its .s exists but no INCLUDE_ASM uses it
  - code in other asm/ files (hand-written or not yet split into C) counts as unmatched

Usage:
  python3 tools/progress.py          # print progress
  python3 tools/progress.py --log    # also append a line to docs/progress.csv
"""

import argparse
import csv
import datetime
import re
import sys
from pathlib import Path

ASM_DIR = Path("asm")
NONMATCHING_DIR = ASM_DIR / "nonmatchings"
SRC_DIR = Path("src")
LOG_FILE = Path("docs/progress.csv")

# splat instruction lines look like: /* 1050 80000450 27BDFFE8 */  addiu $sp, $sp, -0x18
INSTRUCTION = re.compile(r"^\s*/\*\s*[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]{8}\s*\*/", re.MULTILINE)
INCLUDE_ASM = re.compile(r'INCLUDE_ASM\(\s*"([^"]+)"\s*,\s*([A-Za-z0-9_]+)\s*\)')


def code_bytes(path: Path) -> int:
    return 4 * len(INSTRUCTION.findall(path.read_text(errors="replace")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", action="store_true", help=f"append a line to {LOG_FILE}")
    args = parser.parse_args()

    if not NONMATCHING_DIR.exists() and not ASM_DIR.exists():
        print("Nothing split yet. Run the splat split first (make split).")
        return 0

    functions = {p.resolve(): code_bytes(p) for p in NONMATCHING_DIR.rglob("*.s")} if NONMATCHING_DIR.exists() else {}

    still_asm = set()
    for c_file in SRC_DIR.rglob("*.c") if SRC_DIR.exists() else []:
        for folder, name in INCLUDE_ASM.findall(c_file.read_text(errors="replace")):
            still_asm.add((Path(folder) / f"{name}.s").resolve())

    loose_bytes = sum(
        code_bytes(p) for p in ASM_DIR.rglob("*.s")
        if NONMATCHING_DIR not in p.parents
    ) if ASM_DIR.exists() else 0

    total_funcs = len(functions)
    matched_funcs = sum(1 for p in functions if p not in still_asm)
    func_bytes = sum(functions.values())
    matched_bytes = sum(b for p, b in functions.items() if p not in still_asm)
    total_bytes = func_bytes + loose_bytes

    def pct(part: int, whole: int) -> str:
        return f"{100 * part / whole:6.2f}%" if whole else "   n/a"

    print(f"Functions matched: {matched_funcs:>6,} / {total_funcs:<6,} {pct(matched_funcs, total_funcs)}")
    print(f"Code bytes in C:   {matched_bytes:>6,} / {total_bytes:<6,} {pct(matched_bytes, total_bytes)}")
    if loose_bytes:
        print(f"  ({loose_bytes:,} bytes are in asm files outside nonmatchings/, counted as not yet in C)")

    if args.log:
        new_file = not LOG_FILE.exists()
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", newline="") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(["date", "functions_matched", "functions_total", "bytes_matched", "bytes_total"])
            writer.writerow([datetime.date.today().isoformat(), matched_funcs, total_funcs, matched_bytes, total_bytes])
        print(f"Logged to {LOG_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
