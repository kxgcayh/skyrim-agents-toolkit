# Cross-compiling Windows `.exe` tools on macOS, and running .NET GUI tools under CrossOver

Build Windows GUI and console programs (BodySlide, Outfit Studio, LOOT-class tools) on a Mac with `clang-cl`,
`lld-link` and vcpkg, then run them in a CrossOver bottle. Section 9 covers the opposite problem: .NET Avalonia tools
(Wabbajack) that start but look hung. Read it with `skse-cross-compile-macos.md`, which has the same toolchain for DLLs;
the short version is section 7 of `macos-crossover.md`.

Tags are those of `macos-crossover.md`. Everything here is **Measured (notes)**: built and run by the maintainer on
Apple Silicon, carried over from earlier notes, not re-run for this page. Paths are placeholders: `<xwin>` is the
sysroot (the notes use `~/.xwin`), `<vcpkg>` the vcpkg checkout, `<bottle>` the CrossOver bottle.

## 1. What differs from a plugin DLL

A GUI tool built on wxWidgets with a 3D view adds problems a plugin does not have:

1. **Resource scripts (`.rc`)** go through `llvm-rc`, not GNU `windres`.
2. **Subsystem and manifest:** `/subsystem:windows`, `/MANIFESTINPUT`, `/MANIFEST:EMBED`.
3. **One CRT everywhere.** Static dependencies need `/MT` (or `/MTd`) in every port, or the link fails with
   `/failifmismatch: mismatch detected for 'RuntimeLibrary'`.
4. **Host detection leaks.** Running CMake on macOS makes checks like `if(APPLE)` fire unless the toolchain scopes them.

## 2. Prerequisites

```bash
brew install llvm cmake ninja nasm pkg-config
cargo install xwin          # or: brew install xwin
```

| Tool | Role |
|---|---|
| `clang-cl` | Clang with MSVC command-line syntax |
| `lld-link` | LLVM linker for PE/COFF |
| `llvm-lib` | replaces `lib.exe` |
| `llvm-rc` | replaces `rc.exe` |
| `nasm` | assembler for the SIMD code in `libjpeg-turbo` |
| `xwin` | downloads and unpacks the Microsoft CRT and Windows SDK |

## 3. Sysroot

```bash
xwin --accept-license 17 splat --output <xwin>
```

For Debug builds, check that the debug runtimes exist: `libcmtd.lib`, `libcpmtd.lib`, `msvcrtd.lib` in
`<xwin>/crt/lib/x86_64`, and `libucrtd.lib` in `<xwin>/sdk/lib/ucrt/x86_64`. Compare `skse-cross-compile-macos.md`
section 3, which uses `--arch x86_64` and a different output folder.

## 4. vcpkg triplet and toolchain

### 4.1 Toolchain file `x64-windows-llvm-toolchain.cmake`

```cmake
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR AMD64)
set(WINSYSROOT "$ENV{HOME}/.xwin")

set(CMAKE_C_COMPILER   "/opt/homebrew/opt/llvm/bin/clang-cl")
set(CMAKE_CXX_COMPILER "/opt/homebrew/opt/llvm/bin/clang-cl")
set(CMAKE_LINKER       "/opt/homebrew/bin/lld-link")
set(CMAKE_AR           "/opt/homebrew/opt/llvm/bin/llvm-lib")
set(CMAKE_RANLIB       "/opt/homebrew/opt/llvm/bin/llvm-ranlib")
set(CMAKE_RC_COMPILER  "/opt/homebrew/opt/llvm/bin/llvm-rc")
set(CMAKE_MT           "/opt/homebrew/opt/llvm/bin/llvm-mt")

set(MSVC_COMMON_FLAGS "--target=x86_64-pc-windows-msvc -msse4.1 -fuse-ld=lld-link -imsvc ${WINSYSROOT}/crt/include -imsvc ${WINSYSROOT}/sdk/include/ucrt -imsvc ${WINSYSROOT}/sdk/include/shared -imsvc ${WINSYSROOT}/sdk/include/um -imsvc ${WINSYSROOT}/sdk/include/winrt /D_CRT_SECURE_NO_WARNINGS /DNOMINMAX")
set(CMAKE_C_FLAGS_INIT   "${MSVC_COMMON_FLAGS}")
set(CMAKE_CXX_FLAGS_INIT "${MSVC_COMMON_FLAGS} /EHsc")
set(CMAKE_RC_FLAGS_INIT  "-I ${WINSYSROOT}/sdk/include/um -I ${WINSYSROOT}/sdk/include/shared -I ${WINSYSROOT}/sdk/include/ucrt -I ${WINSYSROOT}/crt/include")

cmake_policy(SET CMP0091 NEW)
set(CMAKE_POLICY_DEFAULT_CMP0091 NEW)

set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>" CACHE STRING "")
set(CMAKE_C_FLAGS_RELEASE   "/MT /O2 /Ob2 /DNDEBUG"  CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_RELEASE "/MT /O2 /Ob2 /DNDEBUG"  CACHE STRING "" FORCE)
set(CMAKE_C_FLAGS_DEBUG     "/MTd /Zi /Ob0 /Od /RTC1" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_DEBUG   "/MTd /Zi /Ob0 /Od /RTC1" CACHE STRING "" FORCE)

set(MSVC_LINK_DIRS "/LIBPATH:${WINSYSROOT}/crt/lib/x86_64 /LIBPATH:${WINSYSROOT}/sdk/lib/ucrt/x86_64 /LIBPATH:${WINSYSROOT}/sdk/lib/um/x86_64")
set(CMAKE_EXE_LINKER_FLAGS_INIT    "${MSVC_LINK_DIRS}")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${MSVC_LINK_DIRS}")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "${MSVC_LINK_DIRS}")
```

