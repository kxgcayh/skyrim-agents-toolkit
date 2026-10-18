# Skyrim AE 1.7.99 / 1.7.104: per-plugin fixes, hook maps and binary patches

What broke in nine SKSE plugins on **Skyrim AE 1.7.99+ (1.7.104.0) with SKSE 2.3.1**, the root cause of each, and the
fix. Read it before you port or patch a plugin to this build, and before you re-investigate a failure that already
has an entry here. The general mechanics (entry points, Address Library formats, the pre-load gate) are in
`skse-internals.md`; the patch method is `binary-patcher-guide.md`; the Mac build is `skse-cross-compile-macos.md`.

Tags are those of `macos-crossover.md`; every entry is **Measured (notes)** unless marked. They were observed on the
maintainer's setup (AE 1.7.104, SKSE 2.3.1, CrossOver on Apple Silicon) and carried over, not re-run for this page.

> **Build-specific warning.** `skse-internals.md` deliberately leaves out hook offsets, RVAs and vtable addresses,
> because each belongs to one game build. This page keeps them because the old workspace they came from is retired.
> Every RVA, file offset and hash here is valid for **1.7.104.0 only** (and the other build named next to it). Re-derive
> them for any other build; do not paste them in.

## 1. The three failure phases

| Phase | Message or symptom | Cause | Fix |
|---|---|---|---|
| 1. SKSE 2.3.1 pre-load gate | `<Plugin>.dll: must be recompiled for new address library` | SKSE reads the exported `SKSEPlugin_Version`. If `versionIndependence & AddressLibraryPostAE` is set, `versionIndependenceEx` must have bit 1 set (`kVersionIndependentEx_AddressLibraryV5 = 1 << 1`) | Patch `struct_offset + 0x304 \|= 0x02`, or recompile with an updated CommonLibSSE-NG |
| 2. CommonLibSSE-NG minor-version trap | `REL/ID.h(219): failed to open address library file` | `Module::load_version` switches on `_version[1]`. A minor version other than 6 falls through to `Runtime::SE` and asks for `version-1-7-104-0.bin` | Patch `cmp ax,6; setne al; inc al` to `cmp ax,6; setb al; inc al` (treats 6 or more as AE), or recompile with CommonLibSSE-NG 12.1.0+ (`_version[1] >= 6`) |
| 3. Address Library format and hook drift | Wrong or no addresses, crashes at a hook | (A) The official `versionlib-1-7-104-0.bin` is **Format 5** (dense array, 96-byte header); old CommonLib reads only **Format 2** (packed deltas), so redirect to `versionl2b-1-7-104-0.bin` or use a Format 5 parser. (B) Inlined engine code moved, was extracted, or changed calling convention between 1.6.1170 and 1.7.104 | Re-verify every hook site on the new binary |

Both byte patches are worked through in `binary-patcher-guide.md` section 2.

## 2. Where the code lives

The source trees were submodules of the retired workspace; they are forks on GitHub (account `kxgcayh`). Clone from
there, not from the old workspace.

| Plugin | Repository | Branch |
|---|---|---|
| ImprovedCameraSE-NG | `kxgcayh/ImprovedCameraSE-NG` | `ae-1.7.104` |
| SkyParkourNG (Agility) | `kxgcayh/skyrim-SkyParkourNG_Agility` | `v3` |
| Better Third Person Selection | `kxgcayh/skyrim-mod-betterthirdpersonselection` (private) | `ae-1.7.104` |
| DovaJump (Blessed NG patch) | `kxgcayh/DovaJump-1.7` | not recorded |
| EngineFixesSkyrim64 | `kxgcayh/EngineFixesSkyrim64` | `master` |
| CommonLibSSE-NG | `kxgcayh/CommonLibSSE-NG` | `ng` |
| Dynamic Armor Variants Extended | `kxgcayh/DynamicArmorVariants-Extended` | tag `v1.8.0-pre.1` |
| Sprint Swim Redux, Quest Journal Overhaul patcher, Interrupt Package Deadlock Fix | not in any repo | the old workspace records them as reference-machine only, and no copy was found there; sections 6, 7 and 8 hold the facts |

Also forked and used for the CrossOver notes: `kxgcayh/loot` (branch `kxgcayh/macos-crossover-compat`),
`kxgcayh/BodySlide-and-Outfit-Studio`, `kxgcayh/modorganizer`, `kxgcayh/Pandora-Behaviour-Engine-Plus` (branch
`feature/crossover-compatibility`), `kxgcayh/MacrimModManager` (private, a native macOS mod manager). See `crossover-loot-and-qt6.md` and
`crossover-bodyslide-opengl.md`.

