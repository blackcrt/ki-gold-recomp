// Stand-alone test for src/game/computed_jump.cpp. No runtime, no game running.
//
// It compares two things for every count from 0 to 7, for both computed jumps:
//   - the game: the real instructions, read from the decompressed ROM on this PC
//     (build/kigold.decompressed.z64) and run by the small interpreter below,
//     from the count math up to the "jr $ra";
//   - ours: the function in src/game/computed_jump.cpp, called at the "jr $t5"
//     with the registers the game has at that point, like the hook does.
// It checks which stores happen, their order, the final registers and the final
// memory. Run it with: sh tools/jumptest/run.sh
//
// The interpreter only knows the few instructions these two pieces of code use
// and stops with an error on anything else. Nothing from the ROM is printed.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>

#include "recomp.h"

extern "C" void kigold_computed_jump_800322DC(uint8_t* rdram, recomp_context* ctx);
extern "C" void kigold_computed_jump_80032424(uint8_t* rdram, recomp_context* ctx);

namespace {
    // stream1 in the decompressed ROM (the section in syms/dump.toml).
    constexpr uint32_t STREAM1_ROM = 0x00C00000;
    constexpr uint32_t STREAM1_VRAM = 0x8000F960;
    // A made-up return address. Reaching it means the game's "jr $ra" ran.
    constexpr uint32_t RETURNED = 0x8FFFFFF0;
    // The test's piece of game memory: N64 addresses 0x80000000 and up.
    constexpr uint32_t MEMORY_SIZE = 0x4000;
    constexpr uint8_t MEMORY_FILL = 0xEE;

    struct Store {
        uint32_t address;
        uint32_t bytes;
        uint32_t value;
        bool operator==(const Store& other) const {
            return address == other.address && bytes == other.bytes && value == other.value;
        }
    };

    [[noreturn]] void stop(const std::string& text) {
        fprintf(stderr, "jumptest: %s\n", text.c_str());
        std::exit(2);
    }

    gpr sign32(uint32_t value) {
        return (gpr)(int64_t)(int32_t)value;
    }

    // The game side.
    struct Game {
        const std::vector<uint8_t>& rom;
        gpr reg[32]{};
        std::map<uint32_t, uint8_t> memory; // only the bytes the game wrote
        std::vector<Store> stores;

        explicit Game(const std::vector<uint8_t>& rom_file) : rom(rom_file) {}

        uint32_t word(uint32_t vram) const {
            size_t at = (size_t)STREAM1_ROM + (vram - STREAM1_VRAM);
            if (vram < STREAM1_VRAM || at + 4 > rom.size()) {
                stop("address outside stream1 in the ROM file");
            }
            return (uint32_t)rom[at] << 24 | (uint32_t)rom[at + 1] << 16 | (uint32_t)rom[at + 2] << 8 | rom[at + 3];
        }

        void store(uint32_t address, uint32_t bytes, uint32_t value) {
            stores.push_back({ address, bytes, value });
            for (uint32_t i = 0; i < bytes; i++) {
                memory[address + i] = (uint8_t)(value >> (8 * (bytes - 1 - i))); // big-endian
            }
        }

