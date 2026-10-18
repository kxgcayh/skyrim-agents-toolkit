# Running the toolkit on macOS with CrossOver

For Skyrim SE/AE played on a Mac (Apple Silicon) through **CrossOver** (Wine + DXVK + D3DMetal/MoltenVK), with the
agent running natively on macOS. This is not the Linux container (`container-vs-windows.md`): the game and its mod
manager live in a Wine bottle, the agent and most tools live on the Mac.

Every statement carries a tag:

| Tag | Meaning |
|---|---|
| **Measured today** | Run on macOS (Darwin, Apple Silicon) while writing this page |
| **Measured (notes)** | Observed by the maintainer on a CrossOver setup; carried over from their earlier notes, not re-run |
| **Inferred** | Follows from how the pieces work; not run. Check before relying on it |

Maintainer's setup for the "notes" entries: Skyrim SE/AE 1.7.104, Mod Organizer 2 2.5.x, a CrossOver bottle, the game
and MO2 instance on an external volume. Versions of Wine-side tools move; treat version numbers as examples.

## 1. What runs where

| Piece | Where | Status |
|---|---|---|
| `setup.sh`, the Python and shell tools | macOS, natively | **Measured today**: `setup.sh --game <dir> --agent claude` exits 0, configures the hooks, leaves the game folder untouched. Python 3.9 from Xcode is below the tested 3.10-3.13 |
| The safety hooks (`.claude/hooks/*.sh`) | macOS, natively, **but only under bash 4.4+** | **Measured today**: the hooks need bash 4.4 for a time-limited child process; on bash 3.2 they cannot run the engine and **refuse every guarded call** (their source returns 126). macOS ships 3.2. See the next section |
| Codex hooks | n/a | The toolkit's Codex support is Windows-only (`setup.sh` says so) |
| `XEditLib.dll` (xelib, `skyrim-winner`) | Windows only | **Inferred**: a Delphi-built Windows DLL cannot load into a native macOS process, the same reason it cannot run in the Linux container (`container-vs-windows.md`) |
| `Caprica.exe`, `Champollion.exe` | Windows `.exe` | **Inferred**: would need to run under CrossOver's `wine` (section 6). Not tried |
| Spriggit, AutoMod CLI | .NET 10 | **Inferred**: .NET runs on macOS, but AutoMod downloads Windows tools for some modules. Not tried |
| ReSaver CLI | Java | **Inferred**: needs a real JDK 17+ on the Mac |
| DevBench (live in-game) | inside the game, in the bottle | **Inferred**: its localhost server is reachable from macOS only if CrossOver exposes the port. Not tried |
| Mod Organizer 2, LOOT, BodySlide, Wabbajack | Windows apps in the bottle | **Measured (notes)**: they run, with the fixes in section 5 |

## 2. Bash 4.4 or newer is required for the hooks

**Measured today.** `/bin/bash` on macOS is 3.2.57. The hooks run under the `bash` first on `PATH` and need 4.4+
(`.claude/hooks/*.sh`, lines that test `BASH_VERSINFO`). On 3.2 they fail closed: Bash and edit calls are refused,
and `KB GUARD: NOT RUN -- the engine failed (exit 126)` appears at session start. Eight hook-related test files
(`test_hooks`, `test_kb_guard`, `test_codex_entry`, ...) still fail 132 tests here on bash 3.2, none of them new.

```bash
brew install bash                                  # a host install: for you to run, not the agent
export PATH="/opt/homebrew/bin:$PATH"             # before /bin; add to your shell profile
bash -c 'echo ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}'    # must print 4.4 or higher
bash tools/hook-canary.sh                          # after real agent calls, confirms the hooks ran
```

Restart your agent after changing `PATH`. `setup.sh` now warns when the bash on `PATH` is too old. The two bash 3.2
errors that did not need a newer bash are fixed in this fork (`printf '%(...)T'` falls back to `date`, and
`tools/kb-guard.sh` no longer needs `declare -A`), but the 4.4 requirement itself remains.

**Measured today with Homebrew bash 5.3 first on `PATH`**: the same 14 hook, guard and setup test files go from 134
failures to 4 (3 in `test_setup_paths`, 1 in `test_setup_agent`: Codex and Windows tests, identical on the upstream
commit). So the hooks work on a Mac once the bash is new enough.

