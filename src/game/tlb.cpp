// TLB mapping: osMapTLB and osUnmapTLB for the runtime, which has no TLB support.
//
// The game maps per-fighter data blocks and one palette page at low virtual
// addresses (see PLAN.md, risks table, "TLB mapping", and NOTES.md, tasks 7o to
// 7r). It uses the same memory through the low address and through the normal
// 0x80000000 address, in both directions, so a one-time copy is not enough.
//
// How it works: our runtime fork (docs/RUNTIME_FORK.md) backs the game's RAM with
// a Windows section object and leaves the rest of its 4 GB block as placeholder
// memory. A low N64 address lands exactly 2 GB into that block (MEM_W in
// recomp.h). osMapTLB maps the wanted 4 KB physical page of the section a second
// time at that spot, osUnmapTLB removes it and leaves a placeholder. After that
// every access just works, from generated code, the runtime or the renderer, at
// no cost per access. Proven outside the game by tools/tlbtest.
//
// Not handled: the address space ID (logged only), page sizes other than 4 KB
// (stops the game), and osVirtualToPhysical on a low address (open item in
// NOTES.md).
//
// libultra signatures (public, from the N64 SDK headers):
//   void osMapTLB(s32 index, OSPageMask pm, void* vaddr, u32 evenpaddr, u32 oddpaddr, s32 asid);
//   void osUnmapTLB(s32 index);
#include <cstdarg>
#include <cstdio>
#include <mutex>

#include "kigold_decls.h"
#include "librecomp/addresses.hpp"
#include "librecomp/game.hpp"
#include "ultramodern/error_handling.hpp"

#ifdef _WIN32
#include <Windows.h>
#endif

