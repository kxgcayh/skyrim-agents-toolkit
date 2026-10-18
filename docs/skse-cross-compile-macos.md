# Cross-compiling SKSE plugins on macOS (clang-cl + xwin + CMake + Ninja)

Build a native Windows x64 SKSE plugin DLL (`x86_64-pc-windows-msvc`) on a Mac, with no Visual Studio and no Wine.
Read it before you build a CommonLibSSE-NG plugin on macOS or diagnose a cross-build error. The Linux/devcontainer
variant that uses xmake is `skse-cross-compile.md`; the shorter summary of Windows-tool cross-builds is section 7 of
`macos-crossover.md`; the same toolchain builds `.exe` tools in `windows-exe-cross-compile-macos.md`.

Tags are those of `macos-crossover.md`. The pipeline and every trap below are **Measured (notes)**: built and
verified by the maintainer on Apple Silicon, carried over from earlier notes, not re-run for this page. Paths are
placeholders: `<winsdk>` is the xwin sysroot, `<vcpkg>` the vcpkg checkout.

## 1. Why this toolchain

An SKSE plugin is a PE32+ DLL for x86_64. Nearly all modern ones use **CommonLibSSE-NG**, which needs:

1. the **MSVC C++ standard library and ABI** (C++20/23, `/EHsc`, MSVC name mangling);
2. the **Windows SDK** headers (`windows.h`, `d3d11.h`, `dxgi.h`) and import libraries (`kernel32.lib`, `d3d11.lib`);
3. static dependencies: `spdlog`, `fmt`, `nlohmann-json`, `simpleini`, `xbyak`, `rapidcsv`, `DirectXTK`.

MinGW (`x86_64-w64-mingw32-g++`) does not work: its `libstdc++` ABI is incompatible with MSVC-mangled symbols,
CommonLibSSE-NG relies on MSVC preprocessor extensions, SAL annotations and calling conventions, and DirectXTK and
other Skyrim libraries ship no MinGW support.

What works: **`clang-cl`** (a `cl.exe` look-alike) and **`lld-link`** (a `link.exe` look-alike) against a Windows
SDK and MSVC CRT sysroot unpacked by **`xwin`**, driven by CMake and Ninja.

## 2. Prerequisites

```bash
brew install llvm cmake ninja xwin
clang-cl --version     # must support x86_64-pc-windows-msvc
lld-link --version
xwin --version         # 0.10.x or newer
```

Installing software on the host is the user's decision; `toolkit-setup` covers what an agent may install.

## 3. The Windows SDK and CRT sysroot

`xwin` downloads Microsoft's CRT and SDK packages. Pass `--accept-license` in every script: without it `xwin` prompts
and fails with `Error: unknown response to license request`.

```bash
export WINSYSROOT="<winsdk>"
mkdir -p "$WINSYSROOT"
xwin --accept-license --arch x86_64 --timeout 300s --http-retry 5 splat --output "$WINSYSROOT"
```

Expected layout:

```
$WINSYSROOT/
  crt/include            <iostream>, <vector>, <format> ...
  crt/lib/x86_64         msvcrt.lib, vcruntime.lib, msvcp.lib
  sdk/include/{shared,ucrt,um,winrt}
  sdk/lib/ucrt/x86_64    ucrt.lib
  sdk/lib/um/x86_64      kernel32.lib, user32.lib, d3d11.lib, dxgi.lib
```

## 4. CMake toolchain file (`clang-cl-msvc.cmake`)

Homebrew paths below are for Apple Silicon (`/opt/homebrew`); on Intel use `/usr/local`.

```cmake
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR AMD64)

if(NOT DEFINED WINSYSROOT)
    set(WINSYSROOT "<winsdk>" CACHE PATH "Windows SDK / CRT sysroot")
endif()

set(CMAKE_C_COMPILER   "/opt/homebrew/opt/llvm/bin/clang-cl")
set(CMAKE_CXX_COMPILER "/opt/homebrew/opt/llvm/bin/clang-cl")
set(CMAKE_LINKER       "/opt/homebrew/bin/lld-link")
set(CMAKE_AR           "/opt/homebrew/opt/llvm/bin/llvm-lib")
set(CMAKE_RANLIB       "/opt/homebrew/opt/llvm/bin/llvm-ranlib")
set(CMAKE_RC_COMPILER  "/opt/homebrew/opt/llvm/bin/llvm-rc")
set(CMAKE_MT           "/opt/homebrew/opt/llvm/bin/llvm-mt")

set(MSVC_COMMON_FLAGS "--target=x86_64-pc-windows-msvc -fuse-ld=lld-link -imsvc ${WINSYSROOT}/crt/include -imsvc ${WINSYSROOT}/sdk/include/ucrt -imsvc ${WINSYSROOT}/sdk/include/shared -imsvc ${WINSYSROOT}/sdk/include/um -imsvc ${WINSYSROOT}/sdk/include/winrt")
set(CMAKE_C_FLAGS_INIT   "${MSVC_COMMON_FLAGS}")
set(CMAKE_CXX_FLAGS_INIT "${MSVC_COMMON_FLAGS}")

set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")      # /MD

set(MSVC_LINK_DIRS "/LIBPATH:${WINSYSROOT}/crt/lib/x86_64 /LIBPATH:${WINSYSROOT}/sdk/lib/ucrt/x86_64 /LIBPATH:${WINSYSROOT}/sdk/lib/um/x86_64")
set(CMAKE_EXE_LINKER_FLAGS_INIT    "${MSVC_LINK_DIRS}")
set(CMAKE_SHARED_LINKER_FLAGS_INIT "${MSVC_LINK_DIRS}")
set(CMAKE_MODULE_LINKER_FLAGS_INIT "${MSVC_LINK_DIRS}")
```

