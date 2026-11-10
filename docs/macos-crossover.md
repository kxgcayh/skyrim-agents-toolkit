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
| `caprica` | macOS, natively | **Measured 2026-11-04**: built from the kxgcayh/Caprica fork (commit d8f7064, see `installing-tools.md`); compiles a `.psc` to a valid `.pex`. No CrossOver needed. The older CrossOver route for `Caprica.exe` is in `papyrus-caprica-crossover.md` |
| `champollion` | macOS, natively | **Measured 2026-11-04**: built from the kxgcayh/Champollion fork (commit 23e947a, see `installing-tools.md`); `champollion --version` prints v1.3.2. No CrossOver needed |
| Spriggit 0.41.0 | macOS, natively, **but not through the CLI** | **Measured 2026-11-04**: `spriggit serialize` fails (`Win32Exception (2)`: it tries to start `Spriggit.Yaml.Skyrim.exe` from `$TMPDIR/Spriggit/Translations/...`); the CLI's deserialize failed 2026-10-28 with `DllNotFoundException: kernel32.dll` from Noggog's `ChildProcessTracker`. Calling the translation DLL directly skips both: `dotnet "$TMPDIR/Spriggit/Translations/Spriggit.Yaml.Skyrim/0.41.0/.store/spriggit.yaml.skyrim/0.41.0/spriggit.yaml.skyrim/0.41.0/tools/net10.0/any/Spriggit.Yaml.Skyrim.dll" serialize -i <esp> -o <dir> -g SkyrimSE -p Spriggit.Yaml.Skyrim -v 0.41.0` (and `deserialize -i <dir> -o <esp>`); a round trip of `tests/fixtures/spriggit/FixLimitsRoundTrip.esp` came back byte-identical. The folder appears after one CLI run. `tools/spriggit-cli.sh` does this itself on macOS since 2026-11-09 (finds the DLL under `~/.nuget/packages/spriggit.yaml.skyrim` or `$TMPDIR/Spriggit/Translations`, or `SPRIGGIT_DLL`; runs one CLI call to unpack it if missing): serialize then deserialize of the fixture came back byte-identical through the wrapper. The no-path forms (`--help`, `--version`) still use the CLI. If `tools/Spriggit/publish/Spriggit.CLI` exists (a local build of the `kxgcayh/Spriggit` `audit-fixes` fork, git-ignored, never shipped) the wrapper uses it instead and the CLI runs natively on macOS; measured 2026-11-09, fixture round trip byte-identical, `dotnet test Spriggit.Tests` 137 passed |
| AutoMod CLI (`nif` module) | .NET 10 natively; its `nif-tool.exe` through CrossOver's `wine` | **Measured 2026-11-05**: `bash tools/automod-cli.sh --rebuild` builds v1.11.2 for net10.0 (on a Mac .NET 10 SDK one patch newer than the pinned 10.0.401); `nif info` runs natively. `nif list-textures`, `list-strings`, `shader-info` and `verify` call `tools/automod/tools/nif-tool/nif-tool.exe`, a Windows PE, so put the real binary there as `nif-tool-win.exe` and make `nif-tool.exe` an executable bash shim that runs `"$CX/bin/wine" --bottle SkyGames --no-convert -- "$(dirname "$0")/nif-tool-win.exe" "$@"` (with `CX_BOTTLE_PATH="$HOME/Bottles"`, `WINEDEBUG=-all`). Unix paths in the arguments resolve through Wine's `Z:` drive; about 0.5 s per call. All four commands worked on SSE meshes. Other AutoMod modules not tried |
| ReSaver CLI | Java | **Inferred**: needs a real JDK 17+ on the Mac |
| DevBench (live in-game) | inside the game, in the bottle | **Measured** 2026-11-05: 1.32.0 loads on AE 1.7.104 under CrossOver, and wineserver listens on 127.0.0.1:8920, reachable from macOS with no setup |
| Mod Organizer 2, LOOT, BodySlide, Wabbajack | Windows apps in the bottle | **Measured (notes)**: they run, with the fixes in section 5 and the pages it links |

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

