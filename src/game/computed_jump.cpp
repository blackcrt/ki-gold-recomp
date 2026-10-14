// Does two computed jumps of stream1 in our own code.
//
// func_80032200 and func_800323A4 (hand-written assembly) fill a row of memory.
// Each ends with a trick: a straight run of 7 stores, and a "jr $t5" that jumps
// into the middle of that run, so that exactly as many stores run as are left to
// do (0 to 7). The jump target is worked out from the count:
//
//   func_80032200, jr at 0x800322DC: run starts at 0x800322E4, 8 bytes per step
//     0x800322E4: sh $t3, 0xC($t0)    sb $t9, 6($t1)
//     ...
//     0x80032314: sh $t3, 0x0($t0)    sb $t9, 0($t1)
//     0x8003231C: jr $ra
//   func_800323A4, jr at 0x80032424: run starts at 0x8003242C, 4 bytes per step
//     0x8003242C: sb $zero, 6($t1)
//     ...
//     0x80032444: sb $zero, 0($t1)
//     0x80032448: jr $ra
//
// N64Recomp cannot translate a jump into the middle of a function. It turns the
// jr into a lookup of a function at that address, and the runtime stops with
// "Failed to find function at 0x800322EC" (run 12, NOTES.md task 7u). There is
// no address table, so this is not a jump table either.
//
// How. A [[patches.hook]] in kigold.toml sits just before each jr. The game's own
// (translated) code has already worked out the target in $t5. The hook calls the
// function here, which does the stores between the target and the "jr $ra", in
// the same order, and then the hook returns from the generated function. No
// register is changed, like in the game.
//
// tools/jumptest checks this file against the game's real instructions for every
// count. It builds this file with KIGOLD_JUMP_TEST defined, which reports every
// store to the test.
#include <atomic>
#include <cstdio>
#include <cstdlib>

#include "recomp.h"

#ifdef KIGOLD_JUMP_TEST
extern "C" void kigold_test_saw_store(uint32_t address, uint32_t bytes, uint32_t value);
#endif

namespace {
    // Calls logged per jump before it goes quiet.
    constexpr uint32_t MAX_LINES = 4;

    // One computed jump and its run of stores.
    struct Run {
        const char* function;
        uint32_t jump;   // address of the "jr $t5"
        uint32_t first;  // first store of the run, the target for a count of 7
        uint32_t end;    // the "jr $ra" after the run, the target for a count of 0
        uint32_t step;   // bytes of code per count
        std::atomic<uint32_t> lines{ 0 };
    };

    Run run_80032200{ "func_80032200", 0x800322DC, 0x800322E4, 0x8003231C, 8 };
    Run run_800323A4{ "func_800323A4", 0x80032424, 0x8003242C, 0x80032448, 4 };

    // How many steps of the run lie between the jump target and its end.
    uint32_t steps_left(Run& run, gpr target_register) {
        uint32_t target = (uint32_t)target_register;
        if (target < run.first || target > run.end || (target - run.first) % run.step != 0) {
            fprintf(stderr,
                "[kigold][jump] FATAL: 0x%08X (%s) jumps to 0x%08X, which is not one of its 8 targets (0x%08X to 0x%08X). Our code only knows those\n",
                run.jump, run.function, target, run.first, run.end);
            fflush(stderr);
            std::quick_exit(EXIT_FAILURE);
        }
        uint32_t count = (run.end - target) / run.step;
        if (run.lines.load(std::memory_order_relaxed) < MAX_LINES) {
            uint32_t line = run.lines.fetch_add(1, std::memory_order_relaxed);
            if (line < MAX_LINES) {
                fprintf(stderr,
                    "[kigold][jump] 0x%08X (%s): computed jump to 0x%08X, count %u (0 to 7), done in our code%s\n",
                    run.jump, run.function, target, count,
                    line + 1 == MAX_LINES ? ". Further lines for this jump are hidden" : "");
            }
        }
        return count;
    }

    void store16(uint8_t* rdram, gpr base, uint32_t offset, gpr value) {
        MEM_H(offset, base) = (int16_t)value;
#ifdef KIGOLD_JUMP_TEST
        kigold_test_saw_store((uint32_t)base + offset, 2, (uint16_t)value);
#endif
    }

    void store8(uint8_t* rdram, gpr base, uint32_t offset, gpr value) {
        MEM_B(offset, base) = (int8_t)value;
#ifdef KIGOLD_JUMP_TEST
        kigold_test_saw_store((uint32_t)base + offset, 1, (uint8_t)value);
#endif
    }
}

// Before the "jr $t5" at 0x800322DC. $t0 = r8, $t1 = r9, $t3 = r11, $t5 = r13,
// $t9 = r25.
extern "C" void kigold_computed_jump_800322DC(uint8_t* rdram, recomp_context* ctx) {
    // The run goes from index 6 down to index 0, a count of n enters it at n - 1.
    for (uint32_t index = steps_left(run_80032200, ctx->r13); index-- > 0;) {
        store16(rdram, ctx->r8, index * 2, ctx->r11); // sh $t3, index * 2($t0)
        store8(rdram, ctx->r9, index, ctx->r25);      // sb $t9, index($t1)
    }
}

// Before the "jr $t5" at 0x80032424. $t1 = r9, $t5 = r13.
extern "C" void kigold_computed_jump_80032424(uint8_t* rdram, recomp_context* ctx) {
    for (uint32_t index = steps_left(run_800323A4, ctx->r13); index-- > 0;) {
        store8(rdram, ctx->r9, index, 0); // sb $zero, index($t1)
    }
}
