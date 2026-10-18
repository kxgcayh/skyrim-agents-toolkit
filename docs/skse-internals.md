# SKSE plugin internals: entry points, Address Library, runtime targeting

How a native SKSE plugin is found, loaded and bound to engine addresses on **Skyrim SE and AE (PC)**. Read it
before diagnosing a plugin that "does not load" or crashes at load. VR is covered last, as inherited material.

Adapted from the maintainer's own AE 1.7.104 notes (a separate workspace). Every fact is tagged:

| Tag | Meaning |
|---|---|
| **All** | Holds on SE, AE and VR |
| **SE/AE** | Applies to flat Skyrim. Entries marked *measured* were observed on AE 1.7.104 with SKSE 2.3.1 |
| **VR** | Inherited from upstream and public sources. **Not tested by this fork** (no VR setup) |

Hook offsets, RVAs and vtable addresses from the AE notes are deliberately NOT carried over: each belongs to one
game build and is wrong on any other. Re-derive them per build (section 6) and keep them with the plugin. The per-plugin values the maintainer did keep are
in `ae-1-7-104-plugin-fixes.md`, each tagged with the one build it is valid for.

## 1. Entry points

A plugin is a DLL in `Data/SKSE/Plugins/` that SKSE finds by its exports.

| Export | Read by | Notes |
|---|---|---|
| `SKSEPlugin_Query` | SKSE for **SE 1.5.97 and VR** | Fills in plugin info, returns true/false. Keep it minimal |
| `SKSEPlugin_Version` (a `constinit` data struct) | SKSE for **AE (1.6+)** | Metadata plus compatibility flags |
| `SKSEPlugin_Load` | All | The real work: logging setup, hooks, event sinks, Papyrus registration |

Each SKSE ignores the other's symbol, so a plugin meant to load on both pre-AE and AE must export both.
CommonLibSSE-NG's `SKSEPluginInfo` macro generates both. Move anything that used to live in `Query` (Creation Kit
check, logger setup) into `Load`.

## 2. Address Library

**All.** Engine functions, vtables and globals have a stable numeric ID. The plugin asks for `REL::ID(n)`; the
loader turns it into `base + offset` using a database file in `Data/SKSE/Plugins/`. A game update moves the offset,
not the ID, so one DLL survives updates as long as the database for that exact game version is present.

**SE/AE.** The database format follows the game era:

| File | Format | Era |
|---|---|---|
| `version-<ver>.bin` | 1 | SE 1.5.x |
| `versionlib-1-6-*.bin` | 2, packed deltas, header `02 00 00 00` | AE 1.6.x |
| `versionlib-1-7-*.bin` | 5, dense ID-indexed array, 96-byte header `05 00 00 00` | AE 1.7.99+ |
| `versionl2b-1-7-*.bin` | 2 (unofficial community build for 1.7.x) | AE 1.7.x, for loaders that cannot read Format 5 |

The game version is the 4-part file version of the exe (`1.7.104.0`). The plugin's CommonLib build must know how to
read the format and how to map that version to a database name; an old build that does neither fails at load.