More about the bottle, all **Measured (notes)**:

- `drive_c/users/crossover/{Documents,Downloads,Music,Pictures,Videos}` are symlinks to the matching Mac home folders.
- A tool that locates MO2 data through `...\AppData\Local\ModOrganizer\<Instance>\` finds there only
  `ModOrganizer.ini`, `categories.dat`, `nexuscatmap.dat`, `logs/` and `crashDumps/`. That is why the two symlinks above
  are needed.
- **MO2's virtual filesystem (USVFS)** is `usvfs_x64.dll`: it intercepts Win32 file calls (`CreateFileW`,
  `FindFirstFileW`) and redirects `Data/` to `mods/<ModName>/`. Paths must respect Wine's casing. A file you change in
  the real game folder is overridden by MO2 if the same relative path exists in `mods/` or `overwrite/`; inspect the
  profile's `modlist.txt`, not the game folder.
- **Profile-specific INIs.** Each MO2 profile can hold its own `skyrimprefs.ini` (and `skyrim.ini`) next to
  `modlist.txt` and `plugins.txt`. When the profile uses local INIs, those, not the ones under `My Games`, are what
  the game reads. Check the profile before you advise an INI change (INI hierarchy: `CLAUDE.md`).
- **Verified read-only use** (2026-10-15): Radium Textures, a Rust/iced Windows GUI that optimizes textures, loaded the
  MO2 profile `...\ModOrganizer\SSEAE\profiles\Overhaul 1.4` through those symlinks: 1128 mods, 863 enabled, 61596 VFS
  file entries, 10579 loose textures, 544 BSAs, 31121 BSA textures. Its `wgpu` DXGI factory logs
  `create_factory_media failed: 0x80004002` under Wine; that is harmless and the GUI proceeds.

## 5. Known Wine/CrossOver failures and fixes (**notes**)

Each row has a full page with the root cause and the fix: `crossover-d3d11-swapchain.md`, `crossover-loot-and-qt6.md`
(LOOT, the MO2 TLS crash and `bsplugins.dll`), `crossover-bodyslide-opengl.md`, and section 9 of
`windows-exe-cross-compile-macos.md` (Wabbajack).

| App / symptom | Cause | Fix |
|---|---|---|
| Game start: `D3D11CreateDeviceAndSwapChain failed: 0x80070057` (`E_INVALIDARG`), raised by SSE Display Tweaks | `SkyrimPrefs.ini` has `bFull Screen=1` together with `bBorderless=1`, or the flip-discard swap effect that Wine/DXVK cannot present, or a stale Wine display session | `SkyrimPrefs.ini [Display]`: `bFull Screen=0`, `bBorderless=1`. `SSEDisplayTweaks.ini [Render]`: `Fullscreen=false`, `Borderless=true`, `SwapEffect=discard`. Then CrossOver: **Bottle > Restart Bottle** |
| LOOT 0.29.x: crash or no window on start | LOOT sets the Qt style before `QApplication` exists; null platform pointer inside Qt6Gui. Also a missing `icuuc.dll` in the 0.29.2 package. Qt's RHI may fail on MoltenVK | Prefer MO2's built-in sort: it calls the headless `lootcli.exe`, which avoids Qt entirely. Otherwise use a LOOT build with the style call moved after `QApplication` and `QSG_RHI_BACKEND=software` |
| MO2 2.5.x crashes on any HTTPS call (Nexus sync, downloads) inside `ntdll` | Qt6 picks its OpenSSL backend, whose init faults under Wine on Apple Silicon | Rename `dlls/tls/qopensslbackend.dll` and the loose `libssl-3-x64.dll` / `libcrypto-3-x64.dll` to `*.disabled`; Qt falls back to Schannel |
| MO2 2.5.2 crashes building the plugin pane | `bsplugins.dll` (built for MO2 2.5.0) calls into changed internals | Rename `plugins/bsplugins.dll` to `.disabled`; MO2's built-in plugin list is stable |
| BodySlide / Outfit Studio: `OpenGL context is not OK` | macOS only gives forward-compatible 3.2+ core contexts; BodySlide requests one without the forward-compatible bit | Source fix: add `.ForwardCompatible()` to the context attributes and skip `glShadeModel` on Apple. Build via the project's CI or cross-compile (section 7) |
| Wabbajack (Avalonia): GUI "does nothing" | `winewrapper --new-console` stays resident; orphaned single-instance mutex; slow first network calls behind a host firewall; Wine has no storage WMI classes (`KeyNotFoundException 'C'`) | Launch with CrossOver's `wine` directly (section 6); kill leftover `winewrapper`/app processes before relaunch; use `wabbajack-cli.exe` for automation |
| WPF apps (Synthesis, etc.): black/empty window | WPF renders via D3D9; DXVK/MoltenVK hardware acceleration produces an empty client area | In the bottle's Regedit: create `HKEY_CURRENT_USER\Software\Microsoft\Avalon.Graphics` → DWORD `DisableHWAcceleration` = `1`. Forces software rasterization. **Measured today.** |
| MO2 "Open in Explorer" on a folder opens Wine's own file window | MO2 calls `ShellExecuteEx` with the `explore` verb on the directory (`uibase/src/utility.cpp`), and Wine's `Folder` class has no `explore` command | In the bottle (`CX_BOTTLE_PATH="$HOME/Bottles"`): `wine --bottle <bottle> reg add 'HKLM\Software\Classes\Folder\shell\explore\command' /ve /d 'C:\windows\system32\winebrowser.exe "%1"' /f`. Folders now open in Finder. **Measured with a test exe in the bottle, not from inside MO2.** Put it in `HKLM`: the same key in `HKCU\Software\Classes` is not merged and is ignored. A file's "show in folder" runs `explorer /select,"<path>"` and is not covered; a registry key cannot intercept it |
| VRAMr v16.0310 (Nexus 90557): `script.bat` stops at the first prompt or folder dialog | The bottle has no `powershell.exe`, `choice.exe` or `mode.com`; `script.bat` uses them for GPU detection, every prompt and every folder picker. Its seven worker exes (`LayerPrep`, `BSA`, `Loose`, `Exclude`, `Filter`, `Extract`, `Optimise`) are plain CLIs and run under Wine, and `texconv -gpu 0` encodes BC7 on the GPU through DirectCompute (512² in 1.5 s; `-nogpu` 15 s) | `tools/vramr-crossover.cmd` runs the same exes with the same arguments using `set /p` prompts. Add it in MO2 as an executable: binary `C:\windows\system32\cmd.exe`, arguments `/c ""Z:\<toolkit>\tools\vramr-crossover.cmd" O D:\ "<MO2 profile folder>""` (preset `H\|Q\|O\|P\|V`, or `C <diffuse> <normal> <parallax> <material>` for custom resolutions), start in `<game>\Data`, so the exes see the virtual Data. The doubled outer quotes are required: `cmd /c` strips the first and last quote when the line holds more than two, and with single outer quotes nothing runs and nothing is logged. One MO2 executable per preset gives the preset menu, since Wine shows no console window for it. **Measured from MO2** on a 629-mod profile (preset O): 82 mod BSAs indexed, 3121 textures, 3040 converted, 81 failed with `Access denied (os error 5)` when `Optimise.exe` started texconv (left as the extracted originals), 14 min. Not reproduced with 400 textures, inside or outside MO2 (USVFS logged every successful texconv start, and nothing for the failed ones); cause unknown. The script therefore retries only the failed files after Optimise (up to 3 passes, via VRAMr's own `Loose.exe` + `Optimise.exe` in a separate folder, so nothing is encoded twice), and `R <preset> <output root>` retries an existing output without MO2: on that run, all 81 converted on the first retry. **Measured in the bottle, outside MO2**, on a scratch Data: 4096² BC1 diffuse and normal became 2048² and 1024² BC7 (preset O); a 111-file mod BSA was indexed (all filtered out, so extraction from a BSA was not exercised). Needs MO2's `usvfs_x64.dll` 0.5.7.2+ (0.5.7.1 corrupts directory listings) |
| Dynamic Interface Patcher 2.1.5 (Nexus 96891): does it run at all? | It does, unchanged: a frozen Python 3.12 + PySide6 app that unpacks its bundled Windows JRE (`jre.7z`, Java 21.0.3) to `C:\users\crossover\AppData\Local\Temp\DIP_*` and runs FFDec with it. No wrapper is needed, unlike VRAMr | **Launched from MO2 2.5.3-beta.12 it does not run**: USVFS 0.5.7.2 injects into `DIP.exe` (twice, two PIDs) and both exit with no window, no `DIP.log` and no crash dump. stderr (MO2 executable `cmd.exe /c ""<DIP.exe>" > <file> 2>&1"`) shows `ImportError: C:\windows\system32\shiboken6\libshiboken does not exist`, raised from `PySide6\__init__.py`, with every module path reading `\u6f68\u6b6f...W\main.py`: UTF-16 garbage that decodes to the ASCII string `hook_FindFirstFileExW`. The frozen app's own exe path (from `GetModuleFileNameW`, which usvfs hooks) comes back as a usvfs symbol name, so PySide6 falls back to `system32`. Root cause inside usvfs under Wine not traced. Run it outside MO2 instead, on the real mod folder: `wine --bottle <bottle> --no-convert 'D:\...\DIP\DIP.exe' -s -o '<output>' '<patch folder>' '<original mod folder or folder holding the BSA>'` (Wine passes each argument intact; measured). CLI: `DIP.exe -s [-d] -o <output> <patch> <original>`. Do not wrap it in `cmd /c "..."` from the Mac shell: the nested quotes break and argparse rejects the last path. DIP writes `DIP.log`, and with `-d` the patched XMLs, next to its exe, so under MO2 they land in `overwrite/`. Without `-o` it writes into the original mod folder. **Measured in the bottle, outside MO2** (copy of DIP, upstream's example RaceMenu patch, a copy of RaceMenu AE's `RaceMenu.bsa`): BSA read, both SWFs through FFDec swf2xml/xml2swf, 2 patched `CWS` v10 SWFs written, 16 s, rc 0. The GUI window also renders. Not yet exercised: a run from MO2 through USVFS, shape (SVG) patching (the example ships no SVG), `--repack-bsa`. **In game:** the "RaceMenu - Untarnished UI" DIP patch (Nexus 97347, v1.4) applied this way to RaceMenu AE 0.5.0.0 b6 works (user confirmed, 2026-11-02) |

The exact byte patches for the LOOT 0.29.2 binaries are in `crossover-loot-and-qt6.md` section 3. They belong to that
release only; do not apply them to another version.

## 6. Running a Windows tool in the bottle from the Mac shell (**notes**)

Launching from the CrossOver GUI wraps the app in `winewrapper.exe`, which can hang. Calling Wine directly avoids it:

```bash
CX_BOTTLE="<bottle>" CX_BOTTLE_PATH="$HOME/Bottles" \
"/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine" \
  --bottle "<bottle>" --no-convert 'D:\Path\To\Tool.exe' <args>
