# Compiling Papyrus (`.psc` to `.pex`) with Caprica on macOS under CrossOver

Caprica is a Windows console `.exe` with no macOS build, so on a Mac it runs inside the CrossOver bottle. This page is
the working command, the traps that make it look like it did not run, and what was and was not tried. The Windows form
of the command, with the base-game import rules, is in skill `skyrim-context` ("Compiling Papyrus (Caprica)"); the
general way to run a Windows tool from the Mac shell is section 6 of `macos-crossover.md`.

| Tag | Meaning |
|---|---|
| **Measured today** | Run on macOS (Darwin, Apple Silicon) while writing this page: Caprica v0.3.0, CrossOver bottle `SkyGames` |
| **From `--help`** | Printed by `Caprica.exe --help`, not exercised |
| **Carried over** | Stated by the Windows toolkit (skill `skyrim-context`); not re-run here |
| **Inferred** | Follows from how the pieces work; not run |

## 1. Why it can look as if nothing ran

1. **The bottle is not where CrossOver looks.** **Measured today.** A bottle kept in `~/Bottles` is not found unless
   `CX_BOTTLE_PATH="$HOME/Bottles"` is set. Without it the `wine` wrapper fails with a `cxmessage standin` dialog text,
   `Unable to find the '<bottle>' bottle`, and exits 1.
2. **The `msync:` lines are not an error.** **Measured today.** `msync: bootstrapped mach port on wine-<id>-msync.` and
   `msync: up and running.` are Wine's start-up banner on stderr. They appear whenever the bottle was found, whether or
   not the program then did anything. If they are all you see, redirect the program's output to a file (section 2) and
   check whether the `.pex` appeared in `-o`.
3. **`Caprica.exe --help` exits 255.** **Measured today.** That is not a failure; the help text is on stdout.

The reason one earlier attempt printed only the banner was not established.

## 2. A working command

**Measured today** (a one-file test script compiled to a valid `.pex`: magic `fa57c0de`, version 3.2, exit 0).

```bash
W=/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine
CX_BOTTLE_PATH="$HOME/Bottles" "$W" --bottle <bottle> cmd /c \
  'cd /d <win-path-to-source-folder> && <win-path-to>\Caprica.exe --game skyrim -i . -o <win-path-to-output> MyScript.psc' \
  > caprica.log 2>&1
```

- Paths inside the quoted string are **Windows paths**: the maintainer's `D:` is the external volume's `Windows`
  folder, so `/Volumes/<disk>/Windows/Modding/...` is `D:\Modding\...`, and `Z:\` is the Mac root `/`, so
  `Z:\Users\...` reaches any Mac path (drive table: `macos-crossover.md` section 4). Wine does not translate arguments.
  That a Unix path in `-i` or `-o` fails is **Inferred**; the test used Windows paths throughout.
- `cmd /c` with the output redirected to a file kept Caprica's progress lines (`Imported 2 files.`, `Compiling 1
  files...`, `Compiling MyScript.psc`) in the log. Judge success by the `.pex` in `-o`, not by the exit code alone.
- `--no-convert` and `CX_BOTTLE=<bottle>`, used in `macos-crossover.md` section 6, were not needed for this run.
- `--game skyrim` is required: **From `--help`**, the default game is `starfield`.
- The source file is a **bare filename**, run from inside its folder. **Carried over**; the test did the same.
- A second `-i` pointing at the base-game `.psc` sources is needed whenever a script extends a vanilla type (without
  it: `Unable to resolve type`). **Carried over**, not re-run: the test script extended nothing.

## 3. Other flags worth knowing (From `--help`)

| Flag | Effect |
|---|---|
| `-R`, `--recurse` | compile every script in the given directories recursively |
| `-p`, `--parallel-compile` | compile files in parallel (see the 80% machine budget in `CLAUDE.md`) |
| `-q`, `--quiet` | report failures only |
| `--anonymize` | anonymize script header information |
| `--ignorecwd` | do not add the working directory to the import list |
| `-f <file>` | user-flags file; defaults exist for Skyrim |
| `--champollion-compat` | on by default; eases compiling Champollion's output |

## 4. Things to know

- **The `.pex` records the source path.** **Measured today**: the path of the compile (`Z:\private\tmp\...`) is readable
  in the header bytes. Whether `--anonymize` removes it was not tried; check before you publish a compiled script.
- Caprica adds the working directory to the import list itself, so `-i .` just makes it log "Imported 2 files" for a
  single script. Harmless. **Measured today**.
- A `.pex` loads at game startup only; a recompiled script does not hot-reload (`CLAUDE.md`, Safety Rules).
- Compile into a scratch folder, then copy the finished `.pex` where it is needed. Do not compile straight into a
  protected instance path.

## 5. Not tried

- A script that extends vanilla types, so the base-game import rules above are untested on the Mac.
- `-p` and `-R` under Wine.
- Champollion (`.pex` to `.psc`) under CrossOver: expected to behave the same way, **Inferred**.
