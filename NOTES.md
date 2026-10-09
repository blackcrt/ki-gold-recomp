# Session notes

Newest entries at the top. Each entry: what was done, what's stuck, what's next.

## 2026-10-08: libultra fingerprint tool and reference build (session 1 of 2)

**Done**
- Added `tools/build_libultra_ref.py`. It fetches pinned copies of `decompals/ultralib` (the public libultra decompilation), N64Recomp (only for its function lists), and IDO 5.3 (ido-static-recomp v1.2) into `build/ref/`, then compiles every ultralib source file with the flags from ultralib's own Makefile. Result: 477 of 477 files compile, in two variants (`ultralib_2.0I_rom` with `_FINALROM`, `ultralib_2.0I` without), about 30 seconds. Nothing in `build/ref/` is committed.
- **No apt install was needed.** IDO compiles the C and the assembly files, a Python script drives it instead of `make`, and the tool reads the object files itself.
- Added `tools/fingerprint_libultra.py`. It reads the reference objects and splat's functions, blanks the link-time fields the object's relocations point at, and compares. A name is CONFIRMED only when the match is exact, unique both ways, at least 8 instructions, its calls agree with the reference, and it is not isolated. A tiny or ambiguous function can be confirmed only when a confirmed function calls it by that name. Everything else is LIKELY: reported, never named.
- The main score is coverage of N64Recomp's lists, read straight from its `src/symbol_lists.cpp` (`reimplemented_funcs`, `ignored_funcs`, `renamed_funcs`).
- `--symbols-out` writes proposed `symbol_addrs.txt` lines, each with an evidence comment, confirmed names only.
- Added `tools/test_fingerprint_libultra.py`, a known-answer test on synthetic objects with ten traps (changed instruction, wrong call target, wrong opcode at a call, duplicate, ambiguous pair, tiny, isolated, and so on). 27/27 checks pass.
- Checked the object reader on the real reference (not on the game): 641 distinct function names. The reference can supply 103 of the 116 `reimplemented_funcs` names and 287 of the 358 `ignored_funcs` names. Most gaps are things a 1996 game cannot have (voice, rumble, debugger internals).
- **Not run on the game yet**, on purpose.

**Stuck / unknown**
- **ultralib has no real 2.0D.** Its version switches start at 2.0J, so the oldest code it holds is 2.0I. The build uses that with the flags its Makefile lists for versions D to I. Functions that changed between D and I will not match. The matching rules stay strict; we accept fewer matches.
- GoldenEye's copy is version G, closer to D than ultralib's I, so the second reference matters more than expected. It is not built yet; the build script only handles ultralib so far.
- `__osInitialize_common` is on the reimplemented list but is a 2.0J and later name; older libraries only have `osInitialize`.
- 108 reference functions are under 8 instructions and can only be named through a confirmed caller.
- The tool compares calls but not data addresses. Checking that two functions agree on a shared variable's address would be extra evidence for tiny functions; not built.

**Next**
- Session 2: run the tool on the game, review the LIKELY pile, write confirmed names into `disasm/symbol_addrs.txt`.
- If coverage is thin, add GoldenEye's `libultra` (version G) and `libultrare` as a second reference folder under `build/ref/obj/`.

## 2026-10-08: splat config, first clean split

**Done**
- Added `disasm/kigold.yaml` (splat 0.50.0) and `disasm/symbol_addrs.txt`. Input is `build/kigold.decompressed.z64`; the config carries its SHA1 so splat refuses any other file. Run: `cd disasm && .venv/bin/python -m splat split kigold.yaml`.
- Segments: header, ipl3 (blob), boot (code 0x1000 to 0x7160, data to 0x7EC0, plus its 0x8690 bytes of variables), `rom_data` (blob, 0x7EC0 to 0xC00000), stream1 (code to +0x32C90, then the `stream1_rsp` blob), stream2 and stream3 as overlays with their own `exclusive_ram_id` and symbol names ending in `_stream2` / `_stream3`. Code ends for boot, stream2, and stream3 were confirmed by a block scan before writing the config.
- `symbol_addrs.txt` holds 8 names, all from the boot trace (our names, not original ones).
- The split runs clean: exit 0, no errors. The only messages are file-split and rodata hints.
- Added `disasm/include/` to `.gitignore` (splat writes a generated `macro.inc` there).