        // Runs from pc until until_pc is about to run, or until the game returns.
        // A jump takes effect after the instruction behind it (the delay slot).
        void run(uint32_t pc, uint32_t until_pc) {
            uint32_t next_pc = pc + 4;
            for (int steps = 0; steps < 200; steps++) {
                if (pc == until_pc || pc == RETURNED) {
                    return;
                }
                uint32_t w = word(pc);
                uint32_t op = w >> 26, rs = (w >> 21) & 31, rt = (w >> 16) & 31, rd = (w >> 11) & 31;
                uint32_t shift = (w >> 6) & 31, function = w & 63;
                int32_t imm = (int16_t)(w & 0xFFFF);
                uint32_t after = next_pc + 4;
                if (op == 0 && function == 0x00) {        // sll (all zero: nop)
                    reg[rd] = sign32((uint32_t)reg[rt] << shift);
                } else if (op == 0 && function == 0x21) { // addu
                    reg[rd] = sign32((uint32_t)reg[rs] + (uint32_t)reg[rt]);
                } else if (op == 0 && function == 0x23) { // subu
                    reg[rd] = sign32((uint32_t)reg[rs] - (uint32_t)reg[rt]);
                } else if (op == 0 && function == 0x08) { // jr
                    after = (uint32_t)reg[rs];
                } else if (op == 0x09) {                  // addiu
                    reg[rt] = sign32((uint32_t)reg[rs] + (uint32_t)imm);
                } else if (op == 0x0F) {                  // lui
                    reg[rt] = sign32((uint32_t)imm << 16);
                } else if (op == 0x29) {                  // sh
                    store((uint32_t)reg[rs] + (uint32_t)imm, 2, (uint16_t)reg[rt]);
                } else if (op == 0x28) {                  // sb
                    store((uint32_t)reg[rs] + (uint32_t)imm, 1, (uint8_t)reg[rt]);
                } else {
                    char text[120];
                    snprintf(text, sizeof(text),
                        "the instruction at 0x%08X is of a kind this test does not know (opcode %u, function %u)",
                        pc, op, function);
                    stop(text);
                }
                reg[0] = 0;
                pc = next_pc;
                next_pc = after;
            }
            stop("the game code did not return within 200 instructions");
        }
    };

    // Our side reports its stores here (KIGOLD_JUMP_TEST in computed_jump.cpp).
    std::vector<Store> our_stores;

    gpr recomp_context::* const REGISTERS[32] = {
        &recomp_context::r0, &recomp_context::r1, &recomp_context::r2, &recomp_context::r3,
        &recomp_context::r4, &recomp_context::r5, &recomp_context::r6, &recomp_context::r7,
        &recomp_context::r8, &recomp_context::r9, &recomp_context::r10, &recomp_context::r11,
        &recomp_context::r12, &recomp_context::r13, &recomp_context::r14, &recomp_context::r15,
        &recomp_context::r16, &recomp_context::r17, &recomp_context::r18, &recomp_context::r19,
        &recomp_context::r20, &recomp_context::r21, &recomp_context::r22, &recomp_context::r23,
        &recomp_context::r24, &recomp_context::r25, &recomp_context::r26, &recomp_context::r27,
        &recomp_context::r28, &recomp_context::r29, &recomp_context::r30, &recomp_context::r31,
    };

    struct Case {
        const char* function;
        uint32_t start; // first instruction of the count math (after the "bnez, nop")
        uint32_t jump;  // the "jr $t5"
        void (*ours)(uint8_t* rdram, recomp_context* ctx);
    };

    const Case CASES[] = {
        { "func_80032200", 0x800322C4, 0x800322DC, kigold_computed_jump_800322DC },
        { "func_800323A4", 0x8003240C, 0x80032424, kigold_computed_jump_80032424 },
    };

    // Two memory layouts: even addresses, and addresses that are not multiples of
    // 4 (the game's memory is stored byte-swapped on PC, so those are the risky ones).
    struct Layout {
        const char* name;
        uint32_t t0;
        uint32_t t1;
    };
    const Layout LAYOUTS[] = {
        { "t0 = 0x80001000, t1 = 0x80002000", 0x80001000, 0x80002000 },
        { "t0 = 0x80001006, t1 = 0x80002005", 0x80001006, 0x80002005 },
    };

    std::string describe(const std::vector<Store>& stores, const Layout& layout) {
        if (stores.empty()) {
            return "(none)";
        }
        std::string text;
        for (const Store& s : stores) {
            char one[48];
            if (s.bytes == 2) {
                snprintf(one, sizeof(one), "sh t0+0x%X", s.address - layout.t0);
            } else {
                snprintf(one, sizeof(one), "sb t1+%u", s.address - layout.t1);
            }
            text += text.empty() ? "" : ", ";
            text += one;
        }
        return text;
    }

