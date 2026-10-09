#!/usr/bin/env python3
"""Known-answer test for tools/fingerprint_libultra.py (ground rule 4).

Builds small synthetic ELF objects in memory as the "reference", links them at
made-up addresses as the "game", and checks that the tool confirms exactly the
functions it should and refuses every trap. Uses no ROM and no libultra code.

Usage:
  python3 tools/test_fingerprint_libultra.py
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fingerprint_libultra as fp
from fingerprint_libultra import FingerprintError, GameFunc

JAL, J, JR_RA = 0x0C000000, 0x08000000, 0x03E00008
LUI_AT, LW_V0_AT = 0x3C010000, 0x8C220000


def body(seed: int, n: int) -> list:
    """A fake n-instruction function, different for every seed."""
    return [0x27BDFFE8] + [0x34080000 | seed << 8 | k for k in range(n - 3)] + [JR_RA, 0x27BD0018]


def with_words(words: list, changes: dict) -> list:
    out = list(words)
    for index, word in changes.items():
        out[index] = word
    return out


# name -> (words, relocations). A relocation is (word index, kind, target).
# Kinds: "call" a named function, "static" a file-local function, "hi"/"lo" data.
FUNCS = {
    "alpha": (with_words(body(1, 16), {3: JAL, 5: JAL, 7: LUI_AT, 8: LW_V0_AT, 10: JAL}),
              [(3, "call", "tiny"), (5, "static", "helper"), (7, "hi", "gData"),
               (8, "lo", "gData"), (10, "call", "twin1")]),
    "helper": (body(2, 10), []),
    "tiny": (body(3, 4), []),
    "twin1": (body(4, 12), []),
    "twin2": (body(4, 12), []),          # same code as twin1, different name
    "pair1": (body(5, 12), []),
    "pair2": (body(5, 12), []),          # same code as pair1, different name
    "lonely_tiny": (body(6, 5), []),
    "dup": (body(7, 12), []),
    "changed": (body(8, 12), []),
    "jumper": (with_words(body(9, 12), {2: JAL}), [(2, "call", "tiny")]),
    "liar": (with_words(body(10, 12), {2: JAL}), [(2, "call", "beta")]),
    "beta": (body(11, 12), []),
    "gamma": (body(12, 12), []),
    "hermit": (body(13, 12), []),
    "shifty": (with_words(body(14, 12), {2: JAL}), [(2, "static", "helper2")]),
    "helper2": (body(15, 6), []),
    "padded": (body(16, 12), []),
    # Data address traps. owner is big and unique, so it fixes where gCur and
    # gNext live (it reads gNext + 4, to exercise offsets).
    "owner": (with_words(body(20, 16), {3: LUI_AT, 4: LW_V0_AT, 6: LUI_AT, 7: LW_V0_AT | 4}),
              [(3, "hi", "gCur"), (4, "lo", "gCur"), (6, "hi", "gNext"), (7, "lo", "gNext")]),
    "getcur": (with_words(body(21, 12), {2: LUI_AT, 3: LW_V0_AT}), [(2, "hi", "gCur"), (3, "lo", "gCur")]),
    "getnext": (with_words(body(21, 12), {2: LUI_AT, 3: LW_V0_AT}),   # same code as getcur
                [(2, "hi", "gNext"), (3, "lo", "gNext")]),
    "tinycur": (with_words(body(22, 6), {1: LUI_AT, 2: LW_V0_AT}), [(1, "hi", "gCur"), (2, "lo", "gCur")]),
    "wrongdata": (with_words(body(23, 6), {1: LUI_AT, 2: LW_V0_AT}), [(1, "hi", "gNext"), (2, "lo", "gNext")]),
    "odd1": (with_words(body(24, 12), {2: LUI_AT, 3: LW_V0_AT}), [(2, "hi", "gFoo"), (3, "lo", "gFoo")]),
    "odd2": (with_words(body(24, 12), {2: LUI_AT, 3: LW_V0_AT}),      # same code as odd1
             [(2, "hi", "gBar"), (3, "lo", "gBar")]),
    "dupdata": (with_words(body(25, 6), {1: LUI_AT, 2: LW_V0_AT}), [(1, "hi", "gCur"), (2, "lo", "gCur")]),
    # Callee traps: same code, told apart only by which confirmed function is called.
    "longread": (with_words(body(30, 12), {2: JAL}), [(2, "call", "beta")]),
    "longwrite": (with_words(body(30, 12), {2: JAL}), [(2, "call", "gamma")]),
    # Copy traps: one copy in each segment.
    "shared": (body(31, 12), []),
    "shared2": (body(32, 12), []),
}
STATIC = {"helper", "helper2"}
OBJECTS = [["alpha", "helper"], ["tiny"], ["twin1"], ["twin2"], ["pair1"], ["pair2"],
           ["lonely_tiny"], ["dup"], ["changed"], ["jumper"], ["liar"], ["beta"], ["gamma"],
           ["hermit"], ["shifty", "helper2"], ["padded"], ["owner"], ["getcur"], ["getnext"],
           ["tinycur"], ["wrongdata"], ["odd1"], ["odd2"], ["dupdata"],
           ["longread"], ["longwrite"], ["shared"], ["shared2"]]
RELOC_TYPE = {"call": 4, "static": 4, "hi": 5, "lo": 6}


def make_object(names: list, sizes: bool = True) -> bytes:
    """A minimal big-endian MIPS ELF object holding the named functions."""
    offsets, text = {}, []
    for name in names:
        offsets[name] = len(text) * 4
        text += FUNCS[name][0]
    symbols = [("", 0, 0, 0, 0), (".text", 0, len(text) * 4, 3, 1)]  # name, value, size, info, shndx
    index = {}
    for name in names:
        if name not in STATIC:
            index[name] = len(symbols)
            symbols.append((name, offsets[name], len(FUNCS[name][0]) * 4 if sizes else 0, 0x12, 1))
    rels = []
    for name in names:
        for word, kind, target in FUNCS[name][1]:
            at = offsets[name] // 4 + word
            if kind == "static":
                text[at] |= offsets[target] >> 2   # target offset lives in the instruction
                sym = 1
            else:
                if target not in index:
                    index[target] = len(symbols)
                    symbols.append((target, 0, 0, 0x12 if kind == "call" else 0x11, 0))
                sym = index[target]
            rels.append((at * 4, sym << 8 | RELOC_TYPE[kind]))

    strtab = b"\0"
    symtab = b""
    for name, value, size, info, shndx in symbols:
        symtab += struct.pack(">IIIBBH", len(strtab) if name else 0, value, size, info, 0, shndx)
        if name:
            strtab += name.encode() + b"\0"
    sections = [("", 0, b"", 0, 0), (".text", 1, struct.pack(f">{len(text)}I", *text), 0, 0),
                (".rel.text", 9, b"".join(struct.pack(">II", *r) for r in rels), 3, 1),
                (".symtab", 2, symtab, 4, 0), (".strtab", 3, strtab, 0, 0)]
    shstrtab = b"\0" + b"".join(n.encode() + b"\0" for n, *_ in sections[1:]) + b".shstrtab\0"
    sections.append((".shstrtab", 3, shstrtab, 0, 0))
    blob = bytearray(0x34)
    headers = b""
    for name, stype, data, link, info in sections:
        name_off = shstrtab.index(name.encode() + b"\0") if name else 0
        headers += struct.pack(">10I", name_off, stype, 0, 0, len(blob), len(data), link, info, 4, 0)
        blob += data + bytes(-len(data) % 4)
    blob[0:6] = b"\x7fELF\x01\x02"
    struct.pack_into(">I", blob, 0x20, len(blob))
    struct.pack_into(">HHH", blob, 0x2E, 40, len(sections), len(sections) - 1)
    return bytes(blob + headers)


# The fake game: (segment, base address, [(game label, function, trailing nops)]).
# A label ending in ' is a function altered on purpose; decoys match nothing.
for n in range(1, 10):
    FUNCS[f"decoy{n}"] = (body(0x40 + n, 12 if n > 1 else 4), [])
LAYOUT = [
    ("main", 0x80001000, [("alpha", 0), ("helper", 0), ("tiny", 0), ("twin1", 0), ("lonely_tiny", 0),
                          ("dup", 0), ("dup", 0), ("changed", 0), ("jumper", 0), ("liar", 0),
                          ("beta", 0), ("gamma", 0), ("shifty", 0), ("decoy1", 0), ("helper2", 0),
                          ("padded", 3), ("pair1", 0), ("owner", 0), ("getcur", 0), ("getnext", 0),
                          ("tinycur", 0), ("wrongdata", 0), ("odd1", 0), ("dupdata", 0), ("dupdata", 0),
                          ("longread", 0), ("longwrite", 0), ("shared", 0), ("shared2", 0)]),
    ("far", 0x80100000, [("decoy2", 0), ("decoy3", 0), ("decoy4", 0), ("decoy5", 0), ("hermit", 0),
                         ("decoy6", 0), ("decoy7", 0), ("decoy8", 0), ("decoy9", 0),
                         ("shared", 0), ("shared2", 0)]),
]


def link() -> tuple[list, dict]:
    """Place every function, then fill in the address fields like a linker."""
    placed, where = [], {}
    for segment, base, entries in LAYOUT:
        addr = base
        for name, pad in entries:
            placed.append((segment, addr, name, pad))
            where.setdefault(name, addr)
            addr += (len(FUNCS[name][0]) + pad) * 4
    where["gData"] = 0x80234568
    where.update(gCur=0x80240010, gNext=0x80240020, gElsewhere=0x80250000, gFoo=0x80260000, gBar=0x80260008)
    game = []
    for segment, addr, name, pad in placed:
        words, relocs = FUNCS[name]
        words = list(words)
        for index, kind, target in relocs:
            if name == "liar":
                target = "gamma"                       # trap: calls the wrong function
            if name == "wrongdata":
                target = "gElsewhere"                  # trap: reads a different variable
            dest = where[target]
            if kind in ("call", "static"):
                words[index] |= (dest >> 2) & 0x03FFFFFF
            elif kind == "hi":
                words[index] |= dest >> 16
            else:
                words[index] = words[index] & 0xFFFF0000 | (words[index] + dest) & 0xFFFF
        if name == "changed":
            words[4] ^= 0x1                            # trap: one instruction differs
        if name == "jumper":
            words[2] = J | words[2] & 0x03FFFFFF       # trap: j where the reference has jal
        game.append(GameFunc(f"func_{addr:08X}", addr, words + [0] * pad, segment))
    return game, where


SPLAT_ASM = """\
nonmatching func_80001000, 0x10

