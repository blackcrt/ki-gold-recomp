// Killer Instinct Gold: Recompiled. Program start.
//
// Our own file. Its order of steps follows the main.cpp of the WWF WrestleMania 2000
// recomp (GPL-3.0, https://github.com/jessetbh/WWFWrestleMania2000Recomp), cut down
// to the minimum the runtime needs: describe the game, register the recompiled code,
// hand the runtime its callbacks (window, sound, input, microcode), then start.
//
// State (Phase 2, task 6c): written to compile and link. It has never been run.
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <memory>
#include <string>
#include <system_error>
#include <vector>

#define SDL_MAIN_HANDLED
#include "SDL.h"
#include "SDL_syswm.h"
#include "nfd.h"

#include "ultramodern/ultra64.h"
#include "ultramodern/ultramodern.hpp"
#include "librecomp/game.hpp"
#include "librecomp/rsp.hpp"
#include "recompui/recompui.h"
#include "recompui/renderer.h"
#include "recompui/config.h"
#include "recompui/program_config.h"
#include "util/file.h"
#include "recompinput/recompinput.h"
#include "recompinput/profiles.h"
#include "recompinput/input_events.h"
#include "recompinput/input_state.h"
#include "recompinput/players.h"

#include "kigold_decls.h"

#ifdef _WIN32
#include <Windows.h>
#include <timeapi.h>
#endif

static const recomp::Version version { 0, 1, 0, "" };

static const char* const program_name = "Killer Instinct Gold: Recompiled";

[[noreturn]] static void exit_error(const char* what, const char* detail) {
    fprintf(stderr, "[kigold] FATAL: %s: %s\n", what, detail);
    ultramodern::error_handling::quick_exit(__FILE__, __LINE__, __FUNCTION__);
}

// ---- Window ----
// RecompFrontend reads these two globals by name, so they cannot be static.
SDL_Window* window = nullptr;
std::vector<recomp::GameEntry> supported_games;

static ultramodern::gfx_callbacks_t::gfx_data_t create_gfx() {
    SDL_SetHint(SDL_HINT_WINDOWS_DPI_AWARENESS, "permonitorv2");
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER | SDL_INIT_JOYSTICK) != 0) {
        exit_error("SDL_Init failed", SDL_GetError());
    }
    return {};
}

static ultramodern::renderer::WindowHandle create_window(ultramodern::gfx_callbacks_t::gfx_data_t) {
    uint32_t flags = SDL_WINDOW_RESIZABLE;
#if defined(RT64_SDL_WINDOW_VULKAN)
    flags |= SDL_WINDOW_VULKAN;
#endif
    window = SDL_CreateWindow(program_name, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 1280, 960, flags);
    if (window == nullptr) {
        exit_error("SDL_CreateWindow failed", SDL_GetError());
    }
    SDL_SysWMinfo wm_info;
    SDL_VERSION(&wm_info.version);
    SDL_GetWindowWMInfo(window, &wm_info);
#if defined(_WIN32)
    return ultramodern::renderer::WindowHandle{ wm_info.info.win.window, GetCurrentThreadId() };
#else
    return ultramodern::renderer::WindowHandle{ window };
#endif
}

static void update_gfx(void*) {
    recompinput::handle_events();
}

// ---- Input ----
static ultramodern::input::connected_device_info_t get_connected_device_info(int controller_num) {
    // Two controller ports, nothing plugged into the controllers. The game has
    // Controller Pak code (see NOTES.md, task 6c) but the runtime cannot emulate a
    // Controller Pak, so none is reported.
    return {
        .connected_device = (controller_num < 2) ? ultramodern::input::Device::Controller
                                                 : ultramodern::input::Device::None,
        .connected_pak = ultramodern::input::Pak::None,
    };
}

// ---- Sound: pass the game's samples straight to SDL (16-bit stereo) ----
static SDL_AudioDeviceID audio_device = 0;
static uint32_t audio_rate = 0;
constexpr uint32_t audio_channels = 2;

static void set_frequency(uint32_t freq) {
    // Reopening the device throws away what is queued, so only do it on a change.
    if (audio_device != 0 && freq == audio_rate) {
        return;
    }
    if (audio_device != 0) {
        SDL_CloseAudioDevice(audio_device);
        audio_device = 0;
    }
    SDL_AudioSpec want{}, have{};
    want.freq = (int)freq;
    want.format = AUDIO_S16SYS;
    want.channels = (Uint8)audio_channels;
    want.samples = 512;
    audio_rate = freq;
    audio_device = SDL_OpenAudioDevice(nullptr, 0, &want, &have, 0);
    if (audio_device == 0) {
        fprintf(stderr, "[kigold] SDL_OpenAudioDevice failed: %s\n", SDL_GetError());
        return;
    }
    SDL_PauseAudioDevice(audio_device, 0);
}

// The most samples one real buffer can have. The game keeps a frame's length as a
// signed 16-bit count of frames and passes that count times 4 as the byte length,
// so the largest honest value is 0x7FFF * 4 bytes = 0xFFFE samples.
constexpr size_t MAX_BUFFER_SAMPLES = 0xFFFE;
// Both checks below log a few lines and then go quiet, so they cannot flood.
constexpr int MAX_AUDIO_LOG_LINES = 5;

