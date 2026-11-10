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
| Take a Peek Custom IMenu (`keyholepeekmenu.dll`) | `kxgcayh/jayserpa-take-a-peek-imenu` | `ae-1.7.104` |
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

## 13. Exit Sneak On Sprint (SprintCancelsSneak.dll)

### 13.1 Root cause on Skyrim AE 1.7.104
- **Startup dialog rejection**: `SprintCancelsSneak.dll: REL/ID.h(223): failed to open address library file`.
- Nexus build (v1.2.1, Nexus 138669 by Quantumyilmaz) built against older CommonLibSSE-NG / CommonLibVR. On AE 1.7.104.0 (`minor = 7`), `Module::load_version` fails the `minor == 6` check and falls back to looking for `version-1-7-104-0.bin` (phase 2 in section 1).
- In addition, the AE 1.7.104 database is Format 5 (dense array, 96-byte header), whereas older CommonLib only parses Format 2.
- In AE 1.7.99+, two virtual functions were added to `PlayerInputHandler`, shifting `ProcessButton` from vtable slot 4 (`0x20`) to slot 6 (`0x30`). The old binary called vtable index 4 directly without relocation.

### 13.2 Hook verification and implementation (1.7.104)
- Hook target: `PlayerControls::ProcessInput` dispatcher call site at `RELOCATION_ID(67315, 68617) + 0x7B`.
  - ID 68617 is RVA `0x0CF95F0`; `+ 0x7B` is RVA `0x0CF966B` (VA `0x140CF966B`).
  - 1.7.104 bytes at `0x140CF966B`: `E8 E0 0F 00 00` (`callq 0x140CFA650`). Intact 5-byte direct call.
- Trigger logic:
  - Intercepts `PlayerControls::ProcessInput(RE::PlayerControls* a_controls, RE::InputEvent** a_event)`.
  - Checks if `player->IsSneaking()` and player is moving (`moveInputVec != 0`, `autoMove`, or actor movement flags).
  - Checks if sprint button is held $\ge 0.20\text{s}$ (or $\ge 0.125\text{s}$ for mouse).
  - Debounces with an internal boolean flag until sprint is released.
  - Action: If The Ultimate Dodge Mod (`Ultimate Dodge Mod.esp`, Quest `0xD27A1`) is loaded, dispatches Papyrus `UDSKSEFunctionsScript.EndSneakMode()` via VM. Otherwise, if walking triggers `toggleRunHandler->ProcessButton()`, then `sneakHandler->ProcessButton()`, then `sprintHandler->ProcessButton()`.
  - Key mapping queries `ControlMap::GetMappedKey()` dynamically on dispatch to guarantee full key-remap compatibility without hooking `Journal_SystemTab`.

### 13.3 Build and deployment
- Port source: `skyrim-workspace/mods/ExitSneakOnSprint`.
- Submodule: `extern/CommonLibSSE-NG` checked out to tag `v14.0.1`.
- Built with `clang-cl-msvc.cmake` toolchain targeting `Release` with C++23. Output `SprintCancelsSneak.dll` has `versionIndependenceEx = 0x3` (`AddressLibraryV5 | NoStructUse`).
- Deployed to `<mo2>/mods/Exit Sneak On Sprint/SKSE/Plugins/SprintCancelsSneak.dll`. Original backed up as `SprintCancelsSneak.dll.bak`.

## 14. Immersive Activate (ImmersiveActivate.dll v1.4.1, dann1)

Upstream `dann1/ImmersiveActivate`. Source: `skyrim-workspace/mods/ImmersiveActivate-src`.

**Cause.** Built on old CommonLibSSE (not NG) with a `SKYRIM_AE` build switch, `SKSEPlugin_Version` without the V5 flag
and `OFFSET(se, ae)` macros resolved at compile time. Same phase 1/2/3 failures as section 1.

**Port.** Rebuilt against `alandtse/CommonLibSSE-NG` (installed under `tools/CommonLibSSE-NG/build-install`) with
`add_commonlibsse_plugin`; `SKSEPluginLoad` replaces `SKSEPlugin_Query`/`Load`/`Version`; `OFFSET` became `REL::Relocate`;
`clib-util` is header-only, pinned in `extern/CLibUtil` to the commit in `cmake/ports/clib-util`. NG renames:
`HUDData::crossHairRef` -> `crosshairRef`, `HUDData::Type::kUnk0` -> `HUD_MESSAGE_TYPE::kNone`,
`kActivateNoLabel` -> `kSetCrosshairTargetTextOnly` (both value 3).

