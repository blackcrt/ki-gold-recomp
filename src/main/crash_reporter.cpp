// Crash reporter: prints loud [kigold][CRASH] lines when the program hits a fatal
// CPU exception (access violation and friends), instead of dying silently.
//
// Our own file. It uses a Windows vectored exception handler, which Windows calls
// on the crashing thread before anything else gets to see the exception.
//
// What it prints:
//   - the exception code and the thread it happened on
//   - the code address, and the game function it lies in if there is one (as the
//     function's N64 address; look that up in syms/dump.toml for a name). Other
//     code prints as exe + offset; look that up in build-msvc/KIGoldRecompiled.map
//   - for an access violation: the memory address, read or write, and what that
//     address means to the game (N64 address, and which kind of address it is)
//   - the chain of callers, each one resolved the same way
//
// The handler only reports. It then lets Windows carry on as before, so the
// program still ends with the same exit code (for example 0xC0000005).
#include <atomic>
#include <cstdio>

#include "kigold_decls.h"
#include "librecomp/addresses.hpp"

namespace {
    // Where the runtime put the game's memory. Set by kigold::note_rdram.
    std::atomic<uint8_t*> game_rdram{ nullptr };
}

void kigold::note_rdram(uint8_t* rdram) {
    game_rdram.store(rdram, std::memory_order_relaxed);
}

uint8_t* kigold::known_rdram() {
    return game_rdram.load(std::memory_order_relaxed);
}

// Section numbers of the generated section table (RecompiledFuncs/recomp_overlays.inl).
const char* kigold::section_name(uint32_t section) {
    static const char* const names[] = { "boot", "stream1", "stream2", "stream3" };
    return section < 4 ? names[section] : "?";
}

#if defined(_WIN32) && defined(_M_X64)
#include <Windows.h>

namespace {
    // A handled exception somewhere in a library would also pass through here,
    // so stop after a few reports instead of flooding the log.
    constexpr int MAX_REPORTS = 3;
    constexpr int MAX_FRAMES = 32;
    std::atomic<int> reports{ 0 };
    // Set while a thread is inside the handler, so a fault in the handler itself
    // cannot loop.
    thread_local bool in_handler = false;

    const char* exception_name(DWORD code) {
        switch (code) {
        case EXCEPTION_ACCESS_VIOLATION: return "access violation";
        case EXCEPTION_IN_PAGE_ERROR: return "in-page error";
        case EXCEPTION_STACK_OVERFLOW: return "stack overflow";
        case EXCEPTION_ILLEGAL_INSTRUCTION: return "illegal instruction";
        case EXCEPTION_PRIV_INSTRUCTION: return "privileged instruction";
        case EXCEPTION_INT_DIVIDE_BY_ZERO: return "integer divide by zero";
        case EXCEPTION_ARRAY_BOUNDS_EXCEEDED: return "array bounds exceeded";
        case EXCEPTION_DATATYPE_MISALIGNMENT: return "datatype misalignment";
        default: return nullptr;
        }
    }

    // find_generated_function only knows where each function starts, so it returns
    // the nearest start below the address, even when the address is in some other
    // code that happens to sit after it in the exe (run 4: the runtime's
    // run_thread_function was reported as a game function 0x556B3 bytes away).
    // Windows knows the real start and end of the function an address is in (its
    // unwind table). The match only counts if the game function starts inside it.
    bool really_inside(uintptr_t lookup_address, const kigold::GeneratedFunc& func) {
        uintptr_t func_start = lookup_address - func.host_offset;
        DWORD64 image_base = 0;
        PRUNTIME_FUNCTION entry = RtlLookupFunctionEntry(lookup_address, &image_base, nullptr);
        if (entry == nullptr) {
            // A tiny function without a stack frame has no entry. Accept only if close.
            return func.host_offset < 0x100;
        }
        return func_start >= image_base + entry->BeginAddress;
    }