glabel func_80001000
    /* 1000 80001000 27BDFFE8 */  addiu      $sp, $sp, -0x18
alabel func_80001004
    /* 1004 80001004 03E00008 */  jr         $ra
    /* 1008 80001008 27BD0018 */   addiu     $sp, $sp, 0x18
    /* 100C 8000100C 00000000 */  nop
endlabel func_80001000

nonmatching func_80001010

dlabel func_80001010
    /* 1010 80001010 3C01801E */ .word 0x3C01801E
enddlabel func_80001010
"""

REF_ASM = """\
.section .text, "ax"
glabel asmfunc
/* 000100 70000100 3C088002 */  lui   $t0, %hi(gCur + 4) # $t0, 0x8002
/* 000104 70000104 8D081234 */  lw    $t0, %lo(gCur + 4)($t0)
/* 000108 70000108 0C001234 */  jal   outside
/* 00010C 7000010C 00000000 */   nop
/* 000110 70000110 0C000046 */  jal   inner
/* 000114 70000114 3C09A430 */   lui   $t1, %hi(0xA430000C) # $t1, 0xa430
glabel inner
/* 000118 70000118 03E00008 */  jr    $ra
/* 00011C 7000011C 00000000 */   nop

.section .rodata
/* 000200 70000200 DEADBEEF */ .word 0xDEADBEEF
"""

LISTS = """\
const std::unordered_set<std::string> N64Recomp::reimplemented_funcs {
    // a comment with a "quoted" word
    "alpha",
    "tiny",
    "missing",
};