    // One count of one jump in one layout. Returns true if game and ours agree.
    bool check(const std::vector<uint8_t>& rom, const Case& c, const Layout& layout, uint32_t count, bool print) {
        Game game(rom);
        for (uint32_t i = 1; i < 32; i++) {
            game.reg[i] = sign32(0x01010101u * i); // a different value in every register
        }
        game.reg[5] = count;                    // $a1, what is left to store
        game.reg[8] = sign32(layout.t0);        // $t0
        game.reg[9] = sign32(layout.t1);        // $t1
        game.reg[11] = 0x123456781234ABCDull;   // $t3, the low 16 bits get stored
        game.reg[25] = 0xC0C0C0C0C0C0C0C0ull;   // $t9, the low 8 bits get stored
        game.reg[31] = sign32(RETURNED);        // $ra

        // The count math, up to the jump. In the real build the translated game
        // code does this part.
        game.run(c.start, c.jump);
        uint32_t target = (uint32_t)game.reg[13]; // $t5

        // Ours: called at the jump, with the registers as they are now.
        std::vector<uint8_t> memory(MEMORY_SIZE, MEMORY_FILL);
        uint8_t* rdram = memory.data();
        recomp_context ctx{};
        for (uint32_t i = 0; i < 32; i++) {
            ctx.*REGISTERS[i] = game.reg[i];
        }
        our_stores.clear();
        c.ours(rdram, &ctx);

        // The game: the jump, the stores, the "jr $ra".
        game.run(c.jump, 0);

        bool same_stores = our_stores == game.stores;
        bool same_registers = true;
        for (uint32_t i = 0; i < 32; i++) {
            same_registers = same_registers && ctx.*REGISTERS[i] == game.reg[i];
        }
        bool same_memory = true;
        for (uint32_t offset = 0; offset < MEMORY_SIZE; offset++) {
            gpr address = sign32(0x80000000u + offset);
            auto wrote = game.memory.find(0x80000000u + offset);
            uint8_t expected = wrote == game.memory.end() ? MEMORY_FILL : wrote->second;
            same_memory = same_memory && MEM_BU(0, address) == expected;
        }
        bool pass = same_stores && same_registers && same_memory && game.stores.size() <= 14;
        if (print || !pass) {
            printf("  count %u: jumps to 0x%08X, %zu store(s): %s\n", count, target, game.stores.size(),
                describe(game.stores, layout).c_str());
            if (!same_stores) {
                printf("           OURS, %zu store(s): %s\n", our_stores.size(), describe(our_stores, layout).c_str());
            }
            printf("           stores and order %s, 32 registers %s, memory %s: %s\n",
                same_stores ? "same" : "DIFFERENT", same_registers ? "same" : "DIFFERENT",
                same_memory ? "same" : "DIFFERENT", pass ? "PASS" : "FAIL");
        }
        return pass;
    }
}

extern "C" void kigold_test_saw_store(uint32_t address, uint32_t bytes, uint32_t value) {
    our_stores.push_back({ address, bytes, value });
}

int main(int argc, char** argv) {
    if (argc != 2) {
        stop("usage: jumptest <path to build/kigold.decompressed.z64>");
    }
    std::ifstream file(argv[1], std::ios::binary);
    if (!file) {
        stop(std::string("cannot open ") + argv[1] + " (build it with python3 tools/unpack_rom.py)");
    }
    std::vector<uint8_t> rom((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());

    int passed = 0, total = 0;
    for (const Case& c : CASES) {
        for (const Layout& layout : LAYOUTS) {
            bool first_layout = &layout == &LAYOUTS[0];
            int layout_passed = 0;
            printf("%s, jump at 0x%08X, %s\n", c.function, c.jump, layout.name);
            for (uint32_t count = 0; count <= 7; count++) {
                bool pass = check(rom, c, layout, count, first_layout);
                layout_passed += pass;
                passed += pass;
                total++;
            }
            if (!first_layout) {
                printf("  counts 0 to 7: %d of 8 pass\n", layout_passed);
            }
        }
    }
    printf("\nResult: %d of %d pass\n", passed, total);
    return passed == total ? 0 : 1;
}
