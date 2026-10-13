// Functions the recompiled game calls that the runtime does not provide.
//
// N64Recomp leaves these three libultra names for the runtime to supply, but
// N64ModernRuntime at our pin has no body for them. They are reached only from
// unnamed Controller Pak style code (7 functions in stream1).
//
// None of them does the real work, so each call logs a loud line: if one shows
// up in a run, the game got into its Controller Pak code, which the static
// reading says should not happen while no pak is reported (see NOTES.md, tasks
// 6c, 7c and 7d).
//
// __osContAddressCrc and __osContDataCrc used to be here. The game's own code
// for them is now translated instead (KEEP_GAME_CODE in tools/gen_symbols.py).
#include <cstdio>

#include "recomp.h"
#include "ultramodern/ultramodern.hpp"

#define KIGOLD_LOG_MISSING(name, what) \
    fprintf(stderr, \
        "[kigold][MISSING] " #name " called: a0=0x%08X a1=0x%08X a2=0x%08X a3=0x%08X ra=0x%08X (" what ")\n", \
        (uint32_t)ctx->r4, (uint32_t)ctx->r5, (uint32_t)ctx->r6, (uint32_t)ctx->r7, \
        (uint32_t)ctx->r31)

// These two take and release the lock on the serial port. Doing nothing is
// harmless as long as one thread at a time uses the port.
#define KIGOLD_MISSING(name) \
    extern "C" void name##_recomp(uint8_t* rdram, recomp_context* ctx) { \
        (void)rdram; \
        KIGOLD_LOG_MISSING(name, "NO BODY, log only"); \
    }

KIGOLD_MISSING(__osSiGetAccess)
KIGOLD_MISSING(__osSiRelAccess)

// The serial port block the game sends and reads back: 64 bytes, the last one
// is a control byte.
static constexpr int SI_BLOCK_SIZE = 64;
static constexpr int SI_CONTROL = SI_BLOCK_SIZE - 1;

// The last block the game sent, already answered.
static uint8_t si_block[SI_BLOCK_SIZE];

// Answers every command in the block the way the console does when nothing is
// plugged in: bit 7 of the command's receive length is set ("no response") and
// the receive bytes are left as they were.
//
// Block layout (standard for the console): a 0x00 byte skips a port, 0xFF is
// padding, 0xFD resets a port, 0xFE ends the block. Anything else starts a
// command: send length, receive length, then that many send and receive bytes.
static void si_answer_nothing_plugged_in(uint8_t* block) {
    int i = 0;
    while (i < SI_CONTROL) {
        uint8_t send = block[i];
        if (send == 0xFE) {
            break;
        }
        if (send == 0x00 || send == 0xFF || send == 0xFD) {
            i++;
            continue;
        }
        if (i + 1 >= SI_CONTROL || block[i + 1] == 0xFE) {
            break;
        }
        uint8_t receive = block[i + 1];
        block[i + 1] = receive | 0x80;
        i += 2 + (send & 0x3F) + (receive & 0x3F);
    }
    // The console clears the "run the commands" bit when it is done.
    block[SI_CONTROL] = 0;
}

// __osSiRawStartDma(direction, block): direction 1 sends the block to the
// console's controller chip, direction 0 reads the answered block back. Each
// caller then waits for the "serial port done" message.
//
// Stand-in: there is no controller chip here, so a sent block is kept and
// answered as "nothing plugged in", and a read returns that answer. Callers
// overwrite their buffer between the two calls, so the answer has to be kept
// here. The done message is sent through the runtime so no thread waits forever.
extern "C" void __osSiRawStartDma_recomp(uint8_t* rdram, recomp_context* ctx) {
    KIGOLD_LOG_MISSING(__osSiRawStartDma, "STAND-IN, answers as nothing plugged in");

    gpr block = ctx->r5;
    if ((int32_t)ctx->r4 == 1) {
        for (int i = 0; i < SI_BLOCK_SIZE; i++) {
            si_block[i] = (uint8_t)MEM_BU(i, block);
        }
        si_answer_nothing_plugged_in(si_block);
    }
    else {
        for (int i = 0; i < SI_BLOCK_SIZE; i++) {
            MEM_B(i, block) = (int8_t)si_block[i];
        }
    }

    ultramodern::send_si_message();
    ctx->r2 = 0;
}