const std::unordered_set<std::string> N64Recomp::ignored_funcs {
    "beta", "hermit", "lonely_tiny",
};
"""


def listing(name: str, words: list) -> str:
    """An assembly listing holding one function with these exact bytes."""
    rows = [f"/* {k * 4:06X} {0x70000000 + k * 4:08X} {w:08X} */  nop" for k, w in enumerate(words)]
    return "\n".join([".section .text", f"glabel {name}"] + rows) + "\n"


def fails(data: bytes) -> bool:
    try:
        fp.read_object(data, "synth", "bad.o")
    except FingerprintError:
        return True
    return False


def main() -> int:
    refs = []
    for i, names in enumerate(OBJECTS):
        refs += fp.read_object(make_object(names), "synth", f"obj{i}.o")
    by_name = {r.name: r for r in refs}
    alpha = by_name["alpha"]
    game, where = link()
    matches = fp.match_all(game, refs)
    at = {m.game.vram: m for m in matches}
    confirmed = {m.names[0]: m for m in matches if m.confirmed}

    def likely(name: str, reason: str, index: int = 0) -> bool:
        addrs = [g.vram for (seg, _, entries) in LAYOUT for g in game
                 if g.segment == seg and g.vram in at]
        hits = [at[a] for a in sorted(set(addrs)) if name in at[a].names and not at[a].confirmed]
        return len(hits) > index and reason in hits[index].evidence

    parsed = fp.parse_splat_asm(SPLAT_ASM, "seg")
    lists = fp.parse_runtime_lists(LISTS)
    rows = {row[0]: row[1:] for row in fp.coverage(matches, refs, lists)}
    lines = fp.symbol_lines(matches)
    no_sizes = fp.read_object(make_object(["alpha", "helper"], sizes=False), "synth", "x.o")
    game_alpha = next(g for g in game if g.vram == where["alpha"])
    asm_refs = fp.read_asm_reference(REF_ASM, "synth", "x.s")
    asm_short = asm_refs[0]
    # A listing that gives gamma's code a wrong label, and one that is the only
    # reference for a decoy.
    listed = (fp.read_asm_reference(listing("mislabelled", FUNCS["gamma"][0]), "synth", "a.s")
              + fp.read_asm_reference(listing("listed_only", FUNCS["decoy3"][0]), "synth", "b.s"))
    with_listing = {m.game.vram: m for m in fp.match_all(game, refs + listed)}
    far_copy = next(g.vram for g in game if g.segment == "far" and g.words == FUNCS["shared"][0])
    suffixed = {m.game.vram: m for m in fp.match_all(game, refs, copy_suffix={"far": "_far"})}

    checks = [
        ("object reader lists global functions only", "helper" not in by_name and "helper2" not in by_name
         and len(refs) == len(FUNCS) - 9 - 2),
        ("object reader gets the size and instructions", alpha.words[0] == 0x27BDFFE8 and len(alpha.words) == 16),
        ("object reader blanks call targets and address halves",
         [alpha.masks[i] for i in (3, 5, 7, 8, 10)] == [0x03FFFFFF, 0x03FFFFFF, 0xFFFF, 0xFFFF, 0x03FFFFFF]
         and sum(m != 0 for m in alpha.masks) == 5),
        ("object reader records named and file-local calls",
         alpha.calls == {3: ("sym", "tiny"), 5: ("static", 0x40), 10: ("sym", "twin1")}),
        ("a symbol without a size runs to the end of the code",
         [(f.name, len(f.words)) for f in no_sizes] == [("alpha", 26)]),
        ("a file that is not an ELF object is rejected", fails(b"not an object file at all" * 4)),
        ("splat parser reads glabel functions and skips raw-word blocks",
         [(f.name, f.vram, f.words, f.size) for f in parsed]
         == [("func_80001000", 0x80001000, [0x27BDFFE8, JR_RA, 0x27BD0018], 16)]),
        ("the linked game copy really differs from the reference", game_alpha.words != alpha.words),
        ("big unique function with agreeing calls is confirmed",
         "alpha" in confirmed and confirmed["alpha"].game.vram == where["alpha"]
         and "3 calls agree" in confirmed["alpha"].evidence),
        ("tiny function is confirmed only through its confirmed caller",
         "tiny" in confirmed and "called as tiny by alpha" in confirmed["tiny"].evidence),
        ("ambiguous function is settled by its confirmed caller",
         "twin1" in confirmed and "twin2" not in confirmed and confirmed["twin1"].game.vram == where["twin1"]),
        ("ambiguous function nobody calls stays unnamed", likely("pair1", "several names")
         and likely("pair2", "several names")),
        ("tiny function nobody calls stays unnamed", likely("lonely_tiny", "only 5 instructions")),
        ("a name matching two game functions stays unnamed",
         likely("dup", "2 game functions", 0) and likely("dup", "2 game functions", 1)),
        ("one changed instruction means no match", not any("changed" in m.names for m in matches)),
        ("a different opcode at a call site means no match", not any("jumper" in m.names for m in matches)),
        ("a call to the wrong function blocks the name", likely("liar", "calls beta in the reference")),
        ("the functions around that trap are still confirmed", "beta" in confirmed and "gamma" in confirmed),
        ("a local call at the wrong distance blocks the name", likely("shifty", "different distance")),
        ("an isolated match stays unnamed", likely("hermit", "isolated")),
        ("trailing padding does not break a match", "padded" in confirmed),
        ("object reader records address pairs with their offsets",
         by_name["owner"].data == [(3, 4, ("sym", "gCur"), 0), (6, 7, ("sym", "gNext"), 4)]),
        ("identical code is settled by data addresses, both ways",
         "getcur" in confirmed and "getnext" in confirmed
         and confirmed["getcur"].game.vram == where["getcur"]
         and confirmed["getnext"].game.vram == where["getnext"]
         and "data rules out getnext" in confirmed["getcur"].evidence),
        ("a tiny function is confirmed when its data address agrees",
         "tinycur" in confirmed and "gCur at 0x80240010" in confirmed["tinycur"].evidence),
        ("a tiny function reading the wrong address stays unnamed",
         likely("wrongdata", "only 6 instructions") and likely("wrongdata", "different address")),
        ("identical code reading variables nobody confirmed stays unnamed",
         likely("odd1", "several names") and likely("odd2", "several names")),
        ("two game functions that both fit the data stay unnamed",
         likely("dupdata", "2 game functions", 0) and likely("dupdata", "2 game functions", 1)),
        ("confirmed functions agree on every data address", fp.data_conflicts(matches) == []),
        ("assembly listing: every glabel is offered with every possible end",
         [(f.name, len(f.words)) for f in asm_refs] == [("asmfunc", 6), ("asmfunc", 7), ("inner", 1)]),
        ("assembly listing: address halves and jumps are blanked, data sections skipped",
         asm_short.masks == [0xFFFF, 0xFFFF, 0x03FFFFFF, 0, 0x03FFFFFF, 0xFFFF]
         and asm_short.words[0] == 0x3C088002),
        ("assembly listing: named call, in-file call by distance, address pair with offset",
         asm_short.calls == {2: ("sym", "outside"), 4: ("static", 0x18)}
         and asm_short.data == [(0, 1, ("sym", "gCur"), 4)]),
        ("a compiled object's name wins over a listing's label",
         with_listing[where["gamma"]].confirmed and with_listing[where["gamma"]].names == ["gamma"]),
        ("a match only a listing supports stays unnamed",
         not with_listing[where["decoy3"]].confirmed
         and with_listing[where["decoy3"]].names == ["listed_only"]
         and "assembly listing" in with_listing[where["decoy3"]].evidence),
        ("identical code is settled by the confirmed function it calls",
         "longread" in confirmed and "longwrite" in confirmed
         and confirmed["longread"].game.vram == where["longread"]
         and confirmed["longwrite"].game.vram == where["longwrite"]
         and "calls confirmed beta" in confirmed["longread"].evidence
         and "that call rules out longwrite" in confirmed["longread"].evidence),
        ("one copy per segment stays unnamed when no suffix is set",
         likely("shared", "confirmed at 2 addresses", 0) and likely("shared", "confirmed at 2 addresses", 1)),
        ("with a suffix set, the plain copy keeps the name and the other gets the suffix",
         suffixed[where["shared"]].confirmed and suffixed[where["shared"]].names == ["shared"]
         and suffixed[far_copy].confirmed and suffixed[far_copy].names == ["shared_far"]
         and "own copy" in suffixed[far_copy].evidence),
        ("two matches in one segment are still refused when a suffix is set",
         not any(m.confirmed for m in suffixed.values() if "dup" in m.names)),
        ("exactly the expected names are confirmed",
         sorted(confirmed) == ["alpha", "beta", "gamma", "getcur", "getnext", "longread",
                               "longwrite", "owner", "padded", "tiny", "tinycur", "twin1"]),
        ("functions without a reference get no entry",
         len(matches) == 27 and where["helper"] not in at and where["decoy2"] not in at),
        ("runtime lists are parsed, comments ignored",
         lists == {"reimplemented_funcs": {"alpha", "tiny", "missing"},
                   "ignored_funcs": {"beta", "hermit", "lonely_tiny"}}),
        ("coverage counts confirmed, likely, and available names",
         rows == {"reimplemented_funcs": (3, 2, 2, 0), "ignored_funcs": (3, 3, 1, 2)}),
        ("symbol lines hold confirmed names with evidence, nothing else",
         f"alpha = 0x{where['alpha']:08X}; // type:func" in lines and lines.count("// evidence: exact match") == 12
         and "hermit" not in lines and "liar" not in lines and "dup" not in lines),
        ("a higher size floor demotes mid-sized functions",
         "padded" not in {m.names[0] for m in fp.match_all(game, refs, min_instr=13) if m.confirmed}),
    ]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
