#!/usr/bin/env bash
# Share git submodules through tools/: one clone per upstream in tools/<name>, and each submodule
# path becomes a detached `git worktree` of that clone at the pinned commit. Objects are stored once;
# the parent repo's `git status` stays clean (a symlink at a submodule path breaks git, a worktree does not).
#
#   link-submodules.sh link  <repo>          link every uninitialised submodule of <repo>, recursively
#   link-submodules.sh clone <url> [<dest>]  git clone without submodules, then link
#
# An already-initialised classic submodule is left alone; the script prints the commands to migrate it.
# After moving a mod folder, run `git -C tools/<name> worktree repair <new path>`.
set -euo pipefail

WS="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$WS/tools"

norm_url() { # https/ssh/.git/case-insensitive identity of a GitHub-style URL
  printf '%s' "$1" | sed -E 's#^(git@|ssh://git@)([^:/]+)[:/]#https://\2/#; s#\.git/?$##; s#/$##' | tr 'A-Z' 'a-z'
}

shared_clone() { # url -> path of tools/ clone for that exact upstream (cloned if missing)
  local url="$1" name owner dir
  name="$(basename "$url" .git)"  # keep upstream's case for the folder name
  owner="$(basename "$(dirname "$(norm_url "$url")")")"
  for dir in "$TOOLS/$name" "$TOOLS/$name-$owner"; do
    if [ -d "$dir/.git" ]; then
      [ "$(norm_url "$(git -C "$dir" remote get-url origin)")" = "$(norm_url "$url")" ] && { echo "$dir"; return; }
    elif [ ! -e "$dir" ]; then
      echo "  clone $url -> $dir" >&2
      git clone -q "$url" "$dir" >&2
      echo "$dir"; return
    fi
  done
  echo "ERROR: $TOOLS/$name and $TOOLS/$name-$owner both exist and neither has origin $url" >&2
  return 1
}

link_repo() {
  local repo; repo="$(cd "$1" && pwd)"
  [ -f "$repo/.gitmodules" ] || return 0
  echo "== $repo"
  git -C "$repo" config -f .gitmodules --get-regexp '^submodule\..*\.path$' | while read -r key path; do
    local name="${key#submodule.}"; name="${name%.path}"
    local url sha target clone
    url="$(git -C "$repo" config -f .gitmodules "submodule.$name.url")"
    sha="$(git -C "$repo" ls-tree HEAD -- "$path" | awk '$2=="commit"{print $3}')"
    target="$repo/$path"
    if [ -z "$sha" ]; then
      echo "  SKIP $path: listed in .gitmodules but no gitlink in HEAD (nothing pinned)"; continue
    fi
    case "$url" in ./*|../*) url="$(cd "$repo" && git config --get remote.origin.url | sed 's#/*$##')/$url";; esac
    if [ -e "$target/.git" ]; then
      if git -C "$target" rev-parse --path-format=absolute --git-common-dir 2>/dev/null | grep -q "^$TOOLS/[^/]*/\.git$"; then
        echo "  ok   $path (already a tools/ worktree)"
      else
        echo "  KEEP $path: classic submodule checkout. To migrate (check 'git -C \"$target\" status' first):"
        echo "       git -C \"$repo\" submodule deinit -f -- \"$path\" && rm -rf \"$repo/.git/modules/$path\" && $0 link \"$repo\""
      fi
      continue
    fi
    [ -z "$(ls -A "$target" 2>/dev/null)" ] || { echo "  SKIP $path: not empty and not a git checkout"; continue; }
    clone="$(shared_clone "$url")"
    git -C "$clone" cat-file -e "$sha^{commit}" 2>/dev/null \
      || git -C "$clone" fetch -q origin "$sha" 2>/dev/null \
      || git -C "$clone" fetch -q origin '+refs/heads/*:refs/remotes/origin/*' --tags
    rmdir "$target" 2>/dev/null || true
    git -C "$clone" worktree add -q --detach "$target" "$sha"
    echo "  link $path -> $(basename "$clone") @ $(git -C "$clone" describe --tags --always "$sha")"
    link_repo "$target"
  done
}

case "${1:-}" in
  link)  link_repo "${2:?repo path}";;
  clone) dest="${3:-$(basename "${2:?url}" .git)}"; git clone -q "$2" "$dest"; link_repo "$dest";;
  *) sed -n '2,10p' "$0"; exit 2;;
esac
