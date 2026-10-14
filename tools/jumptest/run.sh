#!/bin/sh
# Builds and runs the stand-alone test for src/game/computed_jump.cpp.
# Run from Ubuntu: sh tools/jumptest/run.sh
# Needs g++ and the decompressed ROM (python3 tools/unpack_rom.py).
# Output goes to build-jumptest/, never committed.
set -e
cd "$(dirname "$0")/../.."
mkdir -p build-jumptest
# KIGOLD_JUMP_TEST makes computed_jump.cpp report every store to the test.
g++ -std=c++17 -Wall -Wextra -DKIGOLD_JUMP_TEST \
    -I lib/N64ModernRuntime/N64Recomp/include \
    tools/jumptest/jumptest.cpp src/game/computed_jump.cpp \
    -o build-jumptest/jumptest
build-jumptest/jumptest build/kigold.decompressed.z64
