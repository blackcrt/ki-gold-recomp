// Heartbeat: every 2 seconds, prints [kigold][beat] lines that say what each game
// thread is doing and how much work has gone through. For a run that hangs
// without crashing. Off by default: set the environment variable
// KIGOLD_HEARTBEAT to 1 before starting the exe.
//
// Our own file. Nothing in lib/ is changed and no hook in kigold.toml is needed.
//
// How it finds the threads. The runtime keeps no list of game threads. But it
// calls our thread name callback once for every thread the game creates, on
// that new thread, and passes the game's own thread record (OSThread, which
// lives in game memory). kigold::note_game_thread keeps that record's address
// and a handle to the PC thread. The very first thread (the one that runs the
// boot code before the game creates any thread) has no record and is not listed.
//
// How it finds the state. The runtime only ever writes STOPPED or QUEUED into a
// thread record's state field, never RUNNING or BLOCKED, so that field is no
// use. What the runtime does keep right is the record's "queue" field: the list
// the thread is parked in.
//   - the runtime's own ready list: READY (can run, waits for its turn)
//   - a list inside a message queue: WAITING to receive or to send on that queue
//   - no list: RUNNING. The runtime lets one game thread run at a time. A thread
//     that stopped itself also has no list, the stack part of the line tells
//   - no PC thread behind the record any more: ENDED
//
// How it finds the caller. The runtime does not record who called osRecvMesg.
// So the heartbeat stops the PC thread for a moment, walks its stack, and lets
// it go again. The first game function on that stack is the caller. This is the
// same walk the crash reporter does, only on another thread.
//
// All of this reads game memory while the game runs, without any lock. A line
// can be out of date by the time it prints. It is a diagnosis tool, not a proof.
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <thread>
#include <utility>
#include <vector>

#include "kigold_decls.h"

#if defined(_WIN32) && defined(_M_X64)
#include <Windows.h>
#define KIGOLD_CAN_WALK_STACKS 1
#endif

// The runtime's wrappers that generated code calls for these libultra names.
extern "C" {
    void osRecvMesg_recomp(uint8_t* rdram, recomp_context* ctx);
    void osSendMesg_recomp(uint8_t* rdram, recomp_context* ctx);
    void osJamMesg_recomp(uint8_t* rdram, recomp_context* ctx);
    void osStartThread_recomp(uint8_t* rdram, recomp_context* ctx);
    void osStopThread_recomp(uint8_t* rdram, recomp_context* ctx);
    void osSetThreadPri_recomp(uint8_t* rdram, recomp_context* ctx);
}

namespace {
    constexpr std::chrono::seconds BEAT_INTERVAL{ 2 };
    // The console's RAM: 8 MB from 0x80000000. Game records lie inside it.
    constexpr uint32_t CONSOLE_RAM_START = 0x80000000;
    constexpr uint32_t CONSOLE_RAM_SIZE = 8 * 1024 * 1024;

    struct KnownThread {
        const OSThread* record; // the game's thread record, inside game memory
        void* handle;           // our own handle to the PC thread behind it
    };

    // Never freed on purpose: the heartbeat thread may still be printing while
    // the program shuts down.
    struct State {
        std::atomic<bool> on{ false };
        std::atomic<uint64_t> video_ticks{ 0 };
        std::atomic<uint64_t> graphics_tasks{ 0 };
        std::atomic<uint64_t> audio_tasks{ 0 };
        std::atomic<uint64_t> inflates{ 0 };
        std::atomic<uint64_t> dp_blocks{ 0 };
        std::atomic<bool> told_first_graphics_task{ false };
        std::mutex threads_mutex;
        std::vector<KnownThread> threads;
    };
    State& state() {
        static State* const instance = new State;
        return *instance;
    }

    bool in_console_ram(int32_t address) {
        uint32_t a = (uint32_t)address;
        return a >= CONSOLE_RAM_START && a - CONSOLE_RAM_START < CONSOLE_RAM_SIZE && (a & 3) == 0;
    }

    // Passes every call through to the real renderer and counts the graphics
    // tasks. Says so once, loudly, when the first one arrives.
    class CountingRenderer final : public ultramodern::renderer::RendererContext {
    public:
        explicit CountingRenderer(std::unique_ptr<ultramodern::renderer::RendererContext> renderer)
            : inner(std::move(renderer)) {}

