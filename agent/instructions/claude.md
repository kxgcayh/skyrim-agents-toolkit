
---

## Claude Code specifics

Generated into `CLAUDE.md` only. Everything above is shared with every agent.

- **Mandatory skills workflow**: Skills live in `.claude/skills/<name>/SKILL.md` (invoke via
  `Skill: <name>`). Reading the relevant `SKILL.md` is a required first step before writing code, compiling Papyrus,
  or editing assets — skills hold CLI recipes and engine quirks absent from base training.
- **Tone, directness & conciseness**: Dense, brief, technical answers without disingenuous modifiers
  ("genuinely", "honestly", "straightforward"). Push back constructively when an approach risks CTD or save
  corruption. During multi-tool chains, give a 1-sentence status every few calls.
- **Reply after tool calls**: State the answer directly in 1-2 sentences. A bare "Done." is not a reply;
  never repeat what was already stated before a tool call.
- **Mistake handling**: Own mistakes promptly and focus on the fix: steady, honest helpfulness without
  self-abasement, excessive apology, or defensive surrender.
- **File strategy**: Short edits (<100 lines) in one pass; complex changes (>100 lines) built
  iteratively (outline, section by section, verify). Catch errors in tooling before live testing.
- **The guards** are `.claude/hooks/*.sh`, thin adapters over `tools/skyguard/`, wired up in
  `.claude/settings.json`: `Bash`, `PowerShell`, `Monitor` → `protect-bash` + `snapshot-before-tool`; `Edit`, `Write`,
  `NotebookEdit` → `protect-files` + `backup-before-edit`; the DevBench MCP tools → `protect-mcp`; SessionStart → `session-kb-guard` (knowledgebase snapshot, then your `## My preferences`). `setup.sh` records the
  Python path in each hook. The user lists or disables them with `/hooks`. Only the Bash tool gets
  `SKYGUARD_SESSION_ID`, so lift the lock from Bash, never PowerShell.
- **What the backup hook cannot see.** `backup-before-edit.sh` fires on Edit/Write/NotebookEdit tool calls, with no
  extension filter (`.psc` included). A file written by a script run through the Bash tool is invisible to
  it. That is how the knowledgebase is usually written, and it is why `session-kb-guard.sh` snapshots the
  knowledgebase files at SessionStart. `snapshot-before-tool.sh` copies `.psc`/`.pex` from both Papyrus
  source layouts and the compiled-scripts folder, regardless of age, before each non-read-only shell command.
- **Why `hook-canary.sh` matters here.** Claude Code spawns a hook with a Win32 pipe on stdin, on which
  `cat /dev/stdin` returns zero bytes. Every hook here was inert that way for months while its suite
  passed. The canary reads heartbeats written from inside real invocations.
- **A refused command the user really wants**: they can run it themselves with the `!` prefix.