| Segment | splat functions | `jr ra` count | Why they differ |
| --- | --- | --- | --- |
| boot | 116 | 118 | 6 functions have two `jr ra`; 4 have none |
| stream1 | 459 | 535 | 36 functions have more than one `jr ra` (77 extra), 1 has none |
| stream2 | 251 | 270 | 7 functions have more than one `jr ra` (19 extra) |
| stream3 | 78 | 130 | see below |

- In boot, stream1, and stream2 every `jr ra` is inside a function and every word decodes. splat's counts are the better function counts: 826 for those three.

**Stuck / unknown**
- **Stream3 is only about half disassembled.** splat gave up on 30 blocks and wrote them as raw words: 12,540 words, about 50 KB of the 92 KB code area. Those blocks hold 74 of the 130 `jr ra`. 249 of the words are not valid instructions, which fits the data tables between routines seen earlier; one bad word makes splat drop the whole block. The largest "function" is 42 KB, clearly many routines glued together.
- In the half that did decode: 78 functions, 71 extra entry labels (jumps into the middle of a function), and 28 functions with no `jr ra`. So the real stream3 routine count is unknown; 78 is a floor.
- Stream1 has a few functions with many returns (one has 15, two have 8). Could be hand-written or switch-style code; not looked at.
- The tail of stream1 (`stream1_rsp`, 31.5 KB) is treated as one blob. It holds the microcode, and stream1's own data may be in there too; not separated yet.
- splat's rodata hints (jump tables at 0x7D30, 0xD20380, 0xD3AC84) are not applied; data is one block per segment for now.

