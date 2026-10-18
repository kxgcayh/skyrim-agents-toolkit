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
game build and is wrong on any other. Re-derive them per build (section 6) and keep them with the plugin.

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

## 7. VR (inherited, not tested here)

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
