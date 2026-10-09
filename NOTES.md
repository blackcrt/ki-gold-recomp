# Session notes

Newest entries at the top. Each entry: what was done, what's stuck, what's next.

## 2026-10-08: Exception handler group and osAiGetLength (session 5)

**Done**
- Named the exception handler group by hand, 7 names, plus `osAiGetLength`. All 8 are in `disasm/symbol_addrs.txt` in their own block with evidence. No tool changes.

| Name | Address | Evidence in short |
| --- | --- | --- |
| `__osExceptionPreamble` | 0x80003DA0 | Exact match (3 instr). `osInitialize` copies it to the four exception vectors |
| `__osException` | 0x80003DB0 | The preamble jumps here. 337 instr, not exact (version D). Calls `send_mesg` 15 times |
| `send_mesg` | 0x800042F8 | Exact match (44 instr). Called 15 times by `__osException` |
| `handle_CpU` | 0x800043AC | Exact match (13 instr). Follows `send_mesg` as in the reference |
| `__osEnqueueAndYield` | 0x800043E0 | 5 confirmed functions call it where the reference calls this name. 35 instr, not exact: 35 same kind, 34 identical |
| `__osDispatchThread` | 0x800044C8 | `osStartThread` and `osDestroyThread` call it where the reference calls this name; `__osEnqueueAndYield` jumps to it. 80 instr, not exact |
| `__osCleanupThread` | 0x80004608 | Exact match (2 instr). `osCreateThread` stores this address where the reference stores `&__osCleanupThread` |
| `osAiGetLength` | 0x80039990 | Exact match, single candidate (3 instr); the match includes the AI length register address. Called by the game's audio code right after `osAiSetNextBuffer` |

- **splat had merged three small pieces into their neighbours:** the preamble into `__osException`, `handle_CpU` into `send_mesg`, and `__osCleanupThread` into `__osDispatchThread`. That is why the fingerprint tool never matched them: cut at the right address, four of the seven are exact matches. Naming them makes splat cut there. The split now has **907 functions** (was 904), exit 0, no errors.
- This also explains last session's lead that `send_mesg` matched "except two local jump distances": those two jumps were in the `handle_CpU` part.
- Cross-check method (throwaway script): for every confirmed function, list each address it calls or points to and the name the reference uses there. Side result: 11 confirmed audio functions call 0x800062C0 as `osSetIntMask`, which independently backs that hand name from session 4.
- Re-ran the fingerprint tool after the split: 221 exact matches (was 219; it now confirms `send_mesg` and `handle_CpU` by itself), 0 data conflicts, and nothing it confirms disagrees with the symbol file. Test still 43/43.
- **Coverage, counted from the symbol file:** `reimplemented_funcs` **55 of 116** (was 54), `ignored_funcs` 111 of 358 (was 103), `renamed_funcs` 6 of 83. 250 function names in total.
- Ticked "Identify remaining OS core functions by hand" in `PLAN.md`.

**Stuck / unknown**
- **`osYieldThread` is not in the decoded code.** It must call `__osEnqueueAndYield`, and that has exactly 5 callers, all confirmed as other functions. The game's `__osDevMgrMain` (version D) is also much shorter than later versions, which do call `osYieldThread`. Caveat: stream3 is half decoded, so this is "not found", not "proven absent".
- `__osException` and `__osDispatchThread` differ from versions G and I and were not read line by line. Their names rest on who calls or jumps to them.
- Leads seen in the cross-check, **not named** (outside this task):
  - 0x80032F50 is called by confirmed `guLookAtHilite` as `guLookAtHiliteF` (no exact match).
  - 0x8003EE70 is called by confirmed `alSynAllocFX` as `alFxNew` (no exact match).
  - 0x8003F330 / 0x80040F30 are the identical pair `alMainBusParam` / `alAuxBusParam`; confirmed callers and stored pointers say which is which, but the tool refuses because both game functions match both names.
  - 0x800413C8 is called as `alSeqGetTicks` by confirmed `__postNextSeqEvent`.
  - 0x800064F0 is `__osGetCause` by exact match (2 instr), single candidate, 6 callers.
- Still not found from the earlier list: `osPiReadIo`, `osPiGetStatus`, `osEPiRawStartDma`, `osStopThread`, `osViSetXScale`, `osViSetYScale`, `__ull_to_d`, `__ull_to_f`.

