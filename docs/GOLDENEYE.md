# GoldenEye 007 decomp: reference notes for KI Gold

GoldenEye ([n64decomp/007](https://github.com/n64decomp/007)) is 100% matched and was built by the same studio about a year after KI Gold. These notes record what to borrow and what to check. Studied 2026-10-08 from a shallow clone of its `master` branch.

Everything here is a **lead**, not a fact about KI Gold. KI Gold shipped in late 1996, GoldenEye in 1997, so Rare's tools and library versions may differ.

**Relevance to the recomp:** written when the plan was a matching decomp. For the recomp, the **libultra** and **compression** sections matter most: identifying libultra functions is how the symbol file tells the runtime which functions to replace, and compressed code must be decompressed before N64Recomp can read it. The compiler section only matters for the optional partial decomp (Phase 6).

## Compiler and flags

| Setting | GoldenEye value | Use for KI Gold |
| --- | --- | --- |
| Compiler | IDO 5.3 (via ido-static-recomp) | First guess |
| Game code optimization | `-O2` | First guess |
| ISA | `-mips2 -32` | First guess |
| Common flags | `-Wab,-r4300_mul -non_shared -Olimit 2000 -G 0 -Xcpluscomm` | Copy as-is |
| libultra optimization | `-O1` for both C and assembly | First guess for library code |
| libultra extra defines | `-DNDEBUG`, `_FINALROM` for `os/` files | Copy as-is |
| Some math (`random.c`) | Experimented with `-O3 -mips3`, commented out | Note only |

**Verified here:** IDO 5.3 from [ido-static-recomp v1.2](https://github.com/decompals/ido-static-recomp/releases/tag/v1.2) (`ido-5.3-recomp-linux.tar.gz`) downloads and compiles a test function with these flags.

## libultra

- GoldenEye uses **libultra version G** (`src/libultra/readme.md`), kept unmodified.
- Rare's changes live separately in **`src/libultrare/`**. Files Rare modified:
  - audio: `drvrNew.c`, `env.c`, `reverb.c`
  - io: controller and EEPROM/Controller Pak routines (`controller.c`, `contreaddata.c`, `conteep*.c`, `contram*.c`, `pfsinit.c`, `pfsisplug.c`), `pimgr.c`, `devmgr.c`, `epirawdma.c`, `epirawwrite.c`, `sptask.c`, `vi.c`, `vimgr.c`, `vitbl.c`, `vimodepallan1.c`, `aisetnextbuf.c`, 64DD (`leodiskinit.c`, `leointerrupt.c`), and one unnamed `ultra80069080.c`
  - libc: `xprintf.c`
  - os: `destroythread.c`, `initialize.c`
- About 173 library files are linked in total, listed explicitly in `src/libultrare/Makefile.libultrare`.

**For KI Gold:**
1. Read the libultra version letter from the ROM header (`python3 tools/romcheck.py` prints it). If it's earlier than G, expect small differences.
2. Fingerprint the standard libultra functions first (gu math, pi, si, sp, vi, ai, audio library). These are the easiest wins.
3. Then compare against the `libultrare` versions. If KI Gold matches Rare's modified copies, that proves shared in-house code.

## Compression: Rare "1172"

- Format: 2-byte header `11 72`, then a **raw deflate stream** (gzip output with the gzip header and trailer stripped).
- Decompressor in the game is a modified copy of Mark Adler's public-domain `inflate.c` from gzip 1.2.4 (`src/inflate/inflate.c`).
- GoldenEye recompresses with a decomp-built gzip (`tools/gzipsrc`) at `--best` to get byte-identical output.

**For KI Gold:** `python3 tools/scan_rom.py` searches the ROM for `11 72` blocks and test-inflates each one. If it finds valid blocks, the same format is in use. If it finds none, look for a different or earlier scheme.

## Microcode

- GoldenEye's repo has `rsp/rspboot.s` and `rsp/graphics/gmain.s` (graphics microcode source).
- **For KI Gold:** `python3 tools/scan_rom.py` lists microcode name strings found in the ROM. That answers the biggest open risk in `PLAN.md`.

## Build structure worth copying

- Explicit per-file lists of library objects, split into "original" vs "Rare modified".
- `COMPARE` build option that checks the ROM's SHA1 after building.
- `IDO_RECOMP` option so no IRIX emulation is needed.
- A `context` target that preprocesses headers into one file for decomp.me and m2c.

## Not checked yet

- Banjo-Kazooie decomp's compiler and libultra version ([GitLab](https://gitlab.com/banjo.decomp/banjo-kazooie)). Worth a look once KI Gold's libultra version is known.
