# Knowledgebase: Environment, DevBench and guards

Part of the Skyrim modding knowledgebase; index: `KNOWLEDGEBASE.md`. Covers mod manager layout, paths, DevBench, hooks and guard behaviour.

## Hook Candidates

A living list of potential safety hooks identified during work. Evaluated but not necessarily implemented.

| Candidate | Trigger | What it would do | Priority | Status |
|-----------|---------|------------------|----------|--------|
| *None yet* | — | — | — | — |

**When to add entries:** After any near-miss, unexpected outcome, or pattern of risk that current hooks don't cover. Include why the gap was noticed and whether the overhead is justified.

---

## DevBench — Live In-Game Testing (hazards + confirmed patterns)

DevBench (alandtse, Nexus SE 181326) exposes the **running** game over a localhost REST/MCP server.
Everything below was learned during live sessions on a heavy (700+ plugin) VR load order. Read this
before your first live session — several of these cost a force-killed game to discover.

### Versions and what changed in 1.16-1.24 (read from the changelog/README, 2026-10-05; not run live)
- Latest seen: **1.24.0** (2026-10-04). Toolkit floor stays **1.11.0** (`alive`; off-thread since 1.12.0).
  No removals or renames in 1.16-1.24: ports, `POST /api/tool/<tool>`, `/api/health` fields, `/api/tools`,
  console exec/capture/read and the 400/504 meanings are all unchanged.
- **Update the VR Address Library first.** DevBench 1.19+ is built on CommonLibSSE-NG 8.3.0. Newest VR
  Address Library seen: **0.276.1** (2026-10-04).
- New: `game loadLast` / `advanceTime` (1.17) / `setTimeScale` / `getTimeScale` (1.22, 0.1..3.0, leased, 409
  while recording); `wait` and `sleep` (1.16); `input` (1.18-1.24, synthetic keyboard/VR tracked-pose, mutating);
  `camera orbit` (third person only, 501 on VR); `inspect kind=extensions`; `menu invoke`; `devbench-bridge`
  stdio exe. `inspect state` also returns `pid`, `port`, `exe`.
