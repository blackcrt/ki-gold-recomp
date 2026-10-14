// Our own osDpSetNextBuffer, and a logger for the blocks the game passes to it.
//
// osDpSetNextBuffer(block, size) hands the console's drawing chip (the display
// processor, DP) a block of raw drawing commands. The chip draws them and then
// raises a "DP done" interrupt. N64ModernRuntime at our pin has a body for this
// name that does nothing, so the interrupt never came and the game's scheduler
// waited forever (runs 6 and 7, see NOTES.md tasks 7k and 7l).
//
// Stand-in: nothing is drawn. The block is counted, the first few are printed,
// and the "DP done" message is sent so the scheduler goes on. The block's
// drawing (screen clear or background picture) is lost for now.
//
// Which queue and which message. The runtime keeps the queue a game registers
// for an event in a private place, and its own "DP done" sender is not in a
// public header. So the two values are written down here, from the game's code:
//   0x80001E4C  osCreateMesgQueue(0x8000CF70, 0x8000CFA8, 5)
//   0x80001E60  osSetEventMesg(9, 0x8000CF70, 1)    9 is OS_EVENT_DP
//   0x80001E74  osSetEventMesg(4, 0x8000CF70, 2)    4 is OS_EVENT_SP
// Run 7 agrees: the scheduler thread (20) sat waiting on queue 0x8000CF70.
// Both callers (0x80002490, 0x80002534) pass the block in a0 and its size in
// a2:a3 (a 64-bit value, the high half is always 0), and treat a return value
// of -1 as "busy, try again".
//
// This file defines the same name as librecomp's dp.cpp. Generated code uses no
// other name from that file, so the linker takes ours and leaves that one out.
#include <atomic>
#include <cstdio>

#include "kigold_decls.h"

namespace {
    constexpr int32_t DP_QUEUE = (int32_t)0x8000CF70;
    constexpr int32_t DP_QUEUE_SLOTS = 5;
    constexpr uint32_t DP_MESSAGE = 1;

    // How many blocks are printed command by command before the logger goes quiet.
    constexpr uint64_t PRINTED_BLOCKS = 3;
    // The game's blocks hold 200 commands at most (0x640 bytes).
    constexpr int MAX_PRINTED_COMMANDS = 256;

    constexpr uint32_t CONSOLE_RAM_START = 0x80000000;
    constexpr uint32_t CONSOLE_RAM_SIZE = 8 * 1024 * 1024;

    std::atomic<uint64_t> blocks_seen{ 0 };
    std::atomic<bool> warned_queue{ false };

    uint32_t read_word(uint8_t* rdram, uint32_t address) {
        return (uint32_t)MEM_W(0, (gpr)(int32_t)address);
    }

    // The chip only looks at the low 6 bits of a command's first byte.
    const char* command_name(uint32_t opcode) {
        switch (opcode) {
            case 0x00: return "no operation";
            case 0x08: return "triangle";
            case 0x09: return "triangle, depth";
            case 0x0A: return "triangle, textured";
            case 0x0B: return "triangle, textured, depth";
            case 0x0C: return "triangle, shaded";
            case 0x0D: return "triangle, shaded, depth";
            case 0x0E: return "triangle, shaded, textured";
            case 0x0F: return "triangle, shaded, textured, depth";
            case 0x24: return "texture rectangle";
            case 0x25: return "texture rectangle, flipped";
            case 0x26: return "sync load";
            case 0x27: return "sync pipe";
            case 0x28: return "sync tile";
            case 0x29: return "sync full (end of drawing)";
            case 0x2A: return "set key green and blue";
            case 0x2B: return "set key red";
            case 0x2C: return "set convert";
            case 0x2D: return "set scissor";
            case 0x2E: return "set primitive depth";
            case 0x2F: return "set other modes";
            case 0x30: return "load palette";
            case 0x32: return "set tile size";
            case 0x33: return "load block";
            case 0x34: return "load tile";
            case 0x35: return "set tile";
            case 0x36: return "fill rectangle";
            case 0x37: return "set fill color";
            case 0x38: return "set fog color";
            case 0x39: return "set blend color";
            case 0x3A: return "set primitive color";
            case 0x3B: return "set environment color";
            case 0x3C: return "set combine";
            case 0x3D: return "set texture image";
            case 0x3E: return "set depth image";
            case 0x3F: return "set color image";
            default: return "UNKNOWN";
        }
    }

    // Most commands are 8 bytes. A texture rectangle is 16. A triangle is 32,
    // plus 64 if shaded, 64 if textured and 16 if it has depth.
    uint32_t command_bytes(uint32_t opcode) {
        if (opcode >= 0x08 && opcode <= 0x0F) {
            return 32 + ((opcode & 4) ? 64 : 0) + ((opcode & 2) ? 64 : 0) + ((opcode & 1) ? 16 : 0);
        }
        if (opcode == 0x24 || opcode == 0x25) {
            return 16;
        }
        return 8;
    }

