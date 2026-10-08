# Pre-recon research

What we learned from public sources before touching the ROM. Everything here is a lead to confirm in Phase 1, not a fact about KI Gold yet.

Researched 2026-10-08, when the plan was a matching decomp. Still relevant to the recomp: the microcode, compression, libultra, and arcade-heritage leads all feed Phase 1 recon. The compiler leads only matter for the optional partial decomp.

## No existing KI Gold decomp or recomp

No public decompilation or recompilation of Killer Instinct Gold was found. We start from raw assembly.

## Best reference: GoldenEye 007 decomp

- 100% matching as of August 2026, after about nine years of community work ([Time Extension](https://www.timeextension.com/news/2026/08/after-9-years-of-work-goldeneye-007-n64-is-now-100percent-decompiled)).
- Built with **IDO 5.3**, with `-O2` for the final build. Supports building through ido-static-recomp, so no IRIX emulation needed ([repo](https://github.com/n64decomp/007)).
- Keeps two libultra copies: standard `libultra` and **`libultrare`, a Rare-modified libultra**. KI Gold shipped about a year earlier from the same studio, so its libultra may match one of these closely.
- Has an `inflate` folder for Rare's startup decompression code. KI Gold may use the same or an earlier version of that compression.

**Why it matters:** GoldenEye gives us a likely compiler, a likely libultra, and a matched codebase to fingerprint against. That could knock out all library code early.

## Other Rare references

- **Banjo-Kazooie decomp** ([GitLab](https://gitlab.com/banjo.decomp/banjo-kazooie)): another Rare N64 decomp. Compiler and library details to check in its README during recon.
- **Diddy Kong Racing:** has a decomp effort and a native PC port in progress ([Time Extension](https://www.timeextension.com/news/2025/04/soon-youll-be-able-to-play-diddy-kong-racing-natively-on-your-pc)).

## AI-driven decomp precedent

- **Silent Hill 2 (PS2)** ([repo](https://github.com/oohweee/sh2-decomp)): about 97% of roughly 5,000 functions matched between Oct 1 and Oct 8, 2026, written by Claude Code and Codex. Started from a finished prototype decomp with debug info, and used about 58 hours of main-session time plus about 256 hours of subagent time. About 90% is clean C; the rest uses fitted stand-ins, fake matches, or assembly, which the author labels clearly.
- **Takeaway:** an AI-driven matching loop works. Our pace will be slower (no head start, usage limits).

## KI Gold facts

- Developed by Rare, published by Nintendo, 1996. Software credits: Mark Betteridge, Tony Wong, Chris Tilston, Mike Currington ([Rare Gamer](https://www.raregamer.co.uk/?p=967)).
- 12 MB (96 megabit) cartridge.
- Ported from the Killer Instinct 2 arcade game. The KI arcade boards used an **IDT R4600 MIPS CPU** ([MiSTer forum](https://www.misterfpga.org/viewtopic.php?p=41359)). Some N64 game logic may be adapted from arcade code, possibly with different coding patterns. Hypothesis only.
- Audio: the game uses libultra's audio library (`alCSeqNew` and related calls), confirmed by a 2000s music-ripping walkthrough done on US V1.2 ([hcs64](https://www.hcs64.com/usf/usfwalkthrough.txt)). Standard audio library code should fingerprint easily.

## Still unknown (Phase 1)

| Question | How we'll answer it |
| --- | --- |
| Graphics microcode | Search the ROM for microcode name strings ("F3DEX", "RSP Gfx ucode", "RSP SW Version") |
| Audio microcode | Same string search; compare with known aspMain versions |
| Compression | Look for Rare's inflate routine and compressed segments while splitting |
| Compiler | Match one small function with IDO 5.3 at -O2; try other versions if it fails |
| libultra version | Fingerprint against GoldenEye's `libultra` and `libultrare` |
| Function count | Count after the first clean splat split |
