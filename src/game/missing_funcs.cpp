// Functions the recompiled game calls that the runtime does not provide.
//
// N64Recomp leaves these five libultra names for the runtime to supply, but
// N64ModernRuntime at our pin has no body for them. They are reached only from
// unnamed Controller Pak style code (7 functions in boot and stream1) and, for
// __osContDataCrc, from the save checksum code in stream2.
//
// These bodies ONLY LOG. They do no work and return nothing useful, so whatever
// calls them will misbehave. Each line is loud on purpose: if one shows up in a
// run, that function needs a real answer (see NOTES.md, task 6c).
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
KIGOLD_MISSING(__osContAddressCrc)
KIGOLD_MISSING(__osContDataCrc)
