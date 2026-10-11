#!/usr/bin/env python3
"""Cleanup step: chain functions that fall through into the next function.

Hand-written assembly (stream3) often lets one routine run off its end into the
routine below it. N64Recomp turns each routine into one C function and simply
ends the C function there, so the game would return to the caller instead of
carrying on. No warning is printed. This step adds the missing link: a call to
the next function and a return, the same two lines N64Recomp writes for a
branch into another function's start.

Which functions fall through is decided from the MIPS code, not from the C:
  - syms/dump.toml gives every function's address and size.
  - The decompressed ROM gives its instructions.
  - A function "falls" when following its branches from its first instruction
    reaches the address just past its end.
  - A function "falls (unseen entry)" when its last stretch of code is not
    closed by a jump, but nothing inside the function leads there. That code is
    either dead or entered through a table the tracer could not follow. It gets
    the same fix: harmless if dead, needed if not.

Reported and left alone:
  - Functions whose last instruction is itself a branch or jump. Its delay slot
    is the first instruction of the next function, which a call cannot express.
  - Functions that fall off into something that is not a function.
  - Stubbed functions (empty on purpose) and functions with no body in the C.

Running it twice changes nothing the second time: fixed functions carry a
marker comment. tools/regen.py runs this after N64Recomp. Never fix the
generated C by hand.

Usage:
  python3 tools/fix_fallthroughs.py          # fix RecompiledFuncs/ in place
  python3 tools/test_fix_fallthroughs.py     # known-answer test on a made-up example
"""

import re
import struct
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYMBOLS = REPO / "syms" / "dump.toml"
ROM = REPO / "build" / "kigold.decompressed.z64"
RECOMP_CONFIG = REPO / "kigold.toml"
OUT_DIR = REPO / "RecompiledFuncs"

MARKER = "added by tools/fix_fallthroughs.py"
FUNC_START = re.compile(r"^RECOMP_FUNC void (\w+)\(")
FUNC_END = ";}"

# What the end of a function does.
CLOSED = "closed"                # ends with a jump that never comes back, or padding
FALLS = "falls"                  # runs off its end, proven from its first instruction
FALLS_UNSEEN = "falls (unseen entry)"
BRANCH_AT_END = "branch at end"  # last instruction is a branch or jump

# What was done about it.
FIXED = "fixed"
ALREADY = "already fixed"
NO_NEXT = "not fixed: what follows is not a function"
STUBBED = "not fixed: stubbed in kigold.toml"
NO_BODY = "not fixed: no body in the C"


@dataclass
class Function:
    section: str
    name: str
    vram: int
    state: str
    next_name: str | None  # the function that starts right after this one
    result: str = ""


