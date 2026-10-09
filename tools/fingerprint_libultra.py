#!/usr/bin/env python3
"""Identify libultra functions in the game by fingerprinting (ground rule 5).

Compares every function splat found (disasm/asm/*.s) against reference
libultra objects built by tools/build_libultra_ref.py, and reports which game
functions are which libultra functions. The main score is coverage of the
function lists N64Recomp's runtime reimplements or ignores.

How a match works:
  A fingerprint is a function's instructions with the link-time fields blanked
  (call targets and address halves; the reference object's relocations say
  which). A game function is a candidate for a reference function when it has
  the same length and every other bit is identical.

A candidate only becomes a CONFIRMED name when all of these hold:
  - exact match, as above (never a partial or fuzzy match)
  - unique: one reference name for this game function, one game function for
    this name
  - big enough: at least --min-instr instructions (tiny functions look alike)
  - calls agree: wherever the reference calls a named function, the game
    calls a function that matches that same name; calls to file-local
    functions land at the same distance as in the reference
  - not isolated: it has a matching neighbour or an agreeing call

A tiny or ambiguous candidate can still be confirmed in two ways:
  - a confirmed function calls it by that name
  - data addresses: confirmed functions fix where each library variable lives
    in the game. A candidate name is accepted when the variables it reads sit
    at exactly those addresses, every other candidate name for the function is
    contradicted by them, and no other game function fits the name as well.
Everything else is LIKELY: reported, never named.

References are ELF objects (.o) and, for GoldenEye, assembly listings (.s) that
carry each instruction's bytes in a comment. A listing's labels were typed in
by hand and some are wrong, so a name from a compiled object always wins over
a listing's, and a match that only a listing supports is never confirmed.

Usage:
  python3 tools/fingerprint_libultra.py
  python3 tools/fingerprint_libultra.py --symbols-out build/libultra_symbols.txt
"""
import argparse
import re
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_ASM = REPO / "disasm" / "asm"
DEFAULT_REF = REPO / "build" / "ref" / "obj"
DEFAULT_LISTS = REPO / "build" / "ref" / "N64Recomp" / "src" / "symbol_lists.cpp"

MIN_INSTR = 8   # below this a fingerprint alone proves nothing
MIN_DATA_INSTR = 3  # smallest function a data address match may name
WINDOW = 3      # neighbour check: look this many functions each way

# ELF constants
SHT_SYMTAB, SHT_REL = 2, 9
STT_FUNC = 2
R_MIPS_32, R_MIPS_26, R_MIPS_HI16, R_MIPS_LO16 = 2, 4, 5, 6
STB_GLOBAL, STT_SECTION, SHN_COMMON = 1, 3, 0xFFF2
RELOC_16 = {5, 6, 7, 8, 9, 10, 11}  # HI16, LO16, GPREL16, LITERAL, GOT16, PC16, CALL16
JUMP_MASK = 0x03FFFFFF


class FingerprintError(Exception):
    pass


@dataclass
class RefFunc:
    name: str
    source: str            # reference build, for example "ultralib_2.0I_rom"
    obj: str               # object file, for example "os/createthread.o"
    words: list            # instructions, trailing nops stripped
    masks: list            # per word: bits that depend on the link address
    calls: dict            # word index -> ("sym", name) or ("static", distance from function start)
    listing: bool = False  # read from an assembly listing, not a compiled object
    # Address pairs: (index of the high half, index of the low half, key, offset).
    # key is ("sym", name) for a named variable, or ("local", source, obj, section).
    data: list = field(default_factory=list)

    @property
    def informative(self) -> int:
        """Instructions with at least some fixed bits."""
        return sum(m != 0xFFFFFFFF for m in self.masks)


@dataclass
class GameFunc:
    name: str
    vram: int
    words: list            # trailing nops stripped
    segment: str
    size: int = 0          # bytes, before stripping

    def __post_init__(self):
        self.size = self.size or len(self.words) * 4
        self.words = strip_nops(self.words)


@dataclass
class Match:
    game: GameFunc
    names: list            # candidate names; exactly one when confirmed
    confirmed: bool
    evidence: str          # for confirmed: why. for likely: why not
    refs: list = field(default_factory=list)