Not in any repository and not recoverable from one: the original DovaJump files (`Dova Jump`, `Dova Jump NG patch`,
`src`), a pristine SKSE64 2.3.1 source tree, a copy of the 1.7.104.0 `SkyrimSE.exe` used for analysis, and the built
DLLs. Only upstream sources can be re-cloned; rebuild the DLLs with `skse-cross-compile-macos.md`.

## 3. Dynamic Armor Variants Extended (DAVE)

**Engine change.** The target is `TESNPC::InitWornForm` at `RelocationID(24232, 24736)` (RVA `0x3C4080` on 1.7.104).
In 1.7.99+ Bethesda moved part of the worn-armor loop into a standalone helper, Address Library ID `17792` (RVA
`0x27EAE0`).

**Crash.** `Unhandled exception "EXCEPTION_ACCESS_VIOLATION" at 0x7D930: mov eax, [rcx + 0x38]`.
Detouring the entry of ID 17792 crashed because that function receives a `RE::TESNPC*` (the actor base) in `RDX`, not
an `RE::Actor*`. `a_actor->GetActorBase()` then read `[rcx + 0x40]` from a `TESNPC*`, got `nullptr`, and
`actorBase->GetSex()` faulted.

**Fix: hook inside `InitWornForm` at `+0x2F0`** (RVA `0x3C4370` on 1.7.104). Register state there:

| Register | Holds |
|---|---|
| `rbp` | `TESObjectARMO*` (the armor) |
| `r13` | `RE::Actor*` (set by `cmp byte ptr [rdx + 0x1a], 0x3e; cmove r13, rdx`) |
| `r12` | `RE::BSTSmartPointer<RE::BipedAnim>*` (kept from `r8`) |

The Xbyak patch (`src/main/Patches.cpp`) must fit in 0x17 bytes and refuses to install otherwise:

```cpp
void Patches::WriteInitWornPatch(InitWornArmorFunc *a_func) {
  auto hook = util::MakeHook(RE::Offset::TESNPC::InitWornForm, 0x2F0);

  struct Patch : public Xbyak::CodeGenerator {
    Patch(std::uintptr_t a_funcAddr) {
      mov(r8, r12);           // BSTSmartPointer<BipedAnim>*
      mov(rdx, r13);          // Actor*
      mov(rcx, rbp);          // TESObjectARMO*
      mov(rax, a_funcAddr);   // replacement InitWornArmor
      call(rax);
    }
  };

  Patch patch{reinterpret_cast<std::uintptr_t>(a_func)};
  patch.ready();
  if (patch.getSize() > 0x17) { util::report_and_fail("Patch was too large, failed to install"sv); }

  REL::safe_fill(hook.address(), REL::INT3, 0x17);
  REL::safe_write(hook.address(), patch.getCode(), patch.getSize());
}
```

Null guards in the replacement (`src/main/Hooks.cpp`):

```cpp
void Hooks::InitWornArmor(RE::TESObjectARMO *a_armor, RE::Actor *a_actor, RE::BSTSmartPointer<RE::BipedAnim> *a_biped) {
  if (!a_actor || !a_armor) return;
  const auto *actorBase = a_actor->GetActorBase();
  if (!actorBase) return;
  // resolve the variant ...
}
```

**Packaging.** Archives are named `Dynamic Armor Variants Extended v<version>.zip`, with no `.dirty` suffix.

## 4. ImprovedCameraSE-NG

### 4.1 Six bugs on 1.7.104

1. **Build detection never matched (`SkyrimSE.cpp`).** `FileVersion` is `"1.7.104.0"`, so the revision is `104`, not
   `17104`; upstream tested `m_VersionRevision >= 17104`. Fix:
   `else if (m_VersionMajor == 1 && m_VersionMinor == 7 && m_VersionRevision >= 99) m_Build = BuildInfo::k17104;`
2. **Version-range gate rejected valid AE (`plugin.cpp`).** Each version field was compared on its own, so with a
   maximum revision of `104`, AE `1.6.1179` (`1179 > 104`) was rejected. Fix: compare one packed 64-bit value,
   `(maj << 48) | (min << 32) | (rev << 16) | bld`.
3. **Dead 1.7.104 special cases (`Hooks.cpp`).** Special offsets for `TESObjectCell_Get3D` and
   `SmoothAnimationTransitions` were overwritten by duplicate unconditional `REL::VariantOffset` lines right below
   them. Fix: remove the duplicates.
4. **Crash: Papyrus native called without a VM (`Addresses.cpp`).** `GetEquippedItemTypeID` called
   `papyrus::Actor::GetEquippedItemType` (`REL::RelocationID(53876, 54685)`); on 1.7.104 that crashes without a VM
   pointer. Fix: classify locally with `actor->GetEquippedObject(!rightHand)->GetFormType()`.
5. **Corrupted instruction: `SmoothAnimationTransitions` offset.** Upstream used `+0x2F3` on
   `RelocationID(40937, 41996)`. On 1.7.104 that lands on a `je` (`0F 84 ...`) and destroys control flow. The call site
   is **`+0x303`** (`callq *0x388(%rax)`, bytes `FF 90 88 03 00 00`).
