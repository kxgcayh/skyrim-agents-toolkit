# Knowledgebase: VR

Part of the Skyrim modding knowledgebase; index: `KNOWLEDGEBASE.md`. Covers VR vs SSE differences, VR input, VR Papyrus findings, VR physics (inherited, untested in this fork).

## VR vs SSE Differences

### Engine Foundation

- Skyrim VR is functionally based on SSE but is a **separate engine build** — not compatible with SSE or Oldrim
- Game mode in XEditLib: `gmSSE=4` (use this for VR — there is no VR-specific mode)
- Registry key: `HKLM\SOFTWARE\WOW6432Node\Bethesda Softworks\Skyrim Special Edition` (SSE key, not VR)

### SKSE: SE vs VR

- SKSEVR is a **completely separate build** from SKSE64 (SE)
- Address libraries are entirely different — thousands of addresses differ between SE and VR
- Manual offset updates required when porting SE plugins to VR
- CommonLibSSE NG supports SE, AE, and VR in a single multi-runtime build
- **#1 mod breakage cause**: mods requiring SKSE64 (not SKSEVR) won't load
- Entry points, Address Library files, runtime targeting and what is AE-only (not VR): `docs/skse-internals.md`
- The SKSE 2.3.1 pre-load gate and the exported version struct: `docs/skse-internals.md` section 7. Per-plugin AE 1.7.104 fixes and hook maps: `docs/ae-1-7-104-plugin-fixes.md`. Patching a DLL you may not redistribute: `docs/binary-patcher-guide.md`, `docs/licensing-and-delta-patching.md`

### Animation System

- VR uses the same Havok Behavior graph as SSE — `.hkx` files and Nemesis patches work
- The critical difference: VR's "first person" is the HMD's physical orientation, not the game camera
- `SetAngle`, `ForceThirdPerson`, `ForceFirstPerson` do not control the HMD view
- `SetVehicle` causes HMD desync — game moves player position while HMD anchor stays physically fixed

**Skeleton:**
- VR is extremely particular about skeleton structure
- **Remove PreWEAPON and PreSHIELD nodes** (keep vanilla skeleton) or CTDs occur
- VR appears to do text-contains search for WEAPON/SHIELD nodes, gets confused by Pre* prefixes
- XP32 First Person Skeleton CTD Bugfix critical for custom skeleton users
- VRIK maps head and arms via IK rig, displays virtual body matching player movements

**Animation Replacers:**
- OAR (Open Animation Replacer): native VR support
- DAR animations auto-converted to OAR format on load
- Animation priorities must be higher than MCO/ADXP for proper playback

### Camera System

- VR uses headset tracking for primary camera (HMD position/rotation)
- `PlayerCamera` exists but is **subordinate to VR camera**
- Standard SE `PlayerCamera` interactions may not function identically
- `Game.ShakeCamera()` adds noise to the third-person camera node — in VR this is mostly inert (minor artifacts at best, nauseating at worst). Generally safe to leave in.

### Player Control Functions in VR

**CORRECTED + VERIFIED from reference VR mod (`JudgementCutEnd.esp`):**

