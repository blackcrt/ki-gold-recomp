# Session notes

Newest entries at the top. Each entry: what was done, what's stuck, what's next.

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