### 4.2 Triplet `x64-windows-llvm.cmake`

```cmake
set(VCPKG_TARGET_ARCHITECTURE x64)
set(VCPKG_CRT_LINKAGE static)
set(VCPKG_LIBRARY_LINKAGE static)

set(VCPKG_C_FLAGS_RELEASE   "/MT")
set(VCPKG_CXX_FLAGS_RELEASE "/MT")
set(VCPKG_C_FLAGS_DEBUG     "/MTd")
set(VCPKG_CXX_FLAGS_DEBUG   "/MTd")

# Unsetting VCPKG_CMAKE_SYSTEM_NAME forces pure Windows mode, so vcpkg does not pull host/Linux
# dependencies such as GTK3, Cairo or gettext.
unset(VCPKG_CMAKE_SYSTEM_NAME)

set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE "${CMAKE_CURRENT_LIST_DIR}/x64-windows-llvm-toolchain.cmake")
```

## 5. Port traps

### 5.1 The `opengl` port wants the Windows registry

`ports/opengl/portfile.cmake` calls `vcpkg_get_windows_sdk`, which reads the registry and fails on a Mac host.
**Fix:** patch the portfile to detect `<xwin>/sdk/lib/um/x86_64/OpenGL32.Lib` and install `GL.h`, `GLU.h`,
`OpenGL32.Lib` and `GlU32.Lib` into the package directory directly.

### 5.2 UTF-16 resource scripts

`llvm-rc` rejects a UTF-16 LE file with a byte-order mark:
`fatal error: UTF-16 (LE) byte order mark detected in 'App.rc', but encoding is not supported`.
**Fix:** convert `.rc` and `resource.h` to UTF-8:

```bash
iconv -f UTF-16LE -t UTF-8 App.rc > App.rc.utf8 && mv App.rc.utf8 App.rc
```

### 5.3 `OBJCXX` leaks into wxWidgets

With a toolchain file, `APPLE` can already be `1` before `project()`. wxWidgets then does
`list(APPEND wxLANGUAGES OBJCXX)`, and CMake tests an Objective-C++ compiler against Windows link paths and fails.
**Fix:** in wxWidgets' `CMakeLists.txt`, drop `OBJCXX` or guard it with
`if(APPLE AND NOT CMAKE_SYSTEM_NAME STREQUAL "Windows")`.

### 5.4 A transitive port adds `/MD`

`openexr` and `openjph` can append `/MD` when `CMP0091` is not `NEW` in their sub-builds. The link then fails:
`/failifmismatch: mismatch detected for 'RuntimeLibrary': wxmsw33u_core.lib has value MT_StaticRelease, OpenEXRCore has value MD_DynamicRelease`.
**Fix:** `FORCE` the `CMAKE_C_FLAGS_RELEASE` / `CMAKE_CXX_FLAGS_RELEASE` cache entries to `/MT` in the toolchain (as in
4.1) and set `VCPKG_C_FLAGS_RELEASE` to `/MT` in the triplet.

## 6. Configure and build

```bash
cmake -S . -B build-win \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=AMD64 \
  -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
  -DVCPKG_CHAINLOAD_TOOLCHAIN_FILE="$VCPKG_ROOT/triplets/x64-windows-llvm-toolchain.cmake" \
  -DVCPKG_TARGET_TRIPLET=x64-windows-llvm \
  -DCMAKE_BUILD_TYPE=Release

cmake --build build-win --config Release --parallel
```