6. **POV toggle dead: `TogglePOVHandler` vtable shift (`Hooks.cpp`, `PCH.h`).** 1.7.99+ added `ProcessMotionGesture`
   and `ProcessSixaxis` at indices 2 and 3 of `PlayerInputHandler`, moving `ProcessButton` from index 4 to 6.
   Overwriting index 4 patched an empty `retq` stub (`0x14055D600`) and left the POV button unhooked. Fix: dynamic
   index support in `PCH.h` (`write_vfunc(std::size_t a_index = T::index)`), choosing 6 when
   `pluginSkyrimSE->Build() == BuildInfo::k17104`. The same vtable shift hit DovaJump (section 8) and SkyParkourNG
   (section 9).

### 4.2 Verified 1.7.104 hook map (23 sites, each checked with `llvm-objdump`)

"Payload" rows overwrite an instruction rather than a call.

| Hook | AE ID | Offset | Site RVA | Instruction at the site |
|---|---|---|---|---|
| ProcessInput | 68617 | +0x7B | `0x0CF966B` | `callq` (direct) |
| UpdateSwitchPOV | 40476 | +0x294 | `0x0748FA4` | `callq` (direct) |
| UpdateCamera | 50784 | +0x1A6 | `0x08F8826` | `callq` (direct) |
| UpdateFirstPerson | 40522 | +0xD7 | `0x074C157` | `callq` (direct) |
| TESObjectCell_Get3D | 19165 | +0x7A | `0x02CA2AA` | `callq *0x468(%rax)` |
| **SmoothAnimationTransitions** | 41996 | **+0x303** | `0x07A42D3` | `callq *0x388(%rax)` |
| ShaderReferenceEffect1 | 34913 | +0xE1 | `0x05DE9E1` | `callq` (direct) |
| ShaderReferenceEffect2 | 34913 | +0x1F5 | `0x05DEAF5` | `callq *0x1d8(%rax)` |
| GetEffectNode_IsThirdPerson | 34142 | +0x51 | `0x05BF851` | `callq *0x388(%rax)` |
| ForceFirstPerson | 55564 | entry | `0x0A2AD20` | `movq ...%rcx` |
| ForceThirdPerson | 55565 | entry | `0x0A2AD30` | `movq ...%rcx` |
| Ragdoll | 39895 | +0x5B | `0x072381B` | `callq` (direct) |
| Ragdoll_IsTaskPoolRequired | 39895 | +0x2E | `0x07237EE` | `callq` (direct) |
| Ragdoll_UpdateObjectUpwards | 39895 | +0x2C5 | `0x0723A85` | `callq` (direct) |
| RagdollDeath | 37316 | +0x76 | `0x0677A36` | `callq` (direct) |
| KillActor | 40733 | +0xEC | `0x075E3EC` | `callq` (direct) |
| ThirdpersonFade (payload) | 50832 | +0x4DD | `0x08FAAAD` | overwrites `movss`; the jump lands on a `je` at `0x8FAB07` |
| HorseLookingDownFix1 (payload) | 37356 | +0xB64 | `0x067CEE4` | overwrites a 2-byte `ja` |
| HorseLookingDownFix2 (payload) | 37610 | +0x78 | `0x0692F28` | overwrites a 2-byte `ja` |
| HorseLookingDownFix3 (payload) | 37611 | +0x7F | `0x06930CF` | overwrites a 2-byte `ja` |
| NearDistanceIndoorsFix (payload) | 107125 | +0x14 | `0x1537804` | overwrites exactly one 6-byte `jne rel32` |
| NiCameraUpdate | 70643 | entry | `0x0EF17A0` | `pushq %rbx` |
| FadeOutGame | 52847 | entry | `0x098DD00` | `pushq %rdi` |

## 5. Verifying a hook site (the method behind 4.2)

For each hook, resolve the Address Library ID to an RVA for the target build, add the offset, and disassemble that
address. Accept the hook only if the instruction is the one the hook expects (a call for a call hook, the exact
instruction length for a payload hook). The 23 sites above all passed. A hook that lands on a branch or in the middle of
an instruction, like bug 5 in section 4.1, is the usual cause of a crash at an AE-only call site. Static analysis steps
without source: `skse-internals.md` section 6.

## 6. Sprint Swim Redux SKSE

- Recompiled natively against Format 5 CommonLibSSE-NG instead of patching. Plugin `SprintSwim.dll`. All five
  relocation IDs resolve on 1.7.104: `208717`, `414675`, `414563`, `252907`, `410534`.
- **`min`/`max` macros.** Windows headers `#define max(a,b)`, which breaks `std::numeric_limits<size_t>::max()` in
  `SimpleIni.h`. Fix in `src/settings.cpp`: `#ifdef max` / `#undef max` / `#endif`. DovaJump needed the same
  (define `NOMINMAX` in CMake).
