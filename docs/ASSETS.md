# Menu assets and controller database

Where every file the launcher needs comes from, its license, and the pinned version.

RecompFrontend loads `recomp.rcss`, three fonts and `icons/*.svg` from an `assets` folder next to the exe. `src/main/main.cpp` loads `recompcontrollerdb.txt` from the exe's folder. RecompFrontend ships none of these files, and no submodule has them. Nothing here was copied from `lib/`.

The build (`CMakeLists.txt`, section "Menu assets and controller database") puts everything in `build-msvc/assets/` and `build-msvc/recompcontrollerdb.txt`.

Our source folder is called `menu/`, not `assets/`, because the legal guard reserves the name `assets` for extracted game data.

## Committed files

| File | Source | License | Pinned version |
| --- | --- | --- | --- |
| `menu/recomp.rcss` | Written for this project | GPL-3.0 (ours) | n/a |
| `menu/icons/*.svg` (11 files) | [BanjoRecomp/BanjoRecomp](https://github.com/BanjoRecomp/BanjoRecomp), `assets/icons/` | GPL-3.0 | commit `dbd52154bc1e00e56867b1fac94a8f907052f41b` (2026-09-25) |
| `recompcontrollerdb.txt` | [BanjoRecomp/BanjoRecomp](https://github.com/BanjoRecomp/BanjoRecomp), `recompcontrollerdb.txt`. Its data comes from [SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB) (named in the file's header as `gabomdq/SDL_GameControllerDB`, the project's old address) | GPL-3.0 for the BanjoRecomp file, zlib for the SDL_GameControllerDB data | same commit |

Notes on the committed files:
- **Icons.** Unchanged copies. Banjo: Recompiled is made by the authors of RecompFrontend, and its repository has the full icon set the frontend asks for at our pin: `Caret`, `Cont`, `Keyboard`, `PlusKeyboard`, `Question`, `Quit`, `RecordBorder`, `RecordSpinner`, `Reset`, `Trash`, `X`. The repository is GPL-3.0 with a plain `COPYING` file and no separate terms for its assets, so the icons are taken as GPL-3.0, the same license as this project. The files carry no author or license marks of their own. Five of them (`Quit`, `RecordBorder`, `Reset`, `Trash`, `X`) are also in [Zelda64Recomp](https://github.com/Zelda64Recomp/Zelda64Recomp) (GPL-3.0). Only the 11 icons the frontend loads are included.
- **Controller database.** Unchanged copy, 81 controller entries. It is a filtered list (N64 and GameCube style controllers, per its header). The full upstream file is 609 KB, over the guard's 512 KB limit. The file is optional: without it SDL still knows the common controllers.
- **Style sheet.** RecompFrontend has its base styles built in. Ours holds one empty rule.

SHA-256 of the copied files, to check they are unchanged:

| File | SHA-256 |
| --- | --- |
| `menu/icons/Caret.svg` | `fa4fe2c02fdcd210fecc6788bde1d7e73dce74bd1065d1769aedc7b522593e4f` |
| `menu/icons/Cont.svg` | `8e29c18296ddf89ba8e2329ee800d1f7fb72534cdd81d04c79e02cb65b5ef6b4` |
| `menu/icons/Keyboard.svg` | `ebd3e892dd90ea84b3aa6073f7e7c2bbe7901cce768eac592abf7635b9a67ff3` |
| `menu/icons/PlusKeyboard.svg` | `0431fb0a1ba3da8f6611997e8ce413d6c3b6a62a8b938a9fa7514c6384de0938` |
| `menu/icons/Question.svg` | `fe8b47d048d5f4bfb0ed81306fb51ed3d3d01c41de294f22c7445880ddb1213f` |
| `menu/icons/Quit.svg` | `7b175d3db463d74782cf85d3cfb5012aed298be64681b3b663787a585e69ede0` |
| `menu/icons/RecordBorder.svg` | `e25ea113f4397f983a518d9e271eeefc85e2f5f6b595236413872dae6778fa3c` |
| `menu/icons/RecordSpinner.svg` | `82b2225a050ab3931744c53236fa954940818bc3de9536781ff5b2f00806c6e6` |
| `menu/icons/Reset.svg` | `1f7d082f9e02d643356014bfddec6da7c6821b13ef831bcde0bb0d9c2df08c98` |
| `menu/icons/Trash.svg` | `0641be86b647b6c8088639d7e8a60a9e3d568ac6e594697787ebfd15443a80d0` |
| `menu/icons/X.svg` | `55e9e47d8f1de87267b99ab7eae0d0fb50bc78c75922c46599b98a55041512bb` |
| `recompcontrollerdb.txt` | `a0659f8fb5c1398365d1280034f39350259cd169c79c0e12002da0df92adcc7c` |

## Downloaded at configure time (never committed)

CMake downloads each file once into `build-msvc/menu-fonts/`, checks its SHA-256, and stops with an error if it does not match. A file that is already there with the right hash is not downloaded again.

| File in `assets/` | Project | License | Pinned version | Download | SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `InterVariable.ttf` | [Inter](https://github.com/rsms/inter) | SIL Open Font License 1.1 | v4.1, commit `e3a3d4c57d5ecc01453a575621882a384c1995a3` | `docs/font-files/InterVariable.ttf` from the repository at that commit | `4989b125924991b90d05b2d16e0e388c48f7d5bb8b30539bbf9c755278d0ccaf` |
| `InterVariable-LICENSE.txt` | same | | same | `LICENSE.txt` | `262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a` |
| `NotoEmoji-Regular.ttf` | [Noto Emoji](https://github.com/googlefonts/noto-emoji) | SIL Open Font License 1.1 | v2.034, commit `9a5261d871451f9b5183c93483cbd68ed916b1e9` | `fonts/NotoEmoji-Regular.ttf` from the repository at that commit | `415dc6290378574135b64c808dc640c1df7531973290c4970c51fdeb849cb0c5` |
| `NotoEmoji-LICENSE.txt` | same | | same | `fonts/LICENSE` | `6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2` |
| `promptfont/promptfont.ttf` | [PromptFont](https://github.com/Shinmera/promptfont) | SIL Open Font License 1.1 | v1.5 | taken out of the release file `promptfont.zip` | `f421290c042d4cbb384491f9ba095d1c71a098af29ac730fdc159b28b2462f69` |
| `promptfont/LICENSE.txt` | same | | same | same zip | `6c18ad8456572e565054d86e8bc5f444e760f77624aed710b7ba828c03af51ae` |
| (the zip itself, stays in `menu-fonts/`) | same | | v1.5 | `https://github.com/Shinmera/promptfont/releases/download/v1.5/promptfont.zip` | `b7c4890998177f34a0c46363cb423e70c4d331216c7ffb7df6bc63b8ad3e86fc` |

Notes on the fonts:
- Inter v4.1 and Noto Emoji v2.034 are byte for byte the files WM2K and Banjo: Recompiled ship (compared by hash only).
- **PromptFont is not the same build they ship.** Their file (101,696 bytes) matches none of the releases v1.2 to v1.10. v1.5 is the closest in size (102,848 bytes) and has the same font file as v1.6. PromptFont draws the controller button pictures in the menus. If a button picture is missing or wrong in the launcher, this is the first place to look.
- The Noto Emoji repository as a whole is Apache-2.0 (its tools); its fonts are under the SIL Open Font License, per `fonts/LICENSE`.
- The license files are placed beside the fonts so the build folder is complete if it is ever passed on. Releases of this project are source only.

## To update a file

Change the version and the hash together, in `CMakeLists.txt` (fonts) or by replacing the committed file, and update this page in the same commit.
