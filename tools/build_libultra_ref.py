#!/usr/bin/env python3
"""Build the libultra reference objects that fingerprint_libultra.py matches against.

Everything lands in build/ref/ (git-ignored, never committed):
  build/ref/ultralib/   decompals/ultralib, the public libultra decompilation
  build/ref/N64Recomp/  only for src/symbol_lists.cpp (the runtime's function lists)
  build/ref/ido/        IDO 5.3 from decompals/ido-static-recomp v1.2
  build/ref/obj/<variant>/<dir>/<file>.o   the compiled reference objects

No make, gcc, or MIPS binutils needed: IDO compiles both the C and the assembly
files, and the fingerprint tool reads the .o files itself.

Version note: KI Gold reports libultra 2.0D. ultralib has no 2.0D-specific
source (its version switches start at 2.0J), so this builds its oldest code,
which is 2.0I, with the optimisation flags its Makefile lists for versions
D to I. Functions that changed between D and I will simply not match.

Usage:
  python3 tools/build_libultra_ref.py            # fetch what is missing, build
  python3 tools/build_libultra_ref.py --jobs 8
"""
import argparse
import subprocess
import sys
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REF = REPO / "build" / "ref"

# Pinned so every machine builds the same reference.
ULTRALIB_URL = "https://github.com/decompals/ultralib"
ULTRALIB_COMMIT = "e24c836796df4bf520ff8b11a5c9d2cea3a66cbd"
N64RECOMP_URL = "https://github.com/N64Recomp/N64Recomp"
N64RECOMP_COMMIT = "ffb39cdad1da5de07eaaa48bd1db4a89a7986771"
IDO_URL = ("https://github.com/decompals/ido-static-recomp/releases/download/"
           "v1.2/ido-5.3-recomp-linux.tar.gz")

# Variants: we do not know yet whether Rare linked the "_rom" (final ROM)
# library or the plain one, so build both.
VARIANTS = {
    "ultralib_2.0I_rom": ["-D_FINALROM"],
    "ultralib_2.0I": [],
}

# Flags below are copied from ultralib's Makefile and makefiles/ido.mk
# (TARGET=libultra*, VERSION D to I).
CFLAGS = ["-c", "-Wab,-r4300_mul", "-G", "0", "-nostdinc", "-Xcpluscomm",
          "-fullwarn", "-woff", "516,649,838,712"]
ASFLAGS = ["-c", "-Wab,-r4300_mul", "-G", "0", "-nostdinc",
           "-woff", "516,649,838,712"]
CPPFLAGS = ["-D_MIPS_SZLONG=32", "-DBUILD_VERSION=VERSION_D",
            '-DBUILD_VERSION_STRING="2.0D"', "-DNDEBUG"]
O3_DIRS = {"libc", "sched", "gu", "mgu", "sp", "audio", "rg", "gt"}
O1_LIBC = {"ll", "llbit", "llcvt"}
MIPS3 = {"libc/ll", "libc/llbit", "libc/llcvt", "os/exceptasm"}
GBI = {"gu/parse_gbi": ["-DF3D_GBI"], "sp/sprite": ["-DF3D_GBI"],
       "gu/us2dex_emu": [], "gu/us2dex2_emu": [],
       "sp/spriteex": [], "sp/spriteex2": []}
# Versions J and below use the C matrix code, not these assembly files.
SKIP = {"mgu/mtxcatf.s", "mgu/normalize.s", "mgu/scale.s", "mgu/translate.s"}
SKIP_DIRS = {"voice"}  # needs a Shift-JIS conversion step; not in a 1996 game


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def fetch_repo(url, commit, dest):
    """Clone one pinned commit (shallow) unless it is already there."""
    if (dest / ".git").exists():
        have = run(["git", "rev-parse", "HEAD"], cwd=dest).stdout.strip()
        if have == commit:
            return
        sys.exit(f"{dest} is at {have}, expected {commit}. Delete it and rerun.")
    dest.mkdir(parents=True, exist_ok=True)
    for cmd in (["git", "init", "-q"],
                ["git", "remote", "add", "origin", url],
                ["git", "fetch", "-q", "--depth", "1", "origin", commit],
                ["git", "checkout", "-q", "FETCH_HEAD"]):
        r = run(cmd, cwd=dest)
        if r.returncode != 0:
            sys.exit(f"{' '.join(cmd)} failed in {dest}: {r.stderr.strip()}")


def fetch_ido(dest):
    if (dest / "cc").exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "ido.tar.gz"
    urllib.request.urlretrieve(IDO_URL, archive)
    with tarfile.open(archive) as tar:
        tar.extractall(dest)
    archive.unlink()


def flags_for(rel, defines):
    """Compiler flags for one source file, following ultralib's Makefile."""
    key = rel.with_suffix("").as_posix()
    top = rel.parts[0]
    is_asm = rel.suffix == ".s"
    if is_asm:
        opt = "-O2" if top in ("libc", "mgu") else "-O1"
    elif key == "os/initialize_isv":
        opt = "-O2"
    elif top == "libc" and rel.stem in O1_LIBC:
        opt = "-O1"
    elif top in O3_DIRS:
        opt = "-O3"
    else:
        opt = "-O1"
    mips = ["-mips3", "-32"] if key in MIPS3 else ["-mips2", "-o32"]
    pic = ["-non_shared"]
    if key == "log/delay":
        mips, pic = ["-mips1", "-o32"], ["-KPIC"]
    gbi = GBI.get(key, ["-DF3DEX_GBI"])
    return (ASFLAGS if is_asm else CFLAGS) + mips + CPPFLAGS + gbi + pic + defines + [opt]


def compile_one(job):
    cc, src_root, rel, out, defines = job
    out.parent.mkdir(parents=True, exist_ok=True)
    inc = src_root.parent / "include"
    cmd = [str(cc)] + flags_for(rel, defines) + [
        rel.name, "-I", str(inc), "-I", str(inc / "compiler" / "ido"),
        "-I", str(inc / "PR"), "-o", str(out)]
    r = run(cmd, cwd=src_root / rel.parent)
    return rel, r.returncode == 0 and out.exists(), r.stderr.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--verbose", action="store_true", help="print compiler errors")
    args = ap.parse_args()

    fetch_repo(ULTRALIB_URL, ULTRALIB_COMMIT, REF / "ultralib")
    fetch_repo(N64RECOMP_URL, N64RECOMP_COMMIT, REF / "N64Recomp")
    fetch_ido(REF / "ido")

    src_root = REF / "ultralib" / "src"
    sources = sorted(
        p.relative_to(src_root) for p in src_root.rglob("*")
        if p.suffix in (".c", ".s")
        and p.relative_to(src_root).parts[0] not in SKIP_DIRS
        and p.relative_to(src_root).as_posix() not in SKIP)

    for variant, defines in VARIANTS.items():
        out_root = REF / "obj" / variant
        jobs = [(REF / "ido" / "cc", src_root, rel,
                 out_root / rel.with_suffix(".o"), defines) for rel in sources]
        with ThreadPoolExecutor(args.jobs) as pool:
            results = list(pool.map(compile_one, jobs))
        failed = [(rel, err) for rel, ok, err in results if not ok]
        print(f"{variant}: {len(results) - len(failed)} of {len(results)} files compiled")
        if failed:
            print("  did not compile: " + " ".join(rel.as_posix() for rel, _ in failed))
            if args.verbose:
                for rel, err in failed:
                    print(f"--- {rel}\n{err[:600]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
