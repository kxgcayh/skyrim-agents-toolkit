
---

## Codex specifics

Generated into `AGENTS.md` only; everything above is shared. Other agents: this section is not about you.

- **The guards run only after the user approves them.** Codex skips unapproved project hooks silently.
  When they run, your session context starts with `SKYGUARD: Codex hooks live`. **If that line is
  missing, the guards are NOT running:** tell the user to run `/hooks` in Codex, approve the Skyrim
  toolkit's hooks, and check with `bash tools/hook-canary.sh`. Approval is needed again after a
  toolkit update whose CHANGELOG says "re-approve your Codex hooks", and (inferred, not measured) after the
  install folder moves: the approval covers the definition as rendered, install path included.
- Start Codex in the game folder itself. Codex runs no hook started from a subfolder unless the install
  folder is a git repository; Steam installs are not. Verify the live banner and canary before relying on hooks.
- **Run the toolkit's scripts as `bash tools/<name>.sh`.** Do not assume your shell is bash: on Windows
  it may be PowerShell, so write commands that work there.
- **A refusal is final.** The guards cannot ask on Codex, so anything that needs the user's confirmation
  is refused with `NEEDS YOUR CONFIRMATION`. Stop and explain what you wanted to run and why; if the user
  agrees, they run it themselves in the Codex TUI with the `!` prefix. Never retry it in another form.
- **Checked:** every shell command and every `apply_patch`, including one run through the shell. Writing
  a plugin or archive (`.esp/.esm/.esl/.bsa/.ba2`) directly is refused; deleting in the game or config
  folders is refused; edits inside the game get advice. Files an `apply_patch` changes or deletes are
  backed up to `.claude/backups/` first, and `.psc`/`.pex` are snapshotted before shell commands.
  A file written by a script you run is not backed up.
- **DevBench MCP** (server name contains `devbench`): `smp reset` is refused. A save is not judged: the save
  vault keeps every version (`docs/save-vault.md`).
- **Not checked:** commands the user types with `!` in the Codex TUI (they bypass hooks), and other MCP
  tools (only logged).
- **Skills** are in `.agents/skills/<name>/SKILL.md`: read the relevant `SKILL.md` before writing code, compiling Papyrus, or editing assets when the task calls for a skill. Skill discovery and path matches only identify candidates. Follow the skill once read.
- **Communication.** Keep answers brief, direct, and technical. Explain a concrete CTD or save-corruption risk when it affects the approach. During longer tool sequences, give a one-sentence status every few calls. After tools finish, lead with the result and any salient verification or blocker. Respect the user's requested reply format. Acknowledge mistakes promptly and focus on the correction.
- **Edits.** Make short, straightforward edits in one pass. For a complex change, outline it, edit in sections, and verify as you go. Catch failures with tooling before live testing.
- `bash tools/hook-canary.sh` shows whether each hook ran, saw its input and finished, per surface.

- Missing tool workdir: Codex shell mutations need absolute paths (Windows: drive/UNC).
