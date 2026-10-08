# KI Gold decomp Makefile
#
# Run `make` with no arguments to see what each command does.
# Phase 2 adds the real build rules (compile, link, compare SHA1).

PYTHON_SYS := python3
VENV       := .venv
PY         := $(VENV)/bin/python3
PIP        := $(VENV)/bin/pip

ROM        := baserom.us.z64
CONFIG     := $(firstword $(wildcard *.yaml))

IDO_VERSION := v1.2
IDO_DIR     := tools/ido
IDO_URL     := https://github.com/decompals/ido-static-recomp/releases/download/$(IDO_VERSION)/ido-5.3-recomp-linux.tar.gz

# Compiler flags carried over from the GoldenEye decomp (see docs/GOLDENEYE.md).
# First guesses for KI Gold, to confirm in Phase 1.
CC        := $(IDO_DIR)/cc
CFLAGS    := -Wab,-r4300_mul -non_shared -Olimit 2000 -G 0 -Xcpluscomm -mips2 -32
OPT_GAME  := -O2
OPT_LIBULTRA := -O1

.DEFAULT_GOAL := help
.PHONY: help setup check scan config split progress guard build clean distclean

help:
	@echo "KI Gold decomp commands:"
	@echo "  make setup      Install Python tools (.venv) and the IDO 5.3 compiler (tools/ido)"
	@echo "  make check      Check the ROM: name, region, revision, byte order, SHA1"
	@echo "  make scan       Recon scan: microcode strings and Rare 1172 compression"
	@echo "  make config     Generate the first splat config from the ROM (Phase 1, run once)"
	@echo "  make split      Split the ROM into asm/, assets/, and the linker script"
	@echo "  make progress   Show how much code is matched C"
	@echo "  make guard      Run the legal guard over every tracked file"
	@echo "  make build      Build the ROM (arrives in Phase 2)"
	@echo "  make clean      Delete build/"
	@echo "  make distclean  Delete build/, asm/, assets/ (everything splat generated)"

setup: $(VENV)/.done $(IDO_DIR)/cc

$(VENV)/.done: requirements.txt
	$(PYTHON_SYS) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	touch $@

$(IDO_DIR)/cc:
	mkdir -p $(IDO_DIR)
	curl -fsSL $(IDO_URL) | tar xz -C $(IDO_DIR)
	@echo "IDO 5.3 installed in $(IDO_DIR)"

check:
	$(PYTHON_SYS) tools/romcheck.py

scan:
	$(PYTHON_SYS) tools/scan_rom.py

config: $(VENV)/.done
	@if [ -n "$(CONFIG)" ]; then echo "A splat config already exists ($(CONFIG)). Delete it first to regenerate."; exit 1; fi
	$(PY) -m splat create_config $(ROM)
	@# splat guesses the KMC compiler; Rare used IDO.
	sed -i 's/^  compiler: KMC$$/  compiler: IDO/' *.yaml
	@echo "Draft config written. Next: review it with Claude Code, then run make split."

split: $(VENV)/.done
	@if [ -z "$(CONFIG)" ]; then echo "No splat config yet. Run make config first."; exit 1; fi
	$(PY) -m splat split $(CONFIG)

progress:
	$(PYTHON_SYS) tools/progress.py

guard:
	$(PYTHON_SYS) tools/guard.py --all

build:
	@echo "Not yet: the build rules arrive in Phase 2 (shiftable build)."

clean:
	rm -rf build

distclean: clean
	rm -rf asm assets
