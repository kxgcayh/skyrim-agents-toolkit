# Knowledgebase: Tools and assets

Part of the Skyrim modding knowledgebase; index: `KNOWLEDGEBASE.md`. Covers NIF, audio, music, BSA, saves, co-saves, crash logs.

## Save File Analysis

### .ess Save Format

SSE, AE, and VR saves all use the same `.ess` format with LZ4 compression. The compressed block is preceded by a `(decompressedSize, compressedSize)` uint32 pair. Typical decompressed sizes are 20-60MB.

**Decompressed structure:**
- **Bytes 0-5**: Preamble
- **Byte 5**: Regular plugin count (uint8), followed by length-prefixed UTF-8 plugin names
- **After regular plugins**: Light plugin count (uint16), followed by length-prefixed names
- **~100KB-22MB**: Global data tables, ChangeForms (binary, mostly non-ASCII)
- **~22MB+**: Papyrus string table (script names, variable names, type annotations)
- **End**: FormID reference tables (dense FormID arrays)

### What Can Be Done

- **Binary search** for any FormID (as LE uint32), string, or byte pattern
- **Count occurrences** to detect accumulation or duplication bugs
- **Read context** around any match (hex + ASCII dump)
- **Extract plugin lists** (both regular and light/ESL plugins)
- **String search** for script names, variable names, EditorIDs

### What Cannot Be Done (Without Full Parser)

- Parse structured Papyrus instance data (variable values, active effect state)
- Edit and write back a valid save (requires full format understanding)
- Browse by record type (use ReSaver for that — Java GUI)

### Common Debugging Use Cases

- **Orphaned scripts**: Search for a removed mod's script names. If still present, the save has orphaned instances.
- **Effect accumulation**: Search for a spell's FormID and count matches. More than expected = stacking bug.
- **Mod footprint**: Search for a mod's EditorID prefix to see how many references it left.
- **Save bloat tracking**: Compare decompressed sizes across saves.

*Tool: `scripts/read-save.py` — requires Python + `lz4` (pinned, hash-locked: `python -m pip install --only-binary=:all: --require-hashes -r tools/requirements-tools.lock`)*

---

## Headless Save Editing (ReSaver CLI)

ReSaver (the save inspector from FallrimTools) ships a Java **library** that can be driven headlessly — no GUI — to parse, cross-reference, and clean `.ess` saves **deterministically**. This supersedes raw binary byte-scanning for any structured work: instead of guessing at offsets you get parsed ChangeForms, the Papyrus instance/string tables, and a real reference index.

**Operations** (`bash tools/resaver-cli.sh <op> <save.ess> [args]`):
- `info` — high-level summary (plugin lists, counts, save metadata)
- `dump` — structured dump of parsed contents
- `find` — locate elements (forms, scripts, strings) by id/name
- `find-refs` — cross-reference: what points at a given form/instance
- `worries` — surface likely problems (orphans, unattached instances, suspicious accumulation)
- `recon` — sync-aware parse-coverage scan of ALL changeform body types (per-type ok/fail, failure
  categories, unknown extra-data types with predecessor histograms — the "phantom test")
- `changeform` — parse ONE changeform body (`--raw` adds changeflags + hex/base64; `--depth N`)
- `extradata-scan` — tally unknown extra-data types (`--type REFR` is the trustworthy subset)
- `changeform-diff` — structured + raw-tail diff of a changeform across two saves (noise-labeled)
- `globaldata` / `globaldata-diff` — global-data table survey / cross-save diff
- `set-global` / `set-var` — targeted value edits
- `clean` — remove orphaned/unattached script data
- `reset-havok` / `cleanse-formlists` / `remove-created` — ReSaver-delegated bulk cleanups
- `verify-roundtrip` — safety self-test: write + re-read + compare, report identical (temp discarded)

**Analysis overlay (read ops only):** the read/diagnostic ops layer a small overlay of *modified
ReSaver source* (Apache-2.0; `tools/resaver-cli/analysis-overlay/`) in front of the jar for extra
changeform parse coverage (extra-data types 16/135, QUST QuestInstances, REFR extra-data). **Write
ops always run the STOCK jar** so an authored parse fix can never reach `ChangeForm.write()` —
corruption safety. If the overlay can't compile against your ReSaver version, the wrapper falls back
to stock parsing automatically (basic ops unaffected).

