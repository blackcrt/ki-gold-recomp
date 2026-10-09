# Session notes

Newest entries at the top. Each entry: what was done, what's stuck, what's next.

## 2026-10-08: Phase 1 recon scan, game code is compressed

**Done**
- Extended `tools/scan_rom.py`: it now searches inside inflated 1172 streams for microcode strings, flags each stream as code or data by counting `jr ra` (the MIPS function return), and maps uncompressed code in 16 KB blocks.
- Added `tools/test_scan_rom.py`, a known-answer test on a synthetic ROM (ground rule 4). 14/14 checks pass.
- Scan results on the real ROM:
  - 69 Rare 1172 streams, 1,747,450 bytes compressed, 3,480,440 inflated, from 0x0121F60 to 0x0BF90B0. No gzip.
  - **Most game code is compressed.** Only 0x1000 to 0x9000 (32 KB, 118 `jr ra`) is uncompressed code, most likely the boot code that inflates the rest.
  - Three streams hold code: 0x0A94D70 (239,520 bytes inflated, 548 `jr ra`), 0x0B00DF0 (154,048 bytes, 130 `jr ra`), and 0x0AB5870 (953,152 bytes, 270 `jr ra`, so code mixed with a lot of data). The other 66 streams are data.
  - One microcode string, inside stream 0x0A94D70 near its end: an RSP software version 2.0D string dated April 1996. That is the original Fast3D generation, and it agrees with the libultra 2.0D value in the ROM header.
  - Rough function count from `jr ra`: about 1,070 (118 uncompressed, 948 compressed).

**Stuck / unknown**
- Audio microcode: no ID string (normal, audio microcode usually has none). Needs another method.
- The 2.0D string names the microcode generation, not the exact variant. Confirm when the game renders in RT64.
- 0x9000 to 0x0121F60 (about 1.1 MB) is neither code nor 1172 streams. Unknown data so far.
- Where each code stream loads in RAM. The boot code at 0x1000 should tell us.

**Next**
- Decide how to give N64Recomp uncompressed code: a tool that inflates the three code streams into a decompressed ROM. This comes before, or together with, the splat config.

## 2026-10-08: Phase 0 done

**Done** (following `docs/SETUP.md` with the coach)
- **Part 1, tools:** git, Python 3.14, gh (logged in as blackcrt), and Claude Code all confirmed. Set the global git `user.name` (BlackCRT) and the noreply email; neither was set before.
- **Part 3, repo:** cloned to `/mnt/c/src/ki-gold-recomp`. Set `core.hooksPath` and `core.fileMode`. Changed the remote URL to lowercase `blackcrt` to stop the "repository moved" message.
- **Part 4, ROM and guard:** `romcheck` passed: USA, V1.2, 12 MB, z64 byte order, entry point 0x80000400, header reports libultra 2.0D. SHA1 recorded and committed. The guard blocked a forced ROM commit (6 reasons). The GitHub Actions guard passed.
- **Part 5, recon tools:** `disasm/.venv` created, `requirements.txt` installed fine on Python 3.14, splat runs.
- **Part 6, Ollama:** skipped on purpose. Decision: Claude Code does that work instead; revisit only if usage limits become a problem.
- **Part 2, Windows build tools:** deferred to the start of Phase 2, as planned.

**Stuck / unknown**
- The libultra 2.0D value comes from the ROM header. It is a lead for the Phase 1 fingerprinting, not a confirmed version.
- Same Phase 1 unknowns as before: microcode, compression, function count.

**Next**
- Phase 1 (Recon), starting with `python3 tools/scan_rom.py` for microcode and Rare 1172 compression.

## 2026-10-08: Hybrid setup and coach workflow