static void queue_samples(int16_t* audio_data, size_t sample_count) {
    // Safety net. A longer buffer cannot be real, and reading it would run off the
    // end of the game's RAM (the crash of runs 4 and 5). Skip it: that frame is lost.
    if (sample_count > MAX_BUFFER_SAMPLES) {
        static int lines = 0;
        if (lines < MAX_AUDIO_LOG_LINES) {
            lines++;
            fprintf(stderr, "[kigold][audio] IMPOSSIBLE LENGTH: queue_samples got %zu samples (0x%zX). BUFFER SKIPPED, not played%s\n",
                sample_count, sample_count, lines == MAX_AUDIO_LOG_LINES ? " (no more of these lines)" : "");
        }
        return;
    }
    // The game's samples arrive with left and right swapped (a side effect of how
    // the runtime stores big-endian memory), so swap each pair back.
    static std::vector<int16_t> swapped;
    swapped.resize(sample_count);
    for (size_t i = 0; i + 1 < sample_count; i += 2) {
        swapped[i + 0] = audio_data[i + 1];
        swapped[i + 1] = audio_data[i + 0];
    }
    if (audio_device != 0) {
        SDL_QueueAudio(audio_device, swapped.data(), (Uint32)(sample_count * sizeof(int16_t)));
    }
}

// The most queued sound the game may be told about, in frames.
//
// Why a limit: the game's sound code (func_8002AED8, 0x8002AF24 to 0x8002AF64) works
// out the next frame's length as (frameSize + 0x60 - frames still queued), keeps it
// as a signed 16-bit number and checks it with an unsigned compare. Told about more
// than frameSize + 0x60 frames, the result goes negative, the check misses it, and
// the game hands us a 4 GB buffer one frame later (runs 4 and 5).
//
// Why this number: frameSize + 0x60 is the game's own largest buffer (it stores it
// at 0x8006805C, set up at 0x8002AA5C to 0x8002AB18: one video frame of sound,
// rounded up to 16, plus 0x60). It is the most the game ever gives the sound chip
// in one go, and the largest value its sum can take. At 22050 Hz: 368 + 96 = 464.
// A console never gets past it, because there the chip plays without pause and
// the sound thread runs on every video frame. Our SDL queue has no such limit.
static uint32_t max_reported_frames() {
    uint32_t frame_size = (audio_rate + 59) / 60; // one video frame of sound, rounded up
    frame_size = (frame_size + 15) & ~15u;        // rounded up to 16, as the game does
    return frame_size + 0x60;
}

static size_t get_frames_remaining() {
    if (audio_device == 0) {
        return 0;
    }
    size_t queued = SDL_GetQueuedAudioSize(audio_device) / (audio_channels * sizeof(int16_t));
    size_t limit = max_reported_frames();
    if (queued > limit) {
        static int lines = 0;
        if (lines < MAX_AUDIO_LOG_LINES) {
            lines++;
            fprintf(stderr, "[kigold][audio] %zu frames are queued, telling the game %zu (its limit)%s\n",
                queued, limit, lines == MAX_AUDIO_LOG_LINES ? " (no more of these lines)" : "");
        }
        return limit;
    }
    return queued;
}

// ---- Microcode ----
// Graphics tasks go to the renderer and never reach this. Sound tasks run the
// translated audio microcode. Anything else gets a do-nothing routine and a loud
// log line, because returning nullptr makes the runtime fail the task.
static RspExitReason unknown_ucode(uint8_t*, uint32_t) {
    return RspExitReason::Broke;
}

static RspUcodeFunc* get_rsp_microcode(const OSTask* task) {
    if (task->t.type == M_AUDTASK) {
        kigold::count_audio_task();
        return kigold_audio_ucode;
    }
    fprintf(stderr, "[kigold] UNKNOWN RSP task type=%u ucode=0x%08X (doing nothing)\n",
        (unsigned)task->t.type, (unsigned)task->t.ucode);
    return unknown_ucode;
}

