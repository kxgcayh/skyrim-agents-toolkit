# The workspace

The workspace is a folder next to the toolkit where every new file goes: mods and tools you were handed, things you
build or patch, reports, and throwaway test output. The toolkit is a public project and is replaced on every update,
so nothing of yours belongs in it, and a stray file there can end up in a release.

`setup.sh` creates it and records where it is, so an agent started in the toolkit and an agent started in the
workspace both know the same thing.

## What setup does

- Default location: `skyrim-workspace` in the folder that holds the toolkit. Change it with
  `bash setup.sh --workspace <dir>`; skip it with `bash setup.sh --no-workspace`.
- Records it as `SKYRIM_WORKSPACE_DIR` in `skyrim-paths.env` (machine-local, not tracked). It is not a guarded folder,
  so an agent can delete in its `scratch/`. A value you set by hand survives a re-run, like the other paths.
- Creates only what is missing, from `agent/workspace/`: `mods/ tools/ reports/ scratch/`, `README.md`, `AGENTS.md`,
  `CLAUDE.md`, `link-submodules.sh`. An existing file is never overwritten, so a workspace you already use is kept.
- Writes `toolkit.env` in the workspace with `SKYRIM_TOOLKIT_DIR`, the toolkit's folder, and rewrites it when the
  toolkit moves. Scripts in the workspace read the toolkit's paths through it instead of hardcoding them.
- Fills the **Workspace** line in `CLAUDE.md` / `AGENTS.md`, so an agent in the toolkit knows where to put files.
- Refuses a workspace inside the toolkit or the game folder.

## What an agent does in it

The workspace's own `AGENTS.md` (and a `CLAUDE.md` that points to it) tells an agent to read the toolkit's
instructions and `KNOWLEDGEBASE.local.md` first, where each kind of file goes, that `upstream/` is never modified,
and that nothing is installed from there. Some agents read instructions only from the folder they were started in:
start the agent in the workspace (or in the item you work on) and tell it to read `AGENTS.md`.

## Using it from a script

```python
import sys
sys.path.insert(0, "<toolkit>/tools")
import skyrim_paths
skyrim_paths.workspace_dir()      # Path, or None when no workspace is recorded
skyrim_paths.game_root()          # (Path, where the answer came from)
```

In shell, `. <workspace>/toolkit.env` sets `SKYRIM_TOOLKIT_DIR`. The game, config and mod-manager folders are in
`skyrim-paths.env` at the toolkit root; read it as data (`tools/skyguard/paths.py`), never source it.

## Moving or turning it off

Move the folder, then set `SKYRIM_WORKSPACE_DIR` in `skyrim-paths.env` and re-run `bash setup.sh`, or run
`bash setup.sh --workspace <new dir>`. `bash setup.sh --no-workspace` records none; the Workspace line in
`CLAUDE.md` / `AGENTS.md` then reads "not set". Setup never deletes the old folder.
