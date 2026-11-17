# skyrim-workspace

Working area next to the toolkit, created by the toolkit's `setup.sh`. Staging for third-party mods and tools you hand
to an agent, and for the things you build. Not a git repo; each item under `mods/` or `tools/` may be its own repo.
Every new file an agent creates lands here, never in the toolkit. Agents: read `AGENTS.md` first.

    tools/<Name>/   upstream/  extracted/  src/  build/  dist/  NOTES.md
    mods/<Name>/    upstream/  extracted/  src/  build/  dist/  known-good/  NOTES.md
    reports/        audits, generated lists (sorted modlists, patch audits)
    scratch/        throwaway files; safe to empty

- `upstream/`: the archive exactly as downloaded, with its SHA-256 in NOTES.md. Never modified.
- `extracted/`: unpacked copy for reading. Extract each archive into its own new, empty folder; run scripts from outside it.
- `src/`, `build/`, `dist/`, `known-good/`: only when you have source, a build, a package or a working snapshot.
- `NOTES.md`: version, source URL, SHA-256, the mod-update-check verdict, install target, what was verified.
- A mod you create yourself gets its own git repo under `mods/<Name>/`, with a `README.md` written as its Nexus page,
  `BUILDING.md`, `NOTES.md`, `LICENSE`, a build script, and no other mod's data in the repo.

Submodules
- Shared through `tools/`: `./link-submodules.sh clone <url> mods/<Name>` or `./link-submodules.sh link <repo>`.
  One clone per upstream in `tools/<Name>`; each submodule path is a detached worktree of it at the pinned commit.
  Never clone with `--recursive` or run a submodule init here.

Where the toolkit is
- `toolkit.env` holds `SKYRIM_TOOLKIT_DIR`, written by the toolkit's `setup.sh` and rewritten when the toolkit moves.
  The game, config and mod-manager folders are in `skyrim-paths.env` at that toolkit root.
- Nothing here is installed by an agent. Mods go in through your mod manager, or `tools/mod-install.py` in the
  toolkit (dry run first, then `--apply`).