def sext16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def pair_value(words: list, hi: int, lo: int) -> int:
    """The address a lui/low-half instruction pair builds."""
    return ((words[hi] & 0xFFFF) << 16) + sext16(words[lo] & 0xFFFF)


def strip_nops(words: list) -> list:
    end = len(words)
    while end and words[end - 1] == 0:
        end -= 1
    return list(words[:end])


# ---------------------------------------------------------------- reference side

def read_object(data: bytes, source: str, obj: str) -> list:
    """Return the global functions of one big-endian MIPS ELF object."""
    if data[:4] != b"\x7fELF" or data[4] != 1 or data[5] != 2:
        raise FingerprintError(f"{obj}: not a 32-bit big-endian ELF object")
    shoff, = struct.unpack_from(">I", data, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from(">HHH", data, 0x2E)
    secs = [struct.unpack_from(">10I", data, shoff + i * shentsize) for i in range(shnum)]

    def cstr(table: bytes, off: int) -> str:
        return table[off:table.index(b"\0", off)].decode()

    def body(sec) -> bytes:
        return data[sec[4]:sec[4] + sec[5]]

    names = [cstr(body(secs[shstrndx]), s[0]) for s in secs]
    if ".text" not in names:
        return []
    text_idx = names.index(".text")
    text = body(secs[text_idx])

    symtab = next((s for s in secs if s[1] == SHT_SYMTAB), None)
    if symtab is None:
        return []
    strtab = body(secs[symtab[6]])
    syms = []  # (name, value, size, type, shndx)
    binds = []
    for i in range(symtab[5] // 16):
        n, value, size, info, _, shndx = struct.unpack_from(">IIIBBH", data, symtab[4] + i * 16)
        syms.append((cstr(strtab, n), value, size, info & 15, shndx))
        binds.append(info >> 4)

    def data_key(symidx: int, addend: int):
        """Which variable an address pair points at: (key, offset), or None."""
        sname, svalue, _, stype, sshndx = syms[symidx]
        if sshndx in (0, SHN_COMMON):
            return ("sym", sname), addend
        if sshndx >= len(secs):
            return None
        if sshndx == text_idx and svalue + addend in func_at and (stype == STT_SECTION or addend == 0):
            return ("sym", func_at[svalue + addend][0]), 0
        if binds[symidx] == STB_GLOBAL and stype != STT_SECTION and sname:
            return ("sym", sname), addend
        return ("local", source, obj, names[sshndx]), svalue + addend

    starts = sorted({v for _, v, _, t, sh in syms if t == STT_FUNC and sh == text_idx})
    func_at = {}
    for name, value, size, stype, shndx in syms:
        if stype != STT_FUNC or shndx != text_idx:
            continue
        if size == 0:  # no size recorded: runs to the next function or the section end
            later = [s for s in starts if s > value]
            size = (later[0] if later else len(text)) - value
        func_at[value] = (name, size)

    relocs = defaultdict(list)  # text offset -> [(type, symbol index)]
    for sec, sname in zip(secs, names):
        if sec[1] == SHT_REL and sec[7] == text_idx:
            for k in range(sec[5] // 8):
                off, info = struct.unpack_from(">II", data, sec[4] + k * 8)
                relocs[off].append((info & 0xFF, info >> 8))

    funcs = []
    for start, (name, size) in sorted(func_at.items()):
        words = list(struct.unpack_from(f">{size // 4}I", text, start))
        masks = [0] * len(words)
        calls = {}
        pairs = []
        last_hi = {}  # symbol index -> word index of its latest high half
        for i in range(len(words)):
            for rtype, symidx in relocs.get(start + i * 4, ()):
                if rtype == R_MIPS_HI16:
                    last_hi[symidx] = i
                elif rtype == R_MIPS_LO16 and symidx in last_hi:
                    hi = last_hi[symidx]
                    found = data_key(symidx, pair_value(words, hi, i))
                    if found:
                        pairs.append((hi, i, *found))
                if rtype == R_MIPS_26:
                    masks[i] |= JUMP_MASK
                    sname, svalue, _, stype, sshndx = syms[symidx]
                    if sshndx == text_idx:
                        # Defined in this object. A section symbol carries the
                        # target offset in the instruction itself.
                        target = svalue if stype == STT_FUNC else (words[i] & JUMP_MASK) << 2
                        if target in func_at:
                            calls[i] = ("sym", func_at[target][0])
                        else:
                            calls[i] = ("static", target - start)
                    elif sshndx == 0:
                        calls[i] = ("sym", sname)
                elif rtype in RELOC_16:
                    masks[i] |= 0xFFFF
                else:  # R_MIPS_32 or anything unexpected: trust no bit of it
                    masks[i] = 0xFFFFFFFF
        keep = len(strip_nops(words))
        funcs.append(RefFunc(name, source, obj, words[:keep], masks[:keep],
                             {i: c for i, c in calls.items() if i < keep},
                             data=[d for d in pairs if d[1] < keep]))
    return funcs


ASM_REF_LINE = re.compile(r"\s*/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]{8}) ([0-9A-Fa-f]{8}) \*/([^#]*)")
ASM_JUMP = re.compile(r"\s*(?:jal|j)\s+([^\s,]+)\s*$")
ASM_HALF = re.compile(r"%(hi|lo)\(([^)]*)\)")
ASM_EXPR = re.compile(r"([A-Za-z_]\w*)\s*(?:([+-])\s*(0x[0-9A-Fa-f]+|\d+))?$")
ASM_LOCAL = re.compile(r"\.L([0-9A-Fa-f]{8})$")


def read_asm_reference(text: str, source: str, obj: str) -> list:
    """Reference functions from an assembly listing with the bytes in comments.

    The listing does not say where a function ends, and a glabel can be a
    label in the middle of one. So every glabel is offered with every possible
    end (each later glabel, and the end of the code). Only the stretch that is
    exactly one game function can match.
    """
    rows, labels, in_text = [], [], True  # rows: (address, word, operand text)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith((".section", ".text", ".data", ".rodata", ".bss")):
            in_text = ".text" in stripped.split("#")[0]
        elif not in_text:
            continue
        elif stripped.startswith("glabel "):
            labels.append((len(rows), stripped.split()[1]))
        else:
            m = ASM_REF_LINE.match(line)
            if m:
                rows.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3)))
    labels = [(at, name) for at, name in labels if at < len(rows)]
    address_of = {name: rows[at][0] for at, name in labels}

    funcs = []
    for n, (start, name) in enumerate(labels):
        seen = set()
        for end in [at for at, _ in labels[n + 1:] if at > start] + [len(rows)]:
            span = rows[start:end]
            if any(b[0] - a[0] != 4 for a, b in zip(span, span[1:])):
                break  # a gap in the addresses: not one piece of code
            keep = len(strip_nops([w for _, w, _ in span]))
            if not keep or keep in seen:
                continue
            seen.add(keep)
            words, masks, calls, pairs, last_hi = [], [], {}, [], {}
            for i, (_, word, operands) in enumerate(span[:keep]):
                mask = 0
                jump = ASM_JUMP.match(operands)
                if jump:
                    mask = JUMP_MASK
                    target, local = jump.group(1), ASM_LOCAL.match(jump.group(1))
                    if target in address_of:
                        calls[i] = ("static", address_of[target] - span[0][0])
                    elif local:
                        calls[i] = ("static", int(local.group(1), 16) - span[0][0])
                    else:
                        calls[i] = ("sym", target)
                for half, expr in ASM_HALF.findall(operands):
                    mask |= 0xFFFF
                    expr = expr.strip()
                    if half == "hi":
                        last_hi[expr] = i
                    elif expr in last_hi and ASM_EXPR.match(expr):
                        sym, sign, number = ASM_EXPR.match(expr).groups()
                        offset = int(number, 0) * (-1 if sign == "-" else 1) if number else 0
                        pairs.append((last_hi[expr], i, ("sym", sym), offset))
                words.append(word)
                masks.append(mask)
            funcs.append(RefFunc(name, source, obj, words, masks, calls, True, pairs))
    return funcs


