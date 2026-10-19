# Skyrim Modding Knowledgebase (SE / AE / VR)

A living document of quirks, gotchas, and hard-won lessons about Skyrim modding (SE / AE / VR). Everything here was either discovered through debugging or verified via web research. VR-specific behavior is called out as such. Always consult this before making changes.

> **Fork note.** This fork targets Skyrim SE and AE on PC. Sections about VR (VR vs SSE differences, VR controller input, VR weapon collision, VR Playroom, OpenComposite) are inherited from upstream and have not been tested here. Treat them as unverified; everything else applies to flat Skyrim.

This file is an index. The content lives in `kb/`; open only the file that matches the task. The 18 most dangerous gotchas are always in context in `CLAUDE.md` / `AGENTS.md`. Your own findings go in `KNOWLEDGEBASE.local.md`, never here or in `kb/` (both are replaced on update).

| Read | When you are about to... |
|---|---|
| `kb/papyrus.md` | write, compile, debug or read the log of a Papyrus script; `.pex` loading; VM load problems |
| `kb/esp-xedit.md` | edit a plugin with xEdit, xelib or Spriggit; FormID, master-count, game-path traps; records reused from vanilla |
| `kb/tools-and-assets.md` | touch a NIF, audio, music, BSA; parse or edit a save or co-save; read a crash log |
| `kb/environment-and-guards.md` | resolve paths under MO2 or a second `My Games`; use DevBench; understand a hook, guard or lock behaviour |
| `kb/engine-and-combat.md` | stagger, bleed, knockback, spawned-actor crashes, other engine quirks |
| `kb/vanilla-reference.md` | judge a gameplay-mod conflict; need vanilla formulas, FormIDs/EditorIDs or the vanilla bug catalogue |
| `kb/vr.md` | the target includes Skyrim VR: VR vs SSE, controller input, VR Papyrus, VR physics (inherited, untested here) |

Sections by file (search a heading with `grep -n '^## ' kb/*.md`):

- `papyrus.md`: Papyrus Scripting; Papyrus Debugging in VR; Papyrus Log cleanup lessons; VM page-policy CTD; recompiled `.pex` loads only at startup; No Papyrus Raycast
- `vr.md`: VR vs SSE Differences; VR Controller Input Detection; VR Papyrus Confirmed Findings; Havok Units and VR Hit-Detection; Immobilizing in VR; Weapon Manipulation at Runtime
- `esp-xedit.md`: xEdit / xelib / ESP Editing; ESP Creation via Spriggit; `setFormID` master-count trap; `setGamePath` trailing separator; reused vanilla records carry Conditions
- `tools-and-assets.md`: Save File Analysis; ReSaver CLI; cosave-info; Music System; Orphaned Extended Skeletons CTD; Audio & Tooling; AutoMod BSA needs `bsarch.exe`; NIF Tooling; NIF Validation; CrashLogger `.LOG`
- `environment-and-guards.md`: Hook Candidates; DevBench; MO2 virtual filesystem; `sed` and Windows paths; multiple `plugins.txt`; skill `paths:` gating; guard depth; hook timeout economics; verify-release hook floor
- `engine-and-combat.md`: Game Engine Quirks; Stagger & Bleed; Explosion knockback; Spawned-Actor Havok CTD
- `vanilla-reference.md`: Combat & Defense Formulas; Crafting & Leveling Formulas; Vanilla Record Reference; Vanilla Bug Catalogue