**Write safety:** every write op is **dry-run by default** and only applies with `--apply`. An applied write always goes to a **NEW file** — it never overwrites the input save. Every `--apply` is additionally **verify-gated**: the output is re-read and compared to the written model, and on any unintended divergence the file is deleted and the op fails (fail-to-write beats silent corruption). As always, **loading the result in-game is the final validation gate.**

**Performance:** a full structured parse of a ~45MB save runs in about **2.4s**, including building the cross-reference index — fast enough to use interactively during debugging.

**Name resolution:** ReSaver works in FormIDs. Resolve FormID → EditorID on demand with `tools/resaver-resolve-names.js` (xeditlib-backed) so dumps and reference reports are human-readable.

**Requirements:** a JDK plus ReSaver's `ReSaver.jar` + its `lib/` folder in `tools/resaver-cli/`; `bash tools/resaver-cli.sh verify` checks both against the pinned SHA-256s. The wrapper auto-compiles its small driver on first run.

---

## Co-save (.skse) Structural Survey (cosave-info)

The `.ess` is only half the save state — SKSE mods stash their own data in a sibling **co-save**
(`SaveN_....skse`, same basename as the `.ess`). `bash tools/cosave-cli.sh <cosave.skse>` emits a
**read-only** JSON survey: the header fields plus a per-opcode chunk inventory (count + total bytes),
so you can see **which** plugins stashed co-save data (StorageUtil/PapyrusUtil, JContainers, per-mod
blobs) and **how much** — the mod-state landscape the `.ess` never exposes. It surveys chunk
*structure* (the `{u32 type, u32 version, u32 length}` walk, validated on real VR cosaves) and
resyncs on a desync, reporting coverage — it does **not** decode each chunk's plugin-internal format
(those are undocumented per-plugin). No install beyond Python 3; it never writes the cosave.

### Node/koffi helper exit codes are unreliable on Windows

Every xelib / koffi-based Node helper (resaver-resolve-names.js, the xelib scripts, etc.) can exit **non-zero (e.g. 127) even on full success** on Windows / Git-Bash — Node's stdio-flush-on-exit races against the resident native DLL's teardown. **Judge success by parsing the JSON the script prints, never by the process exit code.** Wrappers that gate on `$?` will report phantom failures.

---

## Music System

### MUSC vs MUST — Critical Distinction

**MUSC = Music Type container.** What the music manager tracks on its priority stack. Has FNAM flags, PNAM (priority + ducking dB), WNAM fade duration, TNAM (track list). The Papyrus `MusicType` form type maps to MUSC.

**MUST = Music Track Type.** Individual audio file entries. Referenced from MUSC.TNAM. They are NOT on the priority stack.

`DbSKSEFunctions.GetMusicTypeStatus(form)` always returns `-1` if passed a MUST FormID — the manager doesn't track individual tracks. Always pass the MUSC container.

Key MUSC FormIDs (Skyrim.esm): MUSCombat `0x0003418E`, MUSCombatBoss `0x000D777A`, MUSExploreMountain `0x000B9DCE`.

### FNAM Flags on MUSC Records

Bit 0 (0x01): Plays One Selection. **Bit 1 (0x02): Abrupt Transition** — switches immediately on trigger without waiting for current track's natural end. Bit 2 (0x04): Cycle Tracks. Bit 3 (0x08): Maintain Track Order. Bit 5 (0x20): DucksCurrentTrack (Mutagen naming; non-standard flag).

Vanilla MUSCombat FNAM = `0x09` (PlaysOneSelection + MaintainTrackOrder). Without Abrupt Transition, the engine queues combat music but waits for the current exploration track to finish before switching. PM exploration tracks have no cue points, so this wait is 60-120+ seconds — meaning short fights end before combat music ever fires.

**Correct Spriggit YAML flag names** for MUSC FNAM: `PlaysOneSelection`, `AbruptTransition`, `CycleTracks`, `MaintainTrackOrder`, `DucksCurrentTrack` (=0x20). Use these in Flags list. Do NOT try to set via xelib `setValue()` with a binary string — xelib writes the wrong value silently (verified: produced `0x34` instead of intended `0x0B`). Always use Spriggit YAML for FNAM edits on MUSC records.

