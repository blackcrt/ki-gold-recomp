# Phase 0 setup guide

For the Windows PC. Written for beginners to Linux and git. Do it in order; each part ends with a check so you know it worked.

Budget: one or two evenings. Do this on a PC you control.

---

## Part 1: Install WSL2 and Ubuntu (Windows side)

WSL2 runs a real Linux system inside Windows. All decomp tools expect Linux.

1. Open **PowerShell as Administrator** (Start menu, type "PowerShell", right-click, Run as administrator).
2. Run:
   ```powershell
   wsl --install -d Ubuntu-24.04
   ```
3. Restart the PC when it asks.
4. After restart, an Ubuntu window opens. Pick a **username** (lowercase, no spaces) and a **password**.
   - When you type the password, nothing shows on screen. That's normal Linux behavior, keep typing and press Enter.
   - You'll need this password for any command starting with `sudo`.

**Check:** in the Ubuntu window, run `uname -a`. You should see a line containing `Linux` and `WSL2`.

From here on, every command goes in the **Ubuntu** window unless it says PowerShell. Tip: install **Windows Terminal** from the Microsoft Store; it gives Ubuntu tabs and easy copy/paste.

---

## Part 2: Ten Linux commands you'll actually use

| Command | What it does | Windows equivalent |
| --- | --- | --- |
| `pwd` | Show which folder you're in | `cd` with no arguments |
| `ls` | List files in this folder | `dir` |
| `cd foldername` | Go into a folder | `cd` |
| `cd ~` | Go to your home folder | `cd $HOME` |
| `cd ..` | Go up one folder | `cd ..` |
| `mkdir name` | Make a folder | `mkdir` |
| `cp a b` | Copy a file | `copy` |
| `nano file` | Edit a file (Ctrl+O to save, Ctrl+X to exit) | Notepad |
| `sudo command` | Run as admin | Run as administrator |
| `explorer.exe .` | Open this folder in File Explorer | |

Your Windows drives live under `/mnt/c/`. Your Windows Downloads folder is `/mnt/c/Users/<your Windows name>/Downloads`.

**Rule:** keep the project in your Linux home folder (`~`), not under `/mnt/c/`. It's much faster and avoids permission weirdness.

---

## Part 3: Install the base toolchain

1. Update Ubuntu:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
2. Install build tools, git, Python, and the MIPS assembler/linker:
   ```bash
   sudo apt install -y build-essential git python3 python3-pip python3-venv \
     binutils-mips-linux-gnu make cmake ninja-build pkg-config libcapstone-dev \
     curl unzip gh
   ```

**Check:** `mips-linux-gnu-as --version` and `git --version` each print a version.

---

## Part 4: git identity (resume-safe)

Commits record a name and email. To keep your real name and email out of a public repo:

1. On github.com go to **Settings > Emails**, turn on **Keep my email addresses private**, and copy the address that looks like `12345678+BlackCRT@users.noreply.github.com`.
2. In Ubuntu:
   ```bash
   git config --global user.name "BlackCRT"
   git config --global user.email "PASTE_THE_NOREPLY_ADDRESS_HERE"
   git config --global init.defaultBranch main
   ```
3. Log the GitHub CLI into your account:
   ```bash
   gh auth login
   ```
   Pick **GitHub.com**, **HTTPS**, **Yes** to authenticate git, and **Login with a web browser**. It shows a code; paste it in the browser page that opens.

**Check:** `gh auth status` says you're logged in as BlackCRT.

---

## Part 5: Install Claude Code