def load_references(ref_root: Path) -> list:
    """Every .o and .s under ref_root/<source>/. Sources are read in name order."""
    refs = []
    for source_dir in sorted(p for p in ref_root.iterdir() if p.is_dir()):
        for path in sorted(source_dir.rglob("*.o")):
            obj = path.relative_to(source_dir).as_posix()
            refs += read_object(path.read_bytes(), source_dir.name, obj)
        for path in sorted(source_dir.rglob("*.s")):
            obj = path.relative_to(source_dir).as_posix()
            refs += read_asm_reference(path.read_text(), source_dir.name, obj)
    return refs


# ---------------------------------------------------------------- game side

ASM_WORD = re.compile(r"\s*/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]{8}) ([0-9A-Fa-f]{8}) \*/")


def parse_splat_asm(text: str, segment: str) -> list:
    """Functions (glabel ... endlabel) from one splat .s file.

    Blocks splat wrote as raw words (dlabel) are skipped: they are not
    disassembled functions.
    """
    funcs, name, vram, words = [], None, None, []
    for line in text.splitlines():
        if line.startswith("glabel "):
            name, vram, words = line.split()[1], None, []
        elif line.startswith("endlabel") and name:
            if words:
                funcs.append(GameFunc(name, vram, words, segment))
            name = None
        elif name:
            m = ASM_WORD.match(line)
            if m:
                if vram is None:
                    vram = int(m.group(1), 16)
                words.append(int(m.group(2), 16))
    return funcs