**Next**
- Phase 1 has two boxes left: "identify graphics and audio microcode" and "generate the symbol file N64Recomp reads (`syms/`)". The symbol file is the natural next step.
- Optional and cheap: name the five leads above (the audio ones are not on the reimplemented list, so they do not block the recomp).
- Before leaning on any "not in the game" verdict: finish decoding stream3.

## 2026-10-08: Callee rule, boot copies, and first hand-found OS functions (session 4)

**Decisions (BlackCRT)**
- Keep `osGetThreadPri`.
- Duplicates: the stream1 copy keeps the standard name, the boot copy gets `_boot`.
- Ticked the fingerprint box in `PLAN.md` with a note and added "Identify remaining OS core functions by hand".

**Done**
- `tools/fingerprint_libultra.py`, two new rules, test now 43/43:
  - **Callee rule.** A call to a confirmed function counts like a data address: for a candidate name when the reference calls that function there, against it when the reference calls a different one. Same strictness as the data rule (one name fits, every other is contradicted, no rival in the segment).
  - **Copies.** "Unique" is now judged inside one segment. A name confirmed once in boot and once in stream1 stays plain in stream1 and gets `_boot` in boot (`COPY_SUFFIX`). Two matches inside one segment are still refused.
- Tool run on the game: **219 exact matches (was 201), 30 likely, 655 no match, 0 data conflicts.** All earlier names unchanged. 18 new:
  - Callee rule: `osEepromLongRead` (0x80036780, calls `osEepromRead`) and `osEepromLongWrite` (0x80036640, calls `osEepromWrite`), `__osSiRawReadIo`, `__osSiRawWriteIo`, `guRotate`, `guScale`, `guRotateRPY`, `guOrtho`, `osSpTaskYield` (7 instructions, calls confirmed `__osSpSetStatus`).
  - Copies: `memcpy`, `strlen`, `strchr` in stream1 and `memcpy_boot`, `strlen_boot`, `strchr_boot` in boot.
  - Caller rule, now that it is per segment: `__osSiCreateAccessQueue`, `__osSiGetAccess`, `__osSiRelAccess` in stream1.
- **The access queue functions are not duplicates.** Stream1's set is the Si set (called by `osContStartQuery`); boot's set is the Pi set (called by `osCreatePiManager`). So the only real duplicates are `memcpy`, `strlen`, `strchr`.
- **Duplicates and the runtime lists:** `memcpy`, `strlen`, `strchr` are on `renamed_funcs` only. That list just renames a function so it does not clash with the PC's C library; the game's own code still runs. They are not on `reimplemented_funcs` or `ignored_funcs`, so the boot copies need no special handling, and `_boot` names cannot clash.
- **Hand search**, with throwaway scripts (not committed): listed which named functions every unnamed function calls, compared that with the reference, then counted how many instructions are the same kind and how many are identical. 16 names added to `disasm/symbol_addrs.txt` in their own block, marked "by hand", each with its evidence. These are **not exact matches** unless the line says so.

| Name | Address | Evidence in short |
| --- | --- | --- |
| `osInitialize` | 0x80002590 | Same 14 calls in order; 139 of 139 instr same kind, 126 identical (vs 2.0I final ROM); called first by the entry point |
| `osCreatePiManager` | 0x80002D50 | Same 11 calls in order; 90 of 94 same kind |
| `osPiStartDma` | 0x80002F00 | Same 4 calls in order; 65 of 65 same kind, 61 identical; called by `boot_rom_read` |
| `osCreateViManager` | 0x800031F0 | Same 12 calls in order; 93 of 96 same kind |
| `osContInit` | 0x8003A070 | Same 16 calls in order as Rare's version; 124 of 126 same kind, 111 identical |
| `osSetIntMask` | 0x800062C0 | Older, shorter version: 23 of 23 same kind, 17 identical; touches the status register and the interrupt mask register; 19 callers in save/restore pairs |
| `__osDevMgrMain` | 0x80004C50 | Thread entry that `osCreatePiManager` passes to `osCreateThread` |
| `viMgrMain` | 0x80003374 | Thread entry that `osCreateViManager` passes to `osCreateThread` |
| `__osViInit` | 0x80005350 | Called by `osCreateViManager` in the right place; calls `bzero` and `__osViSwapContext` |
| `__osViGetCurrentContext` | 0x80005480 | Returns `__osViCurr` (0x80007040); called by `viMgrMain` |
| `__osPiCreateAccessQueue`, `__osPiGetAccess`, `__osPiRelAccess` | 0x80004A90, 0x80004AE0, 0x80004B24 | Exact match with the Pi/Si pair; settled by the `osCreatePiManager` call and the shared queue at 0x8000F648 |
| `__osGetSR`, `__osSetSR`, `__osSetFpcCsr` | 0x80003CE0, 0x80003CD0, 0x80003CF0 | Exact, single candidate; called by `osInitialize` in the reference's order |

