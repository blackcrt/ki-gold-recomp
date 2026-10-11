#!/usr/bin/env python3
"""Known-answer test for tools/stream3_map.py (ground rule 4).

Assembles a tiny made-up program by hand (36 words of code and tables, 5 words
of data) and checks the tracer finds exactly the code, tables and functions
that were put in. Uses no real ROM data.

The program, at RAM 0x80100000 (ROM 0x2000):

  00 entry   jal f2 / lui+addiu builds 0x8010001C / lbu through it / jr ra
  1C         lookup table, 2 words that are not valid instructions
  24 f2      bne to 0x38 (the middle of f3), then falls through into f3
  30 f3      called by case_a; its last two words (0x38) are entered by f2's branch
  40         address table, 2 words: disp, and 0x80100034 (the middle of f3)
  48 disp    jr through a jump table in the data area: case_a, case_b
  5C case_a  jal f3 / jr ra
  6C case_b  jr ra
  78         valid code that nothing reaches
  84 fq      reached only through an address stored in the data area
  90 data    0x8010001C (points at the lookup table, so it is not code),
             the jump table (case_a, case_b, 0), and the address of fq

A second program checks that a function never starts on a delay slot just
because an address was built that happens to land there (two tracer bugs found
in Phase 2, task 4b):

  00 g0     j g2 / nop
  08 gback  addiu a1,a1,0x34   a1 was overwritten in g2, so this builds no address.
                               A tracer that pairs it with g2's lui gets 0x80100034.
  0C        lui+addiu builds 0x80100020, adds an index, loads through it: a table base.
            The table is 1-based, so the base is the word before it.
  1C        jr ra
  20        its delay slot (the table base address)
  24        the lookup table, 2 words that are not valid instructions
  2C g1     addiu / bne back to 2C / its delay slot at 34 / jr ra / nop
  40 g2     lui a1,0x8010 / addu a1,a0,a0 (overwrites a1) / jal g1 / nop / j gback / nop

Usage:
  disasm/.venv/bin/python tools/test_stream3_map.py
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stream3_map

ROM, VRAM, CODE_SIZE = 0x2000, 0x80100000, 0x90
AT, V0, A0, A1, T0, T1, RA = 1, 2, 4, 5, 8, 9, 31
NOP = 0


def jal(to): return 0x0C000000 | ((to & 0x0FFFFFFF) >> 2)
def j(to): return 0x08000000 | ((to & 0x0FFFFFFF) >> 2)
def jr(reg): return (reg << 21) | 8
def lui(rt, imm): return 0x3C000000 | (rt << 16) | imm
def addiu(rt, rs, imm): return 0x24000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)
def lbu(rt, off, rs): return 0x90000000 | (rs << 21) | (rt << 16) | off
def lw(rt, off, rs): return 0x8C000000 | (rs << 21) | (rt << 16) | off
def addu(rd, rs, rt): return (rs << 21) | (rt << 16) | (rd << 11) | 0x21
def bne(rs, rt, at, to): return 0x14000000 | (rs << 21) | (rt << 16) | (((to - at - 4) >> 2) & 0xFFFF)


def a(offset): return VRAM + offset


CODE = [
    jal(a(0x24)), NOP, lui(T0, 0x8010), addiu(T0, T0, 0x1C), lbu(T1, 0, T0), jr(RA), NOP,      # 00 entry
    0x01020304, 0x05060708,                                                                   # 1C lookup table
    bne(A0, 0, a(0x24), a(0x38)), NOP, addiu(V0, 0, 1),                                       # 24 f2
    addiu(V0, 0, 2), addiu(V0, V0, 1), jr(RA), NOP,                                           # 30 f3
    a(0x48), a(0x34),                                                                         # 40 address table
    lui(AT, 0x8010), addu(AT, AT, A0), lw(T1, 0x94, AT), jr(T1), NOP,                         # 48 disp
    jal(a(0x30)), NOP, jr(RA), NOP,                                                           # 5C case_a
    addiu(V0, 0, 5), jr(RA), NOP,                                                             # 6C case_b
    addiu(V0, 0, 3), jr(RA), NOP,                                                             # 78 unreached
    addiu(V0, 0, 6), jr(RA), NOP,                                                             # 84 fq
]
DATA = [a(0x1C), a(0x5C), a(0x6C), 0, a(0x84)]
# Code somewhere else that calls entry, builds fq's address, and calls outside the segment.
CALLER_VRAM = 0x80000400
CALLER = [jal(a(0x00)), NOP, lui(A0, 0x8010), addiu(A0, A0, 0x84), jal(0x80200000), NOP]

CODE2 = [
    j(a(0x40)), NOP,                                                                          # 00 g0
    addiu(A1, A1, 0x34),                                                                      # 08 gback
    lui(T0, 0x8010), addiu(T0, T0, 0x20), addu(T0, T0, A0), lw(T1, 0, T0), jr(RA),            # 0C
    addiu(V0, 0, 1),                                                                          # 20 delay slot
    0x01020304, 0x05060708,                                                                   # 24 lookup table
    addiu(V0, 0, 2), bne(A0, 0, a(0x30), a(0x2C)), addiu(V0, V0, 1), jr(RA), NOP,             # 2C g1
    lui(A1, 0x8010), addu(A1, A0, A0), jal(a(0x2C)), NOP, j(a(0x08)), NOP,                    # 40 g2
]


def blob(code, data) -> bytes:
    return struct.pack(">%dI" % (len(code) + len(data)), *code, *data)


def is_target(x) -> bool:
    return VRAM <= x < VRAM + CODE_SIZE and x % 4 == 0


def run(code=CODE, data=DATA):
    calls, consts = stream3_map.scan_code(CALLER, CALLER_VRAM, is_target)
    return stream3_map.trace_segment("test", ROM, blob(code, data), VRAM, CODE_SIZE, calls, consts)


def main() -> int:
    assert len(CODE) * 4 == CODE_SIZE
    calls, consts = stream3_map.scan_code(CALLER, CALLER_VRAM, is_target)
    m = run()
    tracer = stream3_map.Tracer(blob(CODE, DATA), VRAM, CODE_SIZE)
    # The same program, but the unreached code jumps out of the segment and the data points at it.
    leaving = CODE[:30] + [j(0x80200000), NOP, NOP] + CODE[33:]
    m_leaving = run(code=leaving, data=DATA + [a(0x78)])
    # The same program, but the lookup table is never loaded through, and it decodes as code.
    no_table = CODE[:7] + [addiu(V0, 0, 8), addiu(V0, 0, 9)] + CODE[9:]
    no_table[3], no_table[4] = NOP, NOP
    m_no_table = run(code=no_table, data=DATA[1:])
    m2 = stream3_map.trace_segment("test2", ROM, blob(CODE2, []), VRAM, len(CODE2) * 4, {a(0x00): [CALLER_VRAM]})
    ends2 = {start + size for start, size, _ in m2.functions}
    checks = [
        ("calls from other code are found, calls to elsewhere are not", dict(calls) == {a(0x00): [CALLER_VRAM]}),
        ("an address built with lui+addiu in other code is found", dict(consts) == {a(0x84): [CALLER_VRAM + 0xC]}),
        ("a word that is a code address is never an instruction",
         (tracer.kind(a(0x40)), tracer.kind(a(0x24)), tracer.kind(a(0x1C))) == ("bad", "branch", "bad")),
        ("a jump table in the data area is read up to its first non-code word",
         tracer.jump_table(a(0x54)) == [a(0x5C), a(0x6C)]),
        ("the data regions are the two tables", m.data == [(a(0x1C), a(0x24), "lookup table"),
                                                           (a(0x40), a(0x48), "pointer table")]),
        ("valid code nothing reaches is kept as code, apart from traced code",
         m.unreached == [(a(0x78), a(0x84))] and m.traced_bytes == 116),
        ("code, unreached code and data add up to the code area",
         m.traced_bytes + 12 + sum(b - s for s, b, _ in m.data) == CODE_SIZE),
        ("routines: entry, f2, f3, the code after the address table, fq",
         m.routines == [(a(0x00), a(0x1C), "call"), (a(0x24), a(0x30), "call"), (a(0x30), a(0x40), "call"),
                        (a(0x48), a(0x84), "orphan"), (a(0x84), a(0x90), "pointer")]),
        ("functions: the routines, with f3 split where f2 branches into it",
         m.functions == [(a(0x00), 0x1C, "call"), (a(0x24), 0xC, "call"), (a(0x30), 0x8, "call"),
                         (a(0x38), 0x8, "entry"), (a(0x48), 0x3C, "orphan"), (a(0x84), 0xC, "pointer")]),
        ("jump table targets inside the jumping function are not split off",
         all(f[0] not in (a(0x5C), a(0x6C)) for f in m.functions)),
        ("no function holds a data word",
         all(f[0] + f[1] <= s or f[0] >= b for f in m.functions for s, b, _ in m.data)),
        ("a stored address that points at a table is rejected, with the reason",
         m.rejected == {a(0x1C): "invalid instruction at 8010001C"}),
        ("a stored address into the middle of a function is reported", m.mid_targets == [a(0x34)]),
        ("the outside caller is recorded", m.callers == {a(0x00): [CALLER_VRAM]}),
        ("a weak seed whose code jumps out of the segment is rolled back",
         m_leaving.rejected.get(a(0x78)) == "jumps out of the segment" and m_leaving.traced_bytes == 116
         and m_leaving.functions == m.functions),
        ("a gap that decodes cleanly and is not used as a table counts as code, not data",
         m_no_table.data == [(a(0x40), a(0x48), "pointer table")] and (a(0x1C), a(0x24)) in m_no_table.unreached
         and m_no_table.functions[0] == (a(0x00), 0x24, "call")),
        ("the config lines list code and data pieces in order, by ROM offset",
         stream3_map.yaml_lines(m) == ["      - [0x2000, asm]",
                                       "      - [0x201C, data]   # 0x8010001C, lookup table, 0x8",
                                       "      - [0x2024, asm]",
                                       "      - [0x2040, data]   # 0x80100040, pointer table, 0x8",
                                       "      - [0x2048, asm]"]),
        ("the symbol lines are the routine starts with default names",
         stream3_map.symbol_lines(m)[1:3] == ["func_80100024_test = 0x80100024; // type:func segment:test",
                                              "func_80100030_test = 0x80100030; // type:func segment:test"]
         and len(stream3_map.symbol_lines(m)) == 5),
        ("a table base that lands on a delay slot does not start a function",
         a(0x20) not in [f[0] for f in m2.functions] and m2.data == [(a(0x24), a(0x2C), "mixed data")]),
        ("an addiu is not paired with a lui that comes later in memory",
         a(0x34) not in [f[0] for f in m2.functions]),
        ("second program: functions are g0, gback, g1, g2 and nothing else",
         m2.functions == [(a(0x00), 0x8, "call"), (a(0x08), 0x1C, "entry"),
                          (a(0x2C), 0x14, "call"), (a(0x40), 0x18, "entry")]),
        ("second program: no function ends between a branch or jump and its delay slot",
         a(0x20) not in ends2 and a(0x34) not in ends2),
    ]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