- **Clang C++23 nested class.** Default member initializers inside nested structs that a static inline member refers to
  raise `-Wdefault-member-init`. Fix: define `Control` and `Link` outside `Settings`, before they are used.
- Build: CMake + Ninja with the `clang-cl-msvc.cmake` toolchain and CommonLibSSE-NG
  (`skse-cross-compile-macos.md`).

## 7. Quest Journal Overhaul (QJO), `QuestJournalOverhaul.dll` v1.2.0

- Original SHA-256 `7ff0430e0115ba1439556fc0511aa56599156df91f3dd531aadfaf06cbf519a1`
- Fully patched SHA-256 `4a03517d57d9d168fdf239e93c2e54ae751b0100f70f2f5ded4f4b0ccb2f8770`

| Patch | File offset | Original | Replacement | Purpose |
|---|---|---|---|---|
| SKSE 2.3.1 gate | `0xB3454` | `01 00 00 00` | `03 00 00 00` | sets `kVersionIndependentEx_AddressLibraryV5` |
| AE runtime check | `0x443F8` | `66 83 F8 06 0F 95 C0 FE C0` | `66 83 F8 06 0F 92 C0 FE C0` | minor version 6 or more counts as AE |
| Address Library path | `0xA0CE8` | `versionlib-{}.bin\0` | `versionl2b-{}.bin\0` | read the Format 2 database |

These three patches clear the gate and the version check, but the plugin still failed inside `SKSE::Init` with a raw
SEH exception while loading the Address Library under CrossOver; analysis and open hypothesis: `skse-internals.md` section 8.

## 8. Interrupt Package Deadlock Fix, `InterruptPackageDeadlockFix.dll`

- Original SHA-256 `05cc4a3af83db3642bb24de508182156630da5072a7be37f2ae93c8ebbbb61ce`
- Patched SHA-256 `a6b18a0024978c43917d096c4b22c2bf6016a1c58611956102aa64db803887b4`

Function ID `41331` (the package-evaluation interrupt handler) has call sites that moved by `+0x20` between 1.6.1170
and 1.7.104: site 1 `0x171` to **`0x191`**, site 2 `0x36F` to **`0x38F`**.

| Location | File offset | Original | Patched | Meaning |
|---|---|---|---|---|
| `kRuntime` constant | `0x3D6D8` | `01 00 06 00 92 04 00 00` (1.6.1170.0) | `01 00 07 00 68 00 00 00` (1.7.104.0) | target runtime version |
| `kSites` array | `0x3D6E0` | `71 01 00 00 00 00 00 00 6F 03 00 00 00 00 00 00` | `91 01 00 00 00 00 00 00 8F 03 00 00 00 00 00 00` | call-site offsets |
| `Install()` site 1 | `0x11ABC` | `71 01 00 00` | `91 01 00 00` | immediate `0x191` |
| `Install()` site 2 | `0x11ACF` | `6F 03 00 00` | `8F 03 00 00` | immediate `0x38F` |
| Thunk logging site 1 | `0x5F9` | `71 01 00 00` | `91 01 00 00` | immediate `0x191` |
| Thunk logging site 2 | `0x619` | `6F 03 00 00` | `8F 03 00 00` | immediate `0x38F` |
| SKSE 2.3.1 gate | `0x3D9E4` | `01 00 00 00` | `03 00 00 00` | sets the `AddressLibraryV5` bit |
| Address Library path | `0x42110` | `versionlib-{}.bin\0` | `versionl2b-{}.bin\0` | read the Format 2 database |

## 9. DovaJump (v1.1.0 Blessed NG patch)

### 9.1 Why jumping stopped on 1.7.104

1. **Input suppression.** `HookedCanProcess` intercepts the jump `ButtonEvent` and returns `false` on
   `button->IsDown()` to stop the vanilla instant jump. That enables charge, double and wall jumps on release
   (`button->IsUp()`).
2. **A vtable insertion.** 1.7.99+ added two virtual input handlers to `PlayerInputHandler`, the base of `JumpHandler`:
   `ProcessMotionGesture` (base index 2, composite index 4) and `ProcessSixaxis` (base index 3, composite index 5).
   `ProcessButton` moved from index 4 (1.5.97 to 1.6.1170) to index 6 (1.7.99, 1.7.104).

   | Build | `VTABLE_JumpHandler` RVA | `[1]` `CanProcess` | `[4]` | `[6]` |
   |---|---|---|---|---|
   | 1.6.1170 | `0x18B6F40` | `0x1407A08A0` | `0x14079F380` (`ProcessButton`) | n/a |
   | 1.7.104 | `0x19354A8` | `0x1407B4F10` | `0x14055D600` (`ProcessThumbstick` stub, `retq`) | `0x1407B3150` (`ProcessButton`) |
