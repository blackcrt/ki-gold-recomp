# WrestleMania 2000 recomp: how it's built (our template)

[WWFWrestleMania2000Recomp](https://github.com/jessetbh/WWFWrestleMania2000Recomp) is a working N64Recomp port of a 1999 N64 game with **no decomp**, which is exactly our situation. Studied 2026-10-08 from a shallow clone of `main`. Everything here is a lead to adapt, not something to copy blindly: KI Gold is a different engine.

## The pipeline

1. **Symbols** (`disasm/` + `syms/`): a splat project splits the ROM; a script turns splat's output into `syms/dump.toml`, the symbol file N64Recomp reads. libultra functions are identified by **fingerprinting** against a sister game and renamed, so the runtime can replace them.
2. **Recompile**: `N64Recomp.exe wm2k.toml` reads the ROM and the symbols and writes `RecompiledFuncs/` (about 19 MB of C). `RSPRecomp.exe rsp/wm2k_audio.toml` translates the audio microcode.
3. **Mandatory cleanup pipeline** after every regeneration, because N64Recomp silently gets some IDO-compiled code wrong:
   - `fix_stumps.py`: re-chains functions truncated at overlapping symbols (otherwise dropped epilogues corrupt the stack)
   - `fix_switches.py`: completes jump tables that cross function boundaries
   - `fix_backbranches.py`: finds branches outside a function's decoded range and adds missing entry points
   - `readd_hand_edits.py`: reapplies documented diagnostic edits that regeneration wipes
   - `audit_coresidency.py`: checks overlay functions for bad static binding
4. **Port build**: CMake + Ninja + **clang-cl** (Visual Studio Build Tools 2022) compile the generated C with the runtime stack into one `.exe`. MinGW can't replace clang-cl because RT64 needs the Windows SDK (D3D12/Vulkan).

## The recomp config (`wm2k.toml`)

- `[input]`: entry point (`0x80000400`), ROM path, symbol file, output folder.
- `stubs`: functions that use CPU instructions the recompiler can't translate (cop0, cache, TLB). They start as stubs and become proper renames as they're identified.
- `ignored`: functions the runtime provides instead.
- `[[patches.instruction]]`: single-instruction fixes, each with a written reason. Example: a busy-wait loop that never yields under the runtime's cooperative scheduler is rewritten so the thread pauses properly.

## Runtime libraries

`lib/` holds git submodules: forks of N64ModernRuntime, RecompFrontend, and RT64 on a `wcw` branch with fixes shared across the author's AKI wrestling ports. We start from upstream and only fork if KI Gold needs runtime changes.

## Lessons for KI Gold

- **Recon first, then symbols.** Their whole pipeline depends on a good symbol file, and the symbol file depends on identifying libultra. Our GoldenEye fingerprinting (`docs/GOLDENEYE.md`) is that step.
- **Expect silent miscompiles.** Budget time for a cleanup pipeline from day one; their scripts are a ready-made checklist of what to look for.
- **Their code wasn't compressed.** If `scan_rom.py` finds Rare 1172 compression on KI Gold's code, we add a decompression step before N64Recomp.
- **Debug tooling pays off.** They log to `%LOCALAPPDATA%\<game>\`, symbolize crash backtraces against the linker map, and gate extra logging behind environment variables (frame rate, audio, video interface).
- **Widescreen:** RT64's "Expand" aspect mode widens the 3D view while keeping 2D at original proportions. That worked for them out of the box.
- **High framerate:** disabled in WM2K. The game builds each frame from several RSP tasks and submits fully composed matrices, which defeats RT64's frame interpolation. Fixing it needs game-side matrix-group patches (the Zelda64Recomp approach), which they haven't done yet. KI Gold may or may not have the same problem.
- **No patches pipeline yet.** WM2K skips the MIPS clang + make toolchain because it has no C patches. We'll need that toolchain for widescreen HUD fixes and high refresh rate.
- **Keep the repo clean.** Their `.gitignore` excludes the ROM, `RecompiledFuncs/`, `rsp/*.cpp`, recompiler binaries, and splat output while keeping configs and symbol files. Ours follows the same pattern, enforced by `tools/guard.py`.