        bool valid() override { return inner->valid(); }
        ultramodern::renderer::SetupResult get_setup_result() const override { return inner->get_setup_result(); }
        ultramodern::renderer::GraphicsApi get_chosen_api() const override { return inner->get_chosen_api(); }
        bool update_config(const ultramodern::renderer::GraphicsConfig& old_config,
                const ultramodern::renderer::GraphicsConfig& new_config) override {
            return inner->update_config(old_config, new_config);
        }
        void enable_instant_present() override { inner->enable_instant_present(); }
        void send_dl(const OSTask* task) override {
            State& s = state();
            s.graphics_tasks.fetch_add(1, std::memory_order_relaxed);
            // Printed before the renderer gets the task, so the line is there
            // even if the renderer then fails on it.
            if (!s.told_first_graphics_task.exchange(true)) {
                fprintf(stderr,
                    "[kigold][gfx] FIRST GRAPHICS TASK reached the renderer: display list at 0x%08X (%u bytes), microcode at 0x%08X, DP blocks before it: %llu\n",
                    (uint32_t)task->t.data_ptr, (uint32_t)task->t.data_size, (uint32_t)task->t.ucode,
                    (unsigned long long)s.dp_blocks.load(std::memory_order_relaxed));
            }
            inner->send_dl(task);
        }
        void send_dummy_workload(uint32_t fb_address) override { inner->send_dummy_workload(fb_address); }
        void update_screen() override { inner->update_screen(); }
        void shutdown() override { inner->shutdown(); }
        uint32_t get_display_framerate() const override { return inner->get_display_framerate(); }
        float get_resolution_scale() const override { return inner->get_resolution_scale(); }

    private:
        std::unique_ptr<ultramodern::renderer::RendererContext> inner;
    };

    // Says what the thread waits on, from the list its record is parked in.
    // That list is the first word of a message queue (threads waiting to
    // receive) or the second word (threads waiting to send). The two cases are
    // told apart by which reading gives a sane queue: a small slot count and a
    // message buffer inside RAM.
    void describe_wait(uint8_t* rdram, int32_t list, char* out, size_t out_size) {
        constexpr int32_t MAX_SLOTS = 0x10000;
        if (in_console_ram(list) && in_console_ram(list + 0x14)) {
            const OSMesgQueue* queue = TO_PTR(OSMesgQueue, list);
            if (queue->msgCount > 0 && queue->msgCount <= MAX_SLOTS && in_console_ram(queue->msg)) {
                snprintf(out, out_size, "WAITING to receive on queue 0x%08X (%d of %d messages in it)",
                    (uint32_t)list, (int)queue->validCount, (int)queue->msgCount);
                return;
            }
        }
        if (in_console_ram(list - 4) && in_console_ram(list + 0x10)) {
            const OSMesgQueue* queue = TO_PTR(OSMesgQueue, list - 4);
            if (queue->msgCount > 0 && queue->msgCount <= MAX_SLOTS && in_console_ram(queue->msg)) {
                snprintf(out, out_size, "WAITING to send to queue 0x%08X, which is full (%d of %d messages in it)",
                    (uint32_t)(list - 4), (int)queue->validCount, (int)queue->msgCount);
                return;
            }
        }
        snprintf(out, out_size, "WAITING in a thread list at 0x%08X that does not look like a message queue", (uint32_t)list);
    }

#ifdef KIGOLD_CAN_WALK_STACKS
    constexpr int MAX_FRAMES = 48;
    // How many entries of the stack go into a line.
    constexpr int MAX_CHAIN = 4;

    // Stops the thread, collects the code addresses on its stack, lets it go.
    // While the thread is stopped this must not print or allocate memory: the
    // stopped thread may be holding the lock for either, and we would wait on
    // it forever. Only the plain unwind calls below are used in between.
    int capture_stack(HANDLE thread, uintptr_t* frames) {
        if (SuspendThread(thread) == (DWORD)-1) {
            return 0;
        }
        int count = 0;
        CONTEXT context{};
        context.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
        if (GetThreadContext(thread, &context)) {
            frames[count++] = (uintptr_t)context.Rip;
            while (count < MAX_FRAMES) {
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
                frames[count++] = (uintptr_t)context.Rip;
            }
        }
        ResumeThread(thread);
        return count;
    }