3. **Silent drop.** Upstream hardcoded `oldVtable[4]`. On 1.7.104 `g_originalProcessButton` therefore called the `retq`
   stub, discarding every jump while `HookedCanProcess` kept blocking the vanilla jump.
4. **SKSE 2.3.1 gate.** The shipped NG patch DLL had `versionIndependenceEx = 0x01` (`NoStructUse` only) and lacked bit 1
   (`AddressLibraryV5 = 0x02`), so SKSE asked for a recompile unless the version was in `compatibleVersions`.

### 9.2 Jump multiplier call site (identical on all AE builds)

Address Library ID `37257`; the call is at `+0x190` on 1.5.97 and `+0x17F` on 1.6.1170 and 1.7.104.

| Build | RVA |
|---|---|
| 1.5.97 | `0x617EF0` |
| 1.6.1170 | `0x6626F0` |
| 1.7.104 | `0x675110` |

`REL::ID(37257).address() + 0x17F` was verified the same on every AE build.

### 9.3 The fix

```cpp
const size_t processButtonIdx = (REL::Module::get().version() >= SKSE::RUNTIME_SSE_1_7_99) ? 6 : 4;
uintptr_t origProcessButtonAddr = reinterpret_cast<uintptr_t>(oldVtable[processButtonIdx]);
std::memcpy(&g_originalProcessButton, &origProcessButtonAddr, sizeof(origProcessButtonAddr));
```

- Clang fixes: define `NOMINMAX` in CMake; replace the MSVC union accessor `.m128_f32[i]` with vector subscripting
  `quad[i]` on `RE::hkQuadReal`.
- Gate compliance: `SKSEPlugin_Version` with `versionIndependenceEx = 0x03` (`AddressLibraryV5 | NoStructUse`) and
  `versionIndependence = 0x05` (`AddressLibraryPostAE | StructsPost629`), and `compatibleVersions` listing `1.7.104.0`,
  `1.7.99.0`, `1.6.1170.0`, `1.6.1130.0`, `1.5.97.0`.

## 10. SkyParkourNG (v3.6.3, AE 1.7.104 port)

### 10.1 Failure modes

1. **Corrupt Address Library vtable IDs.** In `versionlib-1-7-104-0.bin` the automated matching mapped input and camera
   handler vtables to wrong offsets, so hooking through the IDs overwrote unrelated code or static tables. Verified
   1.7.104 RVAs:

   | Class / interface | Corrupt AL RVA | Verified 1.7.104 RVA | Hook |
   |---|---|---|---|
   | `JumpHandler` | `0x01935488` | `0x019354A8` | `VTABLE_JumpHandler[0]` |
   | `SneakHandler` | `0x01935548` | `0x019354E8` | `VTABLE_SneakHandler[0]` |
   | `MovementHandler` | `0x01935360` | `0x019351C8` | `VTABLE_MovementHandler[0]` |
   | `ActivateHandler` | `0x01935720` | `0x01935388` | `VTABLE_ActivateHandler[0]` |
   | `TogglePOVHandler` | `0x01935748` | `0x01935568` | `VTABLE_TogglePOVHandler[0]` |
   | `ReadyWeaponHandler` | `0x019359F8` | `0x01935348` | `VTABLE_ReadyWeaponHandler[0]` |
   | `LookHandler` | `0x019353B8` | `0x01935150` | `VTABLE_LookHandler[0]` |
   | `SprintHandler` | `0x01935CA0` | `0x01935208` | `VTABLE_SprintHandler[0]` |
   | `ThirdPersonState[0]` | offset mismatch | `0x018ECC08` | `VTABLE_ThirdPersonState[0]` |
   | `ThirdPersonState[1]` | offset mismatch | `0x018ECC90` | `VTABLE_ThirdPersonState[1]` |
   | `FirstPersonState[0]` | offset mismatch | `0x0196D8F0` | `VTABLE_FirstPersonState[0]` |
   | `FirstPersonState[1]` | offset mismatch | `0x0196D940` | `VTABLE_FirstPersonState[1]` |
   | `BSAnimationGraphManager[0]` | offset mismatch | `0x01A05798` | `VTABLE_BSAnimationGraphManager[0]` |
   | `PlayerCharacter[3]` | offset mismatch | `0x0192A070` | `VTABLE_PlayerCharacter[3]` |

2. **`ProcessButton` moved from slot 4 to slot 6** in every `PlayerInputHandler` derivative on 1.7.99+. Hooking slot 4
   overwrote unrelated virtual methods and crashed on the first key press.