- **Coverage, counted from the symbol file:** `reimplemented_funcs` **54 of 116** (was 44), `ignored_funcs` 103 of 358 (was 79), `renamed_funcs` 6 of 83. 242 function names in total.
- `osSetIntMask` at 23 instructions (39 in version I) and the much shorter `__osDevMgrMain` are the first direct evidence that this library is older than G, which fits the 2.0D lead.
- Re-ran the splat split: exit 0, no errors, still 904 functions.

**Stuck / unknown**
- Of the 14 targets, 8 were **not found**:
  - `osPiReadIo`: nothing calls the boot `__osPiGetAccess`, so no function has its call pattern. Probably not in the game.
  - `osStopThread`, `osViSetXScale`, `osViSetYScale`: no unnamed function in boot or stream1 has their call pattern. Probably not in the game.
  - `osEPiRawStartDma`: no candidate. It may not exist in version D at all (the EPi functions came later). Not verified.
  - `osPiGetStatus`: 3 instructions, no calls, nothing to go on. The one 3-instruction candidate (0x80037650) is an empty stub, not this.
  - `__ull_to_d`, `__ull_to_f`: tiny maths helpers with no calls and no data; no method finds them. Unknown.
- "Not found" in boot and stream1 only. Stream2 and stream3 were not searched by hand, and stream3 is still half decoded.
- Exception handler leads, seen but **not named** (outside this task): `0x80003DA0` (341 instr, calls `send_mesg` 15 times) looks like `__osException`; `0x800042F8` is `send_mesg`; `0x800043E0` (35 instr, 35 same kind and 34 identical against `__osEnqueueAndYield`); `0x800044C8` calls `__osPopThread` and `osDestroyThread`, so `__osDispatchThread` is in or near it. splat's function boundaries in this hand-written assembly may not match the reference's.
- `osYieldThread` was not looked for.
- The hand names rest on call order and instruction similarity, not exact matches. The running game is the final proof (ground rule 1).
- Still likely, not named: `__ll_rem` / `__ull_rem` (identical code, two addresses), `osAiGetLength` (3 instructions), `__osGetCause`, the `alCSP*` / `alSeqp*` pairs.

**Next**
- "Identify remaining OS core functions by hand": the exception handler group above, then `osYieldThread`.
- `osAiGetLength` (0x80039990) is called by the game's audio code next to `osAiSetNextBuffer`; a hand check would probably settle it.
- Then the `syms/` file for N64Recomp.

## 2026-10-08: GoldenEye reference and data-address check (session 3)

**Done**
- `tools/build_libultra_ref.py` now also fetches a pinned copy of `n64decomp/007` (GoldenEye) into `build/ref/ge007/` and builds two more reference folders: `ge007_libultra_G` (121 of 121 C files compile) and `ge007_libultrare`, Rare's modified files (30 of 30). Flags come from GoldenEye's own Makefile. Nothing in `build/ref/` is committed.
- GoldenEye's 23 assembly files are written for the GNU assembler, which we do not have. No install was needed: each line carries the instruction's bytes in a comment, so the build script copies them and the fingerprint tool reads the text.
- `tools/fingerprint_libultra.py` now compares **data addresses**. Confirmed functions fix where each libultra variable lives in the game (kept apart per segment). An unconfirmed function gets a name only when one candidate name reads variables at exactly those addresses, every other candidate name is contradicted, and no other game function fits the name too. The report also lists any variable that two confirmed functions place differently.
- **Finding: GoldenEye's assembly listings have wrong labels.** Its `pirawwrite.s` is labelled `osPiRawWriteIo`, but the code reads from the cartridge and stores to the caller's pointer, so it is `osPiRawReadIo` (our existing name, from the compiled ultralib object, was right). Its `bzero.s` also calls `bzero` `memset`. New tool rule: a name from a compiled object always wins over a listing label, and a match that only a listing supports is never confirmed.
- Test: `tools/test_fingerprint_libultra.py` grew from 27 to 39 checks (identical pair settled by data, pair nobody can settle, tiny function with agreeing data, wrong-address trap, two-fits trap, the listing reader, and the two listing trust rules). 39/39 pass.
- Run on the game, four reference folders: **201 confirmed (was 185), 48 likely, 655 no match.** All 185 earlier names came back at the same addresses. **0 data address conflicts** among confirmed functions, which is an independent check on the earlier names.
- Main score, confirmed names only: `reimplemented_funcs` **44 of 116** (was 34), `ignored_funcs` 79 of 358 (was 66), `renamed_funcs` 3 of 83.
- The 16 new names, all appended to `disasm/symbol_addrs.txt` with evidence:
  - From Rare's modified files (`libultrare`), exact matches: `osSpTaskLoad`, `osDestroyThread`, `osAiSetNextBuffer`, `osContStartReadData`, `osEepromProbe`, `osEepromRead`, `osEepromWrite`, `__osEepStatus`, `__osPackRequestData`, `__osPackEepReadData`, `alFxParamHdl`.
  - From version G: `guLookAtReflectF`, `guMtxL2F`.
  - Settled by data addresses: `osViGetCurrentFramebuffer` and `osViGetNextFramebuffer` (identical code, told apart by `__osViCurr` at 0x80007040 and `__osViNext` at 0x80007044), and `osGetThreadPri` (6 instructions, reads `__osRunningThread` at 0x80006FB0, the address confirmed functions use).
