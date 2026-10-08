# Session notes

Newest entries at the top. Each entry: what was done, what's stuck, what's next.

## 2026-10-08: Planning and pre-recon research

**Done**
- Decided on a matching decomp as the main goal, recomp as optional.
- Wrote this starter kit: CLAUDE.md, PLAN.md, setup guide, guard, research notes.
- Created the private repo BlackCRT/ki-gold-decomp and pushed the kit.
- Pre-recon research from public sources (see `docs/RESEARCH.md`): GoldenEye's decomp is 100% matched, uses IDO 5.3 and a Rare-modified libultra, so it's our main reference.

**Stuck / unknown**
- Which graphics and audio microcode KI Gold uses. No public source found; check the ROM directly in Phase 1.
- Compression format and function count. Also Phase 1.

**Also done (same day, still pre-ROM)**
- GoldenEye reference notes (`docs/GOLDENEYE.md`): IDO 5.3, game code `-O2 -mips2`, libultra `-O1`, Rare's `libultrare` modified files, and the 1172 compression format.
- Phase 1 helpers: `make check` (ROM check and byte-order fix), `make scan` (microcode strings and 1172 streams), `make progress`. All tested on synthetic ROMs.
- Build skeleton: `Makefile`, `requirements.txt` (splat64 0.50.0). `make setup` downloads IDO 5.3 from ido-static-recomp v1.2; `make config` generates the first splat config and switches it to IDO.
- Retired the old Claude Docs plan page and the claude.ai Project copy. This repo is the only plan now.

**Next**
- BlackCRT follows `docs/SETUP.md` on the Windows PC when ready to start Phase 0.
- First Phase 1 session: `make check`, `make scan`, then `make config` and `make split`.
