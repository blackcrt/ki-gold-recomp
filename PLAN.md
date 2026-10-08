# KI Gold Recomp: Project Plan

**Status:** Phase 0 not started. Planning only until BlackCRT says go.
**Last updated:** 2026-10-08

## Goal

A native Windows PC port of Killer Instinct Gold (U) (V1.2), made by **static recompilation** with N64Recomp, rendered with RT64, and upgraded with **modern features**: high resolution, widescreen, high refresh rate, and quality-of-life fixes. Built by Claude Code with BlackCRT directing and playtesting.

Milestones, each useful on its own:

1. **First boot:** the recompiled game reaches the title screen on PC.
2. **Playable:** full matches with working input, audio, saves, and rumble.
3. **Modernized:** the feature list below, easiest first.
4. **Optional:** decompile only the systems a feature needs to change deeply.

## How it works (one paragraph)

splat maps out the ROM and gives every function an address and a name. N64Recomp reads the ROM plus that symbol list and translates every MIPS function into C. Cleanup scripts fix the cases N64Recomp gets silently wrong. The generated C is compiled together with N64ModernRuntime (replaces the N64's OS), RT64 (renders the N64's graphics commands on a modern GPU), and RecompFrontend (launcher, menus, input) into a Windows `.exe`. Modern features come from RT64 settings and from **patches**: small C replacements for specific game functions. This is the same pipeline as the [WrestleMania 2000 recomp](https://github.com/jessetbh/WWFWrestleMania2000Recomp); see `docs/WM2K.md`.

## Modern features

| Feature | How | Difficulty |
| --- | --- | --- |
| High resolution, anti-aliasing | Built into RT64 | Easy |
| Modern input: rebinding, keyboard, any controller, rumble | Built into RecompFrontend | Easy |
| Automatic saves | Built into the runtime | Easy |
| Settings menu (graphics, audio, controls) | Built into RecompFrontend | Easy |
| Widescreen 3D view (16:9, ultrawide) | RT64 "Expand" aspect mode | Easy to medium |
| Widescreen HUD and camera fixes | Patches: anchor health bars and text to screen edges, widen camera bounds | Medium |
| High-res texture packs | RT64 texture replacement; making the art is separate work | Easy (support), large (art) |
| Quality of life: skip intro logos, fast boot, pause when the window loses focus | Patches | Medium |
| **High refresh rate (120Hz, 144Hz and up)** | RT64 frame interpolation plus patches that tag the game's matrices, the approach Zelda64Recomp uses. Game logic stays at its original speed so gameplay timing is unchanged | **Hard.** WM2K hasn't solved this yet for its engine |

Patches need an extra toolchain (a MIPS-capable clang and make); we add it at the start of Phase 4.

## Phases

| Phase | Work | Gate to move on |
| --- | --- | --- |
| 0: Setup | Set up WSL (Ubuntu, Claude Code, git); add Visual Studio Build Tools and Ollama on Windows; clone the repo to `C:\src`; ROM checked and hash recorded | Guard blocks a test ROM; `romcheck` passes |
| 1: Recon | Scan for microcode and compression; splat split; identify libultra by fingerprinting against GoldenEye; generate the first symbol file | **Go/no-go:** microcode is supported by RT64 (or a plan exists for it) and the symbol file covers the whole game |
| 2: First boot | Build N64Recomp and RSPRecomp; write the recomp config; set up the post-regen cleanup pipeline; build the port; chase crashes one at a time | Boots past the Rare logo to the title screen |
| 3: Playable | Input, audio, saves, rumble; test every fighter, stage, and mode | Full arcade run with no crashes; versus mode works |
| 4: Modernize | Patches toolchain, then the feature list easiest first; high refresh rate last | Every feature BlackCRT wants is in, or consciously dropped |
| 5: Polish and publish check | Clean build from a fresh clone using only the README; your own cartridge dump works | Both pass |
| 6: Optional | Partial decomp of systems a feature needs (for example, the HUD or camera) | BlackCRT's call |

### Phase 0 checklist (when BlackCRT says go)

- [ ] Follow `docs/SETUP.md` on the Windows PC
- [x] Create the private GitHub repo (done 2026-10-08)
- [ ] Guard hook on, and it blocks a test commit of the ROM
- [ ] `python3 tools/romcheck.py` passes and the SHA1 is recorded in `tools/rom.sha1`
- [ ] Ollama and Qwen2.5-Coder 14B installed and sanity checked

### Phase 1 checklist

- [ ] `python3 tools/scan_rom.py`: identify graphics and audio microcode
- [ ] `python3 tools/scan_rom.py`: check for Rare 1172 compression (compressed code needs a decompressed ROM before N64Recomp can read it)
- [ ] Generate a splat config in `disasm/` and get a clean split
- [ ] Fingerprint libultra against GoldenEye's `libultra` and `libultrare` (see `docs/GOLDENEYE.md`); the runtime replaces these functions, so they must be identified
- [ ] Generate the symbol file N64Recomp reads (`syms/`)
- [ ] Go/no-go: write findings to `NOTES.md` and confirm the plan

## AI workflow

- **Claude Code (engineer):** runs the build, reads crash logs, traces them to a function, and fixes them with config changes, stubs, cleanup scripts, or patches.
- **Local model (intern):** Ollama + Qwen2.5-Coder 14B on a local GPU. Suggest function names, summarize unfamiliar functions, draft notes.
- **BlackCRT (director and playtester):** plays builds, describes what's broken, approves changes, decides what's next.
- **Rule:** nothing merges unless the game still boots and the guard passes.

### Ground rules

Adapted from finished recomp and decomp projects (WM2K, the [BFM decomp](https://github.com/Druthulu/BFM-decomp/wiki/Start-a-new-decomp-project), and [this write-up on agent-driven N64 work](https://blog.chrislewis.au/using-coding-agents-to-decompile-nintendo-64-games/)):

1. **The running game is the proof.** A fix counts when the build boots and plays past the problem, not when an agent says so.
2. **Run the full cleanup pipeline after every regeneration.** WM2K found that N64Recomp miscompiles some code silently; a skipped step can boot fine and corrupt itself later.
3. **Never hand-edit generated code.** Fix things in the config, a cleanup script, or a patch, so the fix survives regeneration.
4. **Test every tool against a known answer first.** A tool that finds nothing may be broken.
5. **Names need evidence.** Record the reason (a string, a libultra fingerprint, a GoldenEye match) in a comment.
6. **One change at a time.** Small, tested steps; keep previous attempts instead of overwriting them.

## Tools

| Tool | Job | Phase |
| --- | --- | --- |
| splat (+ spimdisasm, crunch64) | Map the ROM, generate symbols | 1 |
| N64Recomp, RSPRecomp | Translate game code and audio microcode to C | 2 |
| N64ModernRuntime, RT64, RecompFrontend | Runtime, renderer, launcher and menus | 2 |
| Ubuntu in WSL | Home base: git, Python tools, recon, recompiler | All |
| Visual Studio Build Tools 2022 (clang-cl, CMake, Ninja) | Build the Windows port (started from WSL via PowerShell) | 2 |
| MIPS-capable clang + make | Build patches | 4 |
| Claude Code | Main agent | All |
| Ollama + Qwen2.5-Coder 14B | Local bulk worker | All |
| ares or Mupen64Plus | Emulator to compare against the original | All |

## Working rhythm

- **Coach relay:** a claude.ai coach chat plans each step; BlackCRT tells Claude Code what to do and pastes results back. Start a fresh coach chat per phase; `NOTES.md` is the handoff.
- Short, frequent sessions. Each one ends with a commit.
- Track progress by milestones: how far the build gets (boots, menus, a match, each fighter and stage, each feature).
- When crash-chasing gets grindy, switch to a feature, tooling, or docs.
- A skipped week is fine. A dead project is the only failure.

## Risks

| Risk | Fallback |
| --- | --- |
| Custom graphics microcode RT64 doesn't support | Checked first in Phase 1; ask the RT64 community; scope as its own sub-project |
| Custom audio microcode | Same; audio can come after first boot |
| Rare 1172 compression on code | Decompress before recompiling; GoldenEye's tools document the format |
| Silent miscompiles (jump tables, overlapping functions, shared code tails) | WM2K's cleanup scripts are a ready-made map of what to check |
| High refresh rate fights the engine | Ship everything else first; high refresh is last on purpose |
| Claude usage limits | Pace sessions; push bulk work to the local model |
| Burnout | Rhythm rules above |
| Accidental commit of game data | `tools/guard.py` on every commit and in CI |

## Legal and repo hygiene

| Goes in the repo | Never goes in the repo |
| --- | --- |
| splat and recomp configs, symbol files | The ROM, in any byte order |
| Our patches, cleanup scripts, runtime code | Extracted assets (textures, audio, sprites, models) |
| Build scripts, CMake files, docs, notes | Generated code (`RecompiledFuncs/`, RSPRecomp output, split assembly) |
| The expected ROM SHA1 | Executables, DLLs, archives; leaked SDKs or Rare material; official logos |

Other rules: dump your own cartridge before going public, free forever, labeled as an unofficial fan project, repo private until BlackCRT chooses otherwise, source-only releases, comply with any takedown immediately.

## Decisions log

| Date | Decision |
| --- | --- |
| 2026-10-08 | Target ROM: Killer Instinct Gold (U) (V1.2), .z64 |
| 2026-10-08 | Plan lives in this repo (CLAUDE.md, PLAN.md, NOTES.md), not in outside docs |
| 2026-10-08 | Source-only releases; no prebuilt executables |
| 2026-10-08 | **Final direction: recomp with modern features** (high res, widescreen, high refresh rate, QoL). Replaces the earlier decomp-first plan; partial decomp only where a feature needs it |
| 2026-10-08 | Dropped the Makefile and IDO compiler (decomp-only tools) |
| 2026-10-08 | Hybrid setup: Ubuntu in WSL as home base, Windows build tools only for the game `.exe`, repo on `C:\src`. No Docker |
| 2026-10-08 | Coach relay workflow: claude.ai chat coaches, BlackCRT relays to and from Claude Code |
