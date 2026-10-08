# Phase 0 setup guide

For the Windows PC that builds and runs the game. **You don't need to follow this alone:** open a chat in the claude.ai Project and say "Let's start Phase 0." The coach chat walks you through it one step at a time. This file is the reference version.

## How this setup works

Ubuntu in WSL plus one Windows piece:

- **Ubuntu (WSL) is home base.** You open Ubuntu, go to the project, and run `claude`. Git, Python tools, recon, and the recompiler all run here.
- **Windows builds the game.** The final `.exe` needs Windows build tools (clang-cl, CMake, Ninja). Claude Code starts that build from Ubuntu with a PowerShell script, and you double-click the result to play. Not needed until Phase 2.
- **The repo lives on your C: drive** (`C:\src\ki-gold-recomp`), so both sides can reach it. From Ubuntu it's `/mnt/c/src/ki-gold-recomp`.
- **No Docker.** This project doesn't need it.

Each part ends with a **Check** so you know it worked.

---

## Part 1: Confirm what you already have

In Ubuntu:

```bash
git --version
python3 --version
gh auth status
claude --version
git config --global user.email
```

**Check:** all of them print something, `gh auth status` shows you logged in as BlackCRT, and the email is your `...@users.noreply.github.com` address. If anything is missing, tell the coach chat and we'll fix it.

Then add the one Python package the recon tools need:

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
```

---

## Part 2: Windows build tools (can wait until Phase 2)

In **PowerShell on Windows** (not Ubuntu). It's a large download (several GB) and asks for admin approval:

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Llvm.Clang --add Microsoft.VisualStudio.Component.VC.Llvm.ClangToolset --add Microsoft.VisualStudio.Component.VC.CMake.Project --includeRecommended"
```

Then turn on long file paths, since the runtime libraries we'll pull in later are nested deeply. In **PowerShell as administrator**:

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force
```

**Check:** open **Developer PowerShell for VS 2022** from the Start menu and run `clang-cl --version`, `cmake --version`, and `ninja --version`. All three should print a version.

---

## Part 3: Get the repo

In Ubuntu:

```bash
mkdir -p /mnt/c/src
cd /mnt/c/src
git clone https://github.com/BlackCRT/ki-gold-recomp.git
cd ki-gold-recomp
git config core.hooksPath .githooks
git config core.fileMode false
```

- `core.hooksPath` switches on the legal guard.
- `core.fileMode false` stops git from thinking every file changed. Files on the C: drive look "executable" to Linux, and without this git reports that as a change.

**Check:** `git status` says "nothing to commit, working tree clean", and `ls` shows `CLAUDE.md`, `PLAN.md`, `NOTES.md`, `tools`, and `docs`.

---

## Part 4: Add the ROM and prove the guard works

1. Copy your ROM into the repo with the exact name the project expects. Your Windows files are under `/mnt/c/`. Quotes matter because of the spaces and brackets:
   ```bash
   cp "/mnt/c/path/to/Killer Instinct Gold (U) (V1.2) [!].z64" baserom.us.z64
   ```
2. Check it:
   ```bash
   python3 tools/romcheck.py
   ```
   It should say USA, revision 2 (V1.2), and 12.00 MB. If the byte order is wrong, it prints the exact commands to fix it.
3. Record the SHA1: `nano tools/rom.sha1`, paste the 40-character SHA1 on its own line at the bottom, save (Ctrl+O, Enter), exit (Ctrl+X). Run `python3 tools/romcheck.py` again; it should say `OK: SHA1 matches`.
4. **Test the guard.** This commit should FAIL on purpose:
   ```bash
   git add -f baserom.us.z64
   git commit -m "this should be blocked"
   ```
   You should see `guard: BLOCKED` with several reasons.
5. Unstage it, then commit and push the hash file:
   ```bash
   git restore --staged baserom.us.z64
   git add tools/rom.sha1
   git commit -m "Record ROM SHA1"
   git push
   ```

**Check:** `git status` doesn't list `baserom.us.z64` (it's ignored), the guard test was blocked, and the **Actions** tab on github.com shows a green `guard` run.

---

## Part 5: Python tools for recon

```bash
python3 -m venv disasm/.venv
disasm/.venv/bin/pip install -r requirements.txt
```

**Check:** `disasm/.venv/bin/python -m splat --help` prints splat's help.

---

## Part 6: Local AI model (Ollama, on Windows)

Ollama runs on Windows so it gets full use of your GPU.

1. Download and install Ollama for Windows from [ollama.com](https://ollama.com).
2. In PowerShell:
   ```powershell
   ollama pull qwen2.5-coder:14b
   ollama run qwen2.5-coder:14b "Explain what a MIPS jal instruction does in two sentences."
   ```

**Check:** you get a sensible two-sentence answer. Type `/bye` if it opens a chat.

---

## Part 7: Start Claude Code

In Ubuntu:

```bash
cd /mnt/c/src/ki-gold-recomp
claude
```

First message to Claude Code: **"Read CLAUDE.md, PLAN.md, and NOTES.md, then give me a short summary of where we are."** Paste its answer to the coach chat.

Phase 0 is done when every **Check** above passed (Part 2 can wait). Your first Phase 1 command is `python3 tools/scan_rom.py`.

---

## Optional: dump your own cartridge (the clean legal path)

Using a dump of a cartridge you own is the cleanest legal footing for a public release. It isn't needed to start; it's needed before anything goes public. You'll need a KI Gold cartridge and one of these readers ([dumping.guide](https://dumping.guide/_export/raw/carts/nintendo/n64) compares them):

| Reader | Notes |
| --- | --- |
| **Open Source Cartridge Reader (OSCR, "Sanni" reader)** | Dumps N64 out of the box, plus many other systems. A prebuilt v3 was listed at $169 on [Tindie](https://www.tindie.com/products/acidice333/sanni-cart-reader-v3-game-cartridge-reader/), but that seller is on a break; other sellers and DIY kits exist. Best all-rounder. |
| **Retrode 2 + N64 adapter** | Simple, shows up as a USB drive. **Watch out:** it overdumps 12 MB carts like KI Gold unless you set the size or trim the file afterward. Set voltage to 3.3V. |
| **RetroBlaster 2.0 + N64 adapter** | Works, Windows-only software, set to 3V. |
| GameShark / Action Replay, old copiers | Not recommended; unreliable dumps. |

After dumping, check it with `python3 tools/romcheck.py` (temporarily named `baserom.us.z64`). A SHA1 match means your dump is identical to the one you're working from.