`--parallel` without a number uses every core. The 80% machine budget in `CLAUDE.md` applies: pass a job count below
the core count.

## 7. Verify

```bash
file build-win/MyApplication.exe       # PE32+ executable (GUI) x86-64, for MS Windows
```

Run it in the bottle without starting the game (`macos-crossover.md` section 6 has the general form):

```bash
CX_BOTTLE="<bottle>" CX_BOTTLE_PATH="$HOME/Bottles" \
/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine --bottle "<bottle>" ./build-win/MyApplication.exe --help
```

## 8. Where to put the output

Stage finished binaries and the assets they need in one build-output folder outside the game install and outside MO2's
`mods/` (for example `<workspace>/build-output/<ProjectName>/`), then install them through the mod manager.

For .NET tools (Pandora Behaviour Engine, Synthesis) publish a self-contained Windows build:

```bash
dotnet publish -c Release -r win-x64 --self-contained -o <workspace>/build-output/<ProjectName>
```

## 9. .NET Avalonia GUI tools that look hung (Wabbajack 4.3.0.2)

Single-file Avalonia tools start under CrossOver on Apple Silicon but appear stuck. These are the causes found with
Wabbajack 4.3.0.2.

### 9.1 CrossOver's launcher never lets go (`winewrapper.exe --new-console`)

Launching from the CrossOver GUI ("Run Command...", desktop or Start Menu shortcut) runs `winewrapper.exe` with
`--new-console --start`. It hands the program to `ShellExecuteEx` and detaches it, but stays resident waiting for child
handles, so CrossOver keeps showing "Running command..." even after the app has exited.
**Fix:** call Wine directly, without `--new-console` or `--start`:

```bash
CX_BOTTLE="SkyGames" CX_BOTTLE_PATH="$HOME/Bottles" \
"/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine" \
  --bottle SkyGames --no-convert 'D:\Modding\Wabbajack-4.3.0.2\Wabbajack.exe'
```

### 9.2 Named-mutex collision (`SingleInstance`)

Wabbajack allows one process through a named mutex. After an abrupt exit, or while `wineserver` still holds the handle,
the next start sees `!singleInstance.IsFirstInstance`, sends its arguments over `WabbajackProtocolPipe` and exits with
code `0`. The user sees a brief spin and then nothing.
**Fix:** find and kill orphaned `winewrapper.exe` / `Wabbajack.exe` first:

```bash
ps -ef | grep -E -i "wabbajack|winewrapper" | grep -v grep
```

### 9.3 Slow first network calls behind a host firewall

At start `HomeVM` and `ModListGalleryVM` run `Client.LoadLists()` and query `raw.githubusercontent.com` for dozens of
modlist definitions in parallel. A macOS application firewall (for example Objective-See LuLu) can intercept or delay
outbound sockets of a freshly extracted single-file binary. The result is an 80 to 90 second wait with empty card
counters and loading rings, which looks like a deadlock.

### 9.4 WMI storage classes missing in Wine

1. `System.Management.WmiNetUtilsHelper` cannot load `C:\windows\Microsoft.NET\Framework64\v4.0.30319\wminet_utils.dll`
   (Win32Exception 126).
2. `DriveHelper.Partitions` queries `\\.\root\Microsoft\Windows\Storage` (`MSFT_Partition`, `MSFT_PhysicalDisk`). Wine
   returns an empty result, so `partitions[driveLetter]` throws `KeyNotFoundException: The given key 'C' was not present
   in the dictionary`.

### 9.5 Avalonia on DXVK

Avalonia 11 uses `Win32CompositionMode.RedirectionSurface`. Under DXVK on MoltenVK the swapchain comes up at native
size (for example `1427x688`, `VK_FORMAT_B8G8R8A8_UNORM`, `VK_PRESENT_MODE_FIFO_KHR`). The custom window chrome
(`ExtendClientAreaToDecorationsHint="True"`, `ExtendClientAreaChromeHints="NoChrome"`) depends on translated
`WM_NCHITTEST` messages, so while the .NET dispatcher is busy with bulk network and JSON work, UI hit-testing stalls.

### 9.6 Use the CLI

`cli/wabbajack-cli.exe` avoids the Avalonia composition, the WMI storage queries and the DXVK swapchain. For downloads,
game detection and installs, prefer it:

```bash
CX_BOTTLE="SkyGames" CX_BOTTLE_PATH="$HOME/Bottles" \
"/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine" \
  --bottle SkyGames --no-convert 'D:\Modding\Wabbajack-4.3.0.2\cli\wabbajack-cli.exe' list-games
```