1. In Ubuntu:
   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   ```
2. Close the Ubuntu window and open a new one.
3. Run `claude --version`. It should print a version number.
4. Log in: run `claude` and follow the browser prompt with your Pro account. Type `/exit` to leave for now.

Source: [Claude Code setup docs](https://code.claude.com/docs/en/setup).

---

## Part 6: Get the repo onto your PC

The private repo `BlackCRT/ki-gold-decomp` already exists on GitHub with the starter kit in it. You just download ("clone") it.

1. Clone it into your Linux home folder:
   ```bash
   cd ~
   git clone https://github.com/BlackCRT/ki-gold-decomp.git
   cd ki-gold-decomp
   ls -a
   ```
   You should see `CLAUDE.md`, `PLAN.md`, `NOTES.md`, `README.md`, `.gitignore`, `tools`, `docs`, and more.
2. Switch on the guard. This setting is per-computer, so it has to be done on every machine you work from:
   ```bash
   git config core.hooksPath .githooks
   ```

**Check:** `git config core.hooksPath` prints `.githooks`, and on github.com the repo shows a lock icon (private).

---

## Part 7: Add the ROM and prove the guard works

1. Copy your ROM into the repo with the exact name the project expects:
   ```bash
   cp "/mnt/c/path/to/Killer Instinct Gold (U) (V1.2) [!].z64" ~/ki-gold-decomp/baserom.us.z64
   ```
   Quotes matter because the filename has spaces and brackets.
2. Install the project's tools (Python packages and the IDO compiler), then check the ROM:
   ```bash
   make setup
   make check
   ```
   `make check` prints the ROM's name, region, revision, and SHA1 fingerprint. It should say USA, revision 2 (V1.2), and 12.00 MB. If it says the byte order is wrong, it prints the exact command to fix it.
3. Open `tools/rom.sha1` with `nano tools/rom.sha1`, paste the 40-character SHA1 from `make check` on its own line at the bottom, save (Ctrl+O, Enter) and exit (Ctrl+X). Run `make check` again; it should now say `OK: SHA1 matches`.
4. **Test the guard.** Force-add the ROM and try to commit it. This should FAIL on purpose:
   ```bash
   git add -f baserom.us.z64
   git commit -m "this should be blocked"
   ```
   You should see `guard: BLOCKED` with several reasons.
5. Unstage it again, then commit the hash file:
   ```bash
   git restore --staged baserom.us.z64
   git add tools/rom.sha1
   git commit -m "Record ROM SHA1"
   git push
   ```

**Check:** `git status` does not list `baserom.us.z64` at all (it's ignored), and the guard test was blocked.

---

## Part 8: Local AI model (Ollama)

Ollama runs on Windows so it gets full use of your GPU.

1. Download and install Ollama for Windows from [ollama.com](https://ollama.com).
2. In **PowerShell** (normal, not admin):
   ```powershell
   ollama pull qwen2.5-coder:14b
   ollama run qwen2.5-coder:14b "Explain what a MIPS jal instruction does in two sentences."
   ```
   The download is several GB. The 14B model fits in your 12 GB of VRAM.

**Check:** you get a sensible two-sentence answer. Type `/bye` if it opens a chat.

We'll connect Ollama to the Linux side in Phase 1 when we actually need it.

---

## Part 9: Hand off to Claude Code

```bash
cd ~/ki-gold-decomp
claude
```

Then type: **"Read CLAUDE.md, PLAN.md, and NOTES.md, then tell me where we are and what's next."**

Phase 0 is done when every **Check** above passed. Tick the boxes in `PLAN.md` (or ask Claude Code to).

---

## Optional: dump your own cartridge (the clean legal path)

Using a dump of a cartridge you own is the cleanest legal footing for a public release. It isn't needed to start; it's needed before anything goes public. You'll need a KI Gold cartridge and one of these readers ([dumping.guide](https://dumping.guide/_export/raw/carts/nintendo/n64) compares them):

| Reader | Notes |
| --- | --- |
| **Open Source Cartridge Reader (OSCR, "Sanni" reader)** | Dumps N64 out of the box, plus many other systems. A prebuilt v3 was listed at $169 on [Tindie](https://www.tindie.com/products/acidice333/sanni-cart-reader-v3-game-cartridge-reader/), but that seller is on a break; other sellers and DIY kits exist. Best all-rounder. |
| **Retrode 2 + N64 adapter** | Simple, shows up as a USB drive. **Watch out:** it overdumps 12 MB carts like KI Gold unless you set the size or trim the file afterward. Set voltage to 3.3V. |
| **RetroBlaster 2.0 + N64 adapter** | Works, Windows-only software, set to 3V. |
| GameShark / Action Replay, old copiers | Not recommended; unreliable dumps. |

After dumping, run `sha1sum` on your dump and compare with `tools/rom.sha1`. A match means your dump is identical to the one you're working from.