**Personalized Music - Remade.esp** overrides MUSCombat FNAM to `0x24` = CycleTracks + DucksCurrentTrack. This is intentional — PM's 88 combat tracks require CycleTracks to cycle through the pool. Removing CycleTracks causes the engine to fail to play any track and leaves the music manager in a deadlocked state (MUSCombat never becomes Playing, exploration music is cut by AbruptTransition, total silence results). Always preserve PM's flags when patching MUSCombat.

Target FNAM for working MUSCombat with Abrupt Transition on top of PM's override: `0x26` = AbruptTransition + CycleTracks + DucksCurrentTrack. In Spriggit YAML:
```yaml
Flags:
- AbruptTransition
- CycleTracks
- DucksCurrentTrack
```

### Papyrus MusicType.Add() Bypasses Engine Ducking (Critical)

Calling `MusicType.Add()` from Papyrus and the engine's native combat trigger go through **different code paths**:

- **Engine-native trigger**: Applies PNAM ducking → lower-priority types become inaudible (MUSCombat has PNAM ducking=100dB, effectively muting exploration music)
- **Papyrus `Add()`**: Bypasses ducking entirely → exploration music stays audibly layered under combat music

This means any Papyrus-based "force-start combat music on combat entry" workaround will produce the "multiple tracks playing at once" symptom. Always rely on the engine's native combat trigger, not scripted Add().

### BossMusic.esm Stacking Pattern

BossMusic.esm has 13 MUSC records all at priority 2 (same as MUSCombat). The script `_A_BossMusic.pex` is attached to actors via VMAD. Each tagged actor independently calls `BossMusic.Add()` on combat entry (then `GoToState("PlaySong")`). `BossMusic.Remove()` fires only on `OnDying`.

Consequence: multiple boss-tagged actors in the same fight → multiple `Add()` calls stack at the same priority. Escaped/despawned actors leak entries (Remove() never fires). Stack accumulates over the session, eventually corrupting the music manager so MUSCombat won't re-fire on subsequent encounters.

Diagnostic: `DbSKSEFunctions.GetMusicTypeStatus(BossXxx)` going to `1` (Playing) simultaneously with `MUSCombat=1` confirms stacking.

### CombatMusicFixNG.dll — Incompatible with Multi-Enemy Fights

Despite its name, CombatMusicFixNG.dll **must not be used** here. It hooks actor-death events and calls `Game.GetPlayer().IsInCombat()`. In a multi-enemy fight, there's a brief window after killing one enemy where `IsInCombat()` returns false before the player acquires the next target. The plugin force-terminates combat music in that window even though combat is ongoing. Result: combat music plays 3-4 seconds then stops mid-fight. Keep disabled.

---

## Orphaned Extended Skeletons -> Havok Contact-Solver CTD
A partially-uninstalled adult-creature mod (the More-Nasty-Critters / Creature-Framework family) can
leave orphaned extended `skeleton.nif` files in `Data/meshes/actors/<creature>/character assets/`
after its ESP, physics configs, and Creature Framework are gone. The extended ragdoll/collision
(`bhkRagdollConstraint` / `bhkRigidBody` / `bhkCapsuleShape`) can fault the Havok contact solver:
`EXCEPTION_ACCESS_VIOLATION` in the physics path (`hkpConstraintInstance` / `hkpRigidBody` /
`hkpSimulationIsland`) while the creature contacts world geometry, independent of combat. Fix: restore
the vanilla `skeleton.nif` for that creature (extract from `Skyrim - Meshes0.bsa`).

**Tooling note**: nif-tool.exe / the AutoMod `nif` module CANNOT inspect Havok `bhk*` collision
(textures/strings/shaders only). Use NifSkope (GUI) for collision-block inspection.

---

## Audio & Tooling Lessons

### Freeze/Timestop scripts that kill enemies → vanished corpses (the JCE "disappear" fix)

**Symptom**: an enemy hit by a timestop/freeze effect (AI disabled + paralyzed) is killed *while
frozen*, then **vanishes** instead of leaving a corpse — specifically *"when the effect finishes."*

**Root cause**: the freeze MGEF's `OnEffectFinish` calls `EnableAI()` / clears `Paralysis` on the
target **without checking `IsDead()`**. Re-animating a corpse at freeze-end despawns it. (`OnEffectStart`
is usually guarded against dead targets; `OnEffectFinish` often is not.)

