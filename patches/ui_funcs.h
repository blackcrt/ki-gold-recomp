// RecompFrontend expects the game project to have this file: its
// recompui/src/api/ui_api_events.cpp includes "patches/ui_funcs.h" from the root of
// the project that builds it. It needs the UI event types from it.
//
// We have no patches yet (Phase 4), so this only passes on the copy of those types
// that RecompFrontend ships in its own public header.
#ifndef KIGOLD_UI_FUNCS_H
#define KIGOLD_UI_FUNCS_H

#include "recompui/event_structs.h"

#endif
