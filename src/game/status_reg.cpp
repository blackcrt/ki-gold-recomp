// Lets the game switch on the "FPU usable" bit of the CPU's status register.
//
// The first function of stream3 (0x801AD900, hand-written assembly) does what
// boot code does on a console: it reads the status register, sets bit
// 0x20000000 (CU1: floating point instructions are allowed) and writes it back
// at 0x801AD9F0. N64ModernRuntime at our pin only knows one status bit (FR). For
// any other changed bit its cop0_status_write prints "Unhandled status register
// bits changed" and calls exit(). In run 9 that exit() then crashed inside the
// menu library's cleanup, which hid the real cause (see NOTES.md, task 7n).
//
// On PC the bit means nothing: recompiled floating point code is plain C math
// and cannot be switched off. So the bit only has to be remembered, so that a
// later read of the register gives back what the game wrote.
//
// How. The runtime's function cannot be replaced (the runtime uses it itself,
// the linker would see two). Instead a [[patches.hook]] in kigold.toml calls
// kigold_before_status_write just before that one write. It copies the bit into
// the register first, so the runtime sees no change in it. Every other bit is
// left for the runtime to judge: a change we have not looked at should still
// stop the run.
#include <atomic>
#include <cstdio>

#include "recomp.h"

namespace {
    // CU1, "coprocessor 1 usable". Coprocessor 1 is the FPU.
    constexpr uint32_t STATUS_FPU_USABLE = 0x20000000;

    std::atomic<bool> told{ false };
}

// value is what the game is about to write to the status register.
extern "C" void kigold_before_status_write(recomp_context* ctx, gpr value) {
    uint32_t changed = (ctx->status_reg ^ (uint32_t)value) & STATUS_FPU_USABLE;
    if (changed == 0) {
        return;
    }
    ctx->status_reg ^= changed;
    if (!told.exchange(true)) {
        fprintf(stderr,
            "[kigold][status] the game writes 0x%08X to the status register: \"FPU usable\" bit (0x%08X) switched %s. Accepted, it has no meaning on PC\n",
            (uint32_t)value, STATUS_FPU_USABLE, ((uint32_t)value & STATUS_FPU_USABLE) ? "ON" : "OFF");
    }
}
