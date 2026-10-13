// Functions the recompiled game calls that the runtime does not provide.
//
// N64Recomp leaves these three libultra names for the runtime to supply, but
// N64ModernRuntime at our pin has no body for them. They are reached only from
// unnamed Controller Pak style code (7 functions in stream1).
//
// These bodies ONLY LOG. They do no work and return nothing useful, so whatever
// calls them will misbehave. Each line is loud on purpose: if one shows up in a
// run, that function needs a real answer (see NOTES.md, tasks 6c and 7c).
//
// __osContAddressCrc and __osContDataCrc used to be here. The game's own code
// for them is now translated instead (KEEP_GAME_CODE in tools/gen_symbols.py).
#include <cstdio>

#include "recomp.h"

#define KIGOLD_MISSING(name) \
    extern "C" void name##_recomp(uint8_t* rdram, recomp_context* ctx) { \
        (void)rdram; \
        fprintf(stderr, \
            "[kigold][MISSING] " #name " called: a0=0x%08X a1=0x%08X a2=0x%08X a3=0x%08X ra=0x%08X (NO BODY, log only)\n", \
            (uint32_t)ctx->r4, (uint32_t)ctx->r5, (uint32_t)ctx->r6, (uint32_t)ctx->r7, \
            (uint32_t)ctx->r31); \
    }

KIGOLD_MISSING(__osSiGetAccess)
KIGOLD_MISSING(__osSiRelAccess)
KIGOLD_MISSING(__osSiRawStartDma)
