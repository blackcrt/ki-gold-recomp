#!/usr/bin/env python3
"""Known-answer test for tools/gen_symbols.py (ground rule 4).

Builds a tiny made-up splat project in a temporary folder (a config, two .s
files, a symbol list) and checks the generator finds exactly the functions
that were put in. Uses no real ROM data.

Usage:
  python3 tools/test_gen_symbols.py
"""

import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import gen_symbols
from gen_symbols import SymbolError

CONFIG = {
    "options": {"asm_path": "asm", "symbol_addrs_path": "symbol_addrs.txt"},
    "segments": [
        {"name": "header", "type": "header", "start": 0},
        {"name": "main", "type": "code", "start": 0x1000, "vram": 0x80000400,
         "subsegments": [[0x1000, "asm"], [0x1040, "data"], {"start": 0x1080, "type": "bss", "vram": 0x80000480}]},
        {"name": "blob", "type": "bin", "start": 0x1080},
        {"name": "ovl", "type": "code", "start": 0x2000, "vram": 0x80100000,
         "subsegments": [[0x2000, "asm"], [0x2030, "bin", "tail"]]},
        [0x3000],
    ],
}


def lines(rom: int, vram: int, count: int, word: bool = False) -> str:
    return "".join(f"    /* {rom + 4 * i:X} {vram + 4 * i:08X} 00000000 */ {'.word 0x0' if word else ' nop'}\n"
                   for i in range(count))


def func(name: str, rom: int, vram: int, count: int, declared: int = None) -> str:
    size = 4 * count if declared is None else declared
    return f"nonmatching {name}, 0x{size:X}\n\nglabel {name}\n{lines(rom, vram, count)}endlabel {name}\n\n"


# main: three functions back to back. The middle one has an extra entry label
# inside it, indented the way splat writes it.
MIDDLE = func("func_80000410", 0x1010, 0x80000410, 6).replace(
    "    /* 1018 ", "  alabel func_80000418\n    /* 1018 ")
MAIN = func("first", 0x1000, 0x80000400, 4) + MIDDLE + func("last", 0x1030, 0x80000430, 4)
# ovl: one function, then a raw block with one extra entry label in it.
OVL = (func("func_80100000_ovl", 0x2000, 0x80100000, 3)
       + "dlabel func_8010000C_ovl\n" + lines(0x200C, 0x8010000C, 2, word=True)
       + "nonmatching func_80100014_ovl\n\nalabel func_80100014_ovl\n" + lines(0x2014, 0x80100014, 5, word=True)
       + "enddlabel func_8010000C_ovl\n")
SYMBOLS = ("// comment\nfirst = 0x80000400; // type:func\nlast = 0x80000430; // type:func\n"
           "some_data = 0x80000440;\n")


def run(main: str = MAIN, ovl: str = OVL, symbols: str = SYMBOLS, config: dict = CONFIG):
    with tempfile.TemporaryDirectory() as tmp:
        asm = Path(tmp) / "asm"
        asm.mkdir()
        (asm / "1000.s").write_text(main)
        if ovl is not None:
            (asm / "2000.s").write_text(ovl)
        return gen_symbols.generate(config, asm, symbols)


def fails(**kwargs) -> bool:
    try:
        run(**kwargs)
    except SymbolError:
        return True
    return False


def main() -> int:
    sections, named = run()
    parsed = tomllib.loads(gen_symbols.render(sections))["section"]
    main_sec, ovl_sec = sections
    no_code_end = dict(CONFIG, segments=[dict(CONFIG["segments"][1], subsegments=[[0x1000, "asm"]])])
    checks = [
        ("only code segments become sections", [s.name for s in sections] == ["main", "ovl"]),
        ("section address and code size come from the config",
         [(s.rom, s.vram, s.size) for s in sections] == [(0x1000, 0x80000400, 0x40), (0x2000, 0x80100000, 0x30)]),
        ("functions are found with name, address and size",
         [(f.name, f.vram, f.size) for f in main_sec.funcs]
         == [("first", 0x80000400, 0x10), ("func_80000410", 0x80000410, 0x18), ("last", 0x80000430, 0x10)]),
        ("a raw block is not a function", [f.name for f in ovl_sec.funcs] == ["func_80100000_ovl"]),
        ("raw blocks are counted", (ovl_sec.raw_blocks, ovl_sec.raw_bytes) == (1, 28)),
        ("an entry label inside a raw block is counted", (ovl_sec.raw_entries, ovl_sec.func_entries) == (1, 0)),
        ("an indented entry label inside a function is counted, and is not a function",
         (main_sec.raw_entries, main_sec.func_entries) == (0, 1) and "alabel" in MIDDLE),
        ("only type:func lines count as named functions", named == {"first": 0x80000400, "last": 0x80000430}),
        ("the output parses as TOML with the same content",
         [(s["name"], s["rom"], s["vram"], s["size"], len(s["functions"])) for s in parsed]
         == [("main", 0x1000, 0x80000400, 0x40, 3), ("ovl", 0x2000, 0x80100000, 0x30, 1)]
         and parsed[0]["functions"][1] == {"name": "func_80000410", "vram": 0x80000410, "size": 0x18}),
        ("a size that disagrees with splat is refused",
         fails(main=func("first", 0x1000, 0x80000400, 4, declared=0x20))),
        ("overlapping functions are refused",
         fails(main=func("first", 0x1000, 0x80000400, 4) + func("b", 0x100C, 0x8000040C, 4))),
        ("a function past the end of the code is refused", fails(main=func("first", 0x1000, 0x80000400, 17))),
        ("a name used in two sections is refused", fails(ovl=func("first", 0x2000, 0x80100000, 3))),
        ("a named function missing from the split is refused",
         fails(symbols=SYMBOLS + "ghost = 0x80000420; // type:func\n")),
        ("a named function at another address is refused",
         fails(symbols="first = 0x80000404; // type:func\n")),
        ("a function with no endlabel is refused", fails(main=MAIN + "glabel open\n" + lines(0x1040, 0x80000440, 1))),
        ("a missing .s file is refused", fails(ovl=None)),
        ("a segment with no code end is refused", fails(config=no_code_end, ovl=None)),
    ]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    failed = sum(not ok for _, ok in checks)
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