**Hook sites checked on 1.7.104.0** (Format 5 database: `rva = u32 at 0x60 + 4*id`; disassembled with `llvm-objdump`):

| Use | ID (AE) | Address | Result |
|---|---|---|---|
| Crosshair text | 40621 `+0x280` | RVA `0x757CF0` | 5-byte `call 0x1401B47F0` (UIMessageQueue::AddMessage shape: `rcx` queue, `rdx` menu, `r8d = 0`, `r9` data) |
| Load-door text | 51622 `+0x255` | RVA `0x935305` | same callee, same argument setup |
| Inventory count | 19700 | RVA `0x2E8520` | reads `[rcx+0x40]`, tests form type `0x1C`/`0x2B`; matches `(refr, bool, bool)` |

`versionIndependenceEx = 0x3`. **Not tested in game**; the DLL was not copied to the live MO2.

## 15. SkyUI AIO Survival (SAS) 7.4, `SAS AE+.dll` (AE 1.6.640 build, no source)

**Measured (static analysis), not run in game.** Files: `skyrim-workspace/mods/SAS/` (`src/patch_sas.py`, `src/make_versionl2b.py`, `NOTES.md`).
Only the DLL needs a patch; the SWFs, `.pex` and `SAS.esl` are version independent. Three failures, in load order:

| # | Failure | Evidence | Fix |
|---|---|---|---|
| 1 | SKSE 2.3.1 gate | `versionIndependence = 5` (AddressLibraryPostAE, StructsPost629), `versionIndependenceEx = 0` at struct+0x304 | OR `0x02` (struct at file offset `0x4E470`, byte `0x4E774`) |
| 2 | Format 5 database | IDDatabase accepts only `format == 2` (`cmp eax,2`, RVA `0xFEAB`); path template at RVA `0x3EF90` | same-length `versionlib-` to `versionl2b-`, and generate the Format 2 file from the official one with `make_versionl2b.py` (type byte `0x77`, absolute u32 ID and offset, 9 bytes per entry; round trip checked against the Format 5 table, and the independent packed-delta decoder reproduces the real `versionlib-1-6-640-0.bin`) |
| 3 | Missing ID in `SKSE::log::log_directory` | `REL::ID(380738)` (a `const char*` holding the My Games subfolder) exists in the 1.6.640 library but not in 1.6.1170 or 1.7.104; a missing ID is fatal (message box + `TerminateProcess`) and this runs on every load | replace the 20-byte `mov [rbp-59h],id / lea / call / mov rcx,[rax]` with `lea rcx,[rip+literal]` plus NOPs; the literal `Skyrim Special Edition` goes in `.rdata` file slack and the section `VirtualSize` is raised (`0x11D12` to `0x11D40`) because the loader maps only `VirtualSize` bytes |

This DLL has no runtime SE/AE/VR switch (no `cmp ax,6` pattern from section 2.1 of `binary-patcher-guide.md`) and no byte patches into
game code; every other dependency is a `REL::ID` call or global: 82270/82292 (`GFxValue::ObjectInterface`), 68233/68239 (`BSSpinLock`),
13894, 400269 (`TESDataHandler` singleton), 400507/400517 (`allForms` and its lock). All resolve in the 1.7.104 library. Struct
layouts and vtable indices the DLL assumes are unverified on 1.7.104. Residual risk: section 8 (the Address Library load itself under CrossOver).

## 16. Skyrim Character Sheet 1.1.4.0 (Nexus 56069), `SkyrimCharacterSheet.dll`

**Measured (static analysis and a clean cross-build), not run in game.** Files: `skyrim-workspace/mods/SkyrimCharacterSheet/`
(branch `ae-1.7.104`, `NOTES.md`). Built on a pre-AE-1.7 fork of CommonLibSSE-NG (`extern/CommonLibSSE-NG`), so it has the
section 1 failures. Rebuilt against `alandtse/CommonLibSSE-NG` 14.0.1 (`find_package`, `add_commonlibsse_plugin`,
`SKSEPluginLoad`); `versionIndependenceEx = 0x3`.