def load_game(asm_dir: Path) -> list:
    game = []
    for path in sorted(asm_dir.glob("*.s")):
        game += parse_splat_asm(path.read_text(), path.stem)
    return game


# ---------------------------------------------------------------- matching

def is_exact(game: GameFunc, ref: RefFunc) -> bool:
    return len(game.words) == len(ref.words) and all(
        (g ^ r) & ~m & 0xFFFFFFFF == 0 for g, r, m in zip(game.words, ref.words, ref.masks))


def jump_target(game: GameFunc, index: int) -> int:
    pc = game.vram + index * 4 + 4
    return (pc & 0xF0000000) | ((game.words[index] & JUMP_MASK) << 2)


def data_bases(game: GameFunc, refs: list) -> set:
    """Where the game puts each variable, if `game` is the function `refs` describe.

    Returns {(key, address)}: the address the game's instruction pair builds,
    less the offset the reference adds to the variable.
    """
    return {(key, (pair_value(game.words, hi, lo) - offset) & 0xFFFFFFFF)
            for ref in refs for hi, lo, key, offset in ref.data}


def known_data(named: list) -> dict:
    """(segment, key) -> addresses, from (game function, name, its references).

    A key with more than one address is a conflict and proves nothing.
    Segments are kept apart because each may be linked with its own copy.
    """
    known = defaultdict(set)
    for g, name, refs in named:
        known[g.segment, ("sym", name)].add(g.vram)
        for key, base in data_bases(g, refs):
            known[g.segment, key].add(base)
    return known