int main(int argc, char** argv) {
    (void)argc;
    (void)argv;

    // The program id names the folder for config and saves (under %LOCALAPPDATA%).
    recompui::programconfig::set_program_name(program_name);
    recompui::programconfig::set_program_id(u8"KIGoldRecompiled");

    // No buffering, so the last line before a crash is not lost.
    setvbuf(stdout, nullptr, _IONBF, 0);
    setvbuf(stderr, nullptr, _IONBF, 0);
    fprintf(stderr, "[kigold] main start\n");
    kigold::install_crash_reporter();
    // Does nothing unless the environment variable KIGOLD_HEARTBEAT is set.
    kigold::start_heartbeat();

#ifdef _WIN32
    // The runtime times video frames with Sleep(). Windows only makes Sleep() precise
    // to 1 ms if the program asks for it (found by WM2K).
    timeBeginPeriod(1);
    SDL_setenv("SDL_AUDIODRIVER", "wasapi", true);
#endif
    SDL_SetMainReady();
    NFD_Init();
    SDL_InitSubSystem(SDL_INIT_AUDIO);

    // Controller database: optional, a missing file is not an error worth stopping for.
    std::u8string controller_db = (recompui::file::get_program_path() / "recompcontrollerdb.txt").u8string();
    if (SDL_GameControllerAddMappingsFromFile(reinterpret_cast<const char*>(controller_db.c_str())) < 0) {
        fprintf(stderr, "[kigold] No controller database loaded: %s\n", SDL_GetError());
    }

    // ---- The game ----
    recomp::GameEntry game{};
    // XXH3 64-bit hash of the original US V1.2 ROM in .z64 byte order (12 MB).
    // The user's original ROM is all the game needs: the recompiled boot code inflates
    // the code streams from it, and src/game/inflate_hooks.cpp tells the runtime when.
    // The decompressed ROM of tools/unpack_rom.py is only an input for N64Recomp.
    game.rom_hash = 0x2952FB28B16AB571ULL;
    game.internal_name = "Killer Instinct Gold";
    game.display_name = "Killer Instinct Gold";
    game.game_id = u8"kigold.us.v12";
    game.mod_game_id = "kigold";
    // 4K EEPROM. Evidence in NOTES.md (task 6c): the game reads and writes exactly
    // 0x200 bytes at EEPROM address 0, which is the whole of a 4K EEPROM.
    game.save_type = recomp::SaveType::Eep4k;
    game.is_enabled = true;
    // Through int32_t so the address sign-extends to 64 bits, as the runtime expects.
    game.entrypoint_address = (gpr)(int32_t)0x80000400;
    game.entrypoint = recomp_entrypoint;
    supported_games.push_back(game);
    recomp::register_game(supported_games[0]);

    // The runtime expects its config folder to exist already.
    std::filesystem::path app_folder = recompui::file::get_app_folder_path();
    std::error_code ec;
    std::filesystem::create_directories(app_folder, ec);
    recomp::register_config_path(app_folder);

    kigold::register_overlays();

    // The menu font. CMake downloads the file at configure time (see docs/ASSETS.md).
    recompui::register_primary_font("InterVariable.ttf", "Inter Variable");

    // One player for now. Two-player setup is a later decision (see NOTES.md).
    recompinput::players::set_single_player_mode(true);

    // The settings tabs. The runtime reads these configs during start-up, so they
    // have to exist even before anyone opens the menu.
    recompui::config::GeneralTabOptions general_options{};
    general_options.has_rumble_strength = false;
    recompui::config::create_general_tab(general_options);
    recompui::config::create_graphics_tab();
    recompui::config::create_controls_tab();
    recompui::config::create_sound_tab();
    recompui::config::finalize();

    // ---- Callbacks ----
    recomp::rsp::callbacks_t rsp_callbacks{ .get_rsp_microcode = get_rsp_microcode };
    ultramodern::renderer::callbacks_t renderer_callbacks{
        .create_render_context = [](uint8_t* rdram, ultramodern::renderer::WindowHandle window_handle, bool developer_mode)
            -> std::unique_ptr<ultramodern::renderer::RendererContext> {
            kigold::note_rdram(rdram);
            return kigold::count_graphics_tasks(recompui::renderer::create_render_context(rdram, window_handle,
                ultramodern::renderer::PresentationMode::Console, developer_mode));
        },
    };
    ultramodern::gfx_callbacks_t gfx_callbacks{
        .create_gfx = create_gfx,
        .create_window = create_window,
        .update_gfx = update_gfx,
    };
    ultramodern::audio_callbacks_t audio_callbacks{
        .queue_samples = queue_samples,
        .get_frames_remaining = get_frames_remaining,
        .set_frequency = set_frequency,
    };
    ultramodern::input::callbacks_t input_callbacks{
        .poll_input = recompinput::poll_inputs,
        .get_input = recompinput::profiles::get_n64_input,
        .set_rumble = recompinput::set_rumble,
        .get_connected_device_info = get_connected_device_info,
    };
    ultramodern::events::callbacks_t events_callbacks{
        .vi_callback = []() {
            kigold::count_video_tick();
            recompinput::update_rumble();
        },
        .gfx_init_callback = nullptr,
    };
    ultramodern::error_handling::callbacks_t error_callbacks{ .message_box = recompui::message_box };
    ultramodern::threads::callbacks_t threads_callbacks{
        // The runtime calls this once for each thread the game creates, on that
        // thread. The heartbeat uses it to learn which threads exist.
        .get_game_thread_name = [](const OSThread* thread) -> std::string {
            kigold::note_game_thread(thread);
            return "game";
        },
    };

    // Opens the launcher menu. "Load ROM" and "Start Game" there start the game.
    fprintf(stderr, "[kigold] calling recomp::start\n");
    recomp::start(version, {}, rsp_callbacks, renderer_callbacks, audio_callbacks,
        input_callbacks, gfx_callbacks, events_callbacks, error_callbacks, threads_callbacks);
    fprintf(stderr, "[kigold] recomp::start returned\n");

    NFD_Quit();
    return 0;
}
