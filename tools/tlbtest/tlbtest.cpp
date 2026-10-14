// Stand-alone proof test for the TLB design (NOTES.md, tasks 7o to 7r).
// Our own code, no game code, no runtime code. Windows only.
//
// It proves, outside the game:
//   1. The allocation our N64ModernRuntime fork does (docs/RUNTIME_FORK.md):
//      a 4 GB block reserved as "placeholder" memory, with one shared memory
//      section mapped over the first 512 MB. Part 1 uses the same calls in the
//      same order as the fork.
//   2. 4 KB pieces of that section can be mapped a second time at 4 KB-aligned
//      spots 2 GB into the block (where N64 addresses below 0x80000000 land),
//      so the same memory is reachable through two addresses.
//   3. Remapping those pieces does not disturb another thread that reads the
//      first 512 MB the whole time, like the renderer does in the game.
//
// Build and run: tools\tlbtest\build.ps1

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <thread>

namespace {

constexpr size_t kBlockSize = 4096ULL * 1024ULL * 1024ULL; // runtime: allocation_size
constexpr size_t kRamSize = 512ULL * 1024ULL * 1024ULL;    // runtime: mem_size
constexpr size_t kPage = 0x1000;

// VirtualAlloc2 and MapViewOfFile3 live in kernelbase.dll (Windows 10 1803 and
// newer) and are not in kernel32.lib, so look them up by name.
using VirtualAlloc2Fn = PVOID(WINAPI*)(HANDLE, PVOID, SIZE_T, ULONG, ULONG, void*, ULONG);
using MapViewOfFile3Fn = PVOID(WINAPI*)(HANDLE, HANDLE, PVOID, ULONG64, SIZE_T, ULONG, ULONG, void*, ULONG);

VirtualAlloc2Fn pVirtualAlloc2 = nullptr;
MapViewOfFile3Fn pMapViewOfFile3 = nullptr;

uint8_t* block = nullptr;
HANDLE section = nullptr;
int passes = 0;
int fails = 0;

void check(bool ok, const char* text) {
    if (ok) {
        passes++;
        std::printf("PASS  %s\n", text);
    }
    else {
        fails++;
        std::printf("FAIL  %s (last error %lu)\n", text, GetLastError());
    }
}

// Same arithmetic as the MEM_W macro in recomp.h: the 32-bit N64 address is
// sign-extended to 64 bits, then 0xFFFFFFFF80000000 is subtracted.
uint32_t* host(uint32_t n64_addr) {
    uint64_t reg = static_cast<uint64_t>(static_cast<int64_t>(static_cast<int32_t>(n64_addr)));
    return reinterpret_cast<uint32_t*>(block + (reg - 0xFFFFFFFF80000000ULL));
}

// clang-cl only catches an access violation in __try when it comes from a
// function call, so the reads live in their own functions.
__declspec(noinline) uint32_t read_word(volatile uint32_t* p) {
    return *p;
}

__declspec(noinline) uint64_t sum_words(volatile uint32_t* p, size_t words) {
    uint64_t sum = 0;
    for (size_t i = 0; i < words; i++) {
        sum += p[i];
    }
    return sum;
}

// True if reading the address raises an access violation.
bool faults(uint32_t n64_addr) {
    __try {
        read_word(host(n64_addr));
        return false;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return true;
    }
}

// Like osMapTLB for one 4 KB page: make N64 virtual address vaddr show the
// same memory as physical address phys.
bool map_page(uint32_t vaddr, uint32_t phys) {
    void* spot = host(vaddr);
    // Cut a 4 KB placeholder out of the bigger one. This fails when the spot
    // already is a 4 KB placeholder (left by an earlier unmap), which is fine.
    VirtualFree(spot, kPage, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
    return pMapViewOfFile3(section, nullptr, spot, phys, kPage, MEM_REPLACE_PLACEHOLDER, PAGE_READWRITE, nullptr, 0) == spot;
}

// Like osUnmapTLB for one page: the spot goes back to a no-access placeholder.
bool unmap_page(uint32_t vaddr) {
    return UnmapViewOfFileEx(host(vaddr), MEM_PRESERVE_PLACEHOLDER) != 0;
}

bool map_range(uint32_t vaddr, uint32_t phys, uint32_t pages) {
    bool ok = true;
    for (uint32_t i = 0; i < pages; i++) {
        ok = map_page(vaddr + i * kPage, phys + i * kPage) && ok;
    }
    return ok;
}

bool unmap_range(uint32_t vaddr, uint32_t pages) {
    bool ok = true;
    for (uint32_t i = 0; i < pages; i++) {
        ok = unmap_page(vaddr + i * kPage) && ok;
    }
    return ok;
}

// Write through one address range, read through the other, one word per page
// at a different offset in each page.
bool write_then_read(uint32_t write_base, uint32_t read_base, uint32_t pages, uint32_t seed) {
    for (uint32_t i = 0; i < pages; i++) {
        *host(write_base + i * kPage + i * 4) = seed + i;
    }
    for (uint32_t i = 0; i < pages; i++) {
        if (*host(read_base + i * kPage + i * 4) != seed + i) {
            return false;
        }
    }
    return true;
}

// The reader thread stands in for the renderer: it reads a framebuffer-sized
// piece of the first 512 MB (the runtime's dummy framebuffer address) and the
// physical pages the low mappings point at, again and again.
constexpr uint32_t kFramebuffer = 0x80700000;
constexpr size_t kFramebufferWords = 0x4B000 / 4;
constexpr uint32_t kFighterPhys = 0x801DB000;
constexpr size_t kFighterWords = 10 * kPage / 4;

std::atomic<bool> reader_stop{false};
std::atomic<bool> reader_faulted{false};
std::atomic<bool> reader_saw_change{false};
std::atomic<uint64_t> reader_passes{0};

bool reader_pass(uint64_t* sum) {
    __try {
        *sum = sum_words(host(kFramebuffer), kFramebufferWords) + sum_words(host(kFighterPhys), kFighterWords);
        return true;
    }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

void reader_thread(uint64_t expected) {
    while (!reader_stop.load()) {
        uint64_t sum = 0;
        if (!reader_pass(&sum)) {
            reader_faulted.store(true);
            return;
        }
        if (sum != expected) {
            reader_saw_change.store(true);
        }
        reader_passes.fetch_add(1);
    }
}

} // namespace

int main() {
    // No buffering, so the lines printed before a crash are not lost.
    std::setvbuf(stdout, nullptr, _IONBF, 0);

    HMODULE kernelbase = GetModuleHandleW(L"kernelbase.dll");
    pVirtualAlloc2 = reinterpret_cast<VirtualAlloc2Fn>(reinterpret_cast<void*>(GetProcAddress(kernelbase, "VirtualAlloc2")));
    pMapViewOfFile3 = reinterpret_cast<MapViewOfFile3Fn>(reinterpret_cast<void*>(GetProcAddress(kernelbase, "MapViewOfFile3")));
    check(pVirtualAlloc2 != nullptr && pMapViewOfFile3 != nullptr, "Windows has VirtualAlloc2 and MapViewOfFile3 (10 version 1803 or newer)");
    if (fails != 0) {
        return 1;
    }

    std::printf("\n-- Part 1: allocate the block like our runtime fork --\n");

    // The same calls, in the same order, as recomp.cpp in the fork.
    section = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE,
        static_cast<DWORD>(kRamSize >> 32), static_cast<DWORD>(kRamSize), nullptr);
    block = static_cast<uint8_t*>(pVirtualAlloc2(nullptr, nullptr, kBlockSize,
        MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS, nullptr, 0));
    check(section != nullptr && block != nullptr, "Create a 512 MB section and reserve 4 GB as one placeholder");
    if (fails != 0) {
        return 1;
    }
    std::printf("      block at %p\n", static_cast<void*>(block));
    bool split = VirtualFree(block, kRamSize, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER) != 0;
    void* ram = split ? pMapViewOfFile3(section, nullptr, block, 0, kRamSize, MEM_REPLACE_PLACEHOLDER, PAGE_READWRITE, nullptr, 0) : nullptr;
    check(ram == block, "Split the placeholder and map the section over the first 512 MB");
    if (fails != 0) {
        return 1;
    }

    check(*host(0x80000000) == 0 && *host(0x80000400) == 0 && *host(0x803A4000) == 0 && *host(0x80700000) == 0 && *host(0x9FFFFFFC) == 0,
        "New memory reads as zero (5 spots)");
    *host(0x80000000) = 0x0F125700;
    *host(0x9FFFFFFC) = 0x01A57000;
    check(*host(0x80000000) == 0x0F125700 && *host(0x9FFFFFFC) == 0x01A57000, "The first and the last word of the 512 MB can be written and read");
    check(faults(0xA0000000) && faults(0x00000000) && faults(0x00090000) && faults(0x7FFFFFFC),
        "Everything above 512 MB raises an access violation");

    std::printf("\n-- Part 2: 4 KB mappings at low addresses (Maya vs Maya, run 10) --\n");

    check(map_page(0x00000000, 0x003A4000), "Map virtual 0x00000000 to physical 0x003A4000 (4 KB, not 64 KB aligned)");
    check(map_range(0x00090000, 0x001DB000, 10), "Map virtual 0x00090000-0x00099FFF to physical 0x001DB000-0x001E4FFF (10 pages)");
    if (fails != 0) {
        return 1;
    }

    check(write_then_read(0x00000000, 0x803A4000, 1, 0x11110000), "Page 0: write through 0x00000000, read through 0x803A4000");
    check(write_then_read(0x803A4000, 0x00000000, 1, 0x22220000), "Page 0: write through 0x803A4000, read through 0x00000000");
    *host(0x00000FFC) = 0x33330000;
    check(*host(0x803A4FFC) == 0x33330000, "Page 0: last word of the page matches too");
    check(write_then_read(0x00090000, 0x801DB000, 10, 0x44440000), "Fighter: write through 0x0009xxxx, read through 0x801DBxxx (all 10 pages)");
    check(write_then_read(0x801DB000, 0x00090000, 10, 0x55550000), "Fighter: write through 0x801DBxxx, read through 0x0009xxxx (all 10 pages)");
    check(faults(0x00001000) && faults(0x0008F000) && faults(0x0009A000),
        "Pages next to the mappings still raise an access violation");

    std::printf("\n-- Part 3: unmap, then remap to different physical pages (a new fight) --\n");

    check(unmap_page(0x00000000) && unmap_range(0x00090000, 10), "Unmap all 11 pages");
    check(faults(0x00000000) && faults(0x00090000) && faults(0x00099FFC), "Unmapped pages raise an access violation again");
    check(*host(0x803A4FFC) == 0x33330000 && *host(0x801DB000) == 0x55550000, "The physical pages kept their data");

    // Same virtual pages, new physical pages: page 0 to another buffer (the
    // stream2 case), the fighter block to player 2's slot.
    check(map_page(0x00000000, 0x00200000) && map_range(0x00090000, 0x001E5000, 10),
        "Remap the same 11 virtual pages to physical 0x00200000 and 0x001E5000-0x001EEFFF");
    if (fails != 0) {
        return 1;
    }
    check(write_then_read(0x00000000, 0x80200000, 1, 0x66660000) && write_then_read(0x80200000, 0x00000000, 1, 0x67670000),
        "Page 0 now shares with 0x80200000, both directions");
    check(write_then_read(0x00090000, 0x801E5000, 10, 0x77770000) && write_then_read(0x801E5000, 0x00090000, 10, 0x78780000),
        "Fighter block now shares with 0x801E5000, both directions");
    check(*host(0x803A4FFC) == 0x33330000 && *host(0x801DB000) == 0x55550000, "The old physical pages were not touched by the new writes");

    // A different fighter: other virtual pages (ID 7 is 0x00080000), old slot.
    check(unmap_range(0x00090000, 10) && map_range(0x00080000, 0x001DB000, 10) && faults(0x00090000) &&
          write_then_read(0x00080000, 0x801DB000, 10, 0x88880000),
        "Different fighter: unmap 0x0009xxxx, map 0x0008xxxx to physical 0x001DB000");

    std::printf("\n-- Part 4: 1000 full remaps while a second thread reads the block --\n");

    // Give the reader something to add up, then start it and wait until it runs.
    for (size_t i = 0; i < kFramebufferWords; i++) {
        host(kFramebuffer)[i] = static_cast<uint32_t>(i * 2654435761u);
    }
    uint64_t expected = 0;
    reader_pass(&expected);
    std::thread reader{reader_thread, expected};
    while (reader_passes.load() == 0 && !reader_faulted.load()) {
        Sleep(0);
    }
    uint64_t reads_before = reader_passes.load();

    constexpr int kRounds = 1000;
    LARGE_INTEGER frequency, start, end;
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&start);
    bool loop_ok = true;
    for (int round = 0; round < kRounds; round++) {
        uint32_t fighter = (round & 1) ? 0x00080000 : 0x00090000;
        uint32_t other = (round & 1) ? 0x00090000 : 0x00080000;
        loop_ok = unmap_page(0x00000000) && unmap_range(other, 10) && loop_ok;
        loop_ok = map_page(0x00000000, 0x003A4000) && map_range(fighter, 0x001DB000, 10) && loop_ok;
    }
    QueryPerformanceCounter(&end);
    uint64_t reads_during = reader_passes.load() - reads_before;
    reader_stop.store(true);
    reader.join();
    double micros = static_cast<double>(end.QuadPart - start.QuadPart) * 1000000.0 / static_cast<double>(frequency.QuadPart) / kRounds;

    check(loop_ok, "1000 full remaps (unmap 11 pages, map 11 pages) all succeeded");
    std::printf("      one full remap takes about %.0f microseconds\n", micros);
    check(reads_during >= 10 && !reader_faulted.load(), "The reader thread kept reading during the remaps and never faulted");
    std::printf("      the reader finished %llu full reads during the remaps\n", static_cast<unsigned long long>(reads_during));
    check(!reader_saw_change.load(), "The reader saw the same data every time");
    check(write_then_read(0x00080000, 0x801DB000, 10, 0x99990000), "The mappings still work after the 1000 remaps");

    std::printf("\n%d passed, %d failed\n", passes, fails);
    return fails == 0 ? 0 : 1;
}
