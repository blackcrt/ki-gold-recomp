// Watches the stream3 frame for early exits that our translated code gets wrong.
//
// stream3's per-frame entry (0x801AE460, hand-written assembly) saves every
// register, runs the frame, and falls into its tail (0x801AE6B4), which puts the
// stack pointer and all registers back and returns to the main code. Until task
// 7t the tail was a stub. Now N64Recomp translates it (two instruction patches
// in kigold.toml).
//
// The open problem (NOTES.md, tasks 7s and 7t). Three places in stream3 jump
// straight into the tail to end the frame early ("abort"): 0x801BDA40,
// 0x801BDC28 and 0x801BDC34. On the N64 the tail resets the stack pointer, so
// the frame is left at once, no matter how deep in calls the jump was. Our
// translated code cannot do that: its tail returns to whoever called the
// routine that jumped.
//   - If the entry itself jumped (0x801AE560), that is the same thing. Fine.
//   - If a routine the entry called jumped, the entry carries on after that
//     call, runs more of the frame with the registers already put back, and
//     reaches the tail a second time. Wrong.
//
// Nothing here fixes that. This file only makes it visible, through five
// [[patches.hook]] entries in kigold.toml:
//   - every abort jump prints an "ABORT JUMP" line,
//   - a tail that runs a second time in one frame prints a "WRONG" line,
//   - both are counted for the heartbeat (src/main/heartbeat.cpp).
#include <atomic>
#include <cstdio>

#include "kigold_decls.h"

namespace {
    // Lines printed per kind before that kind goes quiet. The counters go on.
    constexpr uint32_t MAX_LINES = 8;

    std::atomic<uint64_t> frames{ 0 };
    std::atomic<uint64_t> abort_jumps{ 0 };
    std::atomic<uint64_t> tail_reruns{ 0 };

    // About the frame that is running. Reset when the entry starts.
    std::atomic<uint32_t> tails_this_frame{ 0 };
    std::atomic<uint32_t> last_abort_from{ 0 };

    std::atomic<uint32_t> abort_lines{ 0 };
    std::atomic<uint32_t> rerun_lines{ 0 };

    // True while this kind of line may still be printed. Prints the "hidden"
    // notice once, when the limit is reached.
    bool may_print(std::atomic<uint32_t>& lines, const char* kind) {
        uint32_t line = lines.fetch_add(1, std::memory_order_relaxed);
        if (line < MAX_LINES) {
            return true;
        }
        if (line == MAX_LINES) {
            fprintf(stderr,
                "[kigold][frame] further %s lines are hidden, the heartbeat keeps counting them\n", kind);
        }
        return false;
    }
}

// Start of the frame entry, 0x801AE460.
extern "C" void kigold_on_frame_enter(void) {
    frames.fetch_add(1, std::memory_order_relaxed);
    tails_this_frame.store(0, std::memory_order_relaxed);
    last_abort_from.store(0, std::memory_order_relaxed);
}

// Just before one of the three jumps into the tail. from is the jump's address.
extern "C" void kigold_on_frame_abort_jump(uint32_t from) {
    uint64_t count = abort_jumps.fetch_add(1, std::memory_order_relaxed) + 1;
    last_abort_from.store(from, std::memory_order_relaxed);
    if (may_print(abort_lines, "ABORT JUMP")) {
        fprintf(stderr,
            "[kigold][frame] ABORT JUMP: 0x%08X jumps into the frame tail (frame %llu, abort jump %llu). Fine if the frame entry jumped here itself, wrong if a routine it called did. A WRONG line after this one means it was wrong\n",
            from, (unsigned long long)frames.load(std::memory_order_relaxed), (unsigned long long)count);
    }
}

// Start of the tail, 0x801AE6B4.
extern "C" void kigold_on_frame_tail(void) {
    uint32_t runs = tails_this_frame.fetch_add(1, std::memory_order_relaxed) + 1;
    if (runs < 2) {
        return;
    }
    tail_reruns.fetch_add(1, std::memory_order_relaxed);
    if (may_print(rerun_lines, "WRONG")) {
        uint32_t from = last_abort_from.load(std::memory_order_relaxed);
        fprintf(stderr,
            "[kigold][frame] WRONG: the frame tail runs for the %s time in frame %llu (last abort jump from 0x%08X). The N64 leaves the frame at the first one. Our code went on with the frame, so the registers the tail restores now may be garbage\n",
            runs == 2 ? "2nd" : "3rd or later", (unsigned long long)frames.load(std::memory_order_relaxed), from);
    }
}

kigold::FrameCounts kigold::frame_counts() {
    return {
        frames.load(std::memory_order_relaxed),
        abort_jumps.load(std::memory_order_relaxed),
        tail_reruns.load(std::memory_order_relaxed),
    };
}
