# KI Gold Decomp: Project Plan

**Status:** Phase 0 not started. Planning only until BlackCRT says go.
**Last updated:** 2026-10-08

## Goal

A matching decompilation of Killer Instinct Gold (U) (V1.2): readable C that rebuilds the exact ROM. Built by Claude Code with BlackCRT directing and testing.

Milestones, each useful on its own:

1. **Shiftable build:** the ROM rebuilds byte-identical from split assembly.
2. **Matching decomp:** all game code in C, still byte-identical.
3. **Optional side quests:** an N64Recomp playable build (can start any time after Phase 1), and later a native PC port with widescreen, texture packs, and PC settings.

## Why we think this is doable

- The [Silent Hill 2 decomp](https://github.com/oohweee/sh2-decomp) reached about 97% matching in roughly a week, written by Claude Code and Codex. It had a big head start (a finished prototype decomp with debug info) and a huge compute budget, so we expect months, not a week.
- The [GoldenEye 007 decomp](https://github.com/n64decomp/007) is 100% matched as of August 2026. It's a Rare N64 game from the same era, built with IDO 5.3, and it includes a Rare-modified libultra. That's our best reference and fingerprint source.
- KI Gold is a 12 MB cart. Its code is likely smaller than SH2's (about 5,000 functions). Exact count comes from recon.

See `docs/RESEARCH.md` for details and sources.

## Phases

| Phase | Work | Gate to move on |
| --- | --- | --- |
| 0: Setup | WSL2, toolchain, Claude Code, Ollama, private repo, guard installed, ROM hash recorded | Guard blocks a test ROM; tools run |
| 1: Recon | Split the ROM with splat; find compression; count functions; identify compiler, libultra, and microcode | **Decomp checkpoint:** compiler confirmed and one function matches |
| 2: Shiftable build | Rebuild the whole ROM from split assembly, data, and assets | SHA1 matches on every build |
| 3: Free wins | Fingerprint libultra, Rare libultra changes, and audio code against GoldenEye and Banjo-Kazooie | All library code identified and matched |
| 4: Matching grind | AI matching loop over game code, easiest functions first | 100% of game code in C, SHA1 still matches |
| 5: Optional | Recomp playable build, native port, enhancements | BlackCRT's call |

### Phase 0 checklist (when BlackCRT says go)

- [ ] Follow `docs/SETUP.md` on the Windows PC
- [ ] Record the ROM's SHA1 in `tools/rom.sha1`
- [x] Create the private GitHub repo and push this starter kit (done 2026-10-08)
- [ ] Install the guard hook and confirm it blocks the ROM
- [ ] Install Ollama and Qwen2.5-Coder 14B and sanity check it

### Phase 1 checklist

- [ ] Write the first splat config and get a clean split
- [ ] Search the ROM for microcode name strings (for example "F3DEX", "RSP Gfx ucode") to identify graphics and audio microcode
- [ ] Identify compression on code and data (Rare used its own inflate-based compression in other games)
- [ ] Fingerprint libultra against GoldenEye's `libultra` and `libultrarare`
- [ ] Confirm the compiler (IDO 5.3 is the working guess) by matching one small function
- [ ] Count functions and estimate the size of the job
- [ ] Decomp checkpoint: write findings to `NOTES.md` and confirm the plan

## AI workflow

- **Claude Code (matcher):** per function, take m2c's first pass, write C, build, diff with objdiff, adjust, repeat. Cap attempts; log near-misses.
- **decomp-permuter (night shift):** grinds near-misses overnight on the CPU. Costs no Claude usage.
- **Local model (intern):** Ollama + Qwen2.5-Coder 14B on a local GPU. Triage difficulty, suggest names, draft comments.
- **BlackCRT (director):** picks batches, reviews merges, tests builds in an emulator, makes naming and structure calls.
- **Rule:** nothing merges unless the full ROM still rebuilds with a matching SHA1 and the guard passes.

## Tools

| Tool | Job |
| --- | --- |
| splat / spimdisasm | Split the ROM into code, data, assets |
| IDO 5.3 (via ido-static-recomp) | Original compiler, confirm in Phase 1 |
| binutils-mips-linux-gnu | Assemble and link |
| m2c | First-pass C from assembly |
| objdiff | Compare compiled functions with the target |
| decomp-permuter | Brute-force near-matches |
| decomp.me | Web scratchpad for stubborn functions |
| Claude Code | Main agent |
| Ollama + Qwen2.5-Coder 14B | Local bulk worker |
| ares or Mupen64Plus | Emulator for testing builds |

## Working rhythm

- Short, frequent sessions. Each one ends with a commit.
- Kick off permuter runs or local-model batches before bed or work.
- Track progress weekly: percent of functions matched, and percent of code bytes.
- When matching gets grindy, switch to tooling, docs, or a side quest.
- A skipped week is fine. A dead project is the only failure.

## Risks

| Risk | Fallback |
| --- | --- |
| Compiler can't be reproduced | Non-matching decomp, or switch to recomp as the main goal |
| Custom compression or packed code | Write a decompressor early; check Rare reference decomps |
| Code ported from the arcade version behaves oddly | The KI2 arcade board also used a MIPS CPU (R4600); some code may be adapted from it. Treat as a hypothesis until recon |
| Hard functions stall progress | Skip and return; use decomp.me; accept a few flagged non-matching functions |
| Claude usage limits | Pace sessions; push bulk work to permuter and local model |
| Burnout | Rhythm rules above |
| Accidental commit of game data | `tools/guard.py` on every commit and in CI |

## Legal and repo hygiene

| Goes in the repo | Never goes in the repo |
| --- | --- |
| splat config, symbol files, linker scripts | The ROM, in any byte order |
| Our C source and headers | Extracted assets (textures, audio, sprites, models) |
| Build scripts, tools, Makefiles | Split assembly, generated C, binary blobs |
| Docs, notes | Prebuilt executables containing game code |
| The expected ROM SHA1 | Leaked SDKs or Rare material; official logos |

Other rules: dump your own cartridge before going public, free forever, labeled as an unofficial fan project, repo private until BlackCRT chooses otherwise, comply with any takedown immediately.

## Decisions log

| Date | Decision |
| --- | --- |
| 2026-10-08 | Target ROM: Killer Instinct Gold (U) (V1.2), .z64 |
| 2026-10-08 | Decomp is the main goal; recomp is an optional side quest |
| 2026-10-08 | Plan lives in this repo (CLAUDE.md, PLAN.md, NOTES.md), not in outside docs |
| 2026-10-08 | Source-only releases; no prebuilt executables |
