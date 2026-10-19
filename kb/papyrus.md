# Knowledgebase: Papyrus

Part of the Skyrim modding knowledgebase; index: `KNOWLEDGEBASE.md`. Covers Papyrus scripting, logs, VM and compile quirks.

## Papyrus Scripting

### Log Noise (Not Bugs)

**"VM is freezing..." / "VM is frozen"** — These lines appear in **every** Papyrus log on normal game exit and save. They are not a crash, not a script error, and have no diagnostic value. Ignore them completely when troubleshooting.

### Script Lifecycle

**OnInit vs OnLoad:**
- `OnInit` fires only once when the script first initializes — never again on subsequent game reloads
- For Quest/Alias scripts: `OnInit` fires at game startup and whenever the quest starts (due to reset)
- For other objects (Topic Infos, Perks, persistent refs): `OnInit` fires at first load into the session
- All properties and variables are reset to default values before `OnInit` fires
- There is NO `OnLoad` event — use `RegisterForSingleUpdate`/`OnUpdate` or `OnGameReload` for reload detection
- `OnInit` does NOT fire again after save/load (quest must be reset)

**Persistence and Save/Load:**
- Auto properties receive their default values after save/load
- **Non-auto properties do NOT receive master file values after save/load** — they remain blank
- If a variable references a Form from a removed mod, it becomes "missing" and stays missing even if the mod is restored
- FormList entries added by scripts persist through save/load
- ObjectReferences are temporary by default — only the base Form is stored in saves. Use `PlaceAtMe` with `persist=true` or ReferenceAlias for persistence

**Orphaned Scripts:**
- Occur when objects are removed before script threads finish, or from uninstalled mods
- Don't cause serious save bloat but indicate cleanup issues
- Removing a mod leaves its `RegisterForUpdate` handlers registered, causing periodic errors

