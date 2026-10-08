# Phase 0 setup guide

For the Windows PC. Everything runs natively on Windows in **PowerShell**, because the recomp's port build requires Windows tools. Do the parts in order; each one ends with a **Check** so you know it worked.

Budget: one or two evenings, mostly waiting on downloads. Do this on a PC you control.

Tip: use **Windows Terminal** (preinstalled on Windows 11, or from the Microsoft Store). When a step says "open a new terminal," close the tab and open a fresh one so it picks up newly installed programs.

---

## Part 1: Git, Python, and the GitHub CLI

In a normal (not admin) PowerShell:

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id GitHub.cli -e
```

Open a new terminal, then:

```powershell
git --version
python --version
gh --version
```

**Check:** all three print a version. If `python` opens the Microsoft Store instead, go to **Settings > Apps > Advanced app settings > App execution aliases**, turn off the two "python" aliases, and open a new terminal.

---

## Part 2: Visual Studio Build Tools (the port compiler)

This installs clang-cl, CMake, and Ninja, the same toolchain the WrestleMania 2000 recomp uses. It's a large download (several GB) and asks for admin approval (UAC):

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Llvm.Clang --add Microsoft.VisualStudio.Component.VC.Llvm.ClangToolset --add Microsoft.VisualStudio.Component.VC.CMake.Project --includeRecommended"
```

**Check:** open **Developer PowerShell for VS 2022** from the Start menu and run:

```powershell
clang-cl --version
cmake --version
ninja --version
```

All three should print a version. We won't use these until Phase 2, but it's good to know they work.

---

## Part 3: git identity (resume-safe) and GitHub login

Commits record a name and email. To keep your real name and email out of the repo:

1. On github.com go to **Settings > Emails**, turn on **Keep my email addresses private**, and copy the address that looks like `12345678+BlackCRT@users.noreply.github.com`.
2. In PowerShell:
   ```powershell
   git config --global user.name "BlackCRT"
   git config --global user.email "PASTE_THE_NOREPLY_ADDRESS_HERE"
   git config --global core.longpaths true
   ```
   `core.longpaths` avoids "Filename too long" errors from the deeply nested runtime libraries we'll pull in later.
3. Log the GitHub CLI into your account:
   ```powershell
   gh auth login
   ```
   Pick **GitHub.com**, **HTTPS**, **Yes** to authenticate git, and **Login with a web browser**. It shows a code; paste it into the browser page that opens.

**Check:** `gh auth status` says you're logged in as BlackCRT.

---

## Part 4: Install Claude Code

```powershell
irm https://claude.ai/install.ps1 | iex
```

Open a new terminal, then run `claude --version`. It should print a version number. Then run `claude`, log in with your Pro account in the browser, and type `/exit`.

Because Git for Windows is installed, Claude Code can use Git Bash for shell commands as well as PowerShell.

Source: [Claude Code setup docs](https://code.claude.com/docs/en/setup).

---

## Part 5: Get the repo

Use a short folder path. Deep paths (like OneDrive Documents) cause "Filename too long" errors later.

```powershell
mkdir C:\src
cd C:\src
git clone https://github.com/BlackCRT/ki-gold-recomp.git
cd ki-gold-recomp
git config core.hooksPath .githooks
```

The last line switches on the legal guard. It's a per-computer setting, so it's needed on every machine you work from.

**Check:** `git config core.hooksPath` prints `.githooks`, and `dir` shows `CLAUDE.md`, `PLAN.md`, `NOTES.md`, `tools`, and `docs`.

---

## Part 6: Add the ROM and prove the guard works

1. Copy your ROM into the repo with the exact name the project expects (quotes matter because of the spaces and brackets):
   ```powershell
   Copy-Item "C:\path\to\Killer Instinct Gold (U) (V1.2) [!].z64" .\baserom.us.z64
   ```
2. Check it:
   ```powershell
   python tools\romcheck.py
   ```
   It prints the ROM's name, region, revision, size, and SHA1. It should say USA, revision 2 (V1.2), and 12.00 MB. If the byte order is wrong, it prints the exact command to fix it.
3. Record the SHA1: run `notepad tools\rom.sha1`, paste the 40-character SHA1 on its own line at the bottom, save, and close. Run `python tools\romcheck.py` again; it should now say `OK: SHA1 matches`.
4. **Test the guard.** Force-add the ROM and try to commit it. This should FAIL on purpose:
   ```powershell
   git add -f baserom.us.z64
   git commit -m "this should be blocked"
   ```
   You should see `guard: BLOCKED` with several reasons.
5. Unstage it, then commit and push the hash file:
   ```powershell
   git restore --staged baserom.us.z64
   git add tools\rom.sha1
   git commit -m "Record ROM SHA1"
   git push
   ```

**Check:** `git status` doesn't list `baserom.us.z64` (it's ignored), the guard test was blocked, and on github.com the **Actions** tab shows a green `guard` run.

---

## Part 7: Python tools for recon

Phase 1 uses splat and friends. They go in their own virtual environment inside `disasm\` so they don't clutter your system Python:

```powershell
python -m venv disasm\.venv
disasm\.venv\Scripts\pip install -r requirements.txt
```

**Check:** `disasm\.venv\Scripts\python -m splat --help` prints splat's help.

---

## Part 8: Local AI model (Ollama)

1. Download and install Ollama for Windows from [ollama.com](https://ollama.com).
2. In PowerShell:
   ```powershell
   ollama pull qwen2.5-coder:14b
   ollama run qwen2.5-coder:14b "Explain what a MIPS jal instruction does in two sentences."
   ```
   The download is several GB. The 14B model fits in your 12 GB of VRAM.

**Check:** you get a sensible two-sentence answer. Type `/bye` if it opens a chat.

---

## Part 9: Hand off to Claude Code

```powershell
cd C:\src\ki-gold-recomp
claude
```

Then type: **"Read CLAUDE.md, PLAN.md, and NOTES.md, then tell me where we are and what's next."**

Phase 0 is done when every **Check** above passed. Ask Claude Code to tick the boxes in `PLAN.md`. Your first Phase 1 command is `python tools\scan_rom.py`.

---

## Optional: dump your own cartridge (the clean legal path)

Using a dump of a cartridge you own is the cleanest legal footing for a public release. It isn't needed to start; it's needed before anything goes public. You'll need a KI Gold cartridge and one of these readers ([dumping.guide](https://dumping.guide/_export/raw/carts/nintendo/n64) compares them):

| Reader | Notes |
| --- | --- |
| **Open Source Cartridge Reader (OSCR, "Sanni" reader)** | Dumps N64 out of the box, plus many other systems. A prebuilt v3 was listed at $169 on [Tindie](https://www.tindie.com/products/acidice333/sanni-cart-reader-v3-game-cartridge-reader/), but that seller is on a break; other sellers and DIY kits exist. Best all-rounder. |
| **Retrode 2 + N64 adapter** | Simple, shows up as a USB drive. **Watch out:** it overdumps 12 MB carts like KI Gold unless you set the size or trim the file afterward. Set voltage to 3.3V. |
| **RetroBlaster 2.0 + N64 adapter** | Works, Windows-only software, set to 3V. |
| GameShark / Action Replay, old copiers | Not recommended; unreliable dumps. |

After dumping, check it with `python tools\romcheck.py` (temporarily named `baserom.us.z64`). A SHA1 match means your dump is identical to the one you're working from.
