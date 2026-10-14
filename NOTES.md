# Session notes

Newest entries at the top. Each entry: what was done, what's stuck, what's next.

## 2026-10-13: Run 7 confirms the DP wait, plan for osDpSetNextBuffer (Phase 2, task 7l)

**Result: plan only. No code, no generated code, nothing in `lib/` changed. Not committed yet.** Everything below is static reading and is unproven until a run shows it (ground rule 1).

**Run 7** (heartbeat on, log in `build-msvc/firstrun.log`)
- Candidate 1 from 7k is confirmed. At 38 s: video ticks 2139, graphics tasks 0, audio tasks 2131, inflates 3. Thread 20 waits on `0x8000CF70` (0 of 5). Thread 3 waits on `0x8004A168` in `func_801ADB1C_stream2`. Thread 4 waits on `0x80066D08` (normal). Thread 73 idle on `0x802D3D48`, so the save worker is not the cause. Same picture from 4 s to 98 s. No MISSING, CRASH or WARNING lines.

**What the block is**
- Two buffers of `0x640` bytes (200 commands) at `0x80068820`, one per frame buffer, index in `0x80044904`. Frame buffers are two 640x480 16-bit buffers at `0x802D4000` (`0x96000` each).
- The frame function gets a "builder" as its first argument. The builder fills the block every frame that is built. 5 of 9 call sites in stream2 pass `func_801AE568_stream2`. The other 4 pass `func_801ADEC0_stream2`, which calls through the pointer at `0x8004A920`. That pointer is set from about 20 places to one of 7 stream1 functions: `func_800198D0` (most common, 11 places), `func_80014330`, `func_800155E4`, `func_800160C8`, `func_80016874`, `func_80018EC0`, `func_8001377C`.
- `func_801AE568_stream2` always writes: sync pipe, set color image (16-bit, screen width, address from table `0x8004A320`), set scissor 0,0 to 640,480. Then either a screen clear (fill mode, fill color from `0x80295668/6C/70`, fill rectangle over the screen), or, when flag `0x801CE504` is set, `func_801BCE58_stream2` adds a 64x48 256-color picture stretched over the screen (load palette, load block, one texture rectangle). It always ends with sync full. So this block is never empty.
- `func_800198D0` also writes a low-level triangle command (opcode `0x0E`, shaded and textured, given as raw edge and texture slopes, tile 7), with a horizon check at line 147 (`0x8001A098`). Also set prim and env color, render modes, palette loads, fill rectangles. Not read in full.
- Addresses in the block are plain `0x80......` addresses, not segment addresses. One command is written with opcode byte `0x2F` (set other modes with the top two bits clear) and one F3D command (`0xBA000E02`) sits in the raw block. Hardware only looks at the low 6 bits of the opcode.
- Scheduler detail: after `osDpSetNextBuffer` it sets `0x8000D186` = 1 and waits for message 1 on `0x8000CF70` (`osSetEventMesg(9, 0x8000CF70, 1)` at `0x80001E60`). Only then does it start the task. The same message 1 arrives again when the task itself is done. A return value of -1 means "busy, try again".

**Runtime and RT64 at our pins**
- Runtime: `osDpSetNextBuffer_recomp` is empty (`librecomp/src/dp.cpp`). For a normal task `events.cpp` sends "SP done", calls the renderer's `send_dl`, then sends "DP done". `dp_complete` is not in a public header. `ultramodern::enqueue_external_message` is public.
- RT64 has a raw DP path: `Application::processDisplayLists(memory, start, end, false)` calls `Interpreter::processRDPLists`. It masks opcodes to 6 bits and has every command the block uses, including low-level triangles (`rt64_gbi_rdp.cpp`, `tri`). Triangles are only mapped in this raw path, not in the display list path.
- RecompFrontend only ever calls the display list path (`rt64_render_context.cpp` line 344) and keeps its RT64 object private (`renderer.h` line 37). So there is a path inside RT64 but no door to it from our code today.
- Generated code calls only `osDpSetNextBuffer_recomp` from the DP family (4 mentions), so our own definition should link without pulling in the runtime's file. The build will tell.

**Options (see chat summary for the full list)**
- (a) Our own `osDpSetNextBuffer`: return 0, remember and log the block, send message 1 to `0x8000CF70`. Unblocks. The block's drawing is lost.
- (b1) Draw the block through RT64's raw path from our renderer wrapper, right before the task it belongs to. Needs access to the private RT64 object.
- (b2) Translate the block into a small display list and send it through `send_dl`. No access problem, but cannot carry the low-level triangle.

**Next (proposal, waits for the coach)**
- Task 7m: option (a) with a block logger and a heartbeat counter, then run 8.
- After run 8: decide how to draw the block.

## 2026-10-13: Heartbeat added, static reading points at osDpSetNextBuffer (Phase 2, task 7k)

**Result: the heartbeat is written and builds. The exe was not run**, so it is unproven until run 7 (ground rule 1). The static reading found a strong lead for the run 6 hang: the game's scheduler waits for a display processor interrupt that the runtime never sends. No game code, no generated code and nothing in `lib/` was touched. No regeneration was needed.

**Part 1: heartbeat** (new file `src/main/heartbeat.cpp`)
- Off by default. Set the environment variable `KIGOLD_HEARTBEAT=1` before starting the exe. Every 2 seconds it prints one counter line and one line per game thread, all starting with `[kigold][beat]`.
- Counter line: video ticks, graphics tasks, audio tasks, inflates, number of game threads.
  - video ticks: counted in our video callback, only once the game runs. The runtime sends the game one video interrupt message on each. It is the runtime's count of frames, not proof the game picked the message up.
  - graphics tasks: counted in a thin wrapper around the renderer (`send_dl`). The wrapper is only put in place while the heartbeat is on.
  - audio tasks: counted in our microcode callback in `main.cpp`.
  - inflates: counted in the existing inflate hook.
- Thread line: id, priority, address of the thread record, state, and a short stack. Example of what a line should look like: `thread 20 (0x14) pri 13, record 0x8000CFC0: WAITING to receive on queue 0x8000CF70 (0 of 5 messages in it). Stack: osRecvMesg < 0x80001F20 boot`.
- **The runtime does not expose thread state.** What I found in `lib/N64ModernRuntime/ultramodern/src` (read only):
  - It keeps no list of game threads. But it calls our thread name callback once per created thread, on that thread, with the game's thread record. We already supplied that callback (it returned "game"). It now also remembers the record and a handle to the PC thread.
  - It only ever writes STOPPED or QUEUED into the record's state field (`scheduling.cpp`, `threads.cpp`), never RUNNING or BLOCKED. So the state is worked out from the record's `queue` field instead: the ready list means READY, a list inside a message queue means WAITING (first word of the queue = waiting to receive, second word = waiting to send), no list means RUNNING, no PC thread means ENDED.
  - It does not record who called `osRecvMesg`. The heartbeat stops the PC thread for a moment, walks its stack the same way the crash reporter does, and lets it go. Game functions print as N64 addresses, a few runtime functions (`osRecvMesg`, `osSendMesg`, `pause_self` and so on) by name.
- Why this way: the two other ways were a hook on every calling function (needs a regeneration, and we do not know the callers in advance) or changing `lib/` (not allowed).
- Limits, stated plainly: a line is a snapshot read without locks and can be a moment out of date. Stopping a thread to read its stack is a debugger technique with a small risk of its own, which is why it is off by default. The first boot thread has no record and is not listed. Stacks are Windows x64 only.
- Small shared helpers moved out of the crash reporter so both can use them: `kigold::find_game_function`, `kigold::section_name`, `kigold::known_rdram`. Crash reports print the same as before.

**Part 2: what the game most likely waits for (static reading of the split, nothing proven)**

What comes after the data inflate, in order: the rest of `func_801AEE60_stream2` is about 100 calls of `func_8002FE7C` plus copies, with no library call that can wait. `func_801BCB30_stream2`, `func_800129A0`, `func_801BE1D0_stream2` and `func_801CCE90_stream2` cannot wait either. After that `stream2_entry` talks to a worker thread and enters its frame loop. The candidates, most likely first:

1. **The scheduler waits for a display processor interrupt (strongest).**
   - The game has its own scheduler: thread id 0x14 (20), priority 13, function `func_80001F20`, set up in `func_80001DF0`. It waits on queue `0x8000CF70` (5 slots) for three messages: 0 = video interrupt, 2 = RSP task done, 1 = display processor done.
   - Each graphics task record has an optional block of raw display processor commands in front of the normal task (pointer at +0x00, size at +0x04, the normal task at +0x18). `func_80002420` sends that block straight to the display processor with `osDpSetNextBuffer` (`0x80002490` and `0x80002534`), sets a busy flag (`0x8000D186` = 1), and the normal task is only started when the "done" message arrives (`0x800021F8` to `0x8000221C`).
   - The runtime's `osDpSetNextBuffer` at our pin is an empty function (`lib/N64ModernRuntime/librecomp/src/dp.cpp` line 33, `assert(false)`, and our Release build removes asserts). It draws nothing and sends no "done" message.
   - stream2's frame function `func_801ADB1C_stream2` gets that block from `func_801AE568_stream2`, which writes a pointer for it at `0x801AE5A8`. So the first stream2 frame most likely already has one. Not confirmed that it is never zero.
   - What that would look like: graphics tasks stay at 0, video ticks and audio tasks keep rising, the main thread stops building frames after 2 unanswered tasks (check at `0x801ADB94`). Blank window, no crash, almost no CPU. That is run 6.
   - **This is bigger than the hang.** If right, KI Gold draws part of each frame with commands that go around the path RT64 listens to. Fixing the wait alone would not make that part visible. What the block contains was not read.
2. **The main thread waits for its frame message.** `func_801ADB1C_stream2` at `0x801ADB4C`: blocking `osRecvMesg` on queue `0x8004A168`. Type 1 = a new video frame (the scheduler sends it to up to 3 registered queues at `0x800020C0`), type 2 = a graphics task is done. In candidate 1 the main thread sits here too, between frames.
3. **The main thread is stuck sending to the worker.** `stream2_entry` sends 4 blocking messages (7, then 2 on a cold start, then 0, 0) at `0x801ACC98` to `0x801ACCE8` to queue `0x802D3D48`, which has 2 slots. The worker is thread id 0x49 (73), priority 2, function `func_801CCC8C_stream2`. Message 7 runs `func_801CDE94_stream2` (save chip probe, controller query, then a blocking wait for the "serial port done" message on queue `0x800683D0` at `0x801CDEE4`, also `0x801CCBC4`). Message 2 runs `func_801C0AE0_stream2` (reads the save, and can reach the Controller Pak code with our `__osSiRawStartDma` stand-in). Run 6 had no `MISSING` line, so the pak code had not run.
4. **The controller wait.** `func_8002B5B0` at `0x8002B5C8`: blocking wait on `0x800683D0`, once per frame and from the worker. It needs one "done" message per `osContStartReadData`. The runtime sends one each time, so this only hangs if the two get out of step.

Also checked: stream3 not loading is not by itself a sign of trouble. `stream2_entry` is a loop that only returns when its state variable (`0x80295678`) becomes 10 (`0x801AD890`). The reset event the worker registers (`0x801CCEEC`, event 14) is ignored by the runtime, harmless.

**Commands**
- Build: `Build OK`, no warnings from our files.

**Next**
- Run 7 with `KIGOLD_HEARTBEAT=1` (and `KIGOLD_VERIFY_INFLATE` as before). If candidate 1 is right: `graphics tasks 0` on every beat while video ticks and audio tasks rise, thread 20 waiting on `0x8000CF70`, the main thread waiting on `0x8004A168` with `0x801ADB1C stream2` on its stack.
- If so, the decision for the coach: how to handle `osDpSetNextBuffer`. First step would be to read what the game puts in that block.

## 2026-10-12: Run 6, no crash, the game waits (Phase 2, end of session 3)

**Result: the 7j audio cap works and the crash is gone. The game now hangs instead: the window stays open, blank and silent.** No code changes in this entry. Written from the coach chat at the end of the session.

**Run 6** (same settings, `KIGOLD_VERIFY_INFLATE` set; log in `build-msvc/firstrun.log`)
- Same start as run 5: stream1 loaded, VERIFY OK, entered stream1; stream2 loaded, VERIFY OK, entered stream2; data inflate to `0x802DEF10`.
- Then the audio cap acted 5 times (the log limit): 816, 816, 656, 656, 496 frames queued, each reported to the game as 464. The queue was draining.
- No `IMPOSSIBLE LENGTH`, no `MISSING`, no `CRASH`, no `osMapTLB` line.
- **No stream3 load and no "entered stream3"**, although stream1 calls into stream3 at `0x8000FEF0`.
- The window stayed open, blank, no sound.
- **CPU use was 0 to 1%** in Task Manager over about 10 seconds. So a thread is waiting (for a message, interrupt, DMA or another thread), not spinning.
- **The X button did not close the window.** It had to be force killed (`Stop-Process -Name KIGoldRecompiled -Force`). Fits a thread stuck waiting, since a clean shutdown waits for every game thread.
- Exit code not recorded (force killed).

**Stuck / unknown**
- What the game waits for after the data inflate in `func_801AEE60_stream2` (or later in stream2_entry). The log cannot say.
- Whether the audio thread keeps running after the 5 logged cap lines (the log limit hides it).

**Next: task 7k**
- Add a heartbeat, off by default, switched on by `KIGOLD_HEARTBEAT`. Every 2 seconds: each game thread (id, priority, state, and if waiting, the message queue address and the game function that called), plus counters (video interrupts, graphics tasks sent to the renderer, audio tasks, inflates). Our own `src/` files and hooks only, never `lib/`.
- Static reading: list what the game most likely waits for right after the data inflate.
- Then run 7 with the heartbeat on.

## 2026-10-12: Limit the reported sound queue, skip impossible buffers (Phase 2, task 7j)

**Result: run 5 proved the 7i lead. Both agreed changes are in our sound callbacks in `src/main/main.cpp`. Build passes. The exe was not run**, so the fix is unproven until run 6 (ground rule 1). No game code and no generated code was touched.

**Run 5** (`build-msvc/firstrun.log`): `IMPOSSIBLE LENGTH: queue_samples got 2147483584 samples (0x7FFFFFC0)`, then the run 4 crash again with the same callers. The reporter fixes of 7i worked too: frame #4 now prints as `not a game function`, and the "first page after RAM" NOTE appeared.
- 0x7FFFFFC0 samples is a byte count of 0xFFFFFF80, which is `-32 << 2`. So the game's frame length was -32, exactly the kind of value 7i predicted.
- Worked backwards through the game's sum, `(464 - queued) & 0xFFF0 = -32` means the game was told 481 to 496 frames were still queued. With the runtime's half-frame allowance that is about 576 frames in our SDL queue: only 26 ms, about 1.6 of the game's sound frames.

**1. Limit in `get_frames_remaining`**
- It now reports at most `frameSize + 0x60` frames, worked out from the sound rate the same way the game does: one video frame of sound (rate / 60, rounded up), rounded up to 16, plus 0x60. At 22050 Hz: 368 + 96 = **464 frames**.
- Why that number: it is the game's own largest buffer (stored at 0x8006805C by `func_8002AA20`), so it is the most the game ever gives the sound chip in one go, and it is the largest value the game's sum `frameSize + 0x60 - queued` can take before going negative.
- Check of the whole chain at the limit: we report 464 frames, the runtime turns that into bytes and takes off half a video frame (1856 - 367 = 1489), the game divides by 4 and gets 372, the sum gives 464 - 372 = 92, and the game raises that to its minimum of 352. Never negative.
- Normal play is not affected: the game aims to keep about 96 frames queued, far under the limit. The limit only acts when sound piles up.
- Honest gap: I did not confirm from hardware documents whether a console's length register counts one buffer or both of the two the chip can hold. The limit rests on the game's own code, which only works for values up to 464.
- Logs `[kigold][audio] N frames are queued, telling the game 464 (its limit)`, at most 5 lines.

**2. Safety net in `queue_samples`**
- More than 0xFFFE samples (the most a signed 16-bit frame count times 4 can give) is refused: logged as `IMPOSSIBLE LENGTH ... BUFFER SKIPPED`, at most 5 lines, and the buffer is not read. With change 1 this should never print. If it does, the limit is not enough.

