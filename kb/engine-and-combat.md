# Knowledgebase: Engine and combat

Part of the Skyrim modding knowledgebase; index: `KNOWLEDGEBASE.md`. Covers engine quirks, stagger, bleed, knockback, spawned-actor CTD.

## Game Engine Quirks

### Ability-Type Spells

- Abilities are "always on" spells — Constant Effect, no duration.
- `AddSpell` for an already-present ability = safe no-op (no stacking).
- Abilities persist through save/load. Remove them explicitly when done.

### Papyrus fUpdateBudgetMS

- Default: 1.2ms per frame for all scripts combined.
- With 700+ plugins, this budget is frequently exceeded.
- Papyrus Tweaks NG can increase this via `fMainThreadTaskletBudget`.
- Affects `Wait()` reliability and event dispatch timing.

### Known Vanilla Bugs

- `IsHostileToActor` crashes to desktop with NONE object
- `abPreventEquip` flag in `UnequipItem` doesn't work on NPCs
- `ForceThirdPerson`/`ForceFirstPerson` can't determine current camera mode
- Forcing view change causes immediate revert
- Bashing costs no stamina in vanilla Skyrim VR (infinite stagger exploit)

### SKSE Plugin Version Compatibility

**PapyrusTweaks NG v4.1.1 (Oct 2025) breaks NPC dialogue in VR.** The newer version's `ValidationSignaturesHook` and `AttemptFunctionCallHook` cause NPC dialogue options to never appear — NPC speaks their greeting but the player choice menu doesn't show. **Use the stable 2023 version instead.** Symptom: NPC speaks but dialogue menu never opens; Papyrus log shows many `Unbound native function` and `does not match existing signature` errors at load time.

**po3_PapyrusExtender updates can break backward compatibility.** The March 2025 update changed function signatures for `PO3_SKSEFunctions`, causing mods compiled against older versions to fail with "does not match existing signature" errors. Functions like `GetSkinColor`, `GetHairColor`, `GetAllSpellsInMod`, `ToggleChildNode`, `ResetActor3D` all affected.

**The DLL on disk is the source of truth for "what version is actually installed" — not the mod manager.** For any SKSE plugin, read the embedded File/Product version of `Data/SKSE/Plugins/*.dll` directly (e.g. the stable PapyrusTweaks build reports `4.1.0.x`). A manually-installed or hand-reverted plugin is invisible to Vortex/MO2, so the manager's reported version can disagree with what the game actually loads. Because these are DLLs with no save data, reverting one is safe mid-playthrough — the problem disappears on an existing save. Keep a personal "do-not-update-past" list; a plugin that is silently broken in VR while fine on SE/AE is easy to misattribute and easy to reinstall months later.

### Engine Fixes Available

- **Engine Fixes VR**: tree LOD visibility, BSFadeNode offset corrections, volume settings persistence
- **Poached Bugs VR**: ports Scrambled Bugs fixes to VR (spellcasting, texture, weapon issues)
- **Papyrus Tweaks NG**: script execution fixes, VR playroom script pausing — **use 2023 version, NOT v4.1.1** (see above)

---

## Stagger & Bleed — Vanilla Alignment

### Stagger-archetype spell cast from Papyrus → no visible animation

`Spell.Cast(source, target)` where the spell wraps a `Stagger` archetype MGEF produces NO visible stagger animation on the target. Vanilla Skyrim never delivers stagger this way — vanilla staggers come from perk entry points on weapon hit, shout impact data, or spell impact data on projectile collision. None of those paths are accessible from a Papyrus `Spell.Cast()` call. Do not pursue this approach.

**Practical substitute:** `Caster.PushActorAway(target, 1.0–3.0)` produces a physical stumble that reads visually as stagger. It fires reliably from script, scales with force, and matches the user's expectation of "hit = stumble."

### Stagger MGEF on Concentration enchantment = stagger lock

A `Stagger` archetype MGEF placed directly on a Concentration enchantment effect re-fires at ~90Hz in VR. The stagger animation restarts every frame before the previous one completes → infinite locked stumble. **Never put Stagger MGEFs on Concentration enchantments.** Deliver stagger per-swing via script (PushActorAway or a FireAndForget spell cast on dirChanged).

### Vanilla bleed pattern

Vanilla bleed (e.g. Bleeding Strikes perk, `0C367A:Skyrim.esm`):
- Archetype: ValueModifier Health
- CastType: FireAndForget
- Duration > 0 (persists after application, ticks over time)
- Delivered via perk entry point triggered on each weapon swing hit

**Script analog for a beam/sweep weapon:** cast a FireAndForget bleed spell from your per-swing scan when `dirChanged == true` — one cast per swing per actor on the line. This maps directly to "each swing applies bleed," matching vanilla bleed semantics precisely.

### `GetActorValue("IsBlocking")` is NOT a valid actor value

Throws `Error: Actor value "IsBlocking" does not exist` on every call. This error has non-trivial VM overhead, especially in hot paths. **Use `Actor.GetAnimationVariableBool("IsBlocking")` instead** — this reads the animation graph variable and works correctly.

### dirChanged early-return is the correct pattern for cheap polling loops

When a 10Hz polling loop has swing-event work (tier knockback, bleed cast, form lookup), gate ALL of it behind `dirChanged` and exit early on `!dirChanged`. Most ticks during normal beam use will be `!dirChanged` (player holding the beam still). This collapses the per-tick cost to a direction dot product + return — effectively free.

---

## Spawned-Actor Havok CTD (null physics body)
Calling `PushActorAway` or a lethal `DamageActorValue` on a freshly `PlaceAtMe`'d / just-spawned actor
whose 3D/Havok body hasn't loaded yet = `EXCEPTION_ACCESS_VIOLATION` CTD. Guard any physics op behind
an `Is3DLoaded()` wait-loop before touching a spawned actor.

---

## Explosion knockback needs a Knock Down flag, not more Force

An `EXPL` record's `DATA\Force` **only moves actors if a Knock Down flag is set** in `DATA\Flags`.
Without `Knock Down - Always` or `Knock Down - By Formula`, raising Force does nothing at all — you can
go 3, then 50, then 1000, and see zero knockback. This is a classic dead end: the parameter looks like
the knob, and it is not.

- `Knock Down - Always` ragdolls every affected actor regardless of mass; `Knock Down - By Formula` is
  mass-weighted and gentler.
- Force pushes **radially away from the explosion centre**, so a self-centred explosion flings distant
  actors outward. For a directional fling the centre must be offset from the target.
- For simple visible knockback, the engine-native `PushActorAway(target, magnitude)` (roughly 1-5 =
  stagger through ragdoll) is usually a better tool than an explosion at all.
