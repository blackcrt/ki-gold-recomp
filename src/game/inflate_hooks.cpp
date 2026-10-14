// Inflate hooks: tell the runtime when the game has unpacked one of its code streams.
//
// The game keeps its code compressed in the ROM and inflates it into RAM itself
// (the recompiled boot code does this from the user's original ROM). The runtime
// only has to be told which block of recompiled functions now sits at which RAM
// address. That is load_overlays; it reads the section table, never the ROM.
//
// These functions are called from generated code through the [[patches.hook]]
// entries in kigold.toml:
//   kigold_on_rom_read       start of boot_rom_read (0x80000740) and func_800007B4
//   kigold_on_inflate_start  start of boot_inflate (0x80000900)
//   kigold_on_inflate_end    just before boot_inflate returns (0x80000950)
//   kigold_on_stream_entry   start of stream1_entry, stream2_entry, stream3_entry
//
// A stream is only accepted when both ends agree: the destination address, and
// the ROM offset the source buffer was last filled from, checked against the
// game's own stream table. Anything that only half matches is logged loudly and
// nothing is loaded or unloaded.
//
// Streams 2 and 3 share RAM (stream 3 lies inside stream 2), so the whole shared
// range is unloaded before either one is loaded.
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <unordered_map>
#include <vector>

#include "recomp.h"
#include "librecomp/overlays.hpp"

#include "kigold_decls.h"

namespace {
    // The game's stream table, copied to RAM with the boot code (ROM 0x7DE0).
    // Pairs of ROM offsets (start, end). Entries 0, 1, 2 are the code streams.
    constexpr int32_t STREAM_TABLE = (int32_t)0x800071E0;

    struct CodeStream {
        const char* name;
        // Offset in the decompressed ROM layout of tools/unpack_rom.py. The runtime
        // uses it only as the ID of the section in the generated section table.
        uint32_t section_rom;
        uint32_t ram;
        // Size of the whole inflated image (code and data).
        uint32_t size;
    };

    constexpr CodeStream STREAMS[3] = {
        { "stream1", 0x00C00000, 0x8000F960, 0x0003A7A0 },
        { "stream2", 0x00C3A7A0, 0x801ACB20, 0x000E8B40 },
        { "stream3", 0x00D232E0, 0x801AD900, 0x000259C0 },
    };

    // The RAM that streams 2 and 3 share: all of stream 2's image.
    constexpr uint32_t SHARED_RAM = 0x801ACB20;
    constexpr uint32_t SHARED_SIZE = 0x000E8B40;

    std::mutex state_mutex;
    // Buffer address -> ROM offset it was last filled from.
    std::unordered_map<uint32_t, uint32_t> last_rom_read;

    // What the inflate running on this thread is doing, for the end hook.
    thread_local int pending_stream = -1;
    thread_local uint32_t pending_dst = 0;

    int stream_by_destination(uint32_t dst) {
        for (int i = 0; i < 3; i++) {
            if (STREAMS[i].ram == dst) {
                return i;
            }
        }
        return -1;
    }

    int stream_by_rom_offset(uint8_t* rdram, uint32_t rom_offset) {
        for (int i = 0; i < 3; i++) {
            if ((uint32_t)MEM_W(8 * i, STREAM_TABLE) == rom_offset) {
                return i;
            }
        }
        return -1;
    }

