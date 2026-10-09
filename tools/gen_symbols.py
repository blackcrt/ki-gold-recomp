#!/usr/bin/env python3
"""Generate the symbol file N64Recomp reads (syms/dump.toml).

Reads the splat project, never the ROM:
  - disasm/kigold.yaml       where each code segment sits (ROM offset, RAM
                             address, where its code ends)
  - disasm/asm/<start>.s     the functions splat found (glabel ... endlabel)
  - disasm/symbol_addrs.txt  our named functions, used as a cross-check

Writes one [[section]] per code segment with every function's name, RAM
address and size, the same layout WM2K's tools/gen_symbols.py produces. The
overlays (stream2, stream3) are ordinary sections that share RAM addresses.

The output holds names, addresses and sizes only. It is safe to commit.

What it refuses to write (exit 1):
  - a function outside its section, overlapping another, or not word aligned
  - a size that disagrees with the size splat printed for the function
  - a name used twice
  - a function named in symbol_addrs.txt that is missing or at another address

What it reports but cannot fix: code that is in no function. Blocks splat
wrote as raw words (dlabel) and extra entry labels (alabel) are counted per
section; they are not in the symbol file.

Run from the repo root, after a splat split, with the splat environment:
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


def sub_start(sub) -> int:
    return sub["start"] if isinstance(sub, dict) else sub[0]


def sub_type(sub) -> str:
    if isinstance(sub, dict):
        return sub.get("type", "")
    return sub[1] if len(sub) > 1 else ""


def read_sections(config: dict) -> list:
    """Code segments from the splat config: the part before the first non-asm subsegment."""
    sections = []
    for seg in config["segments"]:
        if not isinstance(seg, dict) or seg.get("type") != "code":
            continue
        subs = seg["subsegments"]
        if sub_type(subs[0]) != "asm" or sub_start(subs[0]) != seg["start"]:
            raise SymbolError(f"{seg['name']}: expected one asm subsegment at the segment start")
        if len(subs) < 2 or sub_type(subs[1]) == "asm":
            raise SymbolError(f"{seg['name']}: cannot tell where the code ends")
        sections.append(Section(seg["name"], seg["start"], seg["vram"], sub_start(subs[1]) - seg["start"]))
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
    names = set(named)
    for sec in sections:
        covered = sum(f.size for f in sec.funcs)
        lines.append(f"{sec.name:<9} {len(sec.funcs):>9}  {sum(f.name in names for f in sec.funcs):>5}  "
                     f"{sec.size:>10}  {covered:>6} {100 * covered / sec.size:>4.0f}%  {sec.raw_blocks:>10}  "
                     f"{sec.raw_bytes:>9}  {sec.raw_entries:>11}  {sec.func_entries:>16}")
    lines.append(f"total     {sum(len(s.funcs) for s in sections):>9}  {len(named):>5}")
    return "\n".join(lines)


def generate(config: dict, asm_dir: Path, symbol_text: str):
    sections = read_sections(config)
    for sec in sections:
        path = asm_dir / f"{sec.rom:X}.s"
        if not path.exists():
            raise SymbolError(f"{path} is missing; run the splat split first")
        parse_asm(path.read_text(), sec)
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
    base = args.config.parent
    try:
        config = yaml.safe_load(args.config.read_text())
        sections, named = generate(config, base / config["options"]["asm_path"],
                                   (base / config["options"]["symbol_addrs_path"]).read_text())
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
