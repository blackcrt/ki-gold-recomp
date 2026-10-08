#!/usr/bin/env python3
"""Legal guard for the KI Gold decomp.

Blocks anything that could be game data from being committed:
ROM files, extracted or generated output, binary files, large files,
and any file that looks like or matches the N64 ROM.

Usage:
  python3 tools/guard.py --staged   # check what's about to be committed (pre-commit hook)
  python3 tools/guard.py --all      # check every tracked file (GitHub Actions)

Exit code 0 means clean, 1 means something was blocked.
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path, PurePosixPath

# Files bigger than this are blocked. Real source files are tiny.
MAX_BYTES = 512 * 1024

# Extensions that are never allowed, anywhere.
BLOCKED_EXTENSIONS = {
    ".z64", ".n64", ".v64", ".rom", ".ndd",  # ROMs
    ".bin", ".o", ".elf", ".exe", ".dll",    # binaries and build output
    ".zip", ".7z", ".rar", ".tar", ".gz",    # archives can hide anything
}

# Filename prefixes that are never allowed.
BLOCKED_PREFIXES = ("baserom",)

# Folders that only ever hold generated or extracted output.
BLOCKED_DIRS = {
    "build", "asm", "assets", "bin", "expected", "nonmatchings",
    "recompiledfuncs", "recompiledpatches",  # N64Recomp output: translated game code
}

# Generated files that live next to files we do commit.
BLOCKED_GLOBS = (
    "rsp/*.cpp",  # RSPRecomp output: translated audio microcode
)

# Binary files are only allowed for these image types, inside docs/images/.
ALLOWED_BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_BINARY_DIR = PurePosixPath("docs/images")

# The first 4 bytes of an N64 ROM in each byte order.
ROM_MAGIC = {
    bytes.fromhex("80371240"): "big-endian (.z64)",
    bytes.fromhex("37804012"): "byte-swapped (.v64)",
    bytes.fromhex("40123780"): "little-endian (.n64)",
}

SHA1_FILE = Path("tools/rom.sha1")


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def known_rom_sha1() -> str | None:
    """Read the expected ROM SHA1 from tools/rom.sha1, ignoring comment lines."""
    if not SHA1_FILE.exists():
        return None
    for line in SHA1_FILE.read_text().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#") and len(line) == 40:
            return line
    return None


def staged_files() -> list[tuple[str, bytes]]:
    names = git("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    files = []
    for name in filter(None, names.decode().split("\0")):
        files.append((name, git("show", f":{name}")))  # the staged version
    return files


def tracked_files() -> list[tuple[str, bytes]]:
    names = git("ls-files", "-z")
    files = []
    for name in filter(None, names.decode().split("\0")):
        path = Path(name)
        if path.is_file():
            files.append((name, path.read_bytes()))
    return files


def looks_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def check(name: str, data: bytes, rom_sha1: str | None) -> list[str]:
    problems = []
    path = PurePosixPath(name)
    suffix = path.suffix.lower()

    if suffix in BLOCKED_EXTENSIONS:
        problems.append(f"'{suffix}' files are never allowed")
    if path.name.lower().startswith(BLOCKED_PREFIXES):
        problems.append("files named 'baserom...' are the ROM and never allowed")
    if BLOCKED_DIRS.intersection(part.lower() for part in path.parts[:-1]):
        problems.append("this folder only holds generated or extracted output")
    if any(path.match(pattern) for pattern in BLOCKED_GLOBS):
        problems.append("this is generated code (recompiler output)")
    if len(data) > MAX_BYTES:
        problems.append(f"file is {len(data) // 1024} KB, over the {MAX_BYTES // 1024} KB limit")
    if data[:4] in ROM_MAGIC:
        problems.append(f"file starts with an N64 ROM header, {ROM_MAGIC[data[:4]]}")
    if rom_sha1 and hashlib.sha1(data).hexdigest() == rom_sha1:
        problems.append("file is byte-identical to the ROM")
    if looks_binary(data):
        allowed = suffix in ALLOWED_BINARY_EXTENSIONS and ALLOWED_BINARY_DIR in path.parents
        if not allowed:
            problems.append("binary file (only images inside docs/images/ are allowed)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check staged files")
    mode.add_argument("--all", action="store_true", help="check all tracked files")
    args = parser.parse_args()

    files = staged_files() if args.staged else tracked_files()
    rom_sha1 = known_rom_sha1()

    blocked = {}
    for name, data in files:
        problems = check(name, data, rom_sha1)
        if problems:
            blocked[name] = problems

    if not blocked:
        print(f"guard: OK ({len(files)} file(s) checked)")
        return 0

    print("guard: BLOCKED. These files can't be committed:\n")
    for name, problems in blocked.items():
        print(f"  {name}")
        for problem in problems:
            print(f"    - {problem}")
    if args.staged:
        print("\nTo unstage a file:  git restore --staged <file>")
        print("Do not bypass this check with --no-verify.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
