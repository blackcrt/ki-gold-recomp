# KI Gold Recomp: Project Plan

**Status:** Phase 2 (First boot) in progress, started 2026-10-10. Phase 1 done (2026-10-10).
**Last updated:** 2026-10-10

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
| 0: Setup | Set up WSL (Ubuntu, Claude Code, git); add Visual Studio Build Tools on Windows; clone the repo to `C:\src`; ROM checked and hash recorded. The local model (Ollama) is deferred | Guard blocks a test ROM; `romcheck` passes |
| 1: Recon | Scan for microcode and compression; splat split; identify libultra by fingerprinting against GoldenEye; generate the first symbol file | **Go/no-go:** microcode is supported by RT64 (or a plan exists for it) and the symbol file covers the whole game |
| 2: First boot | Build N64Recomp and RSPRecomp; write the recomp config; set up the post-regen cleanup pipeline; build the port; chase crashes one at a time | Boots past the Rare logo to the title screen |
| 3: Playable | Input, audio, saves, rumble; test every fighter, stage, and mode | Full arcade run with no crashes; versus mode works |
| 4: Modernize | Patches toolchain, then the feature list easiest first; high refresh rate last | Every feature BlackCRT wants is in, or consciously dropped |
| 5: Polish and publish check | Clean build from a fresh clone using only the README; your own cartridge dump works | Both pass |
| 6: Optional | Partial decomp of systems a feature needs (for example, the HUD or camera) | BlackCRT's call |

### Phase 0 checklist (done 2026-10-08)

- [x] Follow `docs/SETUP.md` on the Windows PC (Parts 1, 3, 4, 5 done; Part 2, the Windows build tools, was deferred to the start of Phase 2 as planned and done 2026-10-10)
- [x] Create the private GitHub repo (done 2026-10-08)
- [x] Guard hook on, and it blocks a test commit of the ROM (blocked a forced ROM commit with 6 reasons; the GitHub Actions guard also passed)
- [x] `python3 tools/romcheck.py` passes and the SHA1 is recorded in `tools/rom.sha1`
- [ ] Ollama and Qwen2.5-Coder 14B installed and sanity checked. **Deferred:** skipped on purpose, see the decisions log

### Phase 1 checklist (done 2026-10-10)