def kind(word: int, pc: int) -> tuple:
    """Classify one instruction: ("jump" | "cond" | "call" | "eret" | "plain", branch target or None).

    "jump" never comes back (j, jr, b). "call" comes back after its delay slot.
    """
    op, rs, rt, funct = word >> 26, (word >> 21) & 31, (word >> 16) & 31, word & 63
    target = (pc + 4 + (((word & 0xFFFF) ^ 0x8000) - 0x8000) * 4) & 0xFFFFFFFF
    if op == 2:
        return "jump", (pc & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
    if op == 3 or (op == 0 and funct == 9):                # jal, jalr
        return "call", None
    if op == 0 and funct == 8:                             # jr
        return "jump", None
    if op == 4:                                            # beq; "b" is beq with equal registers
        return ("jump" if rs == rt else "cond"), target
    if op in (5, 6, 7, 0x14, 0x15, 0x16, 0x17):            # bne blez bgtz and the "likely" forms
        return "cond", target
    if op == 1 and rt in (0, 1, 2, 3):                     # bltz bgez and the "likely" forms
        return ("jump" if rt == 1 and rs == 0 else "cond"), target
    if op == 1 and rt in (0x10, 0x11, 0x12, 0x13):         # bltzal bgezal: branch and link
        return "call", None
    if op == 0x11 and rs == 8:                             # bc1f bc1t
        return "cond", target
    if word == 0x42000018:
        return "eret", None
    return "plain", None


def end_state(words, vram: int) -> str:
    """Decide what happens at the end of one function from its instructions."""
    count = len(words)
    end = vram + 4 * count
    if kind(words[-1], end - 4)[0] not in ("plain", "eret"):
        return BRANCH_AT_END

    # Follow the code from the first instruction.
    seen, todo = set(), [0]
    while todo:
        i = todo.pop()
        if i == count:
            return FALLS
        if i in seen:
            continue
        seen.add(i)
        what, target = kind(words[i], vram + 4 * i)
        if what == "plain":
            todo.append(i + 1)
        elif what != "eret":
            if target is not None and vram <= target < end:
                todo.append((target - vram) // 4)
            if what in ("cond", "call"):
                todo.append(i + 2)  # carries on after the delay slot

    # Not reached from the start. Look at the code after the last jump that never comes back.
    tail_start = 0
    for i in range(count):
        what = kind(words[i], vram + 4 * i)[0]
        if what == "jump":
            tail_start = i + 2  # skip its delay slot
        elif what == "eret":
            tail_start = i + 1
    tail = words[tail_start:]
    return FALLS_UNSEEN if any(tail) else CLOSED  # all-zero words are padding


def find(symbols: dict, rom: bytes) -> list:
    """Return every function whose end is not closed."""
    found = []
    for section in symbols["section"]:
        starts = {f["vram"]: f["name"] for f in section["functions"]}
        for f in sorted(section["functions"], key=lambda f: f["vram"]):
            offset = section["rom"] + f["vram"] - section["vram"]
            words = struct.unpack(f">{f['size'] // 4}I", rom[offset:offset + f["size"]])
            state = end_state(words, f["vram"])
            if state != CLOSED:
                found.append(Function(section["name"], f["name"], f["vram"], state,
                                      starts.get(f["vram"] + f["size"])))
    return found


def fix(files: dict, found: list, stubs: set) -> dict:
    """Add the call and return to each function that needs it.

    files maps a file name to its C text. Returns the changed files only, and
    sets .result on every Function in found.
    """
    lines = {name: text.split("\n") for name, text in files.items()}
    where = {}  # function name -> (file name, line of its closing ";}")
    for name, file_lines in lines.items():
        current = None
        for number, line in enumerate(file_lines):
            match = FUNC_START.match(line)
            if match:
                current = match.group(1)
            elif line == FUNC_END and current:
                where[current] = (name, number)
                current = None

    inserts = {}  # file name -> list of (line number, new lines)
    for f in found:
        if f.state == BRANCH_AT_END:
            f.result = f.state
        elif f.name in stubs:
            f.result = STUBBED
        elif f.name not in where:
            f.result = NO_BODY
        elif f.next_name is None:
            f.result = NO_NEXT
        elif f.next_name not in where:
            f.result = NO_BODY
        else:
            name, end_line = where[f.name]
            if MARKER in lines[name][end_line - 3]:
                f.result = ALREADY
                continue
            f.result = FIXED
            inserts.setdefault(name, []).append((end_line, [
                f"    // {f.state} into {f.next_name}, {MARKER}",
                f"    {f.next_name}(rdram, ctx);",
                "    return;",
            ]))

    changed = {}
    for name, todo in inserts.items():
        for end_line, new_lines in sorted(todo, reverse=True):  # bottom up keeps line numbers valid
            lines[name][end_line:end_line] = new_lines
        changed[name] = "\n".join(lines[name])
    return changed


def report(found: list) -> str:
    out = []
    fixed = Counter((f.section, f.state) for f in found if f.result == FIXED)
    already = sum(1 for f in found if f.result == ALREADY)
    out.append(f"fall-throughs fixed: {sum(fixed.values())}, already fixed: {already}")
    for (section, state), count in sorted(fixed.items()):
        out.append(f"  {count:4d}  {section}: {state}")
    left = [f for f in found if f.result not in (FIXED, ALREADY)]
    if left:
        out.append(f"left alone: {len(left)}")
        for f in left:
            out.append(f"  {f.section}: {f.name} ({f.result})")
    return "\n".join(out)


def run(out_dir: Path = OUT_DIR) -> list:
    """Fix the generated C in out_dir in place. Returns the list of functions looked at."""
    symbols = tomllib.loads(SYMBOLS.read_text())
    stubs = set(tomllib.loads(RECOMP_CONFIG.read_text()).get("patches", {}).get("stubs", []))
    found = find(symbols, ROM.read_bytes())
    files = {path.name: path.read_text() for path in sorted(out_dir.glob("*.c"))}
    for name, text in fix(files, found, stubs).items():
        (out_dir / name).write_text(text, newline="\n")
    return found


def main() -> int:
    for needed in (SYMBOLS, ROM, RECOMP_CONFIG, OUT_DIR):
        if not needed.exists():
            print(f"FAIL: {needed} is missing. Run tools/regen.py.")
            return 1
    print(report(run()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