    // Runtime functions worth a name in the line: the ones a game thread waits in.
    struct RuntimeName {
        uintptr_t start;
        const char* name;
    };
    const char* runtime_name(uintptr_t lookup_address) {
        static const RuntimeName names[] = {
            { reinterpret_cast<uintptr_t>(&osRecvMesg), "osRecvMesg" },
            { reinterpret_cast<uintptr_t>(&osRecvMesg_recomp), "osRecvMesg" },
            { reinterpret_cast<uintptr_t>(&osSendMesg), "osSendMesg" },
            { reinterpret_cast<uintptr_t>(&osSendMesg_recomp), "osSendMesg" },
            { reinterpret_cast<uintptr_t>(&osJamMesg), "osJamMesg" },
            { reinterpret_cast<uintptr_t>(&osJamMesg_recomp), "osJamMesg" },
            { reinterpret_cast<uintptr_t>(&osStartThread), "osStartThread" },
            { reinterpret_cast<uintptr_t>(&osStartThread_recomp), "osStartThread" },
            { reinterpret_cast<uintptr_t>(&osStopThread), "osStopThread" },
            { reinterpret_cast<uintptr_t>(&osStopThread_recomp), "osStopThread" },
            { reinterpret_cast<uintptr_t>(&osSetThreadPri), "osSetThreadPri" },
            { reinterpret_cast<uintptr_t>(&osSetThreadPri_recomp), "osSetThreadPri" },
            { reinterpret_cast<uintptr_t>(&pause_self), "pause_self (the runtime's idle wait)" },
        };
        // Windows knows where the function an address lies in starts.
        DWORD64 image_base = 0;
        PRUNTIME_FUNCTION function = RtlLookupFunctionEntry(lookup_address, &image_base, nullptr);
        if (function == nullptr) {
            return nullptr;
        }
        uintptr_t start = (uintptr_t)(image_base + function->BeginAddress);
        for (const RuntimeName& entry : names) {
            if (entry.start == start) {
                return entry.name;
            }
        }
        return nullptr;
    }

    // Writes the innermost named entries of a stack: "A < B < C" means A was
    // called from B, and B from C. Runtime functions print by name, game
    // functions by N64 address and section. Everything else (Windows, the rest
    // of the runtime) is skipped.
    void describe_stack(const uintptr_t* frames, int count, char* out, size_t out_size) {
        out[0] = '\0';
        size_t used = 0;
        int entries = 0;
        const char* last_name = nullptr;
        uint32_t last_vram = 0;
        for (int i = 0; i < count && entries < MAX_CHAIN && used + 1 < out_size; i++) {
            // A return address points just past the call, which can already be
            // the next function. Look up one byte earlier.
            uintptr_t lookup = frames[i] - (i > 0 ? 1 : 0);
            char text[64];
            const char* name = runtime_name(lookup);
            kigold::GeneratedFunc func{};
            if (name != nullptr) {
                // The wrapper and the function it wraps have the same name.
                if (name == last_name) {
                    continue;
                }
                last_name = name;
                snprintf(text, sizeof(text), "%s", name);
            }
            else if (kigold::find_game_function(lookup, func)) {
                if (last_name == nullptr && entries > 0 && func.vram == last_vram) {
                    continue;
                }
                last_name = nullptr;
                last_vram = func.vram;
                snprintf(text, sizeof(text), "0x%08X%s %s", func.vram, func.shared ? "?" : "",
                    kigold::section_name(func.section));
            }
            else {
                continue;
            }
            int written = snprintf(out + used, out_size - used, "%s%s", entries > 0 ? " < " : "", text);
            if (written < 0) {
                break;
            }
            used += (size_t)written;
            entries++;
        }
        if (entries == 0) {
            snprintf(out, out_size, "no game function on its stack");
        }
    }
#endif

    void print_thread(uint8_t* rdram, const KnownThread& known) {
        const OSThread* record = known.record;
        uintptr_t offset = (uintptr_t)((const uint8_t*)record - rdram);
        if (offset >= CONSOLE_RAM_SIZE) {
            fprintf(stderr, "[kigold][beat]   a thread record outside the game's RAM, skipped\n");
            return;
        }
        uint32_t address = CONSOLE_RAM_START + (uint32_t)offset;

        char what[160];
        bool alive = true;
        if (record->context == nullptr) {
            snprintf(what, sizeof(what), "ENDED");
            alive = false;
        }
        else if (record->queue == ultramodern::running_queue) {
            snprintf(what, sizeof(what), "READY (can run, waits for its turn)");
        }
        else if (record->queue == NULLPTR) {
            snprintf(what, sizeof(what), "%s", record->state == OSThreadState::STOPPED
                ? "NOT STARTED" : "RUNNING (or stopped itself, see stack)");
        }
        else {
            describe_wait(rdram, record->queue, what, sizeof(what));
        }

        char stack[256] = "";
#ifdef KIGOLD_CAN_WALK_STACKS
        if (alive && known.handle != nullptr) {
            uintptr_t frames[MAX_FRAMES];
            int count = capture_stack((HANDLE)known.handle, frames);
            if (count > 0) {
                describe_stack(frames, count, stack, sizeof(stack));
            }
        }
#else
        (void)alive;
#endif
        fprintf(stderr, "[kigold][beat]   thread %d (0x%X) pri %d, record 0x%08X: %s%s%s\n",
            (int)record->id, (unsigned)record->id, (int)record->priority, address, what,
            stack[0] != '\0' ? ". Stack: " : "", stack);
    }