- [x] `python3 tools/scan_rom.py`: identify graphics and audio microcode. Done 2026-10-08: graphics is stock Fast3D (RT64 entry `F3D_SDK_E`, matched by hash on code and data, supported); audio is the standard Nintendo audio microcode (see `NOTES.md`, session 6)
- [x] `python3 tools/scan_rom.py`: check for Rare 1172 compression (compressed code needs a decompressed ROM before N64Recomp can read it)
- [x] `python3 tools/unpack_rom.py`: build the decompressed ROM in `build/` (original ROM plus the three inflated code streams)
- [x] Generate a splat config in `disasm/` and get a clean split (`disasm/kigold.yaml`; the run is clean, but about half of stream3's code comes out as raw words and needs symbol work, see `NOTES.md`)
- [x] Fingerprint libultra against GoldenEye's `libultra` and `libultrare` (see `docs/GOLDENEYE.md`); the runtime replaces these functions, so they must be identified. Done 2026-10-08 against ultralib 2.0I and GoldenEye's version G and `libultrare`: 219 exact matches, 54 of 116 `reimplemented_funcs` named (see `NOTES.md`). The fingerprint run is finished, the identification is not: the rest moves to the next line. The 2.0D lead is still not confirmed
- [x] Identify remaining OS core functions by hand. Done 2026-10-08: start-up, Pi and Vi managers, and the exception handler group are named (see `NOTES.md`, sessions 4 and 5). 55 of 116 `reimplemented_funcs` named; the rest look absent from the game or are too small to prove
- [x] Generate the symbol file N64Recomp reads (`syms/`). Done 2026-10-08: `tools/gen_symbols.py` writes `syms/dump.toml` (4 sections, 907 functions) and N64Recomp reads it without errors. Boot, stream1 and stream2 are fully covered; only 45% of stream3's code is in functions (see `NOTES.md`, session 7) **Update 2026-10-10:** stream3's functions now come from the tracer (`tools/stream3_map.py`): 1442 functions in all, stream3 613, every byte of stream3's code area is in a function or in one of 31 known tables (see `NOTES.md`, session 2, task 2c)
- [x] Go/no-go: write findings to `NOTES.md` and confirm the plan. Done 2026-10-10: go for Phase 2, approved by BlackCRT. The write-up is the next section; `NOTES.md` has a short entry that points to it

### Phase 1 go/no-go (2026-10-10)

**Recommendation: GO for Phase 2.**

The gate was: the microcode is supported by RT64, and the symbol file covers the whole game. Both are met. Everything in this section is from reading and translating the ROM. Nothing has been compiled or run yet, so each verdict means "ready to try", not "works".

| Part | Verdict | Why |
| --- | --- | --- |
| Microcode | Go | Graphics is stock Fast3D, RT64 entry `F3D_SDK_E`, matched by hash on code and data. Audio is the standard Nintendo audio microcode, not Rare's modified one |
| boot | Go | 119 functions, 90 named, all code covered. No stubs since `__osGetCause` was named |
| stream1 | Go | 459 functions, 159 named, all code covered. 1 stub (`func_80030EF0`) |
| stream2 | Go | 251 functions, all code covered, 0 stubs. Only 1 function named, which is fine for a recomp |
| stream3 | Go, with known work | 613 functions from the tracer, every byte is in a function or one of 31 tables, 605 translate. Hand-written assembly that breaks normal calling rules: this is where most Phase 2 fixes will land |
| Symbol file | Go | `syms/dump.toml`: 4 sections, 1442 functions, 251 names. N64Recomp reads it and finishes with exit 0 and 9 stubs |

**Why go:** no blocker was found, and the open problems are all the kind that only a build can answer. More recon would not shrink them. stream3 has a chosen approach (option A, WM2K style) and a fallback (option B).

**Known risks going into Phase 2**

| Risk | What we know | Plan |
| --- | --- | --- |
| Nothing compiled or run | "Translates" only means N64Recomp produced C | Get to a first compile and link early, before polishing anything |
| 9 stubs | `func_80030EF0` in stream1 (branches into the middle of the next function), and 8 in stream3: 5 hand-made jump tables, 2 that read the Count register, 1 with a stack offset N64Recomp rejects | A stub is an empty function. Fix each when the game reaches it |
| stream3 fall-throughs | 243 functions run off their end into the next one. N64Recomp makes the C function simply return, with no warning. Silent miscompile | Cleanup script that chains each one into the next function, with a known-answer test. **Done 2026-10-10:** `tools/fix_fallthroughs.py` fixes 235 on every regeneration (239 before the task 4b split fix) |
| stream3 cross-function loops | 169 functions in 14 loop groups (largest 95). Each loop becomes a call then `return`, so a loop turns into recursion | Check whether clang-cl makes these real jumps. If not, the stack grows and it needs a cleanup step |
| 86 mid-function table addresses | Three inline tables point into the middle of functions. They sit beside the 5 jump-table stubs | Decide together with those 5 stubs: the fix for the dispatch decides whether the 86 become function starts |
| `__osGetCause_recomp` link question | The generated C calls it 6 times from 3 unnamed functions, and N64Recomp writes no body for it. Not checked whether the runtime provides it | Name the 3 callers first (`func_80005D98`, `func_80005E58`, `func_80006190`). If they are libultra internals, the calls disappear. **Update 2026-10-10:** they are libultra's debug link code, but naming alone does not remove the calls. Stub the debug link functions in the recomp config (Phase 2 checklist, task 3). **Closed 2026-10-10:** stubbed in `kigold.toml`, 0 calls left. The same question is open for 9 other names (43 calls), listed in `NOTES.md` |
| Dropped delay slots in stream3 | Found 2026-10-10. 3 functions end on a branch or `jr ra` whose delay slot is the first instruction of the next function, and N64Recomp drops that instruction: `func_801BFFF0_stream3`, `func_801C0150_stream3` (both `bnel`) and `func_801C0BF4_stream3` (`jr ra`, loses `addiu sp, sp, 0x10`). Silent miscompile | **Fixed 2026-10-10 (task 4b).** Two tracer bugs in `tools/stream3_map.py` made false function starts on delay slots (a stale `lui` pairing, and table bases counted as code pointers). Nothing jumps there. stream3 is now 605 functions (was 613). `tools/regen.py` stops if any function ends on a branch or jump again |
| TLB mapping | Found 2026-10-10 (task 3b). The game maps per-fighter data blocks (ROM table entries 3 to 13) at virtual `0x00010000` to `0x000BA000` plus page 0, from `func_8001CF5C` and `func_801C57B0_stream2`, physical `0x1DB000` to `0x1EEFFF`. Data only. N64Recomp and N64ModernRuntime have no TLB support, so the first read of a mapped address crashes | With the project skeleton and first link: start with `osMapTLB_recomp` and `osUnmapTLB_recomp` versions that log their arguments, then add real mapping. Open: Windows 4 KB mapping alignment (the physical slots are not 64 KB aligned), whether a copy approach is safe, `osVirtualToPhysical` on mapped addresses. References: Gauntlet Legends recomp `src/tlb.cpp`, BM64TSARecomp `src/game/tlb.cpp` |
| 61 unnamed libultra functions | 55 of 116 `reimplemented_funcs` are named. The rest look absent or too small to prove. An unnamed one gets translated as game code instead of replaced by the runtime | Expect some early crashes in hardware access code. Name each one as the crash points to it |

Smaller open items: 1,344 bytes of stream3 code in 144 pieces that nothing reaches (may be dead; the number is from `tools/stream3_map.py`, and the 1,300 in the `NOTES.md` 2b report is the old throwaway tracer, which reached 44 more bytes through splat's labels), stream1's 30 entry labels around `0x80031028`, RT64 marks `F3D_SDK_E` as "needs confirmation", the audio microcode size is measured and not confirmed, and what stream3 does in the game is still unknown.

### Phase 2 checklist (started 2026-10-10)

This is the suggested order from the go/no-go. It can change as the build teaches us things.

- [x] Windows build tools (`docs/SETUP.md` Part 2, deferred from Phase 0). Done 2026-10-10
- [x] Name the 3 callers of `__osGetCause`. Done 2026-10-10: one is proven and named (`__osSyncPutChars` at `0x80006190`); the other two are the debug link code in `kdebugserver.c`, in an older version than any reference we have, so they stay unnamed. Naming does not close the link question, stubs will (see `NOTES.md`)
- [x] Real recomp config in the repo (replaces the throwaway ones in `build/`), with the 9 stubs listed and a reason for each. Add the debug link functions as stubs here. Done 2026-10-10: `kigold.toml` with 12 stubs, regenerated by `python3 tools/regen.py`. `__osGetCause_recomp` calls are 0. 9 other names have no body and are not on N64Recomp's reimplemented list (see `NOTES.md`)
- [x] Fall-through cleanup script and its test. First, because it is the one silent problem. Done 2026-10-10: `tools/fix_fallthroughs.py`, step 5 of `tools/regen.py`, 239 fixed (235 after task 4b). It also found a second silent problem: 3 functions lost a delay slot instruction. Fixed in the tracer the same day (task 4b, see the risks table)
- [ ] RSPRecomp config for the audio microcode
- [ ] Project skeleton from the WM2K template, then first compile and link. Fix what the linker reports
- [ ] First run. Chase crashes one at a time. Check the cross-function loops here
- [ ] The 8 stream3 stubs and the 86 table addresses, when the game reaches them. This may come sooner than its place in the list: stream1 calls into stream3 at `0x8000FEF0`, near the start of stream1, which hints that stream3 runs early. Not checked

## AI workflow

- **Claude Code (engineer):** runs the build, reads crash logs, traces them to a function, and fixes them with config changes, stubs, cleanup scripts, or patches.
- **Local model (intern):** deferred. Claude Code does this work for now (suggest function names, summarize unfamiliar functions, draft notes). If added later: Ollama + Qwen2.5-Coder 14B on a local GPU.
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
| Ollama + Qwen2.5-Coder 14B | Local bulk worker. Deferred; Claude Code does this work for now | Later, if needed |
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
| Custom graphics microcode RT64 doesn't support | **Cleared 2026-10-08:** stock Fast3D, in RT64's table as `F3D_SDK_E`. Still to prove by rendering in Phase 2 |
| Custom audio microcode | **Cleared 2026-10-08:** standard Nintendo audio microcode. RSPRecomp run is still to do in Phase 2 |
| Rare 1172 compression on code | Decompress before recompiling; GoldenEye's tools document the format |
| Silent miscompiles (jump tables, overlapping functions, shared code tails) | WM2K's cleanup scripts are a ready-made map of what to check |
| High refresh rate fights the engine | Ship everything else first; high refresh is last on purpose |
| Claude usage limits | Pace sessions; the local model is deferred, so set it up if limits become a problem |
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
| 2026-10-08 | Ollama (local model) skipped on purpose. Claude Code does that work instead; revisit only if usage limits become a problem |
| 2026-10-08 | Decompressed ROM layout: keep the original 12 MB unchanged and append the three inflated code streams after it (from 0xC00000). The game still reads its data streams from their original offsets, so nothing else moves. Built by `tools/unpack_rom.py`, never committed |
| 2026-10-10 | stream3 (hand-written assembly with tables between routines): **option A, WM2K style**. Its function list comes from tracing the code (`tools/stream3_map.py`), and what N64Recomp gets wrong is fixed by cleanup scripts and config in Phase 2 (fall-throughs, cross-function loops, the 8 stubbed functions). Option B (treat stream3 as one unit with custom translation) stays as the fallback |