```

Use a Windows-style path for the executable. Check for leftovers first: `ps -ef | grep -E -i "winewrapper|<tool>"`.
Prefer a tool's CLI over its GUI under Wine whenever one exists.
A tool outside the `D:` drive, or one that exits with no output, needs the launch form and the debug variable in
`crossover-loot-and-qt6.md` section 7.1.

Traps hit while doing this (2026-11-01):

- **zsh does not word-split `$var`.** `$args` holding `-gpu 0` reaches the exe as ONE argument; texconv then silently
  does nothing. Use an array (`args=(-gpu 0)`, `"${args[@]}"`).
- **`cmd /c` with more than two quotes** drops its first and last quote and runs nothing, silently (Windows does the same).
  Wrap the whole command once more: `/c ""<script>" <args> "<quoted arg>""`. Several quoted paths in one `cmd /c "..."`
  from the Mac shell also break the quoting; write a `.cmd` file and run that.
- **MO2 executables: "Start in" and "Arguments" swapped** gives `Error 267 ERROR_DIRECTORY` with `cwd` = the command text.
  MO2 writes executables to `ModOrganizer.ini` later, not on OK, so verify by reopening Modify Executables, not the ini.
- **No console window.** cmd started from MO2 or via `start` shows none in the bottle, and there is no wineconsole,
  cscript, wscript or mshta: an interactive menu has to become one MO2 executable per choice.
- **Computer-use on a CrossOver window:** typing turns every character into "a" and `ctrl+v` does nothing. Write the
  clipboard, wait about 2 s (or the old clipboard pastes), triple-click the field, then `cmd+v` (CrossOver maps Cmd to Ctrl).

### The same from an MCP client: `tools/crossover-mcp.py`

A stdio MCP server, standard library only, for clients without a shell. Tools: `list_bottles`, `run` (exit code
and output; `wait=false` for GUI apps), `stop_bottle` (`wineserver -k`, every process in the bottle), `launch_mo2`,
`mo2_log` and `screenshot`. Register it with, for Claude Code:

```bash
claude mcp add crossover -e CX_BOTTLE=<bottle> -e CX_BOTTLE_PATH="$HOME/Bottles" -e 'CX_MO2_DIR=D:\Modding\MO2' \
  -- python3 "$PWD/tools/crossover-mcp.py"
