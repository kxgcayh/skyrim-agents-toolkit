#!/usr/bin/env python3
"""modlist-move -- move mods between MO2 separators in a COPY of modlist.txt. Never writes the profile.

MO2's modlist.txt lists the highest priority first, and a separator line comes AFTER its members (its members are
the lines above it, up to the previous separator). "Above X" therefore means "higher priority than X".

Usage:
    python tools/modlist-move.py --out DIR [--plan plan.json] [--move "MOD=>ANCHOR"]... [--disabled-to SEP]
                                 [--label NAME] [--json] [--mods DIR] [--profile DIR]

--move "MOD=>ANCHOR"   put MOD directly above the mod ANCHOR (exact names, without the +/- prefix).
--plan plan.json       a list of moves: {"mod": M, "above": A} | {"mod": M, "top_of": SEP} | {"mod": M, "bottom_of": SEP}.
                       SEP is a substring of exactly one separator name. Moves sharing a target keep plan order
                       (the earlier one ends up higher).
--disabled-to SEP      move every disabled mod (not separators) outside SEP to the bottom of SEP, order kept.
--out DIR              where the result goes: DIR/modlist.<profile>.<label>.txt. Refused inside the MO2 instance.

Checks before writing (any failure writes nothing, exit 1): every moved mod and anchor matches exactly one line,
the result has the same lines (multiset) and line ending, and every line not moved keeps its relative order.
Then it reports loose-file conflicts the move creates: for each moved enabled mod, files it newly loses to or newly
wins over another enabled mod (meta.ini, .DS_Store, Thumbs.db and top-level docs ignored). Plugin load order is
LOOT's and does not change with mod priority. Finally it prints the apply command, with the backup named the way MO2
names its own (modlist.txt.YYYY_MM_DD_HH_MM_SS), to run with MO2 closed.

Folders come from $SKYRIM_MO2_MODS and $SKYRIM_LOADORDER_DIR, then skyrim-paths.env.
Exit: 0 written · 1 a check failed, nothing written · 2 bad usage or missing folders.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skyguard import paths as sg_paths  # noqa: E402

TOOLKIT = Path(__file__).resolve().parent.parent
SEP_SUFFIX = "_separator"
IGNORED_NAMES = {"meta.ini", ".ds_store", "thumbs.db", "desktop.ini"}
TOP_LEVEL_DOCS = (".txt", ".md", ".pdf", ".html", ".htm", ".rtf", ".png", ".jpg")


class Refused(Exception):
    """A check failed; nothing is written."""


def configured(key: str) -> str | None:
    if os.environ.get(key):
        return os.environ[key]
    return sg_paths.read_install(str(TOOLKIT), os.environ).first(key)


def is_sep(line: str) -> bool:
    return line.endswith(SEP_SUFFIX)


def is_mod(line: str) -> bool:
    return line[:1] in "+-" and not is_sep(line)


def name(line: str) -> str:
    return line[1:]


def read_modlist(path: Path) -> tuple[list[str], str, bool, str]:
    """(lines, eol, trailing newline, sha256 of the exact bytes parsed): one read, so the hash is of what was moved."""
    raw = path.read_bytes()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8").split(eol)
    trail = lines[-1] == ""
    return (lines[:-1] if trail else lines), eol, trail, hashlib.sha256(raw).hexdigest()


def one(lines: list[str], pred, what: str) -> int:
    hits = [i for i, l in enumerate(lines) if pred(l)]
    if len(hits) != 1:
        raise Refused(f"{what} matches {len(hits)} lines, need exactly 1")
    return hits[0]


def mod_index(lines: list[str], mod: str) -> int:
    return one(lines, lambda l: is_mod(l) and name(l) == mod, f"mod {mod!r}")


def sep_index(lines: list[str], sep: str) -> int:
    needle = sep.casefold()
    return one(lines, lambda l: is_sep(l) and needle in l.casefold(), f"separator {sep!r}")


def members_start(lines: list[str], s: int) -> int:
    """First line that belongs to the separator at s (after the previous separator or the header comments)."""
    i = s - 1
    while i >= 0 and not is_sep(lines[i]) and not lines[i].startswith("#"):
        i -= 1
    return i + 1


def parse_moves(args) -> list[dict]:
    moves: list[dict] = []
    if args.plan:
        data = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit("ERROR: --plan must hold a JSON list")
        for m in data:
            kinds = [k for k in ("above", "top_of", "bottom_of") if isinstance(m, dict) and k in m]
            if (not isinstance(m, dict) or len(kinds) != 1
                    or not all(isinstance(m.get(k), str) and m[k].strip() for k in ("mod", kinds[0]))):
                raise SystemExit(f"ERROR: plan entry needs a non-empty 'mod' and one of above/top_of/bottom_of: {m!r}")
            moves.append({"mod": m["mod"], "kind": kinds[0], "target": m[kinds[0]]})
    for spec in args.move or []:
        if "=>" not in spec:
            raise SystemExit(f"ERROR: --move needs MOD=>ANCHOR, got {spec!r}")
        mod, anchor = (s.strip() for s in spec.split("=>", 1))
        moves.append({"mod": mod, "kind": "above", "target": anchor})
    return moves


def apply_moves(lines: list[str], moves: list[dict], disabled_to: str | None) -> tuple[list[str], list[str]]:
    """The moved list and the lines moved, in move order. Raises Refused on any failed check."""
    moved_lines = []
    for m in moves:
        moved_lines.append(lines[mod_index(lines, m["mod"])])
        if m["kind"] == "above":
            mod_index(lines, m["target"])
        else:
            sep_index(lines, m["target"])
        if m["kind"] == "above" and m["target"] in {x["mod"] for x in moves}:
            raise Refused(f"anchor {m['target']!r} is itself moved; anchor on a mod that stays")
    if len(set(moved_lines)) != len(moved_lines):
        raise Refused("a mod is moved twice")

    disabled_lines: list[str] = []
    if disabled_to:
        s = sep_index(lines, disabled_to)
        inside = set(range(members_start(lines, s), s))
        explicit = set(moved_lines)
        disabled_lines = [l for i, l in enumerate(lines)
                          if l.startswith("-") and not is_sep(l) and i not in inside and l not in explicit]
        swept = {name(l) for l in disabled_lines}
        for m in moves:
            if m["kind"] == "above" and name(lines[mod_index(lines, m["target"])]) in swept:
                raise Refused(f"anchor {m['target']!r} is disabled, so --disabled-to {disabled_to!r} moves it first; "
                              "anchor on an enabled mod, or a mod already under that separator")

    gone = set(moved_lines) | set(disabled_lines)
    work = [l for l in lines if l not in gone]
    last: dict[tuple[str, str], str] = {}
    for m, line in zip(moves, moved_lines):
        # Group by the line the target resolves to, not its spelling: two spellings of one separator are one group.
        anchor = lines[mod_index(lines, m["target"])] if m["kind"] == "above" else lines[sep_index(lines, m["target"])]
        key = (m["kind"], anchor)
        if key in last:
            at = work.index(last[key]) + 1
        elif m["kind"] == "above":
            at = mod_index(work, m["target"])
        elif m["kind"] == "top_of":
            at = members_start(work, sep_index(work, m["target"]))
        else:
            at = sep_index(work, m["target"])
        work.insert(at, line)
        last[key] = line
    if disabled_lines:
        at = sep_index(work, disabled_to)
        work[at:at] = disabled_lines

    if collections.Counter(work) != collections.Counter(lines):
        raise Refused("the result does not hold the same lines")
    every = gone
    if [l for l in work if l not in every] != [l for l in lines if l not in every]:
        raise Refused("a line that was not moved changed its relative order")
    return work, moved_lines + disabled_lines


def mod_files(mods_dir: Path, mod: str) -> set[str]:
    root = mods_dir / mod
    out: set[str] = set()
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
        for f in files:
            low = f.lower()
            if low in IGNORED_NAMES:
                continue
            rel = os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/").lower()
            if "/" not in rel and (low.endswith(TOP_LEVEL_DOCS) or "." not in low):
                continue
            out.add(rel)
    return out


def conflicts(old: list[str], new: list[str], moved: list[str], mods_dir: Path) -> list[dict]:
    old_pos = {l: i for i, l in enumerate(old)}
    new_pos = {l: i for i, l in enumerate(new)}
    enabled = [l for l in new if l.startswith("+") and not is_sep(l)]
    cache: dict[str, set[str]] = {}

    def files(line):
        if line not in cache:
            cache[line] = mod_files(mods_dir, name(line))
        return cache[line]

    found = []
    for m in moved:
        if not m.startswith("+"):
            continue
        for other in enabled:
            if other == m:
                continue
            was_above = old_pos[other] < old_pos[m]
            is_above = new_pos[other] < new_pos[m]
            if was_above == is_above:
                continue
            common = files(m) & files(other)
            if common:
                found.append({"mod": name(m), "other": name(other), "moved_mod": "loses" if is_above else "wins",
                              "files": len(common), "sample": sorted(common)[:3]})
    return found


def separator_of(lines: list[str]) -> dict[str, str]:
    out, cur = {}, ""
    for l in reversed(lines):
        if is_sep(l):
            cur = name(l)[: -len(SEP_SUFFIX)].strip("_ ")
            cur = " ".join(cur.replace("_", " ").split())
        else:
            out[l] = cur
    return out


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Move mods between MO2 separators in a copy of modlist.txt.")
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan")
    ap.add_argument("--move", action="append")
    ap.add_argument("--disabled-to")
    ap.add_argument("--label", default="moved")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mods")
    ap.add_argument("--profile")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.label) or args.label.strip(".") == "":
        ap.error("--label takes letters, digits, '.', '_' and '-' only")
    moves = parse_moves(args)
    if not moves and not args.disabled_to:
        ap.error("nothing to do: give --plan, --move or --disabled-to")
    # Check the raw strings: Path("") is ".", which is a directory, so an unset setting would scan the cwd.
    mods_raw = (args.mods or configured("SKYRIM_MO2_MODS") or "").strip()
    profile_raw = (args.profile or configured("SKYRIM_LOADORDER_DIR") or "").strip()
    if not profile_raw:
        print("ERROR: no MO2 profile; set SKYRIM_LOADORDER_DIR or pass --profile.", file=sys.stderr)
        return 2
    mods, profile = Path(mods_raw), Path(profile_raw)
    if not mods_raw or not mods.is_dir():
        print(f"ERROR: no MO2 mods folder ({mods}); set SKYRIM_MO2_MODS or pass --mods.", file=sys.stderr)
        return 2
    modlist = profile / "modlist.txt"
    if not modlist.is_file():
        print(f"ERROR: no modlist.txt in {profile}; set SKYRIM_LOADORDER_DIR or pass --profile.", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    forbidden = [profile, mods]
    if profile.parent.name.lower() == "profiles":
        forbidden.append(profile.parent.parent)
    for root in forbidden:
        if inside(out_dir, root):
            print(f"ERROR: --out {out_dir} is inside {root}; write the copy outside the MO2 instance.", file=sys.stderr)
            return 2

    lines, eol, trail, digest = read_modlist(modlist)
    try:
        new, moved = apply_moves(lines, moves, args.disabled_to)
    except Refused as e:
        print(f"REFUSED: {e}. Nothing written.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    out = (out_dir / f"modlist.{profile.name}.{args.label}.txt").absolute()
    if out.is_symlink() or (out.exists() and not out.is_file()):
        print(f"ERROR: {out} is a link or not a regular file; refusing to write through it.", file=sys.stderr)
        return 2
    # Write beside it and rename: os.replace swaps the directory entry and never follows a link put there meanwhile.
    body = (eol.join(new) + (eol if trail else "")).encode("utf-8")
    tmp = out.with_name(out.name + f".{os.getpid()}.tmp")
    with open(tmp, "xb") as fh:
        fh.write(body)
    os.replace(tmp, out)
    proposal_digest = hashlib.sha256(body).hexdigest()

    seps = separator_of(new)
    pos = {l: i for i, l in enumerate(new)}
    placed = [{"mod": name(l), "enabled": l.startswith("+"), "separator": seps.get(l, ""), "line": pos[l] + 1}
              for l in moved]
    found = conflicts(lines, new, moved, mods)
    q = shlex.quote
    # Both files are checked: the live modlist is still the one moved, and the proposal is still the one reviewed
    # (a later run with the same label replaces the proposal file).
    check = ("import hashlib,sys; h=lambda f: hashlib.sha256(open(f,'rb').read()).hexdigest(); "
             f"sys.exit(h('modlist.txt') != '{digest}' or h(sys.argv[1]) != '{proposal_digest}')")
    apply = (f"cd {q(str(profile.absolute()))} && {{ {q(sys.executable)} -c {q(check)} {q(str(out))} "
             f"|| {{ echo 'modlist.txt or the proposal changed since this proposal was made; rerun modlist-move' >&2; false; }}; }} "
             # the backup is created only if its name is free: a second apply in the same second must not overwrite it
             f"&& b=\"modlist.txt.$(date +%Y_%m_%d_%H_%M_%S)\" "
             f"&& {{ ( set -C; cat modlist.txt > \"$b\" ) 2>/dev/null "
             f"|| {{ echo \"backup $b already exists; wait a second and rerun\" >&2; false; }}; }} "
             f"&& cp {q(str(out))} modlist.txt")

    if args.json:
        print(json.dumps({"out": str(out), "lines": len(new), "moved": placed, "conflicts": found,
                          "apply": apply}, indent=2))
        return 0
    print(f"wrote {out} ({len(new)} lines, {len(moved)} moved; same lines, unmoved order kept)")
    for p in placed:
        print(f"  {p['mod']}  ->  {p['separator']}  (line {p['line']}{'' if p['enabled'] else ', disabled'})")
    print(f"loose-file conflicts the move creates: {len(found)}")
    for c in found:
        print(f"  {c['mod']} now {c['moved_mod']} {c['files']} file(s) {'to' if c['moved_mod'] == 'loses' else 'over'} "
              f"{c['other']}: {', '.join(c['sample'])}")
    print("apply with MO2 closed:")
    print(f"  {apply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
