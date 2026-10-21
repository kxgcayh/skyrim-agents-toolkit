# CrossOver: LOOT and other Qt 6 apps (start crash, TLS crash, MO2 plugin ABI)

Why **LOOT 0.29.x** and **Mod Organizer 2 2.5.x** crash or show no window under CrossOver on Apple Silicon, and what to
change. Read it when a Qt 6 tool dies at start, when MO2 dies on its first HTTPS call, or when MO2 2.5.2 dies building
its plugin pane. The one-line version of each is in the table in section 5 of `macos-crossover.md`.

Tags are those of `macos-crossover.md`. Everything here is **Measured (notes)**: found by disassembly and Wine
backtraces on the maintainer's setup (LOOT 0.29.1 and 0.29.2, MO2 2.5.2, CrossOver bottle on Apple Silicon), carried
over from earlier notes, not re-run for this page. The byte patches in section 3 belong to **one release** and must not
be applied to another.

## 1. LOOT: why it dies on start

### 1.1 Qt style set before `QApplication` exists (primary cause)

`src/gui/qt/main.cpp` (introduced upstream in LOOT commits `d23444c` / `3654002`) did, on Windows:

```cpp
auto overrideDefaultStyle = QStyleFactory::create("fusion");   // before QApplication exists
if (overrideDefaultStyle) { QApplication::setStyle(overrideDefaultStyle); }
QApplication app(argc, argv);
```

1. `QStyleFactory::create("fusion")` asks the platform theme plugin (`qwindows.dll`) for style metrics.
2. `QApplication` does not exist yet, so `QGuiApplicationPrivate::platformIntegration()` returns `nullptr`.
3. In `Qt6Gui.dll` (RVA `0x6b39f`, `QPixmap` initialization) the code loads that pointer and dereferences it:

   ```asm
   mov rcx, [rip + 0x84b78e]    ; platform integration pointer = NULL
   mov edx, 1
   mov rax, [rcx]               ; null dereference
   ```
4. Native Windows tolerates this early state. Wine raises `Unhandled page fault on read access to 0000000000000000`
   and the process ends before any window appears.

### 1.2 Missing ICU forwarder (secondary)

The `icuuc.dll` shipped with LOOT 0.29.x forwards to the unified `icu.dll` of Windows 10 1903+. CrossOver's bottle does
not provide it:

```
err:module:find_forwarded_export module not found for forward 'icu.ucnv_open' used by icuuc.dll
```

### 1.3 Qt 6 RHI over Direct3D 11 and MoltenVK (tertiary)

Qt 6's rendering layer negotiates DXGI swapchain surfaces over Wine's virtual desktop. MoltenVK on Apple Silicon can
fail to create the Vulkan surface capabilities silently, so a hardware swapchain may never come up.

## 2. LOOT: fix by rebuilding

Create the `QApplication` first, set the style after it, and force the software backend. This changes only
`main()` and loses no GUI or sorting feature:

```cpp
int main(int argc, char* argv[]) {
#ifdef _WIN32
  if (loot::isApplicationMutexLocked()) {
    HWND hWnd = ::FindWindow(nullptr, L"LOOT");
    ::SetForegroundWindow(hWnd);
    return 0;
  }
  qputenv("QSG_RHI_BACKEND", "software");     // renders reliably over Wine/MoltenVK
  qputenv("QT_QUICK_BACKEND", "software");
#endif

  loot::ApplicationMutexGuard mutexGuard;
  QApplication app(argc, argv);               // first

#ifdef _WIN32
  auto overrideDefaultStyle = QStyleFactory::create("fusion");   // after
  if (overrideDefaultStyle) { QApplication::setStyle(overrideDefaultStyle); }
#endif
  QCommandLineParser parser;
  // ... rest unchanged
```

Building a Windows Qt app from the Mac: `windows-exe-cross-compile-macos.md`.

