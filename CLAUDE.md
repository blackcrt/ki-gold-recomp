# KI Gold Recomp: instructions for Claude Code

Read this first every session. Then read `PLAN.md` for the full plan and the latest entries in `NOTES.md` for where we left off.

## The project

A solo, AI-assisted **static recompilation** of Killer Instinct Gold (N64, Rare, 1996), US V1.2, into a native Windows PC port, using N64Recomp, N64ModernRuntime, RT64, and RecompFrontend. The headline goal is **modern features**: high resolution, widescreen, high refresh rate, and quality-of-life fixes. Modeled on the WrestleMania 2000 recomp (`docs/WM2K.md`).

- Owner: BlackCRT. sets goals, makes decisions, and playtests. Claude does the engineering.
- Spend usage on the hard parts; push bulk work to the local model.
- Platform: native Windows, PowerShell. The port build needs Visual Studio Build Tools (clang-cl, CMake, Ninja).
- Current phase: see the status line at the top of `PLAN.md`.

## How to work with BlackCRT

- Explain every command before it is run: what it does and why. Give PowerShell commands, not bash, unless there's a reason.
- Keep answers short and simple. Lead with what to do next.
- Never use em dashes in anything you write: chat, docs, code comments, commit messages.
- Ask before anything that can't be undone (deleting files, rewriting git history, force pushes).

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
| `docs/SETUP.md` | Phase 0 setup guide for the Windows PC (Windows) |
| `docs/WM2K.md` | How the WrestleMania 2000 recomp is built; our template |
| `docs/GOLDENEYE.md` | GoldenEye decomp notes: libultra identification and Rare compression |
| `docs/RESEARCH.md` | Pre-recon findings and sources |
| `tools/guard.py` | Legal guard: blocks ROMs, generated code, binaries, big files |
| `tools/romcheck.py` | Checks the ROM, converts byte order |
| `tools/scan_rom.py` | Recon scan for microcode and Rare compression |
| `requirements.txt` | Python tools for recon (splat), installed into `disasm\.venv` |