- **KI Gold matches Rare's modified library files, not the stock ones.** That proves shared in-house library code between KI Gold and GoldenEye, as `docs/GOLDENEYE.md` guessed. It also answers one question: the game saves to **EEPROM** (probe, read, and write are all present in stream1).
- Re-ran the splat split: exit 0, no errors, still 904 functions, same 201 on a second fingerprint run.

**Stuck / unknown**
- **72 of 116 reimplemented functions are still not confirmed.**
  - 14 exist in the GoldenEye reference and still found no match: `osInitialize`, `osCreatePiManager`, `osCreateViManager`, `osPiStartDma`, `osPiReadIo`, `osPiGetStatus`, `osEPiRawStartDma`, `osContInit`, `osSetIntMask`, `osStopThread`, `osViSetXScale`, `osViSetYScale`, `__ull_to_d`, `__ull_to_f`. Either KI Gold's version D code differs from G here, or the game does not use them. Not checked per function.
  - 6 are likely but not named: `osEepromLongRead` / `osEepromLongWrite` (two game functions, two names, identical code), `__ull_rem` (same code as `__ll_rem`), `osSpTaskYield` (7 instructions), `osAiGetLength` and `__osSetFpcCsr` (3 instructions, no confirmed function reads the same variable).
  - 39 exist only in ultralib and found no match. Most are hardware a 1996 game cannot have (flash, rumble, 64DD cart init, debugger). The ones that could matter: `osAiGetStatus`, `osGetMemSize`, `osSetTime`, `osStopTimer`, `osGetThreadId`, `osContSetCh`, and the `osPfs*` Controller Pak set.
  - 13 are in no reference (voice, `__osInitialize_common`, `osSetCount`, and so on).
- OS core from the ignored list still missing: `__osException`, `__osDispatchThread`, `__osEnqueueAndYield`, `__osDevMgrMain`, `__osViInit`, `osYieldThread`. GoldenEye's `exception.s` gave one lead only: its `send_mesg` label matches the game at 0x800042F8 except for two local jump distances. So the exception handler is there but its layout differs from version G.
- The Pi and Si access queue functions are not settled. Data cannot do it (no confirmed function reads the queue variables directly), and the caller rule refuses because boot and stream1 each hold a copy, so each name fits two addresses. Same for `memcpy`, `strlen`, `strchr`. This needs a decision on how to name duplicate copies; a symbol file cannot hold one name twice.
- One judgement call to review: `osGetThreadPri` is only 6 instructions. It was named because its code is unique in the reference and its data address agrees. The floor for a data-confirmed name is 3 instructions (`MIN_DATA_INSTR`); the 8 instruction floor still applies to everything else.
- Stream3 is still only half decoded.

**Next**
- Cheap and strict: let a confirmed *callee* rule out a candidate name, the mirror of the data rule. `osEepromLongRead` calls `osEepromRead` and `osEepromLongWrite` calls `osEepromWrite`, and both of those are now confirmed, so this would settle that pair. Not done, since it was not asked for.
- Decide how to name the duplicate boot and stream1 copies.
- For the 14 start-up, Pi, and Vi functions that match neither I nor G: find them by hand from their confirmed callers and callees (for example, whatever calls `osCreateThread` with the Pi and Vi manager setup), then compare against the reference source line by line.

