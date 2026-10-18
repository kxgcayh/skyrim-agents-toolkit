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
