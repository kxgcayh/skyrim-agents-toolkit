#!/bin/bash
# UserPromptSubmit / PreToolUse: show the agent the toolkit guidance section that matches what it is about to do
# (tools/doc_lookup.py; index in agent/doc-index.json and the `## Doc index` block of KNOWLEDGEBASE.local.md).
# Usage in a hook: bash tools/doc-inject.sh <claude|codex>   (hook JSON on stdin, hook JSON or nothing on stdout)
#
# NOT a guard, like tools/session-charter.sh: it decides nothing, only adds context, so it has no heartbeat, no
# fallback chain and no fail-closed path. Any failure prints nothing and exits 0. Kept outside skyguard so it does
# not add the guard engine's per-call cost. The interpreter is setup.sh's, read as data from skyrim-paths.env.
AGENT="${1:-claude}"
case "$AGENT" in claude|codex) ;; *) AGENT=claude ;; esac
IFS= read -r -d '' INPUT
[ -n "$INPUT" ] || exit 0

_SELF="${BASH_SOURCE[0]//\\//}"
case "$_SELF" in */*) TOOLS_DIR="${_SELF%/*}" ;; *) TOOLS_DIR="." ;; esac
_CWD="$PWD"
ROOT=""
CDPATH= cd -- "$TOOLS_DIR/.." >/dev/null 2>&1 && ROOT="$PWD"
CDPATH= cd -- "$_CWD" >/dev/null 2>&1
[ -n "$ROOT" ] || exit 0

PY=""
for _PATHS in "$ROOT/.claude/skyrim-paths.env" "$ROOT/skyrim-paths.env"; do     # the 3.x location first, so the root file wins
    [ -r "$_PATHS" ] || continue
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        case "$line" in SKYGUARD_PYTHON=*) PY="${line#SKYGUARD_PYTHON=}" ;; esac
    done < "$_PATHS"
done
case "$PY" in \'*\') PY="${PY:1:${#PY}-2}"; PY="${PY//\'\\\'\'/\'}" ;; esac
[ -n "$PY" ] || exit 0

# A native Windows Python needs the Windows spelling of the install (same conversion as the guard wrappers).
WS="$ROOT"
_MSYS=""
case "$OSTYPE" in msys*) _MSYS=1 ;; cygwin*) [ -e /usr/bin/msys-2.0.dll ] && _MSYS=1 ;; esac
case "$_MSYS:$ROOT" in
    1:/[a-zA-Z]/*) WS="${ROOT:1:1}"; WS="${WS^}:${ROOT:2}" ;;
    1:/[a-zA-Z])   WS="${ROOT:1:1}"; WS="${WS^}:/" ;;
    1:/*)          WS="$(CDPATH= cd -- "$ROOT" 2>/dev/null && pwd -W 2>/dev/null)" ;;
esac
[ -n "$WS" ] || exit 0

# Pass the output on only when the resolver finished cleanly: never half a JSON document.
OUT="$("$PY" -B "$WS/tools/doc_lookup.py" --hook "$AGENT" 2>/dev/null <<<"$INPUT")" || exit 0
[ -n "$OUT" ] && printf '%s\n' "$OUT"
exit 0