## 3. LOOT 0.29.2 release package: binary patch (this release only)

For the official package `loot_0.29.2-0-g0402143_0.29.2` when you do not rebuild.

| Step | What | Detail |
|---|---|---|
| Missing DLL | `icuuc.dll` is absent from the 0.29.2 package; `Qt6Core.dll` needs it (`STATUS_DLL_NOT_FOUND`, `0xc0000135`) | Copy `icuuc.dll` from the LOOT 0.29.1 folder into the 0.29.2 folder |
| `LOOT.exe` | The early `setStyle` call is at file offset `0x2a75d` (`48 85 ff 74 09`) | Change the `je` byte `0x74` to `jmp` `0xeb` at offset `0x2a760` |
| `Qt6Gui.dll` | The `QPixmap` platform-integration check is at offset `0x6d807` (`48 83 3d ... 74 4a`) | Change the `je` byte `0x74` to `jmp` `0xeb` at offset `0x6d807` |

With both one-byte patches and `icuuc.dll` present, `LOOT.exe` starts under CrossOver, shows the First-Time Tips modal
(582x272) and then the main window (1030x787).

Offsets are file offsets in those exact binaries. Before you patch, check that the bytes at the offset match the
pattern given, and use the method of `binary-patcher-guide.md` (backup, hash before and after). LOOT is open source, so
the licensing question of `licensing-and-delta-patching.md` does not stop a rebuild.

## 4. No rebuild at all: `lootcli`

When you only need a sorted load order, skip the GUI. MO2 ships a headless `loot/lootcli.exe` that uses `libloot.dll`
directly, which avoids Qt 6 and the Wine GUI path. MO2's own **Sort** button calls it, so sorting from MO2 works
without a working LOOT window.

## 5. MO2 2.5.x: HTTPS crashes in `ntdll` (TLS backend)

**Symptom.** MO2 2.5.x dies on the first HTTPS call (Nexus sync, update check, download validation). The backtrace runs
`ntdll` <- `libssl-3-x64` <- `qopensslbackend` <- `qt6network` <- `modorganizer`.

**Cause.** Qt 6 loads TLS backends from `dlls/tls/`: `qopensslbackend.dll` (OpenSSL 3 via `libssl-3-x64.dll` and
`libcrypto-3-x64.dll`), `qschannelbackend.dll` (Windows Secure Channel) and `qcertonlybackend.dll`. If the OpenSSL
backend and its libraries are present, Qt prefers them. Under Wine on Apple Silicon (Rosetta 2), OpenSSL 3's start-up
(`OPENSSL_init_ssl`) does thread synchronization and CPU-feature probes that fault inside Wine's `ntdll.dll`.

**Fix.** Make Qt fall back to Schannel, which Wine backs with macOS SecureTransport / GnuTLS:

1. Rename `dlls/tls/qopensslbackend.dll` to `qopensslbackend.dll.disabled`.
2. Disable the loose OpenSSL 3 binaries (`libcrypto-3-x64.dll`, `libssl-3-x64.dll`) in the application root and `dlls/`.

## 6. MO2 2.5.2: crash building the plugin pane (`bsplugins.dll`)

**Symptom.** MO2 2.5.2 with the Bethesda Plugin Manager (`bsplugins.dll`, built for MO2 2.5.0) dies as soon as it builds
the right-hand plugin pane; the backtrace is `qt6core` <- `bsplugins` <- `modorganizer`.

**Cause.** `bsplugins.dll` hooks MO2's internal C++ plugin model classes in `uibase.dll`. Struct layouts and Qt 6
object bindings changed between 2.5.0 and 2.5.2, so calls across that ABI hit a null or invalid pointer in `Qt6Core`.

**Fix.** Disable the plugin; MO2 falls back to its built-in plugin list, which is stable on 2.5.2:

```bash
mv "<mo2-dir>/plugins/bsplugins.dll" "<mo2-dir>/plugins/bsplugins.dll.disabled"
```

