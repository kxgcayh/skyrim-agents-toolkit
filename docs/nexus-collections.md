# Nexus collections to MO2 inputs

Tool: `python tools/nexus-collection.py plan|download <slug> --out DIR` (stdlib; needs `bsdtar` or `7z`; Premium key for `download`).
`bash tools/nexus.sh collection <slug>` is the quick GraphQL name list only (no order, no file pins).

`plan --mo2` writes only `modlist.txt` and, when present, `plugins.txt` (the MO2 profile files) and removes the intermediate `collection.json`.

## What each source gives (Measured, collection `rzkoas`, 2026-10-19)

- **v3 REST (`api.nexusmods.com/openapi.yaml`)**: the `collections` tag is write-only (create, edit, create revision). There is no GET
  for a collection's contents. Do not look there for reads.
- **v2 GraphQL**: `collection(slug) { latestPublishedRevision { revisionNumber downloadLink modFiles { fileId optional file { mod { modId name } } } } }`.
  `modFiles` is a plain list, not `nodes`. It carries names only: no order, no FOMOD choices, no md5.
- **Manifest** (`downloadLink` -> `GET /v2/collections/<id>/revisions/<id>/download_link` -> a 7z holding `collection.json`): the authoritative
  source. Per mod: `source.{modId,fileId,md5,fileSize,logicalFilename}`, `optional`, `choices` (FOMOD selections, 48 of 283 here);
  plus `modRules` (before/after, 110), `plugins`, `pluginRules`. Entries are per FILE, so one Nexus mod can appear twice.
- **v1** `files/<id>.json` gives the real archive `file_name` (matches the manifest's `fileExpression`); `download_link.json` gives CDN URLs
  (Premium, expire within the hour).

## Gotchas

- **No plugin load order**: `rzkoas` has 5 `plugins` entries (forced on/off) and empty `pluginRules`/group `after` lists, so the collection leaves plugin
  order to LOOT. `plan` writes `plugins.txt` only when entries cover at least half the mods, else it says to run LOOT.
- The CDN answers **HTTP 403 to the default `Python-urllib` User-Agent** (curl's passes). The tool sends its own descriptive agent
  instead of impersonating a browser.
- MO2 `modlist.txt` lists the **highest priority first** (verified against a live profile: the `NEW & UNSORTED` separator is line 1, `*DLC:`
  lines last). `plan` writes it in that order from a topological sort of the before/after rules. Names are the manifest names, so they
  only match mod folders MO2 creates if you install under those names.
- `download` verifies each archive against the manifest md5 and writes the MO2 `.meta` beside it; it is a dry run without `--apply` and
  skips archives it already has. Total for `rzkoas` is 35.7 GB: check disk first.

## Not done

Installing archives into MO2 mod folders. FOMOD choices are exported to `fomod-choices.json` for reference only; applying them needs a
FOMOD runner. Archives go to `DIR/downloads`; copying them into MO2's downloads folder is left to the user.