- `DisablePlayerControls()` does **NOT** prevent VR controller thumbstick movement. VR controller input (thumbstick/wand movement) is a separate engine-level input system that bypasses the traditional control disable flags. Calling it during a scripted sequence does nothing to stop the player from walking around.
- **`DisablePlayerControls(True, True, False, False, False, True, True, False, 0)` + `Actor.SetDontMove(True)`** together is the correct approach. `SetDontMove` is the key — `DisablePlayerControls` alone or `SetRestrained` alone do not stop VR movement. Source: decompiled `EndMagicEndScript.pex` from `JudgementCutEnd.esp`, confirmed working in VR.
- **`Actor.SetRestrained(true)`** was tried but also NOT effective for VR movement. It operates at the actor level (not the input level), intercepting movement before the VR input reaches the character. Per CK wiki: "disables player movement, camera switching and camera rotating." Confidence: 85% (tested in VR context).
- `Game.SetPlayerAIDriven(true)` can be combined for belt-and-suspenders — overrides player control with AI behavior.
- Over-encumbrance (adding heavy items / reducing carry weight) only slows to walk speed — does NOT prevent movement.
- Paralysis effects work but trigger ragdoll physics — avoid for cinematic sequences unless using a "no-ragdoll paralysis" mod.
- `ForceActorValue("SpeedMult", 0)` prevents movement but feels unresponsive (controller input still registered, character just doesn't move).
- **VR-native solutions** (VRIK Actions, Disable Input VR SKSE plugin) work best but add dependencies.
- `EnablePlayerControls()` still needed to restore menu/combat/other input; pair with `SetRestrained(false)`.

*Source: in-game testing; CK wiki; web research on VR mod implementations*

### UI System

- UI completely reworked for VR controllers/motion input
- Menu processing limited to up/down/right/left controller signals
- SkyUI incompatible — SkyUI VR fork needed
- Book content treated as 2D HUD layer; text scaled if UI scaling applied

### ImageSpace (Post-Processing)

- Off: fixes some UI problems but creates visible darker/lighter seam between eyes
- On: fixes visual seam but breaks UI in some configurations
- Core tension between VR visual requirements and UI rendering
- Community Shaders has known broken UI issues in VR

### Weather

- `Weather.ForceActive(True)` snaps instantly — no transition. Jarring in a headset but functional.
- `Weather.SetActive()` transitions over ~2 seconds (gradual). Smoother for VR.
- Weather renders in full stereo in the headset.

### Physics & Havok

- Havok locked to **60Hz by default** — not updated for VR 90Hz requirement
- INI tweak raises rate to 90Hz for VR
- **Player collision changed**: player capsule vs enemy capsule (SE) → player capsule vs **enemy ragdoll** (VR)
- Player capsule narrower in VR than base game
- These physics differences affect melee combat significantly

### Input & Controllers

- VR controllers are primary input — mods assuming keyboard/mouse fail
- Locomotion: teleport vs smooth (VR-specific)
- Hand-based item interaction (picking up, holding, throwing via HIGGS)
- Motion archery and melee (hand gestures trigger attacks)

### VR Playroom

- Scripts running in VR playroom cause incompatibilities
- Papyrus Tweaks NG pauses non-VR-playroom scripts until player exits

### OpenComposite / OpenXR

- Skyrim VR ships with OpenVR (SteamVR) support
- OpenComposite bypasses SteamVR → directly to OpenXR
- Significant performance gains, reduced CPU/GPU load
- Especially beneficial for Quest 3 via Virtual Desktop

### Mod Framework VR Status

| Framework | VR Status |
|-----------|-----------|
| SKSEVR | Supported (separate build from SKSE64) |
| Nemesis | Works (behavior patches are version-agnostic HKX) |
| OAR (replacing DAR) | Native VR support |
| DAR (original) | VR build has `IsInCombat` offset bug → use DAR VR Fix or switch to OAR |
| Animation Motion Revolution | VR-compatible (CTD fixed in update) |
| PayloadInterpreter | VR support since v1.1.0 (Nexus) via VR Address Library |
| IFrame Generator RE | VR-compatible (CommonLibSSE-NG) |
| SCAR | Dedicated VR port exists (BFCO) |
| MCO/ADXP | Works at animation level in VR |
| True Directional Movement | No VR port, non-functional in VR |
| VRIK | VR-only — overrides skeleton IK from controllers |
| Precision | Works in VR via OAR versions |
| HIGGS | VR-only — hand interaction, gravity gloves |
| Papyrus Extender | VR version maintained by community (original author has no headset) |

### Common Mod Breakage Categories

1. **SKSE dependency without SKSEVR port** — #1 cause of breakage
2. **UI interaction assumptions** — mods assuming 2D menus/mouse input
3. **Address/function offset mismatches** — SE addresses don't map to VR
4. **Skeleton structure issues** — PreWEAPON/PreSHIELD nodes cause CTD
5. **Controller input paradigm** — keyboard/mouse mods don't work
6. **Framerate constraints** — physics/logic tuned for 60Hz fails at VR 90Hz
7. **ImageSpace/visual conflicts** — post-processing vs UI rendering trade-offs
8. **Physics collision differences** — player ragdoll vs capsule collision

---

## VR Controller Input Detection

### SKSE Input API — DOES NOT WORK for VR Controllers
- `Input.GetMappedKey("Right Attack/Block")` returns **-1** in VR — VR controllers are not mapped through DirectInput keycodes
- `Input.GetNumKeysPressed()` / `Input.GetNthKeyPressed()` never see VR controller input
- `Input.IsKeyPressed()` is useless for VR trigger/grip/button detection
- Only `GetMappedKey("Left Attack/Block") = 507` returned a value; right-hand controls returned -1
- **Do NOT use the SKSE Input API for VR controller detection**

### VRIK API — THE Correct Method for VR Input
All functions are native globals on the `VRIK` scriptname (`Data/Scripts/VRIK.psc`).

**Button Press Detection (all confirmed working on Quest 3 via Virtual Desktop + OpenComposite):**
- `VRIK.VrikIsTriggerPressed(Bool onLeft)` — **WORKS** clean press/release, zero false positives
- `VRIK.VrikIsGripPressed(Bool onLeft)` — **WORKS**
- `VRIK.VrikIsThumbstickPressed(Bool onLeft)` — **WORKS**
- `VRIK.VrikIsButtonAPressed(Bool onLeft)` — **WORKS**
- `VRIK.VrikIsButtonBPressed(Bool onLeft)` — **WORKS**
- Pass `false` for right hand, `true` for left hand

**Touch Detection (capacitive):**
- `VRIK.VrikIsTriggerTouched(false)` returns **TRUE at rest** on Quest 3 — finger resting on capacitive trigger. Use `Pressed` not `Touched` for intentional input.

**Position Tracking (confirmed working):**
- `VRIK.VrikGetHandX/Y/Z(Bool onLeft)` — world-space hand position, updates in real-time
- `VRIK.VrikGetHmdX/Y/Z()` — world-space HMD position
- Positions are real tracking data; change when player moves

**Controller Info:**
- `VRIK.VrikGetControllerType()` — Quest 3 reports as **0 (Rift/Oculus)**

**Axis Values:**
- `VRIK.VrikGetAxisX/Y(Bool onLeft)` — thumbstick X/Y positions

**Known Issues:**
- `VrikGetFingerPos` has a **signature mismatch** with current VRIK VR build — function will not be bound. All other VRIK functions work fine.
- Duration functions (`VrikTriggerPressDuration`, etc.) — not tested but likely work

**VRIK "Adjust Held Weapon Positions" causes concentration beam angle offset.** In VRIK Options, the setting "Adjust Held Weapon Positions" subtly rotates held weapons to fit better in the hand. For normal melee weapons this is fine. For a staff firing a concentration beam, it deflects the projectile origin ~15 degrees off-center, making the beam fire noticeably to one side instead of straight. **Fix: disable "Adjust Held Weapon Positions" in VRIK Options.** The beam then fires exactly along the controller direction via MISVR. This is a per-save MCM setting, not stored in vrik.ini.

**Usage Pattern (from POS3/POS4 mods):**
```papyrus
; In a polling loop:
if VRIK.VrikIsTriggerPressed(false)
    ; Right trigger is held — do something
endif
```

### Direction from VR Hand Position
To compute a direction vector from the player toward where the sword is pointing:
```papyrus
float dx = VRIK.VrikGetHandX(false) - player.GetPositionX()
float dy = VRIK.VrikGetHandY(false) - player.GetPositionY()
float dist = Math.sqrt(dx*dx + dy*dy)
float sinAng = dx / dist
float cosAng = dy / dist
```
This gives the horizontal direction from body center to sword hand — accurate enough for extension/projectile aiming in VR.

---

## Weapon Manipulation at Runtime

### What WORKS
- **Direct weapon swap**: `Actor.UnequipItem(weaponA, false, true)` → `Actor.EquipItem(weaponB, false, true)` — confirmed working in VR, weapon visually changes in hand
- **Weapon swap UX caveat**: Force-equipping/unequipping during powers causes a visible game stutter (brief pause). **Bad modding practice** — never force swap the player's equipped weapon. Instead, check if the required weapon is equipped and refuse activation if not.
- **Weapon.SetReach(float)** — the value IS respected by the game independently of mesh (confirmed with whip mod). But **only takes effect on game restart**, not during gameplay.
- **Weapon.GetReach() / SetReach()** — SKSE native functions, no documented upper cap
- **NetImmerse.SetNodeScale(Caster, "WEAPON", scale, false)** — scales the WEAPON skeleton bone and all children (including equipped weapon mesh). Engine renders at render framerate. One Papyrus call to extend, one to retract. Zero per-tick visual work. **Confirmed working in VR** for instant weapon scaling. Requires a visible weapon to be equipped (scaling invisible = still invisible).
- **`Caster.QueueNiNodeUpdate()`** — call after SetNodeScale to flush the scale change to the render pipeline.

### What DOES NOT WORK at Runtime
- **Weapon.SetModelPath(string)** — changes the internal path but does **NOT update the visual** of an already-equipped weapon. Even unequip→SetModelPath→re-equip cycle just shows disappear/reappear with the same model.
- **Weapon.SetEquippedModel(Static)** — native SKSE function (Weapon.psc line 55). **CONFIRMED DESTRUCTIVE in VR.** Called correctly with valid Static forms — no visual change, but actively corrupts the weapon's equipped model reference. Combined with `QueueNiNodeUpdate()`, causes the weapon to **disappear from the player's hand entirely**. The weapon shows as equipped in inventory but is invisible/gone in-world. Only fixable by manually unequipping and re-equipping. **NEVER USE THIS FUNCTION.**
- **SetReach at runtime** — value changes but hit detection range doesn't update until game restart
- **Effect Shader via GetFormFromFile** — `Game.GetFormFromFile(0x00010DDD, "Skyrim.esm") as EffectShader` returned None. FormID may be wrong or form type mismatch.
- **`ModAV("SpeedMult", -70)` for VR locomotion slowdown** — has NO effect on VR thumbstick movement. User confirmed no slowdown felt at all. VR locomotion bypasses SpeedMult.
- **`ModAV("CarryWeight", -99999)` for VR locomotion slowdown** — WORKS. Over-encumbrance (carry weight exceeded) does slow VR thumbstick movement. Use this instead of SpeedMult.

### VR Weapon Collision / Reach
- **WEAP Reach field does NOT control VR weapon collision distance.** HIGGS/VRIK use the NIF's Havok physics collision geometry to determine hit detection range, not the Reach value.
- **To extend weapon collision in VR**: the weapon NIF needs extended physics collision geometry — a longer `bhkConvexVerticesShape` or a chain of physics bones with constraints (e.g., Fettered Fragments' 17-bone `Fragment_0-16` chain). Standard weapons use `bhkBoxShape` matching the visual mesh.
- **The `_HDTSw` dummy armor trick** does NOT extend reach on its own. The primary reach extension comes from the weapon NIF's physics bone chain.
- **Creating extended-reach VR weapons requires NifSkope/Blender** to modify the NIF's physics structure.

### OL_WEAPON Projectile Routing — Damage Through Extended Weapon Collision

**Root cause**: Any projectile (spell or arrow) that physically contacts a Havok collision shape with layer `OL_WEAPON` (layer 5) has its damage routed to the weapon's owner-actor. This is an engine-level routing step that occurs before SpellAbsorption, MagicResist, block, and all Papyrus event hooks — none of those mechanisms can intercept it.

**Consequence for extended custom weapons**: A weapon NIF with a long `bhkCapsuleShape` layered `OL_WEAPON` (e.g., a 71.43 Havok unit / ~5000 game unit beam) makes the player take full spell damage from any projectile contacting any part of the capsule, regardless of distance from the hand.

**Approaches that do NOT fix it** (confirmed wrong path):
- `ModAV("SpellAbsorption", …)` — "SpellAbsorption" is not a valid Papyrus AV name; generates log errors on every call. Even if it were valid, SpellAbsorption gates the *spell-cast-at-actor* pathway, not the *projectile-hits-OL_WEAPON-shape* routing.
- `MagicResist` buff — same wrong path; applies to direct spell effects, not collision-routed damage.
- Absorb MGEF, Atronach Stone perk — operate on the spell-cast path, not the OL_WEAPON path.
- Po3 `OnProjectileHit` event — **not available in VR**. Po3 VR only exports projectile property accessors (GetProjectileSpeed, etc.), no event handlers.

**WeaponCollision.dll (ijwzac/WeaponCollisionVR) cannot help**: The plugin uses hardcoded per-weapon-type reach values (sword=90, greatsword=100, axe=70 game units, scaled by `WeaponRangeMultiply` INI setting). It reads neither the NIF collision geometry nor the weapon record's Reach field. Visual debug (`DebugShowPlayerWeaponRange=true`) confirms the parry line is always ~90 units regardless of equipped weapon. A custom NIF capsule of 5000 units is completely invisible to it.

**Clean fix path (bookmarked, not yet implemented)**: Fork `github.com/ijwzac/WeaponCollisionVR` (Apache 2.0, explicitly fork-permitted). Add ~10 lines: INI flag `bUseWeaponLengthOverride = true` + a custom keyword on the weapon form → when that keyword is present, replace the hardcoded sword line length with a configurable value (e.g., 5000 units). Build requires Visual Studio + CommonLibSSE-NG + CMake 3.21+ + C++23. Confidence: 70% (risks: VR-specific CommonLibSSE-NG quirks, SKSE update breakage, maintenance burden).

**Accepted workaround**: Frame spell vulnerability as a deliberate design tradeoff — extending the blade exposes the player; retracting (releasing trigger) restores normal hit detection.

### VR Weapon Draw State
- **`DisablePlayerControls(abFighting=true)` causes weapon to sheathe** when `EnablePlayerControls` is called afterward. The engine resets weapon drawn state when the fighting control flag is toggled.
- To freeze the player while preserving weapon drawn state, use: `DisablePlayerControls(true, false, false, false, false, false, true, false, 0)` — disables movement and menu, but NOT fighting. Combined with `SetDontMove(true)` for VR thumbstick freeze.


### Reach Formula (Vanilla, without Precision)
- `fCombatDistance(141) × NPCScale × WeaponReach`
- SetReach(10.0) ≈ 1410 units ≈ 21m
- SetReach(30.0) ≈ 4230 units ≈ 63m
- SetReach(50.0) ≈ 7050 units ≈ 106m
- **Precision does not exist for VR** — weapon collision is handled by HIGGS/VRIK

### PLANCK — VR melee hit detection + runtime settings API

PLANCK replaces vanilla/Precision melee hit detection in VR. Config: `Data/SKSE/Plugins/activeragdoll.ini`.

**Papyrus API** — `planck.psc` (`ScriptName PLANCK Hidden`; source at `Data/Source/Scripts/` — a DIFFERENT dir from `Data/Scripts/Source`, so add it to Caprica `--import` to compile against it):
- `PLANCK.GetSetting(String name)` / `PLANCK.SetSetting(String name, float value)` — global native; read/modify any numeric `activeragdoll.ini` setting at runtime. `GetSetting` returns exactly `-2.71828` if the name doesn't exist (typo check).
- Also `AddIgnoredActor`, `GetLastHitNodeName` (call inside `OnHit`), aggression-topic setters.

**Hit-speed gates** (confirmed 2026-05-17 to be read **per-hit** — `SetSetting` changes take effect live, no restart/cell-load):
- `hitSwingSpeedThreshold` (def 5.0) — min impact-point velocity for a swing to register
- `hitStabSpeedThreshold` (def 2.5) — same for stabs
- `hitRequiredHandSpeedRoomspace` (def 1.5) — the hand must be moving this fast; "walk the weapon into an enemy without moving your hand" won't register otherwise

Setting all three to **0** → any contact registers a melee hit regardless of swing speed. The setting is global (all the player's melee); toggle to 0 for a weapon-state and restore on exit to scope it per-weapon. Useful for an extended-blade weapon that should damage on any contact (toggle the gates from the weapon's script and restore on exit). This is the engine-native "weapon damages on any touch" fix — PLANCK collision runs at engine framerate, no script-sampling gap.

---

## VR Papyrus — Confirmed Findings

### Player Movement
- **`SetPosition()` on the player triggers a cell reload** in Skyrim VR, causing a loading screen even for short distances. Never use it for player teleportation.
- **`TranslateTo()` at extreme speed (100,000+) is effectively instant** and does NOT trigger a cell reload. Works well for flash-step/teleportation in VR. The original camera smoothly follows but at 100K speed it's imperceptible.
- **`MoveTo()` on the player** also triggers cell reload behavior similar to SetPosition. Avoid for short-distance movement.
- **`Game.FadeOutGame()` + `SetPosition`** is a terrible VR teleport method — the cell reload causes a multi-second black screen followed by landscape flickering as assets reload.

### Papyrus Tick Rate with Heavy Plugin Load
- **`Wait(0.1)` rounds to ~0.5-1 second actual** with 700+ plugins. The Papyrus VM is heavily throttled.
- **All Papyrus-positioned objects are limited to ~1Hz visual update rate.** Neither `SetPosition()` per-tick nor `StopTranslation()` + `TranslateTo()` per-tick can achieve smooth real-time tracking.
- **`TranslateTo()` at moderate speed (e.g. 8000 u/s) gives engine-interpolated smoothness** between Papyrus ticks, but objects still visibly "trail" behind the intended position by ~0.5s.
- **`SetPosition()` gives jerky teleporting** — objects snap to new positions with visible jumps.
- **For smooth real-time visual tracking, use engine-level approaches** like `NetImmerse.SetNodeScale()` (one call, engine handles rendering) rather than per-tick Papyrus object positioning.
- **`PlaceAtMe()` creates objects VISIBLE at caster's feet** by default. With large `SetScale()` values, a huge object flickers visibly at the player's feet. Fix: use `PlaceAtMe(form, 1, false, true)` — 4th parameter `abInitiallyDisabled=true` creates the object disabled. Then `SetPosition()` to correct location while invisible, then `EnableNoWait()`.
- **Remove `Debug.Notification()` from tight polling loops** — notification queue is slow and adds overhead per-tick.

### PapyrusUtil in VR
- **`miscutil.ScanCellNPCs()` can crash** PapyrusUtil.dll in VR with an access violation in `TESObjectREFR::SetParentCell`. Crash occurs when processing actors with invalid/missing cell references (e.g., a Goat with `ParentCell: ---`). Replace with `FindRandomActorFromRef()` loops for safer target finding.
- **`papyrusutil.ObjRefArray()`** works fine in VR for dynamic arrays exceeding 128 elements (tested up to 270).

### Targeting (TDM Replacement)
- **`truedirectionalmovement` does not exist for VR.** All calls to `truedirectionalmovement.GetCurrentTarget()` must be replaced. The script name won't resolve at all — Papyrus logs "Cannot open store for class 'truedirectionalmovement', missing file?"
- **`GetCombatTarget()`** only returns an actor when the player is in active combat (has attacked or been attacked). Returns None for passive/nearby enemies.
- **`FindRandomActorFromRef()`** is truly random — it can return any actor in range regardless of direction, proximity, or hostility. To approximate "target what you're looking at," sample 30+ times and filter by `GetHeadingAngle()` (±60°), keeping the closest match.
- **`GetActorBase().GetName()` returns empty** for leveled actors (trolls, bandits, etc.). Use `GetDisplayName()` instead for notification text.

### Spell/Effect Architecture
- **`Self.dispel()` on an ActiveMagicEffect only dispels THAT specific effect**, not the entire spell. If a spell has multiple effects (e.g., a spell with 8 effects from 8 MGEFs), dispelling one leaves the other 7 running with their summoned objects still visible. Use `actor.DispelSpell(spellForm)` to end all effects from a spell.
- **GlobalVariable signals for cross-script communication** work reliably between ActiveMagicEffects, but globals are STICKY — if a signal is set when no handler is running, it persists until cleared. Always clear signal globals in `OnEffectStart` to prevent stale signals from previous casts triggering immediately.
- **`RemoveSpell` does NOT fire `OnEffectFinish`** — use `DispelSpell` when cleanup logic exists in OnEffectFinish. (Previously known, reconfirmed.)

### Object Spawning
- **`PlaceAtMe()` + immediate `SetMotionType()` fails in VR** because 3D assets load slower than flatscreen SSE. The object's 3D isn't loaded yet when SetMotionType is called, producing "has no 3d, and so cannot have its motion type changed." Fix: wait loop checking `Is3DLoaded()` before calling `SetMotionType()`.
- **Spawning 270 weapon objects** via PlaceAtMe in a single OnEffectStart works without crashing in VR, but takes several seconds. OnUpdate won't start until OnEffectStart completes.

### Formation Math (object rings)
- **`While i < 180` with `sin(i)/cos(i)` only creates a semicircle** (0°-180° covers right→bottom→left). For a full 360° ring of objects, use `While i < 360`.
- **Radius 1800 units (~25m) exceeds typical object render distance** in VR — swords at the far side won't be visible. Keep formation radii under ~1300 units for reliable visibility.

### Decompilation (Champollion)
- **Champollion cannot decompile all bytecode.** Some code blocks decompile as empty if/elseif branches with only debug line number comments. The assembly output (`-a` flag) shows these as genuine `jmp` instructions with no code between them — the blocks may have been empty in the original compiled source (code commented out before compilation), not a decompiler bug.
- **Champollion produces variable shadowing** that Caprica rejects. Inner scope `Float cosi` conflicts with outer scope `Float cosI` (Papyrus is case-insensitive). Remove the inner redeclaration.
- **`OnPlayerFastTravelEnd` on ActiveMagicEffect** compiles in the original compiler but Caprica rejects it as "Non-native scripts cannot define new events." Safe to remove — OnEffectFinish handles cleanup.
- **Compilation stubs** are needed for type references (e.g., `zzz_getClosetTgt`) when compiling scripts that use those types as properties. Create minimal stubs with function signatures, compile, then delete the stubs.

### Skyrim Sound System: SOUN vs SNDR (CRITICAL — do not confuse)

**Every playable sound requires TWO records, not one:**
- **SNDR** (Sound Descriptor) — stores WAV file paths, OutputModel, Category. Cannot be played directly from scripts.
- **SOUN** (Sound Marker) — a thin wrapper that references one SNDR. This is what the Papyrus `Sound` type maps to.

**The Papyrus `Sound` type = SOUN records only.** `GetFormFromFile(id, "plugin.esp") as Sound` silently returns `None` if `id` points to a SNDR instead of a SOUN. No error in Papyrus log. Total silence, no indication of failure.

**Correct wiring pattern** (confirmed from a working mod's Spriggit serialization):
```
SNDR record (e.g. FormKey 49D076) ← holds WAV paths, category, output model
SOUN record (e.g. FormKey 49D077) ← SoundDescriptor: 49D076:YourMod.esp
Script: GetFormFromFile(0x49D077, "YourMod.esp") as Sound  ← uses SOUN FormID
```

**In Spriggit YAML**, SOUN records go in a `SoundMarkers/` folder:
```yaml
FormKey: 00085E:YourMod.esp
EditorID: MySoundMarker
SoundDescriptor: 000857:YourMod.esp
```

**Correct OutputModel for scripted action SFX**: `000EC7:Skyrim.esm` (`SOMStereoRad09000_verbSHOUTS`). This is the right output model for scripted action SFX. Do NOT use `0FD93D:Skyrim.esm` (`SOMStereoRad03000_verb`) — that's for ambient environmental emitters.

**Correct Category for action SFX**: `0172A1:Skyrim.esm` (`AudioCategorySFX`). Do NOT use `01A0BD:Skyrim.esm` (`AudioCategoryMAG`) — that's specifically for magic effects audio.

**WAV format**: 44100 Hz, 16-bit PCM. Sounds played positionally on a game object (`Sound.Play(objectRef)`) should be **mono**; stereo may not position correctly in 3D space.


### Spriggit WEAP YAML Format (CRITICAL — invisible weapons if wrong)

**`BasicStats` and `Data` sections have DIFFERENT fields.** Getting them swapped = invisible weapons (no mesh, no icon, record exists but renders nothing).

Correct mapping (confirmed against working weapon records):
- **`BasicStats:`** = `Value`, `Weight`, `Damage` (the "stat card" numbers)
- **`Data:`** = `AnimationType`, `Speed`, `Reach`, `Flags`, `NumProjectiles`, `AnimationAttackMult`, `Skill`, `Stagger`, `Unused`, `Unknown2`, `Unknown3`

**Required `Data:` subfields** (omitting any causes invisible/broken weapons):
```yaml
Data:
  AnimationType: OneHandSword  # or TwoHandSword, etc.
  Unused: 0x000000
  Speed: 1.0
  Reach: 1.0
  Flags: []                    # or [CantDrop], [NonPlayable], etc.
  NumProjectiles: 1
  AnimationAttackMult: 1
  Unknown2: 1061997773         # standard value from vanilla records
  Unknown3: 0x000000000000000000000000
  Skill: OneHanded             # or TwoHanded
  Stagger: 0.5
```

**Other important fields for visible weapons:**
- `Model.Data: 0x020000000000000000000000` — MODT subrecord, present in all working records
- `ImpactDataSet: 013CAC:Skyrim.esm` — standard weapon impact (without this, no hit sounds/effects)
- `DetectionSoundLevel: Normal` — affects sneak detection
- `Critical:` section — include even with minimal values (`Damage: 1, PercentMult: 10, Flags: [], Unused2: 0x000000`)
- `ObjectBounds:` — safe default: `First: -32768, -32768, -32768` / `Second: 32767, 32767, 32767`

**Working minimal WEAP YAML template** (based on working weapon records):
```yaml
FormKey: XXXXXX:Mod.esp
EditorID: MyWeapon
ObjectBounds:
  First: -32768, -32768, -32768
  Second: 32767, 32767, 32767
Name:
  TargetLanguage: English
  Value: My Weapon
Model:
  File: weapons\path\to\mesh.nif
  Data: 0x020000000000000000000000
EquipmentType: 013F45:Skyrim.esm
Keywords:
- 01E711:Skyrim.esm
Description:
  TargetLanguage: English
  Value: ''
ImpactDataSet: 013CAC:Skyrim.esm
BasicStats:
  Value: 100
  Weight: 5.0
  Damage: 12
Data:
  AnimationType: OneHandSword
  Unused: 0x000000
  Speed: 1.0
  Reach: 1.0
  Flags: []
  NumProjectiles: 1
  AnimationAttackMult: 1
  Unknown2: 1061997773
  Unknown3: 0x000000000000000000000000
  Skill: OneHanded
  Stagger: 0.5
Critical:
  Damage: 1
  PercentMult: 10
  Flags: []
  Unused2: 0x000000
DetectionSoundLevel: Normal
```

**Common EquipmentType FormIDs:**
- `013F45:Skyrim.esm` — RightHand (one-handed weapons)
- `013F42:Skyrim.esm` — BothHands (two-handed weapons)

**Previous error**: Using `Critical.Flags: [OnDeath]` caused Spriggit parse error. Use `Flags: []` instead. `OnDeath` is valid in some records but may not be valid for Mutagen's CriticalData.Flag enum.

### Spell Effect Area is in FEET (CRITICAL)
- **Spell effect Area values are measured in FEET, not game units.** 1 foot ≈ 21.3 game units ≈ 30.5 cm.
- Area=60 = 60 feet = ~18 meter RADIUS (36m diameter) — NOT 60 game units (~85cm).
- Area=200 = ~61 meter radius. Area=3 = ~0.9m radius. Area=1 = ~0.3m radius.
- For sword-width damage: Area=2-3 (about 60-90cm radius).
- For wider effects (stagger aura, splash): Area=10-15 (~3-5m radius).
- This affects ALL spell effects: damage, healing, cloak, area denial, etc.

### ESP/Spriggit
- **Spriggit requires `--PackageVersion` parameter** when `--PackageName` and `--GameRelease` are set, or it throws "PackageVersion needs to be set."
- **A plugin's own records use a mod index equal to its master count** for `GetFormFromFile()` (an ESP with 5 masters uses index `0x05`; with 2 masters, `0x02`). Match the prefix to the master count or the lookup silently returns None.

### ImageSpaceModifier
- **`FadeToBlackHoldImod`** (Skyrim.esm FormID `0x0F756E`) fades the screen to black and holds. Can be applied at partial strength (e.g., 0.6) for dimming rather than full blackout.
- **`ApplyCrossFade(strength)`** transitions gradually to the IMOD effect, vs `Apply(strength)` which snaps to it instantly.
- **`FadeToBlackImod`** = `0x0F756D`, **`FadeToBlackBackImod`** = `0x0F756F` (fade back from black).

---

### Staff AnimationType, WNAM, and VR In-Hand Render

**`AnimationType: Staff` causes visual blade inversion when using a sword NIF.** The staff skeleton orients the weapon bone differently than the sword skeleton. Result: blade appears held backwards. **Fix: apply a Y-axis rotation matrix to all child NiTriShape geometry nodes in the NIF.** This successfully corrects the inversion without breaking beam direction.

**VRIK uses the 3rd-person weapon NIF *only when WNAM is null***. In Skyrim VR with VRIK active, the engine attaches the 3rd-person model (`MODL`) to the avatar hand bone — UNLESS the WEAP record has a `WNAM` (FirstPersonModel) field set to a STAT that wraps a different NIF. **Setting `WNAM = SomeStat` redirects the in-hand render to the STAT's NIF.** Confirmed: pointing `WNAM` at a STAT that wraps a vanilla 1st-person NIF causes the in-hand mesh to render that vanilla blade instead of the edited 3rd-person NIF. An earlier diagnostic (swapping the custom 1st-person NIF for an iron dagger had zero visual effect) was true *because WNAM was null at the time* — the auto-fallback 1st-person NIF lookup was indeed unused, but an *explicit* WNAM redirect is honored. **Practical rule: if you want VR in-hand to show NIF X, either edit the 3rd-person Model AND leave WNAM null, OR set WNAM to a STAT wrapping NIF X.** Both work; mixing them produces the override case where WNAM wins.

**Inventory icon UI also follows WNAM.** When WNAM is null, the inventory icon viewport renders blank (or nothing reasonable). Setting WNAM to a valid STAT activates the icon. The rendered icon is the STAT's NIF (same one used for in-hand). To get a glowing inventory icon, point WNAM at a STAT wrapping a glowing NIF.

**Skyrim does NOT auto-derive 1stperson NIF paths for custom directories.** The `1stperson<name>.nif` convention only works within recognized vanilla paths (e.g., `weapons/akaviri/`). Custom paths like `mymod/weapon.nif` → `mymod/1stpersonweapon.nif` do not resolve. Confirmed by diagnostic.

**`AnimationType: Staff` IS required for hold-to-fire.** With `AnimationType: OneHandSword` (even with `WeapTypeStaff` keyword + `EnchantType: StaffEnchantment`), the engine does not trigger hold-attack-to-cast. AnimationType: Staff is the gate.

**DAC-NG does NOT support concentration spells.** `_DynamicAnimationCasting/template.toml` explicitly states concentration spells "not working well right now" and provides `IgnoreConcentrationSpell = true` as a filter. Not viable for continuous beam.

---

### Staff vs Sword Skeleton: Blade Inversion + Grip Offset
A sword NIF set to `AnimationType: Staff` renders the blade **inverted** (held backwards), because the
staff skeleton orients the weapon bone differently than the sword skeleton.

**Fix**: rotate every child NiTriShape geometry node 180 deg around **Y** (negates X and Z, reversing
the forward-facing axis). Do this with PyFFI on an LE-format NIF, not by hand-patching bytes. Z- or
X-rotation only spins the blade about its own axis and does not flip the tip direction.

**Grip offset** comes from the skeleton bone positions:

| Bone | X | Y | Z |
|------|---|---|---|
| WeaponSword | -11.89 | +1.92 | +6.67 |
| WeaponStaff | 0.00 | -10.08 | +2.47 |

The ~12-unit Y difference makes a staff grip feel "further back"; the ~12-unit X difference makes it
feel "more centered." A root NIF translation to compensate has little effect in VR — VRIK's own grip
system controls hand-to-weapon placement and is only adjustable via VRIK's in-game per-weapon-type
calibration (not via `vrik.ini`, which has only a global `weaponAdjustment`).

### Cell.GetNthRef is UNRELIABLE for Real-Time Actor Detection

**`Cell.GetNumRefs(0)` + `Cell.GetNthRef(i, 0)` does NOT reliably return all loaded actors.** Confirmed via Papyrus logging: a Frost Troll being continuously hit by an engine beam (dozens of BEAM CONTACT events per second) appeared in only 2 out of 24 consecutive `GetNthRef` scans (~1s each). The ref count jumped from 17→18→19 when the troll appeared, suggesting dynamic load/unload of the ref list.

**Fix: Use `PO3_SKSEFunctions.GetActorsByProcessingLevel(0)` instead.** Returns an `Actor[]` array directly — no ObjectReference casting needed, far more reliable. Processing level 0 = high (nearby, combat-active actors). Confirmed working: 14 actors found per tick in the same area where GetNthRef found 1-2.

### Concentration Beam OnEffectStart Behavior

**For Script archetype MGEFs on concentration spells:** `OnEffectStart` fires at engine framerate (dozens per second, not once). Each call is a separate script instance. This means:
- Any `Spell.Cast()` or `RegisterForSingleUpdate()` inside `OnEffectStart` will spam
- Use a script-level `bool` gate to prevent spam (set true on first fire, reset in `OnEffectFinish`)
- `HasMagicEffect()` check races with Cast — the effect hasn't registered by the time the next `OnEffectStart` fires

**For ValueModifier archetype MGEFs on concentration spells:** Continuous HP drain at engine speed. Magnitude is per-second.

### Staff AnimationType Melee Auto-Fires Enchantment

**When a Staff weapon physically contacts an enemy in melee, the engine auto-fires the staff's concentration enchantment.** This happens WITHOUT the player pressing the VR trigger. The beam visual appears and the beam's damage script fires.

**Fix 1 (Papyrus — has 1-frame flash):** Check `VRIK.VrikIsTriggerPressed(false)` in OnEffectStart. If trigger not pressed, call `self.Dispel()`.

**Fix 2 (Engine-level — prevents beam entirely):** Strip the enchantment from the weapon via `Weapon.SetEnchantment(None)` when trigger is released, restore with `Weapon.SetEnchantment(beamEnch)` when trigger is pressed. Modifies the base Weapon form. Confirmed working in VR — enchantment toggle propagates to equipped instance.

### Useful Vanilla MGEFs / Reference FormIDs

| Record | FormID | Purpose |
|--------|--------|---------|
| PerkBleedingDamage | 0C367A:Skyrim.esm | Vanilla sword bleed effect (Bladesman perk). ValueModifier/Health, HideInUI, FireAndForget/Touch. |

### PushActorAway — Caller is the Source, Parameter is the One Pushed

`Actor.PushActorAway(Actor akActorToPush, float afKnockbackForce)` — the **calling actor** is the source of the push; **akActorToPush** is the one who gets knocked back, away from the caller.

- `Caster.PushActorAway(Target, 15.0)` → enemy flies away from player ✓
- `Target.PushActorAway(Caster, 15.0)` → **player** flies away from enemy ✗ (common mistake)

### Block Detection in Papyrus

**No native `IsBlocking()` function exists** in Papyrus, SKSE, PO3, or DbSKSE. **Workaround:** `target.GetActorValue("IsBlocking")` returns 1.0 if actor is in blocking stance, 0.0 otherwise. This is an internal AV, not documented but functional.

### DbSKSEFunctions — Projectile Collision Tracking

`DbSKSEFunctions.psc` provides powerful projectile inspection:
- `GetProjectileHitRefs(ObjectReference projectileRef)` — all refs a projectile hit
- `GetProjectileCollidedLayerNames(ObjectReference projectileRef)` — collision layer names
- `SetProjectileBaseCollisionRadius(Projectile, float)` — change beam width at runtime
- `GetProjectileShooter(ObjectReference projectileRef)` — trace who fired

Useful for diagnostics and potentially for detecting beam pass-through. Requires the projectile ObjectReference, not just the Projectile base form.

### Core Modding Philosophy: Prefer Native Engine Solutions

**Always prefer what the engine already knows how to do over Papyrus-based workarounds.** "Simple" in modding means simple from the engine's perspective — not simple as code.

Examples of native vs. wrong approach:

| Problem | Wrong (script hack) | Right (native) |
|---------|---------------------|----------------|
| Stagger immunity | `ForceActorValue("Stagger", 0)` every tick | AddPerk with stagger resist entry point |
| Keeping Magicka up | `RestoreAV("Magicka", 9999)` in loop | Enchantment with 0 Magicka cost |
| Preventing melee auto-fire | Dispel in OnEffectStart | Strip enchantment from weapon form (engine-level) |
| Hit detection | Papyrus raycast | Engine collision (projectile/weapon) |
| Movement restriction | Script-forced position | SetRestrained or Paralysis MGEF |

**The question to always ask first:** "How does the game already handle this scenario?" Find that mechanism and use it. Only fall back to Papyrus scripting when no native mechanism exists — and even then, treat it as a supplement to engine behavior, not a replacement.

This is the same principle as engine-primary hit detection: the engine is always doing more work more reliably than Papyrus can. Work with it, not around it.

*Last updated: 2026-04-08*
*Add new entries as they're discovered. Prefer verified facts over speculation.*

---

## Havok Units & VR Hit-Detection

### Havok game units
1 Havok unit ≈ 70 game units. This applies to `bhk*` collision blocks ONLY (bhkBoxShape dimensions,
bhkConvexTransformShape translations, capsule lengths). A ~5000-game-unit collision shape is ~71 Havok
units. Get this wrong and the collision geometry lands far from the visual mesh.

### VR melee hit-detection stack
VR melee hit detection is layered: vanilla engine + HIGGS (hand interaction) + WeaponCollision.dll +
PLANCK (active-ragdoll melee). They stack — a hit can come from any layer.
- WeaponCollision.dll's `EnemyDetectionRange` (default 600) is often the real range bottleneck — raise
  it before blaming the weapon.
- The engine's melee hit range is effectively capped (~1500 game units) and does NOT scale with a
  longer Havok capsule. Reach beyond the cap must come from a Papyrus script (per-swing scan +
  spell/damage cast), not from enlarging the collision capsule.

---

## Immobilizing the Player / NPCs in VR (aggro + VRIK)
- `DisablePlayerControls(movement)` makes the player effectively un-attackable by NPCs (they stop
  aggroing). To immobilize while KEEPING aggro, use `Actor.SetDontMove(true)` ALONE — it freezes VR
  thumbstick locomotion but does NOT freeze the VRIK weapon-bone aim, so the player can still fight.
- `SetRestrained` stops movement but does NOT stop attacks.
- To fully freeze an NPC victim (no movement, no attacks), use `EnableAI(false)` — and restore AI
  before any kill so the corpse doesn't despawn (see the `OnEffectFinish` IsDead guard above).
