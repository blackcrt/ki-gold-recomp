#!/usr/bin/env python3
"""Map stream3's code by tracing it (recursive descent), not by guessing.

stream3 is hand-written assembly with tables between its routines, so splat's
function guesses are wrong for it. This tool follows the code from its known
entry points and reports three things:
  - data regions inside the code area (tables), for disasm/kigold.yaml
  - routine starts, for disasm/symbol_addrs.txt
  - the function list N64Recomp needs, used by tools/gen_symbols.py

Method:
  - Start at the segment start and at every address boot or stream1 calls.
  - Follow every branch, jump, call and resolvable jump table.
  - Then try weaker seeds: code addresses stored in data, stored between
    routines, or built with lui+addiu. A weak seed is kept only if everything
    it leads to decodes cleanly; otherwise it is rolled back as a data pointer.
  - A word that is itself an address in the code area is never an instruction.
  - Unreached gaps that decode cleanly are kept as code nothing reaches. The
    other gaps are the data regions.
  - Function split: a function is one unbroken run of code, and any address
    entered from outside its function is a function start.

It reads the decompressed ROM in build/ and the layout below, nothing else. It
does not read splat's output. Its output is addresses, sizes and classes only.

Run from the repo root with the splat environment:
  disasm/.venv/bin/python tools/stream3_map.py             summary
  disasm/.venv/bin/python tools/stream3_map.py --yaml      subsegment lines for kigold.yaml
  disasm/.venv/bin/python tools/stream3_map.py --symbols   routine starts for symbol_addrs.txt
  disasm/.venv/bin/python tools/stream3_map.py --funcs     the function list
"""

import argparse
import bisect
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import rabbitizer

REPO = Path(__file__).resolve().parent.parent
ROM = REPO / "build" / "kigold.decompressed.z64"

# Layout, the same numbers as disasm/kigold.yaml. gen_symbols.py checks that
# stream3's still agree with the config.
# rom, vram, code size, code + data size
STREAM3 = (0xD232E0, 0x801AD900, 0x16760, 0x259C0)
# Code that can call stream3: rom, vram, size. stream2 shares stream3's RAM, so it cannot.
CALLERS = {
    "boot": (0x1000, 0x80000400, 0x6160),
    "stream1": (0xC00000, 0x8000F960, 0x32C90),
}
# Data outside stream3 that could hold stream3 addresses: rom, size
OTHER_DATA = {
    "boot_data": (0x7160, 0x7EC0 - 0x7160),
    "stream1_data": (0xC34F90, 0x4D50),
}

ID = rabbitizer.InstrId
ENDS_FLOW = ("jr", "j", "ubranch", "eret")
LOADS = (0x20, 0x21, 0x23, 0x24, 0x25)      # lb lh lw lbu lhu
STORES = (0x28, 0x29, 0x2B)                 # sb sh sw
LUI, ADDIU, ORI, LW = 0x0F, 0x09, 0x0D, 0x23


