#!/usr/bin/env python3
"""Regenerate the recompiled C code in one command.

Runs the steps in the only order that works:
  1. Unpack check: build/kigold.decompressed.z64 must match the SHA1 in
     disasm/kigold.yaml. If it is missing or different, tools/unpack_rom.py
     rebuilds it from baserom.us.z64.
  2. Split: splat disassembles the ROM into disasm/asm/.
  3. Symbols: tools/gen_symbols.py writes syms/dump.toml from the split.
  4. Recompile: N64Recomp reads kigold.toml and writes RecompiledFuncs/.
  5. Report: function count, and calls to functions that have no body.

Cleanup scripts (ground rule 2 in PLAN.md) will run between steps 4 and 5
once they exist.

Usage:
  python3 tools/regen.py

RecompiledFuncs/ is generated game code: never commit it, never edit it by hand.
"""

import hashlib
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO / "disasm" / ".venv" / "bin" / "python"
N64RECOMP = REPO / "build" / "N64Recomp" / "build-linux" / "N64Recomp"
SPLAT_CONFIG = REPO / "disasm" / "kigold.yaml"
RECOMP_CONFIG = REPO / "kigold.toml"
ROM = REPO / "build" / "kigold.decompressed.z64"
OUT_DIR = REPO / "RecompiledFuncs"
SPLIT_LOG = REPO / "build" / "split.log"

DEFINED = re.compile(r"^RECOMP_FUNC void (\w+)\(", re.MULTILINE)
CALLED = re.compile(r"^\s+(\w+)\(rdram, ctx\);", re.MULTILINE)


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def rom_ok() -> bool:
    want = re.search(r"^sha1:\s*([0-9a-f]{40})", SPLAT_CONFIG.read_text(), re.MULTILINE)
    return bool(want) and ROM.exists() and hashlib.sha1(ROM.read_bytes()).hexdigest() == want.group(1)


def calls_without_body(out_dir: Path) -> tuple[int, Counter]:
    """Count the functions written, and the calls to names that have no body."""
    defined, called = set(), Counter()
    for path in sorted(out_dir.glob("*.c")):
        text = path.read_text()
        defined.update(DEFINED.findall(text))
        called.update(CALLED.findall(text))
    return len(defined), Counter({name: n for name, n in called.items() if name not in defined})


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # keep our lines in order with the tools' output
    for needed in (VENV_PYTHON, N64RECOMP):
        if not needed.exists():
            return fail(f"{needed} is missing. See docs/SETUP.md.")

    print("[1/5] Unpack check")
    if rom_ok():
        print(f"  {ROM.relative_to(REPO)} matches the SHA1 in disasm/kigold.yaml")
    else:
        print("  decompressed ROM is missing or different, rebuilding it")
        if subprocess.run([sys.executable, "tools/unpack_rom.py"], cwd=REPO).returncode != 0:
            return fail("tools/unpack_rom.py")
        if not rom_ok():
            return fail("the rebuilt ROM still does not match the SHA1 in disasm/kigold.yaml")

    print("[2/5] Split (splat)")
    split = subprocess.run([str(VENV_PYTHON), "-m", "splat", "split", SPLAT_CONFIG.name],
                           cwd=SPLAT_CONFIG.parent, capture_output=True, text=True)
    SPLIT_LOG.write_text(split.stdout + split.stderr)
    print(f"  exit {split.returncode}, full output in {SPLIT_LOG.relative_to(REPO)}")
    if split.returncode != 0:
        return fail("splat split")

    print("[3/5] Symbols (gen_symbols.py)")
    if subprocess.run([str(VENV_PYTHON), "tools/gen_symbols.py"], cwd=REPO).returncode != 0:
        return fail("tools/gen_symbols.py")

    print("[4/5] Recompile (N64Recomp)")
    # Start from an empty folder so no file from an older run is left behind.
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    recomp = subprocess.run([str(N64RECOMP), RECOMP_CONFIG.name], cwd=REPO, capture_output=True, text=True)
    output = recomp.stdout + recomp.stderr
    # N64Recomp prints hundreds of "Tail call" lines for stream3; show the rest.
    for line in output.splitlines():
        if line.strip() and "ail call in " not in line:
            print(f"  {line}")
    print(f"  ({output.count('ail call in ')} tail call notes hidden)")
    print(f"  N64Recomp exit code: {recomp.returncode}")
    if recomp.returncode != 0:
        return fail("N64Recomp")

    print("[5/5] Report")
    bodies, missing = calls_without_body(OUT_DIR)
    print(f"  {len(list(OUT_DIR.iterdir()))} files in {OUT_DIR.name}/, {bodies} function bodies")
    print(f"  __osGetCause_recomp calls: {missing.get('__osGetCause_recomp', 0)}")
    print(f"  calls to names with no body: {sum(missing.values())} calls, {len(missing)} names")
    print("  (the runtime must provide every one of these, or the link fails)")
    for name, count in sorted(missing.items()):
        print(f"    {count:4d}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