```

`launch_mo2` starts a portable MO2 folder (one with `portable.txt`) freely. A folder without it opens a global
instance, which is the live mod setup, and starts only when the call passes `live=true`. Optional `instance` (`-i`),
`profile` (`-p`) and `executable` (an MO2 executable entry, run through the virtual file system as `moshortcut://`).
`dry_run=true` returns the exact `wine` command and whether the folder is live, and starts nothing. `screenshot`
returns the screen as an image (to check a Wine window opened) and deletes the file before returning; it needs Screen
Recording permission for the app that runs the server.
Measured 2026-11-05: `run`, `stop_bottle`, the live refusal, `mo2_log`, a detached launch from a portable stand-in
folder, and a live launch (`live=true`): MO2 2.5.3-beta.12 opened its window on `SSEAE`, profile `Overhaul 1.1`.

## 7. Building Windows tools from the Mac (**notes**)

Windows `.exe` tools can be cross-compiled on macOS with `clang-cl` + `lld-link` against a Windows SDK/CRT sysroot
from `xwin`, using a vcpkg triplet that forces pure Windows mode and a static runtime (`/MT`). Traps seen:

- vcpkg's `opengl` port queries the Windows registry; patch it to use the sysroot's `OpenGL32.Lib`.
- `llvm-rc` rejects UTF-16 `.rc` files: `iconv -f UTF-16LE -t UTF-8`.
- Host detection leaks (`APPLE` true) make wxWidgets add `OBJCXX`; guard it with `NOT CMAKE_SYSTEM_NAME STREQUAL "Windows"`.
- A transitive port can add `/MD`; force `/MT` for every port or the link fails with `/failifmismatch RuntimeLibrary`.
- .NET tools: `dotnet publish -c Release -r win-x64 --self-contained`.

Full pipelines: `windows-exe-cross-compile-macos.md` for `.exe` tools and `skse-cross-compile-macos.md` for SKSE plugin
DLLs. `skse-cross-compile.md` is the Linux/devcontainer variant, written for Linux and unvalidated.

## 8. Not covered / still to verify

- Whether `XEditLib`-based tools can be driven from the Mac at all, e.g. by running them under CrossOver's `wine`.
- AutoMod modules other than `nif`; DevBench reachability from the Mac side. (Champollion, Caprica, Spriggit and AutoMod
  `nif` are measured in section 1;
  the Synthesis WPF black-window fix is in section 5.)
- A macOS test run of the toolkit's own suite: many tests assume Git Bash and Windows paths (145 failures in the five
  hook/setup suites, identical to the upstream commit, on Python 3.15).
- Anything about CrossOver versions other than the maintainer's.