**Next**
- Stream3 needs manual work before N64Recomp can use it: mark the data tables inside the code and add routine starts to `symbol_addrs.txt`.
- libultra fingerprinting (boot and stream1 first; splat's file-split hints in boot look like libultra file edges).

## 2026-10-08: Unpacker tool, decompressed ROM builds

**Done**
- Added `tools/unpack_rom.py`. It checks the ROM SHA1, reads the stream table at ROM 0x7DE0, inflates table entries 0, 1, 2, and writes `build/kigold.decompressed.z64`: the original 12 MB unchanged, then the three code images. It also writes `build/unpack_layout.toml` (addresses and sizes only). Both are git-ignored.
- Added `tools/test_unpack_rom.py`, a known-answer test on a synthetic ROM. 20/20 checks pass.
- Result on the real ROM (total size 0xD48CA0, about 13.9 MB):

| Segment | ROM offset in the decompressed ROM | RAM address | Size |
| --- | --- | --- | --- |
| stream1 | 0xC00000 | 0x8000F960 | 0x3A7A0 |
| stream2 | 0xC3A7A0 | 0x801ACB20 | 0xE8B40 |
| stream3 | 0xD232E0 | 0x801AD900 | 0x259C0 |

- Verified from the output file: the first 12 MB still matches the recorded SHA1, and each segment starts with sensible code at its RAM address.
  - stream1: starts with a normal function opening. 98% of its internal call targets land on a function start.
  - stream2: same, 100%.
  - stream3: starts with a loop that clears memory from 0x801D32C0, which is exactly where stream3 ends. The three addresses stream 1 calls outside itself (0x801ACB20, 0x801AD900, 0x801AE460) are all real routine starts.
- **Stream 3 is mostly hand-written assembly:** 629 plain jumps (`j`) against 130 `jr ra`, many routines end with a jump instead of a return, small data tables sit between routines, and it touches CPU control registers directly (`mfc0`). So the `jr ra` count undercounts its functions.

**Stuck / unknown**
- Stream 3's style will make function splitting harder for splat and N64Recomp (routines without a clear end, data inside code). Expect manual symbol work there, and it is where WM2K-style cleanup scripts matter most.
- Where CPU code ends in stream1 is only approximate (about +0x32C90), so the layout file has no `code_size` for it.

**Next**
- The splat config, pointed at the decompressed ROM and using the layout file for segment addresses.

## 2026-10-08: Boot code traced, code stream RAM addresses found

**Done**
- Read the boot code with the `rabbitizer` disassembler (throwaway scripts, nothing written to disk) and found where each code stream is inflated.

| Stream (ROM offset) | Inflated size | RAM address | When |
| --- | --- | --- | --- |
| 0x0A94D70 | 0x3A7A0 | 0x8000F960 to 0x8004A100 | At boot, by the boot code, which then jumps to it |
| 0x0AB5870 | 0xE8B40 | 0x801ACB20 to 0x80295660 | Later, by stream 1 |
| 0x0B00DF0 | 0x259C0 | 0x801AD900 to 0x801D32C0 | Later, by stream 1 |

- **Boot code:** ROM 0x1000 to 0x7EC0, RAM 0x80000400 to 0x800072C0. The entry point zeroes 0x8690 bytes of variables after it (up to 0x8000F950), sets the stack, and starts threads. ROM 0x7EC0 to 0x9000 is not boot code; it belongs to the unknown data area.
- **Stream table:** ROM 0x7DE0 (RAM 0x800071E0) holds 27 start/end pairs of ROM offsets. Entries 0, 1, 2 are the three code streams (in table order: 0x0A94D70, 0x0AB5870, 0x0B00DF0). The rest are data streams.
- **Boot sequence** (function at RAM 0x80000520): clear RAM, read table entry 0 into a staging buffer at 0x802D4000, inflate it to 0x8000F960, jump to 0x8000F960.
- **Shared helpers in the boot code:** ROM read at 0x80000740 and 0x800007B4, inflate at 0x80000900 (arguments: source, destination, work buffer). Stream 1 calls them for every later load.
- **Overlay load sites, both in stream 1:**
  - Stream 2 (table entry 1): inflate call at 0x8001236C inside function 0x80012260, then a call to 0x801ACB20. Function 0x80012260 is called from 0x8000FB14.
  - Stream 3 (table entry 2): inflate call at 0x8000FC90 inside function 0x8000FAA0, which later calls 0x801AD900 (at 0x8000FEF0).
  - Function 0x8000FAA0 is the main function, called once from the stream 1 entry at 0x8000F960.
- **Streams 2 and 3 overlap in RAM.** Code ends at +0x219E0 in stream 2 and +0x16760 in stream 3 (from the cache flush ranges at the load sites); the rest of each is data. Reading: stream 2 is start-up code plus a large data block, and stream 3 loads over stream 2's used-up code. Not proven; the running game has to confirm the order.
- **Microcode location:** the last part of stream 1, from about +0x32C90 (RAM 0x800425F0), is RSP microcode, not CPU code. The first RSP-style call is at +0x32CC0.
- **Corrected function count** (`jr ra` inside CPU code only): about 1,053. Boot 118, stream 1 535, stream 2 270, stream 3 130. The earlier 1,070 included 13 inside the microcode and counted stream 1 as 548.
- Checked the reference docs: GoldenEye documents the same 1172 format; WM2K's code was not compressed, so it has no template for this step.
- **Decision:** the decompressed ROM keeps the original 12 MB unchanged and appends the three inflated code images after it (see the `PLAN.md` decisions log).

**Stuck / unknown**
- The exact order of the stream 2 and stream 3 loads, and whether either is reloaded during play.
- An LZ-style decompressor at RAM 0x800005EC has no direct callers in the boot code or stream 1. Unknown use.
- Phase 2: the runtime must be told when stream 2 or 3 is loaded (a hook at the two load sites), and the port needs its own unpack step for players' ROMs. N64ModernRuntime is believed to have a hook for that; not checked in its source yet.

**Next**
- Build `tools/unpack_rom.py` with a known-answer test, then the splat config.

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