3. **Static initialization before the Address Library.** In `src/HUD/Scaleform/SkyParkourMenu.hpp`,
   `g_worldToCamMatrix`, `g_viewPort` and `g_fHUDOpacity` were initialized as globals through
   `REL::Relocation<...>::get()`. C++ dynamic initialization of globals runs at DLL load, before `REL::Module` has
   loaded the Address Library, so the process crashed before SKSE initialization began. **Fix:** defer those lookups
   to runtime (after `SKSEPlugin_Load`).
4. **Clang-cl vector syntax and CTAD macros.** C++23 Clang has no `.m128_f32` member access on `__m128`; use
   `reinterpret_cast<const float*>(&vec.quad)[i]` or an explicit vector conversion. Logging macros defined as
   variables in `_Skyparkour.h` clashed with CommonLibSSE-NG class-template CTAD; they became `#define`s.

### 10.2 Reusable vtable resolution

```cpp
namespace Hooking {
    inline std::uintptr_t ResolveVTable(REL::VariantID id, std::uintptr_t rva17104) {
        if (REL::Module::get().version() >= SKSE::RUNTIME_SSE_1_7_99) {
            return REL::Module::get().base() + rva17104;
        }
        return id.address();
    }

    inline std::size_t GetJumpProcessButtonIndex() {
        return (REL::Module::get().version() >= SKSE::RUNTIME_SSE_1_7_99) ? 0x6 : 0x4;
    }
}
```

## 11. EngineFixesSkyrim64

### 11.1 Memory and hook safety

1. **`MaxStdIO` null function pointer (`src/patches/max_stdio.h`).** Upstream tested `proc != nullptr` and then called
   `old = get()` even when `_getmaxstdio` did not resolve from `API-MS-WIN-CRT-STDIO-L1-1-0.DLL`. Fix:
   `const auto old = get ? get() : 512;`.
2. **Volatile registers in the waterflow main-loop hook (`src/patches/waterflow_animation.cpp`).** The trampoline called
   `update_timer()` without saving the volatile x64 registers (`RAX`, `RCX`, `RDX`, `R8`-`R11`, `XMM0`-`XMM5`).
   `update_timer()` calls `RE::GetSecondsSinceLastFrame()` and reads settings, so registers the engine still needed
   were destroyed, giving intermittent CTDs. Fix: push the volatile GPRs, reserve 128 bytes (96 for `XMM0`-`XMM5` via
   `movdqu` plus 32 bytes of shadow space, keeping 16-byte alignment), call, restore everything.
3. **Dynamic sound categories (`src/patches/save_added_sound_categories.cpp`).** A category created at runtime, or
   without a source mod file, returns `nullptr` from `GetDescriptionOwnerFile()`; `srcFile->fileName` then crashed.
   Fix: `if (!srcFile || !srcFile->fileName) continue;` in both save (`Unlock`) and load (`LoadVolumes`).
4. **Tree LOD parent cell and ESL (`src/patches/tree_lod_reference_caching.cpp`).** Distant-tree LOD updates used
   `parentCell->IsAttached()` without checking `parentCell`, crashing during cell streaming. The lookup also shifted
   only normal master indices (`i << 24 | baseId`) and ignored light plugins. Fix: validate
   `parentCell && parentCell->IsAttached()`, check `bEnableStippleFade`, and search `compiledFileCollection.smallFiles`
   with prefix `0xFE000000 | (j << 12) | (baseId & 0x00000FFF)`.
5. **Gate compliance (`src/main.cpp`).** AE builds omitted `versionIndependenceEx` and tied runtime support to
   `1.7.104`. Fix: `versionIndependenceEx = kVersionIndependentEx_AddressLibraryV5 | kVersionIndependentEx_NoStructUse`
   and runtime support for `1.6.1130`, `1.6.1170`, `1.7.99`, `1.7.104`.
6. **Dropped `boost-regex`.** `src/clean_cosaves.cpp` linked all of Boost Regex only to test for the `.skse` extension.
   Replaced with a `HasSKSEExtension` built on `std::filesystem::path::extension()`; `boost-regex` removed from
   `vcpkg.json` and `CMakeLists.txt`. Offline unit tests in `tests/test_main.cpp` run with `BUILD_TESTS`.
7. **Form caching null dereference on temporary references (`src/patches/form_caching.h`).**
   - Crash signature: `Unhandled exception "EXCEPTION_ACCESS_VIOLATION" at 0x7FF774028C68 SkyrimSE.exe+0x1A8C68: mov eax, [rdx]`.
   - Cause: mods such as Better Third Person Selection scan actors and objects in interaction range
     (`ForEachReferenceInRange`), so the engine creates, queries or deletes temporary references (`0xFFxxxxxx`).
     EngineFixes hooks `FormMap_RemoveAt` and `FormScatterTable_SetAt`. `oldFunc(a_this, a_index, a_formIdPtr, a_formPtr)`
     returns `1` on a successful removal, but `a_formIdPtr` can be `nullptr` or point to a cleared slot during a rehash
     or table compression, and `*a_formIdPtr` then faults.
   - Fix: `if (result == 1 && a_formIdPtr != nullptr) FormCache::Remove(*a_formIdPtr);` in `FormMap_RemoveAt`, and a
     `a_formIdPtr != nullptr` check in `FormScatterTable_SetAt`.