*Sources: [CK Wiki: OnInit](https://ck.uesp.net/wiki/OnInit), [CK Wiki: Save Files Notes](https://ck.uesp.net/wiki/Save_Files_Notes_(Papyrus))*

### Threading Model

- Papyrus is **single-threaded per script instance**. Concurrent calls queue (FIFO).
- Default `fUpdateBudgetMS` is 1.2ms per frame for all scripts combined.
- The VM is limited to ~100 operations per task.
- If budget is exceeded, execution pauses until next frame.
- `iMaxAllocatedMemoryBytes`: total memory limit for all stack frames. If exceeded, VM waits rather than allocating.
- A script stack dump occurs after 5000ms continuous overload — incoming events are dropped (not `Wait()` continuations).
- PayloadInterpreter bypasses Papyrus entirely — can fire simultaneously with running scripts.

**Race Conditions:**
- Only one thread can operate on a script at a time, creating queues
- Deadlocks can occur when locking multiple locks — define a convention for lock order
- **Out-of-order event delivery**: `OnTriggerLeave` can arrive before `OnTriggerEnter` — use counters, not booleans
- Multiple scripts calling the same function create queue delays — popular scripts become progressively slower

**VM Freezing:**
- VM freezes when game is paused (menu, console)
- Toggling scripts with console pauses all scripts; they resume on save action or stack dump

*Sources: [CK Wiki: Threading Notes](https://ck.uesp.net/wiki/Threading_Notes_(Papyrus)), [Papyrus INI Settings Analysis](https://thallassathoughts.wordpress.com/2016/09/16/myths-and-legends-papyrus-ini-settings/)*

### RemoveSpell vs DispelSpell

- `RemoveSpell()` removes a spell from the actor's spell list but does **NOT** fire `OnEffectFinish` on the magic effect script.
- `DispelSpell()` cancels the active magic effect and **DOES** fire `OnEffectFinish`.
- **CRITICAL: `DispelSpell()` explicitly EXCLUDES ability-type spells.** It only works on non-ability active effects (spells, enchantments, potions). For abilities, you MUST use `RemoveSpell()`.
- If a magic effect script has cleanup logic in `OnEffectFinish` (restoring weather, re-enabling AI, deleting placed objects), you **must** use `DispelSpell()`, not `RemoveSpell()` — but only for non-ability spells.
- For ability-type spells (Type=Ability, Cast=Constant Effect): use `AddSpell()` to apply, `RemoveSpell()` to remove. `DispelSpell()` will silently do nothing.
- `AddSpell()` on an ability the actor already has is a safe no-op — no stacking, no error.

### Utility.Wait() Reliability

- `Wait()` is frame-bounded — minimum resolution is one frame (~11ms at 90fps).
- Sub-100ms waits (e.g. `Wait(0.05)`) are unreliable under script load. They can fire 2-3x late.
- Under extreme script load (700+ plugins), jitter can reach 200-500ms on rare occasions.
- `Wait()` is never skipped — the engine defers but always resumes.
- **Prefer `RegisterForSingleUpdate`/`OnUpdate`** over `Wait()` — safer, avoids stack issues with long waits.
- For FX sequencing, merge any sub-100ms gaps into the adjacent step.
- For combat-critical timing (18-20ms precision), Papyrus is inadequate — use native C++ (PayloadInterpreter, SKSE plugin).

### Spell.Cast() vs PayloadInterpreter @CAST

- `Spell.Cast()` goes through the Papyrus VM scheduler. Subject to per-frame script budget (1.2ms default).
- PayloadInterpreter `@CAST` is native C++ — fires in the same engine tick as the animation event, zero Papyrus overhead.
- `@APPLYSPELL` bypasses all casting mechanics (no resource costs, no casting animation). Equivalent to `AddSpell(spell, false)` for abilities.
- `@UNAPPLYSPELL` removes the applied effect. Equivalent to `RemoveSpell()` — NOT `DispelSpell()`, since PI primarily uses this for ability-type spells which DispelSpell excludes.
- `Spell.Cast()` CAN stack effects if called multiple times. `AddSpell()` for abilities CANNOT stack.

### PlayIdle() and Animations in VR

- `PlayIdle()` on the player is unreliable in VR. VRIK overrides the upper-body skeleton via IK from controllers.
- Even if the idle fires, VRIK fights the pose on head and arms in real-time.
- `PlayIdle()` makes condition checks; `SendAnimationEvent()` bypasses some but is still state-dependent.
- Can't play idle if in "Weapon Drawn" state; can't use `attackStart` if in Idle state.
- Conditions in behavior files prevent certain animations from firing.
- If a mod depends on animation annotation events (e.g. PayloadInterpreter payloads), and those events come from a `PlayIdle()` animation, the entire chain fails in VR.
- **Workaround**: bypass animation dependency entirely with timed Papyrus scripts.

### GetFormFromFile()

- `Game.GetFormFromFile(formID, "plugin.esp")` looks up forms at runtime without needing script properties.
- Avoids VMAD property complexity when you'd otherwise need 20+ spell properties.
- The formID parameter is the **local** FormID (without the load-order prefix).
- Returns `None` if the plugin isn't loaded — **always check before casting**.
- Form ID must include `0x` prefix (e.g., `0x0001ABCD`).

### ESP Dependency Rule: Own Your Records

**Never use `GetFormFromFile()` to borrow records from another mod.** Soft runtime dependencies (`GetFormFromFile("SomeMod.esp")`) silently break when that mod is disabled, uninstalled, or load-order shifted — the call returns `None` with no error until the feature simply doesn't work.

**Rule**: If you need a record (SNDR, SPEL, MGEF, etc.) from another mod, copy it into the ESP you're actively developing. Create your own version of the record in the ESP you're actively developing and reference that instead.

- Hard master dependencies (listed in MAST records) can't always be avoided — they're acceptable when you're overriding or extending a specific mod's content.
- Soft `GetFormFromFile()` dependencies on other mods are almost always avoidable: copy the WAV/record into your own ESP.
- **Exception**: `Skyrim.esm` and the game's core master files — always safe to reference by FormID since they're always loaded.

### Magic Effect Lifecycle

**OnEffectStart / OnEffectFinish:**
- `OnEffectStart` fires when effect activates on target
- `OnEffectFinish` fires when effect ends
- **CRITICAL**: When `OnEffectFinish` fires, the effect may already be deleted — calling methods on it can fail

**Casting Types (all effects on a spell MUST match):**
- Constant Effect (0): always active like an ability
- Fire-and-Forget (1): charge then fire on release
- Concentration (2): sustained while held, drains magicka continuously

**Delivery Types:**
- Self: applies to caster
- Touch: applies on contact
- Aimed/Projectile: applies to target hit

**Spell vs Ability vs Power:**
- Spell: cast from menu, costs magicka
- Ability: passive, always active (Constant Effect, no duration)
- Power: equips to shout key; Greater Power = 1/day, Lesser Power = unlimited or custom cooldown
- Each behaves fundamentally differently for cooldowns, stacking, and activation

### RegisterForSingleUpdate vs RegisterForUpdate

- `RegisterForUpdate`: fires continuously at specified interval (creates repeating loop)
- `RegisterForSingleUpdate`: fires exactly once, must be called again to repeat
- If mod is removed, `RegisterForUpdate` handlers still fire → periodic errors in log
- **Safer to chain `RegisterForSingleUpdate` calls** rather than relying on `RegisterForUpdate`

### State System Quirks

- `OnBeginState` does NOT fire if already in that state
- Calling `GoToState("")` inside `OnUnload` triggers `OnEndState` but `Self` is None/Null → crash
- **Workaround**: move `GoToState("")` call to `OnLoad` instead

### Actor Value Functions

- `SetActorValue`: sets **BASE** value (maximum), not current value
- `RestoreActorValue`: adds to current value up to base limit, doesn't change base
- `ModifyActorValue`: changes **BOTH** current AND base value simultaneously
- `DamageActorValue`/`RestoreActorValue` for current-only changes
- `SetActorValue` should only be used intentionally for base value changes

### Equipment Functions

- `EquipItem`: if actor doesn't have item, gives it first (better to `AddItem` first)
- Enchanted weapon charges reset to full if actor not in loaded cell
- `abPreventEquip` flag doesn't work on NPCs (only Ammo)
- `QueueNiNodeUpdate` (SKSE) needed after `EquipItem` to force visual update

### SetVehicle Issues

- `SetVehicle(None)` does NOT reliably dismount — players may remain stuck
- Setting as vehicle for custom creatures crashes without matching `.hkx` animation files
- No `IsRidingHorse` function — workaround: check `bIsRiding` animation value
- In VR: causes HMD desync (game moves player position while HMD anchor stays fixed)

### Performance Pitfalls

**Most expensive operations (in order):**
1. Native function calls (biggest bottleneck)
2. Accessing properties on different scripts (involves function call)
3. String operations
4. Complex conditional logic

**Optimizations:**
- Cache property values in local variables
- Minimize native calls
- Use auto properties when possible
- Default arrays limited to 128 items (use JContainers/PapyrusUtil for more)
- Arrays are pass-by-reference — modifying elements affects all references to that array

### Null Reference Patterns

- "Cannot call X() on a None object" — attempting operation on null value
- Always check for `None` before operations
- `IsHostileToActor` crashes to desktop with NONE object (vanilla bug)

### Condition Function Gotchas

- **OR has precedence over AND** — `A AND B OR C AND D` evaluates as `(A AND (B OR C) AND D)`, NOT `(A AND B) OR (C AND D)`
- More than 3 AND-pairs causes performance hits on high-demand items (spells, effects)
- Some condition functions lack Papyrus equivalents (e.g., `IsPlayerInRegion`)
- `GetIsRace` condition doesn't always recognize race properly — use `GetRace()` script function instead

*Sources: [CK Wiki: Condition Functions](https://ck.uesp.net/wiki/Condition_Functions), [Beyond Skyrim: Scripting Best Practices](https://wiki.beyondskyrim.org/wiki/Arcane_University:Scripting_Best_Practices)*

---

## Papyrus Debugging in VR

### Debug.Notification() Limitations
- Skyrim displays **one notification at a time** with ~5 second delay before the next in queue
- Notifications from rapid script execution pile up and display minutes after they fired
- **Do NOT rely on notifications for real-time feedback or timing-sensitive tests**
- `Debug.MessageBox()` is **non-blocking** in Papyrus — fires and script continues immediately, does NOT wait for OK

### Debug.Trace() — The Correct Logging Method
- Writes directly to `Documents/My Games/Skyrim VR/Logs/Script/Papyrus.0.log`
- No queue delay — logged at time of execution
- Use `[TAG]` prefixes for easy grepping: `Debug.Trace("[MYMOD] message")`
- Use `Utility.GetCurrentRealTime()` for timing measurements

### Concurrent Script Instances
- Activating a Lesser Power multiple times spawns multiple ActiveMagicEffect instances
- Each runs its own script thread — polling loops from multiple activations overlap
- **Always use a GlobalVariable lock** to prevent re-entrance:
  ```papyrus
  if MyLock.GetValue() != 0
      return
  endif
  MyLock.SetValue(1)
  ; ... do work ...
  MyLock.SetValue(0)
  ```

---

## Papyrus Log — Generalizable Cleanup Lessons

### "Cannot open store for class X" is benign orphan noise
Lobotomized or removed mods leave `Cannot open store for class "..."` lines (orphaned script
instances baked into save aliases). They are harmless. `bDisableMissingScriptError = true` in
PapyrusTweaks.ini suppresses them at the log level; ReSaver can clean the underlying orphans.

### GetTargetActor() == None is NOT a valid unbound-Self guard
When an ActiveMagicEffect script's `Self` has no native binding (e.g. phantom AME instances created
by an equip/ability re-broadcast), calling ANY native function on it logs `Unable to call X - no
native object bound` BUT does NOT return None — it returns a non-None garbage value. So
`If GetTargetActor() == None : Return` never triggers, and actually ADDS an error instead of
suppressing one. This contradicts common Papyrus advice — trust the empirical log. There is no
in-script way to make such a phantom instance short-circuit; fix it at the source (reduce the
broadcast, detach the script at ESP level, or filter via an SKSE plugin), not in the script body.

### po3 Papyrus Extender on VR: the old 2019 port is a trap (corrected 2026-10-05)
The earlier note here said `po3_papyrusextender_vr.dll` "omits ~24 functions present in the SSE build"
(`Apply3DHavokImpulse`, `GetAllActiveEffectsOnActor`, `InstantKill`, `RemoveChildNode`). That described
the **old 2019 port** (log banner `po3_PapyrusExtenderVR 2.3`), not the modern VR build.
- **Correct VR setup:** Nexus SE **22854**'s scripts (the original Papyrus Extender) **plus** Nexus SE
  **58296**'s DLL (alandtse's CommonLibVR build, `po3_PapyrusExtender.dll`, same filename, meant to
  overwrite the original's DLL). 58296's page says it requires the original for the scripts, and its
  archive ships only that one DLL. A mod manager may file the VR DLL under 22854 because it was
  dropped over the original's in staging; that is the documented install, not an error.
- **The trap:** a 2019 `po3_papyrusextender_vr.dll` left beside the modern DLL is a second Papyrus
  Extender. It loads after it and **replaces about 90 of the modern DLL's natives** (measured on
  one install: 90 of 90 shared names), and some replacements change signature, so scripts compiled
  against the modern `.psc` call them with the wrong shape. The function-gap list above was the old
  port's; the modern VR build supplies most of it.
- **Fix:** retire the old DLL (rename to `.disabled`; a DLL change is save-safe), then confirm the
  `Replacing native function` lines disappear from the next Papyrus log.
- **General lesson:** `grep "Replacing native function"` in the Papyrus log to find **stale duplicate
  SKSE plugins**. Two plugins registering the same script's natives is the signature, whatever the
  plugin (see the rubric's "old-named sibling" rule).

### PapyrusTweaks.ini on heavy modlists
Useful keys: `iMaxOpsPerFrame` (raise from vanilla 100); `bDisableMissingScriptError` and
`bDisableNoPropertyOnScriptErrorLogs` (suppress cosmetic version-skew noise); `bSpeedUpNativeCalls`
(desync native calls from framerate — a real perf win); `iStackDumpTimeoutMS` (lower = stack dumps
fire before a freeze times out, so you actually capture the offending stack). On a very heavy modlist
the inflated Papyrus memory settings are load-bearing — see the VM page-policy note below.

---

## Papyrus VM Page-Policy CTD on Heavy Modlists
Signature (CrashLoggerSSE): `EXCEPTION_ACCESS_VIOLATION` in `SkyrimScript::HandlePolicy::Func4`,
through `BSScript VirtualMachine -> NativeFunctionBase::Call`, with `SimpleAllocMemoryPagePolicy`
(and often PapyrusTweaks) in the stack. This is the VM's internal script-memory page-policy faulting
— NOT machine RAM exhaustion. The last script line is incidental (the policy serves all scripts).

**Tuning lesson**: on a very heavy modlist, do NOT shrink the Papyrus memory page sizes. Inflating
the pool (`iMaxAllocatedMemoryBytes`) while shrinking `iMaxMemoryPageSize` / `iMinMemoryPageSize`
produces hundreds of thousands of tiny pages — pathological, and causes an instant CTD on game load.
Big pages compensate for a big pool; the two are coupled. If the crash frequency is intolerable, the
only low-risk lever is PapyrusTweaks `bIgnoreMemoryLimit` true->false (re-imposes the ceiling so the
VM freezes/dumps instead of growing into the fault) — without touching page geometry.

---

## No Papyrus Raycast
There is no raycast available to Papyrus. Scripts cannot find a beam's or projectile's terrain-contact
point. Continuous terrain-impact effects keyed to where a beam hits the world are not achievable from
script alone — use engine projectile collision (impact data sets, explosions) instead.

---

## Papyrus: a recompiled `.pex` only loads at game STARTUP

A `.pex` is read when the game launches. **A mid-session save/load never re-reads it from disk** — not
even loading a save that has never seen your mod. If you recompile a script attached to an active magic
effect or ability and then quickload, the game keeps running the **old bytecode**: Skyrim bakes the
script instance into the save and restores that instance on load.

**The only reliable refresh:** quit to desktop, relaunch, and load a **pre-activation** save (one made
before that effect was ever active). A post-activation save restores its baked instance even after a
full restart.

**Verify which build is live rather than assuming.** Plant a distinctive log line in each build and
check for it in the on-disk log — that is the definitive marker. Separately, grep a newly added string
into the `.pex` on disk first, which distinguishes "it did not compile" from "it did not load".

**Design implication — this is the real fix.** Because loading new code is expensive, make anything you
intend to *iterate* a runtime parameter (a `GlobalVariable` the script reads each run) instead of a
constant. Tuning then never changes the code: one load to get the parameter-driven build in, and zero
reloads for the entire sweep, flipping values live via the console or DevBench. Put the *mechanism*
behind a parameter too, not just the magnitude, so you can swap approaches without recompiling.
