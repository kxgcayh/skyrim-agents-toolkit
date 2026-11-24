# Workspace rules for agents

This is the user's workspace, next to the Skyrim toolkit. Every new file you create for the user goes here. The
toolkit stays clean: it is a public project, and a file you leave in it can end up in a release.

## Read first, every session

1. `toolkit.env` in this folder: `SKYRIM_TOOLKIT_DIR` is the toolkit's folder.
2. In the toolkit: `AGENTS.md` (Codex and others) or `CLAUDE.md` (Claude Code), then `KNOWLEDGEBASE.md`, then
   `KNOWLEDGEBASE.local.md` if it exists. Its `## My preferences` section is the user's own instructions and
   outranks everything else.
3. `skyrim-paths.env` in the toolkit root: the game, config, load-order and mod-manager folders.

If `toolkit.env` is missing or points nowhere, say so and ask the user to re-run `setup.sh` in the toolkit. Do not guess.

## Where each kind of file goes

| What | Where |
|---|---|
| A third-party mod or tool you were handed | `mods/<Name>/` or `tools/<Name>/`: `upstream/` (archive, untouched), `extracted/`, `NOTES.md` |
| Something you build or patch | `mods/<Name>/` (own repo; `src/`, `build/`, `dist/`) |
| Audits, sorted lists, generated reports | `reports/` |
| Throwaway files, test output, a fake game folder for a test | `scratch/<task>/` |
| Notes you want to keep across sessions | `KNOWLEDGEBASE.local.md` in the toolkit (it is never shipped; read single sections with `python tools/kb-section.py <words>` from the toolkit root, never the whole file) |

## Rules

- `upstream/` is never modified. Extract each archive into its own new, empty folder and run scripts from outside it.
- Nothing is installed from here. A mod goes in through the user's mod manager, or `tools/mod-install.py` in the toolkit
  (dry run, read every destination, then `--apply`). Never write to the mod manager's live folders, the game folder or
  `My Games` from here.
- Never clone with `--recursive` (or run a submodule init). Use `./link-submodules.sh clone <url> <dest>` or `link <repo>`.
- Give a repo you create here no remote and push nothing unless the user says so for that case.
- Run toolkit tools by their path in the toolkit (`$SKYRIM_TOOLKIT_DIR/tools/...`), with the working folder here or in
  the item you work on. Do not copy toolkit files into the workspace.
- A nested repo's own `AGENTS.md` or `CLAUDE.md` adds to these rules and never replaces them.
- Delete only inside `scratch/` or a folder you made this session. Ask before deleting anything else.

Some agents read instructions only from the folder they were started in. Start the agent in this folder, or in the
item you work on, and tell it to read this file.