    // Developer check, off by default. Set the environment variable
    // KIGOLD_VERIFY_INFLATE to the path of build/kigold.decompressed.z64 and each
    // code stream is compared with that file right after the game inflates it.
    // The file is game data: it stays on the developer's disk and is never shipped.
    const std::vector<uint8_t>* verify_image() {
        static bool tried = false;
        static std::vector<uint8_t> image;
        if (!tried) {
            tried = true;
            const char* path = std::getenv("KIGOLD_VERIFY_INFLATE");
            if (path != nullptr && path[0] != '\0') {
                std::ifstream file(path, std::ios::binary);
                image.assign(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
                if (image.empty()) {
                    fprintf(stderr, "[kigold][inflate] VERIFY: could not read %s, check is off\n", path);
                }
                else {
                    fprintf(stderr, "[kigold][inflate] VERIFY: on, comparing against %s (%zu bytes)\n", path, image.size());
                }
            }
        }
        return image.empty() ? nullptr : &image;
    }

    void verify_stream(uint8_t* rdram, const CodeStream& stream) {
        const std::vector<uint8_t>* image = verify_image();
        if (image == nullptr) {
            return;
        }
        if ((size_t)stream.section_rom + stream.size > image->size()) {
            fprintf(stderr, "[kigold][inflate] VERIFY: the file is too small to hold %s\n", stream.name);
            return;
        }
        uint32_t bad = 0;
        uint32_t first_bad = 0;
        // The address must be a sign-extended 64-bit value, as in a register. With a
        // 32-bit address and an unsigned index the sum is not sign-extended, and
        // MEM_B then reads 4 GB past the byte that was meant.
        gpr ram = (gpr)(int32_t)stream.ram;
        for (uint32_t i = 0; i < stream.size; i++) {
            uint8_t in_ram = (uint8_t)MEM_B(i, ram);
            if (in_ram != (*image)[stream.section_rom + i]) {
                if (bad == 0) {
                    first_bad = stream.ram + i;
                }
                bad++;
            }
        }
        if (bad == 0) {
            fprintf(stderr, "[kigold][inflate] VERIFY: %s OK, 0x%X bytes match\n", stream.name, stream.size);
        }
        else {
            fprintf(stderr, "[kigold][inflate] VERIFY: %s WRONG, %u of 0x%X bytes differ, first at 0x%08X\n",
                stream.name, bad, stream.size, first_bad);
        }
    }
}

// Arguments of both ROM read helpers: a0 = ROM offset, a1 = buffer, a2 = length.
extern "C" void kigold_on_rom_read(uint8_t* rdram, recomp_context* ctx) {
    // The earliest point where our code sees the game's memory: tell the crash reporter.
    kigold::note_rdram(rdram);
    std::lock_guard lock{ state_mutex };
    last_rom_read[(uint32_t)ctx->r5] = (uint32_t)ctx->r4;
}

// Arguments of boot_inflate: a0 = compressed source, a1 = destination, a2 = work buffer.
extern "C" void kigold_on_inflate_start(uint8_t* rdram, recomp_context* ctx) {
    kigold::count_inflate();
    uint32_t src = (uint32_t)ctx->r4;
    uint32_t dst = (uint32_t)ctx->r5;

    bool rom_known = false;
    uint32_t rom_offset = 0;
    {
        std::lock_guard lock{ state_mutex };
        auto it = last_rom_read.find(src);
        if (it != last_rom_read.end()) {
            rom_known = true;
            rom_offset = it->second;
            // Used up: a second inflate from this buffer needs a fresh ROM read to count.
            last_rom_read.erase(it);
        }
    }

    int by_dst = stream_by_destination(dst);
    int by_src = rom_known ? stream_by_rom_offset(rdram, rom_offset) : -1;

    pending_stream = -1;
    pending_dst = dst;

    char rom_text[32];
    if (rom_known) {
        snprintf(rom_text, sizeof(rom_text), "0x%08X", rom_offset);
    }
    else {
        snprintf(rom_text, sizeof(rom_text), "unknown");
    }

    if (by_dst >= 0 && by_dst == by_src) {
        const CodeStream& stream = STREAMS[by_dst];
        if (by_dst != 0) {
            unload_overlays((int32_t)SHARED_RAM, SHARED_SIZE);
        }
        load_overlays(stream.section_rom, (int32_t)stream.ram, stream.size);
        pending_stream = by_dst;
        fprintf(stderr, "[kigold][inflate] dst=0x%08X rom=%s: %s loaded\n", dst, rom_text, stream.name);
    }
    else if (by_dst >= 0) {
        fprintf(stderr,
            "[kigold][inflate] WARNING dst=0x%08X rom=%s: destination is where %s goes, but the source is not that stream. NOTHING LOADED OR UNLOADED\n",
            dst, rom_text, STREAMS[by_dst].name);
    }
    else if (by_src >= 0) {
        fprintf(stderr,
            "[kigold][inflate] WARNING dst=0x%08X rom=%s: source is %s, but the destination is not its address. NOTHING LOADED OR UNLOADED\n",
            dst, rom_text, STREAMS[by_src].name);
    }
    else {
        fprintf(stderr, "[kigold][inflate] dst=0x%08X rom=%s: data\n", dst, rom_text);
    }
}

extern "C" void kigold_on_inflate_end(uint8_t* rdram, recomp_context* ctx) {
    (void)ctx;
    int stream = pending_stream;
    pending_stream = -1;
    if (stream >= 0) {
        verify_stream(rdram, STREAMS[stream]);
    }
}

// The game has jumped into the first function of a code stream. Log only, to
// show how far a run gets. Stops after MAX_ENTRY_LINES so a stream that is
// entered again and again cannot flood the log.
extern "C" void kigold_on_stream_entry(uint8_t* rdram, recomp_context* ctx, int stream) {
    (void)rdram;
    (void)ctx;
    constexpr int MAX_ENTRY_LINES = 32;
    static int lines = 0;
    std::lock_guard lock{ state_mutex };
    if (lines > MAX_ENTRY_LINES || stream < 1 || stream > 3) {
        return;
    }
    if (lines == MAX_ENTRY_LINES) {
        fprintf(stderr, "[kigold][entry] more stream entries follow, not logged\n");
    }
    else {
        fprintf(stderr, "[kigold][entry] entered %s at 0x%08X\n", STREAMS[stream - 1].name, STREAMS[stream - 1].ram);
    }
    lines++;
}
