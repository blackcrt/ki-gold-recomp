// Ends the process cleanly when exit() is called on a thread that is not the
// main thread.
//
// N64ModernRuntime calls exit() on the game thread for errors it cannot continue
// from: "Failed to find function at 0x..." (librecomp/src/overlays.cpp) and
// "Unhandled status register bits changed" (librecomp/src/recomp.cpp). exit()
// then runs the whole program cleanup on that thread, while the main thread
// still runs the window and the menu. In runs 9 and 12 that cleanup crashed
// inside RmlUi (a null read while its global list of contexts was destroyed),
// and the crash report buried the one line that mattered.
//
// How. exit() calls the functions registered with atexit, newest first, before
// it destroys older global objects. install_exit_guard registers one at the
// start of main, after all global objects (RmlUi's among them) were built, so it
// runs before their cleanup. If it finds itself on another thread than the main
// thread, it prints a line, flushes the output, and ends the process at once
// with _Exit. On the main thread (a normal end) it does nothing.
//
// Limits: the exit code is always EXIT_FAILURE in that case, which is what the
// runtime passes in both places. Cleanup registered later than this guard still
// runs before it.
#include <cstdio>
#include <cstdlib>
#include <thread>

#include "kigold_decls.h"

namespace {
    std::thread::id main_thread;

    void on_exit() {
        if (std::this_thread::get_id() == main_thread) {
            return;
        }
        fprintf(stderr,
            "[kigold][exit] exit() was called on a thread that is not the main thread. The runtime does that for an error it cannot continue from, see the line above this one. Ending the process now with exit code %d, without the program cleanup (it is not safe from this thread)\n",
            EXIT_FAILURE);
        fflush(nullptr);
        std::_Exit(EXIT_FAILURE);
    }
}

void kigold::install_exit_guard() {
    main_thread = std::this_thread::get_id();
    std::atexit(on_exit);
}