## 5. Dependencies with vcpkg

```bash
git clone --depth=1 https://github.com/microsoft/vcpkg.git <vcpkg>
<vcpkg>/bootstrap-vcpkg.sh
```

Triplet overlay `vcpkg-triplets/x64-windows-cross.cmake`:

```cmake
set(VCPKG_TARGET_ARCHITECTURE x64)
set(VCPKG_CRT_LINKAGE dynamic)
set(VCPKG_LIBRARY_LINKAGE static)
set(VCPKG_CMAKE_SYSTEM_NAME Windows)
set(VCPKG_CHAINLOAD_TOOLCHAIN_FILE "<path>/clang-cl-msvc.cmake")
```

```bash
<vcpkg>/vcpkg install --triplet x64-windows-cross --overlay-triplets=<path>/vcpkg-triplets \
  simpleini nlohmann-json xbyak rapidcsv spdlog
```

## 6. Traps

### A. A rogue `sal.h` from a port

- **Symptom:** errors inside standard headers (`<execution>`, `<concurrencysal.h>`): `unknown type name '_Guarded_by_'`
  or `duplicate member '_Segment_lock'`.
- **Cause:** some ports (for example `directxmath`) install an emulation `sal.h` from dotnet's PAL under
  `vcpkg/installed/.../include/`, which hides Microsoft's real `sal.h` in the CRT.
- **Fix:** delete the shadowing header so `clang-cl` finds the SDK one:
  `rm -f <vcpkg>/installed/x64-windows-cross/include/sal.h`.

### B. The `PlaySound` macro

- **Symptom:** `no member named 'PlaySoundA' in namespace 'RE'`.
- **Cause:** `<mmsystem.h>` does `#define PlaySound PlaySoundA`; with Windows headers included first, `RE::PlaySound`
  becomes `RE::PlaySoundA`.
- **Fix:** after the includes, `#ifdef PlaySound` / `#undef PlaySound` / `#endif`.

### C. Multiple inheritance and `operator delete`

- **Symptom:** `explicitly defaulted destructor is implicitly deleted`, then `deleted function '~CustomMenu' cannot
  override a non-deleted function`, noting that a virtual destructor needs an unambiguous `operator delete`.
- **Cause:** two bases (for example `IMenu` and `MenuEventHandler`) both provide virtual destructors, so the
  deallocation function lookup is ambiguous under strict Clang.
- **Fix:** name one: `using MenuEventHandler::operator delete;` in the derived class
  (`class CustomMenuEx : public RE::JournalMenu { public: using MenuEventHandler::operator delete; ... };`).

### D. DirectXTK wants a shader compiler

- **Symptom:** `vcpkg install directxtk` fails because it runs `CompileShaders.cmd` or `fxc.exe`.
- **Fix:** if the mod needs only the math/utility headers (`SimpleMath.h`, `DirectXMath.h`), copy them from DirectXTK's
  `Inc/` and provide an interface target in `directxtkConfig.cmake`:
  ```cmake
  if(NOT TARGET Microsoft::DirectXTK)
      add_library(Microsoft::DirectXTK INTERFACE IMPORTED)
  endif()
  set(directxtk_FOUND TRUE)
  ```

### E. The OpenVR submodule hangs

- **Symptom:** `git submodule update --init --recursive` in CommonLibSSE-NG stalls on `extern/openvr`.
- **Cause:** Valve's `openvr.git` carries historical binary SDK snapshots and driver repos over 100 MB.
- **Workaround:** `extern/openvr` is a gitlink (mode `160000`). If you copy its headers from another cache, delete the
  copied `.git` inside it (`rm -rf extern/openvr/.git`), or the parent repo reports the submodule as dirty.

## 7. Build and verify

```bash
cmake -GNinja -DCMAKE_TOOLCHAIN_FILE="<path>/clang-cl-msvc.cmake" \
  -DCMAKE_PREFIX_PATH="<vcpkg>/installed/x64-windows-cross" -DCMAKE_BUILD_TYPE=Release \
  -S "<source>" -B "<source>/build"
cmake --build "<source>/build" -j"$(sysctl -n hw.ncpu)"
```

Keep the parallelism under the 80% machine budget in `CLAUDE.md`: cap `-j` below the core count rather than using
every core.

```bash
file "<source>/build/MyPlugin.dll"      # PE32+ executable (DLL) (GUI) x86-64, for MS Windows
llvm-nm -g "<source>/build/MyPlugin.dll" | grep -E "SKSEPlugin_(Load|Query|Version)"
```

A DLL that builds is not a DLL that loads. For a plugin that stays dead on a new game build, go to
`skse-internals.md` section 5. Deploy the finished DLL through the mod manager, not by hand into `Data/`.

## 8. Checklist

| Step | Action | Command or target |
|---|---|---|
| 1 | Install the toolchain | `brew install llvm cmake ninja xwin` |
| 2 | Sysroot | `xwin --accept-license --arch x86_64 splat --output <winsdk>` |
| 3 | Toolchain file | `clang-cl-msvc.cmake` |
| 4 | Dependencies | `vcpkg install --triplet x64-windows-cross ...` |
| 5 | Source fixes | `#undef PlaySound`, `using Base::operator delete;` |
| 6 | Build | `cmake --build` |
| 7 | Verify | `file`, `llvm-nm -g` |