- **`scenario` fails on an inner tool error since 1.16 (#72)**; it used to report success.
- Console capture: 1.19 fixed empty-buffer capture (#96), 1.24 "capture console output" (#117), and 1.24
  warns on unknown request keys (#116). The old "count:0 is normal" is partly a pre-1.19 artefact.
- **CrashLogger:** 1.24.0 added `__fastfail` crash dumps (a crash class older loggers never wrote).
  `tools/crash-triage.py` already matches `crash-*.txt`/`.log` case-insensitively; no real `__fastfail`
  dump has been run through it yet -- when one exists, confirm the unparsed counter stays 0.

### The server is not the game (liveness ≠ ping)
- The HTTP server runs on a **separate thread from the game**. A deadlocked, hung, or paused game
  still answers `ping` with `{"ok":true}`. **`ping` is not proof the game is alive.**
- Worse, you cannot diagnose a hang with an ordinary tool call: every tool (`inspect`, `console`,
  `papyrus`, …) is dispatched onto the **main thread** and throws **504 after 5 s** if that thread is
  stuck. The probe fails in exactly the case it exists to detect.
- **Use `GET /api/health`** (DevBench **1.11.0+**; answered off the main thread since **1.12.0**, and
  `inspect kind=health` is the MCP-reachable twin). It is the only endpoint that keeps replying
  through a stall, and returns liveness *and* identity in one shot:
  `{ ok, lastLifecycle, frame, lastTaskFrame, pendingTasks, pid, port, exe, vr }`.
- Read it as **four** states, not two — `tools/devbench-cli.sh alive` samples it twice and does this:

  | Signal | State | Exit |
  |---|---|---|
  | `frame` advancing | running | 0 |
  | `frame` frozen, `pendingTasks` 0 | **paused / console open / loading — NOT a hang** | 2 |
  | `frame` frozen, `pendingTasks` > 0, `lastTaskFrame` frozen | main-thread queue starved = **hung** | 2 |
  | `frame` < 0 | server up, no save loaded (main menu) | 3 |

  A frozen frame **alone is not proof of a hang** — the old two-read frame diff cried wolf every time
  the user opened a menu. The task queue is the discriminator.
- `pid`/`port`/`exe`/`vr` identify **which instance answered**. If you ever run two Skyrims (SE on
  8920, VR on 8921), a client pinned to the wrong port silently returns real-looking results from the
  wrong game; this catches it in one call.
- Status codes are meaningful — don't treat any JSON body as success: **504** = main thread busy or
  stuck (server fine), **400** = bad argument type (since 1.11.0; it used to be a 500), **connection
  refused** = game closed. Collapsing these into "it failed" sends you debugging the wrong layer.

### ⚠ `game save` can deadlock the game (observed on v1.8.2)
- Driving `game {action:"save"}` mid-session hung the game's main thread: a 0-byte `<name>.ess.tmp`
  that never finalized, `inspect` timing out, frame counter stopped. Recovery was a force-kill of the
  game process. `ping` kept answering the whole time.
- **To reload a script for testing, have the USER do an in-game load (F9 / load menu)** — that path
  never hung; only DevBench's own save did.
- DevBench 1.9.1 changed this area ("console: reroute save/load to game tool path") and mutating
  `game` actions are documented as fire-and-forget with `lifecycle` events for completion. Whether
  the deadlock persists on current versions is **untested here** (1.22.0's changelog says named saves are
  now queued through SKSE, #104 -- reported fixed in 1.22 per the changelog, unverified) — treat `game save` as suspect and
  prefer the user-driven load until you have verified otherwise on your version.
- If you do try it on a newer build, watch it with `alive` / `GET /api/health` (see above) rather than
  `inspect` — a tool call is dispatched onto the very main thread the deadlock freezes, so it 504s
  and tells you nothing, while `health` keeps answering and shows `pendingTasks` piling up.

### Paused-game semantics (in a menu)
- **READ tools work while paused** — `inspect state/vm/scene/player/effects/refs` are fine, which
  makes pause useful for a leisurely inspection.
- **WRITE/act tools do NOT process while paused.** `console exec` only *queues* (commands run on the
  game thread, landing a frame later); Papyrus `OnUpdate` does not fire. Do not mistake a paused game
  for a logic failure.
- Shader-state probes report **false negatives while paused** (playback is frozen), so a
  "shader not playing" reading taken in a menu is meaningless. Check unpaused.

### Don't wreck the live session you're testing in
- **Heavy/global console commands can CTD a big load order.** A full `smp reset` reliably crashed a
  700+ plugin VR load order — reproduced by typing it manually, so this is the command's cost, not
  DevBench's fault. Keep live commands lightweight and targeted; get the user's OK and a save before
  any state change.
- **Don't poke the player's real ongoing activity to "test".** Firing state-mutating commands at live
  systems pollutes engine state (e.g. the music instance stack, producing phantom double-tracks).
  **Spawn dedicated test actors and act on those** (`player.placeatme <hostileBase> N`), and observe
  the player's natural activity rather than perturbing it.
- Many commands produce **no console output at all** (`addmusic`/`removemusic`, etc.). `count:0` from
  a capture can be genuine (on DevBench < 1.19 it was also what an empty capture buffer returned; fixed in
  1.19, reworked in 1.24) — judge the result by re-reading state, not by captured lines.

### Papyrus `call` gotchas
- Globals/native functions: **omit `self`**. Member functions: pass it —
  `{"form":"0x14"}` (or an EditorID), or `"selected"` for the console/crosshair ref (set via `prid`).
- Unlike console `cgf`, **the return value comes back** (`{called, returned, returnedType}`) — this is
  what makes read-modify-read loops possible without a play-session round trip.
- **Omitted trailing optional params are padded with neutral defaults** (`None`/`0`/`0.0`/`false`/`""`).
  For reference ops (`MoveTo`, `Disable`, `Kill`) a short arg list therefore **silently no-ops** —
  pass every optional whose real default isn't neutral (e.g. `StringUtil.Substring`'s `-1`).
- Array returns may not serialize (an array-returning function can come back as `none`) — probe with a
  scalar-returning function instead of concluding the state is absent.

### Protocol for tests the user must physically observe (VR)
- **Narrate on the HUD.** The user cannot see chat while in the headset. Drive every instruction and
  countdown through `Debug.Notification` (`devbench-cli.sh notify "..."`) so the sequence explains
  itself in-game, and only ask them to remove the headset when the HUD says it's done.
- **Burst, never single-shot.** A one-off effect is a "shooting star" the user will miss. Fire
  10–15 times over ~10s so one burst is one unmissable observation.
- **Prefer explicit player facing/angles over weapon-node geometry** when the test doesn't need the
  weapon — it removes pose dependency.
- Log results to a file and read them yourself. Don't rely on the user's eyes, and don't rely on
  console capture where a Papyrus channel or an on-disk log will do.

---

## Mod Manager Layout — MO2's Virtual Filesystem (read this before trusting any path)

**Mod Organizer 2 has no real merged `Data/` folder.** It builds a *virtual* one at launch by
overlaying, in priority order: the stock game's `Data/`, then each enabled mod's own folder, then
`overwrite/` (highest). That virtual view exists **only while MO2 is running a program through it**.

Vortex and manual installs are the opposite — they deploy mod files directly into the game's `Data/`,
so `Data/` really is the merged view. Everything else in this knowledgebase assumes that layout.

**What this changes for MO2 users:**

| Thing | Stock / Vortex | MO2 |
|---|---|---|
| A mod's actual files | `Data/...` | `<instance>/mods/<mod-name>/...` |
| INIs | `Documents/My Games/<game>/` | `<instance>/profiles/<profile>/` (when profile-specific INIs are on — a per-profile toggle) |
| `loadorder.txt` / `plugins.txt` | `%LOCALAPPDATA%/<game>/` | `<instance>/profiles/<profile>/` |
| Files a tool writes into `Data/` at runtime | land in `Data/` | land in `<instance>/overwrite/` |

**Finding the instance:** global instances live in `%LOCALAPPDATA%/ModOrganizer/<InstanceName>/`;
a portable instance keeps everything in MO2's own install folder. Either way the settings are in
`ModOrganizer.ini` — `[General]` holds `gamePath`, `gameName`, `selected_profile`; `[Settings]` holds
the optional `base_directory`, `mod_directory`, `profiles_directory`, `overwrite_directory` overrides,
which may contain the literal token `%BASE_DIR%`. Values are QSettings-escaped (backslashes doubled).
Match an instance to a game folder by comparing its `gamePath`. `setup.sh` does all of this
automatically and writes the correct paths into CLAUDE.md.

### The silent-wrong-answer trap: load-order tooling outside MO2

**xelib/XEditLib resolves plugins from the game path.** Launched *outside* MO2, it sees only the
plugins physically present in the stock `Data/` — which on an MO2 setup is the base game and little
else. It does not error. It returns a **wrong but entirely plausible** answer for anything involving
the override chain, conflict resolution, or the full load order.

- **Needs the MO2 VFS** (run the script through MO2's executables list): override-chain resolution,
  "what wins this conflict", anything reading the full load order, load-order-dependent edits.
- **Works fine outside MO2**: reading or editing a single plugin by path (Spriggit serialize /
  deserialize), because those never consult the load order at all. This is the main reason to prefer
  Spriggit for single-plugin work on an MO2 install.

The same logic applies to any tool that resolves the game path from the registry rather than from an
explicit file path.

### Never bare-copy a mod into `Data/` on a managed install

A dev tool and a mod are different things, and the line matters here. Dev tools (Spriggit, xelib,
Champollion, ReSaver, …) live outside the game and can be installed freely. **A mod — anything that
ends up under `Data/`, including SKSE plugin DLLs — belongs to the mod manager**, and copying files
in by hand is the wrong move on any Vortex or MO2 install:

- **Vortex** tracks deployed files; a hand-placed file is untracked, and a later deploy or purge can
  clobber or orphan it.
- **MO2** builds `Data/` virtually at launch. A file written to the real `Data/` isn't part of any
  mod, doesn't appear in the conflict view, and won't behave like the rest of the load order.
- Either way it's invisible to the user's own record of what's installed — which is exactly the state
  that makes a broken install impossible to debug later.

So: install it through the mod manager, or tell the user to. "It's just one DLL" is how an install
becomes unreproducible.

When the user installs by hand anyway, use `tools/mod-install.py`, never a bare copy: its dry run
shows every destination (anything outside `Data/` flagged), and `--apply` backs up what it replaces
and writes a SHA-256 manifest, which is the record a bare copy lacks. Under MO2 it installs a new mod
folder in MO2's `mods/` (enable it in MO2) instead of writing to the real `Data/`. Read the
destinations before `--apply`, and check the result after it (skill `triage-and-conflicts`).

---

## Windows paths in `sed` replacement text get eaten

Feeding a backslash-separated Windows path straight into `sed`'s *replacement*
half silently destroys it. GNU sed reads backslash sequences there as escapes:
`\U` switches on upper-casing, `\L` on lower-casing, `\t` becomes a literal tab,
and every other backslash is simply dropped. Measured on this toolkit's own
`setup.sh`:

```
supplied  C:\Users\testuser\AppData\Local\Microsoft\WinGet\Links\jq.exe
produced  C:SERS<TAB>ESTUSERAPPDATAocalmicrosoftwingetinksjq.exe
```

There is no error and no non-zero exit -- the substitution "succeeds" and writes
garbage. When the value is a path to a tool, whatever consumes it fails open.

**Rule: normalize before substituting.** `path=$(printf '%s' "$path" | tr '\134' '/')`
Skyrim tooling accepts forward slashes everywhere, so this costs nothing.

**Normalize at the point where the branches converge, not at each assignment.**
This toolkit shipped the bug twice for that reason: the v3.2.1 fix normalized
two variables and missed a third, and that third had *three* assignment sites
(a `which` result, a known-locations loop, and a post-install re-detect), so a
fix attached to any one of them would still have missed the others.

The same trap exists in Python -- `"C:\Users\..."` in a non-raw string is a
`\UXXXXXXXX` escape error, and `\t` in a double-quoted string is a tab. Use raw
strings, or build the separator with `chr(92)`.

---

## More than one `plugins.txt` (and more than one `My Games` folder) — the wrong one reads perfectly

A machine that has ever had more than one Skyrim installed carries several copies of the same
per-game state, and **nothing errors when the wrong one is read**:

- `%LOCALAPPDATA%\Skyrim VR\plugins.txt`, `...\Skyrim Special Edition\plugins.txt`,
  `...\Skyrim\plugins.txt` — the active load order.
- `Documents\My Games\Skyrim VR\`, `...\Skyrim Special Edition\`, `...\Skyrim\` — INIs,
  `Logs\Script\Papyrus.*.log`, and the `SKSE\` folder with the crash dumps.

Measured on the dev machine (a VR-only install): the **SSE** `plugins.txt` exists, holds 659
plugins, and is **18 days stale**. It disagrees with the VR file about which plugins are
active. A stale-but-valid file does not fail a loader — it produces a complete, plausible,
**wrong** load order, and every conflict answer computed from it is confidently wrong.

Note this contradicts the older advice that the SSE `plugins.txt` "does not exist on a VR
install". It may well exist. Don't assume its absence.

**Rule: pick deliberately, report the rivals, and offer an override.** The bundled tools probe
`Skyrim VR → Skyrim Special Edition → Skyrim`, print every candidate they ignored to stderr,
and honour `$PLUGINS_TXT`, `$PAPYRUS_LOG_DIR`, `$SKSE_CRASH_DIR`. Silently picking the first
hit is the same class of bug as reading the wrong half of the crash logs (above): a confident
answer about an install you are not modding.

---

## `paths:` in SKILL.md gates LISTING, not loading

MEASURED 2026-09-09. Reading a `.psc` under `Data/` produced *"The following skills are available
for use with the Skill tool: skyrim-context"* — the skill became **invocable**; its body did **not**
enter context. A description that says "Auto-loads when working with X" is describing an intention,
not the mechanism.

**Consequence for any `CLAUDE.md` → skill migration:** the root file must keep an explicit *invoke*
pointer. Without one, a future session sees no mention of the knowledge and concludes it does not
exist — the migration silently deletes the guidance instead of deferring it. Never migrate a
"never do X" rule this way at all.

---

## A guard at the wrong depth resolves a wrong root and silently allows

MEASURED 2026-09-09, same file, two locations, same payload. `protect-bash.sh` derives its install
root from its own location (`$(dirname "$_SELF")/../..`). Run from its real location it correctly
DENIES an `rm -rf` of the game install. A **byte-identical copy** run from a temp directory returns
**zero bytes** — and zero bytes is read as ALLOW.

The documented invariant is *"no root resolvable → DENY"*. It does not cover **root resolvable but
wrong**, which is the more dangerous case because nothing errors. `hook-canary.sh` reports such a
hook ALIVE, correctly: it *is* running and it *is* receiving its payload.

This matters here because users extract the bundle themselves, and a wrong depth is silent. Not yet
fixed: the obvious check ("deny unless the root looks like a Skyrim install") would break this
repository, which ships these hooks and is not a game install.

---

## Hook timeout economics — measure before optimising the guard

MEASURED 2026-09-09 with zero-fork in-hook markers (`EPOCHREALTIME` + `printf`, both bash builtins,
so the instrument does not perturb what it measures):

| hook | stdin read | body median | body max |
|---|---|---|---|
| `protect-bash.sh` | 13.0 ms | 372.9 ms | 465.2 ms |
| `snapshot-before-tool.sh` | 13.1 ms | 531.5 ms | 557.2 ms |
| `protect-files.sh` | 14.1 ms | 209.1 ms | 215.9 ms |
| `backup-before-edit.sh` | 13.8 ms | 113.7 ms | 123.0 ms |

Two conclusions. **The `INPUT=$(cat)` stdin read is ~3% of the cost** — bounding it saves nothing on
the normal path. And **fork reduction cannot be justified against a 60s budget**: the whole of
`protect-bash` is 375 ms.

⚠ **The observed timeouts do not live on this distribution.** Successful runs cap at ~8.2 s across
250 transcripts while every timeout is ≥10 s, with nothing in between. Either the process is not
starting at all (see [claude-code#77078](https://github.com/anthropics/claude-code/issues/77078) —
hook processes left suspended, `UserProcessorTime = 00:00:00`, OPEN with no known root cause), or
`durationMs` is measured differently for a cancellation than for a success. **That question is
unresolved** — do not treat the fork count as the explanation.

---

## KNOWN, NOT FIXED: verify-release.sh's hook floor is never actually derived

Found by the v3.9.1 release review, 2026-09-09. **Deferred deliberately — fix this before
`verify-release.sh` certifies another release.**

`tools/verify-release.sh:73-74` reads the floor from
`"$ROOT/../.github/workflows/release.yml"`. But `ROOT="$WORK/skyrimvr-claude-toolkit-$VER"`
where `WORK=$(mktemp -d)` holds only the zip and the extracted tree — and **`.github` is
excluded from the release payload**, so that path never exists. `sed` fails, `floor` comes back
empty, and `case "$floor" in ''|*[!0-9]*) floor=5 ;;` substitutes the hardcoded 5.

So the check passes for the wrong reason. Two claims in the file are false as written:

- the inline comment: *"The FLOOR is derived from the workflow that built this zip, not retyped
  here"* — it is retyped, in the fallback.
- the header: *"the hook floor and the gate list are read from the working tree"* —
  `$ROOT/../` is the temp directory, not the working tree.

⚠ **It is invisible because the fallback is currently CORRECT.** `release.yml` asserts `-ge 5`
and the fallback says 5, so the assertion agrees with reality today and will keep agreeing until
someone adds a sixth hook — at which point the tool reports a stale floor with a comment
insisting it cannot be stale. That is the exact defect this line was written to repair: a
hardcoded `-ge 4` that was one release stale the moment it shipped.

**Fix shape:** derive from the checkout, not from the extracted payload — the working tree is
where `.github` actually lives, and the header already says that is the intent. Then prove it by
mutation: change `release.yml`'s floor and require the named check to go red. A derivation that
cannot be shown to follow its source is a hardcoded value with extra steps.