def be_words(data: bytes) -> tuple:
    return struct.unpack(">%dI" % (len(data) // 4), data[:len(data) // 4 * 4])


def signed16(imm: int) -> int:
    return imm - 0x10000 if imm & 0x8000 else imm


def scan_code(words, vram: int, is_target) -> tuple:
    """Addresses another piece of code calls (jal/j) or builds (lui+addiu/ori).

    Returns two dicts, target -> list of the addresses that refer to it.
    """
    calls, consts, hi = defaultdict(list), defaultdict(list), {}
    for n, w in enumerate(words):
        a = vram + n * 4
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op in (2, 3):
            t = (a & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
            if is_target(t):
                calls[t].append(a)
        if op == LUI:
            hi[rt] = (imm, a)
        elif op in (ADDIU, ORI) and rs in hi and a - hi[rs][1] <= 0x40:
            t = ((hi[rs][0] << 16) + (signed16(imm) if op == ADDIU else imm)) & 0xFFFFFFFF
            if is_target(t):
                consts[t].append(a)
    return calls, consts


def scan_pointers(words, is_target) -> set:
    return {w for w in words if is_target(w)}


class Tracer:
    """Follows code inside one segment. blob is the segment's code then its data."""

    def __init__(self, blob: bytes, vram: int, code_size: int):
        self.blob, self.vram = blob, vram
        self.end = vram + code_size
        self.words = be_words(blob[:code_size])
        self.reached = {}                   # address -> tier that first reached it
        self.visited = set()                # followed as an instruction, not only seen as a delay slot
        self.edges = []                     # (from, to, kind): branch, j, jal, jtbl
        self.call_targets = set()
        self.table_jumps = {}               # address of a jr through a table -> its targets
        self.consts = defaultdict(list)     # lui+addiu value in the code area -> where it is built
        self.bad = []                       # (seed, address, reason)
        self.delay_branches = []
        self.rejected = {}                  # weak seed -> why it is not code
        self.tiers = []                     # (tier, label, seeds, new bytes, rejected)
        self._hi = {}
        self._decoded = {}

    def in_code(self, a: int) -> bool:
        return self.vram <= a < self.end and a % 4 == 0

    def word(self, a: int) -> int:
        return self.words[(a - self.vram) // 4]

    def decode(self, a: int) -> tuple:
        """(kind, target) of the instruction at a, for control flow."""
        d = self._decoded.get(a)
        if d is None:
            d = self._decoded[a] = self._decode(a)
        return d

    def _decode(self, a: int) -> tuple:
        w = self.word(a)
        i = rabbitizer.Instruction(w, vram=a)
        if not i.isValid() or self.in_code(w):
            return "bad", None
        u = i.uniqueId
        if u == ID.cpu_jal:
            return "jal", i.getInstrIndexAsVram()
        if u == ID.cpu_j:
            return "j", i.getInstrIndexAsVram()
        if u == ID.cpu_jr:
            return "jr", None
        if u == ID.cpu_jalr:
            return "jalr", None
        if u == ID.cpu_eret:
            return "eret", None
        if i.isBranch():
            return ("ubranch" if i.isUnconditionalBranch() else "branch"), i.getBranchVramGeneric()
        return "plain", None

    def kind(self, a: int) -> str:
        return self.decode(a)[0]

    def jump_table(self, a: int) -> list:
        """Targets of the jr at a, if the code just before it loads a table address."""
        hi, table = {}, None
        for b in range(a - 4 * 14, a, 4):
            if not self.in_code(b):
                continue
            w = self.word(b)
            op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
            if op == LUI:
                hi[rt] = imm
            elif op in (ADDIU, LW) and rs in hi:
                table = ((hi[rs] << 16) + signed16(imm)) & 0xFFFFFFFF
        targets = []
        if table is None:
            return targets
        while self.vram <= table < self.vram + len(self.blob) - 3 and len(targets) <= 512:
            off = table - self.vram
            (w,) = struct.unpack(">I", self.blob[off:off + 4])
            if not self.in_code(w):
                break
            targets.append(w)
            table += 4
        return targets

    def _note_const(self, a: int) -> None:
        w = self.word(a)
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == LUI:
            self._hi[rt] = (imm, a)
        # The lui must sit just before. The trace jumps around, so a leftover lui
        # from higher up in memory is not this instruction's partner.
        elif op in (ADDIU, ORI) and rs in self._hi and 0 < a - self._hi[rs][1] <= 8:
            t = ((self._hi[rs][0] << 16) + (signed16(imm) if op == ADDIU else imm)) & 0xFFFFFFFF
            if self.in_code(t):
                self.consts[t].append(a)

    def trace(self, seed: int, tier: int) -> None:
        work = [seed]
        while work:
            a = work.pop()
            while True:
                if not self.in_code(a):
                    self.bad.append((seed, a, "ran off the end"))
                    break
                if a in self.visited:
                    break
                k, target = self.decode(a)
                if k == "bad":
                    self.bad.append((seed, a, "invalid instruction"))
                    break
                self.visited.add(a)
                self.reached.setdefault(a, tier)
                self._note_const(a)
                if k == "plain":
                    a += 4
                    continue
                # control flow: the delay slot is code too
                d = a + 4
                if self.in_code(d):
                    dk = self.kind(d)
                    if dk == "bad":
                        self.bad.append((seed, d, "invalid delay slot"))
                        break
                    if dk != "plain":
                        self.delay_branches.append(d)
                    self.reached.setdefault(d, tier)
                if k == "jal":
                    self.edges.append((a, target, "jal"))
                    if self.in_code(target):
                        self.call_targets.add(target)
                        work.append(target)
                    a += 8
                elif k == "jalr":
                    a += 8
                elif k == "branch":
                    self.edges.append((a, target, "branch"))
                    work.append(target)
                    a += 8
                elif k == "ubranch":
                    self.edges.append((a, target, "branch"))
                    work.append(target)
                    break
                elif k == "j":
                    self.edges.append((a, target, "j"))
                    if self.in_code(target):
                        work.append(target)
                    break
                elif k == "jr":
                    if (self.word(a) >> 21) & 31 != 31:
                        targets = self.jump_table(a)
                        self.table_jumps[a] = targets
                        for t in targets:
                            self.edges.append((a, t, "jtbl"))
                            work.append(t)
                    break
                else:   # eret
                    break

    def _snapshot(self) -> tuple:
        return (dict(self.reached), set(self.visited), len(self.edges), set(self.call_targets),
                dict(self.table_jumps), {k: list(v) for k, v in self.consts.items()},
                len(self.bad), len(self.delay_branches))

    def _restore(self, snap: tuple) -> None:
        self.reached, self.visited = snap[0], snap[1]
        del self.edges[snap[2]:]
        self.call_targets, self.table_jumps = snap[3], snap[4]
        self.consts = defaultdict(list, snap[5])
        del self.bad[snap[6]:]
        del self.delay_branches[snap[7]:]

    def run_tier(self, tier: int, seeds, label: str, strict: bool = True) -> None:
        """Trace from each seed. A strict seed is rolled back unless its code is clean."""
        before, rejected = len(self.reached), 0
        for s in sorted(seeds):
            if s in self.visited or s in self.rejected:
                continue
            self._hi.clear()
            if not strict:
                self.trace(s, tier)
                continue
            snap = self._snapshot()
            self.trace(s, tier)
            why = None
            if len(self.bad) > snap[6]:
                why = "%s at %08X" % (self.bad[snap[6]][2], self.bad[snap[6]][1])
            elif len(self.delay_branches) > snap[7]:
                why = "branch in a delay slot at %08X" % self.delay_branches[snap[7]]
            elif any(not self.in_code(dst) and k != "jal" for _, dst, k in self.edges[snap[2]:]):
                why = "jumps out of the segment"
            if why:
                self._restore(snap)
                self.rejected[s] = why
                rejected += 1
        self.tiers.append((tier, label, len(seeds), (len(self.reached) - before) * 4, rejected))

    def const_use(self, site: int) -> str:
        """What the code does with a lui+addiu value: 'table' if it loads through it."""
        r = (self.word(site) >> 16) & 31
        for x in range(site + 4, site + 4 * 10, 4):
            if not self.in_code(x):
                break
            w = self.word(x)
            op, rs, rt = w >> 26, (w >> 21) & 31, (w >> 16) & 31
            if op in LOADS and rs == r:
                return "table"
            if op == 0 and (w & 0x3F) in (0x20, 0x21) and r in (rs, rt):    # add, addu: indexed
                return "table"
            if op in STORES and rt == r:
                return "stored"
            if op in (LUI, ADDIU, ORI) and rt == r:
                break
        return "other"

    def is_table_base(self, a: int) -> bool:
        return any(self.const_use(site) == "table" for site in self.consts.get(a, ()))

    def code_consts(self) -> list:
        return [t for t in self.consts if not self.is_table_base(t)]

    def gap_pointers(self) -> set:
        """Code addresses stored in words the trace has not reached."""
        return {self.word(x) for x in range(self.vram, self.end, 4)
                if x not in self.reached and self.in_code(self.word(x))}

    def gaps(self) -> list:
        """Unreached stretches of the code area, as (start, end)."""
        out, a = [], self.vram
        while a < self.end:
            if a in self.reached:
                a += 4
                continue
            b = a
            while b < self.end and b not in self.reached:
                b += 4
            out.append((a, b))
            a = b
        return out

    def classify(self, a: int, b: int) -> str:
        """What an unreached stretch is. Only 'unreached code' counts as code."""
        ws = [self.word(x) for x in range(a, b, 4)]
        if any(self.is_table_base(x) for x in range(a, b, 4)):
            return "lookup table"
        if not any(ws):
            return "zero padding"
        nz = [w for w in ws if w]
        raw = self.blob[a - self.vram:b - self.vram]
        if sum(0x80000000 <= w < 0x80800000 for w in nz) * 2 >= len(nz):
            return "pointer table"
        if sum(0x20 <= c < 0x7F or c == 0 for c in raw) >= len(raw) * 0.95 and any(0x41 <= c < 0x7B for c in raw):
            return "text"
        if all(self.kind(x) != "bad" for x in range(a, b, 4)):
            return "unreached code"
        if sum(w < 0x10000 or w >= 0xFFFF0000 for w in nz) * 2 >= len(nz):
            return "number table"
        return "mixed data"


@dataclass
class Map:
    name: str
    rom: int
    vram: int
    code_size: int
    functions: list = field(default_factory=list)   # (start, size, how)
    routines: list = field(default_factory=list)    # (start, end, how), before splitting at entry points
    data: list = field(default_factory=list)        # (start, end, class)
    unreached: list = field(default_factory=list)   # (start, end) of code nothing reaches
    # Addresses stored in the data regions that land inside a function, not at its start.
    # Dispatch through such a table enters a function in the middle.
    mid_targets: list = field(default_factory=list)
    callers: dict = field(default_factory=dict)     # entry point -> addresses outside that call it
    tiers: list = field(default_factory=list)
    rejected: dict = field(default_factory=dict)
    traced_bytes: int = 0

    def rom_of(self, vram: int) -> int:
        return self.rom + vram - self.vram


def trace_segment(name: str, rom: int, blob: bytes, vram: int, code_size: int,
                  ext_calls: dict, ext_consts=(), other_pointers=()) -> Map:
    """Trace one segment. ext_calls: address -> outside callers. See the module text."""
    t = Tracer(blob, vram, code_size)
    own_pointers = scan_pointers(be_words(blob[code_size:]), t.in_code)

    t.run_tier(0, [vram], "segment start", strict=False)
    t.run_tier(1, list(ext_calls), "called from outside", strict=False)

    def weak_rounds():
        for _ in range(8):
            before = len(t.reached)
            t.run_tier(3, own_pointers, "addresses stored in the segment's data")
            t.run_tier(3, t.gap_pointers(), "addresses stored between routines")
            t.run_tier(2, t.code_consts(), "lui+addiu values (not table bases)")
            if len(t.reached) == before:
                break

    weak_rounds()
    t.run_tier(4, set(other_pointers) | set(ext_consts), "addresses stored or built outside")
    weak_rounds()

    starts = {vram} | set(ext_calls) | t.call_targets
    table_targets = {x for targets in t.table_jumps.values() for x in targets}
    # A table base is not a way into code, even when it lands on an instruction
    # (the word before a 1-based table is often the delay slot of a jr ra).
    pointer_starts = {x for x in own_pointers | set(other_pointers) | set(t.code_consts()) | set(ext_consts)
                      if x in t.reached} - table_targets
    natural_starts = {s for s in starts | pointer_starts if s in t.reached}

    # Unreached gaps that decode cleanly stay code; their branches count too.
    unreached = [(a, b) for a, b in t.gaps() if t.classify(a, b) == "unreached code"]
    live = set(t.reached)
    for a, b in unreached:
        for x in range(a, b, 4):
            k, target = t.decode(x)
            if k in ("branch", "ubranch"):
                t.edges.append((x, target, "branch"))
            elif k == "j":
                t.edges.append((x, target, "j"))
            t.reached[x] = 9
    data = [(a, b, t.classify(a, b)) for a, b in t.gaps()]

    runs, a = [], vram
    while a < t.end:
        if a not in t.reached:
            a += 4
            continue
        b = a
        while b < t.end and b in t.reached:
            b += 4
        runs.append((a, b))
        a = b

    extra = set()

    def build(cut_at: set) -> list:
        out = []
        for ra, rb in runs:
            cuts = sorted({ra} | {x for x in cut_at if ra <= x < rb})
            for n, c in enumerate(cuts):
                how = ("call" if c in starts else "pointer" if c in pointer_starts
                       else "entry" if c in extra else "orphan")
                out.append((c, cuts[n + 1] if n + 1 < len(cuts) else rb, how))
        return out

    routines = build(natural_starts)
    funcs = routines
    while True:
        firsts = [f[0] for f in funcs]
        known = set(firsts)
        add = set()
        for src, dst, k in t.edges:
            if k == "jal" or dst not in t.reached or src not in t.reached:
                continue
            if bisect.bisect_right(firsts, src) != bisect.bisect_right(firsts, dst) and dst not in known:
                add.add(dst)
        if not add:
            break
        extra |= add
        funcs = build(natural_starts | extra)

    firsts = {f[0] for f in funcs}
    stored = {t.word(x) for a, b, _ in data for x in range(a, b, 4)}
    mid_targets = sorted(w for w in stored if w in t.reached and w not in firsts)

    return Map(name, rom, vram, code_size, mid_targets=mid_targets,
               functions=[(s, e - s, how) for s, e, how in funcs], routines=routines, data=data,
               unreached=unreached, callers={k: list(v) for k, v in ext_calls.items()},
               tiers=t.tiers, rejected=t.rejected, traced_bytes=len(live) * 4)


def trace_rom(rom_path: Path = ROM) -> Map:
    """Trace stream3 in the decompressed ROM."""
    rom = Path(rom_path).read_bytes()
    s3_rom, s3_vram, s3_code, s3_total = STREAM3

    def is_target(a: int) -> bool:
        return s3_vram <= a < s3_vram + s3_code and a % 4 == 0

    calls, consts = defaultdict(list), set()
    for c_rom, c_vram, c_size in CALLERS.values():
        c, k = scan_code(be_words(rom[c_rom:c_rom + c_size]), c_vram, is_target)
        for target, sites in c.items():
            calls[target] += sites
        consts |= set(k)
    others = set()
    for d_rom, d_size in OTHER_DATA.values():
        others |= scan_pointers(be_words(rom[d_rom:d_rom + d_size]), is_target)
    return trace_segment("stream3", s3_rom, rom[s3_rom:s3_rom + s3_total], s3_vram, s3_code, calls, consts, others)


def yaml_lines(m: Map) -> list:
    """Subsegment lines for kigold.yaml: code and the data regions inside it, in order."""
    out, at = [], m.vram
    for a, b, cls in m.data:
        if a > at:
            out.append(f"      - [0x{m.rom_of(at):X}, asm]")
        out.append(f"      - [0x{m.rom_of(a):X}, data]   # 0x{a:08X}, {cls}, 0x{b - a:X}")
        at = b
    if at < m.vram + m.code_size:
        out.append(f"      - [0x{m.rom_of(at):X}, asm]")
    return out


def symbol_lines(m: Map) -> list:
    """Routine starts for symbol_addrs.txt, with the default names splat would give."""
    return [f"func_{s:08X}_{m.name} = 0x{s:08X}; // type:func segment:{m.name}" for s, _, _ in m.routines]


def summary(m: Map) -> str:
    def count(rows, how):
        return sum(r[2] == how for r in rows)

    data_bytes = sum(b - a for a, b, _ in m.data)
    dead_bytes = sum(b - a for a, b in m.unreached)
    lines = [f"{m.name}: code area 0x{m.vram:08X} to 0x{m.vram + m.code_size:08X} ({m.code_size} bytes)", "",
             "tier  seeds  new bytes  rejected  what"]
    lines += [f"{tier:>4}  {seeds:>5}  {new:>9}  {rej:>8}  {label}" for tier, label, seeds, new, rej in m.tiers]
    lines += ["", "entry points called from outside:"]
    lines += [f"  0x{t:08X}  called at {', '.join('0x%08X' % a for a in sites)}" for t, sites in sorted(m.callers.items())]
    lines += ["",
              f"code reached by tracing:   {m.traced_bytes:>6} bytes",
              f"code nothing reaches:      {dead_bytes:>6} bytes in {len(m.unreached)} pieces",
              f"data inside the code area: {data_bytes:>6} bytes in {len(m.data)} regions",
              f"routines:  {len(m.routines)} (by call {count(m.routines, 'call')}, by stored address "
              f"{count(m.routines, 'pointer')}, after an inline table {count(m.routines, 'orphan')})",
              f"functions: {len(m.functions)} (routines plus {count(m.functions, 'entry')} extra entry points), "
              f"{sum(f[1] for f in m.functions)} bytes",
              f"addresses stored in the data regions that land inside a function: {len(m.mid_targets)}",
              "", "data regions:"]
    lines += [f"  0x{a:08X} to 0x{b:08X}  0x{b - a:>4X}  {cls}" for a, b, cls in m.data]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rom", type=Path, default=ROM)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--yaml", action="store_true", help="print subsegment lines for kigold.yaml")
    group.add_argument("--symbols", action="store_true", help="print routine starts for symbol_addrs.txt")
    group.add_argument("--funcs", action="store_true", help="print the function list: start, size, how it is entered")
    args = parser.parse_args()
    if not args.rom.exists():
        print(f"error: {args.rom} is missing; run tools/unpack_rom.py first", file=sys.stderr)
        return 1
    m = trace_rom(args.rom)
    if args.yaml:
        print("\n".join(yaml_lines(m)))
    elif args.symbols:
        print("\n".join(symbol_lines(m)))
    elif args.funcs:
        print("\n".join(f"{s:08X} {size:X} {how}" for s, size, how in m.functions))
    else:
        print(summary(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