`hook-canary.sh` in a source checkout of the toolkit reports `DEGRADED ... cannot run Python`: the checkout's hooks still
hold the `{{PYTHON_PATH}}` placeholder. Run it in an install that `setup.sh` configured, after real agent calls.

## 3. Setting up the paths (the part that is easy to get wrong)

`setup.sh` finds your config and load-order folders by asking Windows. On a Mac there is no Windows, so it falls
back to a path that does not exist.

**Measured today** (before this fork's fix): with no override it wrote
`SKYRIM_CONFIG_DIR='C:/Users/<you>/Documents/My Games/Skyrim Special Edition'` into `skyrim-paths.env` and
`CLAUDE.md`. The guards then protect a folder that is not there, and your real saves and INIs are unprotected.

**Fix, measured today.** Set both folders before running setup, using the paths the bottle actually uses:

```bash
export SKYRIM_CONFIG_DIR="$HOME/Documents/My Games/Skyrim Special Edition"      # saves, Skyrim.ini, SkyrimPrefs.ini
export SKYRIM_LOADORDER_DIR="<bottle>/drive_c/users/crossover/AppData/Local/Skyrim Special Edition"   # plugins.txt
bash setup.sh --game "<folder holding SkyrimSE.exe>" --agent claude
grep -E 'CONFIG_DIR|LOADORDER_DIR|GAME_ROOT' skyrim-paths.env     # check all three before trusting the guards
```

Where those folders are depends on the bottle. In the maintainer's bottle (**notes**) `Documents`, `Downloads` and
the other user folders inside the bottle are symlinks to the Mac home folders, so the saves are at
`~/Documents/My Games/Skyrim Special Edition`. Check yours with `ls -l <bottle>/drive_c/users/crossover/`.

Also protect, by adding them to your preferences in `KNOWLEDGEBASE.local.md`: the live MO2 instance (`mods/`,
`profiles/`, `overwrite/`), the pristine game folder, and your downloads folder. Read-only rule from the notes:
build and package inside the workspace, never deploy into the live MO2 instance.

Smaller Mac rough edges from the same run (**measured today**), none of them blocking:
- The install hints print `winget install ...` commands, which do not exist on macOS. Use Homebrew or the vendor
  installer for Python, .NET and a JDK.
- Before this fork's fix, `setup.sh` printed "Found Java" for macOS's `java` stub even with no JDK installed.
- It prefers `/usr/bin/python3` (Xcode, 3.9). Put a tested Python first on `PATH` and rerun setup to use it.

## 4. How Wine sees your files (**notes**)

Windows tools inside the bottle see the Mac filesystem through drive links, not Mac paths:

| In the bottle | Is |
|---|---|
| `D:` (in the maintainer's bottle) | the external volume holding the Windows tree (`/Volumes/<disk>/Windows`) |
| `Y:` | the Mac home folder |
| `Z:` | the Mac root `/` |
| `C:` | `drive_c` |

A tool started from `/Volumes/<disk>/Projects/...` logs its own path as `Z:\Volumes\<disk>\Projects\...`.

MO2 keeps its default instance data under `C:\users\crossover\AppData\Local\ModOrganizer\<Instance>\`. A Windows tool
that looks there finds only `ModOrganizer.ini`, caches and logs, because the real `mods` and `profiles` are on the
external volume. Symlink both so a read-only analysis tool can see them:

```bash
ln -s "<volume>/Windows/Modding/<Instance>/mods"     "<bottle>/drive_c/users/crossover/AppData/Local/ModOrganizer/<Instance>/mods"
ln -s "<volume>/Windows/Modding/<Instance>/profiles" "<bottle>/drive_c/users/crossover/AppData/Local/ModOrganizer/<Instance>/profiles"
```

The links live in the bottle, not in a repo, so recreate them on a new bottle. They point at the protected live
instance: use them for tools that only read. A tool that writes through them writes to your real mods.

Do not run `.bat` files natively on macOS. Use the equivalent Unix command or a Python script.

## 5. Known Wine/CrossOver failures and fixes (**notes**)

| App / symptom | Cause | Fix |
|---|---|---|
| Game start: `D3D11CreateDeviceAndSwapChain failed: 0x80070057` (`E_INVALIDARG`), raised by SSE Display Tweaks | `SkyrimPrefs.ini` has `bFull Screen=1` together with `bBorderless=1`, or the flip-discard swap effect that Wine/DXVK cannot present, or a stale Wine display session | `SkyrimPrefs.ini [Display]`: `bFull Screen=0`, `bBorderless=1`. `SSEDisplayTweaks.ini [Render]`: `Fullscreen=false`, `Borderless=true`, `SwapEffect=discard`. Then CrossOver: **Bottle > Restart Bottle** |
| LOOT 0.29.x: crash or no window on start | LOOT sets the Qt style before `QApplication` exists; null platform pointer inside Qt6Gui. Also a missing `icuuc.dll` in the 0.29.2 package. Qt's RHI may fail on MoltenVK | Prefer MO2's built-in sort: it calls the headless `lootcli.exe`, which avoids Qt entirely. Otherwise use a LOOT build with the style call moved after `QApplication` and `QSG_RHI_BACKEND=software` |
| MO2 2.5.x crashes on any HTTPS call (Nexus sync, downloads) inside `ntdll` | Qt6 picks its OpenSSL backend, whose init faults under Wine on Apple Silicon | Rename `dlls/tls/qopensslbackend.dll` and the loose `libssl-3-x64.dll` / `libcrypto-3-x64.dll` to `*.disabled`; Qt falls back to Schannel |
| MO2 2.5.2 crashes building the plugin pane | `bsplugins.dll` (built for MO2 2.5.0) calls into changed internals | Rename `plugins/bsplugins.dll` to `.disabled`; MO2's built-in plugin list is stable |
| BodySlide / Outfit Studio: `OpenGL context is not OK` | macOS only gives forward-compatible 3.2+ core contexts; BodySlide requests one without the forward-compatible bit | Source fix: add `.ForwardCompatible()` to the context attributes and skip `glShadeModel` on Apple. Build via the project's CI or cross-compile (section 7) |
| Wabbajack (Avalonia): GUI "does nothing" | `winewrapper --new-console` stays resident; orphaned single-instance mutex; slow first network calls behind a host firewall; Wine has no storage WMI classes (`KeyNotFoundException 'C'`) | Launch with CrossOver's `wine` directly (section 6); kill leftover `winewrapper`/app processes before relaunch; use `wabbajack-cli.exe` for automation |

Details such as the exact byte patches for LOOT 0.29.2 binaries belong to that release only. Take them from the
maintainer's notes if you need them; do not apply them to another version.

## 6. Running a Windows tool in the bottle from the Mac shell (**notes**)

Launching from the CrossOver GUI wraps the app in `winewrapper.exe`, which can hang. Calling Wine directly avoids it:

```bash
CX_BOTTLE="<bottle>" CX_BOTTLE_PATH="$HOME/Bottles" \
"/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine" \
  --bottle "<bottle>" --no-convert 'D:\Path\To\Tool.exe' <args>
```

Use a Windows-style path for the executable. Check for leftovers first: `ps -ef | grep -E -i "winewrapper|<tool>"`.
Prefer a tool's CLI over its GUI under Wine whenever one exists.

## 7. Building Windows tools from the Mac (**notes**)

Windows `.exe` tools can be cross-compiled on macOS with `clang-cl` + `lld-link` against a Windows SDK/CRT sysroot
from `xwin`, using a vcpkg triplet that forces pure Windows mode and a static runtime (`/MT`). Traps seen:

- vcpkg's `opengl` port queries the Windows registry; patch it to use the sysroot's `OpenGL32.Lib`.
- `llvm-rc` rejects UTF-16 `.rc` files: `iconv -f UTF-16LE -t UTF-8`.
- Host detection leaks (`APPLE` true) make wxWidgets add `OBJCXX`; guard it with `NOT CMAKE_SYSTEM_NAME STREQUAL "Windows"`.
- A transitive port can add `/MD`; force `/MT` for every port or the link fails with `/failifmismatch RuntimeLibrary`.
- .NET tools: `dotnet publish -c Release -r win-x64 --self-contained`.

SKSE plugin cross-compiling has its own page (`skse-cross-compile.md`, written for Linux, and unvalidated).

## 8. Not covered / still to verify

- Whether `XEditLib`-based tools can be driven from the Mac at all, e.g. by running them under CrossOver's `wine`.
- Caprica, Champollion, Spriggit and AutoMod on macOS; DevBench reachability from the Mac side.
- A macOS test run of the toolkit's own suite: many tests assume Git Bash and Windows paths (145 failures in the five
  hook/setup suites, identical to the upstream commit, on Python 3.15).
- Anything about CrossOver versions other than the maintainer's.
