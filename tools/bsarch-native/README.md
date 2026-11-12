# bsarch-native

A BSArch-compatible `bsarch` for macOS and Linux, built from pinned source on your machine and never shipped in the toolkit release archive.

BSArch is a Windows program. AutoMod's `archive` module starts it for `create` (pack) and `extract` (unpack), and every command that
rewrites an archive (`add-files`, `remove-files`, `update-file`, `optimize`, `merge`) is built on those two. On a Mac or Linux the real
`bsarch.exe` cannot run, so this builds a small native replacement. On Windows keep using the real `bsarch.exe` (`docs/installing-tools.md`).

## Source and pins

| Property | Value |
|---|---|
| Library | [Ryan-rsm-McKenzie/bsa](https://github.com/Ryan-rsm-McKenzie/bsa) (MIT, C++20), read and write of TES4-family archives |
| `bsa` commit | `2c7280d5c9199f90b7338d70425181029c9bb2f2` (2025-02-08) |
| `binary_io` commit | `098afdec287b216cf6d78d9f98d95b6ff833a900` |
| `mmio` commit | `b13cc7e0b4290b9379b2376314f86f304aaf8c34` |
| Patch | `patches/bsa-optional-directxtex.patch`: makes the FO4 (BA2) backend, and with it DirectXTex, optional. Only that backend needs DirectXTex; SSE and LE archives do not |
| Shim | `shim/bsarch_shim.cpp`: the command line AutoMod sends, on top of the library |

## Prerequisites

`git`, `cmake`, a C++20 compiler, and a **static** lz4 (`liblz4.a`, so the binary needs no lz4 at run time): macOS `brew install lz4`,
Debian or Ubuntu `apt install liblz4-dev`. `ninja` is used when present. Installing host software is your decision; the build only checks
and tells you. On macOS the build uses Apple's `/usr/bin/clang++` (set `CXX` to override): a Homebrew LLVM `clang++` first on `PATH`
pairs its own libc++ with the SDK's `math.h` and fails to compile (MEASURED 2026-11-12).

## Build and verification

```bash
python tools/bsarch-native/build.py          # fetch the pinned commits, patch, build, self-test, install into bin/
python tools/bsarch-native/build.py --check  # verify pins, shim and patch hashes, and the binary SHA-256; no network
python tools/bsarch-native/build.py --force  # rebuild
```

Each fetch is `git fetch --depth 1` of the pinned commit, and the build is refused unless `HEAD` equals the pin. After linking, the build
packs and unpacks a small tree, checks the archive header (version 105, compressed flag) and the bad-command exit code, and installs only
if all of that passes. `bin/fetched.json` records the pins, the shim and patch hashes and the binary's SHA-256, so `--check` also notices a
shim edited after the build. Output: `tools/bsarch-native/bin/bsarch`, gitignored and never shipped; it links only system libraries.

## When it applies (optional, like xeditlib)

- **Opt-in.** Nothing builds it for you: it is listed with the optional tools in `setup.sh`'s output, and you or your agent run `python3 tools/bsarch-native/build.py`.
- **macOS and Linux only.** `build.py` refuses on Windows, the wrapper never installs it there, and `toolchain-check.sh` does not ask about it there. Windows keeps the real `bsarch.exe`.
- **Only where AutoMod is set up.** `bash tools/toolchain-check.sh` reports `bsarch (native)` as `not built (optional ...)` (informational), `ok`, or `MISMATCH` (built, but a pin, the shim, the patch or the binary no longer matches; the result is then DEGRADED) once AutoMod is installed, and says nothing without it.
- **A hint, not a surprise build.** `tools/automod-cli.sh archive status|create|extract|extract-file|add-files|remove-files|update-file|replace-files|merge|optimize` on macOS or Linux with no `bsarch.exe` in place prints one line on stderr naming the build command, because AutoMod's own "BSArch not found" message points at Windows downloads. The wrapper never fetches or compiles anything by itself.

## How AutoMod gets it

`tools/automod-cli.sh` copies `bin/bsarch` to `<AutoMod build>/tools/bsarch/bsarch.exe` (the path AutoMod's `BsarchWrapper` starts) after
`--rebuild` and before each run, and writes `bsarch-native.txt` beside it. A `bsarch.exe` without that marker (the real one, or a Wine shim you
wrote) is never replaced. `bash tools/automod-cli.sh archive status --json` shows the path in use. A `dotnet build` of AutoMod wipes the
copy; the next wrapper call puts it back.

## Command line

```
bsarch pack <dir> <out.bsa> -sse | -tes5 | -tes4 | -fo3  [-z] [-mt]
bsarch unpack <archive> [<outdir>]
```

Exit 0 on success; exit 1 with a message on stderr on any failure. Differences from the real BSArch, all deliberate:

- `-mt` is accepted and ignored (packing a 5 MB tree takes under 0.1 s).
- FO4 and FO76 (`-fo4`, `-fo76`) and TES3 archives are not supported: the wrapper's defaults are SSE and LE.
- `pack` refuses a file directly in the pack folder (an archive file needs a folder) instead of dropping it.
- `unpack` without `<outdir>` extracts into `<archive folder>/<archive name>`; AutoMod always passes `<outdir>`.
- `unpack` refuses an entry whose path is absolute, names a drive, or contains `..`, so an archive from a third-party mod cannot write outside the
  folder you chose.
- `-z` compresses every file, including `.wav`, `.xwm` and `.fuz`. The archives it writes set the file-type bits by extension and no embedded names.

## What was measured (2026-11-12, AE 1.7.104 under CrossOver)

- 151 installed-mod archives of 20 MB or less (7,749 files, 13 different archive-flag combinations, 28 of them already compressed): unpack,
  repack with `-sse -z`, unpack again: every file name and SHA-256 identical.
- Three repacked mod archives (Simply Knock, Candlehearth, Stormcrown) loaded in the game, and the engine's own resource reader (DevBench `forms
  asset` with `hash:true`) returned 367 of 373 files byte-identical to the originals, including 153 compressed `.fuz` voice files. The other 6
  are scripts that other enabled mods override with loose files; each engine hash equals that mod's file.
- Not measured: audible playback of a repacked sound or voice file (a byte-identical file takes the same decode path as the original), archives over
  20 MB, and archives with non-ASCII entry names.