**How the reference projects do it** (their public `src/main/main.cpp`, read this session, not copied)
- WM2K: `get_frames_remaining` returns the plain SDL queue size in frames, no limit. Same as ours was. It also uses 512-frame SDL chunks like ours. Its comments say that game slows itself down when the queue is full.
- Zelda64Recomp: converts sound to the device's rate, takes one video frame off the reported number, uses 256-frame chunks. No limit either.
- So we now differ from both on purpose. Neither needs a limit because their games cope with a large number. KI Gold's sound code is the stock SDK audio manager, which does not.

**Why is the queue that full so early? (from the code, not proven)**
- It is not very full. The trouble starts at about 556 queued frames (25 ms). The first buffer alone is 464 frames and each later one at least 352, so two buffers that arrive close together are already over.
- SDL does not drain smoothly. It takes sound out of the queue in chunks of 512 frames (`want.samples`), so the number we report jumps instead of falling steadily.
- Bursts. In the runtime only one game thread runs at a time, and it only hands over at a libultra call such as `osRecvMesg` (`check_running_queue` in ultramodern `scheduling.cpp`). On a console the sound thread interrupts the main thread on every video frame. Here, while the main thread is busy without such calls (inflating stream 2 and the data block comes right before the crash in the log), the sound thread cannot run. The video frame messages wait in its queue (room for 8), and when the main thread finally lets go, the sound thread makes several frames back to back with no real time passing.
- That last point is a reading of the code. Nothing measured it.

**Commands**
- Build: `Build OK`, no warnings from our file.

**Next**
- Run 6, same settings. Expected: maybe a few `frames are queued, telling the game 464` lines, no `IMPOSSIBLE LENGTH`, and the run gets further.
- Later, not now: sound may lag behind for a few seconds after a burst (the game only catches up by about 15 frames per video frame). If that is audible, option 4 of 7i (frame timing) is the real cure.

## 2026-10-12: Run 4 crash is in our sound callback, strong lead is an impossible length (Phase 2, task 7i)

**Result: the crash reporter worked. The crash is a read in our own `queue_samples` (`src/main/main.cpp`), called by the runtime's `osAiSetNextBuffer`. The strong lead is that the game handed over an impossible buffer length and our loop ran off the end of RAM, not that the game used an uncached address. Not proven, so the game crash is NOT fixed. Reporter label and a reporter bug fixed, one log-only line added. Build passes. The exe was not run.**

**Run 4** (`build-msvc/firstrun.log`): thread "game", READ of N64 0xA0000002 at `KIGoldRecompiled.exe + 0x2F40`, callers 0x800398E0, 0x8002AED8, 0x8002AD74, then "0x801CD324, 0x556B3 bytes in".

**1. What is at exe + 0x2F40** (from `build-msvc/KIGoldRecompiled.map`)
- `queue_samples` in our `main.cpp` (starts at 0x2E60, so 0xE0 bytes in): the loop that swaps left and right. It reads `audio_data[i + 1]` first, which is why the address ends in 2.
- Caller #1, 0x800398E0, is `osAiSetNextBuffer` (proven name in `syms/dump.toml`). The map shows the code that ran is the runtime's `osAiSetNextBuffer_recomp` (librecomp `ai.cpp`). It passes the game's two arguments (buffer, byte count) to `queue_audio_buffer`, which calls our `queue_samples(pointer, byte count / 2)`.

**2. Reporter label**: fixed. 0xA0000000 to 0xA07FFFFF now prints as uncached RAM (KSEG1), same memory as 0x80000000, not mirrored by the runtime. 0xA0800000 up stays "hardware or cartridge".

**3. Where 0xA0000002 comes from**
- The callers are the standard N64 SDK audio manager, almost line for line: `func_8002AA20` sets it up, `func_8002AD74` is its thread loop, `func_8002AED8` handles one sound frame. (Leads only, no names added.)
- `func_8002AED8` calls `osAiSetNextBuffer(lastInfo->data, lastInfo->frameSamples << 2)` at 0x8002AF14. `lastInfo` is the previous frame's record.
- `data` comes from `alHeapDBAlloc` on the heap the game sets up at 0x8002A3A4: base 0x80128240, length 0x4B380. A normal cached address. If the heap were full the result would be 0, not 0xA0000000.
- Nothing on this path builds an uncached address. There is no `lui 0xA000` or K0-to-K1 conversion in these functions. So "the game reads uncached RAM on purpose" and "a null pointer turned into an uncached address" both have no code behind them.
- What 0xA0000000 really is here: the runtime makes exactly 512 MB readable (`recomp::mem_size`), and 0x80000000 + 512 MB = 0xA0000000. It is the first byte after the end of readable memory. A loop that starts at a good buffer and does not stop faults exactly there, at +2 because of our read order.
- Why the loop would not stop: the length. `frameSamples` is a signed 16-bit field. `func_8002AED8` computes it at 0x8002AF24 to 0x8002AF64 as `(frameSize - osAiGetLength() / 4 + 0x60) & 0xFFF0`, stores it with `sh`, reads it back signed with `lh`, and compares it to the minimum with an unsigned compare (`sltu`). With 22050 Hz, frameSize is 368. If `osAiGetLength` reports more than 464 frames still queued, the result goes negative, the unsigned compare does not catch it, and the next frame passes `negative << 2`, about 4 GB, as the byte count. Our `queue_samples` then resizes its buffer to about 2 billion samples and walks to the end of RAM.
- On a console the sound chip holds at most two buffers, so the queued amount stays small. The runtime's `osAiGetLength` reports whatever our SDL queue holds (minus half a frame), with no upper limit. Two or three frames queued in a burst at start is enough (about 556 frames).
- **Not proven.** The log has no length in it. The alternative (the pointer itself was 0xA0000000) cannot be ruled out from run 4 alone, it just has no known source.

**4. The 0x801CD324 frame: not real**
- The map says that address is the runtime's `run_thread_function` (librecomp `recomp.cpp`), which is right: it is what starts a game thread.
- Reporter bug: the lookup only knows where each function starts and took the nearest start below the address. The table also holds runtime functions (the libultra replacements), which sit elsewhere in the exe, so runtime code between two table entries was credited to the entry below it. "0x556B3 bytes in" for a 0x80 byte function was the giveaway.
- Fix: the match now only counts if Windows' own function table (the unwind data) says the address is in the same function. Wording changed from "generated function" to "game function", because for a libultra name the code that runs is the runtime's version. The last line of the report now names both lookup files.
- New NOTE line: when the address is in the first page after the 512 MB, the report says to check for a loop that ran off the end of RAM.

**5. KSEG1 in the runtime and elsewhere**
- Runtime (read in our pinned `lib/N64ModernRuntime`): every memory access is `rdram + (address - 0x80000000)`. There is no mirror: 0xA0000000 + x lands 512 MB + x into the 4 GB block, which is not readable. Only `osVirtualToPhysical` and the cartridge (PI) functions know about KSEG1 addresses.
- Other recomps: not checked this session, their source is not in the repo. From memory only (unverified): they do not mirror KSEG1 either and deal with single cases by patching the game function. Check `docs/WM2K.md` sources before relying on this.
- Options if KI Gold does turn out to use KSEG1 somewhere: (a) patch that game function through `kigold.toml` so the address is converted first; (b) convert at the edge in our own callbacks where the game hands us a pointer; (c) a real mirror of RAM at +512 MB, which needs runtime changes we do not make in `lib/`; (d) catch the fault and redo the access, complex and slow. Lean: (a) or (b), case by case. Nothing points to KSEG1 being used so far.

**Log line added (log only, no behaviour change)**
- `queue_samples` prints `[kigold][audio] IMPOSSIBLE LENGTH: ...` when it gets more than 0xFFFE samples (the most a signed 16-bit frame count times 4 can give). Run 5 then says yes or no to the lead.

**Options for the game crash, once run 5 confirms the length** (none done)
1. Limit what our `get_frames_remaining` reports, so the game never sees more queued sound than a console could hold. Small, in our own callback, fixes the cause on our side.
2. Refuse impossible lengths in `queue_samples` with a loud log. Stops the crash but the game has already computed a bad frame. Good as a safety net next to option 1.
3. Patch the game's `func_8002AED8` to clamp the value. Touches game logic, most work.
4. Find out why sound queues up at start (frame timing) and fix that. Right in the long run, but open-ended.
- Lean: 1 plus 2.

**Commands**
- Build: `Build OK`, no warnings from our files.

**Next**
- Run 5, same settings. Look for the `[kigold][audio] IMPOSSIBLE LENGTH` line before the crash block.

## 2026-10-12: Third run crash, crash reporter added (Phase 2, task 7h)

**Result: the 7g fixes worked (both streams VERIFY OK, both entered). The third run then died silently with 0xC0000005 after the first data inflate. A crash reporter is added so the next run says where and why. Build passes. The exe was not run**, so the reporter itself is unproven until run 4 (ground rule 1). Nothing in the game path was changed.

**The third run** (BlackCRT, `build-msvc/firstrun.log`): stream1 loaded, VERIFY OK, entered; stream2 loaded, VERIFY OK, entered; `dst=0x802DEF10 rom=0x00A6AA60: data`; exit code -1073741819. No `osMapTLB` line.

