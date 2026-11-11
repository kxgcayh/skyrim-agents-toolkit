# xeditlib

The xeditlib JS wrapper and bundled native libraries are fetched on your machine and never shipped in the toolkit release archive.

## Source and pin

| Property | Value |
|---|---|
| Upstream | [kxgcayh/xeditlib](https://github.com/kxgcayh/xeditlib) (fork of [WingedGuardian/xeditlib](https://github.com/WingedGuardian/xeditlib)) |
| Commit | `96326630099662f14578d273d40b7d9cf7220277` |
| Version | `1.1.0` |
| Native dylib source | [kxgcayh/xedit-lib](https://github.com/kxgcayh/xedit-lib) branch `macos-arm64` commit `df2f8773c67a11b49b9d83fd0fd80067832ced6d` |
| Licence | JS wrapper is MIT; bundled native libraries are MPL 1.1 with notices in the fetched `THIRD_PARTY_NOTICES.txt` |

## Prerequisites

Node.js (>= 24) and `koffi` 2.15.1, installed from the toolkit root via:

```bash
npm ci --ignore-scripts --no-audit --no-fund
```

`koffi` is resolved by upward lookup from `tools/xeditlib/lib/` to `node_modules/koffi`.

## Fetch and verification

Fetch and verify into `tools/xeditlib/lib/`:

```bash
python tools/xeditlib/fetch.py
```

Verify existing installation against the pinned SHA-256 manifest without network:

```bash
python tools/xeditlib/fetch.py --check
```

Force refetch and reinstall:

```bash
python tools/xeditlib/fetch.py --force
```

Output directory: `tools/xeditlib/lib/` (gitignored, never shipped in release archives).
Metadata is kept in `tools/xeditlib/lib/fetched.json`.