    // Prints one code address: the game function it lies in, or else the exe or
    // DLL it belongs to. "Game function" means an entry of the generated section
    // table. For a libultra function that the runtime replaces, that entry points
    // at the runtime's own version, so the address is right but the code is not
    // generated code.
    void print_code_address(const char* label, uintptr_t address, uintptr_t lookup_address) {
        kigold::GeneratedFunc func{};
        if (kigold::find_game_function(lookup_address, func)) {
            fprintf(stderr, "[kigold][CRASH] %s 0x%016llX: game function at N64 0x%08X (%s), 0x%X bytes into its PC code%s\n",
                label, (unsigned long long)address, func.vram, kigold::section_name(func.section), func.host_offset,
                func.shared ? " (several game functions share this PC code, the N64 address may be another one)" : "");
            return;
        }
        HMODULE module = nullptr;
        char path[MAX_PATH] = "";
        if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                (LPCSTR)lookup_address, &module) && module != nullptr
            && GetModuleFileNameA(module, path, sizeof(path)) != 0) {
            const char* file = path;
            for (const char* p = path; *p != '\0'; p++) {
                if (*p == '\\' || *p == '/') {
                    file = p + 1;
                }
            }
            fprintf(stderr, "[kigold][CRASH] %s 0x%016llX: not a game function, %s + 0x%llX\n",
                label, (unsigned long long)address, file, (unsigned long long)(address - (uintptr_t)module));
        }
        else {
            fprintf(stderr, "[kigold][CRASH] %s 0x%016llX: not in any loaded exe or DLL\n",
                label, (unsigned long long)address);
        }
    }

    // Prints what a memory address means to the game.
    void print_memory_address(uintptr_t address) {
        uintptr_t rdram = (uintptr_t)game_rdram.load(std::memory_order_relaxed);
        if (rdram == 0) {
            fprintf(stderr, "[kigold][CRASH] game memory location not known yet, cannot say if this is a game address\n");
            return;
        }
        if (address < rdram || address - rdram >= recomp::allocation_size) {
            fprintf(stderr, "[kigold][CRASH] that is NOT inside game memory (game memory starts at 0x%016llX): a PC-side pointer%s\n",
                (unsigned long long)rdram, address < 0x10000 ? ", and a null pointer" : "");
            return;
        }
        // The generated code reads N64 address A at rdram + (A - 0x80000000).
        uint64_t offset = address - rdram;
        uint32_t n64 = (uint32_t)(offset + 0x80000000ULL);
        // The game's own RAM is 8 MB (what the runtime reports as osMemSize).
        constexpr uint32_t CONSOLE_RAM = 8 * 1024 * 1024;
        const char* kind;
        if (offset < recomp::mem_size) {
            kind = "inside the game's RAM, which is readable and writable (unexpected for an access violation)";
        }
        else if (n64 < 0x00001000) {
            kind = "a null pointer in the game (or a small offset from one)";
        }
        else if (n64 >= 0x00010000 && n64 < 0x000BA000) {
            kind = "a TLB address in the per-fighter range 0x00010000 to 0x000BA000, which our osMapTLB stand-in does not map";
        }
        else if (n64 < 0x80000000) {
            kind = "below 0x80000000: a TLB-mapped address or a bad pointer";
        }
        else if (n64 >= 0xA0000000 && n64 < 0xA0000000 + CONSOLE_RAM) {
            kind = "0xA0000000 to 0xA07FFFFF: on a console this is uncached RAM (KSEG1), the same memory as 0x80000000. The runtime does not mirror it";
        }
        else if (n64 >= 0xA0000000 && n64 < 0xC0000000) {
            kind = "0xA0800000 to 0xBFFFFFFF: direct hardware or cartridge access, which the runtime does not emulate";
        }
        else {
            kind = "past the end of the RAM the runtime provides (512 MB from 0x80000000): a bad pointer";
        }
        fprintf(stderr, "[kigold][CRASH] N64 address 0x%08X (the last 2 bits can differ, the runtime stores bytes swapped)\n", n64);
        fprintf(stderr, "[kigold][CRASH] that is %s\n", kind);
        // The runtime's readable memory ends exactly at offset 512 MB, which is
        // N64 address 0xA0000000. Code that walks forward through RAM and does
        // not stop faults on the first page after it.
        if (offset >= recomp::mem_size && offset < recomp::mem_size + 0x1000) {
            fprintf(stderr, "[kigold][CRASH] NOTE: this is the very first page after the runtime's 512 MB of RAM. Check for a loop that ran off the end of RAM (a huge length) before believing the address\n");
        }
    }

    void print_callers(const CONTEXT* crash_context) {
        CONTEXT context = *crash_context;
        for (int frame = 0; frame < MAX_FRAMES; frame++) {
            DWORD64 image_base = 0;
            PRUNTIME_FUNCTION function = RtlLookupFunctionEntry(context.Rip, &image_base, nullptr);
            if (function == nullptr) {
                // No unwind data: a function without a stack frame. Its return
                // address is on top of the stack.
                if (context.Rsp == 0 || IsBadReadPtr((const void*)context.Rsp, sizeof(DWORD64))) {
                    break;
                }
                context.Rip = *(const DWORD64*)context.Rsp;
                context.Rsp += sizeof(DWORD64);
            }
            else {
                void* handler_data = nullptr;
                DWORD64 establisher_frame = 0;
                RtlVirtualUnwind(UNW_FLAG_NHANDLER, image_base, context.Rip, function, &context,
                    &handler_data, &establisher_frame, nullptr);
            }
            if (context.Rip == 0) {
                break;
            }
            char label[32];
            snprintf(label, sizeof(label), "called from #%d", frame + 1);
            // A return address points just past the call, which can already be the
            // next function. Look up one byte earlier.
            print_code_address(label, (uintptr_t)context.Rip, (uintptr_t)context.Rip - 1);
        }
    }

    LONG CALLBACK crash_handler(EXCEPTION_POINTERS* info) {
        const EXCEPTION_RECORD* record = info->ExceptionRecord;
        const char* name = exception_name(record->ExceptionCode);
        // Not a fatal CPU exception (for example a C++ exception): not ours.
        if (name == nullptr || in_handler) {
            return EXCEPTION_CONTINUE_SEARCH;
        }
        if (reports.fetch_add(1) >= MAX_REPORTS) {
            return EXCEPTION_CONTINUE_SEARCH;
        }
        in_handler = true;

        fprintf(stderr, "\n[kigold][CRASH] ==================== CRASH ====================\n");
        fprintf(stderr, "[kigold][CRASH] exception 0x%08lX (%s)\n", (unsigned long)record->ExceptionCode, name);

        PWSTR thread_name = nullptr;
        if (SUCCEEDED(GetThreadDescription(GetCurrentThread(), &thread_name)) && thread_name != nullptr) {
            fprintf(stderr, "[kigold][CRASH] thread %lu \"%ls\"\n", (unsigned long)GetCurrentThreadId(), thread_name);
            LocalFree(thread_name);
        }
        else {
            fprintf(stderr, "[kigold][CRASH] thread %lu\n", (unsigned long)GetCurrentThreadId());
        }

        uintptr_t code_address = (uintptr_t)record->ExceptionAddress;
        print_code_address("code address", code_address, code_address);

        if ((record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION || record->ExceptionCode == EXCEPTION_IN_PAGE_ERROR)
            && record->NumberParameters >= 2) {
            const char* access = "READ";
            if (record->ExceptionInformation[0] == 1) {
                access = "WRITE";
            }
            else if (record->ExceptionInformation[0] == 8) {
                access = "EXECUTE (a jump to this address)";
            }
            uintptr_t memory_address = (uintptr_t)record->ExceptionInformation[1];
            fprintf(stderr, "[kigold][CRASH] tried to %s memory address 0x%016llX\n", access, (unsigned long long)memory_address);
            print_memory_address(memory_address);
        }

        // On a stack overflow there is almost no stack left to walk with.
        if (record->ExceptionCode != EXCEPTION_STACK_OVERFLOW) {
            print_callers(info->ContextRecord);
        }

        fprintf(stderr, "[kigold][CRASH] names: N64 address in syms/dump.toml (a libultra name means the runtime's own version ran); exe + offset in build-msvc/KIGoldRecompiled.map\n");
        fprintf(stderr, "[kigold][CRASH] ==================== END ====================\n");
        fflush(stderr);
        fflush(stdout);

        in_handler = false;
        // Report only. Windows now does what it would have done without us.
        return EXCEPTION_CONTINUE_SEARCH;
    }
}

bool kigold::find_game_function(uintptr_t host_address, GeneratedFunc& out) {
    return find_generated_function(host_address, out) && really_inside(host_address, out);
}

void kigold::install_crash_reporter() {
    if (AddVectoredExceptionHandler(1, crash_handler) == nullptr) {
        fprintf(stderr, "[kigold] WARNING: could not install the crash reporter\n");
    }
    else {
        fprintf(stderr, "[kigold] crash reporter installed\n");
    }
}

#else

bool kigold::find_game_function(uintptr_t host_address, GeneratedFunc& out) {
    return find_generated_function(host_address, out);
}

void kigold::install_crash_reporter() {
    // Windows x64 only for now. Other platforms get no crash report.
}

#endif
