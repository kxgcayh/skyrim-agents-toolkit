---
name: skyrim-skse
description: Create, build, and manage SKSE C++ plugin projects. Use when the user wants to create native plugins, build them with CMake, add Papyrus native functions, or extend Skyrim's functionality at the native level.
---

# Skyrim SKSE Module

Create and manage SKSE (Skyrim Script Extender) C++ plugin projects using Spooky's AutoMod Toolkit.

## Prerequisites

Run from the toolkit root; the wrapper is `bash tools/automod-cli.sh` (install and pin: `docs/installing-tools.md`).
Check this module exists in your build with `bash tools/automod-cli.sh skse templates --json`.

### Build requirements

| Tool | Purpose |
|------|---------|
| **CMake 3.21+** | Build system |
| A C++ compiler for `x86_64-pc-windows-msvc` | **MSVC Build Tools** on Windows (the full Visual Studio IDE is not needed). **On macOS**, `clang-cl` + `lld-link` + an `xwin` sysroot: `docs/skse-cross-compile-macos.md`. On Linux: `docs/skse-cross-compile.md` |
| vcpkg | Dependencies, bootstrapped by the project |

A plugin that builds still has to load on the target game build: read `docs/skse-internals.md` (Address Library, the
SKSE 2.3.1 gate) and, for AE 1.7.99+, `docs/ae-1-7-104-plugin-fixes.md` before you ship one.

## Overview

SKSE plugins are DLL files that extend Skyrim's functionality at a native level. This module generates project scaffolding using **CommonLibSSE-NG**, which supports Skyrim SE, AE, GOG, and VR from a single codebase.

## Command Reference

### List Available Templates
```bash
bash tools/automod-cli.sh skse templates
```

**Available Templates:**
| Template | Description |
|----------|-------------|
| `basic` | Minimal SKSE plugin with logging |
| `papyrus-native` | Plugin with Papyrus native function support |

### Create SKSE Project
```bash
bash tools/automod-cli.sh skse create "<name>" [options]
```
| Option | Default | Description |
|--------|---------|-------------|
| `--template` | `basic` | Template to use |
| `--output` | `.` | Output directory |
| `--author` | `Unknown` | Author name |
| `--description` | - | Project description |

### Build SKSE Project
```bash
bash tools/automod-cli.sh skse build "<project>" [options]
```
| Option | Default | Description |
|--------|---------|-------------|
| `<project>` | `.` | Project directory |
| `--config` | `Release` | Build configuration (Release or Debug) |
| `--clean` | `false` | Clean build directory before building |

### Get Project Info
```bash
bash tools/automod-cli.sh skse info "<path>"
```
| Option | Description |
|--------|-------------|
| `<path>` | Project directory (default: current) |

### Add Papyrus Native Function
```bash
bash tools/automod-cli.sh skse add-function "<project>" --name "<name>" [options]
```
| Option | Default | Description |
|--------|---------|-------------|
| `--name` | Required | Function name |
| `--return` | `void` | Return type |
| `--param` | - | Parameters (format: `type:name`, repeatable) |

## Common Workflows

### Create Basic SKSE Plugin
```bash
# 1. Create project
bash tools/automod-cli.sh skse create "MyPlugin" --output "./" --author "YourName"

# 2. Build (requires CMake and MSVC)
bash tools/automod-cli.sh skse build "./MyPlugin"

# Output: MyPlugin/build/Release/MyPlugin.dll
```

### Create Plugin with Papyrus Functions
```bash
# 1. Create project with papyrus-native template
bash tools/automod-cli.sh skse create "MyNativePlugin" --template papyrus-native --author "YourName" --output "./"

# 2. Add custom functions
bash tools/automod-cli.sh skse add-function "./MyNativePlugin" --name "GetActorSpeed" --return "Float" --param "Actor:target"

bash tools/automod-cli.sh skse add-function "./MyNativePlugin" --name "SetActorSpeed" --return "void" --param "Actor:target" --param "Float:speed"

bash tools/automod-cli.sh skse add-function "./MyNativePlugin" --name "GetPluginVersion" --return "Int"

# 3. Build
bash tools/automod-cli.sh skse build "./MyNativePlugin"
```

### Check Existing Project
```bash
# Get project info
bash tools/automod-cli.sh skse info "./MyPlugin"
```

## Papyrus Type Mapping

| Papyrus Type | C++ Type | Notes |
|--------------|----------|-------|
| Int | int | 32-bit integer |
| Float | float | 32-bit float |
| Bool | bool | Boolean |
| String | std::string | Text string |
| Actor | RE::Actor* | Actor reference |
| ObjectReference | RE::TESObjectREFR* | Object reference |
| Form | RE::TESForm* | Any form |

### Function Parameter Format
```
--param "Type:name"
```

Examples:
- `--param "Actor:target"` - Actor parameter named "target"
- `--param "Float:speed"` - Float parameter named "speed"
- `--param "Int:count"` - Integer parameter named "count"
- `--param "String:message"` - String parameter named "message"

## Generated Project Structure

```
MyPlugin/
  CMakeLists.txt          # CMake build configuration
  vcpkg.json              # C++ dependencies
  skse_config.json        # Toolkit configuration
  src/
    main.cpp              # SKSE plugin entry point
    plugin.cpp            # Plugin implementation
    plugin.h              # Plugin header
  cmake/
    CommonLibSSE.cmake    # CommonLibSSE-NG integration
```

