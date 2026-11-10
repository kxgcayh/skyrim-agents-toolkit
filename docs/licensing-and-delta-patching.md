# Mod licenses and delta patching: what an agent may ship

How to handle a user's request to fix or modify a mod whose license forbids redistributing changed binaries. Read it
before you build, patch or package anything derived from a third-party DLL. It complements "Never bare-copy a
third-party mod into `Data/`" in `CLAUDE.md`, which is about installing; this page is about distributing.

This is the maintainer's reading of the licenses named below, not legal advice. Read the actual `LICENSE` of the mod
in question every time.

## 1. The landscape

- **Bethesda's terms** cover the engine, the official assets and the file formats. Derivative game assets cannot be
  sold, and game content cannot be monetized directly.
- **Authors own their own code and assets**: C++ source, custom meshes and textures.
- Licenses vary. `CommonLibSSE-NG` is MIT. Many popular mods are source-available or closed-distribution, for example
  *Modern Wait Menu* under the **Fallen01135 Mod License**.

## 2. Worked example: the Fallen01135 license

Clauses that decide what an agent may do (section numbers are those of that license's `LICENSE.md`):

| Section | Says (quoted) | Consequence |
|---|---|---|
| 18, redistribution | "You may not distribute the DLL (or any other native executable code, i.e. `.dll` / `.exe`) in any form other than my official release. No re-uploads, no modified builds, no builds of my source code, and no patching or reverse-engineering of the binary file." | A patched DLL is never shareable |
| 26, private use | "You may use and modify it privately (e.g. your own builds of the DLL, or your own tweaks to plugins and assets)." | A local patch for the user's own game is allowed |
| 29, patches and add-ons | "Publish patches, translations, and add-ons that require this mod and are free of charge... They must not include the DLL." | Add-ons are fine if they ship without the DLL |
| 31, contributions | "You may fork the repository on GitHub for that purpose, change the source code (including the DLL's source), and build it for testing... send changes as a Pull Request." | The upstream route is open |

## 3. Rules for an agent

**Never**

1. Package or distribute a modified `.dll` of a non-open-source mod for public sharing.
2. Upload modified third-party binaries to Nexus or any file host without the author's explicit permission.

**Do**

1. **Patch locally.** Changing a file on the user's own drive for their own play is covered by the private-use clause.
2. **Hand over a delta, not a binary.** A Python patcher or an `.xdelta` file that is applied to the user's own legally
   acquired copy holds only offsets and replacement bytes, not the author's code or game assets. How to build one:
   `binary-patcher-guide.md`.
3. **Contribute upstream.** Fork, fix on a clean branch, and give the user the PR title and description to submit.

A patcher should refuse a build it was not written for: it finds each byte pattern, asserts it occurs exactly once,
and logs the hashes before and after. The template in `binary-patcher-guide.md` does that.