    const char* image_format(uint32_t format) {
        static const char* const names[] = { "RGBA", "YUV", "color index", "intensity+alpha", "intensity" };
        return format < 5 ? names[format] : "format?";
    }

    int pixel_bits(uint32_t size) {
        return 4 << size;
    }

    // Screen and texture positions are stored in quarter pixels.
    double quarter(uint32_t value) {
        return value / 4.0;
    }

    // Triangle heights: 14 bits, signed, in quarter pixels.
    double triangle_y(uint32_t value) {
        int32_t y = (int32_t)(value & 0x3FFF);
        if (y & 0x2000) {
            y -= 0x4000;
        }
        return y / 4.0;
    }

    // The main values of a command in plain words. w2 and w3 are only read for
    // texture rectangles (the caller passes 0 if the block ends before them).
    void describe_command(uint32_t opcode, uint32_t w0, uint32_t w1, uint32_t w2, uint32_t w3,
            char* out, size_t out_size) {
        uint32_t hi_a = (w0 >> 12) & 0xFFF;
        uint32_t lo_a = w0 & 0xFFF;
        uint32_t hi_b = (w1 >> 12) & 0xFFF;
        uint32_t lo_b = w1 & 0xFFF;
        uint32_t tile = (w1 >> 24) & 7;
        out[0] = '\0';

        if (opcode >= 0x08 && opcode <= 0x0F) {
            snprintf(out, out_size, ": %u bytes, %s edge major, tile %u, y from %g to %g (middle %g)",
                command_bytes(opcode), (w0 & 0x00800000) ? "left" : "right", (w0 >> 16) & 7,
                triangle_y(w1), triangle_y(w0), triangle_y(w1 >> 16));
            return;
        }
        switch (opcode) {
            case 0x24:
            case 0x25:
                snprintf(out, out_size,
                    ": from %g,%g to %g,%g, tile %u, texture start %g,%g, step %g,%g per pixel",
                    quarter(hi_b), quarter(lo_b), quarter(hi_a), quarter(lo_a), tile,
                    (int16_t)(w2 >> 16) / 32.0, (int16_t)(w2 & 0xFFFF) / 32.0,
                    (int16_t)(w3 >> 16) / 1024.0, (int16_t)(w3 & 0xFFFF) / 1024.0);
                break;
            case 0x2D:
                snprintf(out, out_size, ": from %g,%g to %g,%g",
                    quarter(hi_a), quarter(lo_a), quarter(hi_b), quarter(lo_b));
                break;
            case 0x2E:
                snprintf(out, out_size, ": depth 0x%04X, depth step 0x%04X", w1 >> 16, w1 & 0xFFFF);
                break;
            case 0x2F: {
                static const char* const cycles[] = { "1 cycle", "2 cycle", "copy", "fill" };
                snprintf(out, out_size, ": %s mode, high bits 0x%06X, low bits 0x%08X",
                    cycles[(w0 >> 20) & 3], w0 & 0xFFFFFF, w1);
                break;
            }
            case 0x30:
                snprintf(out, out_size, ": tile %u, %u colors starting at color %u",
                    tile, (hi_b >> 2) - (hi_a >> 2) + 1, hi_a >> 2);
                break;
            case 0x32:
            case 0x34:
                snprintf(out, out_size, ": tile %u, from %g,%g to %g,%g",
                    tile, quarter(hi_a), quarter(lo_a), quarter(hi_b), quarter(lo_b));
                break;
            case 0x33:
                snprintf(out, out_size, ": tile %u, %u texels starting at %u,%u, row step 0x%03X",
                    tile, hi_b + 1 - hi_a, hi_a, lo_a, lo_b);
                break;
            case 0x35:
                snprintf(out, out_size,
                    ": tile %u, %s %d-bit, %u words per row, texture memory offset %u, palette %u",
                    tile, image_format((w0 >> 21) & 7), pixel_bits((w0 >> 19) & 3), (w0 >> 9) & 0x1FF,
                    w0 & 0x1FF, (w1 >> 20) & 0xF);
                break;
            case 0x36:
                snprintf(out, out_size, ": from %g,%g to %g,%g",
                    quarter(hi_b), quarter(lo_b), quarter(hi_a), quarter(lo_a));
                break;
            case 0x37:
                snprintf(out, out_size, ": color value 0x%08X", w1);
                break;
            case 0x38:
            case 0x39:
            case 0x3B:
                snprintf(out, out_size, ": red %u, green %u, blue %u, alpha %u",
                    w1 >> 24, (w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF);
                break;
            case 0x3A:
                snprintf(out, out_size, ": red %u, green %u, blue %u, alpha %u, detail level %u, fraction %u",
                    w1 >> 24, (w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF, (w0 >> 8) & 0x1F, w0 & 0xFF);
                break;
            case 0x2A:
            case 0x2B:
            case 0x2C:
            case 0x3C:
                snprintf(out, out_size, ": values 0x%06X 0x%08X", w0 & 0xFFFFFF, w1);
                break;
            case 0x3D:
            case 0x3F:
                snprintf(out, out_size, ": %s %d-bit, width %u, address 0x%08X",
                    image_format((w0 >> 21) & 7), pixel_bits((w0 >> 19) & 3), (w0 & 0x3FF) + 1, w1);
                break;
            case 0x3E:
                snprintf(out, out_size, ": address 0x%08X", w1);
                break;
            default:
                break;
        }
    }

    void print_block(uint8_t* rdram, uint64_t number, uint32_t block, uint32_t size) {
        fprintf(stderr, "[kigold][dp] ==== block %llu of the first %llu: address 0x%08X, %u bytes ====\n",
            (unsigned long long)number, (unsigned long long)PRINTED_BLOCKS, block, size);

        bool in_ram = block >= CONSOLE_RAM_START && (block & 7) == 0
            && size <= CONSOLE_RAM_SIZE && block - CONSOLE_RAM_START <= CONSOLE_RAM_SIZE - size;
        if (!in_ram) {
            fprintf(stderr, "[kigold][dp]   WARNING: that is not a block inside the game's RAM, not printed\n");
            return;
        }

        uint32_t offset = 0;
        int commands = 0;
        while (offset + 8 <= size && commands < MAX_PRINTED_COMMANDS) {
            uint32_t w0 = read_word(rdram, block + offset);
            uint32_t w1 = read_word(rdram, block + offset + 4);
            uint32_t first_byte = w0 >> 24;
            uint32_t opcode = first_byte & 0x3F;
            uint32_t length = command_bytes(opcode);
            bool whole = offset + length <= size;
            uint32_t w2 = (whole && length >= 16) ? read_word(rdram, block + offset + 8) : 0;
            uint32_t w3 = (whole && length >= 16) ? read_word(rdram, block + offset + 12) : 0;

            char values[200];
            describe_command(opcode, w0, w1, w2, w3, values, sizeof(values));
            // Normal commands have the top two bits of the first byte set. The
            // chip ignores them, but a renderer that reads the whole byte may not.
            char odd_byte[64] = "";
            if ((first_byte & 0xC0) != 0xC0) {
                snprintf(odd_byte, sizeof(odd_byte), " [first byte 0x%02X, only its low 6 bits count]", first_byte);
            }
            fprintf(stderr, "[kigold][dp]   #%03d +0x%03X  %08X %08X  %s%s%s%s\n",
                commands, offset, w0, w1, command_name(opcode), values, odd_byte,
                whole ? "" : " [CUT OFF: the block ends inside this command]");
            commands++;
            offset += length;
        }
        fprintf(stderr, "[kigold][dp] ==== block %llu end: %d commands%s ====\n",
            (unsigned long long)number, commands,
            offset + 8 <= size ? ", the rest was not printed" : "");
    }

    // True if the queue the "DP done" message goes to is the one the game made.
    bool dp_queue_looks_right(uint8_t* rdram) {
        const OSMesgQueue* queue = TO_PTR(OSMesgQueue, DP_QUEUE);
        return queue->msgCount == DP_QUEUE_SLOTS;
    }
}

extern "C" void osDpSetNextBuffer_recomp(uint8_t* rdram, recomp_context* ctx) {
    uint32_t block = (uint32_t)ctx->r4;
    uint32_t size = (uint32_t)ctx->r7;

    uint64_t number = blocks_seen.fetch_add(1, std::memory_order_relaxed) + 1;
    kigold::count_dp_block();
    if (number == 1) {
        fprintf(stderr,
            "[kigold][dp] osDpSetNextBuffer STAND-IN: blocks are NOT DRAWN. Each one is answered with message %u on queue 0x%08X (\"DP done\")\n",
            DP_MESSAGE, (uint32_t)DP_QUEUE);
    }
    if (number <= PRINTED_BLOCKS) {
        print_block(rdram, number, block, size);
    }
    if (number == PRINTED_BLOCKS) {
        fprintf(stderr, "[kigold][dp] no more blocks are printed. The heartbeat line keeps counting them (DP blocks)\n");
    }

    if (dp_queue_looks_right(rdram)) {
        // Same call the runtime makes for its own "DP done": do not jump the
        // queue, and try again later if the queue is full.
        ultramodern::enqueue_external_message(DP_QUEUE, (OSMesg)DP_MESSAGE, false, true);
    }
    else if (!warned_queue.exchange(true)) {
        fprintf(stderr,
            "[kigold][dp] WARNING: queue 0x%08X does not have %d slots, so it is not the queue the game made. \"DP done\" NOT SENT, the game will wait\n",
            (uint32_t)DP_QUEUE, (int)DP_QUEUE_SLOTS);
    }

    // 0 means "accepted". -1 would mean "busy, try again".
    ctx->r2 = 0;
}