**Done**
- Switched to a **hybrid setup**: Ubuntu in WSL is home base (Claude Code, git, Python tools, recompiler); Windows Build Tools only build the game `.exe`, started from WSL via PowerShell. Repo lives at `C:\src\ki-gold-recomp` (`/mnt/c/src/ki-gold-recomp`). No Docker.
- Adopted the **coach relay** workflow: a claude.ai coach chat plans each step, BlackCRT relays to Claude Code and pastes results back. `CLAUDE.md` now tells Claude Code to do only what's asked, explain commands, and end each task with a pasteable summary.
- Added `.gitattributes` (LF line endings) and `core.fileMode false` in the setup guide, so git on the C: drive doesn't report phantom changes.
- Rewrote `docs/SETUP.md` for the hybrid setup; it now starts by checking what's already installed.

**Next**
- Next: open a new coach chat in the claude.ai Project and say "Let's start Phase 0."

## 2026-10-08: Final direction is the recomp

**Done**
- BlackCRT made the final call: **recomp with modern features** (high res, widescreen, high refresh rate, QoL). Partial decomp only where a feature needs it.
- Studied the WM2K recomp's build pipeline (`docs/WM2K.md`). Key finding: the port build is native Windows (VS Build Tools with clang-cl, CMake, Ninja), so the project moved off WSL.
- Rewrote `PLAN.md`, `CLAUDE.md`, `README.md`, and `docs/SETUP.md` for a Windows, PowerShell recomp.
- Removed the decomp-only `Makefile` (with its IDO compiler download) and `tools/progress.py`. Both are in git history if the partial decomp ever needs them.
- Guard now also blocks recompiler output (`RecompiledFuncs/`, `RecompiledPatches/`, `rsp/*.cpp`). Pre-commit hook finds Python on Windows or Linux.
- `requirements.txt` now matches WM2K's recon toolset (splat, crunch64, n64img, pygfxd); verified it installs.
- Renamed the GitHub repo from `ki-gold-decomp` to **`ki-gold-recomp`** (GitHub redirects the old name). Setup guide updated.

**Stuck / unknown**
- Same Phase 1 unknowns: microcode, compression, libultra version, function count.
- Whether KI Gold's renderer works with RT64 frame interpolation (high refresh rate). Unknown until the game boots.

**Next**
- BlackCRT follows `docs/SETUP.md` on the Windows PC.
- First Phase 1 session: `python tools\romcheck.py`, then `python tools\scan_rom.py`.

## 2026-10-08: Planning and pre-recon research

**Done**
- Decided on a matching decomp as the main goal, recomp as optional.
- Wrote this starter kit: CLAUDE.md, PLAN.md, setup guide, guard, research notes.
- Created the private repo BlackCRT/ki-gold-decomp and pushed the kit.
- Pre-recon research from public sources (see `docs/RESEARCH.md`): GoldenEye's decomp is 100% matched, uses IDO 5.3 and a Rare-modified libultra, so it's our main reference.

**Stuck / unknown**
- Which graphics and audio microcode KI Gold uses. No public source found; check the ROM directly in Phase 1.
- Compression format and function count. Also Phase 1.

**Also done (same day, still pre-ROM)**
- GoldenEye reference notes (`docs/GOLDENEYE.md`): IDO 5.3, game code `-O2 -mips2`, libultra `-O1`, Rare's `libultrare` modified files, and the 1172 compression format.
- Phase 1 helpers: `make check` (ROM check and byte-order fix), `make scan` (microcode strings and 1172 streams), `make progress`. All tested on synthetic ROMs.
- Build skeleton: `Makefile`, `requirements.txt` (splat64 0.50.0). `make setup` downloads IDO 5.3 from ido-static-recomp v1.2; `make config` generates the first splat config and switches it to IDO.
- Retired the old Claude Docs plan page and the claude.ai Project copy. This repo is the only plan now.

**Next**
- BlackCRT follows `docs/SETUP.md` on the Windows PC when ready to start Phase 0.
- First Phase 1 session: `make check`, `make scan`, then `make config` and `make split`.
