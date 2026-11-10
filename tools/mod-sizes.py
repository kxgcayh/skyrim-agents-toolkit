#!/usr/bin/env python3
"""mod-sizes -- how big each Mod Organizer 2 mod is, largest first. Read-only.

The headless form of the MO2ModSizeAnalyzer plugin, whose scan rules it keeps: count regular files,
never follow a link or junction out of the mod, skip separators. The plugin needs MO2's `mobase`
and Qt, so it cannot run from a shell.

Usage:
    python tools/mod-sizes.py [search] [--enabled] [--top N] [--mods DIR] [--profile DIR]

search     case-insensitive; matches the mod's name OR a plugin file in its top folder, so
           "bsheartland" finds Beyond Skyrim - Bruma SE.
--enabled  only mods enabled in the profile's modlist.txt.
--top N    print the N largest matches. The rows not shown are always counted.
Folders come from $SKYRIM_MO2_MODS and $SKYRIM_LOADORDER_DIR, then skyrim-paths.env.
Exit: 0 printed · 2 bad usage, or no MO2 mods folder / modlist.txt.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skyguard import paths as sg_paths  # noqa: E402

TOOLKIT = Path(__file__).resolve().parent.parent
PLUGIN_EXTS = (".esp", ".esm", ".esl")


def configured(key: str) -> str | None:
    if os.environ.get(key):
        return os.environ[key]
    return sg_paths.read_install(str(TOOLKIT), os.environ).first(key)


def scan(root: str) -> tuple[int, int, int]:
    """(bytes, files, unreadable entries) under root, without leaving it through a link."""
    size = files = errors = 0
    pending = [root]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            size += entry.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        errors += 1
        except OSError:
            errors += 1
    return size, files, errors


def plugins_in(mod_dir: Path) -> list[str]:
    try:
        return [p.name for p in mod_dir.iterdir() if p.name.lower().endswith(PLUGIN_EXTS)]
    except OSError:
        return []


def enabled_mods(profile: Path) -> set[str]:
    with open(profile / "modlist.txt", encoding="utf-8", errors="replace") as f:
        return {line.strip()[1:] for line in f if line.startswith("+")}


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            return f"{value:,.0f} B" if unit == "B" else f"{value:,.2f} {unit}"
        value /= 1024
    return f"{value:,.2f} TiB"


def main() -> int:
    ap = argparse.ArgumentParser(description="MO2 mod sizes, largest first (read-only).")
    ap.add_argument("search", nargs="?", default="")
    ap.add_argument("--enabled", action="store_true")
    ap.add_argument("--top", type=int)
    ap.add_argument("--mods")
    ap.add_argument("--profile")
    args = ap.parse_args()
    if args.top is not None and args.top < 1:
        ap.error("--top must be 1 or more")

    mods = args.mods or configured("SKYRIM_MO2_MODS")
    profile = args.profile or configured("SKYRIM_LOADORDER_DIR")
    if not mods or not os.path.isdir(mods):
        print(f"ERROR: no MO2 mods folder (got {mods!r}); set SKYRIM_MO2_MODS or pass --mods.", file=sys.stderr)
        return 2
    if not profile:
        print("ERROR: no profile folder; set SKYRIM_LOADORDER_DIR or pass --profile.", file=sys.stderr)
        return 2
    try:
        enabled = enabled_mods(Path(profile))
    except OSError as e:
        print(f"ERROR: cannot read modlist.txt: {e}", file=sys.stderr)
        return 2

    needle = args.search.casefold()
    folders = [d for d in sorted(Path(mods).iterdir()) if d.is_dir() and not d.name.endswith("_separator")]
    rows = []
    for mod in folders:
        if args.enabled and mod.name not in enabled:
            continue
        plugins = plugins_in(mod)
        if needle and needle not in " ".join([mod.name, *plugins]).casefold():
            continue
        rows.append((*scan(str(mod)), mod.name, mod.name in enabled))
    rows.sort(key=lambda r: (-r[0], r[3].casefold()))

    shown = rows[: args.top] if args.top else rows
    print(f"{len(folders)} mods in {mods}; {len(rows)} match; {format_size(sum(r[0] for r in rows))} matched")
    for size, files, errors, name, is_on in shown:
        note = f"  [{errors} unreadable]" if errors else ""
        print(f"{format_size(size):>12} {files:>8,} files  {'on ' if is_on else 'off'}  {name}{note}")
    print(f"not shown: {len(rows) - len(shown)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