def match_all(game: list, refs: list, min_instr: int = MIN_INSTR, window: int = WINDOW) -> list:
    """Return one Match for every game function that has at least one candidate."""
    refs_by_len = defaultdict(list)
    for r in refs:
        if r.words:
            refs_by_len[len(r.words)].append(r)

    # cands[i]: reference name -> the reference functions behind it
    cands = []
    for g in game:
        found = defaultdict(list)
        for r in refs_by_len.get(len(g.words), ()):
            if is_exact(g, r):
                found[r.name].append(r)
        # Names from compiled objects win over hand-typed listing labels.
        compiled = {name for name, rs in found.items() if not all(r.listing for r in rs)}
        cands.append({name: sorted(rs, key=lambda r: r.listing) for name, rs in found.items()
                      if name in compiled or not compiled})
    game_by_name = defaultdict(list)
    for i, found in enumerate(cands):
        for name in found:
            game_by_name[name].append(i)

    starts = defaultdict(list)  # vram -> game indexes (overlays can share an address)
    for i, g in enumerate(game):
        starts[g.vram].append(i)

    def inside_a_function(addr: int) -> bool:
        return any(g.vram < addr < g.vram + g.size for g in game)

    def callees(i: int, addr: int) -> list:
        """Game functions starting at addr, preferring the caller's own segment."""
        here = [j for j in starts.get(addr, ()) if game[j].segment == game[i].segment]
        return here or starts.get(addr, [])

    def check_calls(i: int, name: str):
        """Compare the calls of game[i] with the reference function `name`.

        Returns (agree, unverifiable, problems). agree is a list of
        (callee index, expected name) pairs.
        """
        g, ref = game[i], cands[i][name][0]
        agree, unverifiable, problems = [], 0, []
        for index, (kind, value) in sorted(ref.calls.items()):
            target = jump_target(g, index)
            if kind == "static":
                if target - g.vram == value:
                    agree.append((None, None))
                else:
                    problems.append(f"local call at +{index * 4:#x} lands at a different distance")
                continue
            there = callees(i, target)
            hit = [j for j in there if value in cands[j]]
            if hit:
                agree.append((hit[0], value))
            elif any(cands[j] for j in there):
                other = sorted(n for j in there for n in cands[j])
                problems.append(f"calls {value} in the reference, but {target:#010x} matches {'/'.join(other)}")
            elif not there and inside_a_function(target):
                problems.append(f"calls {value} in the reference, but {target:#010x} is not a function start")
            else:
                unverifiable += 1
        return agree, unverifiable, problems

    order = defaultdict(list)  # segment -> indexes in address order
    for i in sorted(range(len(game)), key=lambda k: game[k].vram):
        order[game[i].segment].append(i)
    position = {i: p for seg in order.values() for p, i in enumerate(seg)}

    def has_neighbour(i: int) -> bool:
        seg, p = order[game[i].segment], position[i]
        return any(cands[j] for j in seg[max(0, p - window):p + window + 1] if j != i)

    # Pass 1: confirm on the fingerprint alone.
    confirmed = {}   # game index -> (name, evidence)
    doubts = {}      # game index -> reasons it is not confirmed
    call_info = {}   # (game index, name) -> check_calls result
    for i, found in enumerate(cands):
        if not found:
            continue
        reasons = []
        for name in found:
            call_info[i, name] = check_calls(i, name)
        if len(found) > 1:
            reasons.append("matches several names")
        name = sorted(found)[0]
        ref = found[name][0]
        if len(found) == 1:
            agree, unverifiable, problems = call_info[i, name]
            if len(game_by_name[name]) > 1:
                reasons.append(f"{len(game_by_name[name])} game functions match this name")
            if ref.informative < min_instr:
                reasons.append(f"only {ref.informative} instructions")
            if ref.listing:
                reasons.append("the name comes only from an assembly listing")
            reasons += problems
            if not reasons and not agree and not has_neighbour(i):
                reasons.append("isolated: no matching neighbour and no agreeing call")
        if reasons:
            doubts[i] = reasons
        else:
            confirmed[i] = (name, describe(ref, agree, unverifiable))

    def check_data(i: int, name: str, known: dict):
        """(agreeing, contradicting) variables for game[i] read as `name`."""
        agree, against = [], []
        for key, base in sorted(data_bases(game[i], cands[i][name]), key=repr):
            bases = known.get((game[i].segment, key), ())
            if len(bases) == 1:
                (agree if base in bases else against).append((key, base))
        return agree, against

    def data_pass() -> bool:
        """Confirm functions whose data addresses single out one name."""
        known = known_data([(game[i], name, cands[i][name]) for i, (name, _) in confirmed.items()])
        taken = {name for name, _ in confirmed.values()}
        picked = []
        for i, found in enumerate(cands):
            if i in confirmed or not found:
                continue
            verdict = {name: check_data(i, name, known) for name in found}
            good = [name for name, (agree, against) in verdict.items() if agree and not against]
            if len(good) != 1:
                continue
            name = good[0]
            others = sorted(n for n in found if n != name)
            if any(not verdict[n][1] for n in others):
                continue  # another candidate name is not ruled out
            agree_calls, unverifiable, problems = call_info[i, name]
            ref = cands[i][name][0]
            if problems or name in taken or ref.informative < MIN_DATA_INSTR or ref.listing:
                continue
            if any(not check_data(j, name, known)[1] for j in game_by_name[name] if j != i):
                continue  # another game function fits this name as well
            key, base = verdict[name][0][0]
            text = (describe(ref, agree_calls, unverifiable)
                    + f"; data: {len(verdict[name][0])} addresses agree with confirmed functions"
                    + f" ({key[1] if key[0] == 'sym' else key[-1]} at {base:#010x})")
            if others:
                text += f"; data rules out {'/'.join(others)}"
            picked.append((i, name, text))
        for i, name, text in picked:
            confirmed[i] = (name, text)
            doubts.pop(i, None)
        return bool(picked)

    # Pass 2: a confirmed function vouches for the functions it calls by name.
    # Pass 3: data addresses. Repeat both until nothing new is confirmed.
    changed = True
    while changed:
        changed = False
        asked = defaultdict(set)  # callee -> {(name, caller)}
        for i, (name, _) in confirmed.items():
            for j, expected in call_info[i, name][0]:
                if j is not None and j not in confirmed:
                    asked[j].add((expected, i))
        for j, requests in asked.items():
            wanted = {n for n, _ in requests}
            if len(wanted) != 1:
                continue
            name = wanted.pop()
            agree, unverifiable, problems = call_info[j, name]
            taken = any(n == name for n, _ in confirmed.values())
            if problems or taken or len(game_by_name[name]) > 1 or cands[j][name][0].listing:
                continue
            caller = confirmed[min(i for _, i in requests)][0]
            confirmed[j] = (name, describe(cands[j][name][0], agree, unverifiable)
                            + f"; called as {name} by {caller}")
            doubts.pop(j, None)
            changed = True
        if not changed:
            changed = data_pass()

    # Final safety net: one name, one address.
    seen = defaultdict(list)
    for i, (name, _) in confirmed.items():
        seen[name].append(i)
    for name, idxs in seen.items():
        if len(idxs) > 1:
            for i in idxs:
                del confirmed[i]
                doubts[i] = [f"{name} was confirmed at {len(idxs)} addresses"]

    # Say so when the data addresses speak against a candidate.
    known = known_data([(game[i], name, cands[i][name]) for i, (name, _) in confirmed.items()])
    for i, reasons in doubts.items():
        for name in sorted(cands[i]):
            against = check_data(i, name, known)[1]
            if against:
                key = against[0][0]
                reasons.append(f"data: as {name}, {key[1] if key[0] == 'sym' else key[-1]} "
                               f"would be at a different address than in confirmed functions")

    out = []
    for i, found in enumerate(cands):
        if i in confirmed:
            name, evidence = confirmed[i]
            out.append(Match(game[i], [name], True, evidence, found[name]))
        elif found:
            out.append(Match(game[i], sorted(found), False, "; ".join(doubts[i]),
                             [r for rs in found.values() for r in rs]))
    return out


