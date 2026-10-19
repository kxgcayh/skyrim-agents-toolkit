# Knowledgebase: ESP, xEdit, xelib and Spriggit

Part of the Skyrim modding knowledgebase; index: `KNOWLEDGEBASE.md`. Covers editing plugins: xEdit/xelib/Spriggit and record-level traps.

## xEdit / xelib / ESP Editing

### VMAD (Virtual Machine Adapter) Editing

- xEdit/xelib VMAD construction from scratch is fragile — known bugs with complex property structures.
- **VMAD must be read sequentially** — no lengths/offsets provided, making selective editing impossible without corrupting adjacent data.
- **xEdit cannot add new scripts to VMAD** (only remove properties). Adding script fragments requires correct `fragmentCount` or quest aliases corrupt.
- xEdit cannot parse VMAD records with illegal struct definitions (structs within structs, arrays in structs).
- For 25+ properties, the recommended approach is: create a template in Creation Kit, then copy the VMAD subrecord.
- For simple cases (1-3 properties), xelib can handle it.
- Alternative: use `GetFormFromFile()` in the script to avoid needing properties at all.
- Mutagen (C#) has robust, strongly-typed VMAD support for programmatic use.

*Sources: [UESP: VMAD Format](https://en.uesp.net/wiki/Skyrim_Mod:Mod_File_Format/VMAD_Field), [TES5Edit Issues](https://github.com/TES5Edit/TES5Edit/issues/544)*

### XEditLib.dll (Delphi FFI)

- See CLAUDE.md for the full list of quirks (UCS-2 strings, void Init/Close, uint16 WordBool, GetResultString pattern).
- Game mode: always use `GM_SSE` (4) for both Skyrim SE and Skyrim VR.
- Registry: reads from `Skyrim Special Edition` key, not `Skyrim VR`.

**xelib element path navigation quirk**: `getValue(record, 'PARENT\Child')` with nested paths fails ("Expected 2 arguments, got 1" from Koffi FFI) when the target doesn't exist at the first level. Use two-step navigation instead:
```js
const outer = xelib.getElement(recH, 'PARENT');  // e.g. 'DATA'
const inner = xelib.getElement(outer, 'Child');    // e.g. 'Radius'
const v = xelib.getValue(inner, '');               // empty path on element handle
xelib.setFloatValue(inner, '', newValue);
```
This applies to `getValue`, `setValue`, `setFloatValue` — all path-based functions work on element handles with empty paths, not on record handles with nested paths.

### Record Structure Gotchas

**ONAM Requirement:**
- Any ESM-flagged module containing overrides of temporary CELL children must include ONAM subrecords listing all overridden records
- Without proper ONAM, the game engine ignores overrides missing from it
- ESM files cleaned with Quick Auto Clean must be resaved to fix incorrect ONAM data

**ESP Special Behavior:**
- All references in ESP files are treated as permanent regardless of their Temporary flag
- Only ESL-flagged plugins properly support temporary references

**Record Flags:**
- Drag-and-drop in xEdit doesn't always copy record flags correctly
- Partial Form Flag removes all subrecords except EditorID

### Plugin Types (ESM vs ESP vs ESL)

| Type | Load Position | FormID Range | Limit | Notes |
|------|--------------|--------------|-------|-------|
| ESM | Top of load order | Full range | 254 total ESM+ESP | Supports temp refs properly |
| ESP | After ESMs | Full range | 254 total ESM+ESP | Treats ALL refs as permanent |
| ESL | Shares FE slot | xx000800-xx000FFF | 4096 | Only 2048 usable FormIDs |

**ESL Critical Rules:**
- All FormIDs must fall within `xx000800` to `xx000FFF` — exceeding causes crashes or data corruption
- xEdit's "Compact FormIDs for ESL" starts at `FE000xxx`; CK starts at `FE001xxx` (discrepancy)
- ESP→ESL conversion requires compacting FormIDs AND setting ESL flag

### Load Order & Override Resolution

- Last-loaded plugin version of a record is the "conflict winner" — overrides all lower plugins
- "Copy as override" uses the highest override visible to the target file (based on its masters)
- ModGroups hide non-winning overrides from conflict detection (prevent false positives)

### ESP Removal and Existing Saves (CRITICAL)

**NEVER remove/disable an ESP from the load order on an existing save.** The rule stands; the
reason originally written here was WRONG (corrected 2026-10-05, ledger-style note below).

- ~~Removing an ESP shifts downstream load-order indices, which resets their quest/script state.~~
  **Refuted.** The `.ess` carries a plugin-NAME table (`pluginInfo`, plus a separate
  `lightPluginInfo` list for ESL/FE plugins) and a `formIDArray` of save-time FormIDs; on load the
  game remaps save-time IDs to the current order — SKSE's `ResolveFormId` documents exactly that
  contract for co-save data ("takes a formID as it was when the save was made and writes the formID
  as it is when the save is loaded"). READ: UESP *Skyrim Mod:Save File Format*; CommonLibSSE
  *Serialization* wiki. "Remapped by plugin name" is INFERRED from that format, not quoted from a
  page — but no source supports a reset, and inserting/reordering is routine on long saves.
- **The real dangers of removal:** every form from the removed plugin is dropped from the save,
  while its script instances stay baked in (`Cannot open store for class "X", missing file?` in
  the Papyrus log); references, aliases, inventory items and other mods' scripts that pointed at
  its forms dangle. "Removing mods and continuing to use the same save game is not supported by
  the game" (CK *Save File Notes (Papyrus)*). That is why we lobotomize instead.

**Lobotomize instead:** Keep the ESP in the load order (its forms stay resolvable) but strip its functionality:
1. Remove compiled scripts (.pex files from `Data/Scripts/`)
2. Disable SKSE plugins (.dll → .dll.disabled)
3. Disable SPID distribution files (.ini → .ini.disabled) if applicable
4. ReSaver clean to remove orphaned script instances (with .pex gone, they won't re-create)

The ESP remains as a hollow shell. Only suggest removing ESPs when the user is starting a new game.

*Source: direct experience — the lobotomy approach is confirmed working.*

### Updating or Adding Mods on an Existing Save: Safety Rubric

**Classify every update by what it CHANGES, never by what the mod "is".** A "DLL mod" that also
ships `.pex` files is a script update; a "texture mod" that ships an ESP is a plugin update. Open
the archive and sort its files into the rows below, and the riskiest row present sets the verdict.

**Verdicts:** `SAFE` · `SAFE-WITH-STEPS` · `RISKY` (one at a time, checkpoint save between) ·
`DON'T` · **`UNCLEAR`, which means "not proven safe", never "probably fine".** It needs the archive,
a diff, or a DevBench test before it can move. For a mod not yet installed: `ADD-OK` ·
`ADD-WITH-STEPS` · `NEW-GAME-ONLY`.

#### 1. What the update changes, from no save footprint to deep

| Changes | Save footprint | Default verdict | Why / what to check |
|---|---|---|---|
| Textures, meshes, sounds, voice, strings, INI/JSON/TOML config | none | SAFE | Nothing is stored in the save. VR caveats still apply: PreWEAPON/PreSHIELD skeleton nodes CTD (gotcha #11), and a flat-screen `.swf` can replace a VR one. |
| Animations / behavior (`.hkx`, OAR configs) | none | SAFE-WITH-STEPS | No save data, but behavior output may need regenerating (Nemesis/Pandora). An OAR config change needs no regen. |
| SKSE DLL that writes **no co-save records** and registers no Papyrus natives | none | SAFE *if VR-loadable* | See §2. Revert = put the old DLL back, even on the same save. |
| SKSE DLL **that writes co-save records** | `.skse` co-save | SAFE-WITH-STEPS | SKSE hands each plugin its record `version` and leaves the format to the author. A DLL that ignores its own version field after a format change is UNSOURCED territory, so read the changelog for "save format" or "reset". Back up the `.skse` together with the `.ess`. |
| SKSE DLL **+ its `.pex`/`.psc` native declarations** | depends | SAFE-WITH-STEPS | The pair must move together. A mismatch logs `does not match existing signature` and the native goes unbound. |
| ESP record **field edits, FormIDs unchanged** | partial | SAFE-WITH-STEPS | Base-record edits apply on load, except for fields the save already changed (change forms). Visited cells, opened containers and met NPCs keep their baked state until a reset, so the "fix" may be inert on an existing save. That is lost value, not damage. |
| ESP: **records removed** that the save may reference | dangling refs | RISKY | Same as removal: dropped forms and orphaned instances. Needs a diff. |
| ESP: **FormIDs renumbered / compacted** | broken refs | **DON'T** | The save looks for the old IDs. ESLify: "do not compact... mods that have generated facegendata, scripts, or .seq files." |
| ESP: **ESL flag added**, IDs already within 0x800–0xFFF | slot move | RISKY | The plugin moves from a full slot to the FE light list. Remap should cover it (INFERRED), but community advice is new games only. |
| ESP: **ESL flag removed** | slot move | RISKY | UNSOURCED. Treat like the row above. |
| ESP: **master added** | none, if the master is present | SAFE-WITH-STEPS | The new master must already be installed and load earlier. Once in a save, masters can't be dropped. |
| ESP: **running quest** changed (stages, aliases, fragments) | baked | RISKY | QUST is a change form, so alias fills and stage state persist. Changes land only when the quest restarts (INFERRED). |
| `.pex`: **function bodies only** | none | SAFE | "Adding functions: no issues occur." A frame already on the stack finishes on the OLD code, and later calls use the new code. |
| `.pex`: **variable/property removed or renamed** | warning | SAFE-WITH-STEPS | The saved value is discarded with a log warning, and the warning stops after the next save. A rename counts as delete + add. |
| `.pex`: **property ADDED** | unresolved | RISKY / UNCLEAR | **Sources conflict:** the CK page says a new auto property takes the plugin's value, while a Skyrim LE report says instances already in the save stay `None`. Non-auto properties stay blank (gotcha #10). Settle it with DevBench on a save copy before trusting an update that depends on it. |
| `.pex`: **existing property's VALUE changed** in the ESP | baked | inert on an existing save | "Changing the value will not overwrite the value it has in the save game" (unless the property is `const`). The update's fix may never reach the save. |
| `.pex`: **script, state or quest removed** | orphans | RISKY | `Cannot open store for class`. ReSaver can clean unattached instances afterwards. |
| Long-running loop or registration in a changed script | persistent | RISKY | `RegisterForUpdate` and event registrations persist until unregistered. A loop on the stack keeps running old code until it exits. |

**Things that LOWER script risk:** the mod has a version-migration path, such as an SkyUI MCM
`OnVersionUpdate`, a maintenance quest on `OnPlayerLoadGame`, or an "update/reset" MCM button.
Read the decompiled source (Champollion) to confirm it actually exists.

#### 2. SKSE DLLs: the VR gate comes before save safety

"DLL-only = update whenever" is true for save safety only. A DLL can still be wrong for VR:
- **It must be a VR build**, or a CommonLibSSE-NG / CommonLibVR multi-runtime build that declares
  VR. An SE/AE-only DLL is at best refused by SKSE, which disables the feature silently, and at
  worst crashes. NG itself warns: "fundamental ABI incompatibilities between SE/AE and VR".
- **Check the VR-incompatible ledger first**, if you keep one: some releases of otherwise-VR-capable
  plugins (a Papyrus fix-up plugin, a crash logger) are known to break VR or a particular runtime.
- **Fork or rename migrations leave the old DLL behind, and SKSE loads BOTH.** A renamed fork's old
  DLL beside the new one is the classic case. After any update, check for an old-named sibling.
- **The proof is the SKSE log, not the install:** every DLL gets one result line in
  `Documents/My Games/Skyrim VR/SKSE/sksevr.log`: `loaded correctly`, `reported as incompatible
  during query|load`, or `does not appear to be an SKSE plugin`. Diff that file before and after
  each update.
- **Find stateful DLLs from the save itself:** `bash tools/cosave-cli.sh <save>.skse` lists the
  co-save records by opcode. JContainers (`JSTR`), PapyrusUtil (`STFV`/`STRL`/...), Papyrus Extender
  (`P3PE`), SPID and DbSkseFunctions are common writers; many opcodes will be unnamed.

#### 3. Adding a mod not yet installed

- **Appending, or inserting mid-order, does not corrupt other mods' saved state** (see the
  correction above). **It CAN change which plugin wins records other mods depend on.** Run
  `bash tools/skyrim-winner.sh conflicts <new.esp>`, plus a check of what the new plugin newly
  WINS, before activating.
- **Adding a scripted mod is a one-way door.** Removal is unsupported (above), so the only exit is a
  lobotomy. Weigh that before adding, not after.
- **Start-Game-Enabled quests.** Community sources (AutoSEQ README) say SGE quests still start on an
  existing save, but their dialogue, scenes and some fragments need a matching `Data/SEQ/<plugin>.seq`
  plus a save/reload. **One measurement disagrees**: a single SGE quest did NOT auto-start across
  multiple loads and needed `Quest.Start()` plus a save (MEASURED once, 2026-07-09; one quest, one
  load order, not a general rule). So: check that the SEQ file ships, then confirm `Quest.IsRunning`
  via DevBench after the first load. Don't assume it started.
- **Plugin slots:** count from the VR `plugins.txt` at decision time (full slots, light slots, and
  whether a VR ESL-support plugin is loaded); don't carry a number over from an earlier session.
- **The author's "requires a new game" is an author ruling, not an engine rule.** Respect it unless
  a diff proves otherwise.
- **Distribution mods (SPID/KID/SkyPatcher)** apply at runtime on every load, so they can be added
  without a save footprint, except for what they hand out (spells, perks, items), which actors
  then carry.

#### 4. The routine for every update session

1. **Baseline before touching anything:** copy the current `.ess` **and its `.skse`**, `plugins.txt`
   and `loadorder.txt`. Snapshot `sksevr.log`, and run `papyrus-triage` and `crash-triage` so
   "after" has a "before".
2. **One RISKY change at a time,** with a checkpoint save between, so a break can be bisected.
   SAFE items can be batched.
3. **Install through your mod manager (or a dry-run installer that backs up overwritten files and
   writes a manifest)**, so every file stays attributable.
4. **Verify from the outside after each batch:** the `sksevr.log` result line for every touched DLL,
   a DevBench load (`/api/health`, then `game loadLast`), and a Papyrus log diff for new
   `Cannot open store`, `does not match existing signature` or `not found` lines.
5. **If something breaks:** asset or DLL → restore the backup, on the same save. ESP or script →
   roll back to the pre-change save. Never "fix forward" a save that loaded a bad script state.

**Sources:** UESP *Skyrim Mod:Save File Format* and *Skyrim:Form ID*; CommonLibSSE *Serialization*
wiki; CommonLibSSE-NG *Runtime Targeting*; CK *Save File Notes (Papyrus)* and *Persistence (Papyrus)*
(read via the fallout.wiki mirror, because the Skyrim pages 403; VM rules are shared, but not
re-confirmed on the Skyrim page); Nexus forum 9922438 (new properties `None` on existing saves) and
13476332 (orphan log lines); ESLify mod page (SE 21618); AutoSEQ README; Nexus article *Mods,
Stability, and Save games* (Skyrim 801). Rows marked INFERRED or UNSOURCED are claims to test,
not facts.

### BSA/BA2 Archive Load Order

**Priority (highest to lowest):**
1. Loose files in Data folder (**always win** over everything)
2. Plugin-associated BSAs (in plugin load order)
3. Vanilla/engine-loaded BSAs (INI-specified)

- SSE/VR supports dual archives per plugin: `MyMod.bsa` + `MyMod - Textures.bsa`
- BSAs override each other based on position in archive load order; later-loading wins

*Source: [Modding Wiki: Asset Load Order](https://modding.wiki/en/skyrim/users/asset-load-order)*

### Casting Type Rule (Critical)

**All effects on a spell or enchantment must have the same casting type.** Mismatched casting types cause unpredictable behavior or spell failure.

### Navmesh Editing

- Navmesh **creation** is Creation Kit only — xEdit can only delete, not recreate
- Navmesh data is zlib-compressed; tools like TESVSnip can lose data during processing
- Adding too many objects to a cell with ESP-stored navmesh causes crash-on-exit (ESM navmesh is fine)
- Never fix deleted navmeshes from official .esm files — they are intentionally present

### ITM/UDR Cleaning Caveats

- **Not all ITMs are errors** — intentional ITMs exist for compatibility (keyword injections, compatibility patches)
- Deleted references (UDR) are a primary cause of crashes — should be undeleted + disabled
- But if a mod's purpose IS deleting something, UDR-cleaning breaks the mod
- Always review before saving after cleaning

### String Localization

- **STRINGS**: item names, actor names, race names, location names, quest objectives
- **ILSTRINGS**: NPC dialogue subtitles and voice-acted dialogue
- **DLSTRINGS**: book body text and quest descriptions
- Missing string files = blank text in-game
- xEdit does not validate or auto-generate string files

### Creation Kit Known Bugs

- **ESM flag bug**: CK does not set the 0x8 ESM flag when converting files to master type — requires manual correction
- CK can appear to save successfully but the .esp file disappears or becomes corrupted
- CK automatically removes null records on load — potentially silently corrupting data
- xEdit allows ESP files as masters; CK rejects and deletes ESP master references, leaving orphaned records
- Porting LE→SSE loses data (e.g., critical hit data on weapons) due to form version 43→44 changes

### Papyrus Fragment Pitfalls

- Fragments are stored inline in VMAD subrecords — fragile to corruption
- Fragment code must include all necessary function/event declarations
- Declaring properties in fragments can cause compiler errors blocking all further edits
- **Workaround**: add empty fragment, close quest window, reopen, edit code, then assign properties via Properties button
- CK validates fragments on save; xEdit does not — fragments edited in xEdit must be resaved in CK

### Master File Dependencies

- Removing a master file that is actively used leaves broken FormIDs with no recovery
- xEdit's "Clean Masters" detects unused master references and removes them
- Manually removing masters requires updating all referencing FormIDs — extremely error-prone

---

## ESP Creation via Spriggit

### Header Version
- **ESP header version must be 1.7** for SSE/VR plugins. Version 1.0 is flagged as Oldrim/wrong game by tools like Rybash.
- In Spriggit YAML: `ModHeader: Stats: Version: 1.7`
- A `spriggit-meta.json` file is required in the root of the YAML directory for deserialization. Format:
  ```json
  {"PackageName": "Spriggit.Yaml.Skyrim", "Version": "0.41.0", "Release": "SkyrimSE", "ModKey": "YourMod.esp"}
  ```

### Spriggit CLI
- Serialize: `spriggit serialize --InputPath "Data/Mod.esp" --OutputPath "/tmp/output" --GameRelease SkyrimSE --PackageName Spriggit.Yaml --PackageVersion "0.41.0"` (pass what `spriggit --version` prints)
- Deserialize: `spriggit deserialize --InputPath "/tmp/yaml_dir" --OutputPath "Data/Mod.esp"` (reads meta from spriggit-meta.json)
- `--GameRelease` is only for serialize, NOT deserialize
- **Install pinned: `dotnet tool install Spriggit.CLI --version 0.41.0`** (v4, 2026-10-05; was
  0.40.0). 0.41.0 (2026-07-02) ships only `tools/net10.0`, so it needs the **.NET 10 SDK**; per
  the drift audit a `dotnet tool update` on an SDK 6/8/9 machine failed with
  "DotnetToolSettings.xml was not found". 0.40.0 targeted net9.0. `tools/toolchain-check.sh`
  compares `spriggit --version` with the pin in `.config/dotnet-tools.json` (older or newer is
  a MISMATCH) and requires SDK 10+ for 0.41+, SDK 9+ before that.
- **`spriggit --version` exits 1 even when it works** (MEASURED 2026-10-05, 0.41.0, global tool and
  `dotnet tool run spriggit` alike): it prints `Spriggit version 0.41.0+...`, a stray `--version`, and
  `Spriggit.CLI 0.41.0+...`, then returns 1. Probe it by its OUTPUT, never its exit status, and not with
  `| grep -q` under `pipefail` (grep closes the pipe early and the SIGPIPE fails the pipeline). A fake that
  printed one line and exited 0 kept two new tests green while the real tool was never detected.
- **Two installs, both supported:** the global tool (`spriggit` on PATH) and `dotnet tool restore`'s local
  tool (`dotnet tool run spriggit`, answers only from inside the toolkit). `tools/spriggit-cli.sh`,
  `tools/esp-verify-wrapper.sh` and `tools/toolchain-check.sh` use the global one first, then the local one.
- **Use `-u` / `--ErrorOnUnknown` on serialize.** It makes Spriggit throw on unknown
  fields/records instead of dropping them silently — directly mitigates the silent-drop
  issue below. Make it the default for our workflow.

### ✅ Spriggit round-trip is lossless — compare YAML, not ESP bytes (re-measured 2026-10-05)
- A controlled no-op round-trip (`serialize → deserialize unchanged → serialize`) of
  a test ESP produced a **byte-for-byte identical file** (2026-05-18); an unmodified ESP
  round-trip to identical YAML with `:Skyrim.esm` references intact.
- ⚠ **The bytes are only stable once Spriggit has written the file.** MEASURED 2026-10-05 on a
  1549-byte ESP another tool wrote (RallysHandcart.esp, 8 STAT records): one
  serialize → deserialize gave the same size but **1247 of 1549 bytes different** (records come
  out in a different order), with **0.40.0 and 0.41.0 equally** (their two outputs are
  byte-identical, so this is not a 0.41 regression). Re-serializing gave YAML identical to the
  first serialize (10 of 10 files), and a second deserialize reproduced the first output byte for
  byte, so the first pass canonicalises the order and the result is a fixed point. Same result
  on SDK 10.0.401 with nothing else installed. **Prove a round trip by re-serializing and
  diffing the YAML; an ESP byte-compare fails on correct output.** Spriggit serializes
  exactly what the YAML says — it does NOT invent master-attribution corruption.
- The earlier belief that "Spriggit corrupts master prefixes on round-trip" was a
  **misdiagnosis**. The real culprit for re-mastered references (`:Skyrim.esm`
  → `:YourMod.esp`) can be an **over-broad ModKey remap during a manual mod split** —
  a blanket plugin-name replace that sweeps up legitimate field references.
- **Rule**: trust Spriggit round-trips. The real risk is *bulk ModKey/master remap*
  operations (mod splits, find-replace on YAML). Inventory cross-references (FormID +
  target master, per field) before and after any such operation and diff them.

### Tool: `tools/esp-verify-wrapper.sh` — cross-reference integrity guard
Catches the silent re-mastering / dropped-reference corruption class. Tool-agnostic
(guards Spriggit, xEditLib, CK, manual YAML edits). Snapshots are stored outside the
game dir (`~/.esp-verify-snapshots`), so it never trips the edit hooks.
- `bash tools/esp-verify-wrapper.sh snapshot Data/Mod.esp [...]` — before a risky op
- `bash tools/esp-verify-wrapper.sh verify   Data/Mod.esp [...]` — after; exit 1 +
  loud report on any reference whose target master changed or that vanished
- `bash tools/esp-verify-wrapper.sh guard Data/Mod.esp [...] -- <command...>` —
  snapshot → run command → verify, one shot
**Standing practice**: run `snapshot` before, `verify` after, ANY bulk ESP operation
(mod split, plugin rename, master-list edit, YAML find-replace). Verified 2026-05-18
to catch re-mastered / dropped references. If a change is intended, re-run
`snapshot` to accept it as the new baseline.

### ⚠️ Spriggit silently drops unknown YAML fields (CRITICAL)
- **Behavior**: If a YAML field name doesn't match a known Mutagen property, Spriggit deserialize drops the data with **zero error, zero warning, zero log line**. Deserialize returns success and the resulting ESP simply lacks that field.
- **Failure mode**: You can edit YAML, deserialize, deploy, load in-game — everything appears fine — and only notice when in-game behavior tied to that field doesn't manifest. Easily hours of mis-diagnosis.
- **Mandatory verification workflow when writing a NEW YAML field**:
  1. Edit YAML and deserialize to a temp ESP
  2. Re-serialize that temp ESP back to YAML
  3. Grep the re-serialized YAML for the field you just wrote
  4. If absent → field name is wrong (or the field doesn't exist for that record type). Try alternates.
- **Finding the correct Mutagen property name**: Inspect the DLL strings in your Spriggit install's `Mutagen.Bethesda.Skyrim.dll` (under the dotnet tools store, e.g. `~/.dotnet/tools/.store/spriggit.cli/<ver>/.../Mutagen.Bethesda.Skyrim.dll`). Use `grep -aoE "(get|set)_[A-Z][a-zA-Z]+" <dll> | sort -u | grep -i <pattern>` to enumerate property accessors.
- **Known name traps**:
  - MGEF Impact Data Set link → `ImpactData` (NOT `ImpactDataSet`, despite the linked record being IPDS)
  - xEdit's display name often diverges from Mutagen's property name — always verify against Mutagen, not xEdit
- **Discovered** during an MGEF clone for a custom-effect fix.

### Caprica Compilation
- Must run from `Data/Scripts/Source/` directory and use relative paths
- Requires `--flags "TESV_Papyrus_Flags.flg"` or compilation fails with "No user flags defined"
- `state` is a reserved word in Papyrus — cannot be used as a variable name
- To import VRIK API: copy `Data/Scripts/VRIK.psc` to `Data/Scripts/Source/VRIK.psc`
- Command: `../../../tools/Caprica/Caprica.exe --game skyrim --import "." --output "../" --flags "TESV_Papyrus_Flags.flg" "Script.psc"`

---

## xelib `setFormID`: the master-count high-byte trap

The "local" FormID xelib reports for a record a plugin **owns** is **master-count-prefixed**, not the
bare lower three bytes. A plugin with 4 masters owns records whose local form looks like `0x040008XX`.

Passing a bare `0x8B3` to `setFormID(rec, 0x8B3, true)` sets the high byte to `0x00`, which the engine
reads as **an override of `Skyrim.esm` form `0x0008B3`** — a silently corrupt record, and two plugins
doing it will collide. `GetFormFromFile` matches on the lower three bytes, so it can *appear* to
half-work, which is what makes this expensive to track down.

```js
const n = xelib.getMasterNames(file).length;   // e.g. 4
const localFid = (n << 24) | 0x0008B3;         // 0x040008B3
const copy = xelib.copyElement(srcRecord, file, true);   // asNew = standalone
xelib.setFormID(copy, localFid, true, false);            // local = true, fixRefs = false
```

**Verify any ESP edit with a full before/after Spriggit YAML diff** — stronger than a reference-only
check, because it also catches silently dropped fields. Serialize a backup and the live file, then
`diff -r`; only the intended delta should appear. (`--PackageVersion` is required whenever
`--GameRelease` / `--PackageName` are set.)

---

## Reused vanilla records can carry gating Conditions

If a reused vanilla magic effect or spell fires on **some** targets but not others — "hit or miss" —
suspect **Conditions on the MGEF** before anything else. Vanilla effects are often built for a specific
quest context and carry checks (`HasKeyword`, `GetRestrained`, and similar) that made sense there and
quietly gate your reuse. Conditions are evaluated when the effect applies; targets that fail simply get
nothing, with no error anywhere.

Checklist when reusing a vanilla magic effect that must fire reliably:

1. **Own the record first** (see the Own Your Records rule) so another mod's override cannot
   reintroduce the gate, then **strip the Conditions** on your copy.
2. **Check delivery.** A Constant-Effect / Self ability applied via `AddSpell` lands instantly and
   cannot miss; an Aimed projectile cast at a target can whiff entirely.
3. **Check Resist Value** — a separate axis from Conditions. Set it to `None` for unresistable.

Serializing your copy with Spriggit is the fastest way to actually *see* inherited fields you never set.

---

## `setGamePath` needs a trailing separator — and only tells you later, in `setGameMode`

Measured 2026-08-27. XEditLib wants the game path terminated with a separator. Give it
`C:/Games/The Elder Scrolls V Skyrim VR` and the **next** call fails:

```
SetGameMode failed
```

The error names the wrong function. `setGamePath` returns success; the path is only validated
when the mode is set, so the failure surfaces one call later with a message pointing at a call
that is fine. Worse, the trap is **call-order dependent**: it only bites when `setGamePath`
runs *before* `setGameMode`. Scripts that set the mode first never see it, which is why the
same bad path can look harmless in one script and fatal in another.

**Rule: terminate the game path before handing it to xelib.** Deriving the path (rather than
hardcoding it) makes this easy to get wrong, because `path.resolve()` never returns a trailing
separator:

```js
const last = dir.slice(-1);
return (last === path.posix.sep || last === path.win32.sep) ? dir : dir + path.sep;
```

Check **both** separator styles, not `path.sep` alone — game paths are Windows paths even when
the CI runner testing them is Linux, where `path.sep === '/'` and a backslash-terminated path
would be "fixed" by appending a second separator.
