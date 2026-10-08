# KI Gold Decomp: instructions for Claude Code

Read this first every session. Then read `PLAN.md` for the full plan and the latest entries in `NOTES.md` for where we left off.

## The project

A solo, AI-assisted **matching decompilation** of Killer Instinct Gold (N64, Rare, 1996), US V1.2. Goal: readable C that rebuilds a byte-identical ROM. A recomp or PC port can come later, built on the same groundwork.

- Owner: BlackCRT. sets goals, makes decisions, and tests. Claude writes and matches the code.
- Spend usage on the hard parts; push bulk work to the local model and the permuter.
- Current phase: see the status line at the top of `PLAN.md`.

## How to work with BlackCRT

- Explain every command before it is run: what it does and why. Assume nothing about Linux or git.
- Keep answers short and simple. Lead with what to do next.
- Never use em dashes in anything you write: chat, docs, code comments, commit messages.
- Ask before anything that can't be undone (deleting files, rewriting git history, force pushes).

## Legal rules (non-negotiable)

Every commit must contain only our own original work.

- Never commit the ROM, extracted assets, split assembly, generated C, binary blobs, or prebuilt executables.
- Never use leaked SDKs, leaked Rare material, or anything from Nintendo/Rare internal sources.
- Generated and extracted files live only in git-ignored folders (`build/`, `asm/`, `assets/`, `bin/`, `expected/`).
- The guard (`tools/guard.py`) runs on every commit and in GitHub Actions. Never bypass it with `--no-verify`. If it blocks something, the fix is to not commit that file.
- The ROM file is `baserom.us.z64` in the repo root, git-ignored. Never copy it anywhere else or print its bytes.

## Session habits

1. At the start: read the latest `NOTES.md` entry and the current phase in `PLAN.md`.
2. Keep work small enough that each session ends with a commit.
3. At the end: add a dated entry to `NOTES.md` (what was done, what's stuck, what's next) and tick any finished boxes in `PLAN.md`.
4. Commit messages: short, plain, present tense ("Match func_80001234", "Add splat config for code segment").

## Key files

| File | Purpose |
| --- | --- |
| `PLAN.md` | Phases, gates, checklists, decisions |
| `NOTES.md` | Dated session log |
| `docs/SETUP.md` | Phase 0 setup guide for the Windows PC |
| `docs/RESEARCH.md` | Pre-recon findings and sources |
| `docs/GOLDENEYE.md` | What to borrow from the GoldenEye decomp (compiler, libultra, compression) |
| `Makefile` | All commands; run `make` to list them |
| `tools/guard.py` | Legal guard: blocks ROMs, binaries, big files |
| `tools/romcheck.py` | Checks the ROM (`make check`), converts byte order |
| `tools/scan_rom.py` | Recon scan for microcode and compression (`make scan`) |
| `tools/progress.py` | Matched-code progress (`make progress`) |