**Fix (general, reusable)** — guard the finish handler so it never touches a dead actor:
```papyrus
Event OnEffectFinish(Actor akTarget, Actor akCaster)
    if akTarget.IsDead()
        return   ; don't re-enable AI / clear paralysis on a corpse — that despawns it
    endif
    ; ...existing un-freeze cleanup...
EndEvent
```
The despawn happens at *finish*, not start (commenting out a ragdoll-removal call at OnEffectStart is
the wrong fix). The fix is the `IsDead` early-return at the top of `OnEffectFinish` (confirmed working).

### `PushActorAway` argument direction (caused a self-knockback bug)

Signature: `ObjectReference.PushActorAway(Actor akActorToPush, Float aiKnockbackForce)` — **"pushes the
passed-in actor away from THIS object."** So `X.PushActorAway(Y, f)` pushes **Y** away from **X**.
- To knock an **enemy** away from the player: `Caster.PushActorAway(enemy, f)` ✓
- The reversed form `enemy.PushActorAway(Caster, f)` pushes the **PLAYER** ✗ (enemy takes damage but no
  knockback; the player gets launched — the exact symptom that flagged this).

### AutoMod CLI cannot read MGEF / SNDR internals

`automod esp view-record` returns **empty `Properties`** for MGEF and SoundDescriptor (SNDR) records
(it surfaces EditorID/RecordType only). To read their fields (archetype, delivery, area, scripts,
sound file paths) use **xelib** or **Spriggit serialize**. Gotcha: the MGEF archetype field is literally
**misspelled `Archtype`** in the record — xelib path `Magic Effect Data\DATA - Data\Archtype`. A scan
using `Archetype` silently matches nothing.

### WAV → XWM audio pipeline (for SNDR sound files)

AutoMod `audio wav-to-xwm` needs `xWMAEncode.exe` (present at `src/xWMAEncode.exe`); it requires an
`-o` output path. xWMAEncode only accepts **1, 2, or 6** channels and PCM input — multichannel sources
(e.g. a 7.1.4 WAV) fail with `XWMA_E_UNSUPPORTED_CHANNELS`. Normalize first with ffmpeg, then encode:
```bash
ffmpeg -y -i "in.wav" -acodec pcm_s16le -ar 44100 -ac 2 "_pcm.wav"
src/xWMAEncode.exe "_pcm.wav" "Data/Sound/FX/.../out.xwm"
```
A SNDR pointing at a **missing** `.xwm` just plays silence (no crash) — files can be dropped in later.

### Adding new SNDR/SOUN records via Spriggit + the Write-tool `/tmp` gotcha

Spriggit lays records out as per-record YAML in typed folders: SNDR → `SoundDescriptors/`, SOUN →
`SoundMarkers/`, named `<EditorID> - <FormID>_<Plugin>.yaml`. To add a sound: serialize, clone an
existing SNDR (set `SoundFiles: [FX\...\file.xwm]`) + SOUN (set `SoundDescriptor:` to the new SNDR),
deserialize.
- **Spriggit is on PATH directly as `spriggit`** here (NOT `dotnet tool run spriggit`).
- **CRITICAL gotcha**: the Write tool's `/tmp` and Bash's `/tmp` resolve to **different** locations on
  this Windows setup — files Written to `/tmp/...` are invisible to a Bash/Spriggit `/tmp/...` read, so
  the new records silently never deserialize. Use an **explicit absolute path** (e.g. a dedicated `spriggit-tmp/` dir OUTSIDE `/tmp`) for the serialize OutputPath *and* the Write paths so both tools agree.

---

## NIF Tooling — PyFFI Limits, PyNifly, and CTD Prevention

**PyFFI 2.2.3 has two HARD limits (both cost us real debugging):**
1. **Cannot read BSTriShape at all** (`Unknown block type 'BSTriShape'`) → can't touch any SSE-format
   (user_version_2=100) NIF.
2. **Authored animation controllers CTD the engine.** PyFFI can construct
   NiControllerManager/NiControllerSequence blocks and re-read them fine, but the written NIF
   **crashes-to-desktop the instant it's placed** — PyFFI omits the header string-table registrations
   the engine requires. (Confirmed in-game 2026-06-15: a PyFFI-authored `SpecialIdle` spinner CTD'd on
   `placeatme`, despite a clean PyFFI readback.) Also: building from a **fresh `NifFormat.Data()`** corrupts
   the header on write — always load an existing valid NIF and restructure it.
   → PyFFI stays useful ONLY for LE-format **NiTriShape geometry edits** (vertex shifts, bounds, the
   blade split/subdivision).

