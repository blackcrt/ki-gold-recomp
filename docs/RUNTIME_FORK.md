# Our fork of N64ModernRuntime

`lib/N64ModernRuntime` is a git submodule that points at our own fork, not at the upstream project. This file lists every change we make to it and why. If the list and the branch ever disagree, the branch is wrong.

| | |
| --- | --- |
| Upstream | https://github.com/N64Recomp/N64ModernRuntime |
| Our fork | https://github.com/blackcrt/N64ModernRuntime |
| Branch | `kigold` |
| Base commit | `4dc67eda958e5bf7d347e204eaa21798bc306a41` (`4dc67ed`), the pin we used before forking |
| License | GPL-3.0, same as upstream and as this repo |

The other two libraries (`lib/RecompFrontend`, `lib/rt64`) are still upstream at fixed pins, with no changes.

## Changes

| # | Fork commit | Files | What | Why | Could go upstream? |
| --- | --- | --- | --- | --- | --- |
| 1 | `45f0c58` Back rdram with a shared section on Windows | `librecomp/src/recomp.cpp`, `librecomp/include/librecomp/game.hpp` | The game's memory block is reserved as placeholder memory with one section object mapped over the first 512 MB, instead of plain `VirtualAlloc` memory. New function `recomp::get_rdram_section()` returns the section handle. At exit the view is unmapped instead of the block being freed. Windows only, the Linux code is unchanged | Killer Instinct Gold maps fighter data and a palette page at low addresses with the N64 TLB, and uses the same memory through both addresses. Windows can only show the same memory at two addresses if it comes from a section. Doing the swap later from our own code is not safe: the renderer reads the block every frame from another thread (see `NOTES.md`, tasks 7o to 7r) | Maybe, as an option. It raises the minimum to Windows 10 version 1803 |

## How to check

Run from the repo root. The output must be exactly the rows of the table above, newest first:

```
git -C lib/N64ModernRuntime log --oneline 4dc67ed..HEAD
```

To see every changed line:

```
git -C lib/N64ModernRuntime diff 4dc67ed..HEAD
```

## Rules

- A change to the runtime is only ever a commit on the `kigold` branch of the fork. Never edit files under `lib/` without committing them there, and never copy runtime files into our own folders.
- One purpose per commit, with a message that says what and why.
- Add the row to the table above in the same session, and commit the new submodule pointer in this repo together with it.
- Never amend or force-push a commit that is already on the fork. Fix mistakes with a new commit and a new row.
- Keep changes as small as possible. If something can be done from `src/`, do it there.
- Only our own work goes into the fork. The legal rules of this repo apply there too.

## Moving to a newer upstream later

Not planned. If it is ever needed: fetch `upstream`, start a new branch at the new base commit, apply the commits from the table one by one (`git cherry-pick`), build, run the game, then change the base commit in this file.