**1. The crash reporter** (`src/main/crash_reporter.cpp`, new)
- A Windows vectored exception handler, installed at the top of `main`. Prints `[kigold][CRASH]` lines for access violations and the other fatal CPU exceptions, then flushes.
- It prints: exception code and name, thread id and thread name, the code address, READ / WRITE / EXECUTE and the memory address, and the chain of callers (up to 32).
- Code addresses: each one is looked up in the generated section table. A hit prints the function's N64 address and section, for example `generated function at N64 0x801AEE60 (stream2)`. The name is found by that address in `syms/dump.toml` (default names are `func_<address>` anyway). The exe has no table of names in a Release build, so the reporter cannot print the name itself. Code that is not generated prints as `KIGoldRecompiled.exe + offset` (or the DLL name).
- Memory address: if it lies in the 4 GB block the runtime reserves for the game, it is turned back into the N64 address and classified: null pointer, the per-fighter TLB range 0x00010000 to 0x000BA000, other address below 0x80000000, hardware or cartridge (0xA0000000 to 0xBFFFFFFF), or past the 512 MB of RAM.
- It only reports. It returns "continue search", so Windows ends the program as before with the same exit code. At most 3 reports per run, in case a library raises and handles such an exception itself.
- Support code: `kigold::find_generated_function` in `register_overlays.cpp` (sorted list of every generated function's place in the exe, built at start), `kigold::note_rdram` called from the ROM read hook and the renderer callback so the reporter knows where game memory starts.
- Limits: Windows x64 only. If the linker merged identical functions, the N64 address can be one of several, and the line says so.

**2. Likeliest causes of this crash (static reading only, nothing proven)**

Facts first:
- The data inflate is called from `func_801AEE60_stream2` (the `jal` at 0x801AEF10), the third call inside `stream2_entry`. It reads ROM 0xA6AA60 to 0xA73970 (0x8F10 bytes) to 0x802D4000, uses a work buffer at 0x802DCF10, and inflates to 0x802DEF10. All three are inside normal RAM.
- Right after, the same function calls `func_8002FE7C` (stream1) 96 times and `memcpy_boot` 9 times on the inflated data. `func_8002FE7C` calls the decoders `func_8002FA20` and `func_8002FC40`. Then `stream2_entry` goes on to `func_801BCB30_stream2` and `func_800129A0`.
- The log shows where the inflate started, not that it ended, and nothing after it. So the crash is anywhere from inside that inflate onward, on any thread.

Candidates, likeliest first:
1. **A bad pointer in game code after the inflate** (the 96 decoder calls, or later in `stream2_entry`). The decoders walk pointer tables. A wrong translation or a wrong assumption of ours would show here. Report would say: generated function, N64 address of the memory.
2. **A crash inside the runtime or renderer, caused by what the game hands it** (first video, sound or thread setup; `stream2_entry` sets up a 320x240 screen in `func_801AE794_stream2` just before). The exit code does not say which thread died. Report would say: `not generated code`, with generated functions in the caller chain, or a thread named VI, Gfx or SP Task.
3. **The data inflate itself.** Unlikely: the same code just inflated 0x123000 bytes of streams 1 and 2 correctly. But VERIFY only checks code streams, so this data block is unchecked. Report would say: N64 0x80000960 to 0x80001DF0 (boot).
4. **A TLB address.** Unlikely at this point: no `osMapTLB` line was printed, and reading a TLB address before mapping it would crash a real console too. Expected later, not here. Report would say: memory address in the per-fighter TLB range.

Ruled out on paper:
- Direct hardware access in game code: none. The 0xA.../0xB... constants in game functions are display list commands and floats. Only libultra touches hardware, and the runtime replaces it.
- Direct TLB or COP0 instructions in game code: none besides libultra (`stream3_entry` has two, not reached yet).
- A stubbed function: the only stream1 stub, `func_80030EF0`, is called only from `func_8001DE9C`, not from this path.
- A jump to an unknown function or a bad jump table: those print "Failed to find function" (seen in run 1), they do not end in an access violation.

**Commands**
- Build: `Build OK`, no warnings from our files.

**Next**
- Run 4 with the same settings. Paste the `[kigold][CRASH]` block.
- Suggestion, not done: if the crash is in non-generated code, add a linker map file (one flag, output stays in `build-msvc/`) so `KIGoldRecompiled.exe + offset` can be turned into a function name.

## 2026-10-12: Second run, the VERIFY check was wrong and caused the crash (Phase 2, task 7g)

**Result: the 0x80000450 fix worked. The second run's "stream1 WRONG" and the silent exit (0xC0000005) both came from a bug in our own VERIFY check, not from the game's inflate. Fixed. Regen and build pass. The exe was not run again**, so whether the inflate is right is still unproven (ground rule 1).

**The second run** (BlackCRT): stream1 loaded, `VERIFY: stream1 WRONG, 183963 of 0x3A7A0 bytes differ, first at 0x8000F960`, stream2 loaded, then a silent exit with code -1073741819 (0xC0000005, access violation).

**1. The VERIFY check**
- Byte order was handled correctly: the check reads RAM with `MEM_B`, which flips the address with `^ 3`.
- The bug was the address type. The line was `MEM_B(i, (int32_t)stream.ram)` with an unsigned 32-bit `i`. In C++ a signed 32-bit plus an unsigned 32-bit gives an unsigned 32-bit, so the address is not sign-extended to 64 bits. The macro then subtracts `0xFFFFFFFF80000000`, and the result is 4 GB too high.
- Proof: the same expression in a small standalone test gives offset 0x10000F963 as written and 0xF963 with a 64-bit address. The runtime reserves exactly 4 GB for game memory (`allocation_size` in `librecomp/addresses.hpp`), so the check read memory outside that block: something unrelated for stream1, and unmapped memory for stream2.
- Counts worked out from `build/kigold.decompressed.z64` for stream1: 219210 bytes would differ with a byte-order mistake, 180446 if RAM were all zero. The log said 183963, so neither; the check was reading mostly empty memory that is not game RAM.
- The stream table lookup (`MEM_W(8 * i, STREAM_TABLE)`) is fine: both sides are signed there. `missing_funcs.cpp` is fine: it uses the 64-bit register value.
- Fix: `gpr ram = (gpr)(int32_t)stream.ram;` and `MEM_B(i, ram)`, with a comment. **Rule for our code: an address given to a `MEM_` macro must be a `gpr` (or come straight from `ctx->rN`).**
- Read on paper and found sound: the runtime's `osPiStartDma` adds the ROM base to the plain ROM offset the game passes, the overlay loader never writes to game RAM, and the inflate functions (0x80000960 to 0x80001DF0) have no register jumps or inner labels.

**2. Why `ra=0x00000000`**
- N64Recomp turns `jal` into a plain C call and never writes the return address into `ctx->r31`. The generated code only reads `r31` back from the stack. So it is still the 0 the thread started with. It can never tell us the caller, so `ra` is removed from the log lines.

**3. The silent exit**
- 0xC0000005 is a Windows access violation: a read or write of memory that is not mapped.
- No VERIFY line was printed for stream2, so it died after "stream2 loaded" and before the check finished. Likeliest cause by far: the check itself, reading 0xE8B40 bytes at 4 GB past stream2. Without `KIGOLD_VERIFY_INFLATE` set this crash would not have happened.
- Not proven: that nothing else goes wrong after stream2. What comes next is stream1 calling 0x801ACB20 through a register.
- New log line for that: `[kigold][entry] entered streamN at 0x...`, printed at the start of `stream1_entry`, `stream2_entry` and `stream3_entry` (three `[[patches.hook]]` entries in `kigold.toml`, function `kigold_on_stream_entry`). It stops after 32 lines.

**Commands**
- `python3 tools/regen.py`: exit 0, the three new hook lines are in the generated code.
- Build: `Build OK`.

**Next**
- Third run with `KIGOLD_VERIFY_INFLATE` set. Expected: `VERIFY: stream1 OK`, `entered stream1`, `stream2 loaded`, `VERIFY: stream2 OK`, `entered stream2`. If VERIFY still says WRONG, the inflate is really wrong this time.

## 2026-10-12: First run crash, missing function start at 0x80000450 (Phase 2, task 7f)

**Result: the first run stopped with `Failed to find function at 0x80000450`. Cause found and fixed in the symbols. Regen and build pass. The exe was not run again**, so the fix is unproven until BlackCRT runs it (ground rule 1).

**The first run** (BlackCRT, `build-msvc/firstrun.log`): RT64 found the graphics card, the runtime printed "Initializing recomp heap", then the error. No inflate lines, so it died before the first inflate.

**Cause**
- Who jumps there: the entry point itself. `func_80000400` (set as the entry in `kigold.toml` and `main.cpp`, both correct) clears memory, sets `$sp`, then does `lui $t2, 0x8000` / `addiu $t2, $t2, 0x450` / `jr $t2` at 0x8000042C.
- A `jr` through a register becomes `LOOKUP_FUNC(ctx->r10)` in the generated code: the runtime looks the address up in its table of function starts.
- 0x80000450 was not missing, it was the middle of a function. splat had made one function from 0x80000400 to 0x800004AC and marked 0x80000450 only as an inner label (`alabel D_80000450`). The table only holds function starts, so the lookup failed.
- It really is its own function: seven nops sit between the `jr` and 0x80000450, and 0x80000450 opens its own stack frame (`addiu $sp, -0x20`, `sw $ra`), calls `osInitialize`, creates and starts thread 1 (entry `func_800004AC`), and returns with `jr $ra`. This is the usual libultra start: a tiny entry stub that jumps to the boot function.

**The fix**
- One line in `disasm/symbol_addrs.txt`: `func_80000450 = 0x80000450; // type:func`, with the evidence in a comment. The name is the plain default, nothing invented.
- `python3 tools/regen.py`: exit 0. `syms/dump.toml`: `func_80000400` is now 0x34 bytes, new `func_80000450` is 0x5C bytes. 1434 functions became 1435. `RecompiledFuncs/recomp_overlays.inl` now lists `func_80000450` at offset 0x50.
- Build: `Build OK`, exe linked.

**Stuck / unknown**
- Other places may jump through a register into the middle of a function. `gen_symbols.py` already counts inner labels inside functions (`func_entries`); if the same error shows with another address, check that address the same way first.

**Next**
- BlackCRT runs the exe again with `KIGOLD_VERIFY_INFLATE` set.

## 2026-10-12: Menu assets and controller database (Phase 2, task 7e)

**Result: the build now puts a complete `assets` folder and `recompcontrollerdb.txt` next to the exe. Build passes. The exe was not run**, so whether the launcher really draws is still unproven (ground rule 1).

**Decision (BlackCRT, final):** commit the text files if their license allows it in a GPL-3.0 repo; download the fonts at configure time, pinned and hash checked; no font in git, no guard change.

**What RecompFrontend loads at our pin** (searched in its source): `recomp.rcss`, `NotoEmoji-Regular.ttf`, `promptfont/promptfont.ttf`, the primary font our `main.cpp` registers (`InterVariable.ttf`), and 11 icons: `Caret`, `Cont`, `Keyboard`, `PlusKeyboard`, `Question`, `Quit`, `RecordBorder`, `RecordSpinner`, `Reset`, `Trash`, `X`. It never loads a controller database; our `main.cpp` already did, from the exe's folder.

**Where each file comes from** (full table with hashes in `docs/ASSETS.md`)

| File | Source | License | In git |
| --- | --- | --- | --- |
| `menu/recomp.rcss` | written by us. WM2K's is only a placeholder too; the real styles are built into RecompFrontend | ours, GPL-3.0 | yes |
| `menu/icons/*.svg` (11) | BanjoRecomp `assets/icons/`, commit `dbd5215` | GPL-3.0 | yes |
| `recompcontrollerdb.txt` | BanjoRecomp, same commit. Data from SDL_GameControllerDB | GPL-3.0, data zlib | yes |
| `InterVariable.ttf` | rsms/inter v4.1 | OFL 1.1 | no, downloaded |
| `NotoEmoji-Regular.ttf` | googlefonts/noto-emoji v2.034 | OFL 1.1 | no, downloaded |
| `promptfont.ttf` | Shinmera/promptfont v1.5 release zip | OFL 1.1 | no, downloaded |

- Nothing was copied from `lib/`. WM2K's copies in `build/ref/` were only used as a checklist and for hash comparison.
- Why BanjoRecomp for the icons: Zelda64Recomp has only 5 of the 11. Banjo: Recompiled is by the RecompFrontend authors and has all of them. Its repo is GPL-3.0 with no separate asset terms, and the files carry no third-party marks. The 11 files are identical to WM2K's copies.
- Why the filtered controller database: the full upstream file is 609 KB, over the guard's 512 KB limit.
- **The folder is `menu/`, not `assets/`:** the guard blocks any folder named `assets` (reserved for extracted game data). The build copies `menu/` into `assets/` next to the exe.

**The build** (`CMakeLists.txt`)
- `kigold_download`: downloads a file unless it is already there with the right SHA-256; a failed download or a wrong hash stops the configure with a readable error and deletes the file. Tested with a deliberately wrong hash.
- Inter and Noto Emoji come as single files from the original repositories at fixed commits. PromptFont only exists inside its release zip (439 KB), so the zip is downloaded and the font and license are taken out, each checked again.
- Each font's license file is placed beside it.
- New target `KIGoldAssets`, which the exe depends on: copies everything on every build, also when the exe does not relink.
- Downloads live in `build-msvc/menu-fonts/` (git-ignored). A configure now needs internet once.

**Checked after the build**
- `build-msvc/assets/`: `recomp.rcss`, 2 fonts and their licenses, `promptfont/` with font and license, `icons/` with 11 files. `build-msvc/recompcontrollerdb.txt` is there.
- The three fonts and the database have the pinned hashes; the 11 icons are identical to the pinned source.

**Stuck / unknown**
- **PromptFont is not the exact build other recomps ship.** Theirs (101,696 bytes) matches none of the releases v1.2 to v1.10. v1.5 is the closest. If a controller button picture is wrong in the menus, look here first.
- BanjoRecomp's README has a "No-AI stance" for contributions to their project. It is not a license term, and GPL-3.0 allows the reuse, but it is worth knowing where the icons come from.
- The icons' license is the repository's GPL-3.0; there is no per-file statement. Added to the before-going-public check.

**Next**
- The first run, with `KIGOLD_VERIFY_INFLATE` set.

## 2026-10-12: Safe stand-in for `__osSiRawStartDma` (Phase 2, task 7d)

**Result: `__osSiRawStartDma` now answers like a console with nothing plugged in and sends the "done" message, so no caller waits forever. Build passes. The exe was not run.** Decisions from 7c (BlackCRT): yes to the stand-in, and the `_game` suffix is fine.

**What was read first**
- `func_800341BC` builds the status request: one 8-byte record per port, `FF, 01, 03, command, FF, FF, FF, FF`, then `FE` as the end mark, and 1 in the last byte of the 64-byte block. That is the console's standard layout: padding byte, send length, receive length, then the data.
- `func_80034294` unpacks the reply. For each port it takes the top two bits of the receive length byte as an error code (`(byte & 0xC0) >> 4`). If the code is not zero it stores it and skips the rest of that record. "No response" is bit 7 of that byte, which gives code 8. So the planned reply is exactly what the game understands.
- `func_8003BF10` fills its buffer with `FF` bytes between sending the request and reading the reply. So the reply cannot be made from the buffer at read time.

**The stand-in** (`src/game/missing_funcs.cpp`)
- First argument 1 (send): copy the 64-byte block, walk its commands, set bit 7 on each receive length, clear the control byte. The receive bytes stay as they were, as on the console.
- First argument 0 (read): write that kept block back into the game's buffer.
- Both: call the runtime's `ultramodern::send_si_message()`, return 0, and print the loud `[kigold][MISSING] __osSiRawStartDma ...` line (now ending in `STAND-IN, answers as nothing plugged in`).
- `__osSiGetAccess` and `__osSiRelAccess` are unchanged: log only.
- One-off check outside the repo: the walker compiled on Linux and was fed the game's two layouts. Status request: all four ports get error code 8. Block read: only the receive length byte and the control byte change. A block of garbage does not run past the end.

**What the game then does (static reading)**
- `func_8003BF10` (block read): error code 8 is not the retry code 4, so it gives up at once and returns 8. No hang.
- `func_80034020`: no port bit is set. At most 3 tries. No hang.
- `func_800343F4` (status check): returns 1 (no pak) **or 2 (new pak)**. On "no response" the unpacker leaves the status byte unset, and this function tests that byte before the error code, so the result depends on leftover stack bytes. A real console with nothing plugged in has the same behavior. Both results are errors for the caller. No hang either way.

**Stuck / unknown**
- The static reading from 7c still says none of this is reached while no pak is reported. Only the first run can show it.
- Open choice: answer status requests as "controller present, no pak" instead of "no response". That would make `func_800343F4` always return 1. It is a guess about a path that should never run, so it was not done.

**Next**
- Menu assets decision, then the first run with `KIGOLD_VERIFY_INFLATE` set.

## 2026-10-12: CRC functions translated from the game, serial-port callers checked (Phase 2, task 7c)

**Result: the two CRC functions now run the game's own code. Regen and build pass. The exe was not run.** The three serial-port stand-ins are unchanged (log only); what to do with them is an open decision. The TLB functions were not touched.

**Part A: `__osContAddressCrc` (`0x80041210`) and `__osContDataCrc` (`0x800412C0`)**
- Why they were skipped: N64Recomp has a built-in list of libultra names (`src/symbol_lists.cpp`). A function whose name is on it gets `_recomp` added and no body, because the runtime is expected to supply it. The match is by exact name.
- There is no config setting that takes a name off that list. `[patches] renamed` only adds the `_recomp` suffix and `ignored` only skips (read in N64Recomp's `src/main.cpp` and `src/config.cpp`).
- So the fix is a name that is not on the list. `tools/gen_symbols.py` has a new short list, `KEEP_GAME_CODE`, with these two names. When it writes `syms/dump.toml` it adds `_game` to them: `__osContAddressCrc_game`, `__osContDataCrc_game`. The proven names stay as they are in `disasm/symbol_addrs.txt`. The tool refuses to run if a listed name is not in the split. Its test went from 26 to 30 checks.
- `_game` is our marker, not a libultra name. It only says "translated from the game's code".
- Checked in the generated code after regen: both functions have real bodies (stack arithmetic only, no calls out), all 6 call sites call the new names, and no call to the old `_recomp` names is left.
- The two log-only bodies are gone from `src/game/missing_funcs.cpp`. The build links without them, which confirms nothing asks for them any more.
- Effect: the save checksum (`func_801CD08C_stream2`, `func_801CD1C4_stream2`) now gets a real result. Not proven until a run.

**Part B: the 7 callers of `__osSiGetAccess`, `__osSiRelAccess`, `__osSiRawStartDma`**
- **None can be named.** The reference library has the Controller Pak objects (`pfsinit`, `pfsisplug`, `pfsgetstatus`, `contramread`, `contramwrite` and more, in up to three library versions). The fingerprint tool compared every game function against them and none of the 7 is an exact match. They are not even in the "likely" list. KI Gold's copies are most likely from an older library version than our references.
- Naming would not help anyway for most of them: the runtime at our pin has no body for `osPfsInit`, `osPfsIsPlug`, `__osPfsGetStatus`, `__osContRamRead` or `__osContRamWrite`. It only has the higher-level ones (`osPfsInitPak`, `osPfsFindFile` and so on, all answering "no pak").
- What each one does, from reading the code. The "looks like" column is a lead only, not a name.

| Function | What it does | Looks like | Serial-port calls |
| --- | --- | --- | --- |
| `func_800343F4` (queue, port) | sends a status request, waits for the reply, returns 0, 1, 2 or 4 | a pak status check | `RawStartDma` twice, each followed by a blocking `osRecvMesg` |
| `func_80034350` (queue, struct, port) | calls `func_800343F4`, on 0 fills the struct | a pak start | `GetAccess`, `RelAccess` |
| `func_80034020` (queue, result) | asks all ports, up to 3 tries, writes one bit per port with a pak | a "which ports have a pak" check | all three. No direct call to it in any segment |
| `func_8003BF10` | reads one 32-byte block, checks its CRC, up to 3 tries | a pak block read | all three, plus `__osContDataCrc` |
| `func_8003C2A0` | same call pattern as the read (not read line by line) | a pak block write | all three, plus `__osContDataCrc` |
| `func_8003C13C`, `func_8003C4C4` | build the request bytes for the read and the write | request builders | none. They only call `__osContAddressCrc`, which is real code now |

**What happens at the first run**
- **Most likely none of the three is ever called.** The only way in from the game is `func_801CCF4C_stream2`. It first asks which ports have a pak (`func_801CCBA0_stream2`), and that goes through `osContStartQuery` and `osContGetQuery`, which the runtime replaces. The runtime fills the status from what `main.cpp` reports, and we report no pak, so the status is 0 and no port bit is set. `func_80034350` is only called for a port whose bit just turned on.
- The file search (`func_801CD3A4_stream2`, which calls `func_800344D0`) is skipped too when the port bit is clear. Checked at one call site (`0x801CD6FC`). The other sites (`0x801CD9CC`, `0x801CDC84`) follow a call to `func_801CCF4C_stream2` in the same way but were not read line by line.
- This is static reading only. A `[kigold][MISSING]` line in the first run log would prove it wrong.

| Stand-in | If it is reached anyway | Why |
| --- | --- | --- |
| `__osSiGetAccess`, `__osSiRelAccess` | Harmless | They only take and release a lock on the serial port. Doing nothing is fine with one caller at a time |
| `__osSiRawStartDma` | **Hang** | Every caller then waits in a blocking `osRecvMesg` for the "done" message, and nobody sends it. That game thread never wakes |
| `func_8003C13C`, `func_8003C4C4` | Harmless | Plain code, no hardware |

**Suggested safe stand-in (not done, needs a decision)**
- `__osSiGetAccess` and `__osSiRelAccess`: do nothing, keep one log line.
- `__osSiRawStartDma`: answer like a console with nothing plugged in, then send the "done" message with the runtime's own `ultramodern::send_si_message()` and return 0. For a read (first argument 0) that means walking the 64-byte request buffer and setting the "no response" bit (bit 7 of the receive length) on every command. Keep the loud log line.
- Expected effect: `func_800343F4` returns 1 (no pak), the block read and write give up after their retries with an error, and no thread waits forever.
- Not checked yet: `func_80034294`, which unpacks the reply for `func_800343F4`, was not read. It must be read before writing the stand-in.
- Just sending the message without touching the buffer is not safe: the game would read back its own request bytes as the reply.

**Regen and build**
- `python3 tools/test_gen_symbols.py`: 30/30.
- `python3 tools/regen.py`: exit 0. `syms/dump.toml` changed by two lines (the two names). The call report still lists `__osSiGetAccess_recomp` 4, `__osSiRawStartDma_recomp` 8, `__osSiRelAccess_recomp` 6.
- `tools/build.ps1 -Build`: exit 0, `KIGoldRecompiled.exe` linked, no errors, no undefined names.

**Stuck / unknown**
- Whether `func_80034020` is reached through a pointer. No direct call exists.
- Everything else in the 7a/7b entry still stands.

**Next**
- Decision on the `__osSiRawStartDma` stand-in, the menu assets decision, then the first run with `KIGOLD_VERIFY_INFLATE` set.

## 2026-10-12: Inflate hooks, and the ROM question settled (Phase 2, tasks 7a and 7b)

**Result: the hooks are in, regen and build pass. The exe was not run.** Nothing here is proven until the first run shows the log lines (ground rule 1).

**How the runtime learns a section is loaded (read from `lib/N64ModernRuntime/librecomp/src/overlays.cpp`)**
- It keeps a table from RAM address to C function. A lookup that misses prints `Failed to find function at 0x...` and exits.
- `load_overlays(rom, ram, size)` fills the table from our generated section table. It never reads the ROM; the ROM offset is only the ID of a section.
- At start the runtime does this once for ROM `0x1000`, 1 MB. That covers the boot section only.
- `unload_overlays(ram, size)` removes sections. A range that covers only part of a loaded section prints `Cannot partially unload section` and exits.
- In our generated code the jump from boot into stream 1 (`0x800005D4`) is a table lookup, so without a hook the game dies there. The jumps into `stream2_entry` and `stream3_entry` are direct C calls and need no table; function pointers and thread starts inside the streams do.

**The ROM question: no decompressed ROM at run time**
- The recompiled boot code reads the compressed streams from the user's original ROM with `osPiStartDma` and runs the game's own inflate into RAM. The original 12 MB is unchanged in our layout, so every ROM read is right on the original ROM.
- So the hash in `main.cpp` was already correct. `tools/unpack_rom.py` stays a developer tool for regeneration. Users never run it.
- The runtime's `decompression_routine` field is only used for mods (`mods.cpp`). Deferred (decision 2026-10-12).

**The hooks** (`[[patches.hook]]` in `kigold.toml`, code in `src/game/inflate_hooks.cpp`)

| Hook | Where | What it does |
| --- | --- | --- |
| `kigold_on_rom_read` | start of `boot_rom_read` (`0x80000740`) and `func_800007B4` | remembers which ROM offset each buffer was last filled from |
| `kigold_on_inflate_start` | start of `boot_inflate` (`0x80000900`) | identifies the stream, loads its functions, logs one line per inflate |
| `kigold_on_inflate_end` | before the `jr ra` at `0x80000950` | developer check only |

- A stream counts only when both ends agree: the destination address, and the ROM offset of the source buffer compared with entries 0, 1, 2 of the game's own stream table in RAM (`0x800071E0`). No ROM offsets are written in our code.
- A half match (right destination with the wrong source, or the reverse) prints a `WARNING` line and loads and unloads nothing.
- A remembered ROM read is used up by one inflate. A second inflate from the same buffer without a new read counts as unknown source.
- Before stream 2 or 3 is loaded, the whole shared range (`0x801ACB20`, size `0xE8B40`) is unloaded. Stream 3's image lies fully inside stream 2's.
- Why one hook on the helper and not three at the call sites: `boot_inflate` has 19 call sites and only 3 are understood. A reload from one of the other 16 would be missed.
- **Developer check, off by default:** set the environment variable `KIGOLD_VERIFY_INFLATE` to the path of `build/kigold.decompressed.z64`. Each code stream is then compared with that file right after the game inflates it (`VERIFY: stream1 OK` or `WRONG` with the first bad address). The file stays local, as always.

**Load order evidence (static only)**
- In `stream1_main` the stream 2 load (`0x8000FB14`) comes first, `stream2_entry` runs and returns, and the path to the stream 3 inflate (`0x8000FC90`) has only forward skips.
- No function in stream 2 calls stream 3 directly, or the reverse.
- Open hint: the EEPROM save and load functions are in stream 2 at `0x801CD2C4`, inside the area stream 3 overwrites. Either saves only happen during start-up or stream 2 is reloaded later. The inflate log will show it (decision 2026-10-12: no static trace now).

**Regen and build**
- `python3 tools/regen.py`: exit 0, the four hook lines are in `RecompiledFuncs/funcs_0.c`.
- `tools/build.ps1 -Build`: exit 0, `KIGoldRecompiled.exe` linked. No warnings in our files; 233 in `lib/` as before.

**What to look for at the first run**

| Log line | Meaning |
| --- | --- |
| `[kigold][inflate] dst=0x8000F960 ... stream1 loaded`, then stream2, then stream3 | Good. A later `stream2 loaded` means stream 2 is reloaded |
| `[kigold][inflate] WARNING ...` | An inflate that half matches a code stream. Nothing was loaded; needs a look |
| `Failed to find function at 0x8000F960` | The stream 1 hook did not match |
| `Failed to find function at 0x801.....` | A pointer into an unloaded stream, or a function start missing from the symbol file |
| `Cannot partially unload section` | A bug in our unload range |
| `VERIFY: ... WRONG` | The recompiled inflate produces wrong bytes |

**Stuck / unknown**
- A direct C call into a stream that is not loaded gives no error. The inflate log is the only view of the order.
- Everything in the 6c entry still stands: TLB is log only, 5 libultra bodies are log only, the menu assets are missing.

**Next**
- Menu assets decision, then the first run, with `KIGOLD_VERIFY_INFLATE` set.

## 2026-10-10: main.cpp, stand-in bodies, first compile and link (Phase 2, task 6c)

**Result: it compiles and links. `build-msvc/KIGoldRecompiled.exe` exists (12.1 MB). The exe was not run; the first run is task 7 and needs the inflate hooks first.** Linking only proves every name has a body. It says nothing about whether the game works (ground rule 1).

**Decisions on the 6b questions (BlackCRT, 2026-10-10)**
1. Launcher assets: decide at the first run. Lean: commit the text files if their licenses allow, download the fonts at configure time. Now part of the first-run item in `PLAN.md`.
2. Submodule pins: keep as they are. "Fork the 3 libraries under BlackCRT with a branch at each pin, point `.gitmodules` there" is on the before-going-public list.

**New files (all our own)**

| File | What it does |
| --- | --- |
| `src/main/main.cpp` | Program start, 284 lines (WM2K's is 959). Describes the game to the runtime, registers the code sections, sets up window, sound, input and microcode callbacks, calls `recomp::start`. Follows WM2K's order of steps, without its diagnostics, logo, auto-boot and custom key bindings |
| `src/main/register_overlays.cpp` | Hands the generated section table (boot + 3 streams) to the runtime. Adapted from WM2K |
| `src/game/tlb.cpp` | `osMapTLB_recomp` and `osUnmapTLB_recomp`. They log their arguments and do nothing |
| `src/game/missing_funcs.cpp` | Five loud log-only bodies (see the linker list) |
| `include/kigold_decls.h` | Shared declarations |
| `patches/ui_funcs.h` | Not planned, needed by the build (see "Build errors") |

- `CMakeLists.txt`: the four `.cpp` files and `include/` added.

**Save type: 4K EEPROM, plus Controller Pak code** (evidence from the libultra calls, addresses only)
- The three EEPROM functions are named by exact match (`build/libultra_symbols.txt`): `osEepromProbe` `0x800365D0`, `osEepromLongWrite` `0x80036640`, `osEepromLongRead` `0x80036780`. None of the named libultra functions is an SRAM or FlashRAM one. That is not full proof of absence, because 61 libultra functions are still unnamed.
- All EEPROM use is in three stream2 functions:
  - `func_801CD2C4_stream2` (save): `osEepromProbe`, then `osEepromLongWrite(queue, address 0, buffer, length 0x200)`.
  - `func_801CD324_stream2` (load): `osEepromProbe`, then `osEepromLongRead(queue, address 0, buffer, length 0x200)`.
  - `func_801CCF4C_stream2`: `osEepromProbe` only, result stored at `0x802D3B96`.
- **0x200 bytes is 512 bytes, exactly the size of a 4K EEPROM** (a 16K one holds 2048). The game reads and writes the whole thing in one call, at address 0, with a constant length.
- The probe result is only tested for zero or not zero. The game never checks for the 16K answer (2). So it would also run on a 16K chip, but it only ever uses 4K worth. `main.cpp` sets `recomp::SaveType::Eep4k`, and the runtime then answers the probe with 1 (4K).
- The save has a checksum: both functions call a helper (`func_801CD1C4_stream2` before the write, `func_801CD08C_stream2` after the read) that calls libultra's `__osContDataCrc` on the buffer (length argument 0x200 there too).
- **Controller Pak, also used.** `func_801CD3A4_stream2` calls `func_800344D0` with company code `0x3031` ("01", Nintendo) and game code `0x4E4B4945` ("NKIE"), plus name pointers and a result pointer. That is the argument shape of libultra's `osPfsFindFile`. The first argument is an entry in a table at `0x802D3AB0` with 0x68 bytes per entry (the size of libultra's `OSPfs`), and `func_801CCF4C_stream2` passes entries 0 and 1 of that table with channel numbers 0 and 1 to `func_80034350`. So the game looks for a Controller Pak in ports 1 and 2. These two functions are **not named**: the shape fits, but there is no exact-match proof.
- The runtime cannot emulate a Controller Pak (its `Pak` type only has `None` and `RumblePak`), so `main.cpp` reports no pak. What the game stores there is not known yet.

**Build errors and what was done**
- Our five source files compiled without errors on the first try.
- One error, in a submodule file, fixed in our own repo without touching the submodule: `lib/RecompFrontend/recompui/src/api/ui_api_events.cpp` includes `patches/ui_funcs.h` from the root of the project that builds it (its own comment: "TODO: Forced game includes"). We had no such file. It only needs the UI event types, which RecompFrontend also ships in its public header `recompui/event_structs.h`. So `patches/ui_funcs.h` is 3 lines of ours that include that header. WM2K has its own copy of this file for the same reason.
- No change to generated code or to any submodule. `git submodule status` shows the three pins, no local changes.

**The linker's list of missing names: 7**
- Predicted before building by searching the runtime source for each of the 55 names: 48 found, 7 not.
- Confirmed by the linker itself: one extra link with `tlb.cpp` and `missing_funcs.cpp` taken out of the build reported exactly these 7 (`undefined symbol`), then the build file was put back.

| Name | Calls | Called from | What was done |
| --- | --- | --- | --- |
| `osMapTLB_recomp` | 4 | `func_8001CF5C`, `func_801C57B0_stream2` | `src/game/tlb.cpp`: logs all 6 arguments, maps nothing |
| `osUnmapTLB_recomp` | 2 | the same two | `src/game/tlb.cpp`: logs the index |
| `__osSiGetAccess_recomp` | 4 | `func_80034020`, `func_80034350`, `func_8003BF10`, `func_8003C2A0` | `src/game/missing_funcs.cpp`: loud log only |
| `__osSiRelAccess_recomp` | 6 | the same four | loud log only |
| `__osSiRawStartDma_recomp` | 8 | `func_80034020`, `func_800343F4`, `func_8003BF10`, `func_8003C2A0` | loud log only |
| `__osContAddressCrc_recomp` | 2 | `func_8003C13C`, `func_8003C4C4` | loud log only |
| `__osContDataCrc_recomp` | 4 | `func_8003BF10`, `func_8003C2A0`, `func_801CD08C_stream2`, `func_801CD1C4_stream2` | loud log only |

- Why the last five are missing: N64Recomp leaves these libultra names for the runtime to supply, and the runtime at our pin has no body for them. In other games they are only called from inside libultra functions the runtime replaces whole. Here they are called from unnamed functions (Controller Pak style code in boot and stream1) and from the game's own save checksum code.
- **These log-only bodies will cause wrong behavior when reached, on purpose loudly.** Two known cases:
  - `__osContDataCrc` is called by the EEPROM load and save path. With a log-only body the checksum is garbage, so a load will likely be judged corrupt.
  - After `__osSiRawStartDma` the callers wait for a reply message that will never come, so a thread can hang there.
- Likely proper fix for the two CRC functions (suggestion, not done): they are plain arithmetic and their code is in the ROM at known addresses (`0x80041210`, `0x800412C0`), so letting N64Recomp translate them under another name would give correct results. That is a `kigold.toml` or symbol change and a regeneration.

**The build**
- Command: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\src\ki-gold-recomp\tools\build.ps1' -Build`
- **Full build from nothing (`-Build -Fresh`): 117 seconds**, 908 steps, configure 10.9 s of that. Exit 0. An incremental build of our files and the final link: 26 seconds.
- Output in `build-msvc/` (git-ignored): `KIGoldRecompiled.exe` 12.1 MB, `KIGoldRecompiled.map` 10 MB, and the copied `SDL2.dll`, `dxil.dll`, `dxcompiler.dll`.

**Warnings**
- None in our own files.
- 233 compiler warnings, all inside `lib/` (unused parameters and variables, signed/unsigned compares, missing field initializers). Normal noise for these libraries.
- Worth knowing: 4 operator-precedence warnings in the runtime's `rsp_vu_impl.hpp` (the RSP vector unit, used by our audio microcode). Upstream code, used by every recomp, so probably fine, but it is the first place to look if sound math is wrong.
- 3 CMake deprecation notices in third-party build files, as in 6b.
- `RecompiledFuncs` is compiled with warnings off, so the generated code reported nothing either way.

**Stuck / unknown**
- **The ROM question for task 7.** `main.cpp` registers the hash of the original 12 MB ROM (XXH3 64-bit `0x2952FB28B16AB571`, computed with a throwaway program, hash only). But the section table in the generated code points at the decompressed ROM layout (streams at `0xC00000` and up), which the user's ROM does not have. How the runtime gets from one to the other belongs with the inflate hooks.
- The N64Recomp version worry from 6b (generated code from `ffb39cd`, runtime header from `f8d49ca`): no compile or link problem showed up.
- One player only for now (`set_single_player_mode(true)`). Two-player setup needs a look at how RecompFrontend assigns controllers; WM2K changed its fork for that.
- No Rumble Pak is reported. The game is from 1996, before the Rumble Pak; not checked in the code.
- `RecompiledFuncs/lookup.cpp` is generated but not compiled (WM2K does not compile its copy either). Nothing asked for it at link time.
- The menu assets are still missing, so the launcher cannot draw text yet. First-run item.

**Next**
- Task 7 prep: hook the 3 inflate sites, and settle the ROM layout question above.
- Then the first run.

## 2026-10-10: Submodules, license, CMake skeleton, clean configure (Phase 2, task 6b)

**Result: the three runtime libraries are in `lib/` as submodules at the agreed pins, the repo is GPL-3.0, and `tools/build.ps1` gets a clean CMake configure (exit 0, clang-cl 19.1.5, x64).** Nothing was compiled. There is no `main.cpp` yet; that is task 6c.

**Decisions on the 6a plan (BlackCRT, 2026-10-10)**
1. Pins: N64ModernRuntime `4dc67ed`, RecompFrontend `1b98855`, rt64 `99067ac`. These are the commits WM2K's forks are built on (its forks add 10, 1 and 8 commits on top).
2. License: the repo is GPL-3.0. `COPYING` added, and each file adapted from WM2K says so at the top.
3. RecompFrontend: submodule only, never copy its files. `PLAN.md` has a "before going public" checklist with "confirm RecompFrontend's license" first.
4. Fonts and controller database: copy from the submodules at build time, do not commit them. **Could not be done as written, see "Needs a decision".**
- Also added to the Phase 2 checklist, after first link: hook the 3 inflate sites so the runtime sees streams 1 to 3 load (and swap streams 2 and 3).

**The submodules**

| Path | URL | Pin | Size on disk |
| --- | --- | --- | --- |
| `lib/N64ModernRuntime` | `github.com/N64Recomp/N64ModernRuntime` | `4dc67eda958e5bf7d347e204eaa21798bc306a41` | 33 MB |
| `lib/RecompFrontend` | `github.com/N64Recomp/RecompFrontend` | `1b988554352611b5f41900ac15241bd871285abb` | 38 MB |
| `lib/rt64` | `github.com/rt64/rt64` | `99067acfa50273249a5ec3fd8656256e0f7f3d36` | 393 MB |

- 32 nested libraries came with them. Fetched shallow (the pinned commit only, no history): about 220 MB downloaded. A full-history fetch would have been over 1 GB.
- **Fresh clone command:** `git submodule update --init --recursive --depth 1`
- **Trap:** `git submodule add` stages the pointer at the newest `main` commit. Check out the pin and `git add` the folder before running `submodule update`, or the update moves the folder back to `main`. This happened once here and was corrected; `git submodule status` now shows the three pins.

**The pins are not on any upstream branch**
- All three are real commits by Dario (the upstream author), dated 2026-01-29 and 2026-05-02. But each has diverged from upstream `main` (N64ModernRuntime: 109 commits `main` does not have, and `main` has 104 it does not; RecompFrontend 44 and 46; rt64 162 and 180). No upstream branch or tag contains them.
- They still download from the upstream URLs when asked for by full commit ID, because GitHub shares storage between a repo and its forks. So the setup works today, but it is fragile: if GitHub stops serving them, a fresh clone fails. Which repo or branch they were first pushed to was not found.
- They are reachable in the normal way from WM2K's forks (`jessetbh/*`, branch `wcw`).

**What git sees (the third-party check)**
- `git status` after adding: `.gitmodules` and three entries of type 160000 (a submodule pointer: a commit ID, no file content). No file from inside `lib/` is in our git.
- `git add -f lib/rt64/src/contrib/dxc/bin/x64/dxil.dll` is refused by git itself: "Pathspec is in submodule".
- No submodule is modified after the configure run (checked all 35).

**Guard fix (`tools/guard.py`)**
- The guard crashed on the first try: it read every staged path with `git show`, and a submodule pointer has no content to show. A crash, not a pass.
- Now it recognizes pointers (mode 160000), still runs the name checks on their path, skips the content checks, and prints them: "3 submodule pointer(s), commit ID only".
- Tested both ways: passes with the submodules staged (exit 0); a force-staged fake file with an N64 header and a `.bin` name is still blocked (exit 1). `--all` passes (GitHub Actions does not check out submodules, so it sees empty folders).

**The build files**
- `CMakeLists.txt`: adapted from WM2K's. Target `KIGoldRecompiled`. Same structure: rt64, the runtime, `RecompiledFuncs` as a static library, shader compiler settings, SDL2 2.30.3 downloaded into the build folder, RecompFrontend, then the exe. Differences: readable errors when the submodules or the generated code are missing, no icons or logo, console window in every build type for now, and no asset copy step. The exe's only source so far is `rsp/kigold_audio.cpp`.
- `tools/build.ps1`: finds Build Tools with `vswhere`, loads the x64 environment, stops if clang-cl is not x64, runs the configure. `-Build` also compiles (not used yet), `-Fresh` deletes `build-msvc/` first.
- From Ubuntu: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\src\ki-gold-recomp\tools\build.ps1'`
- The run: exit 0, "Configuring done (12.9s)", "Build files have been written to: C:/src/ki-gold-recomp/build-msvc". Warnings are CMake deprecation notices in third-party files (nativefiledialog-extended, zstd, miniz). `build-msvc/` is 38 MB and git-ignored.

**Licenses of the libraries** (read from each one's license file)

| Library | License |
| --- | --- |
| N64ModernRuntime | GPL-3.0 |
| RecompFrontend | **no license file** |
| rt64 | MIT |
| N64Recomp, ELFIO, rabbitizer, tomlplusplus, fmt, miniz, o1heap | MIT |
| sljit, xxHash (two copies) | BSD 2-clause |
| RmlUi, lunasvg | MIT |
| freetype-windows-binaries | FreeType License (prebuilt binaries) |
| ddspp, hlslpp, im3d, imgui, implot, plume, re-spirv, D3D12MemoryAllocator, VulkanMemoryAllocator, volk, SPIRV-Headers | MIT (SPIRV-Headers uses the Khronos MIT-style text) |
| stb | MIT or public domain |
| nativefiledialog-extended | zlib |
| spirv-cross | Apache-2.0 |
| Vulkan-Headers | Apache-2.0 or MIT |
| zstd | BSD or GPL-2.0, your choice |
| mupen64plus-core | GPL-2.0. rt64 only uses its API headers |
| dxc (`rt64/dxc-bin`) | **no license file.** Prebuilt Microsoft shader compiler: `dxc.exe`, `dxcompiler.dll`, `dxil.dll` |
| mupen64plus-win32-deps | **no license file at the top.** A bundle of prebuilt SDL2, freetype, libpng, zlib, boost and others, each with its own license |
| SDL2 2.30.3 (downloaded by CMake, not a submodule) | zlib |

- Nothing here conflicts with GPL-3.0 for a source-only repo, as far as a license-file reading goes. This is not legal advice. The three without a license file are the ones to settle before going public.
- The build copies `SDL2.dll`, `dxil.dll` and `dxcompiler.dll` next to the exe. That is fine for a local build; it matters only if a binary were ever shared, which the plan rules out.

**Needs a decision**
1. **Assets (decision 4).** RecompFrontend loads `recomp.rcss`, three fonts (`InterVariable`, `NotoEmoji-Regular`, `promptfont`) and `icons/*.svg` from an `assets` folder next to the exe, but ships none of them. No submodule has them, or a controller database. WM2K commits its own copies. So "copy from the submodules" is not possible. Options: download them at configure time from their original projects at pinned versions (keeps them out of our git); or commit the text files (`.rcss`, `.svg`, controller database) and download only the fonts; or commit everything (the guard blocks font files today). Not needed for configure or for the first link, needed for the first run.
2. **The pins.** Keep the upstream URLs with these fragile pins (as decided, works today), or point `.gitmodules` at a repo where the commits are on a real branch (WM2K's forks, or forks under BlackCRT's account).

**Stuck / unknown**
- Nothing compiled. A clean configure only proves CMake can read every build file and find the tools (ground rule 1).
- The runtime's `recomp.h` comes from N64Recomp `f8d49ca` (the commit N64ModernRuntime pins). Our generated code was made with N64Recomp `ffb39cd`. If they disagree, the first compile will show it.
- The intrin.h workaround in `CMakeLists.txt` is for clang 20 and newer. We have 19.1.5, so it is untested here but harmless.

**Next**
- Task 6c: `main.cpp` and the bodies the runtime does not provide (the 55 names with no body), then the first compile and link.

## 2026-10-10: RSPRecomp config for the audio microcode (Phase 2, task 5)

**Result: the audio microcode translates. `rsp/kigold_audio.toml` is in the repo, RSPRecomp is step 6 of `tools/regen.py`, and the run is clean: exit 0, no warnings, `rsp/kigold_audio.cpp` is 73,112 bytes (2,272 lines).** Nothing was compiled or run as a game.

**RSPRecomp build**
- Already built. `build/N64Recomp/build-linux/RSPRecomp` came out of the same build as N64Recomp (checkout `ffb39cd`, system tools). No new build was needed.

**The config (`rsp/kigold_audio.toml`)**
- Format read from `read_config` in `RSPRecomp/src/rsp_recomp.cpp`: six required keys (`text_offset`, `text_size`, `text_address`, `rom_file_path`, `output_file_path`, `output_function_name`) and the optional `extra_indirect_branch_targets`. Paths are relative to the config file's folder, so the ROM path is `../build/kigold.decompressed.z64`.
- Values: offset `0xC34170`, size `0xE20`, address `0x04001080`, function name `kigold_audio_ucode` (a neutral name in WM2K's style; `aspMain` is not proven).
- The 16 command table entries at audio data + 0x10 (decompressed ROM `0xC3A4F0`, 16-bit each), in table order:
  `0x1118 0x1470 0x11DC 0x1B38 0x1214 0x187C 0x1254 0x12D0 0x12EC 0x1328 0x140C 0x1294 0x1E24 0x138C 0x170C 0x144C`
  All 16 are different, word aligned, and inside the code. Entries 12 and 13 are the `0x1E24138C` marker word from session 6.

**How the address `0x04001080` was confirmed** (throwaway script, addresses only)
- The boot microcode says so: at boot + 0x14 it loads `0x1080` into r7, and at boot + 0x38 it does `jr r7`.
- The audio code agrees. Its `j`/`jal` instructions hold absolute addresses (43 instructions, 13 targets, `0x10D4` to `0x1DBC`). Tested every start address from `0x1000` to `0x11FC`: with `0x1080`, 18 of the 19 `jal` and table targets land right after an unconditional jump and its delay slot, which is where a routine starts. The next best address scores 4.

**How the size `0xE20` was confirmed**
- Traced the code from `0x1080` and the 16 table entries, following every branch and jump. The last instruction reached is at `0x1E98`, so the code ends at `0x1E9C`. One zero word of padding follows, up to `0x1EA0` = `0x1080 + 0xE20`. So: `0xE1C` bytes of code plus 4 of padding.
- No branch, jump or table entry points outside the block.
- The trace reaches `0xE0C` of the `0xE20` bytes. Not reached: one word at `0x1114`, three at `0x1144`, and the padding word. RSPRecomp translates the whole block anyway.

**Git safety, tested the same way as task 3**
- `git add rsp/kigold_audio.cpp` is refused (`.gitignore` line 12, `rsp/*.cpp`). Forced in with `git add -f`, `tools/guard.py --staged` blocks it: "this is generated code (recompiler output)", exit 1. Unstaged again with `git restore --staged`. No guard or `.gitignore` change was needed.

**The regen step**
- `tools/regen.py` now has 7 steps; RSPRecomp is step 6, after the cleanup. It deletes the old `.cpp` first, so a failed run cannot leave a stale file.
- **RSPRecomp exits 0 even when it prints "Unhandled instruction"** (the source ignores that result), and it prints nothing on success. So the step fails on any output from it, not only on a non-zero exit code.
- The run (`python3 tools/regen.py`): exit 0. N64Recomp numbers are the same as before (1434 functions, 235 fall-throughs fixed, 275 calls to 55 names with no body). RSPRecomp printed nothing.
- The output has one function, 30 indirect jump cases (our 16 plus the return addresses RSPRecomp found itself), and all 16 table entries are among them.

**Compared with WM2K (`rsp/wm2k_audio.toml`)**

| | WM2K | KI Gold |
| --- | --- | --- |
| Keys | the same six plus `extra_indirect_branch_targets` | the same |
| `text_address` | `0x04001080` | `0x04001080` |
| `text_size` | `0xC54` | `0xE20` |
| Table entries | 14 | 16 |
| Paths | relative to `rsp/`, output `wm2k_audio.cpp` | relative to `rsp/`, output `kigold_audio.cpp` |

- The shape is the same. The numbers are not, and should not be: **WM2K does not use the common audio microcode.** Its config comment says it is a newer AKI revision, "NOT aspMain", with 14 commands. Ours has the 16 commands of the common one.
- WM2K had one table entry stored without the `0x1000` bit (`0x02B0` for `0x12B0`). All 16 of ours already have it. RSPRecomp's jump code ORs in `0x1000` at run time either way.

**Stuck / unknown**
- "It translates" is not "it works". Sound is only proven when the game runs (ground rule 1).
- The generated file includes `librecomp/rsp.hpp`. The project has to register `kigold_audio_ucode` with the runtime for audio tasks; that belongs to the skeleton task.
- What the 4 unreached words are was not looked at.

**Next**
- Phase 2 checklist: project skeleton from the WM2K template, then first compile and link.

## 2026-10-10: Dropped delay slots fixed in the tracer (Phase 2, task 4b)

**Result: it was a tracer bug (two of them), not a real jump. Fixed in `tools/stream3_map.py`. The 3 dropped instructions are back in the generated C, and `tools/regen.py` now stops if a function is ever cut before a delay slot again.** stream3 has 605 functions (was 613), the symbol file 1434 (was 1442). Nothing was compiled or run as a game.

**Why the tracer cut at a delay slot**
- Nothing jumps to, calls, or stores any of the 4 delay slot addresses. No branch, no jump table entry, no word in the data.
- Each became a function start because the tracer believed the code builds that address with `lui` + `addiu`, and the split treats every such value as a "pointer start".

| Delay slot | Cause |
| --- | --- |
| `0x801C0E3C`, `0x801C3FDC` | **Bug B.** Real constants, but they are bases of lookup tables that start one word later (the code adds an index and loads through them, at `0x801C0B90` and `0x801C3B9C`). The tracer already knew they are table bases and did not trace them as code, but the split step used all `lui` + `addiu` values, table bases included |
| `0x801C0008`, `0x801C0200` | **Bug A.** No such constant exists. `addiu a2, a2, 8` at `0x801B15E4` and `addiu s6, s6, 0x200` at `0x801B3994` were paired with a leftover `lui 0x801C` seen earlier in the trace at a higher address (2,312 and 6,264 bytes away). The "at most 8 bytes before" test had no lower bound |

- Bug A made 3 more false starts nearby (`0x801BFFE0`, `0x801BFFF0`, `0x801C0010`). All 5 pairings it produced were stale ones; none was a real constant.

**The fix (two one-line changes in `tools/stream3_map.py`)**
- A: the `lui` must be 4 or 8 bytes before the `addiu`/`ori`, not after it.
- B: the split uses only `lui` + `addiu` values that are not table bases, the same list the tracer already used for seeds.
- `disasm/symbol_addrs.txt`: removed the 7 routine names the tracer no longer produces (`func_801BFFE0`, `func_801BFFF0`, `func_801C0008`, `func_801C0010`, `func_801C0200`, `func_801C0E3C`, `func_801C3FDC`, all `_stream3`). They were tracer output, not hand-found names.
- Options for "a jump really targets a delay slot" were not needed: none does.

**What changed in the map, and what did not**

| | Before | After |
| --- | --- | --- |
| stream3 functions | 613 | 605 |
| stream3 routines | 330 | 323 |
| Code reached, unreached code, tables, the 86 table targets | | all identical (86,464 bytes, 1,344 in 144 pieces, 4,192 in 31, 86) |
| Fall-throughs fixed by the cleanup step | 239 | 235 (4 were false cuts inside one real function) |
| Left alone by the cleanup step | 7 | 1 (`__osCleanupThread`, no body) |

**The new check**
- `tools/fix_fallthroughs.py` now treats "a function ends on a branch or jump" as an error, not a report line. `tools/regen.py` runs it right after the symbol step and stops before N64Recomp. The script itself also exits 1.
- Proven on the old symbol file before regenerating: it failed and named the 4 functions.

**The run** (`python3 tools/regen.py`: exit 0, "Function count: 1434", `__osGetCause_recomp` 0, 275 calls to 55 names with no body, same as before)
- The delay slots are now in the generated C, inside one function with their branch:
  - `func_801BFFE8_stream3`: `bnel` at `0x801C0004` now runs `addiu a1, a1, 0x4` on the taken path, and the not-taken path carries on inside the same function.
  - `func_801C0150_stream3`: `bnel` at `0x801C01FC` now runs `addiu t3, k1, 0x20`.
  - `func_801C0BF4_stream3`: `jr ra` at `0x801C0E38` now runs `addiu sp, sp, 0x10` before `return`.
  - `func_801C3C1C_stream3`: `jr ra` at `0x801C3FD8` with its nop.
- Second run of the cleanup script: "fixed: 0, already fixed: 235", checksums identical.
- All 6 tool tests pass. `test_stream3_map.py` went from 18 to 22 checks: a second made-up program with a 1-based table behind a `jr ra` and a stale `lui`. The 4 new checks failed on the unfixed tracer. `test_fix_fallthroughs.py` went from 27 to 29.

**Stuck / unknown**
- Fix A only removes the pairings that are provably wrong (a `lui` later in memory). A `lui` 4 or 8 bytes before an unrelated `addiu` on a path that never runs them in a row could still fool it. The new check catches the case where that lands on a delay slot; a false start elsewhere would only split a function in two, which the entry rule and the fall-through step handle.
- Numbers in older entries (613 functions, 1442 in total, 239 fall-throughs, 330 routines) are from before this fix.
- Nothing compiled or run (ground rule 1).

**Next**
- Phase 2 checklist: RSPRecomp config for the audio microcode.

## 2026-10-10: Fall-through cleanup script (Phase 2, task 4)

**Result: `tools/fix_fallthroughs.py` chains 239 stream3 functions into the function below them, as a step in `tools/regen.py`. 7 open-ended functions are reported and left alone; 3 of those are a new silent problem (a dropped delay slot).** Nothing was compiled or run as a game.

**How it decides (from the MIPS code, not the C)**
- `syms/dump.toml` gives each function's address and size, the decompressed ROM gives its instructions. The tool follows the branches from the function's first instruction. If that reaches the address just past the end, the function "falls".
- "Falls (unseen entry)": the last stretch of code is not closed by a jump, but nothing inside the function leads to it. It is dead code or entered through a table the tracer could not follow. It gets the same fix: harmless if dead, needed if not.
- Trailing all-zero words after a closing jump are padding, not a fall-through.
- The C is only read to find where each function's body ends (`;}`) and whether a function has a body at all.

**The fix:** three lines before the closing `;}`, the same call-then-return N64Recomp writes for a branch into another function's start:

```c
     // 0x801AE1FC: subu        $s7, $s7, $t8
     ctx->r23 = SUB32(ctx->r23, ctx->r24);
+    // falls into func_801AE200_stream3, added by tools/fix_fallthroughs.py
+    func_801AE200_stream3(rdram, ctx);
+    return;
 ;}
```

**The run** (`python3 tools/regen.py`, exit 0, 1442 functions, `__osGetCause_recomp` still 0)

| Item | Result |
| --- | --- |
| Fixed | **239**, all in stream3: 206 "falls", 33 "falls (unseen entry)" |
| Compared with plain N64Recomp output (scratch folder) | 717 lines added (239 x 3), 0 removed, 13 files |
| Second run of the script alone | "fixed: 0, already fixed: 239", every file's checksum identical |
| boot, stream1, stream2 | nothing to fix. Compiled code does not fall through |
| Calls to names with no body | unchanged: 275 calls, 55 names |

- **239, not the 243 from session 2b.** 2b's method was a throwaway and is not recorded. 239 plus the 4 "branch at end" functions below is 243, which is my best guess at the difference. Not verifiable.

**Left alone (7), reported by the script on every run**

| Function | Why |
| --- | --- |
| `__osCleanupThread` (boot) | No body in the C: N64Recomp skips it (ignored list). Its last call, `osDestroyThread`, never returns anyway |
| `func_801BFFF0_stream3` | Ends on `bnel` at `0x801C0004`. Its delay slot is the first instruction of the next function, and it is a real instruction |
| `func_801C0150_stream3` | Same: `bnel` at `0x801C01FC`, real instruction in the delay slot |
| `func_801C0BF4_stream3` | Ends on `jr ra` at `0x801C0E38`. The delay slot at `0x801C0E3C` is `addiu sp, sp, 0x10` |
| `func_801C3C1C_stream3` | Ends on `jr ra` at `0x801C3FD8`. The delay slot is a nop: harmless |
| `func_801C0E3C_stream3` | One instruction (the delay slot above), followed by the table at `0x801C0E40`, not a function |
| `func_801C3FDC_stream3` | One nop (the delay slot above), at the end of stream3's code |

- **New problem found: a function boundary between a branch and its delay slot.** In the first three, N64Recomp drops the delay slot instruction. For `func_801C0BF4_stream3` that means the stack pointer is not restored on return. For the two `bnel` cases the taken path misses one instruction, and the not-taken path should carry on at the second instruction of the next function, which a plain call cannot express. Not fixed here. The likely place for a fix is the function split (`tools/stream3_map.py` should not start a function on a delay slot that is only reached through its branch), but why the tracer made these starts was not looked at.

**Done**
- `tools/fix_fallthroughs.py` and `tools/test_fix_fallthroughs.py`: known-answer test on a made-up program of 15 functions in two overlapping sections, 27 of 27 checks pass. It covers each way of falling through, padding, `b`, the left-alone cases, the exact fixed text, and that a second run changes nothing.
- `tools/regen.py`: now 6 steps. Step 5 is "Cleanup", where later cleanup scripts also go.
- All 6 tool tests pass.

**Stuck / unknown**
- The 3 dropped delay slots above.
- The fix is only correct if the function below ends with a normal return (same condition as N64Recomp's own call-then-return). Chains of fall-throughs become nested calls.
- The 33 "unseen entry" fixes sit after code the C cannot reach today. They matter only once the table dispatch (the 5 jump-table stubs) is fixed.
- Only the running game proves any of this (ground rule 1).

**Next**
- Phase 2 checklist: RSPRecomp config for the audio microcode, then the project skeleton and first link (TLB functions start there, see the entry below).
- Decision for BlackCRT and the coach: fix the 3 dropped delay slots now (small, in the tracer or as a second cleanup script), or when the game reaches them. My suggestion: now-ish, before the first run, because a wrong stack pointer is hard to trace from a crash.

## 2026-10-10: What the game maps through the TLB (Phase 2, task 3b, read-only)

**Result: a blocker for gameplay, but a known pattern with a fix.** The game maps per-fighter data blocks at low virtual addresses. N64Recomp and N64ModernRuntime have no TLB support, so the first read of a mapped address will crash (a clean access violation, not silent corruption). Other recomps have solved this in their own runtime code. Read-only task: nothing was changed.

**Decision (BlackCRT and the coach):** the TLB work happens with the project skeleton and first link. Start with `osMapTLB_recomp` and `osUnmapTLB_recomp` versions that log their arguments, then add real mapping.

**Call sites** (all 4 KB pages, ASID -1 meaning global)

| Call | In | TLB slot | Virtual | Physical |
| --- | --- | --- | --- | --- |
| `osUnmapTLB` at `0x8001CF84` | `func_8001CF5C` | 0 to 30, in a loop | clears all | |
| `osMapTLB` at `0x8001CFBC` | `func_8001CF5C` | 0 | `0x00000000` (one page) | `0x3A4000`, odd page unmapped |
| `osMapTLB` at `0x8001D010` | `func_8001CF5C` | 1 to 5 | `(P1 byte + 1) * 0x10000`, 40 KB | `0x1DB000` to `0x1E4FFF` |
| `osMapTLB` at `0x8001D07C` | `func_8001CF5C` | 6 to 10 | `(P2 byte + 1) * 0x10000`, 40 KB | `0x1E5000` to `0x1EEFFF` |
| `osUnmapTLB` at `0x801C5808` | `func_801C57B0_stream2` | 0 | | |
| `osMapTLB` at `0x801C5850` | `func_801C57B0_stream2` | 0 | `0x00000000` (one page) | a buffer passed in, rounded up to a page |

- The two bytes are at `0x8004E98C` and `0x8004E98D`, one per player. The P2 mapping is skipped when both are equal.
- `func_80012198` fills the two physical slots: it inflates ROM table entry 3 + byte to `0x801DB000` (P1) and `0x801E5000` (P2). The table is the stream table at ROM `0x7DE0`; it has 27 entries.
- Entries 3 to 13 are 11 blocks of 20 to 35 KB. Each holds 580 to 1166 words that point into its own window (entry 3 into `0x0001xxxx`, entry 4 into `0x0002xxxx`, and so on). So they are per-fighter data linked at a fixed low address. "Per fighter" is my reading of 11 blocks picked by a per-player byte, not proven.
- So the mapped range is page 0 plus `0x00010000` to `0x000BA000`, all inside the low half that a recomp cannot treat as plain RAM.

**Code or data? Data only, as far as static reading shows.** The 11 blocks contain no `jr ra` at all; of the 27 table entries only the three code streams do. A `jal` from `0x80xxxxxx` cannot reach low addresses.

**Tool support (read from source)**
- N64Recomp: none. Its README says relocation support for TLB mapping "is coming in the future". `osMapTLB` and `osUnmapTLB` are on its ignored list, so no body is written.
- N64ModernRuntime (commit `cdf5abb`): no `osMapTLB_recomp` or `osUnmapTLB_recomp`, so the link fails until we supply them. `osUnmapTLBAll_recomp` is an empty stub with a TODO; `osVirtualToPhysical` has "TODO handle TLB mappings".
- Why it crashes: recompiled code turns address A into `rdram + (A - 0x80000000)`. The runtime reserves 4 GB (`allocation_size`) but only the first 512 MB (`mem_size`) is usable. `0x00010000` lands 2 GB in, on a no-access page.

**References**
- Gauntlet Legends recomp, `src/tlb.cpp` (github.com/Auxnon/gauntlet-legends-recomp): the closest match. It implements both functions and has the host OS map the same physical pages at the virtual address, so both addresses share memory with no per-access cost. The code read is Linux only (`mmap`).
- BM64TSARecomp, `src/game/tlb.cpp` (github.com/RevoSucks/BM64TSARecomp): records the mappings in a table.
- Goemon, Castlevania and two GoldenEye recomps also declare their own `osMapTLB_recomp`. Not read.

**Open questions**
- Windows mapping alignment: the Windows equivalent of `mmap` normally works in 64 KB steps, and the physical slots at `0x1DB000` and `0x1E5000` are not 64 KB aligned. Whether the newer Windows calls allow 4 KB steps here is unchecked.
- Whether a copy approach is safe (copy the block to the virtual address instead of sharing it). Only if the game never touches the same data through both addresses.
- `osVirtualToPhysical` (36 calls) gives a wrong answer for a mapped address. Not checked whether the game ever passes one.
- What the page at virtual 0 is for, and which functions follow the low pointers.

## 2026-10-10: Real recomp config and one-command regeneration (Phase 2, task 3)

**Result: `kigold.toml` is in the repo with 12 stubs, `python3 tools/regen.py` regenerates the C in one command, and the `__osGetCause_recomp` count is 0.** Nothing was compiled or run as a game.

**Decisions from task 2 (BlackCRT and the coach):** `__osSyncPutChars` stays named. `func_80005D98` and `func_80005E58` stay unnamed.

**Done**
- **`kigold.toml`** at the repo root (WM2K's naming style). Format read from N64Recomp's `src/config.cpp`: `[input]` with `entrypoint = 0x80000400`, `rom_file_path = "build/kigold.decompressed.z64"`, `symbols_file_path = "syms/dump.toml"`, `output_func_path = "RecompiledFuncs"`, and `[patches]` with the `stubs` list. Paths are relative to the config file.
- **12 stubs, each with a comment.** The reasons for the 9 old ones are the errors N64Recomp prints, re-checked by removing one stub at a time in a scratch folder (9 runs, each exit 1 on that function):

| Stub | Reason |
| --- | --- |
| `func_80030EF0` | "Unhandled branch in func_80030EF0 at 0x80030F58 to 0x80031028" |
| `func_801AE6B4_stream3` | "Negative offset for lw from stack: -24584" |
| `func_801AFD44_stream3`, `func_801AFE98_stream3`, `func_801BCC84_stream3`, `func_801C0B5C_stream3`, `func_801C0BB4_stream3` | "Failed to determine size of jump table" (tables at `0x801C52A4`, `0x801B5B64`, `0x801C4604`, `0x801C0E3C`, `0x801C0F08`) |
| `func_801B6578_stream3`, `func_801B8F00_stream3` | "Unhandled cop0 register in mfc0: 9" (Count) |
| `__osSyncPutChars`, `func_80005D98`, `func_80005E58` | Debug link code, stubbed by choice. N64Recomp translates all three without a stub (3 runs, exit 0) |

- **`tools/regen.py`**, five steps in order: unpack check (the decompressed ROM must match the SHA1 in `disasm/kigold.yaml`, else `tools/unpack_rom.py` rebuilds it), splat split (full output to `build/split.log`), `tools/gen_symbols.py`, N64Recomp (into an emptied `RecompiledFuncs/`), and a report. It stops at the first step that fails. Cleanup scripts will go between the last two steps when they exist.
- **Guard and `.gitignore` tested.** `git add RecompiledFuncs/funcs.h` is refused (`.gitignore` line 10). Forced in with `git add -f`, the pre-commit hook blocks it: "this folder only holds generated or extracted output", exit 1. Unstaged again with `git restore --staged`. No guard or `.gitignore` change was needed.

**The run**

| Item | Result |
| --- | --- |
| `tools/regen.py` exit code | 0 (N64Recomp exit 0, splat exit 0) |
| "Function count" | 1442 |
| Output | 30 files, 11 MB: `funcs.h`, `funcs_0.c` to `funcs_26.c`, `lookup.cpp`, `recomp_overlays.inl`. 1330 function bodies (1442 minus the 112 that N64Recomp ignores) |
| `__osGetCause_recomp` calls | **0** (was 6) |
| Calls to `*_recomp` names with no body | 275 calls to 55 names |
| Tracked files after the run | unchanged (`syms/dump.toml` comes out identical) |

- **46 of the 55 names are on N64Recomp's `reimplemented_funcs` list**, which is the list of functions the runtime is expected to provide (`osRecvMesg`, `osCreateThread`, `osViSwapBuffer` and so on). 232 calls.
- **9 names are only on its `ignored_funcs` list: 43 calls, and this is the same kind of link question `__osGetCause` was.** N64Recomp writes no body for them and nothing says the runtime has one:

| Name | Calls | Called from |
| --- | --- | --- |
| `__osSiRawStartDma` | 8 | `func_80034020`, `func_800343F4`, `func_8003BF10`, `func_8003C2A0` |
| `__osSiRelAccess` | 6 | `func_80034020`, `func_80034350`, `func_8003BF10`, `func_8003C2A0` |
| `__osSiGetAccess` | 4 | the same four |
| `__osContDataCrc` | 4 | `func_8003BF10`, `func_8003C2A0`, `func_801CD08C_stream2`, `func_801CD1C4_stream2` |
| `__osContAddressCrc` | 2 | `func_8003C13C`, `func_8003C4C4` |
| `__ull_rshift` | 7 | `func_801BE3CC_stream2`, `func_801C9D78_stream2`, `func_801C9EE4_stream2` |
| `__ll_lshift` | 6 | `func_801BE240_stream2`, `func_801C9D78_stream2`, `func_801C9EE4_stream2` |
| `osMapTLB` | 4 | `func_8001CF5C`, `func_801C57B0_stream2` |
| `osUnmapTLB` | 2 | `func_8001CF5C`, `func_801C57B0_stream2` |

- The callers of the first five look like unnamed libultra controller and pak code (leads only, nothing named). If so, naming them would make the calls disappear the way they do for other libultra internals. `__ull_rshift` and `__ll_lshift` are 64-bit math helpers called from game code in stream2. `osMapTLB` and `osUnmapTLB` are called from game code: the game maps memory through the TLB, which the recomp runtime does not emulate.

**Stuck / unknown**
- The 9 names above. Not looked at beyond the caller list.
- Whether the runtime really provides all 46 "reimplemented" names is unchecked. The runtime is not in the repo yet; the first link will tell.
- Stubbing the debug link still rests on the assumption that retail code never needs it (see the entry below).
- The stubs are gaps, not fixes: 9 functions currently do nothing.

**Next**
- Phase 2 checklist: the fall-through cleanup script and its test.
- Decision for BlackCRT and the coach: look at the 9 unprovided names now (naming the controller code may remove 5 of them), or wait for the first link to list everything that is missing at once. My suggestion: wait for the link, but keep `osMapTLB` in mind as the one that could need real work.

## 2026-10-10: The three callers of `__osGetCause` (Phase 2, task 2)

**Result: one of the three is proven and named, `__osSyncPutChars` at 0x80006190. The other two are identified in kind but not proven, so they stay unnamed. Naming does not remove the 6 `__osGetCause_recomp` calls; stubs in the recomp config will.**

**What the three are**

All three belong to libultra's debug link (the "rdb" port a development kit listens on, at `0xC0000000`). Each writes a packet there, then polls `__osGetCause` until Cause bit `0x2000` (interrupt 6) is set, then clears it by writing `0xC000000C`. A retail console has nothing on that port.

| Function | Verdict | Evidence |
| --- | --- | --- |
| `func_80006190` | **Named `__osSyncPutChars`** | Same length as the reference (72 instr) in `ultralib_2.0I` and `ultralib_2.0I_rom` `os/syncputchars.o`. Not exact: 68 words identical, 4 differ only in a constant with the same instruction and registers, all in how the packet header bits are packed (version I has a 6-bit type, the game a 2-bit one). Callee rule: all 6 calls agree in position and name (`__osAtomicDec` x2, `__osDisableInt`, `__osGetCause` x2, `__osRestoreInt`). `0x80007064` is used at the 4 places the reference uses `__osRdbWriteOK` and starts at 1 like it. Single candidate: the next closest function of that length differs in 69 words |
| `func_80005D98` | **Not named.** Lead: `send_packet` | No exact match, and none is possible with our references (see below). It builds a packet, writes it to `0xC0000000` and waits for interrupt 6 |
| `func_80005E58` | **Not named.** Lead: `send` | No exact match. It calls `func_80005D98` in pieces of 3 bytes, which is what the reference `send` does with `send_packet` |

- **Why the two cannot be proven.** They are file-local (static) functions in `kdebugserver.c`. The game's copy of that file is an older version than version I: seven functions at `0x80005D10` to `0x80006184` with a three-state command reader, where version I has five and a `send_packet` that never reads Cause. The GoldenEye reference has an empty `kdebugserver`. So there is nothing to match against, and static functions have no symbol in the reference objects anyway (which is also why the fingerprint tool never listed them). The names would rest on resemblance and on N64Recomp's list, which is not the session 5 standard.
- **Lead, not named:** `func_80005FA8` is the file's main function (`kdebugserver` in the reference). Its only caller is `__osException` at `0x80003F84`, at the spot where version I calls `kdebugserver` (right after the thread state is set to runnable, followed by a branch to the dispatcher). The code around the call differs between versions.
- **Nothing calls `__osSyncPutChars`.** No call and no pointer to `0x80006190` anywhere in the split. It looks like dead code. Not proven at run time.

**N64Recomp lists**

| Name | reimplemented | ignored | renamed |
| --- | --- | --- | --- |
| `__osSyncPutChars` | no | no | no |
| `send_packet`, `send` (leads) | no | yes ("kdebugserver" block: `string_to_u32`, `send_packet`, `clear_IP6`, `send`, `kdebugserver`) | no |

Coverage is unchanged: `reimplemented_funcs` 55 of 116, `ignored_funcs` 112 of 358, `renamed_funcs` 6 of 83.

**Does naming remove the 6 calls? No.** Tested with N64Recomp in a scratch folder outside the repo. Every run: exit 0, "Function count: 1442", same 9 real stubs.

| Run | `__osGetCause_recomp` calls | Side effect |
| --- | --- | --- |
| Before (old symbol file) | 6 | |
| A: real symbol file, `__osSyncPutChars` named | 6 | None. It is on no list, so it is translated as before |
| B: trial copy, plus `send_packet` and `send` | 2 (both in `__osSyncPutChars`) | 2 new calls to `send_recomp` with no body, from `func_80005F30` and `func_80005F7C` |
| C: trial copy, plus `string_to_u32` and `kdebugserver` | 2 | plus 2 calls to `string_to_u32_recomp` with no body |
| D: real symbol file, `__osSyncPutChars` stubbed in the config | 4 (the two unnamed ones) | None |

- Naming moves the problem instead of closing it: the game's old `kdebugserver.c` has two functions (`func_80005F30`, `func_80005F7C`) that are not on N64Recomp's list, and they keep calling the ignored ones.
- **A stub does close it** (run D): a stubbed function gets an empty body, so its calls vanish and nothing dangles. Stubbing `__osSyncPutChars`, `func_80005D98` and `func_80005E58` in the recomp config should bring the count to 0. Only D was run; the three together were not.
- The trial names in B and C were only in scratch copies of the symbol file. They are not in the repo.

**Done**
- `disasm/symbol_addrs.txt`: `__osSyncPutChars = 0x80006190` with its evidence, in the hand-found block.
- Re-ran the split (exit 0, no warnings or errors) and `tools/gen_symbols.py`: `syms/dump.toml` changed by one line, 1442 functions, boot named 91 (was 90), 252 names in total.
- Tool tests: 5 of 5 pass.
- `docs/SETUP.md` Part 2: the fallback now uses `Start-Process ... -Wait -PassThru`, as BlackCRT actually ran it, with the note that `ExitCode` can be blank in PowerShell 5 and `vswhere` is the reliable check.
- `PLAN.md`: Phase 2 order is now a checklist, tasks 1 and 2 ticked, status line says Phase 2 in progress, link question row updated.

**Stuck / unknown**
- `__osSyncPutChars` is named without an exact match. It follows the session 5 precedent (`__osEnqueueAndYield`, 34 of 35 identical plus call evidence), but it is a judgement call. Easy to revert: one line in `disasm/symbol_addrs.txt`.
- Whether the runtime provides `__osGetCause_recomp` was still not checked. With the stubs it should not matter.
- Stubbing the debug link assumes the game never needs it. That fits a retail cartridge, but only the running game proves it (ground rule 1). `__osException` calls `func_80005FA8` only when the word at `0x80006F94` is not zero; what sets it was not checked.
- Nothing was compiled or run.

**Next**
- Phase 2, task 3: the real recomp config. List the 9 stubs with reasons, and add `__osSyncPutChars`, `func_80005D98` and `func_80005E58` as stubs (debug link, never reached on retail hardware). Then confirm the `__osGetCause_recomp` count is 0.
- Decision for BlackCRT and the coach: keep `func_80005D98` and `func_80005E58` unnamed (my recommendation), or accept `send_packet` and `send` as "likely" names on weaker evidence.

## 2026-10-10: Windows build tools installed and checked (Phase 2, task 1)

**Result: the Windows build tools work, and the x64 environment loads from Ubuntu.** Docs only; nothing was built.

**Done**
- BlackCRT installed Visual Studio Build Tools 2022 on Windows. `winget` was missing, so BlackCRT ran `vs_BuildTools.exe` from `aka.ms/vs/17/release` directly with the same `--add` components as `docs/SETUP.md` Part 2. `vswhere` shows the install complete with the Clang component. `LongPathsEnabled` is 1.
- Checked from Ubuntu through `powershell.exe`: found the install with `vswhere`, loaded `Launch-VsDevShell.ps1 -Arch amd64 -HostArch amd64`, printed the versions.
  - Install path: `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools` (Developer PowerShell v17.14.41)
  - clang-cl 19.1.5, `Target: x86_64-pc-windows-msvc`
  - cmake 3.31.6-msvc6
  - ninja 1.12.1
- The Start menu Developer PowerShell defaults to 32-bit (`Target: i686`). Build scripts must load the x64 environment as above.
- `docs/SETUP.md` Part 2 now has the winget fallback and the x64 note. `PLAN.md` marks Phase 2 task 1 done.

**Stuck / unknown**
- Nothing. No compile was tried yet, so this proves the tools start, not that they build the game.

**Next**
- Phase 2, task 2: name the 3 callers of `__osGetCause` (`func_80005D98`, `func_80005E58`, `func_80006190`).

## 2026-10-10: Phase 1 go/no-go, go for Phase 2 (session 2, task 4)

**Result: GO for Phase 2, approved by BlackCRT.** Phase 1 is done. The full write-up (verdict per part, risks, first Phase 2 tasks) is in `PLAN.md` under "Phase 1 go/no-go". Docs only; no tool, config or symbol changes.

**Done**
- Wrote the go/no-go section in `PLAN.md`, updated the status line, ticked the last Phase 1 box.
- Verdicts: microcode, boot, stream1, stream2 and the symbol file are a go; stream3 is a go with known work (option A).
- **Unreached stream3 code is 1,344 bytes in 144 pieces**, checked by running `tools/stream3_map.py`. The 1,300 bytes in 145 pieces in the 2b entry below is the old throwaway tracer, which also started from splat's labels and reached 44 more bytes. Same 92,000 total.

**Stuck / unknown**
- Nothing was compiled or run (ground rule 1). Every verdict means "ready to try".
- The risks carried into Phase 2 are listed in `PLAN.md`: 9 stubs, 243 fall-throughs, 14 cross-function loop groups, 86 mid-function table addresses, the `__osGetCause_recomp` link question, 61 unnamed libultra functions.
- stream1 calls stream3 at `0x8000FEF0`, near the start of stream1, so stream3 may run early in boot. Not checked.

**Next**
- Phase 2, first tasks in order: Windows build tools (`docs/SETUP.md` Part 2), name the 3 callers of `__osGetCause`, real recomp config, fall-through cleanup script.
- Start a fresh coach chat for Phase 2.

## 2026-10-10: `__osGetCause` named, one stub fewer (session 2, task 3)

**Done**
- **Deleted the throwaway stream3 files in `build/`** (BlackCRT approved): `stream3_map.py`, `stream3_map_report.txt`, `stream3_funcs.txt`, `s3test/`, `s3check/`. All were git-ignored. `tools/stream3_map.py` replaces them.
- **Named `__osGetCause` at 0x800064F0** in `disasm/symbol_addrs.txt`, in the session 5 hand-found block. The session 5 evidence was checked again from scratch, not copied:
  - The function is `mfc0 $v0, $13` (read Cause) then `jr $ra`. Byte for byte the same as `os/getcause.o` in both reference builds (`ultralib_2.0I`, `ultralib_2.0I_rom`).
  - Single candidate: no other object in `build/ref/` contains that instruction pair.
  - 6 calls, two each from `func_80005D98`, `func_80005E58` and `func_80006190`. All three are unnamed, so no caller confirms the name; it rests on the exact match alone.
- Re-ran the split and `tools/gen_symbols.py`.

**Checks**

| Check | Result |
| --- | --- |
| splat split | exit 0, no warnings or errors |
| `syms/dump.toml` | one line changed: `func_800064F0` is now `__osGetCause`. Still 1442 functions; boot named 90 (was 89), 251 names in total |
| N64Recomp (throwaway config in a scratch folder, task 2c's stub list minus `func_800064F0`) | exit 0, "Function count: 1442", **9 stubs (was 10)** |
| Tool tests | 5 of 5 pass |

- **Coverage: `reimplemented_funcs` is still 55 of 116.** `__osGetCause` is on N64Recomp's `ignored_funcs` list, not the reimplemented one. `ignored_funcs` is now **112 of 358** (was 111), `renamed_funcs` 6 of 83. The session 7 note that called it a reimplemented blocker was loose: being ignored is what removes the stub (N64Recomp skips the function instead of translating it).

**Stuck / unknown**
- **The three callers still call it.** The generated C has 6 calls to `__osGetCause_recomp`, and N64Recomp emits no body for an ignored function. Unless the runtime provides that name, the Phase 2 build fails at link time. The likely real fix is naming the three callers: if they are libultra internals on the ignored or reimplemented lists, the calls go away with them. Not checked.
- Nothing was compiled or run (ground rule 1).
- Remaining stubs: `func_80030EF0` and the 8 in stream3.

**Next**
- Identify `func_80005D98`, `func_80005E58` and `func_80006190` (the only users of Cause outside the exception handler).
- Phase 1 go/no-go write-up.

## 2026-10-10: stream3 map in the repo, symbol file now 1442 functions (session 2, task 2c)

**Decision: option A (WM2K style) for stream3.** Recorded in `PLAN.md`. This task only put the map into the repo. No cleanup scripts and no fixes for the 8 stubbed functions; those are Phase 2.

**Done**
- **`tools/stream3_map.py`**: the tracer from `build/`, rewritten as a real tool. Same method, but the tracing is now a function that takes any block of code, which is what makes a test possible. `--yaml` prints the code and data pieces for `kigold.yaml`, `--symbols` the routine starts, `--funcs` the function list. Runs in under a second with `disasm/.venv/bin/python`.
- **It no longer reads splat's output.** The throwaway used splat's labels as a last, weakest set of starting points. The tool's output now feeds splat's config, so that would be a circle. Dropping it changes nothing that matters: the function list is identical to the trial's, line for line (613). Only the bookkeeping moves: the 44 bytes that only splat's labels reached now count as "code nothing reaches" (traced 86,464, unreached 1,344 in 144 pieces, data 4,192 in 31 regions; same 92,000 total).
- **`tools/test_stream3_map.py`**: known-answer test on a made-up program of 36 words, assembled by hand in the test, with the answer worked out on paper first. 18/18 checks pass: tables, unreached code, a rejected pointer, a jump table, and the split into 6 functions.
- **`disasm/kigold.yaml`**: stream3 is now 31 code pieces and 31 data pieces in order, pasted from `--yaml`. Each data line carries its RAM address, the tracer's class and its size.
- **`disasm/symbol_addrs.txt`**: 329 routine starts added from `--symbols` (the 330th, `0x801AD900`, was already there as `stream3_entry`). They use splat's default names (`func_801ADD2C_stream3`) and claim no meaning.
- **`tools/gen_symbols.py`**: stream3's functions and code size now come from the tracer. splat's stream3 files are still read, but only to prove nothing was left undecoded. New refusals for a traced section: config pieces that differ from the tracer's, a traced function that is not inside one code piece, any raw block in splat's output. A traced function keeps our name from `symbol_addrs.txt` where one exists. The "named" column no longer counts default names. Its test went from 18 to 26 checks.
- The code size has to come from the tracer because the last table (`0x801C3FE0`, 0x80 bytes) ends exactly where the code area ends, so "the first non-code piece" in the config no longer marks the end of the code.

**Checks (all on the final code)**

| Check | Result |
| --- | --- |
| splat split | exit 0, no warnings or errors |
| Raw `.word` lines in stream3's 31 code files | 0 (was 30 raw blocks, 50,160 bytes) |
| `syms/dump.toml` regenerates, all safety checks pass | yes: boot 119, stream1 459, stream2 251, stream3 613, total 1442 |
| boot, stream1, stream2 sections | unchanged, byte for byte |
| Whole file against the trial's `build/s3test/dump.toml` | identical |
| N64Recomp on the real file (throwaway config `build/s3check/`, the trial's 10 stubs unchanged) | exit 0, "Function count: 1442" |
| Tool tests | 5 of 5 pass |

**Found on the way, not fixed (needs a Phase 2 decision)**
- **86 addresses stored in three inline tables land in the middle of a function, not at its start.** The tables are `0x801B5B64` (7 of its 17 entries), `0x801BC498` (all 25) and `0x801C0E40` (54 of 102). They sit beside the 5 functions N64Recomp stubbed with "Failed to determine size of jump table", so they are very likely those hand-made dispatch tables. The split rule only makes a function start where a call, a branch or an address in the data area arrives; a jump through one of these tables that the tracer could not resolve adds nothing. Whether the 86 must become function starts depends on how the dispatch is fixed. Making them starts would raise the function count above 613, so it was left alone. The tool prints the number in its summary and the test covers it.
- splat still draws its own function borders in stream3 (168 functions, 461 entry labels), because it demotes a routine start that other code branches past. Harmless now, since those borders are not used.

**Stuck / unknown**
- Same as 2b: nothing was compiled or run. "Function count: 1442" means N64Recomp reads the file, nothing more (ground rule 1).
- The throwaway files in `build/` (`stream3_map.py`, its report, `s3test/`, `s3check/`) are still there. They are git-ignored; delete when convenient.

**Next**
- Phase 1 go/no-go write-up (the last open box).
- Phase 2, in this order of risk: the 243 fall-throughs (silent miscompile), the cross-function loops, then the 8 stubbed functions together with the 86 table targets above.

## 2026-10-10: stream3 mapped by tracing, and a trial N64Recomp run (session 2, tasks 2a and 2b)

Read-only for `disasm/`, `syms/` and `tools/`. Everything lives in `build/` (git-ignored): the tracer `build/stream3_map.py`, its report `build/stream3_map_report.txt`, the function list `build/stream3_funcs.txt`, and the trial run in `build/s3test/`.

**2a: the map**
- **Method:** recursive descent with rabbitizer from known entry points. Weak seeds (stored pointers, splat labels) are accepted only if everything they lead to decodes cleanly; otherwise they are rolled back and counted as data pointers. A word that is itself a stream3 code address is never treated as an instruction.
- **Ways in from outside: two, both from stream1.** `0x801AD900` (called at 0x8000FEF0) and `0x801AE460` (called at 0x800119DC). Boot has none. Stream2 shares the same RAM so it cannot call stream3. Stream3 itself makes **no calls to anything outside itself**.
- Those two entries reach 68,888 bytes with zero decode failures. Stored code addresses add 17,576 bytes (209 distinct targets in stream3's data area, plus tables between routines). splat's labels added only 44 bytes; 20 of its 30 raw-block labels and one entry label (`0x801B5B64`, a 17-entry address table) sit on data.
- **Code vs data** (code area is 92,000 bytes):

| What | Bytes | Share |
| --- | --- | --- |
| Code reached by tracing | 86,508 | 94.0% |
| Valid code nothing reaches (145 small pieces the game jumps over) | 1,300 | 1.4% |
| Data, 31 regions (address tables, lookup tables of bytes and 16-bit values, one big record table at `0x801BB0B4`) | 4,192 | 4.6% |

- **Routines:** 330 (146 entered by `jal`, 174 only through stored addresses, 10 that follow an inline table). 246 have branches leaving them, 242 of those into the middle of another routine; 43 fall through into the next. One web of linked routines holds most of the code (about 57 KB); 43 routines stand alone.
- **Not normal calling rules:** 8 indirect jumps through ordinary registers, no `jalr`. `0x801B1F30` is just `jr $t2` (a hand-made call), `0x801BA7F0` jumps through `$s1`.
- **splat's 30 raw blocks:** 3 all code, 9 mostly code with tables inside, 18 pure data.
- **`0x801AE460`:** stream3's second public entry, running to `0x801AE7A4`. Interrupts off through Status, every register saved on a 0x80 frame, work, restore, interrupts on, returns the byte at `0x801D8876`. Not named; no evidence for a name yet.
- **CPU registers:** Count is read at `0x801B658C` (routine `0x801B6578`) and `0x801B925C`. No Cause reads. Status only in the two entry routines (N64Recomp supports Status).
- 223 floating-point instructions in stream3.

**2b: trial N64Recomp run on the traced split**
- Rule for the split: a function is one unbroken run of code, and anything entered from outside it is a function start. Applying that until nothing changes gives **613 functions** (330 routines plus 283 extra entry points), 87,808 bytes, no data inside any function.
- Throwaway symbol file `build/s3test/dump.toml`: boot, stream1, stream2 copied from `syms/dump.toml`, stream3 replaced by the 613. N64Recomp reads it ("Function count: 1442") and **finishes with exit 0 after 9 reruns**, no warnings.
- **605 of 613 stream3 functions translate.** The 8 that needed a stub:

| Reason | Count | Functions |
| --- | --- | --- |
| "Failed to determine size of jump table" (hand-written table dispatch) | 5 | `801AFD44`, `801AFE98`, `801BCC84`, `801C0B5C`, `801C0BB4` |
| Reads Count | 2 | `801B6578`, `801B8F00` |
| "Negative offset for lw from stack" | 1 | `801AE6B4` (the tail of the `0x801AE460` entry) |

- Outside stream3 the same two as session 7 still need stubs: `func_800064F0` (Cause) and `func_80030EF0` (branch to the entry label 0x80031028). `func_80011824` now translates, because `0x801AE460` exists.
- **What N64Recomp generates:**
  - Branch to another function's start: a call followed by `return;` (930 of these in stream3: 403 forward, 527 backward). Correct as long as the callee ends with a normal return.
  - Backward branch into another function: exactly the same, call then `return;`. A loop that crosses functions therefore becomes recursion. 169 functions sit in 14 such loop groups, the largest with 95 functions (the main dispatcher at `0x801AFD7C` and its handlers).
  - **Fall-through into the next function: nothing.** The C function simply ends, so execution returns to the caller instead of carrying on. No warning. 243 functions end this way. This is a silent miscompile and must be fixed by a cleanup step.
- Earlier wrong numbers, now corrected: the first 2a report said 29 data regions / 329 routines / 604 functions. Two tracer bugs caused that (an instruction first seen as a delay slot was not followed; two small lookup tables that decode as instructions were counted as code).

**Stuck / unknown**
- Nothing was compiled or run; ground rule 1 still applies. "Translates" only means N64Recomp produced C.
- The 145 never-reached code pieces may be dead, or may have entries the trace cannot see.
- Whether clang-cl turns "call then return" into a real jump (so cross-function loops do not grow the stack) is untested.
- What stream3 does in the game is still unknown.

**Next (needs a decision)**
- **Option A, WM2K style, looks workable:** traced function list in the symbol file, a cleanup script that chains the 243 fall-throughs into the next function, a way to keep cross-function loops from growing the stack, and hand fixes for the 8 stubbed functions.
- **Option B, treat stream3 as one unit** (custom translation or a small interpreter behind its two entry points): possible because stream3 calls nothing outside itself, but it needs floating point too and cannot be tested until the Phase 2 runtime exists. Keep as the fallback.
- First steps if A: turn the tracer into a real tool with a known-answer test, add the 31 data regions to `disasm/kigold.yaml`, and let `gen_symbols.py` take stream3's functions from the trace.

## 2026-10-08: Symbol file for N64Recomp (session 7)

**Done**
- **Split `stream1_rsp` into its six parts** in `disasm/kigold.yaml`: `rspboot`, `gfx_text`, `audio_text` (blobs), stream1's own data (now a `data` block, `asm/data/C34F90.data.s`), `gfx_data`, `audio_data` (blobs). Re-ran the split: exit 0, no warnings, same 907 functions (boot 119, stream1 459, stream2 251, stream3 78).
- **Added `tools/gen_symbols.py`.** It reads the segment layout from `disasm/kigold.yaml` and the functions from splat's `.s` files, and writes `syms/dump.toml` in the layout WM2K uses: one `[[section]]` per code segment (`name`, `rom`, `vram`, `size` of the code part) with a `functions` list of `{ name, vram, size }`. Overlays are plain sections that share RAM addresses; WM2K's file has no relocation entries and neither does ours. The format was read from N64Recomp's parser (`src/config.cpp`), not from memory. Run: `disasm/.venv/bin/python tools/gen_symbols.py` (after a split).
- The script refuses to write when something is off: a function outside its section, overlapping, or misaligned; a size that differs from the one splat prints; a name used twice; a function named in `symbol_addrs.txt` that is missing or at another address. On the real project all of these pass, including all 250 named functions.
- **Added `tools/test_gen_symbols.py`**, a known-answer test on a made-up splat project. 18/18 checks pass.
- **Result:**

| Section | ROM | RAM | Code size | Functions | Named | Code inside functions |
| --- | --- | --- | --- | --- | --- | --- |
| boot | 0x1000 | 0x80000400 | 0x6160 | 119 | 89 | 98%, the rest is zero padding |
| stream1 | 0xC00000 | 0x8000F960 | 0x32C90 | 459 | 159 | 100% (780 bytes of zero padding) |
| stream2 | 0xC3A7A0 | 0x801ACB20 | 0x219E0 | 251 | 1 | 100% (104 bytes of zero padding) |
| stream3 | 0xD232E0 | 0x801AD900 | 0x16760 | 78 | 1 | **45%** |

- **Built N64Recomp** (commit ffb39cd) into `build/N64Recomp/build-linux/` (git-ignored). Ubuntu had no C++ tools and `sudo` needs a password, so the build uses pip packages in `~/.cache/kigold-toolchain` (`cmake`, `ninja`, and `ziglang`, whose bundled clang is the compiler, through four small wrapper scripts in that folder). Nothing was installed system-wide.
  - **Update 2026-10-10:** that workaround is gone. BlackCRT installed `build-essential`, `cmake` and `ninja-build` system-wide (gcc/g++ 15.2.0, cmake 4.2.3, ninja 1.13.2, all in `/usr/bin`). `build-linux/` was deleted and N64Recomp rebuilt from a clean configure at the same commit (ffb39cd) with only those tools: 73/73 steps, exit 0, no warnings. The known-answer check below gives the same answer with the new build (4 sections in `syms/dump.toml`, "Function count: 907", same first stop at `func_800064F0`). `~/.cache/kigold-toolchain` was then deleted.
- **Known-answer check:** ran N64Recomp with a throwaway config (`build/symtest/`, git-ignored) on the decompressed ROM and `syms/dump.toml`. **It reads the file without errors**: 4 sections, "Function count: 907", no parse or bounds complaints. No generated C was kept outside `build/`.
- N64Recomp then stops at the first function it cannot translate. To see the whole picture I stubbed each such function in the throwaway config and reran (33 reruns). What it could not translate:
  - **boot: 1.** `func_800064F0` reads CPU register 13 (Cause). This is the `__osGetCause` lead from session 5, still unnamed. The runtime does not recompile such OS internals; it needs its name or a stub.
  - **stream1: 2.** `func_80011824` calls 0x801AE460, which is inside one of stream3's raw blocks, so no function exists there. `func_80030EF0` branches into the middle of the next function (to the entry label `func_80031028`).
  - **stream2: 0.**
  - **stream3: 29 of 78**, almost all "branching outside of the function", two reading CPU register 9 (Count). Then N64Recomp reached code it had discovered itself in a raw block (`static_3_801ADE74`), could not analyse it, and a function like that cannot be stubbed by name, so the loop ended there.

**What the symbol file does not cover**
- **Stream3's undecoded half:** 30 raw blocks, 50,160 bytes (55% of its code), with 71 entry labels inside them. None of it is in the file. Anything that calls in there fails, as `func_80011824` shows.
- **Entry labels inside functions** (places code jumps into the middle of a function): boot 1, stream1 30, stream3 125. They are not functions in the file. Stream1's 30 sit in one area, 0x80031028 to 0x80032514. Session 1 of the split counted "71 extra entry labels" for stream3; that was only the ones in raw blocks, the real total is 196.
- Function ends in stream3 are splat's guesses for hand-written code, which is why 29 of its 78 functions branch outside themselves.
- No data symbols and no relocation entries (WM2K has none either).
- The 61 libultra names still missing (session 5) are in the file as `func_...`; the runtime can only replace functions that carry their real names.

**Stuck / unknown**
- "Reads without errors" is as far as this check goes. Nothing was compiled or run; ground rule 1 still applies.
- The stub loop stopped inside stream3, so there may be more untranslatable code after that point in stream3.
- ~~The toolchain in `~/.cache/kigold-toolchain` is a workaround.~~ Resolved 2026-10-10: replaced by the system gcc, cmake and ninja (see the update under "Built N64Recomp" above).

**Next**
- Phase 1 go/no-go write-up. Microcode is a go; boot, stream1 and stream2 are in good shape (3 problem functions out of 829); **stream3 is the open problem** and needs a decision on how to tackle it.
- Likely first Phase 2 symbol work: decode stream3 properly (real routine starts and ends, data tables between routines), then handle the entry labels the way WM2K does (`extra_funcs.txt` plus its cleanup scripts).
- Cheap: name `__osGetCause` at 0x800064F0 (exact match, single candidate, from session 5).

## 2026-10-08: Microcode identified, graphics is stock Fast3D (session 6)

**Result: go on microcode.** Both microcodes are stock Nintendo ones. Read-only analysis with throwaway scripts; no tool or config changes, no microcode bytes written anywhere.

**Done**
- **Graphics microcode: stock Fast3D, RT64's `F3D_SDK_E`** ("2.0D, 04-01-96 (F3D SDK 2.0E)"). RT64 supports it; it runs on RT64's plain `F3D` path, the same one Super Mario 64 uses.
- **Audio microcode: Nintendo's standard audio microcode** (the common `aspMain`, audio ABI 1). Not custom. RSPRecomp should handle it; that part is not tested until Phase 2.
- **How RT64 detects microcode** (read from `src/gbi/rt64_gbi.cpp`, RT64 commit 8bd2cf1): it takes the microcode code and data addresses from the RSP task the game submits, hashes a fixed length of each with XXH3 (64 bit), and looks both up in a built-in table. Both must be found and must name the same entry; otherwise it prints "This game is not supported in HLE". It hashes emulator memory, where each 4-byte word is stored reversed.
- **How graphics was identified:** parsed RT64's two tables (94 code rows, 105 data rows) and hashed every 8-byte-aligned offset in the tail of stream1 at every table length, in both byte orders. Exactly one hit each, both in the word-reversed order RT64 uses:

| Part | RAM | Hash length | XXH3 | RT64 entry |
| --- | --- | --- | --- | --- |
| Graphics code | 0x800426C0 | 0x1408 | 0x9C0926F5E466BE70 | `F3D_SDK_E` |
| Graphics data | 0x80049640 | 0x800 | 0xEEB10D73400213B3 | `F3D_SDK_E` |

- **The game really submits those addresses.** The graphics task setup at 0x80011500 (stream1) fills a standard libultra `OSTask`: type 1, boot microcode 0x800425F0, code 0x800426C0, data 0x80049640, data size 0x800, stack size 0x400. A second graphics setup in stream2 (0x801AE890) uses the same code and data addresses. A third site at 0x800103D0 only uses the boot and code addresses. The earlier whole-ROM string scan found no second microcode ID string, so there is no sign of another graphics microcode; stream3's hand-written code is only half decoded, so that is not a full proof.
- **How audio was identified:** the audio task setup at 0x8002AFD0 (stream1) uses boot 0x800425F0 (size 0xD0), code 0x80043AD0, data 0x80049E40. The open-source mupen64plus HLE audio plugin (`src/hle.c`) recognises audio microcode by three words of its data, and all three match: data+0x00 is 1, data+0x30 is 0xF0000F00, and data+0x28 is 0x1E24138C, which that source labels "audio ABI (most common)". GoldenEye's value (0x1DC8138C) and the Blast Corps / Diddy Kong Racing value (0x1E3C1390) are different, so KI Gold does **not** use Rare's modified audio microcode. The data also holds the usual 16-entry command table at data+0x10.
- **Layout of the `stream1_rsp` area** (stream1 is at 0xC00000 in the decompressed ROM, RAM 0x8000F960):

| Part | RAM | stream1 offset | Size | SHA1 |
| --- | --- | --- | --- | --- |
| Boot microcode (`rspboot`) | 0x800425F0 | +0x32C90 | 0xD0 | f17bd9a73dade5739249a3aca6fb69830f9d903c |
| Graphics code | 0x800426C0 | +0x32D60 | 0x1410 | 06fccd9882519deede2dc95178df101fab81888e |
| Audio code | 0x80043AD0 | +0x34170 | 0xE20 | 21e05bb9b4b3611e0cc2374c3ad6cc26adf2b385 |
| stream1's own data | 0x800448F0 | +0x34F90 | 0x4D50 | not hashed |
| Graphics data | 0x80049640 | +0x39CE0 | 0x800 | fbb95b2f4e229b7dd59a104f70e1ff4b4522652c |
| Audio data | 0x80049E40 | +0x3A4E0 | 0x2C0 | 41dde0cb13c346f64b3aa429195741438f3a5292 |

- So stream1's CPU code ends exactly at +0x32C90, the three microcode code blocks follow, and stream1's own data starts at +0x34F90 (the lowest data address the code refers to). The "RSP SW Version: 2.0D" string sits at graphics data + 0x270.
- What RSPRecomp needs (read from `RSPRecomp/src/rsp_recomp.cpp`): `text_offset`, `text_size`, `text_address`, `rom_file_path`, `output_file_path`, `output_function_name`, and `extra_indirect_branch_targets`. For us: offset 0xC34170 in the decompressed ROM, size 0xE20. The branch targets are the 16 entries of the command table at audio data + 0x10; read them when writing the config.

**Stuck / unknown**
- RT64 marks its `F3D_SDK_E` rows "Needs confirmation". The hashes match exactly, so detection will succeed; ground rule 1 still applies, the running game is the proof.
- Audio code size 0xE20 is measured (code start to the first stream1 data reference), not taken from a reference. The audio code's RSP address (expected 0x04001080) is not checked; confirm both in Phase 2.
- The audio "standard" verdict rests on the three marker words and the layout, not a byte comparison with a reference copy (we have no legal reference copy of the microcode).
- The audio task's type field was not traced back to its value; the site is identified by its microcode pointers.
- Not checked: whether the game uses unusual display list tricks on top of stock Fast3D. Only rendering will show that.

**Next**
- Last Phase 1 box before go/no-go: generate the symbol file N64Recomp reads (`syms/`).
- Optional tidy-up: split `stream1_rsp` in `disasm/kigold.yaml` into the six parts above, so stream1's data is no longer inside a microcode blob.

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
