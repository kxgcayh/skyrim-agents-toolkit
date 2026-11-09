#!/bin/bash
# Copy the toolkit's gitignored, machine-only files somewhere that survives losing this drive.
#   bash tools/backup-local.sh [DEST]      (default: $SKYRIM_LOCAL_BACKUP, else ~/.skyrim-toolkit-local)
# Restore after a fresh clone: copy them back into the toolkit root, then run bash setup.sh.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-${SKYRIM_LOCAL_BACKUP:-$HOME/.skyrim-toolkit-local}}"
mkdir -p "$DEST/tools"
chmod 700 "$DEST"
n=0
for f in KNOWLEDGEBASE.local.md setup.local.env tools/.nexus_api_key .claude/settings.local.json; do
    [ -f "$ROOT/$f" ] || continue
    mkdir -p "$DEST/$(dirname "$f")"
    cp -p "$ROOT/$f" "$DEST/$f"
    n=$((n + 1))
done
[ ! -f "$DEST/tools/.nexus_api_key" ] || chmod 600 "$DEST/tools/.nexus_api_key"
echo "Backed up $n file(s) to $DEST"
