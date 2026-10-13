# KI Gold Recomp: instructions for Claude Code

Read this first every session. Then read `PLAN.md` for the full plan and the latest entries in `NOTES.md` for where we left off.

## The project

A solo, AI-assisted **static recompilation** of Killer Instinct Gold (N64, Rare, 1996), US V1.2, into a native Windows PC port, using N64Recomp, N64ModernRuntime, RT64, and RecompFrontend. The headline goal is **modern features**: high resolution, widescreen, high refresh rate, and quality-of-life fixes. Modeled on the WrestleMania 2000 recomp (`docs/WM2K.md`).

- Owner: BlackCRT. sets goals, makes decisions, and playtests. Claude does the engineering.
- The local model is deferred, so Claude Code does the bulk work for now; keep usage lean.
- Current phase: see the status line at the top of `PLAN.md`.

## Platform (hybrid)

- **Home base is Ubuntu in WSL.** You (Claude Code) run in the Ubuntu terminal. Use bash and Linux tools for git, Python, recon, splat, and N64Recomp.
- **The repo is on the C: drive:** `/mnt/c/src/ki-gold-recomp` from Ubuntu, `C:\src\ki-gold-recomp` from Windows. Never move it into the Linux home folder; the Windows build needs to reach it.
- **The game build is Windows-only** (Phase 2 onward). Visual Studio Build Tools 2022 (clang-cl, CMake, Ninja) build the `.exe`. Start Windows builds from Ubuntu through `powershell.exe` calling a script in the repo, using Windows paths (`C:\src\...`).
- BlackCRT plays and tests the `.exe` on Windows.
- No Docker.

## How BlackCRT works with you (coach relay)

BlackCRT runs a **coach chat** in claude.ai alongside you. The coach plans each step and says what to ask you; BlackCRT relays your results back to the coach. So:

- **Do what was asked, then stop.** Don't jump ahead to extra tasks or the next phase. If you see a better next step, suggest it instead of doing it.
- **End every task with a short summary that can be pasted back:** what you did, commands you ran and their results, files changed, anything that needs a decision. Plain language, no walls of output.
- **Explain every command before running it:** what it does and why, so nothing gets committed that isn't understood.
- Keep answers short and simple. Lead with what happened and what's next.
- Never use em dashes in anything you write: chat, docs, code comments, commit messages.
- Ask before anything that can't be undone (deleting files, rewriting git history, force pushes).


## Usage habits

- Suggest `/clear` between unrelated tasks; long contexts burn allowance fast.
- Don't read large files or generated code (for example `RecompiledFuncs/`) unless the task needs them; search first.

## Legal rules (non-negotiable)

Every commit must contain only our own original work.

- Never commit the ROM, extracted assets, split assembly, generated code (`RecompiledFuncs/`, `RecompiledPatches/`, `rsp/*.cpp`), binary blobs, executables, or DLLs.
- Never use leaked SDKs, leaked Rare material, or anything from Nintendo/Rare internal sources.
- The guard (`tools/guard.py`) runs on every commit and in GitHub Actions. Never bypass it with `--no-verify`. If it blocks something, the fix is to not commit that file.
- The ROM file is `baserom.us.z64` in the repo root, git-ignored. Never copy it anywhere else or print its bytes.
- Releases are source only. Users build from their own ROM.

## Recomp rules

Follow the six ground rules in `PLAN.md` (AI workflow section). The short version: the running game is the only proof a fix works, run the full cleanup pipeline after every regeneration, never hand-edit generated code, and never invent names without evidence.

## Session habits

1. At the start: read the latest `NOTES.md` entry and the current phase in `PLAN.md`.
2. Keep work small enough that each session ends with a commit.
3. At the end: add a dated entry to `NOTES.md` (what was done, what's stuck, what's next) and tick any finished boxes in `PLAN.md`.
4. Commit messages: short, plain, present tense ("Stub func_80001234", "Add splat config").

## Key files

| File | Purpose |
| --- | --- |
| `PLAN.md` | Goal, modern features list, phases, gates, decisions |
| `NOTES.md` | Dated session log |
| `docs/SETUP.md` | Phase 0 setup guide for the Windows PC (WSL + Windows build tools) |
| `docs/WM2K.md` | How the WrestleMania 2000 recomp is built; our template |
| `docs/GOLDENEYE.md` | GoldenEye decomp notes: libultra identification and Rare compression |
| `docs/RESEARCH.md` | Pre-recon findings and sources |
| `tools/guard.py` | Legal guard: blocks ROMs, generated code, binaries, big files |
| `tools/romcheck.py` | Checks the ROM, converts byte order |
| `tools/scan_rom.py` | Recon scan for microcode and Rare compression |
| `tools/unpack_rom.py` | Builds the decompressed ROM for splat and N64Recomp (output in `build/`, never committed) |
| `kigold.toml` | N64Recomp config: ROM, symbol file, output folder, and the stub list with a reason for each |
| `rsp/kigold_audio.toml` | RSPRecomp config for the audio microcode. Its output `rsp/kigold_audio.cpp` is generated, never committed |
| `tools/regen.py` | Regenerates `RecompiledFuncs/` and `rsp/kigold_audio.cpp` in one command (unpack check, split, symbols, N64Recomp, cleanup, RSPRecomp, report) |
| `tools/fix_fallthroughs.py` | Cleanup step: chains functions that fall through into the next one. Run by `regen.py` |
| `lib/` | Git submodules: N64ModernRuntime, RecompFrontend, rt64, at fixed pins. Never edit or copy files from here. Fresh clone: `git submodule update --init --recursive --depth 1` |
| `CMakeLists.txt` | Build file for the Windows port (adapted from WM2K) |
| `tools/build.ps1` | Loads the x64 clang-cl environment and runs CMake. From Ubuntu: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\src\ki-gold-recomp\tools\build.ps1'` (add `-Build` to compile). Output in `build-msvc/`, never committed |
| `src/main/main.cpp` | Program start: describes the game to the runtime, sets up window, sound, input, then starts it |
| `src/main/register_overlays.cpp` | Hands the generated code section table to the runtime |
| `src/game/tlb.cpp` | `osMapTLB` and `osUnmapTLB` for the runtime. Log only for now |
| `src/game/missing_funcs.cpp` | Loud log-only bodies for the 5 libultra names the runtime does not provide |
| `src/game/inflate_hooks.cpp` | Tells the runtime when the game has inflated code stream 1, 2 or 3. Called from generated code through the `[[patches.hook]]` entries in `kigold.toml`. Developer check: set `KIGOLD_VERIFY_INFLATE` to the path of `build/kigold.decompressed.z64` |
| `include/kigold_decls.h` | Declarations shared by our source files |
| `patches/ui_funcs.h` | Header RecompFrontend expects in the game project. Do not delete; the build fails without it |
| `COPYING` | The license: GPL-3.0 |
| `requirements.txt` | Python tools for recon (splat), installed into `disasm/.venv` |
| `.gitattributes` | Keeps line endings consistent between Ubuntu and Windows |