This is a change inside the user's live MO2 install. State it to the user first, and keep it to the `plugins/` folder;
the guards protect `mods/` and `overwrite/` and any rename away from the install.

## 7. Self-built MO2 (Qt 6.11+): exits with code 53 and no window (`icuuc.dll` not in `dlls.manifest`)

Tag: **Measured** (CrossOver on Apple Silicon, bottle `SkyGames`, a portable MO2 folder holding a
cross-compiled `ModOrganizer.exe`, `uibase.dll`, `archive.dll` and Qt 6.11.x DLLs in `dlls/`).

**Symptom.** `ModOrganizer.exe` exits with code 53 after about 1.4 s. No window, no `logs/`, no `ModOrganizer.ini`. The
previous build of the same exe exits the same way, so a new build is not the cause.

**Cause.** Modern Qt 6 builds (such as Qt 6.11.x) import `icuuc.dll` in `Qt6Core.dll` (earlier builds did not). The exe resolves
everything in `dlls/` through its embedded `dependentAssembly` named `dlls`, which is `dlls/dlls.manifest`. When that file does
not list `icuuc.dll`, Wine looks for it nowhere (`looking for L"icuuc.dll" in (null)`, status `c0000135`) and every
Qt DLL above `Qt6Core` failed in turn:

```
warn:module:load_dll Failed to load module L"icuuc.dll"; status=c0000135
err:module:import_dll Library icuuc.dll (which is needed by L"...\dlls\Qt6Core.dll") not found
err:module:import_dll Library Qt6Core.dll (which is needed by L"...\dlls\Qt6Network.dll") not found
```

**Fix.** Add one line to `dlls/dlls.manifest`, inside `<assembly>`, next to the other `<file>` entries:

```xml
<file name="icuuc.dll" />
```

Every DLL the exe loads from `dlls/` must be listed in that file. After the edit MO2 starts, loads its plugins and
writes `logs/mo_interface.log`. On a fresh portable folder it then reports
`Cannot open instance 'Portable', the managed game was not found in the INI file`, which is the normal first-run state.

**`icu.dll` forwards.** `icuuc.dll` forwards its exports to `icu.dll` (the Windows 10 1903+ unified ICU), which the
bottle does not have. Without it startup logs 20 `find_forwarded_export module not found for forward 'icu.*'` errors.
They are not fatal at startup. **Measured today**: `Qt6Core.dll` imports exactly 20 ICU symbols, all converters
(`ucnv_open`, `ucnv_close`, `ucnv_reset`, `ucnv_getMaxCharSize`, `ucnv_getName`, `ucnv_getStandardName`,
`ucnv_countAvailable`, `ucnv_getAvailableName`, `ucnv_toUnicode`, `ucnv_fromUnicode`, `ucnv_to/fromUCountPending`,
`ucnv_get/setToUCallBack`, `ucnv_get/setFromUCallBack`, `ucnv_cbToUWriteUChars`, `ucnv_cbFromUWriteUChars`,
`UCNV_TO_U_CALLBACK_SUBSTITUTE`, `UCNV_FROM_U_CALLBACK_SUBSTITUTE`). Shim: a freestanding `icu.dll` (no CRT, no imports)
exporting those 20, where `ucnv_open` and `ucnv_getStandardName` set `U_MISSING_RESOURCE_ERROR` and return `NULL`, so Qt
sees "no ICU converters" and keeps its built-in codecs. Source and build line:
`<mo2-build>/icu-shim/icu_shim.c`;
`clang --target=x86_64-pc-windows-msvc -O2 -ffreestanding -fno-stack-protector -c icu_shim.c` then
`lld-link /dll /noentry /nodefaultlib /machine:x64 /out:icu.dll icu_shim.obj`. Put `icu.dll` in `dlls/` and add
`<file name="icu.dll" />` to `dlls.manifest`. Result: 0 forward errors, `icu.dll` loaded, MO2 still runs. **Not tested**:
anything that needs a legacy (non-UTF) text encoding or collation; those would now be unavailable instead of working.