8. **Stuck mouse buttons (`src/fixes/stuck_mouse_buttons.h`).** Upstream watched only button 0 (LMB) and deferred the
   event to the next frame through `SKSE::GetTaskInterface()->AddTask()`. When menus toggled quickly (inventory, map,
   favorites), the delay left button-down states stuck. Scaleform bitmask: `kLMB = 1u << 0`, `kRMB = 1u << 1`,
   `kMMB = 1u << 2`. Fix: iterate `kButtonTable` and send `SendMouseUp` synchronously in `ProcessEvent` of
   `MenuOpenCloseEventSink`; null-check `RE::UI::GetSingleton()` in `Install()`.
9. **Stack alignment in the `BSLightingShaderPropertyShadowMap` detour (`src/fixes/bslightingshaderproperty_shadowmap.h`).**
   The detour did `push rbx; sub rsp, 0x20; call r8; add rsp, 0x20; pop rbx`. RSP was 16-byte aligned inside the engine
   function, so the single `push` left it at `16n - 8` and `call r8` broke the Windows x64 ABI alignment; later SIMD or
   aligned accesses faulted. Fix: build an RBP frame and force alignment:

   ```asm
   push rbx
   push rbp
   mov rbp, rsp
   and rsp, -16
   sub rsp, 0x20
   call r8
   mov rsp, rbp
   pop rbp
   pop rbx
   ```

### 11.2 CrossOver, D3DMetal and Apple Silicon

1. **Runtime Wine detection (`src/util/environment.h`).** Queries `wine_get_version` and `wine_get_host_version` from
   `ntdll.dll`, tells Wine on a Darwin host from native Windows NT, and logs it to `EngineFixes.log`, for example
   `Wine <ver> (Host: Darwin) [D3DMetal / Apple Silicon GPTK active]`.
2. **Allocator choice (`src/memory/memory.cpp`).** Upstream defaulted to `DisableTBB = false`, so Intel TBB
   (`tbbmalloc.dll`) hooked the global allocator. Under Rosetta 2 its x86 spinlocks, thread pinning and virtual memory
   pools clash with Darwin memory management, and a missing `tbbmalloc.dll` crashed the game before the Bethesda
   logo. Fix: fall back to `CRTAllocator` (`malloc` / `_aligned_malloc`) when `bWineCompatibility` is on and Wine is
   detected (under CrossOver MSVCRT's `malloc` goes to Darwin's `libsystem_malloc.dylib`, which is lock-free and
   zone-based), and link with `/DELAYLOAD:tbbmalloc.dll` so the loader does not die when the DLL is absent.
3. **Modal dialog deadlock (`src/util/dialog.h`).** Win32 `MessageBoxW` calls in `SafeExit`, `Warnings` and the PreLoad
   checks were replaced with `Util::Dialog::ShowWarning()`. Under Wine with D3DMetal fullscreen or borderless, a modal
   box appears behind the Metal presentation layer or deadlocks Wine's display server, so the game hangs on exit.
   `ShowWarning()` writes the warning to `EngineFixes.log` instead and lets `TerminateProcess` end the process.

### 11.3 Memory manager override and temporary-form save crash (issue #98)

With `bOverrideMemoryManager = true`, saving a game that holds temporary forms (FormIDs `0xFFxxxxxx` from
`Player.PlaceAtMe`, dropped items, dynamic projectiles) and reloading it gave an immediate `EXCEPTION_ACCESS_VIOLATION`
in `SkyrimSE.exe`. Three causes:

1. **A zero-address pointer the engine reads was never set (`RELOCATION_ID(514118, 410163)`).** In vanilla,
   `MemoryManager::Init()` (ID `66862` / `68121`, RVA `0xCDE810` on 1.7.104) sets a global at
   `RELOCATION_ID(514118, 410163)` (RVA `0x3273B78` on 1.7.104, `0x31CA7F8` on 1.6.1170, `0x1EBDC10` on 1.5.97) to a
   16-byte-aligned static zero buffer (`0x143273b88`). Across `SkyrimSE.exe` (inlined `AutoScrapBuffer` code, form
   deserialization, string readers) the engine compares an allocated pointer with `*0x143273b78` and
   `*0x143273b78 ^ 0x10`. EngineFixes' `StubInit()` replaced `MemoryManager::Init()` with `RET` and set `*initFence = 2`,
   but never initialized that pointer. Fix: set `*zeroAddressPtr = g_ZeroAddress` in `StubInit()`, with `g_ZeroAddress`
   aligned to 64 bytes (`Allocator::GetAllocator()->AllocateAligned(1u << 10, 64)`).
