# CrossOver: BodySlide and Outfit Studio, "OpenGL context is not OK"

Why **BodySlide** and **Outfit Studio** run batch builds under CrossOver on Apple Silicon but fail as soon as you open
the Outfit Studio window or the BodySlide 3D preview, and the source fix. Read it when you see
`Outfit Studio: OpenGL context is not OK.` or `Preview failed: OpenGL context is not OK.` The one-line version is in
section 5 of `macos-crossover.md`.

Tags are those of `macos-crossover.md`. Everything here is **Measured (notes)**: found and fixed by the maintainer on
a CrossOver setup, carried over from earlier notes, not re-run for this page.

## 1. Symptom

The program starts and builds armor/body meshes in batch, but opening **Outfit Studio** or expanding the **BodySlide
preview panel** shows one of the dialogs above. The 3D viewport stays blank or unresponsive.

## 2. Cause

### 2.1 macOS only allows forward-compatible core contexts

Apple's Core OpenGL (CGL) restricts OpenGL 3.2+ core-profile contexts to forward-compatible mode. When a Windows
program calls `wglCreateContextAttribsARB`, Wine's macOS display driver (`winemac.so`) checks the flags and refuses a
3.2+ request that lacks the forward-compatible bit:

```c
if (major >= 3 && minor >= 2) {
    if (!(flags & WGL_CONTEXT_FORWARD_COMPATIBLE_BIT_ARB)) {
        WARN("OS X only supports forward-compatible 3.2+ contexts\n");
        return NULL;                // no context
    }
}
```

### 2.2 BodySlide never sets the bit

Upstream `src/render/GLSurface.cpp` asks for a core 3.3 profile and leaves out `ForwardCompatible()`:

```cpp
ctxAttribs.PlatformDefaults().CoreProfile().OGLVersion(3, 3).EndList();
```

`WGL_CONTEXT_FORWARD_COMPATIBLE_BIT_ARB` (`0x0002`) is therefore missing. Windows drivers accept that; Wine's macOS
driver returns a NULL context.

### 2.3 A removed fixed-function call

`GLSurface::InitGLSettings()` calls `glShadeModel(GL_SMOOTH)`, which does not exist in a core profile and is invalid
under macOS CGL.

## 3. Fix

In `src/render/GLSurface.cpp`, add `.ForwardCompatible()` and guard the legacy call:

```cpp
const wxGLContextAttrs& GLSurface::GetGLContextAttribs() {
    static bool ctxAttribsInitialized{false};
    static wxGLContextAttrs ctxAttribs;

    if (!ctxAttribsInitialized) {
        // required on macOS / CrossOver (Wine) for an OpenGL 3.2+ core profile
        ctxAttribs.PlatformDefaults().CoreProfile().ForwardCompatible().OGLVersion(3, 3).EndList();
        ctxAttribsInitialized = true;
    }
    return ctxAttribs;
}

int GLSurface::InitGLSettings() {
#ifndef __APPLE__
    glShadeModel(GL_SMOOTH);        // legacy fixed-function, removed in core profiles
#endif
    ...
```

## 4. Getting a fixed build

Either way you end up with your own `BodySlide.exe` and `OutfitStudio.exe`.

1. **GitHub Actions (no local toolchain).** Fork the BodySlide-and-Outfit-Studio repository, push the change with a
   release tag (for example `v5.8.0-crossover`), run the **CMake Release** or **CMake RelWithDebInfo** workflow and
   download `windows-x64-relwithdebinfo.zip`.
2. **Local cross-compile on the Mac.** `clang-cl` + `lld-link` against an `xwin` sysroot, triplet `x64-windows-llvm`
   with a static `/MT` runtime and the patched OpenGL and wxWidgets ports. Steps and traps:
   `windows-exe-cross-compile-macos.md`. Verified against a CrossOver bottle without starting Windows.

Install the result into MO2 as a mod (BodySlide lives under `CalienteTools/BodySlide/`) and let the mod manager deploy
it, as with any third-party file.