**Not a real limit, despite what it looks like: PyFFI does NOT need a dedicated Python 3.10.** The
only actual Python-version blocker is one unconditional `from distutils.cmd import Command` in
`pyffi/utils/__init__.py` (an unused doc-building helper), and `distutils` was removed from the
stdlib in 3.12 (PEP 632) — installing setuptools beside it (hash-locked: `python -m pip install --only-binary=:all: --require-hashes -r tools/requirements-tools.lock`) fixes it, since setuptools ships its own
vendored `distutils` plus an import shim (the official PEP 632 migration path). Verified end-to-end
on Python 3.14. The separate `time.clock` monkey-patch (removed in 3.8, [still open upstream](https://github.com/niftools/pyffi/issues/80)) is unrelated and still required regardless of interpreter version.

**PyNifly is the fix** (installed `tools/pynifly/io_scene_nifly/`, prebuilt DLL, no Blender; verified on PyNifly 27.2.0,
the toolkit's one pinned version (library and Blender add-on), where the DLL actually loaded is `io_scene_nifly/NiflyDLL.dll` (the zip's
`io_scene_nifly/pyn/NiflyDLL.dll` is never loaded) and `from pyn import pynifly`, after putting `io_scene_nifly` on `sys.path`, loads it itself;
the animation-authoring round-trip was re-validated 2026-10-06: 27.2.0 and 29.1.0 author byte-identical controller stacks. 29.1.0 is NOT pinned: its Blender add-on strips BSEffectShaderProperty on an import/export round trip when the diffuse texture is not on disk, and a Blender round trip drops animation controllers on both versions). Wraps ousnius/nifly (the
BodySlide/Outfit Studio engine). **Reads/writes SSE incl. BSTriShape** AND has correct `.New()`
controller-authoring factories. Use it for any BSTriShape NIF and ALL animation authoring. See
the `SpecialIdle`-named NiControllerSequence auto-loops on a placed Activator with zero scripting
(a self-spinning mesh effect with no Papyrus).

**CTD-PREVENTION PRINCIPLE (general, not just NIFs):** a crash-to-desktop must be caught in tooling,
not the user's headset. The miss that taught this: I "verified" a PyFFI NIF by reading it back **with
PyFFI** — same buggy tool, so self-consistent ≠ engine-valid. Standing gates before any in-game test:
(1) author with **valid-by-construction** tools (PyNifly, not hand-rolled PyFFI); (2) **cross-validate
with an INDEPENDENT, stricter parser** (PyNifly for NIFs — and check the SPECIFIC crashable subsystem,
e.g. the controller, since a geometry-only read passes even when the animation stack is malformed);
(3) known-good structure diff. **Cathedral Assets Optimizer was NOT adopted** — it's a Nexus-only
*optimizer* that would mutate LE-format meshes (toward BSTriShape); PyNifly is the read-only gate.

**STRETCHING A BLADE MESH (geometry lessons):** matrix-stretching a sparse low-poly blade by a large
factor tears it into invisible slivers, and the worst offenders are the thin cutting-EDGE triangles
(they taper to ~0 area). Two fixes: (a) **subdivide** the blade first (PyFFI midpoint subdivision,
crack-free via a shared edge-midpoint dict) so the stretch spreads across many short segments instead
of a few long ones; (b) **keep the split threshold on a UV/material boundary** — a threshold that pulls
geometry whose UVs map to a different texture region (e.g. a gold guard vs a steel blade) into the
stretch makes that region smear and tear. Thicken the THIN dimension (~x2) to give the edge bevel some
body.

---

## NIF Validation & Render Trichotomy
Three independent gates for an authored/edited mesh — run them in order before any in-game test:
- **PyFFI** — LE-format NiTriShape geometry edits (vertex shifts, bounds, mesh split/subdivision).
  Cannot read BSTriShape; never author animation controllers with it (CTD).
- **PyNifly** — reads/writes SSE BSTriShape, authors animation/controller blocks correctly, AND is the
  independent PARSE gate (a battle-tested second parser that catches malformed files a same-tool
  readback misses). Check the specific crashable subsystem (e.g. the controller) — a geometry-only
  read passes even when the animation stack is malformed.
- **NifSkope (GUI) + headless Blender** — the RENDER gate. NifSkope is the independent visual
  validator; Blender (headless, PyNifly addon) repairs meshes and renders a NIF to PNG so a fix is
  confirmed in chat before loading the game. Blender shares the nifly library, so it is NOT an
  independent parser — use it for repair/render, not parse-validation.

---

## Crash logs: CrashLogger writes `.LOG`, not `.txt`

Recent CrashLogger versions write crash logs as **`.LOG`** into `Documents/My Games/<game>/SKSE/` and
open the newest one in Notepad. If you are looking for `crash-*.txt` and finding nothing, that is why.
Sort that folder by modified time after a CTD.

**The dangerous case is not finding nothing — it is finding some.** Both extensions coexist in
that one folder, so a `crash-*.txt` glob does not fail, it reports a confident total built from
whichever half it matched. Measured 2026-08-27 on the dev install: **8 `.txt` (all June 2025)
beside 20 `.log` (2026)**, and the first version of `crash-triage.py` cheerfully reported
"8 log(s)" — a full year out of date, with an accounting check that balanced perfectly, because
a denominator can only account for what it was given. Match `crash-*.(txt|log)`
case-insensitively, and keep the `crash-` prefix so the plugin's own `CrashLogger.log` is not
counted as a crash.

**Trainwreck** (Nexus 106440) names its dumps by timestamp only (`2026-10-22-22-14-42.log`, no `crash-`
prefix) and writes them to `SKSE/Crashlogs/`. `crash-triage.py` reads that subfolder and that name shape;
a `crash-*` glob finds none of them.

**First moves on a new CTD (measured 2026-11-02, AE 1.7.104).** Before porting or patching the plugin that
changed last: (1) compare the crash signature with and without the suspect, and (2) check every active
plugin's MAST records against `plugins.txt`. A CTD right after the main menu at `SkyrimSE.exe+1DCB60`
(`mov rax,[rcx+0x30]`, called from `+2DF22B`, `rcx = [PlayerCharacter+0x40] + 0x30`, i.e. the player's base
object is null) was identical with and without the blamed DLL; the cause was an enabled patch plugin whose
master had been deleted. MO2 deleted it: installing an archive into an existing mod folder with **Replace**
removes that folder's files first.

---

## AutoMod BSA extract/repack needs `bsarch.exe`

AutoMod's `archive` module reads a BSA index natively for `list`, but `create`, `extract`,
`extract-file`, and `repack` shell out to **BSArch.exe** — without it they fail with `BSArch not found`
(`create` MEASURED 2026-10-05). Place `bsarch.exe` (BSArch 1.0, the tested build; hash in docs/installing-tools.md *Pinned downloads*) at `<build-output>/tools/bsarch/bsarch.exe`, i.e.
under the same `bin/Release/net10.0/` folder the wrapper runs the DLL from (`net8.0/` before v4: the
v4 retarget builds into a NEW folder, so move an existing copy across). BSArch also refuses an
`extract --output` folder that does not exist yet (`EInvalidArguments: Folder does not exist`);
create it first. **It lives under `bin/`, so any `dotnet build` or `clean` of AutoMod wipes
it** — keep a canonical copy elsewhere and re-place it after a rebuild.

Similarly, `audio wav-to-xwm` needs `xWMAEncode.exe`, which is not bundled. It is often simpler to call
`xWMAEncode` directly than to go through AutoMod.

**AutoMod on .NET 10 (v4, MEASURED 2026-10-05, v1.11.2 = e1c34ea, SDK 10.0.401 with no other SDK or
runtime installed).** Upstream targets net8.0; `bash tools/automod-cli.sh --rebuild` pins SDK 10 in
`tools/automod/global.json` and retargets `Directory.Build.props` to net10.0 (one line, a local
patch), then builds the Cli project. It built with 0 errors (2 harmless NU1510 warnings) and on 10.0.12
alone ran: `esp create`, `add-weapon` (dry-run and real), `add-spell/-armor/-global/-quest/-npc/-book/
-perk/-faction`, `info`, `view-record`, `list-masters`; `nif info`; `archive list/create/extract`
(byte-exact); `mcm create/add-toggle/validate`; `papyrus status/generate/validate/download/compile/
decompile`; `audio info/create-fuz/extract-fuz` (byte-exact). Spriggit 0.41 read the AutoMod-written
ESP and round-tripped it byte-identical. Upstream's unit tests: 68 of 69 pass on net10.0 — and the
same 68 of 69 on net8.0: `ResultTests.ToJson_FailedResult_ContainsSuccessFalse` fails on both (a
failed result's JSON omits `"success": false`), so it is upstream's, not .NET 10's. Rebuilding over an
old net8.0 build needs no clean. A net8.0 build does NOT start on a 10-only machine without
`DOTNET_ROLL_FORWARD=Major`; the wrapper refuses it and says to `--rebuild`.

## Reading a BSA or plugin header without AutoMod or xEdit (measured 2026-11-04, macOS)

When neither AutoMod's DLL nor `bsarch.exe` is available, an SSE BSA v105 with archive flags 3 (directory and
file names, no default compression) reads in about 30 lines of Python: header `<4s8I`; folder records `<QIIQ`;
then per folder a bzstring name plus `<QII` file records; then the file-name block (header field 7 is its
length). Bit `0x40000000` of a file size toggles compression for that file, and a compressed block starts
with its uncompressed size (4 bytes), so asset versions compare by size without extracting. Used to pull two
`.pex` out of a 40,643-file BSA and to compare 44k archive entries across a load order.

Header-level plugin parsing is equally small: TES4 MAST subrecords, a GRUP walk, and zlib for records with
flag `0x40000`. That was enough for overlap counts, full override chains (767 plugins in a few minutes) and
LVLO diffs. It does not replace xEdit's field-level conflict view, and it reads files, not the MO2 VFS.

## FOMOD Installers: Authoring and Mod Manager Behaviour (measured 2026-11-01, MO2)

**Archive layout.** `fomod/info.xml` + `fomod/ModuleConfig.xml` + one folder per installable option. Each
`<folder source="X" destination=""/>` must name a folder that exists in the archive; a build script should assert
the set of `source=` values equals the folders it packs. Exclude OS litter (`.DS_Store`, `Thumbs.db`).

**Schema validation.** `xsi:noNamespaceSchemaLocation="http://qconsulting.ca/fo3/ModConfig5.0.xsd"` is a thin file
that `<xs:redefine>`s `http://qconsulting.ca/gemm/ModConfig5.0.xsd`. The gemm schema has `type=" xs:string"`
(leading space) on one attribute, which libxml2 refuses to compile. To validate offline: download both with
`curl -L` (the plain URL returns a redirect page), strip the space, point the redefine at the local copy, then
`xmllint --noout --nonet --schema ModConfig5.0.xsd ModuleConfig.xml`. Well-formed XML is not enough: the schema
catches misplaced elements that a mod manager may silently ignore.

**One plugin per setup (variants).** When a patch must master a different set of optional plugins depending on
what the user has (patch A, patch B, both; optional addon or not), build one plugin per combination, all with the
same file name, each in its own option folder, and let the installer pick. Install exactly one: two copies of
the same overrides confuse load-order sorting and double-apply. Tell the user to reinstall when they enable or
disable one of the detected plugins: the old variant is then a missing master or loses to a plugin it no
longer masters.

**Optional support for another mod: an add-on plugin, not more variants.** When a supported mod is optional
and only adds fields to a few records the patch overrides, ship a small separate plugin that masters both the
main patch and that mod and copies just those fields on top of the main patch's records. One add-on fits every
variant if the main records it touches are identical across variants (assert it in the build). In the FOMOD put
it in a `SelectAny` group: `defaultType NotUsable` (greyed out, it would be a missing master) and one pattern
`Recommended` (checked) when the mod's plugin is `Active`. In `SelectAny`, MO2 disables only that option.

**Auto-detecting active plugins: the layout that works in MO2.**
- One visible step, one `SelectExactlyOne` group, one option per variant. Do not hide the choice entirely in
  `conditionalFileInstalls`: the user then cannot see which variant is installed, and the archive's identical
  plugin names in several folders read as "installs all of them".
- Make **exactly one** option `Recommended` for any setup; every other option `Optional`. Never rely on option
  order to pick among several Recommended ones: MO2's source checks only the first Recommended, yet a real MO2
  build preselected the LAST of several.
- MO2 uses the **first matching pattern** of an option's `dependencyType` (`getPluginDependencyType`). So per
  option: pattern 1 `Optional` when any detected plugin the option does NOT need is `Active` (an `Or` of
  `fileDependency state="Active"`), pattern 2 `Recommended` when all plugins it needs are `Active`, default
  `Optional`. Only positive `Active` checks; no `Missing` / `Inactive` logic needed.
- **Do not use `Required` for auto-selection** in a `SelectExactlyOne` or `SelectAtMostOne` group: MO2 then
  disables EVERY option of the group by design, and the user cannot change or even clearly see the selection.
  `NotUsable` defaults have the same effect on the other options.
- **Do not gate a patch FOMOD with `moduleDependencies`.** It is a hard gate: one required plugin missing or
  inactive (no USSEP, Vortex not yet deployed, a merged or renamed plugin) and the installer refuses to run; the
  user sees only "problem with the fomod". A failing nested `<dependencies operator="Or">` gives MO2's "installation
  as fomod Failed No conditions were successful in an 'OR' clause" (user report 2026-11-02, both target plugins
  installed but not active). Let the plugin's masters and the game's missing-master warning do the gating.