def data_conflicts(matches: list) -> list:
    """Variables that two confirmed functions of one segment place differently."""
    known = known_data([(m.game, m.names[0], m.refs) for m in matches if m.confirmed])
    return sorted((segment, key[1] if key[0] == "sym" else "/".join(key[1:]), sorted(bases))
                  for (segment, key), bases in known.items() if len(bases) > 1)


def describe(ref: RefFunc, agree: list, unverifiable: int) -> str:
    text = f"exact match, {len(ref.words)} instr, {ref.source} {ref.obj}"
    if agree or unverifiable:
        text += f"; {len(agree)} calls agree"
        if unverifiable:
            text += f", {unverifiable} could not be checked"
    return text


# ---------------------------------------------------------------- reporting

LIST_BLOCK = re.compile(r"N64Recomp::(\w+)\s*\{(.*?)\n\};", re.S)


def parse_runtime_lists(text: str) -> dict:
    """The name sets in N64Recomp's src/symbol_lists.cpp, by list name."""
    lists = {}
    for name, body in LIST_BLOCK.findall(text):
        body = re.sub(r"//[^\n]*", "", body)
        lists[name] = set(re.findall(r'"([^"]+)"', body))
    return lists


def coverage(matches: list, refs: list, lists: dict) -> list:
    """Rows of (list name, total, in reference, confirmed, likely)."""
    ref_names = {r.name for r in refs}
    confirmed = {m.names[0] for m in matches if m.confirmed}
    likely = {n for m in matches if not m.confirmed for n in m.names} - confirmed
    return [(name, len(names), len(names & ref_names), len(names & confirmed), len(names & likely))
            for name, names in sorted(lists.items())]