**New class of break: a mod that implements `RE::MenuEventHandler`.** 14.x makes `ProcessKinect/Thumbstick/MouseMove/Button`
non-virtual and dispatches them through `REL::RelocateVirtual` with a per-build slot, so `bool ProcessButton(...) override;`
no longer compiles (`only virtual member functions can be marked 'override'`). The 1.7.99+ layout, confirmed on the 1.7.104
exe from the vtable of `FavoritesHandler` (ID 215785, RVA `0x197C398`; slots 2, 3, 5, 6 are `xor al,al ; ret` stubs, slot 4
and 7 are overrides):

| Slot | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| 1.7.99+ | dtor | CanProcess | ProcessMotionGesture | ProcessSixaxis | ProcessKinect | ProcessThumbstick | ProcessMouseMove | ProcessButton |
| before 1.7.99 | dtor | CanProcess | ProcessKinect | ProcessThumbstick | ProcessMouseMove | ProcessButton | | |

Fix: an intermediate class derived from `RE::MenuEventHandler` that declares the six virtuals in the 1.7.99+ order, and menus
that derive from `RE::IMenu` and that class. The intermediate class is required: with two polymorphic bases MSVC appends a
derived class's new virtuals to the first base's (`IMenu`'s) vtable, not to `MenuEventHandler`'s. Such a DLL cannot also serve
runtimes before 1.7.99, so `SKSEPluginLoad` refuses them. Other 14.x breaks met: `INPUT_DEVICE::kVirtualKeyboard` renamed
`kFlatVirtualKeyboard`; `GetSlotMask()` returns `REX::EnumSet` (`.underlying()`); fmt 11 no longer formats `nlohmann::json`
through its implicit `std::string` conversion (add a `fmt::formatter<nlohmann::json>`). Hook `TweenMenu::CloseTweenMenu`
`VariantID(51839, 52711)` resolves to RVA `0x9884A0` on 1.7.104 and has the expected `AddMessage(tweenMenu, kHide)` body.

## 17. Extended UI 1.2.0d (Nexus 57873, MrJack), `Extended UI.bsa`

**Symptom.** CTD at startup, `EXCEPTION_ACCESS_VIOLATION` at `SkyrimSE.exe+0ECAE2D` (1.7.104), on a loader thread, with
`Extended UI.bsa` on the stack. `mov esi,[rbx+0Ch]` reads the offset field of a 16-byte BSA file record (hash 8, size 4,
offset 4). Reproduced with Immersive Activate unloaded and with InfinityUI 2.1.0.0, so neither is the cause.

**Archive checked.** BSA v104 (Skyrim LE format), 4 folders, 19 files, uncompressed; header, folder records and every
file offset/size parsed consistent and inside the file. The archive is not corrupt. Contents are data only: 4 `.psc`, 4
`.pex`, 9 translation `.txt`, `statsmenu.swf`, `console.swf`. No DLL.

**Fix.** Extract the BSA to loose files and move the BSA aside (community advice for SSE/AE, matches this crash). Extracted
tree: `skyrim-workspace/mods/ExtendedUI/`. Conflicts: the mod overrides `statsmenu.swf` and `console.swf`; as loose files
they now beat other mods' BSA copies. Cause of the engine fault on a valid v104 archive is **not** established.
**Not tested in game.**

**Source.** `github.com/Kapiainen/Extended-UI` (README credits MrJack; no license stated; 50 commits, last 2015-02-24),
cloned to `skyrim-workspace/mods/ExtendedUI/upstream/`. Holds `Data/` (scripts, SWFs), `Flash source/` (`.fla` +
ActionScript for `console` and `statsmenu`) and `TranslationGenerator.py`. Compiling the Flash needs Adobe Flash
Professional CS4 and the Unofficial Skyrim UI SDK. Compared with the shipped 1.2.0d BSA: the 4 `.psc`, both SWFs and
`Extended UI_ENGLISH.txt` are byte-identical; the other 8 translation files differ (upstream has English placeholders,
the release has the contributed translations).

**Crash cause, partly examined.** Crash function `SkyrimSE.exe+0ECAD00` (Address Library id 69752 on 1.7.104) walks a parsed
archive object: folder array at `[archive+0x28]`, 24-byte stride, file-record pointer at `+0x10` of each folder entry, then
`mov esi,[rbx+0Ch]` on a 16-byte file record. It faulted with `rbx = 0x5464FFFE`. A raw v104-as-v105 misread was tested and
**does not** reproduce that value (`0x5464FFFE` is not in the file), so the "v104 folder records read as 24 bytes" theory is
not confirmed. Root cause not established; settling it needs reverse engineering of the loader (REA, only on request).

**1.7 compatibility of the two SWFs (measured).** Extended UI replaces `statsmenu.swf` and `console.swf` with SWF version 10
files built on LE 1.9.32. The vanilla 1.7.104 ones (extracted from `Skyrim - Interface.bsa`, saved in
`skyrim-workspace/mods/ExtendedUI/extracted/vanilla-se-1.7.104/`) are SWF version 15 and contain code Extended UI's lacks:
`statsmenu`: `CrossPlatformButtons`, `PLATFORM_NX/PROSPERO/SCARLETT`, `LegendaryButtonInstance`, `LegendaryCountText`,
`LegendaryIconInfoInstance`; `console`: `InputDetails` with `controllerIdx` and `navEquivalent`. Loose files win, so the LE
builds replace those. In-game effect not tested. Port route: recompile vanilla SE ActionScript with the Extended UI edits
(upstream `Flash source/*/StatsMenu.as`, `Console.as`, 842 and 375 lines, `EXUI_` hooks) using JPEXS FFDec (not installed;
Java 27 present).

## 18. Take a Peek 1.31 (Nexus 66908, jayserpa), `keyholepeekmenu.dll`

**Built (clang-cl cross-build, clean), not run in game.** Port DLL SHA-256
`aef7d87b5918974df3ec710d69fca341218954b9a81cc52e41c29bfd0b332c1c`, `versionIndependenceEx = 0x3`,
`versionIndependence = 0x1`. Files: `skyrim-workspace/mods/TakeAPeek/` is the git checkout itself (branch `ae-1.7.104`, fork in section 2).
Released 2026-11-01 as `v1.3.1-ae1.7` on the fork (tag on `698f120`), asset `keyholepeekmenu-1.3.1-AE-1.7.zip`
(`SKSE/Plugins/keyholepeekmenu.dll`), zip SHA-256 `f0c9e7852d7513dac19ae49b4d4d4375bfd43c220cb141a96ef4214edeee758f`.
Installed DLL SHA-256 `f8d61588f7bb338527fb78784a1f7d98bf1065834acf5d50a5a906c6feec72d5`, built 2022 on vcpkg
CommonLibSSE-NG, so section 1 phases 1-3. Source: `Osmosis-Wrench/jayserpa-take-a-peek-imenu` (MIT); its strings and RTTI
match the shipped DLL. The plugin has no game hooks: three Papyrus natives on `Keyhole` and an `IMenu` subclass (not a
`MenuEventHandler`, so the section 16 slot shift does not apply). Port: `add_commonlibsse_plugin` against NG 14.0.1 and
`SKSEPluginLoad`; no RVAs to verify. Only the DLL changes.

## 19. dTry's Key Utils 1.1 (Nexus 69944), `DtryKeyUtil.dll`

**Built (clang-cl cross-build), not run in game.** Files: `skyrim-workspace/mods/DtryKeyUtil/` is the git checkout of
`D7ry/DtryKeyUtil` (no license; personal use only), branch `ae-1.7.104` commit `5e7ac10`, not pushed. Port DLL SHA-256
`f96803d470956259f42d60a4246e66f12c377251d7f33d3be42df84dccbade6d`. Shipped DLL (SHA-256
`5261d3459f3c56bd0787d5b2bca9fd57dbc1471c39f8188e312d4d4d6baef777`) exports `SKSEPlugin_Query` only; SKSE 2.3.1 logs
`plugin DtryKeyUtil.dll (00000000  00000000) no version data 0 (handle 0)` and skips it.

**The one hook is the 1.7.99 `PlayerInputHandler` slot shift** (same class as sections 4.1 item 6, 9 and 10):
`write_vfunc(0x2, ProcessThumbstick)` and `write_vfunc(0x4, ProcessButton)` on `VTABLE_MovementHandler[0]`. On 1.7.104
the vtable (ID 208715, RVA `0x19351C8`) has `ret 0` stubs at slots 2, 3, 5 and the real overrides at 4 (`0x7B38C0`,
Thumbstick) and 6 (`0x7B37C0`, Button). Fix: `REL::VersionShift(slot, RE::PlayerInputHandler::kAE1799AddedVFuncCount,
SKSE::RUNTIME_SSE_1_7_99)`, which NG 14.0.1 already uses internally. Build fixes: `NOMINMAX`, Windows `ERROR` macro vs
`ERROR(...)` log calls. Result `versionIndependenceEx = 0x3`.

**Correction to section 10.1.** With the `versionlib-1-7-104-0.bin` installed on 2026-11-01, ID 208715
(`VTABLE_MovementHandler`) resolves to the verified `0x19351C8`, not the corrupt `0x1935360`. Resolve the ID against the
installed file before applying a hardcoded RVA override; the corrupt mapping may belong to an older Address Library release.

## 20. Hair Colour Sync NG 1.4.1 (Nexus 156414, kingeric1992), `HairColourSyncNg.dll`

**Measured: the rebuild loads in game (2026-11-02).** Source: `skyrim-workspace/mods/HairColourSyncNG/` (git repo, branch `ae-1.7.104`; rebuild with section 7 of `skse-cross-compile-macos.md`, no CommonLib prefix needed). The binary patch below is documented byte for byte; its script was not kept.
Source: `kingeric1992/HairColourSyncNg` (old `commonlibsse-ng-fork` vcpkg port).
Port: `kxgcayh/HairColourSyncNg` branch `ae-1.7.104` (CommonLibSSE-NG v15.5.0 submodule); upstream PR kingeric1992/HairColourSyncNg#1.

- Symptom: `skse64.log` ends at `loading plugin "HairColourSyncNG"` and the game never starts. The SKSE 2.3.1 gate passes
  (`versionIndependenceEx = 1`, no "must be recompiled" line), so this is phase 2, then phase 3A.
- Fix: `binary-patcher-guide.md` 2.1 (`0f95` to `0f92` at file `0x4D71`) and 2.2 (`versionlib-` to `versionl2b-`). Two bytes.
  SHA-256 `3153c565...e5dd` to `05e04571...3df5`. Needs `versionl2b-1-7-104-0.bin` in Data (the SAS one works).
- One hook, `AttachArmor`, `RELOCATION_ID(15535, 15712)`, `write_branch<5>` at function entry. ID 15712 is RVA `0x21D170` on
  1.7.104 with the prologue `44 89 4C 24 20 4C 89 44 24 18`, identical to 1.6.1170, which is what the plugin's own AOB check
  wants. On a mismatch it shows a message box rather than patching.
- **CTD after the patch was unrelated**: the same crash (`SkyrimSE.exe+1DCB60`) happened with the plugin disabled; it was a
  missing master in the load order. The binary patch is untested in game, not disproven. The hooked function still takes 7
  arguments on 1.7.104.
- **Rebuild:** GitHub HEAD `52c5128` is Nexus **1.3.1**; the Nexus **1.4.1** (hair-physics CTD fixes) has no public source.
  Built against `alandtse/CommonLibSSE-NG` 15.5.0 with two source fixes (`GetGeometryRuntimeData().properties[kEffect]` is now
  `.shaderProperty`; clang rejects `[[msvc::forceinline]]` on lambdas). Plugin keeps its own `SKSEPlugin_Version`; the NG default
  `versionIndependenceEx = AddressLibraryV5` gives `0x3` with `UsesNoStructs()`, so the SKSE 2.3.1 gate passes without `add_commonlibsse_plugin`.
- **In game (2026-11-02):** the rebuild (SHA-256 `1f89a90d...4c76`) loads (`loaded correctly`, version `01030001`) and the game runs with it. Wig colour sync itself not yet confirmed.
- **PR build in game (2026-11-02):** the submodule build of branch `ae-1.7.104` (SE+AE+VR, SHA-256 `0dca5b2a...76e8`) loads correctly on 1.7.104; user reports it works.
- **CTD on save load, upstream 1.3.1 bug (measured 2026-11-02):** `HairColourSyncNg.dll+252B0` (`movzbl (%rdx)`, RDX = 0x30) on
  the `RSM_Initialized` mod event: `attachPlayer` dereferences RaceMenu's `_hairColor`, which unpacks to None when `_customHair`
  is true, and does not null-check `Get3D(false)` either. Fix: null-check both before `attach` (port commit `dedd610`). The
  save that crashed then loaded (user confirmed).

## 21. Porting traps common to every rebuild (CommonLibSSE-NG 12 -> 14/15)

Found across the ports above (2026-10-27 to 2026-11-03); each one cost a failed build or a failed launch.

- **Rebuild the DLL the ENABLED mod ships.** Hash the DLL in the folder that has the `+` line in `modlist.txt` and match its
  PDB source list to a commit. Apprentice was rebuilt from the 1.1.0 source of a disabled Nexus folder while the enabled
  folder (`Appprentice`, three p's) shipped 1.3.2; the 1.1.0 build null-dereferenced on New Game.
- **Two mods shipping the same DLL name.** Tell them apart by the `SKSEPlugin_Version` struct bytes (`+0x304`
  `versionIndependenceEx`, `+0x308` `versionIndependence`) and the version field in `skse64.log`'s line. A
  `no version data` line means the DLL exports `SKSEPlugin_Query` but not `SKSEPlugin_Version` (a 1.5.97 build): often
  another mod bundles an outdated copy (Simply Knock SE ships a pre-AE `PapyrusUtil.dll` that overrode PapyrusUtil AE by
  priority). Delete the bundled copy in the mod manager. Triage: `grep "no version data" skse64.log`, find every copy in
  `mods/`, compare exports with `llvm-readobj --coff-exports`.
- **Manual CommonLibSSE-NG install (no vcpkg port).** `cmake --install` omits `cmake/CommonLibSSE.cmake` (it defines
  `add_commonlibsse_plugin`) and the generated config lacks `find_dependency(directxtk)`: copy the `.cmake` into
  `lib/cmake/CommonLibSSE/` and add `find_dependency(directxtk CONFIG)` before the targets include. Configure with
  `-DENABLE_SKYRIM_VR=OFF -DBUILD_TESTS=OFF` (`extern/openvr` is an empty submodule).
- **14.x API breaks.** No `UNICODE` (use `GetModuleHandleW` for wide literals); `NOMINMAX` must precede `RE/Skyrim.h`;
  `ActorValueOwner::RestoreActorValue(modifier, av, v)` is gone (the 2-argument versions force the sign; use the virtual
  `ModActorValue(modifier, av, v)`); `RE::DebugNotification` is gone (`RE::SendHUDMessage::ShowHUDMessage`).
- **`SKSE::AllocTrampoline(n)` runs once** (`std::once_flag`) and fixes the total size. A helper that calls
  `AllocTrampoline(14)` before each `write_call<5>` leaves a 14-byte trampoline, and the second hook fails with
  `SKSE/Trampoline.cpp(164): Failed to handle allocation request`. Call it once after `SKSE::Init` with 14 x the number of
  call hooks plus margin.
- **`add_commonlibsse_plugin(... STRUCT_DEPENDENT)`** emits `versionIndependenceEx = 0x2` and `versionIndependence = 0x1`
  (no `StructsPost629`), which tells SKSE the plugin uses pre-1.6.629 structs (flag bytes measured; rejection inferred from
  NG's comment in `SKSE/Interfaces.h`, not tested). Plugins that read version-shifted structs through
  `RUNTIME_DATA_ACCESSOR`s pick the layout at runtime and should keep the default (`0x3` / `0x1`).
- **A post-build `copy_if_different` to `$SKYRIM_MODS_FOLDER` / `$SKYRIM_FOLDER`** in a mod's `CMakeLists.txt` writes
  straight into the live install. Configure with those variables unset.
- **The 1.6.1170 `SkyrimSE.exe` is SteamStub-encrypted** (`.text` is noise), so code cannot be diffed across builds without
  an unpacked copy. The 1.7.104 executable is readable. For hardcoded-RVA plugins, map Format 2 (1.6.1170) offset -> ID ->
  Format 5 (1.7.104) offset; Format 5 is `uint32 rva[id]` from file offset 96.

## Sources

- The maintainer's AE 1.7.104 engineering notes (a separate, now retired workspace): the source of every entry above.
- The repositories listed in section 2 hold the code each entry refers to.
- General mechanics and what is and is not confirmed: `skse-internals.md`, Sources.