    void beat_loop() {
        State& s = state();
        auto start = std::chrono::steady_clock::now();
        bool told_waiting = false;
        for (;;) {
            std::this_thread::sleep_for(BEAT_INTERVAL);
            long long seconds = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::steady_clock::now() - start).count();
            uint8_t* rdram = kigold::known_rdram();
            if (rdram == nullptr || !ultramodern::is_game_started()) {
                if (!told_waiting) {
                    told_waiting = true;
                    fprintf(stderr, "[kigold][beat] the game has not started yet, no beats until it does\n");
                }
                continue;
            }

            // Copy the list so the lock is not held while threads are stopped.
            std::vector<KnownThread> threads;
            {
                std::lock_guard lock{ s.threads_mutex };
                threads = s.threads;
            }
            fprintf(stderr,
                "[kigold][beat] ---- %lld s: video ticks %llu, DP blocks %llu, graphics tasks %llu, audio tasks %llu, inflates %llu, game threads %zu ----\n",
                seconds,
                (unsigned long long)s.video_ticks.load(std::memory_order_relaxed),
                (unsigned long long)s.dp_blocks.load(std::memory_order_relaxed),
                (unsigned long long)s.graphics_tasks.load(std::memory_order_relaxed),
                (unsigned long long)s.audio_tasks.load(std::memory_order_relaxed),
                (unsigned long long)s.inflates.load(std::memory_order_relaxed),
                threads.size());
            for (const KnownThread& known : threads) {
                print_thread(rdram, known);
            }
        }
    }
}

void kigold::count_video_tick() {
    // Called on every video frame of the runtime. It only sends the game a video
    // interrupt message once the game runs, so only those frames are counted.
    if (ultramodern::is_game_started()) {
        state().video_ticks.fetch_add(1, std::memory_order_relaxed);
    }
}

void kigold::count_audio_task() {
    state().audio_tasks.fetch_add(1, std::memory_order_relaxed);
}

void kigold::count_inflate() {
    state().inflates.fetch_add(1, std::memory_order_relaxed);
}

void kigold::count_dp_block() {
    state().dp_blocks.fetch_add(1, std::memory_order_relaxed);
}

void kigold::note_game_thread(const OSThread* thread) {
    State& s = state();
    if (!s.on.load(std::memory_order_relaxed)) {
        return;
    }
    void* handle = nullptr;
#ifdef KIGOLD_CAN_WALK_STACKS
    // A handle of our own, so it stays good even after the thread has ended.
    HANDLE duplicate = nullptr;
    if (DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &duplicate,
            THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT | THREAD_QUERY_INFORMATION, FALSE, 0)) {
        handle = duplicate;
    }
#endif
    std::lock_guard lock{ s.threads_mutex };
    // The game can create a new thread in a record it used before.
    for (KnownThread& known : s.threads) {
        if (known.record == thread) {
#ifdef KIGOLD_CAN_WALK_STACKS
            if (known.handle != nullptr) {
                CloseHandle((HANDLE)known.handle);
            }
#endif
            known.handle = handle;
            return;
        }
    }
    s.threads.push_back({ thread, handle });
}

std::unique_ptr<ultramodern::renderer::RendererContext> kigold::count_graphics_tasks(
        std::unique_ptr<ultramodern::renderer::RendererContext> renderer) {
    if (renderer == nullptr) {
        return renderer;
    }
    return std::make_unique<CountingRenderer>(std::move(renderer));
}

void kigold::start_heartbeat() {
    const char* setting = std::getenv("KIGOLD_HEARTBEAT");
    if (setting == nullptr || setting[0] == '\0' || (setting[0] == '0' && setting[1] == '\0')) {
        return;
    }
    state().on.store(true);
    fprintf(stderr, "[kigold][beat] heartbeat on, one beat every %lld seconds\n", (long long)BEAT_INTERVAL.count());
    fprintf(stderr, "[kigold][beat] counters: video ticks = video frames of the runtime since the game started, each one sends the game a video interrupt message; DP blocks = blocks of raw drawing commands the game passed to osDpSetNextBuffer (not drawn yet); graphics tasks = display lists handed to the renderer; audio tasks = sound tasks run; inflates = calls of the game's inflate helper\n");
    fprintf(stderr, "[kigold][beat] stack: A < B means A was called from B. An address is a game function (N64 address, look it up in syms/dump.toml; a libultra name there means the runtime's own version ran). A ? means several game functions share that PC code\n");
#ifndef KIGOLD_CAN_WALK_STACKS
    fprintf(stderr, "[kigold][beat] stacks are Windows x64 only, lines will have no stack part\n");
#endif
    std::thread{ beat_loop }.detach();
}
