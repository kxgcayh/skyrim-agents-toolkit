#!/usr/bin/env python3
"""Build bsarch-native on THIS machine: a BSArch-compatible `bsarch` for macOS and Linux.

    python tools/bsarch-native/build.py [--check] [--force]

BSArch itself is a Windows program. AutoMod's `archive` module runs it for `create` and `extract` (pack and unpack), so on a
Mac or Linux it cannot. This builds a small native replacement from pinned source: Ryan-rsm-McKenzie/bsa (MIT) with the
shim in shim/bsarch_shim.cpp, which accepts the command lines AutoMod sends:

    bsarch pack <dir> <out.bsa> -sse|-tes5 [-z] [-mt]
    bsarch unpack <archive> [<outdir>]

Fetches exactly the pinned commits with git (depth 1), refuses to build unless HEAD equals each pin, applies
patches/bsa-optional-directxtex.patch, builds with cmake, runs a pack/unpack self-test, and installs atomically into
tools/bsarch-native/bin/ (gitignored, never shipped).

Flags:
  --check  verify an existing install (pins, shim and patch hashes, binary SHA-256 from fetched.json), no network.
  --force  rebuild and reinstall even if already installed.

Exit: 0 on success, non-zero on error or mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "bin"
SHIM = HERE / "shim" / "bsarch_shim.cpp"
PATCH = HERE / "patches" / "bsa-optional-directxtex.patch"

# name -> (repository, pinned commit). The commits are the ones the shim was tested with (2026-11-12).
PINS = {
    "bsa": ("https://github.com/Ryan-rsm-McKenzie/bsa.git", "2c7280d5c9199f90b7338d70425181029c9bb2f2"),
    "binary_io": ("https://github.com/Ryan-rsm-McKenzie/binary_io.git", "098afdec287b216cf6d78d9f98d95b6ff833a900"),
    "mmio": ("https://github.com/Ryan-rsm-McKenzie/mmio.git", "b13cc7e0b4290b9379b2376314f86f304aaf8c34"),
}
BINARY = "bsarch"


class BuildError(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        done = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    except FileNotFoundError:
        raise BuildError(f"{cmd[0]} not found on PATH")
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-15:])
        raise BuildError(f"{' '.join(cmd[:3])} failed (exit {done.returncode}):\n{tail}")
    return done.stdout


def check_platform(system: str | None = None) -> None:
    system = (system or platform.system()).lower()
    if system == "windows":
        raise BuildError("Windows uses the real bsarch.exe (docs/installing-tools.md); this native build is for macOS and Linux")
    if system not in ("darwin", "linux"):
        raise BuildError(f"unsupported platform: {system}")


def static_lz4_candidates(env: dict[str, str] | None = None) -> list[Path]:
    """Directories that may hold lib/liblz4.a and include/lz4frame.h, most specific first."""
    env = os.environ if env is None else env
    out: list[Path] = []
    if env.get("LZ4_PREFIX"):
        out.append(Path(env["LZ4_PREFIX"]))
    try:
        brew = subprocess.run(["brew", "--prefix", "lz4"], capture_output=True, text=True).stdout.strip()
        if brew:
            out.append(Path(brew))
    except FileNotFoundError:
        pass
    out += [Path("/usr/local"), Path("/usr")]  # Homebrew, either architecture, is found through `brew --prefix` above
    return out


def find_static_lz4(candidates: list[Path] | None = None) -> tuple[Path, Path]:
    """(liblz4.a, include dir holding lz4frame.h). A static library, so the binary needs no lz4 at run time."""
    for prefix in (candidates if candidates is not None else static_lz4_candidates()):
        include = prefix / "include"
        if not (include / "lz4frame.h").is_file():
            continue
        for libdir in ("lib", "lib64", "lib/x86_64-linux-gnu", "lib/aarch64-linux-gnu"):
            lib = prefix / libdir / "liblz4.a"
            if lib.is_file():
                return lib, include
    raise BuildError("static lz4 (liblz4.a and lz4frame.h) not found. macOS: brew install lz4. Debian/Ubuntu: apt install "
                     "liblz4-dev. Or set LZ4_PREFIX to a prefix that has include/lz4frame.h and lib/liblz4.a")


def pick_compiler(env: dict[str, str] | None = None, system: str | None = None) -> str:
    """CXX when set. On macOS Apple's /usr/bin/clang++: a Homebrew LLVM clang++ first on PATH pairs its own libc++ with the SDK's
    math.h and fails to compile (MEASURED 2026-11-12), so it is only used when CXX names it. Elsewhere clang++, c++ or g++."""
    env = os.environ if env is None else env
    if env.get("CXX"):
        return env["CXX"]
    if (system or platform.system()).lower() == "darwin" and Path("/usr/bin/clang++").is_file():
        return "/usr/bin/clang++"
    for name in ("clang++", "c++", "g++"):
        found = shutil.which(name)
        if found:
            return found
    raise BuildError("no C++ compiler found (clang++, c++ or g++); set CXX")


def source_hashes() -> dict[str, str]:
    return {"shim": sha256(SHIM), "patch": sha256(PATCH)}


def check_install(dest: Path = BIN) -> tuple[bool, str]:
    """Verify an existing install. Returns (True, "") or (False, reason)."""
    meta_file = dest / "fetched.json"
    if not meta_file.is_file():
        return False, f"missing {meta_file}"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except ValueError as e:
        return False, f"unreadable fetched.json: {e}"
    for name, (_, commit) in PINS.items():
        if meta.get("pins", {}).get(name) != commit:
            return False, f"installed {name} commit {meta.get('pins', {}).get(name)} is not the pinned {commit}"
    now = source_hashes()
    for key, value in now.items():
        if meta.get("sources", {}).get(key) != value:
            return False, f"the {key} changed since this binary was built: rebuild with --force"
    binary = dest / str(meta.get("binary", ""))
    if not meta.get("binary") or not binary.is_file():
        return False, f"missing binary {binary}"
    if sha256(binary) != meta.get("sha256"):
        return False, f"hash mismatch for {binary.name}: the binary changed after the build"
    return True, ""


def _fetch(name: str, work: Path) -> Path:
    repo, commit = PINS[name]
    dest = work / name
    dest.mkdir()
    run(["git", "init", "-q"], dest)
    run(["git", "fetch", "-q", "--depth", "1", repo, commit], dest)
    run(["git", "checkout", "-q", "FETCH_HEAD"], dest)
    head = run(["git", "rev-parse", "HEAD"], dest).strip()
    if head != commit:
        raise BuildError(f"{name}: fetched HEAD {head} is not the pinned {commit}")
    return dest


def self_test(binary: Path, work: Path) -> None:
    """pack then unpack a small tree and compare it; fails loudly. Also checks the archive header."""
    import struct
    tree = work / "selftest-in"
    for rel, data in (("meshes/a/one.nif", b"nif-bytes" * 500), ("sound/fx/two.wav", bytes(range(256)) * 40)):
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    archive = work / "selftest.bsa"
    run([str(binary), "pack", str(tree), str(archive), "-sse", "-z"])
    head = archive.read_bytes()[:36]
    magic, version, _, flags = struct.unpack("<4sIII", head[:16])
    if magic != b"BSA\0" or version != 105 or not flags & 4:
        raise BuildError(f"self-test: unexpected archive header (magic {magic!r}, version {version}, flags {flags:#x})")
    out = work / "selftest-out"
    run([str(binary), "unpack", str(archive), str(out)])
    for rel in ("meshes/a/one.nif", "sound/fx/two.wav"):
        if (out / rel).read_bytes() != (tree / rel).read_bytes():
            raise BuildError(f"self-test: {rel} differs after pack and unpack")
    done = subprocess.run([str(binary)], capture_output=True, text=True)
    if done.returncode != 1 or not done.stderr.strip():
        raise BuildError("self-test: a bad command line must exit 1 with a message on stderr")


def build(dest: Path = BIN) -> Path:
    check_platform()
    machine = platform.machine().lower()
    lz4_lib, lz4_include = find_static_lz4()
    cxx = pick_compiler()
    cmake = shutil.which("cmake")
    if not cmake:
        raise BuildError("cmake not found on PATH")
    generator = ["-G", "Ninja"] if shutil.which("ninja") else []
    jobs = str(max(1, (os.cpu_count() or 2) // 2))  # stay well under the 80% machine budget

    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="build-", dir=str(dest.parent)))
    try:
        src = {name: _fetch(name, work) for name in PINS}
        run(["git", "apply", "--check", str(PATCH)], src["bsa"])
        run(["git", "apply", str(PATCH)], src["bsa"])

        prefix = work / "prefix"
        common = generator + ["-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_CXX_COMPILER={cxx}",
                              f"-DCMAKE_INSTALL_PREFIX={prefix}", "-DBUILD_TESTING=OFF"]
        if platform.system().lower() == "darwin":
            common.append(f"-DCMAKE_OSX_ARCHITECTURES={'arm64' if machine in ('arm64', 'aarch64') else 'x86_64'}")
        for name in ("binary_io", "mmio"):
            build_dir = work / "build" / name
            run([cmake, "-S", str(src[name]), "-B", str(build_dir)] + common)
            run([cmake, "--build", str(build_dir), "-j", jobs])
            run([cmake, "--install", str(build_dir)])

        bsa_build = work / "build" / "bsa"
        run([cmake, "-S", str(src["bsa"]), "-B", str(bsa_build)] + common + [
            f"-DCMAKE_PREFIX_PATH={prefix}", f"-DLZ4_LIBRARY_RELEASE={lz4_lib}", f"-DLZ4_INCLUDE_DIR={lz4_include}",
            "-DBSA_ENABLE_FO4=OFF", "-DBSA_BUILD_EXAMPLES=OFF", "-DBSA_BUILD_DOCS=OFF", "-DBSA_SUPPORT_XMEM=OFF"])
        run([cmake, "--build", str(bsa_build), "-j", jobs])
        libbsa = next(iter(bsa_build.rglob("libbsa.a")), None)
        if libbsa is None:
            raise BuildError("libbsa.a was not produced")

        stage = work / "stage"
        stage.mkdir()
        binary = stage / BINARY
        arch = ["-arch", "arm64" if machine in ("arm64", "aarch64") else "x86_64"] if platform.system().lower() == "darwin" else []
        run([cxx, "-std=c++20", "-O2"] + arch + [
            "-I", str(src["bsa"] / "include"), "-I", str(bsa_build / "src" / "include"), "-I", str(prefix / "include"),
            "-I", str(lz4_include), str(SHIM), str(libbsa),
            str(prefix / "lib" / "libbinary_io.a"), str(prefix / "lib" / "libmmio.a"), str(lz4_lib), "-lz", "-o", str(binary)])
        self_test(binary, work)

        meta = {"pins": {name: commit for name, (_, commit) in PINS.items()}, "sources": source_hashes(),
                "binary": BINARY, "sha256": sha256(binary), "machine": machine, "system": platform.system()}
        (stage / "fetched.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        if dest.exists():
            shutil.rmtree(str(dest))
        os.replace(str(stage), str(dest))
        return dest / BINARY
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build bsarch-native (BSArch-compatible pack/unpack for macOS and Linux)")
    parser.add_argument("--check", action="store_true", help="verify an existing install, no network")
    parser.add_argument("--force", action="store_true", help="rebuild and reinstall")
    args = parser.parse_args(argv)

    if args.check or not args.force:
        ok, reason = check_install(BIN)
        if args.check:
            if not ok:
                print(f"ERROR: {reason}", file=sys.stderr)
                return 1
            print(f"verified {BIN}")
            return 0
        if ok:
            print(f"already installed and verified in {BIN}")
            return 0

    try:
        binary = build(BIN)
    except (BuildError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"built {binary}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
