# Killer Instinct Gold: Recompiled

An unofficial, work-in-progress fan project to bring *Killer Instinct Gold* (Nintendo 64, USA V1.2) to Windows as a native PC port through **static recompilation**, with modern features: high resolution, widescreen, high refresh rate, and quality-of-life fixes.

Built with [N64Recomp](https://github.com/N64Recomp/N64Recomp), [N64ModernRuntime](https://github.com/N64Recomp/N64ModernRuntime), and [RT64](https://github.com/rt64/rt64). This is not an emulator and not a decompilation.

**This repository contains no game code or assets. You must supply your own legally obtained copy of the game to build it.**

Not affiliated with or endorsed by Nintendo, Rare, or Microsoft.

## Status

**This project is incomplete and the game is not playable.** It is in Phase 2 (first boot): the game reaches the title screen and menus with sound, with heavy graphics glitches, and a fight starts but its screen stays blank. There is no release, and the modern features are not started. See `PLAN.md` for the roadmap and `NOTES.md` for the work log.

## Building

There are no build instructions yet, because there is nothing playable to build. They will be added once the game runs.

## License

The code in this repository is licensed under the GNU General Public License v3.0, see `COPYING`. The build files are adapted from the [WWF WrestleMania 2000 recomp](https://github.com/jessetbh/WWFWrestleMania2000Recomp). The libraries under `lib/` are git submodules with their own licenses.

## Contributing

This repository never accepts the ROM, extracted assets, generated code, executables, or leaked material. A commit guard (`tools/guard.py`) enforces this.