namespace {

constexpr int kEntries = 32;
constexpr uint32_t kPage = 0x1000;
// libultra passes -1 for a page of the pair that is not mapped.
constexpr uint32_t kNoPage = 0xFFFFFFFF;
// Where N64 address 0 lands inside the runtime's block.
constexpr uint64_t kLowOffset = 0x80000000ULL;

// A TLB entry covers two pages next to each other: [0] even, [1] odd.
struct Entry {
    bool mapped[2];
    uint32_t vaddr[2];
    uint32_t paddr[2];
};

std::mutex tlb_mutex;
Entry entries[kEntries] = {};

// A per-round remap must not flood the log: only the first lines are printed.
constexpr int kMaxLogLines = 64;
int log_lines = 0;

// Called with tlb_mutex held.
void log_line(const char* format, ...) {
    if (log_lines > kMaxLogLines) {
        return;
    }
    if (log_lines == kMaxLogLines) {
        log_lines++;
        fprintf(stderr, "[kigold][tlb] %d lines printed, further TLB lines are hidden (errors are still printed)\n", kMaxLogLines);
        return;
    }
    log_lines++;
    va_list args;
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
}

// Any TLB request we cannot carry out stops the game: carrying on would mean the
// game reads or writes memory that is not there, or the wrong memory.
[[noreturn]] void fatal(const char* format, ...) {
    char text[256];
    va_list args;
    va_start(args, format);
    vsnprintf(text, sizeof(text), format, args);
    va_end(args);
    fprintf(stderr, "[kigold][tlb] FATAL: %s\n", text);
    fflush(stderr);
    ultramodern::error_handling::quick_exit(__FILE__, __LINE__, __FUNCTION__);
}

#ifdef _WIN32

// MapViewOfFile3 (Windows 10 version 1803 and newer) is not in kernel32.lib, so
// it is looked up by name, the same way the runtime fork and tools/tlbtest do.
using MapViewOfFile3Fn = PVOID(WINAPI*)(HANDLE, HANDLE, PVOID, ULONG64, SIZE_T, ULONG, ULONG, void*, ULONG);

MapViewOfFile3Fn map_view_of_file3() {
    static const MapViewOfFile3Fn found = reinterpret_cast<MapViewOfFile3Fn>(reinterpret_cast<void*>(
        GetProcAddress(GetModuleHandleW(L"kernelbase.dll"), "MapViewOfFile3")));
    return found;
}

void map_view(uint8_t* rdram, int index, uint32_t vaddr, uint32_t paddr) {
    void* section = recomp::get_rdram_section();
    if (section == nullptr || map_view_of_file3() == nullptr) {
        fatal("no shared memory section from the runtime. Is lib/N64ModernRuntime on the kigold branch (docs/RUNTIME_FORK.md)?");
    }
    void* spot = rdram + kLowOffset + vaddr;
    // Cut a 4 KB placeholder out of the bigger one. This fails when the spot
    // already is a 4 KB placeholder (left by an earlier unmap), which is fine:
    // the mapping call below is what decides.
    VirtualFree(spot, kPage, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
    void* view = map_view_of_file3()(section, nullptr, spot, paddr, kPage, MEM_REPLACE_PLACEHOLDER, PAGE_READWRITE, nullptr, 0);
    if (view != spot) {
        fatal("entry %d: mapping virtual 0x%08X to physical 0x%08X failed, Windows error %lu", index, vaddr, paddr, GetLastError());
    }
}

void unmap_view(uint8_t* rdram, int index, uint32_t vaddr) {
    if (UnmapViewOfFileEx(rdram + kLowOffset + vaddr, MEM_PRESERVE_PLACEHOLDER) == 0) {
        fatal("entry %d: unmapping virtual 0x%08X failed, Windows error %lu", index, vaddr, GetLastError());
    }
}

#else

void map_view(uint8_t*, int index, uint32_t, uint32_t) {
    fatal("entry %d: TLB mapping is only written for Windows", index);
}

void unmap_view(uint8_t*, int index, uint32_t) {
    fatal("entry %d: TLB mapping is only written for Windows", index);
}

#endif

// Removes the views of one entry. Returns how many pages were unmapped.
// Called with tlb_mutex held.
int clear_entry(uint8_t* rdram, int index) {
    int count = 0;
    for (int half = 0; half < 2; half++) {
        if (entries[index].mapped[half]) {
            unmap_view(rdram, index, entries[index].vaddr[half]);
            entries[index].mapped[half] = false;
            count++;
        }
    }
    return count;
}

} // namespace

extern "C" void osMapTLB_recomp(uint8_t* rdram, recomp_context* ctx) {
    int32_t index = (int32_t)ctx->r4;
    uint32_t pagemask = (uint32_t)ctx->r5;
    uint32_t vaddr = (uint32_t)ctx->r6;
    // Arguments 5 and 6 are passed on the stack, at sp + 0x10 and sp + 0x14.
    uint32_t paddr[2] = { (uint32_t)ctx->r7, (uint32_t)MEM_W(0x10, ctx->r29) };
    int32_t asid = (int32_t)MEM_W(0x14, ctx->r29);
    uint32_t ra = (uint32_t)ctx->r31;

    if (index < 0 || index >= kEntries) {
        fatal("osMapTLB index %d is not 0 to %d (ra=0x%08X)", index, kEntries - 1, ra);
    }
    if (pagemask != 0) {
        fatal("osMapTLB entry %d asks for page mask 0x%08X, only 4 KB pages (mask 0) are written (ra=0x%08X)", index, pagemask, ra);
    }
    // The CPU ignores the low 13 bits of the virtual address: an entry always
    // starts at an even page.
    uint32_t base = vaddr & ~(2 * kPage - 1);
    if (base >= 0x80000000u) {
        fatal("osMapTLB entry %d: virtual 0x%08X is not a low address (ra=0x%08X)", index, vaddr, ra);
    }

    std::lock_guard lock{ tlb_mutex };
    // A remap replaces what the entry held before.
    clear_entry(rdram, index);

    int count = 0;
    for (int half = 0; half < 2; half++) {
        if (paddr[half] == kNoPage) {
            continue;
        }
        uint32_t page_vaddr = base + half * kPage;
        if ((paddr[half] & (kPage - 1)) != 0 || paddr[half] >= recomp::mem_size) {
            fatal("osMapTLB entry %d: physical 0x%08X is not a 4 KB page inside the game's memory (ra=0x%08X)", index, paddr[half], ra);
        }
        // Two entries for the same virtual page are an error on the real CPU too.
        for (int other = 0; other < kEntries; other++) {
            for (int other_half = 0; other_half < 2; other_half++) {
                if (entries[other].mapped[other_half] && entries[other].vaddr[other_half] == page_vaddr) {
                    fatal("osMapTLB entry %d: virtual 0x%08X is already mapped by entry %d (ra=0x%08X)", index, page_vaddr, other, ra);
                }
            }
        }
        map_view(rdram, index, page_vaddr, paddr[half]);
        entries[index].mapped[half] = true;
        entries[index].vaddr[half] = page_vaddr;
        entries[index].paddr[half] = paddr[half];
        count++;
    }

    log_line("[kigold][tlb] osMapTLB index=%d pagemask=0x%08X vaddr=0x%08X evenpaddr=0x%08X oddpaddr=0x%08X asid=%d ra=0x%08X (MAPPED, %d page(s))\n",
        index, pagemask, vaddr, paddr[0], paddr[1], asid, ra, count);
}

extern "C" void osUnmapTLB_recomp(uint8_t* rdram, recomp_context* ctx) {
    int32_t index = (int32_t)ctx->r4;
    uint32_t ra = (uint32_t)ctx->r31;

    if (index < 0 || index >= kEntries) {
        fatal("osUnmapTLB index %d is not 0 to %d (ra=0x%08X)", index, kEntries - 1, ra);
    }

    std::lock_guard lock{ tlb_mutex };
    int count = clear_entry(rdram, index);
    // The game unmaps entries 0 to 30 before every remap. Only the ones that
    // held something are worth a line.
    if (count != 0) {
        log_line("[kigold][tlb] osUnmapTLB index=%d ra=0x%08X (UNMAPPED, %d page(s))\n", index, ra, count);
    }
}