## 2026-10-08: libultra fingerprint run on the game (session 2 of 2)

**Done**
- Ran `tools/fingerprint_libultra.py` against the ultralib 2.0I reference, both variants, over all four code segments (904 splat functions). Result: **185 confirmed, 48 likely, 671 no match.**

| Segment | Confirmed | Likely | Functions | Verdict |
| --- | --- | --- | --- | --- |
| boot | 53 | 19 | 116 | confirmed: holds libultra (OS core, threads, messages, VI, SP, timers) |
| stream1 | 132 | 28 | 459 | confirmed: holds libultra (audio library, gu maths, controller, AI, TLB) |
| stream2 | 0 | 1 | 251 | no match (the one "likely" is a trivial stub that matches three names) |
| stream3 | 0 | 0 | 78 | no match, but only the decoded half was checked |

- Main score, confirmed names only: `reimplemented_funcs` **34 of 116** (7 more likely, 103 exist in the reference), `ignored_funcs` 66 of 358 (22 more likely, 287 in the reference), `renamed_funcs` 3 of 83.
- **Variant:** `_FINALROM` (`ultralib_2.0I_rom`) fits better, by one function. The two variants agree on 184 functions; `__osTimerInterrupt` matches only the `_FINALROM` build. Nothing matches only the other build. So the game was built as a final ROM, as expected for a retail cartridge.
- Wrote the 185 confirmed names to `disasm/symbol_addrs.txt`, each with its evidence comment. No address or name clashes with the 8 boot trace names. Re-ran the splat split: exit 0, no errors, still 904 functions, same confirmed count on a second fingerprint run.
- The audio library (`al*`) and the `gu*` maths match version I almost completely. Those parts did not change between D and I.

**Stuck / unknown**
- **82 of 116 reimplemented functions are not confirmed.** 13 do not exist in the reference at all (voice, `__osInitialize_common`, and so on) and about 30 more are hardware this game may not use (flash, rumble, 64DD). The ones that matter and found no match at all:
  - Start-up and managers: `osInitialize`, `osCreatePiManager`, `osCreateViManager`
  - Cartridge reads: `osPiStartDma`, `osPiReadIo`, `osPiGetStatus`
  - Controllers: `osContInit`, `osContStartReadData`
  - Audio output: `osAiSetNextBuffer`, `osAiGetStatus`
  - Graphics task: `osSpTaskLoad`
  - Saves: `osEepromProbe`, `osEepromRead`, `osEepromWrite`, the long versions, and the `osPfs*` Controller Pak set (which of these the game uses is not known yet)
  - Threads and timers: `osStopThread`, `osDestroyThread`, `osSetIntMask`, `osStopTimer`, `osSetTime`, `osGetMemSize`, `osViSetXScale`, `osViSetYScale`
- Also unmatched from the ignored list: `__osException`, `__osDispatchThread`, `__osEnqueueAndYield`, `__osDevMgrMain`, `__osViInit`, `osYieldThread`. These are the OS core and sit in boot next to the confirmed functions.
- A miss against version I does not mean a function is absent. The game is thought to be 2.0D (lead, not confirmed), and session 1 already expected functions that changed between D and I to miss. Not verified per function. Boot has 44 functions with no match and no likely; most of the missing OS core is probably among them.
- 7 reimplemented names are likely but not named: `osSpTaskYield`, `osGetThreadPri`, `osAiGetLength`, `__osSetFpcCsr` (too short), `osViGetCurrentFramebuffer` / `osViGetNextFramebuffer` and `__ull_rem` / `__ll_rem` (two candidates each, identical code). The Pi and Si access queue functions are the same case. Comparing data addresses would settle most of these; the tool does not do that yet.
- `memcpy`, `strlen`, and `strchr` each exist twice, once in boot and once in stream1, as do the access queue functions. That suggests boot and stream1 were linked separately, each with its own copy. Not investigated.
- Stream3 is still only half decoded, so "no match" there is a floor, not a verdict.

**Next**
- Recommended: build the GoldenEye reference (`libultra` version G and `libultrare`) as a second folder under `build/ref/obj/`. The missing functions are the version-sensitive OS core, and G is closer to D than I is.
- Cheap extra: teach the tool to compare data addresses, to settle the identical-code pairs.

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