**`QtWebEngineProcess.exe` cannot find `Qt6Core.dll`.** Symptom: `Library Qt6Core.dll (needed by QtWebEngineProcess.exe)
not found`, `status c0000135`, when MO2 spawns the WebEngine helper (embedded browser, Nexus login). The helper sits in the
application root and its embedded manifest has no `dlls` assembly dependency, so the loader never looks in `dlls/`.
Stock MO2 relies on `env::prependToPath(dllsPath)` (`moapplication.cpp:144`) so the child inherits `PATH`. **Measured**: run by hand, the
helper starts when `PATH` contains `dlls/` (exit 3 on bad arguments) and fails (exit 53) without it; when MO2 spawned it the
`PATH` did not reach the child, so Wine could not resolve its DLLs.

**An external `QtWebEngineProcess.exe.manifest` does not help**, because an exe with an embedded manifest ignores it.
**Fix (measured)**: rewrite the embedded manifest in place, replacing the `<trustInfo>` block (214 bytes, `asInvoker` is
the default) with the 172-byte dependency below and padding with spaces to the original 762 bytes, so the PE resource
layout does not change:

```xml
<dependency><dependentAssembly><assemblyIdentity name="dlls" processorArchitecture="x86" version="1.0.0.0" type="win32"></assemblyIdentity></dependentAssembly></dependency>
```

Python 3, run on a copy (keep `QtWebEngineProcess.exe.prev`): find the single `<assembly xmlns=` block, replace the
`<trustInfo>...</trustInfo>` text, assert `len(new) <= len(old)`, pad with spaces, write back. After the patch the helper
run directly with no `PATH` help loads `dlls\Qt6Core.dll` and `Qt6WebEngineCore.dll` and exits 3, with no loader errors.
The `dlls` assembly must list every DLL in the helper's closure; `dlls.manifest` already did. **Not exercised**: a full MO2
run did not spawn the helper this time (no embedded-browser action), so the in-MO2 path is unverified.

### 7.1 Launching from the Mac shell and reading Wine's output

The recipe in `macos-crossover.md` section 6 needs three corrections for a folder outside the bottle's `D:` drive.

```bash
CX_BOTTLE=SkyGames CX_BOTTLE_PATH="$HOME/Bottles" CX_DEBUGMSG="err+all,+loaddll" \
"/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine" --bottle SkyGames --no-convert \
  'C:\windows\system32\cmd.exe' /c 'cd /d Z:\Volumes\<disk>\Projects\<workspace>\mo2-portable && ModOrganizer.exe'
```

- **Drive letters.** In this bottle `Z:` is `/` and `D:` is `/Volumes/<disk>/Windows`. Pick the letter from
  `<bottle>/dosdevices`. A folder under `/Volumes/<disk>/Projects` is only reachable as `Z:\Volumes\<disk>\Projects\...`.
- **Debug output.** `WINEDEBUG` is ignored by the CrossOver wrapper and the log stays empty. Use `CX_DEBUGMSG` with the
  same channel syntax.
- **Working directory.** Start the exe through `cmd /c "cd /d <dir> && <exe>"`. Calling the exe directly, relative or
  absolute, also exited 53 with no output here.
- **Exit code 53 and an empty log** mean the process died in the loader. Rerun with `CX_DEBUGMSG` and search the output
  for `err:module:import_dll` and `c0000135`.
- **No `timeout` on macOS.** Wrap the call in Python `subprocess.run(..., timeout=N)`.
- **Check for leftovers first**, as in section 6: `ps -ef | grep -iE "winewrapper|ModOrganizer"`. A running Steam in the
  same bottle shows up as a `winewrapper.exe` and is not a leftover.