## Template Details

### basic Template
Minimal plugin with:
- Modern C++20 plugin metadata (`.RuntimeCompatibility()`)
- Precompiled headers (PCH) for fast builds
- Comprehensive event handler examples (OnHit, OnEquip)
- Safe NiPointer and Actor casting patterns
- Correct form lookup methods (EditorID vs FormID)
- Logging setup
- Message handler for game events

**Modern API Features:**
```cpp
// Modern plugin version declaration
extern "C" __declspec(dllexport) constinit SKSE::PluginVersionData SKSEPlugin_Version = [] {
    SKSE::PluginVersionData data{};
    data.RuntimeCompatibility(SKSE::RuntimeCompatibility::Independent);
    return data;
}();

// Safe NiPointer handling
auto target = event->target.get();  // Get raw pointer
auto actor = target->As<RE::Actor>();  // Safe cast

// Correct form lookup
auto form = RE::TESForm::LookupByEditorID("MyForm"sv);  // By EditorID
auto form = RE::TESForm::LookupByID(0x00012EB7);  // By FormID
```

**Build Options:**
- VCPKG (automatic dependency management)
- Manual vendor/ folder (no VCPKG required)
- Windows CMD build script included (`build.bat`)

### papyrus-native Template
Includes everything in `basic` plus:
- Papyrus native function registration
- Script interface
- Example function

```cpp
// Register functions
bool RegisterFunctions(RE::BSScript::IVirtualMachine* vm) {
    vm->RegisterFunction("MyFunction", "MyScript", MyFunction);
    return true;
}

// Example native function
int MyFunction(RE::StaticFunctionTag*) {
    return 42;
}
```

## Using Native Functions in Papyrus

After building the plugin, call native functions from Papyrus:
```papyrus
ScriptName MyScript

; Declare native functions
Int Function GetPluginVersion() global native
Float Function GetActorSpeed(Actor target) global native
Function SetActorSpeed(Actor target, Float speed) global native

; Usage
Event OnInit()
    Int version = GetPluginVersion()
    Debug.Notification("Plugin version: " + version)

    Actor player = Game.GetPlayer()
    Float speed = GetActorSpeed(player)
    SetActorSpeed(player, speed * 1.5)
EndEvent
```

## CommonLibSSE-NG

This toolkit uses **CommonLibSSE-NG** (Next Generation), which provides:

- **Multi-version support**: Single DLL works on SE, AE, GOG, VR
- **Address independence**: No hardcoded addresses
- **Modern C++**: Uses C++20 features
- **Complete API**: Covers most game functions

### Supported Skyrim Versions
| Version | Support |
|---------|---------|
| Skyrim SE 1.5.x | Full |
| Skyrim SE 1.6.x (AE) | Full |
| Skyrim GOG | Full |
| Skyrim VR | Partial |

## Building Projects

### Using `skse build` (Recommended)
```bash
# Standard build
bash tools/automod-cli.sh skse build "./MyPlugin"

# Debug build
bash tools/automod-cli.sh skse build "./MyPlugin" --config Debug

# Clean rebuild
bash tools/automod-cli.sh skse build "./MyPlugin" --clean

# JSON output
bash tools/automod-cli.sh skse build "./MyPlugin" --json
```

### Manual CMake Build
```bash
cd MyPlugin
cmake -B build -S .
cmake --build build --config Release
```

### Output Location
- Release: `build/Release/MyPlugin.dll`
- Debug: `build/Debug/MyPlugin.dll`

## Installing SKSE Plugins

1. Copy DLL to `Data/SKSE/Plugins/`
2. Copy any config files to same folder
3. Launch game with SKSE loader

## Limitations

This module **CAN**:
- Generate project scaffolding
- Build projects end-to-end via `skse build` (requires CMake + MSVC)
- Add Papyrus native function stubs
- Manage project configuration

This module **CANNOT**:
- Write custom C++ logic (generates stubs/templates)
- Auto-install build tools (user must install CMake and MSVC)
- Debug plugins
- Generate complex game hooks

For advanced SKSE development:
- [CommonLibSSE-NG Wiki](https://github.com/CharmedBaryon/CommonLibSSE-NG/wiki)
- [SKSE Plugin Development Guide](https://www.creationkit.com/index.php?title=Category:SKSE)

## Important Notes

1. **Build tools required** - CMake and MSVC Build Tools needed (NOT full Visual Studio IDE)
2. **Single codebase, all versions** - CommonLibSSE-NG handles version differences
3. **vcpkg auto-bootstraps** - Dependencies downloaded on first build (~5 minutes first time)
4. **Native functions need matching Papyrus declarations** - Script must declare functions as `native`
5. **Use `--json` flag** for machine-readable output when scripting
6. **LLMs can build plugins** - Use Bash tool to invoke CMake commands for end-to-end workflow

## JSON Output

All commands support `--json` for structured output:
```bash
bash tools/automod-cli.sh skse info "./MyPlugin" --json
```

Example response:
```json
{
  "success": true,
  "result": {
    "name": "MyPlugin",
    "author": "YourName",
    "version": "1.0.0",
    "template": "papyrus-native",
    "description": "My SKSE Plugin",
    "targetVersions": ["SE", "AE"],
    "papyrusFunctions": [
      {
        "name": "GetActorSpeed",
        "returnType": "Float",
        "parameters": [
          { "type": "Actor", "name": "target" }
        ]
      }
    ]
  }
}
```
