#!/usr/bin/env python3
"""Known-answer test for tools/fix_fallthroughs.py (ground rule 4).

Assembles a made-up program by hand, with a made-up symbol table and made-up
generated C, and checks the tool finds and fixes exactly the functions that
were built to fall through. Uses no real ROM data.

Section "s" at RAM 0x80100000 (ROM 0x1000), in this order:

  f_plain     two plain instructions                  falls into f_ret
  f_ret       jr ra / nop                             closed
  f_cond      beq to elsewhere / nop                  falls into f_call (branch not taken)
  f_call      jal f_ret / nop                         falls into f_pad (after the call returns)
  f_pad       jr ra / nop / nop / nop                 closed, the nops are padding
  f_b         addiu / b f_ret / nop                   closed, "b" never comes back
  f_unseen    j f_ret / nop / addiu                   falls (unseen entry) into f_loop
  f_loop      bne to +0x10 / nop / jr ra / nop / addiu   falls into f_edge, through its own branch
  f_edge      addiu / bne                             branch at end, left alone
  f_slot      addiu / jr ra / nop                     closed
  f_stub      addiu                                   falls, but stubbed in the config
  f_tonobody  addiu                                   falls into f_nobody, which has no C body
  f_nobody    addiu                                   falls, and has no C body itself
  f_gap       addiu                                   falls into a data word, not a function
  (one data word)
  f_last      jr ra / nop                             closed

Section "t" shares the same RAM address (an overlay): t_a falls into t_b, and
must not be chained to a function of section "s".

Usage:
  python3 tools/test_fix_fallthroughs.py
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fix_fallthroughs as ff

ROM_S, ROM_T, VRAM = 0x1000, 0x2000, 0x80100000
V0, A0, RA = 2, 4, 31
NOP = 0


def jal(to): return 0x0C000000 | ((to & 0x0FFFFFFF) >> 2)
def j(to): return 0x08000000 | ((to & 0x0FFFFFFF) >> 2)
def jr(reg): return (reg << 21) | 8
def addiu(rt, rs, imm): return 0x24000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)
def branch(op, rs, rt, at, to): return (op << 26) | (rs << 21) | (rt << 16) | (((to - at - 4) >> 2) & 0xFFFF)
def beq(rs, rt, at, to): return branch(4, rs, rt, at, to)
def bne(rs, rt, at, to): return branch(5, rs, rt, at, to)


def build_s():
    """Lay out section s. Returns (words, functions) where functions is name -> (vram, size)."""
    f_ret = VRAM + 0x08
    layout = [
        ("f_plain", lambda at: [addiu(V0, 0, 1), addiu(V0, V0, 1)]),
        ("f_ret", lambda at: [jr(RA), NOP]),
        ("f_cond", lambda at: [beq(A0, 0, at, f_ret), NOP]),
        ("f_call", lambda at: [jal(f_ret), NOP]),
        ("f_pad", lambda at: [jr(RA), NOP, NOP, NOP]),
        ("f_b", lambda at: [addiu(V0, 0, 3), beq(0, 0, at + 4, f_ret), NOP]),
        ("f_unseen", lambda at: [j(f_ret), NOP, addiu(V0, 0, 7)]),
        ("f_loop", lambda at: [bne(A0, 0, at, at + 0x10), NOP, jr(RA), NOP, addiu(V0, 0, 8)]),
        ("f_edge", lambda at: [addiu(V0, 0, 9), bne(A0, 0, at + 4, f_ret)]),
        ("f_slot", lambda at: [addiu(V0, 0, 10), jr(RA), NOP]),
        ("f_stub", lambda at: [addiu(V0, 0, 11)]),
        ("f_tonobody", lambda at: [addiu(V0, 0, 12)]),
        ("f_nobody", lambda at: [addiu(V0, 0, 13)]),
        ("f_gap", lambda at: [addiu(V0, 0, 14)]),
        (None, lambda at: [0x80100000]),  # data, not in the function list
        ("f_last", lambda at: [jr(RA), NOP]),
    ]
    words, functions = [], {}
    for name, make in layout:
        at = VRAM + 4 * len(words)
        new = make(at)
        if name:
            functions[name] = (at, 4 * len(new))
        words += new
    return words, functions


def c_function(name: str) -> str:
    return (f"RECOMP_FUNC void {name}(uint8_t* rdram, recomp_context* ctx) {{\n"
            f"    uint64_t hi = 0, lo = 0, result = 0;\n"
            f"    // body of {name}\n"
            f";}}\n")


def main() -> int:
    words_s, funcs_s = build_s()
    words_t = [addiu(V0, 0, 1), jr(RA), NOP]
    funcs_t = {"t_a": (VRAM, 4), "t_b": (VRAM + 4, 8)}
    rom = bytearray(0x3000)
    struct.pack_into(f">{len(words_s)}I", rom, ROM_S, *words_s)
    struct.pack_into(f">{len(words_t)}I", rom, ROM_T, *words_t)
    symbols = {"section": [
        {"name": name, "rom": rom_at, "vram": VRAM, "size": 4 * len(words),
         "functions": [{"name": n, "vram": v, "size": s} for n, (v, s) in funcs.items()]}
        for name, rom_at, words, funcs in (("s", ROM_S, words_s, funcs_s), ("t", ROM_T, words_t, funcs_t))
    ]}
    with_body = [n for n in list(funcs_s) + list(funcs_t) if n != "f_nobody"]
    files = {
        "funcs_0.c": '#include "recomp.h"\n\n' + "\n".join(c_function(n) for n in with_body[:8]),
        "funcs_1.c": '#include "recomp.h"\n\n' + "\n".join(c_function(n) for n in with_body[8:]),
    }

    found = ff.find(symbols, bytes(rom))
    changed = ff.fix(files, found, {"f_stub"})
    got = {f.name: (f.state, f.next_name, f.result) for f in found}
    want = {
        "f_plain": (ff.FALLS, "f_ret", ff.FIXED),
        "f_cond": (ff.FALLS, "f_call", ff.FIXED),
        "f_call": (ff.FALLS, "f_pad", ff.FIXED),
        "f_unseen": (ff.FALLS_UNSEEN, "f_loop", ff.FIXED),
        "f_loop": (ff.FALLS, "f_edge", ff.FIXED),
        "f_edge": (ff.BRANCH_AT_END, "f_slot", ff.BRANCH_AT_END),
        "f_stub": (ff.FALLS, "f_tonobody", ff.STUBBED),
        "f_tonobody": (ff.FALLS, "f_nobody", ff.NO_BODY),
        "f_nobody": (ff.FALLS, "f_gap", ff.NO_BODY),
        "f_gap": (ff.FALLS, None, ff.NO_NEXT),
        "t_a": (ff.FALLS, "t_b", ff.FIXED),
    }
    fixed = {**files, **changed}
    all_text = "".join(fixed.values())
    want_plain = ("RECOMP_FUNC void f_plain(uint8_t* rdram, recomp_context* ctx) {\n"
                  "    uint64_t hi = 0, lo = 0, result = 0;\n"
                  "    // body of f_plain\n"
                  "    // falls into f_ret, added by tools/fix_fallthroughs.py\n"
                  "    f_ret(rdram, ctx);\n"
                  "    return;\n"
                  ";}\n")

    # Second run on the fixed text.
    found2 = ff.find(symbols, bytes(rom))
    changed2 = ff.fix(fixed, found2, {"f_stub"})

    checks = [
        ("jr is a jump that never comes back", ff.kind(jr(RA), VRAM) == ("jump", None)),
        ("b (beq with equal registers) never comes back", ff.kind(beq(0, 0, VRAM, VRAM + 8), VRAM)[0] == "jump"),
        ("beq with different registers is conditional, with its target",
         ff.kind(beq(A0, 0, VRAM + 8, VRAM), VRAM + 8) == ("cond", VRAM)),
        ("jal comes back", ff.kind(jal(VRAM), VRAM)[0] == "call"),
        ("addiu is plain", ff.kind(addiu(V0, 0, 1), VRAM) == ("plain", None)),
        ("exactly the 11 open functions are found, closed ones are not", set(got) == set(want)),
        *[(f"{name}: {state}, next {nxt}, {result}", got.get(name) == (state, nxt, result))
          for name, (state, nxt, result) in want.items()],
        ("f_plain's fixed C is exactly the expected text", want_plain in fixed["funcs_0.c"]),
        ("6 functions were fixed", all_text.count(ff.MARKER) == 6),
        ("the unseen-entry fix says so in its comment",
         "    // falls (unseen entry) into f_loop, added by" in all_text),
        ("t_a is chained to t_b in its own section", "    t_b(rdram, ctx);\n    return;\n;}" in all_text),
        ("closed functions are untouched", c_function("f_ret") in all_text and c_function("f_pad") in all_text
         and c_function("f_b") in all_text and c_function("f_last") in all_text),
        ("left-alone functions are untouched", c_function("f_edge") in all_text and c_function("f_stub") in all_text
         and c_function("f_tonobody") in all_text and c_function("f_gap") in all_text),
        ("nothing was removed: only whole lines were added",
         [l for l in all_text.split("\n") if ff.MARKER not in l and "(rdram, ctx);" not in l and l != "    return;"]
         == "".join(files.values()).split("\n")),
        ("second run changes no file", changed2 == {}),
        ("second run reports the 6 as already fixed",
         sorted(f.name for f in found2 if f.result == ff.ALREADY)
         == sorted(n for n, w in want.items() if w[2] == ff.FIXED)),
        ("report counts 6 fixed and lists 5 left alone",
         "fall-throughs fixed: 6, already fixed: 0" in ff.report(found) and "left alone: 5" in ff.report(found)),
    ]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
