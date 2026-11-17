---
name: github-mod-fetch
description: Download a Skyrim mod published as a GitHub release (an archive, or a bare SKSE .dll or plugin) into the OS Downloads folder as an archive Mod Organizer 2 can install, with a download .meta beside it so MO2 shows the release tag as the mod's version. Use when the user wants a mod from GitHub, a GitHub-only fix or plugin, or a GitHub release installed through MO2.
---

# GitHub mod fetch

`tools/github-mod-fetch.py` turns one GitHub release asset into `<archive>` + `<archive>.meta` in the OS Downloads
folder. MO2's "Install a new mod from archive" reads that `.meta` from the archive's own folder and copies its
version, mod id and categories into the installed mod's `meta.ini`. Without it the mod installs as version
`0.0.0.0`; a bare `.dll` asset is not an installable archive at all.

## 1. Research before downloading

- Read the repository's README, the release notes and the open issues. Follow the Nexus research rule too when
  the mod also has a Nexus page.
- For an SKSE `.dll`, find which game builds it targets (README, `SKSEPlugin_Version`, release notes) and compare
  with the user's game version. For AE 1.7.x read `docs/ae-1-7-104-plugin-fixes.md` first.
- For an update or a new mod on an existing install, run the `mod-update-check` skill for the verdict. This skill
  only fetches.
- Check whether an installed mod already does the same job (two plugins patching the same function).

## 2. Choose the arguments

| Argument | Source |
|---|---|
| `owner/repo` or a github.com URL | the repository |
| `--mod-category N` (required) | the Nexus mod category id. If the mod is also on Nexus, use that page's `category_id`; otherwise pick the category it would have: `bash tools/nexus.sh raw /games/skyrimspecialedition.json` lists them (95 Bug Fixes, 39 Utilities, 84 Patches) |
| `--nexus-id N` | only when the same mod is on Nexus, so MO2 can check it for updates |
| `--tag T` | a specific release; default is the latest |
| `--asset NAME` | when the release has several archives or DLLs (the tool lists them and refuses) |
| `--file-category` | `main` (default), `update`, `optional`, `old`, `miscellaneous` |
| `--name NAME` | the mod name MO2 shows; default is the repository name |

The version in the `.meta` is always the release tag minus one leading `v` (`v1.1` becomes `1.1`), never the
DLL's file version or the asset name. A tag with no digit is refused.

## 3. Run it

```
python tools/github-mod-fetch.py <owner/repo> --mod-category N [options] --dry-run
python tools/github-mod-fetch.py <owner/repo> --mod-category N [options]
```

Show the user the dry run (release, asset, archive path, the `.meta` text) before the real run.

What it writes:
- archive asset: kept byte for byte, top-level entries listed, with a warning when none is a data folder or plugin;
- bare `.dll`: `<repo>-<version>.zip` with `SKSE/Plugins/<dll>` (plus a `.pdb`/`.ini` asset of the same name)
  and a root `meta.ini` whose `url` opens the repository from MO2;
- bare plugin: the same zip with the plugin at the root.

It checks the size and GitHub's SHA-256 digest when published, prints the SHA-256, refuses to overwrite without
`--force`, and refuses an `--out` inside the game folder or the MO2 instance. Exit 0 written, 1 network or
verification failure, 2 refused.

## 4. Hand over to the user

The agent does not install into MO2. Tell the user:
1. MO2 > "Install a new mod from archive" > the archive in Downloads. The `.meta` must stay beside it; dragging
   the archive from another folder gives MO2 a blank `.meta`.
2. After install, check the mod's version column shows the tag version.
3. For an SKSE plugin, check `skse64.log` (or the plugin's own log) for a successful load on the next launch.
