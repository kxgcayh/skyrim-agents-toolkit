# spriggit-fork

The Spriggit fork is built from pinned source on your machine and never shipped in the toolkit release archive.

## Source and pin

| Property | Value |
|---|---|
| Upstream | [kxgcayh/Spriggit](https://github.com/kxgcayh/Spriggit) (fork of [Mutagen-Modding/Spriggit](https://github.com/Mutagen-Modding/Spriggit)): CLI-only, runs natively on macOS and Linux |
| Branch | `audit-fixes` |
| Commit | `90e6fc550e2f04b6a424c70ce57d9ad713da3255` |
| Version stamped into the build | `0.1.0-audit-fixes` |
| Licence | GPL-3.0-only |

## Prerequisites

Git and the .NET 10 SDK, the same SDK the pinned upstream CLI needs. The first build downloads its NuGet packages.

## Build and verification

```bash
python tools/spriggit-fork/fetch.py          # fetch the pinned commit, publish, install into bin/
python tools/spriggit-fork/fetch.py --check  # verify commit pin and binary SHA-256, no network
python tools/spriggit-fork/fetch.py --force  # rebuild
```

The fetch is `git fetch --depth 1` of the pinned commit, and the build is refused unless `HEAD` equals the pin. Git object hashes make that check cover the content, so there is no per-file manifest as in `tools/xeditlib`. The binary's SHA-256 is recorded in `bin/fetched.json` at build time; .NET builds are not byte-reproducible, so it detects later changes, not a different build.

Output: `tools/spriggit-fork/bin/Spriggit.CLI` (`.exe` on Windows), gitignored and never shipped. `tools/spriggit-cli.sh` uses it ahead of a `spriggit` on `PATH`. Its `--version` prints the fork's version, so pass `--PackageVersion 0.41.0` (the translation package), not what it prints.

Limit: plugins on translation packages 0.35.1 or older need the historical Windows-only upstream CLI.