- MO2 answers `fileDependency` for `.esp/.esm/.esl` from its live plugin list: a plugin present but disabled is
  `Inactive`, so "enable first, then install" belongs in the instructions.

**Two independent choices without duplicating the auto-detect group** (a user pick x an auto-detected setup;
XSD-valid and simulated for every setup, not yet manager-tested): options install no files and only set
`conditionFlags`; `conditionalFileInstalls` (after `</installSteps>`, ModConfig 5.0 order) maps each
`flagDependency` pair to one folder. Options keep their `typeDescriptor` patterns, so preselection is unchanged
and the choices stay visible. A FOMOD cannot read mod file priority, so a choice that depends on which mod wins
loose files must be a user pick with the priority rule in its description.

**Self-check before handing it to a user.** Write a small evaluator over `ModuleConfig.xml` (And/Or over
`fileDependency`, first-match patterns, defaultType) and run it over every Active/Inactive/Missing combination of
the detected plugins: assert the install is refused exactly when it should be and that exactly one option is
Recommended, the right one. XSD validation plus this simulation still do not prove a manager's behaviour; one
real install test per manager does.

**Mod name shown by MO2.** The installer window title is MO2's guess from the archive file name, set before
`info.xml` is read. For a file name without a Nexus `-<modid>-` part, MO2 keeps only letters, `_` and spaces up to
the first other character (`Foo - Bar Patch.zip` becomes `Foo`). In a real MO2 build the Name box also kept that
guess although `info.xml` had `<Name>`. For a Nexus download MO2 uses the `.meta` mod name (the page title), so
users are unaffected; for local testing, type the name. Fill `<Author>`, `<Version>` and `<Website>`: MO2 shows
them on the installer page.

