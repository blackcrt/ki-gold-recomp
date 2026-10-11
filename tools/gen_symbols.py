#!/usr/bin/env python3
"""Generate the symbol file N64Recomp reads (syms/dump.toml).

Reads the splat project:
  - disasm/kigold.yaml       where each code segment sits (ROM offset, RAM
                             address, where its code ends)
  - disasm/asm/<start>.s     the functions splat found (glabel ... endlabel)
  - disasm/symbol_addrs.txt  our named functions, used as a cross-check

stream3 is the exception. It is hand-written assembly and splat's function
guesses are wrong for it, so its function list comes from the tracer
(tools/stream3_map.py, which reads the decompressed ROM in build/). splat's
stream3 files are still read, but only to prove no code was left undecoded.

Writes one [[section]] per code segment with every function's name, RAM
address and size, the same layout WM2K's tools/gen_symbols.py produces. The
overlays (stream2, stream3) are ordinary sections that share RAM addresses.

The output holds names, addresses and sizes only. It is safe to commit.

What it refuses to write (exit 1):
  - a function outside its section, overlapping another, or not word aligned
  - a size that disagrees with the size splat printed for the function
  - a name used twice
  - a function named in symbol_addrs.txt that is missing or at another address
  - for a traced section: code and data pieces in kigold.yaml that differ from
    the tracer's, a traced function that is not inside a code piece, or a raw
    block left in splat's output

What it reports but cannot fix: code that is in no function. Blocks splat
wrote as raw words (dlabel) and extra entry labels (alabel) are counted per
section; they are not in the symbol file.

Run from the repo root, after tools/unpack_rom.py and a splat split, with the
splat environment:
  disasm/.venv/bin/python tools/gen_symbols.py
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASM_LINE = re.compile(r"\s*/\* [0-9A-Fa-f]+ ([0-9A-Fa-f]{8}) [0-9A-Fa-f]{8} \*/")
NONMATCHING = re.compile(r"nonmatching (\S+), (0x[0-9A-Fa-f]+)")
SYMBOL_LINE = re.compile(r"\s*(\w+)\s*=\s*(0x[0-9A-Fa-f]+)\s*;\s*//(.*)")
DEFAULT_NAME = re.compile(r"func_[0-9A-F]{8}(_\w+)?$")     # a name splat would give anyway


class SymbolError(Exception):
    pass


@dataclass
class Func:
    name: str
    vram: int
    size: int


@dataclass
class Section:
    name: str
    rom: int
    vram: int
    size: int                      # code only
    funcs: list = field(default_factory=list)
    raw_blocks: int = 0            # dlabel blocks: code splat could not decode
    raw_bytes: int = 0
    raw_entries: int = 0           # alabel inside a raw block
    func_entries: int = 0          # alabel inside a function
    files: list = field(default_factory=list)      # ROM starts of the asm subsegments
    suffix: str = ""               # "_<segment>" when the config adds it to default names
    traced: bool = False           # functions come from the tracer, not from splat
    tables: list = field(default_factory=list)     # traced only: (vram, size) of data inside the code


def sub_start(sub) -> int:
    return sub["start"] if isinstance(sub, dict) else sub[0]


def sub_type(sub) -> str:
    if isinstance(sub, dict):
        return sub.get("type", "")
    return sub[1] if len(sub) > 1 else ""


def traced_pieces(m) -> list:
    """The code and data pieces a traced map expects in the config: (rom, type)."""
    out, at = [], m.vram
    for a, b, _ in m.data:
        if a > at:
            out.append((m.rom + at - m.vram, "asm"))
        out.append((m.rom + a - m.vram, "data"))
        at = b
    if at < m.vram + m.code_size:
        out.append((m.rom + at - m.vram, "asm"))
    return out


def read_sections(config: dict, traced: dict = None) -> list:
    """Code segments from the splat config.

    The code is the part before the first non-asm subsegment. A traced section
    has tables inside its code, so its code size comes from the tracer and its
    subsegments must be exactly the tracer's code and data pieces.
    """
    sections = []
    for seg in config["segments"]:
        if not isinstance(seg, dict) or seg.get("type") != "code":
            continue
        name, subs = seg["name"], seg["subsegments"]
        if sub_type(subs[0]) != "asm" or sub_start(subs[0]) != seg["start"]:
            raise SymbolError(f"{name}: expected one asm subsegment at the segment start")
        m = (traced or {}).get(name)
        if m is None:
            if len(subs) < 2 or sub_type(subs[1]) == "asm":
                raise SymbolError(f"{name}: cannot tell where the code ends")
            sec = Section(name, seg["start"], seg["vram"], sub_start(subs[1]) - seg["start"])
            sec.files = [seg["start"]]
        else:
            if (m.rom, m.vram) != (seg["start"], seg["vram"]):
                raise SymbolError(f"{name}: the tracer and the config disagree on where the segment is")
            sec = Section(name, m.rom, m.vram, m.code_size, traced=True)
            end = m.rom + m.code_size
            pieces = [(sub_start(s), sub_type(s)) for s in subs if sub_start(s) < end]
            if pieces != traced_pieces(m) or not any(sub_start(s) == end for s in subs):
                raise SymbolError(f"{name}: the subsegments in the config are not the tracer's code and data "
                                  f"pieces; update them from the tracer's --yaml output")
            sec.files = [rom for rom, kind in pieces if kind == "asm"]
            sec.tables = [(a, b - a) for a, b, _ in m.data]
        if seg.get("symbol_name_format") == "$VRAM_$SEG":
            sec.suffix = f"_{name}"
        sections.append(sec)
    return sections


def parse_asm(text: str, section: Section) -> None:
    """Fill a section from one splat .s file."""
    declared = {}                  # sizes splat printed on its nonmatching lines
    name, first, last = None, None, None
    in_raw = False
    for line in text.splitlines():
        # splat indents an alabel that sits inside a function
        word = line.split(None, 1)[0] if line.strip() else ""
        if word == "nonmatching":
            m = NONMATCHING.match(line)
            if m:
                declared[m.group(1)] = int(m.group(2), 16)
        elif word == "glabel":
            name, first, last, in_raw = line.split()[1], None, None, False
        elif word == "dlabel":
            section.raw_blocks += 1
            in_raw = True
        elif word == "alabel":
            if name:
                section.func_entries += 1
            else:
                section.raw_entries += 1
        elif word == "endlabel" and name:
            if first is None:
                raise SymbolError(f"{section.name}: {name} has no instructions")
            size = last + 4 - first
            if name in declared and declared[name] != size:
                raise SymbolError(f"{section.name}: {name} is 0x{size:X} bytes but splat says 0x{declared[name]:X}")
            section.funcs.append(Func(name, first, size))
            name = None
        else:
            m = ASM_LINE.match(line)
            if not m:
                continue
            if name:
                last = int(m.group(1), 16)
                if first is None:
                    first = last
            elif in_raw:
                section.raw_bytes += 4
    if name:
        raise SymbolError(f"{section.name}: {name} has no endlabel")


def check(sections: list) -> None:
    seen = {}
    for sec in sections:
        end, prev = sec.vram + sec.size, None
        for f in sec.funcs:
            if f.name in seen:
                raise SymbolError(f"{f.name} is in both {seen[f.name]} and {sec.name}")
            seen[f.name] = sec.name
            if f.vram & 3 or f.size & 3 or f.size == 0:
                raise SymbolError(f"{sec.name}: {f.name} is not word aligned")
            if f.vram < sec.vram or f.vram + f.size > end:
                raise SymbolError(f"{sec.name}: {f.name} is outside the section")
            if prev and f.vram < prev.vram + prev.size:
                raise SymbolError(f"{sec.name}: {f.name} overlaps {prev.name}")
            prev = f


def use_traced(sec: Section, m, symbol_text: str) -> None:
    """Replace splat's functions for a section with the tracer's."""
    if sec.raw_blocks:
        raise SymbolError(f"{sec.name}: splat left {sec.raw_blocks} raw blocks in traced code")
    names = {}                     # our names for this segment: address -> name
    for line in symbol_text.splitlines():
        s = SYMBOL_LINE.match(line)
        if s and "type:func" in s.group(3) and f"segment:{sec.name}" in s.group(3).split():
            names[int(s.group(2), 16)] = s.group(1)
    code, at = [], sec.vram        # the code pieces, as (start, end) in RAM
    for a, size in sec.tables:
        code.append((at, a))
        at = a + size
    code.append((at, sec.vram + sec.size))
    sec.funcs = []
    for vram, size, *_ in m.functions:
        if not any(a <= vram and vram + size <= b for a, b in code):
            raise SymbolError(f"{sec.name}: traced function at 0x{vram:08X} is not inside one code piece")
        sec.funcs.append(Func(names.get(vram, f"func_{vram:08X}{sec.suffix}"), vram, size))


def read_named(text: str) -> dict:
    """Function names from symbol_addrs.txt: name -> address."""
    named = {}
    for line in text.splitlines():
        m = SYMBOL_LINE.match(line)
        if m and "type:func" in m.group(3):
            named[m.group(1)] = int(m.group(2), 16)
    return named


def check_named(sections: list, named: dict) -> None:
    found = {f.name: f.vram for sec in sections for f in sec.funcs}
    for name, vram in named.items():
        if name not in found:
            raise SymbolError(f"{name} is in symbol_addrs.txt but not in the split")
        if found[name] != vram:
            raise SymbolError(f"{name} is at 0x{found[name]:08X} in the split, 0x{vram:08X} in symbol_addrs.txt")


def render(sections: list) -> str:
    out = ["# Generated from the splat disassembly by tools/gen_symbols.py. Do not edit by hand.",
           "# Names, addresses and sizes only."]
    for sec in sections:
        out += ["", "[[section]]", f'name = "{sec.name}"', f"rom = 0x{sec.rom:08X}",
                f"vram = 0x{sec.vram:08X}", f"size = 0x{sec.size:X}", "", "functions = ["]
        out += [f'    {{ name = "{f.name}", vram = 0x{f.vram:08X}, size = 0x{f.size:X} }},' for f in sec.funcs]
        out += ["]"]
    return "\n".join(out) + "\n"


def report(sections: list, named: dict) -> str:
    lines = ["section   functions  named  code bytes  in functions  raw blocks  raw bytes  raw entries  entries in funcs"]
    names = {n for n in named if not DEFAULT_NAME.match(n)}
    for sec in sections:
        covered = sum(f.size for f in sec.funcs)
        lines.append(f"{sec.name:<9} {len(sec.funcs):>9}  {sum(f.name in names for f in sec.funcs):>5}  "
                     f"{sec.size:>10}  {covered:>6} {100 * covered / sec.size:>4.0f}%  {sec.raw_blocks:>10}  "
                     f"{sec.raw_bytes:>9}  {sec.raw_entries:>11}  {sec.func_entries:>16}")
    lines.append(f"total     {sum(len(s.funcs) for s in sections):>9}  {len(names):>5}")
    for sec in sections:
        if sec.traced:
            lines.append(f"{sec.name}: functions come from the tracer, not splat. {len(sec.tables)} tables "
                         f"({sum(size for _, size in sec.tables)} bytes) sit inside its code. The entry "
                         f"labels counted are splat's and are not used.")
    return "\n".join(lines)


def generate(config: dict, asm_dir: Path, symbol_text: str, traced: dict = None):
    """traced: section name -> the tracer's map for it (see tools/stream3_map.py)."""
    sections = read_sections(config, traced)
    for sec in sections:
        for rom in sec.files:
            path = asm_dir / f"{rom:X}.s"
            if not path.exists():
                raise SymbolError(f"{path} is missing; run the splat split first")
            parse_asm(path.read_text(), sec)
        if sec.traced:
            use_traced(sec, traced[sec.name], symbol_text)
    check(sections)
    named = read_named(symbol_text)
    check_named(sections, named)
    return sections, named


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=REPO / "disasm" / "kigold.yaml")
    parser.add_argument("--out", type=Path, default=REPO / "syms" / "dump.toml")
    args = parser.parse_args()
    try:
        import yaml
    except ImportError:
        print("PyYAML is missing. Run with disasm/.venv/bin/python.", file=sys.stderr)
        return 1
    try:
        import stream3_map
    except ImportError:
        print("rabbitizer is missing. Run with disasm/.venv/bin/python.", file=sys.stderr)
        return 1
    if not stream3_map.ROM.exists():
        print(f"error: {stream3_map.ROM} is missing; run tools/unpack_rom.py first", file=sys.stderr)
        return 1
    base = args.config.parent
    try:
        config = yaml.safe_load(args.config.read_text())
        sections, named = generate(config, base / config["options"]["asm_path"],
                                   (base / config["options"]["symbol_addrs_path"]).read_text(),
                                   {"stream3": stream3_map.trace_rom()})
    except SymbolError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(exist_ok=True)
    args.out.write_text(render(sections), newline="\n")
    print(report(sections, named))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