def symbol_lines(matches: list) -> str:
    """Proposed disasm/symbol_addrs.txt entries, confirmed matches only."""
    lines = []
    for m in sorted((m for m in matches if m.confirmed), key=lambda m: (m.game.segment, m.game.vram)):
        lines.append(f"// evidence: {m.evidence}")
        lines.append(f"{m.names[0]} = 0x{m.game.vram:08X}; // type:func")
    return "\n".join(lines) + "\n"


def report(game: list, refs: list, matches: list, lists: dict) -> str:
    out = []
    confirmed = [m for m in matches if m.confirmed]
    likely = [m for m in matches if not m.confirmed]
    sources = sorted({r.source for r in refs})
    out.append(f"Reference: {len({r.name for r in refs})} function names from {', '.join(sources)}")
    out.append(f"Game: {len(game)} functions. Confirmed {len(confirmed)}, likely {len(likely)}, "
               f"no match {len(game) - len(matches)}.")
    if lists:
        out.append("")
        out.append("Main score: coverage of the runtime's lists (confirmed names only)")
        out.append("Not every listed function is in every game, so 100% is not expected.")
        for name, total, in_ref, conf, lik in coverage(matches, refs, lists):
            out.append(f"  {name:<20} {conf:>4} of {total} confirmed, {lik} more likely, "
                       f"{in_ref} exist in the reference")
    out.append("")
    out.append("Per segment (confirmed / likely / functions):")
    for seg in sorted({g.segment for g in game}):
        out.append(f"  {seg:<10} {sum(m.game.segment == seg for m in confirmed):>4} / "
                   f"{sum(m.game.segment == seg for m in likely):>4} / "
                   f"{sum(g.segment == seg for g in game):>4}")
    conflicts = data_conflicts(matches)
    out.append("")
    out.append(f"Data address conflicts between confirmed functions: {len(conflicts)}")
    for segment, what, bases in conflicts:
        out.append(f"   {segment:<8} {what} at {', '.join(f'{b:#010x}' for b in bases)}")
    listed = set().union(*lists.values()) if lists else set()
    out.append("")
    out.append("Confirmed (* = on a runtime list):")
    for m in sorted(confirmed, key=lambda m: (m.game.segment, m.game.vram)):
        star = "*" if m.names[0] in listed else " "
        out.append(f" {star} {m.game.vram:08X} {m.game.segment:<8} {m.names[0]:<28} {m.evidence}")
    out.append("")
    out.append("Likely, not named:")
    for m in sorted(likely, key=lambda m: (m.game.segment, m.game.vram)):
        star = "*" if listed & set(m.names) else " "
        out.append(f" {star} {m.game.vram:08X} {m.game.segment:<8} {'/'.join(m.names)[:60]:<28} {m.evidence}")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asm", type=Path, default=DEFAULT_ASM, help="folder of splat .s files")
    parser.add_argument("--ref", type=Path, default=DEFAULT_REF,
                        help="folder with one subfolder of .o files per reference build")
    parser.add_argument("--lists", type=Path, default=DEFAULT_LISTS,
                        help="N64Recomp src/symbol_lists.cpp")
    parser.add_argument("--min-instr", type=int, default=MIN_INSTR)
    parser.add_argument("--symbols-out", type=Path,
                        help="write proposed symbol_addrs.txt lines here (keep it under build/)")
    args = parser.parse_args()

    try:
        for path, what in ((args.asm, "splat output; run the split first"),
                           (args.ref, "reference objects; run tools/build_libultra_ref.py first")):
            if not path.is_dir():
                raise FingerprintError(f"{path} not found ({what})")
        refs = load_references(args.ref)
        game = load_game(args.asm)
        if not refs or not game:
            raise FingerprintError(f"nothing to compare: {len(refs)} reference and {len(game)} game functions")
    except FingerprintError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    lists = parse_runtime_lists(args.lists.read_text()) if args.lists.is_file() else {}
    if not lists:
        print(f"note: {args.lists} not found, so no coverage score", file=sys.stderr)

    matches = match_all(game, refs, args.min_instr)
    print(report(game, refs, matches, lists))
    if args.symbols_out:
        args.symbols_out.write_text(symbol_lines(matches))
        print(f"\nWrote {args.symbols_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