2. **`AutoScrapBuffer::Ctor` lost its return value in `RAX`.** In the MSVC x64 ABI, and in vanilla `AutoScrapBuffer::Ctor`
   (ID `66853` / `68108`, RVA `0xCDDF40`), the constructor returns `this` in `RAX` (`mov rax, rcx; ret`). EngineFixes
   declared it returning `void`, so `RAX` held whatever `AllocateAligned()` left (`p_Memory`) or garbage for a
   zero-size allocation, and callers that chained the result got `p_Memory` instead of `a_self`. Fix:
   `static AutoScrapBuffer* Ctor(...)` returning `a_self`.
3. **Missing null and zero-address guards.** `Deallocate()` and `ScrapHeap::Deallocate()` did not check `nullptr`,
   `g_ZeroAddress` or the engine's alternating static zero address (`*zeroAddressPtr ^ 0x10`), and `Size()` called
   `_msize(a_mem)` with `nullptr`, which triggers the MSVC CRT invalid-parameter handler. Fix: `IsZeroAddress(void*)` in
   `src/memory/memory_manager.h` (covers `nullptr`, `g_ZeroAddress`, `*zeroAddressPtr`, `*zeroAddressPtr ^ 0x10`),
   used in `Deallocate()`, `Reallocate()`, `Size()` and `ScrapHeap::Deallocate()`.

## 12. Better Third Person Selection (BTPS)

### 12.1 Two failures

- **Startup rejection.** `BetterThirdPersonSelection.log`: `[C] failed to open address library file`. The prebuilt
  Nexus binary asked for `version-1-7-104-0.bin` instead of `versionlib-1-7-104-0.bin` (phase 2 in section 1).
- **EngineFixes crash.** BTPS's periodic candidate sweep (`NearbyActorScanner.cpp`) queries forms across the active
  cell grid. When it meets temporary or deleted references, EngineFixes' `form_caching.h` dereferenced a null
  `a_formIdPtr` in `FormMap_RemoveAt` and the game crashed (EngineFixes item 11.1.7).

### 12.2 Null-dereference hardening in BTPS

1. `NearbyActorScanner.cpp`: `IsValid`, `HasBlockingFlagsNative` and `HasBlockingFlags` used `object.GetObjectReference()`
   without a null check. Return early (`false` / `0`) if `auto* ref = object.GetObjectReference(); !ref`.
2. `src/lib/FenixUtils.cpp`: in `get_raycast_normal`, `caster->GetParentCell()->GetbhkWorld()` was dereferenced
   directly. In exterior cells or during cell transitions the parent cell can be null or not in the Havok world, and
   `rootCollidable` on Havok bodies was used unchecked. Added `cell && cell->GetbhkWorld()` and
   `rootCollidable != nullptr` guards.
3. `src/lib/Util.cpp`: `playerCam->currentState` was read without checking `playerCam` and `currentState` during menu
   opens and camera transitions. Guarded.
4. Trampoline allocation raised from 128 bytes (`1 << 7`) to 512 (`1 << 9`) in `src/main.cpp`, to avoid exhausting it
   when installing several detours.

### 12.3 Dismount hook verification (1.7.104)

BTPS hooks the horse dismount for "Hold to Dismount" in `src/RevE/Hooks.cpp` at function ID `37864` (the
`PlayerInputHandler` dismount call site) `+ 0xE2`.

- ID `37864` is RVA `0x6A77C0`; the call site is `0x6A77C0 + 0xE2 = 0x6A78A2`.
- Disassembly at that address on 1.7.104:

  ```text
  0x6A78A2: E8 B9 49 00 00    call 0x6AC260 ; Actor::Dismount (Address Library ID 37906)
  0x6A78A7: 48 8B 5C 24 30    mov rbx, [rsp+0x30]
  ```

  The call site at `+0xE2` is intact on 1.7.104.

### 12.4 clang-cl C++23 fixes

1. `static [[nodiscard]]` is rejected (`an attribute list cannot appear here`). Write `[[nodiscard]] static` in
   `FocusManager.h`, `Compatibility.h` and `BTPS_API_decl.h`.
2. `cmake/BetterThirdPersonSelection.cmake` set the MSVC flags (`/permissive-`, `/Zc:__cplusplus`) only when
   `CMAKE_GENERATOR MATCHES "Visual Studio"`. Test `if (MSVC)` instead, so `clang-cl` with Ninja gets them.

### 12.5 Build and packaging

Branch `ae-1.7.104`; the release is packaged with `package-release.sh` in the source directory.

## Sources

- The maintainer's AE 1.7.104 engineering notes (a separate, now retired workspace): the source of every entry above.
- The repositories listed in section 2 hold the code each entry refers to.
- General mechanics and what is and is not confirmed: `skse-internals.md`, Sources.