SKSE builds by game era (**SE/AE**, from the maintainer's notes), and two IDs that are the same on every build because
they are IDs, not addresses:

| Era | Game | SKSE |
|---|---|---|
| Pre-AE | 1.5.97 and earlier | 2.0.20 |
| AE 1.6 | 1.6.318 to 1.6.1170 | 2.1.x to 2.2.6 |
| Creation Update 1.7 | 1.7.99, 1.7.104 | 2.3.1 (has the pre-load gate, section 7) |

`SleepWaitMenu::Vtbl` is ID `215936`; `FrameTimer` (the delta frame timer) is ID `410199`.

## 3. CommonLibSSE-NG runtime targeting

- **All.** One DLL can target SE, AE and VR (the default), or a subset with `ENABLE_SKYRIM_SE`,
  `ENABLE_SKYRIM_AE`, `ENABLE_SKYRIM_VR`. The vcpkg ports are `commonlibsse-ng-se`, `-ae`, `-vr` and `-flatrim`
  (AE + SE, **no VR**), so a flat-only fork can build against `-flatrim` and never pay the VR layout tax.
- **All.** Address Library is the default binding. `RELOCATION_ID(se, ae)` (or three arguments with VR) is for the
  case where the ID differs between runtimes.
- **SE/AE, measured.** Runtime detection in older CommonLibSSE-NG switched on the file version's minor number
  (`1.<minor>.x`). `4` was VR, `6` was AE, and anything else fell through to SE. On 1.7.x the minor is `7`, so the
  game was treated as SE and the loader asked for a database that does not exist. Fixed in CommonLibSSE-NG 12.1.0
  by comparing `>= 6`. Detect 1.7.x by the revision field (`104`), not by a packed number.

## 4. AE 1.7.99+ failure modes (SE/AE, measured)

Three separate layers. Diagnose them in this order; the message tells you which one you are in.

| Order | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Modal: `<Plugin>.dll: must be recompiled for new address library` | SKSE 2.3.1 pre-load gate. The exported `SKSEPlugin_Version` has the Address Library flag set but not the V5 flag (`versionIndependenceEx` bit 1) | Recompile with current CommonLibSSE-NG, or patch the flag in the DLL's exported struct |
| 2 | `REL/ID.h(219): failed to open address library file` | Old CommonLib treated `1.7.x` as SE (section 3) | Recompile with CommonLibSSE-NG 12.1.0+ |
| 3 | `Unsupported address library format: 5`, or hooks land on the wrong code | Loader reads only Format 2; or an inlined function moved or changed calling convention between 1.6.x and 1.7.x | Newer loader, or the community Format 2 file; re-verify each hook site on the new build |

Layer 1 happens before the plugin runs at all, so it is not a `REL/ID.h` error. A vtable slot can also shift
between versions (the author saw an input handler's `ProcessButton` move from slot 4 to slot 6 on 1.7.99+): when a
hook "does nothing", check the slot before the logic.

## 5. Diagnostic order for "plugin did not load"

1. **Game build.** Read the exe's file version (`1.5.97.0`, `1.6.1170.0`, `1.7.104.0`).
2. **SKSE log.** `Documents/My Games/Skyrim Special Edition/SKSE/skse64.log`. It says whether each plugin was
   found, rejected at query, or failed in load. Tool: `skse-load-status` (skill `triage-and-conflicts`).
3. **Database.** The Address Library file for this exact game version is in `Data/SKSE/Plugins/`, in a format the
   plugin's CommonLib can read (section 2).
4. **Entry points.** The DLL exports what this SKSE reads (section 1). Check with a PE export dump.
5. **The plugin's own log** (*measured*). Most CommonLib plugins create `<Documents>/My Games/Skyrim Special
   Edition/SKSE/<Name>.log` early in `Load`. If the plugin failed and that file is missing, or older than the
   crash, the failure was before the logger existed: inside `SKSE::Init`, the runtime check or the Address Library
   load.
6. **Reading the dialog** (*measured*). In release builds a checked CommonLib failure shows a message box
   (`file(line): message`) and then terminates the process. A dialog from SKSE alone, with the game still
   loading, means a raw access violation or an uncaught exception: SKSE 2.3.1 wraps the load call in a catch-all
   and logs no exception code.
7. **Mod manager.** Under MO2 the plugin may live in a virtual `Data`; check the profile's mod list, not the real
   game folder (`KNOWLEDGEBASE.md`: Mod Manager Layout).

## 6. Static analysis when there is no source

To get the exact call sequence of a DLL's `SKSEPlugin_Load`: disassemble with `llvm-objdump -d`, take function
bounds from the `.pdata` RUNTIME_FUNCTION table, and walk calls from the export. This works on any PE, ties a crash
to one function without running the game, and verifies a hook site on a new build (the bytes at `ID + offset` must
be the instruction the hook expects). Pair it with the crash logger report (`tools/crash-triage.py`).

## 7. The SKSE 2.3.1 pre-load gate in detail (SE/AE, measured)

Fixing a plugin's own CommonLib logic (sections 3 and 4) is not enough on 1.7.104 with SKSE 2.3.1: SKSE validates every
plugin before `SKSEPlugin_Load` runs. In `PluginManager::ScanPlugins()` it maps each `Data\SKSE\Plugins\*.dll` with
`LoadLibraryEx(..., LOAD_LIBRARY_AS_IMAGE_RESOURCE)`, reads the exported `SKSEPlugin_Version` data symbol and calls
`PluginManager::CheckPluginCompatibility()` (`skse64/PluginManager.cpp`), which does this:

```cpp
const UInt32 kKnownVersionIndependent =
    kVersionIndependent_AddressLibraryPostAE | kVersionIndependent_Signatures | kVersionIndependent_StructsPost629;

if (version.versionIndependence & kVersionIndependent_AddressLibraryPostAE) {
    if (!CheckAddressLibrary())            // opens Data\SKSE\Plugins\versionlib-<ver>.bin
        return "disabled, address library needs to be updated";

    // the address library changed encoding incompatibly in 1.7.99+
    if (!(version.versionIndependenceEx & kVersionIndependentEx_AddressLibraryV5)) {
        UInt32 buildTime = GetBuildTime(plugin);                      // PE header TimeDateStamp
        if ((buildTime >= 520128000) && (buildTime < 1748217600)) {   // before 2025-05-26 GMT
            errorMsg = "must be recompiled for new address library";
            versionIndependent = false;    // falls into the compatibleVersions[] check, which old plugins fail
        }
    }
}
```

Consequences:

- Any CommonLibSSE-NG plugin built before 2025-05-26 that uses the Address Library is rejected with
  `"<Plugin>.dll: must be recompiled for new address library"`, even if it would run once loaded, because old CommonLib
  never sets `kVersionIndependentEx_AddressLibraryV5`.
- SKSE 2.3.1 no longer calls `SKSEPlugin_Query`. Only `SKSEPlugin_Load` (and an optional `SKSEPlugin_Preload`) run.
- Diagnostic shortcut: the modal titled `SKSE Plugin Loader (2.3.1)` with that text is this gate, **not** `REL/ID.h(219)`.
  The latter appears in `skse64.log` or crash output only when the plugin actually executes.

### 7.1 The exported `SKSEPluginVersionData` struct

Layout of the `SKSEPlugin_Version` export, offsets from the symbol start. The maintainer's notes say CommonLibSSE-NG
`include/SKSE/Interfaces.h` and skse64 `PluginAPI.h` agree on it.

| Offset | Size | Field | Notes |
|---|---|---|---|
| `+0x000` | 4 | `dataVersion` | must be `1` |
| `+0x004` | 4 | `pluginVersion` | packed `(maj<<24)\|(min<<16)\|(pat<<8)\|rev` |
| `+0x008` | 256 | `name` | NUL-terminated ASCII |
| `+0x108` | 256 | `author` | |
| `+0x208` | 252 | `supportEmail` | |
| `+0x304` | 4 | `versionIndependenceEx` | bit 0 `NoStructUse = 1<<0`, bit 1 **`AddressLibraryV5 = 1<<1`** |
| `+0x308` | 4 | `versionIndependence` | bit 0 `AddressLibraryPostAE`, bit 1 `Signatures`, bit 2 `StructsPost629` |
| `+0x30C` | 64 | `compatibleVersions[16]` | zero-terminated list of packed `RUNTIME_VERSION` |
| `+0x34C` | 4 | `seVersionRequired` | compared with `PACKED_SKSE_VERSION` |
| total | `0x350` (848) | | |

**Binary fix without a recompile:** OR bit 1 into `versionIndependenceEx`. Find the struct by its signature
(`dataVersion = 1`, then `pluginVersion`, then the name), never by a fixed file offset. Case study,
`QuestJournalOverhaul.dll` v1.2.0 (built February 2025): `versionIndependenceEx` `0x01` to `0x03` (CommonLib had
already set `NoStructUse`), struct at file offset `0xB3150`, patch at `0xB3454`. Method:
`binary-patcher-guide.md` section 2.3.

## 8. Load-phase failure after the gate passes (QJO case study, static analysis 2026-10-12)

**Measured (notes).** With the gate, runtime-check and `versionl2b` patches in place, QJO passes the gate and
`SKSEPlugin_Load` starts, but SKSE's `SafeCallLoadPlugin` `__except` catches an exception (error code 0) and reports
`"disabled, fatal error occurred while loading plugin"`; loading then continues. Static disassembly (`llvm-objdump` plus
`.pdata` function bounds) mapped the whole window. RVAs below are into that one DLL.

| # | RVA | Function | Notes |
|---|---|---|---|
| 1 | `0x46660` | `SKSE::Init` | calls `Module::get()` (`0x14C10` to `0x15410` to `load_version 0x179E0`, PE parse `0x44420`), then `IDDatabase::get()` (`0x14B80` to `load 0x15E00` to `load_file 0x172B0`). **The Address Library load happens here** |
| 2 | `0x37580` | QJO `SetupLog()` | creates `<SKSE log dir>\<name>.log`; its failure path is fatal (`report_and_fail`) |
| 3 | `0x574b0` | spdlog `set_level` | |
| 4-10 | `0x465xx`, `0x463a0` | serialization (`SetUniqueID 0x5153544D`, save/load/revert) and messaging listener | pure interface calls, no `REL` |
| 11 | `0x35210` | `LoadAllQuestsSupplementalData` | quest-location JSON |
| 12 | `0x36a50` | `LoadQuestsCategoriesData` | category JSON |
| 13 | `0xc560` | hook install | 2 relocations, `VirtualProtect(..., 8, PAGE_EXECUTE_READWRITE)`, patches game bytes; originals saved at `0x1800B83E8` / `0x1800B83F0` |
| 14 | `0x51630` and tail | final spdlog line `"Quest Journal is in Player's pocket!"` (`main.cpp:59`), returns true | never reached |

**What was eliminated**

1. **No QJO log file was ever created** (checked Documents `SKSE\`, the mod folder and MO2 overwrite, also by a time
   window around the crash run). `SetupLog` is call 2 and would create it, so the exception fires **inside call 1**,
   during `Module` / `IDDatabase` initialization.
2. **Every checked failure in this loader is fatal with a dialog.** `report_and_error` (body at `0x18B70`) ends in
   `MessageBoxW(NULL, body, caption, MB_OK)` (`0x442B0`) and `TerminateProcess(GetCurrentProcess(), 1)` (`0x442E0`); this
   build is not the `ENABLE_COMMONLIBSSE_TESTING` (throw) variant. Open-fail and format-mismatch go through `0x18DD0`
   (hardcoded `a_fail = true`); version-mismatch, mmap-create-fail and the `catch(std::system_error)` path call `0x18B70`
   with the caller's `a_failOnError = true`. So if the file open, header, version or mapping had failed, a CommonLib
   dialog would have appeared and the game would have exited. Only SKSE's dialog appeared and the process survived, so
   those steps passed.
3. The open path is statically correct with the patches: `Data/SKSE/Plugins/versionl2b-{1-7-104-0}.bin`, format 2, and
   the file was verified byte-exact (435162 entries, 0 trailing).

**Remaining hypothesis.** The one unguarded phase left is the **shared-memory database mapping** in `load_file`:
`OpenFileMappingW` / `CreateFileMappingW` (`PAGE_READWRITE`, 6.96 MB, name `CommonLibSSEOffsets-v2-<version>`) and
`MapViewOfFile`, then an in-place unpack and `std::sort` over that view. An access violation there (a Wine/CrossOver
mapping quirk, for example) is caught by SKSE's `__except` and gives no dialog and no log, and loading continues, which
matches every observation. The mapping is **named and process-wide**: the first old-CommonLib plugin to run creates
`CommonLibSSEOffsets-v2-<version>` and later ones only open it, with no content validation, so a stale or corrupt
section left by another plugin is also a possible trigger.

**Experiments that would decide it (not yet run)**

1. Re-enable QJO and watch for any dialog that appears before SKSE's. The exact CommonLib text
   (`REL/Relocation.h(<line>): <msg>`) names the failure.
2. Temporarily rename `versionl2b-1-7-104-0.bin`. Expect CommonLib `failed to open address library file` and a game exit;
   that confirms the dialog and kill path works under CrossOver and that the loader reaches the open.
3. Set `WINEDEBUG=+seh` in the bottle environment. The exception code (`0xC0000005` access violation or `0xE06D7363`
   C++ throw) and the faulting address pin the site.

## 9. VR (inherited, not tested here)

- **VR.** SKSEVR reads `SKSEPlugin_Query`. A build that exports only `SKSEPlugin_Version` is silently skipped.
- **VR.** The Address Library for 1.4.15 is a separate mod and a CSV (`version-1-4-15-0.csv`), not the binary
  formats above. It reuses SE IDs but is far smaller (the generator's own example is about 3,900 rows), so an SE ID
  can have no VR entry and the offsets differ. That is why an SE plugin needs a VR port.
- **VR.** Some CommonLib classes have a different layout on VR. Members of those classes are only safe through
  accessors such as `GetRuntimeData()`. `RE::PlayerCharacter` is not fully reverse engineered for VR.
- **VR.** SKSE log: `Documents/My Games/Skyrim VR/SKSE/sksevr.log`. The AE-only failures in section 4 do not apply.

Confirm any VR statement before relying on it; the VR sections of `KNOWLEDGEBASE.md` have the same status.

## Sources

- CommonLibSSE-NG wiki, *Runtime Targeting*: <https://github.com/CharmedBaryon/CommonLibSSE-NG/wiki/Runtime-Targeting>
- CommonLibSSE wiki, *Query and Load*: <https://github.com/Ryan-rsm-McKenzie/CommonLibSSE/wiki/Query-and-Load>
- `alandtse/vr_address_tools` (VR database generator): <https://github.com/alandtse/vr_address_tools>
- The maintainer's AE 1.7.104 engineering notes (separate workspace; source of every *measured* entry).

Not confirmed against an official SKSE header: the exact `SKSEPlugin_Version` struct layout and the V5 flag position
quoted above; check them in the SKSE source for your version before patching a DLL.