**Vortex:** not measured. Its installer evaluates the same XML, but preselection and `Required` behaviour may
differ; test once before release.

## Releasing: MO2 `meta.ini` and the Nexus API

- (Source-read 2026-11-03, not verified with a real install.) MO2 keeps a `meta.ini` bundled at the archive root, then overwrites only installationFile, repository,
  author, uploader, uploaderUrl, nexusFileStatus, plus gameName/modid/version when the download's `.meta`
  supplies them. A manually added zip has a blank `.meta` (`version=0.0.0.0`), so the bundled version is lost.
  `url` + `hasCustomURL=true` set "Visit web page". Quote values containing commas (QSettings reads them as
  lists).
- (Measured 2026-11-01.) Nexus API v1 `/games/<domain>/mods/<id>.json` returns the full description (BBCode) but **not** the
  Permissions tab; fetching the page itself gets a Cloudflare 403. Permission terms differ between sibling pages
  by the same author: read each page, never copy one page's terms to another.
- (Source-read 2026-11-03, not yet run live.) Nexus v3 (`https://api.nexusmods.com/v3`, `apikey` header) can only add a new version to an **existing**
  file (`POST /mod-files/{file_id}/versions`); the mod page and its first file are made on the website.
  Upload: `POST /uploads/multipart` -> PUT parts to the presigned URLs (no key) -> POST the completion XML ->
  `POST /uploads/{id}/finalise` -> poll `GET /uploads/{id}` until `available`. Changelog:
  `POST /mods/{id}/changelogs` (appends). Source: `Nexus-Mods/upload-action` commit 98532f7.
