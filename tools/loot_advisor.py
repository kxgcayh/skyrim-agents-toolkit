#!/usr/bin/env python3
"""loot-advisor -- what LOOT would say about the active load order, without changing it. A read-only tool for the agent.

It loads the active plugins exactly as the game will (plugins.txt, the same file the guard and xelib tools resolve;
the enabled Mod Organizer 2 mod folders and overwrite when the install uses MO2), and asks libloot -- the library LOOT
itself is built on -- for:
  order    the order LOOT would sort them into, and which plugins that moves (the fewest that change position)
  issues   LOOT's masterlist messages for these plugins: warnings and errors, dirty plugins (ITMs, deleted references
           and navmeshes, with the cleaner LOOT names), requirements that are missing, incompatibilities that are both
           active, and the masterlist's general messages
The masterlist and its prelude are fetched from LOOT's GitHub repositories at run time, the newest branch this libloot
reads; the report names the branch and commit it used. When the fetch fails the last fetched copy is used and the
report says so. With --userlist, the rules in LOOT's own userlist.yaml (load-after, group and message metadata you set
in LOOT's app) are applied on top, as LOOT's app does; without it they are not, and the report says which.
This tool never writes the live load order or calls libloot's set_load_order. With --propose it writes proposed
plugins.txt and loadorder.txt outside the profile; LOOT's own files remain read-only. Wrye Bash / the mod manager stays the authority on order; on a save you
are keeping, read KNOWLEDGEBASE.local.md `## My preferences` before reordering anything.

Usage:  python tools/loot_advisor.py [--plugins-txt PATH] [--data DIR] [--json] [--offline] [--userlist PATH]
        python tools/loot_advisor.py --from-app [DIR] [--propose [DIR]]
Exit:   0 no moves and nothing but notes · 1 moves or findings (listed) · 2 could not check (named), never "clean"
        Proposal mode (SE/AE only): 0 byte-identical to profile · 1 proposal to review · 2 could not sort
        --plugins-txt must name a file called plugins.txt (libloot reads that name in the folder it is given)
"""
from __future__ import annotations

import argparse
import bisect
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

import skyrim_paths                                              # noqa: E402
from skyguard import paths as sg_paths                           # noqa: E402
from libloot import libloot_loader                               # noqa: E402

REPOS = {"SkyrimVR": "skyrimvr", "SkyrimSE": "skyrimse"}
API = "https://api.github.com/repos/loot/{repo}/branches?per_page=100"
RAW = "https://raw.githubusercontent.com/loot/{repo}/{commit}/{file}"
CACHE = skyrim_paths.TOOLKIT_ROOT / ".skyguard" / "loot" / "masterlists"
UA = {"User-Agent": "skyrim-toolkit-loot-advisor", "Accept": "application/vnd.github+json"}
MAX_DOWNLOAD = 32 * 1024 * 1024        # a masterlist is ~2 MB; anything this large is not one


def _plugin_check():
    spec = importlib.util.spec_from_file_location("plugin_check", Path(__file__).resolve().parent / "plugin-check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def game_type(game: Path) -> str:
    if (game / "SkyrimVR.exe").is_file():
        return "SkyrimVR"
    if (game / "SkyrimSE.exe").is_file():
        return "SkyrimSE"
    raise ValueError("neither SkyrimVR.exe nor SkyrimSE.exe is in " + str(game))


def _get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:           # noqa: S310 (fixed https hosts above)
        data = r.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("%s answered more than %d bytes; refused" % (url, MAX_DOWNLOAD))
    return data


def _replace(path: Path, data: bytes) -> None:
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def newest_branch(repo: str, readable: tuple, fetch=None):
    """(branch, commit) of the newest vX.Y branch no newer than what this libloot reads."""
    rows = json.loads((fetch or _get)(API.format(repo=repo)))
    best = None
    for row in rows:
        m = re.fullmatch(r"v(\d+)\.(\d+)", row.get("name", ""))
        if not m:
            continue
        version = (int(m.group(1)), int(m.group(2)))
        if version <= readable and (best is None or version > best[0]):
            sha = str(row["commit"]["sha"])
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                raise ValueError("loot/%s branch %s has a malformed commit id" % (repo, row["name"]))
            best = (version, row["name"], sha)
    if best is None:
        raise ValueError("loot/%s has no branch this libloot (%d.%d) can read" % ((repo,) + readable))
    return best[1], best[2]


def _branch_version(branch) -> tuple | None:
    m = re.fullmatch(r"v(\d+)\.(\d+)", str(branch or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def masterlist(game: str, readable: tuple, offline: bool = False, fetch=None, cache: Path | None = None,
               validate=None):
    """Paths of the masterlist and prelude to use, plus where they came from.

    validate(masterlist, prelude) parses a fresh download BEFORE meta.json names it: a branch this libloot turns out
    not to read never becomes the cached copy (the fetch then falls back to the cache). A cached copy is used only
    when its branch is one this libloot reads."""
    folder = (CACHE if cache is None else cache) / REPOS[game]
    meta_path = folder / "meta.json"
    if not offline:
        try:
            # _get is looked up at call time (a fetch=_get default is bound once, at import, and a patched
            # module _get would then never be used).
            fetch = fetch or _get
            branch, commit = newest_branch(REPOS[game], readable, fetch)
            pbranch, pcommit = newest_branch("prelude", readable, fetch)
            ml = fetch(RAW.format(repo=REPOS[game], commit=commit, file="masterlist.yaml"))
            pre = fetch(RAW.format(repo="prelude", commit=pcommit, file="prelude.yaml"))
            # One folder per masterlist+prelude commit pair, and meta.json (which names it) written last: a run that
            # stops part-way leaves the previous meta pointing at a complete pair, never at a half-written one.
            store = folder / ("%s-%s" % (commit[:12], pcommit[:12]))
            store.mkdir(parents=True, exist_ok=True)
            _replace(store / "masterlist.yaml", ml)
            _replace(store / "prelude.yaml", pre)
            if validate is not None:
                try:
                    validate(store / "masterlist.yaml", store / "prelude.yaml")
                except Exception as exc:                          # noqa: BLE001 (libloot raises its own types)
                    raise ValueError("the fetched masterlist %s@%s did not parse: %s: %s"
                                     % (branch, commit[:7], type(exc).__name__, exc)) from None
            meta = {"masterlist": {"repo": REPOS[game], "branch": branch, "commit": commit},
                    "prelude": {"repo": "prelude", "branch": pbranch, "commit": pcommit},
                    "folder": store.name, "fetched_unix": int(time.time())}
            previous = json.loads(meta_path.read_text(encoding="utf-8")).get("folder") if meta_path.is_file() else None
            _replace(meta_path, json.dumps(meta, indent=1).encode("utf-8"))
            for old in folder.iterdir():          # this tool's own download cache: keep the current and previous pair
                if old.is_dir() and old.name not in (store.name, previous) and re.fullmatch(r"[0-9a-f]{12}-[0-9a-f]{12}", old.name):
                    shutil.rmtree(old)
            return store / "masterlist.yaml", store / "prelude.yaml", dict(meta, from_cache=False)
        except (OSError, ValueError, KeyError) as exc:
            reason = "%s: %s" % (type(exc).__name__, exc)
        else:
            reason = ""
    else:
        reason = "--offline"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    store = folder / str(meta.get("folder", ""))
    if not (meta.get("folder") and (store / "masterlist.yaml").is_file() and (store / "prelude.yaml").is_file()):
        raise ValueError("no masterlist: the fetch failed (%s) and none was fetched before" % reason)
    for part in ("masterlist", "prelude"):
        version = _branch_version((meta.get(part) or {}).get("branch"))
        if version is None or version > readable:
            raise ValueError("the cached %s is from branch %s, which this libloot (%d.%d) does not read; the fetch "
                             "failed (%s)" % ((part, (meta.get(part) or {}).get("branch")) + tuple(readable) + (reason,)))
    return store / "masterlist.yaml", store / "prelude.yaml", dict(meta, from_cache=True, fetch_problem=reason)


def moves(current, proposed):
    """The plugins whose relative position LOOT changes: everything outside the longest run the two orders share."""
    pos = {p: i for i, p in enumerate(current)}
    seq = [pos[p] for p in proposed if p in pos]
    tails, idx, prev = [], [], [-1] * len(seq)
    for i, x in enumerate(seq):
        k = bisect.bisect_left(tails, x)
        if k == len(tails):
            tails.append(x); idx.append(i)
        else:
            tails[k] = x; idx[k] = i
        prev[i] = idx[k - 1] if k else -1
    keep, i = set(), idx[-1] if idx else -1
    while i >= 0:
        keep.add(current[seq[i]]); i = prev[i]
    out = []
    for n, p in enumerate(proposed):
        if p not in keep:
            out.append({"plugin": p, "from": pos.get(p), "to": n, "after": proposed[n - 1] if n else None})
    return out


def _text(loot, content):
    try:
        return loot.select_message_content(content, "en").text
    except Exception:                                             # noqa: BLE001 (a message with no English text)
        return content[0].text if content else ""


PLUGIN_EXTS = (".esp", ".esm", ".esl")


def _name(f) -> str:
    n = f.name
    return n.as_str() if hasattr(n, "as_str") else str(n)


def present_check(active, data: Path, folders):
    """A plugin counts when it is active; any other file LOOT names (an SKSE DLL, `../sksevr_loader.exe`) when it is on
    disk below Data -- `..` reaching the game folder -- or in an enabled MO2 mod folder."""
    plugins = {p.casefold() for p in active}

    def present(name: str) -> bool:
        if name.lower().endswith(PLUGIN_EXTS):
            return name.casefold() in plugins
        return any((Path(base) / name).exists() for base in [data] + [Path(f) for f in folders])
    return present


def issues(loot, db, active, present=None):
    out = []
    present = present or present_check(active, Path("."), [])
    for m in db.general_messages(True, True):
        out.append({"kind": "general", "type": str(m.message_type).split(".")[-1], "text": _text(loot, m.content)})
    for name in active:
        md = db.plugin_metadata(name, True, True)
        if md is None:
            continue
        for m in md.messages:
            out.append({"kind": "message", "plugin": name, "type": str(m.message_type).split(".")[-1],
                        "text": _text(loot, m.content)})
        for d in md.dirty_info:
            out.append({"kind": "dirty", "plugin": name, "itm": d.itm_count, "deleted_references": d.deleted_reference_count,
                        "deleted_navmeshes": d.deleted_navmesh_count, "cleaner": d.cleaning_utility})
        for r in md.requirements:
            if not present(_name(r)):
                out.append({"kind": "requirement-missing", "plugin": name, "needs": _name(r),
                            "detail": r.display_name or ""})
        for c in md.incompatibilities:
            if present(_name(c)):
                out.append({"kind": "incompatible", "plugin": name, "with": _name(c), "detail": c.display_name or ""})
    return out


def userlist_source(path) -> dict | None:
    """Which userlist the sort used: its path and sha256, or None when none was given."""
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        raise ValueError("userlist not found: %s (LOOT keeps it at <LOOT data>/games/<game folder>/userlist.yaml)"
                         % path)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def advise(plugins_txt: Path, data: Path, game: Path, folders, offline=False, loot=None, fetch=None, userlist=None, from_app=None):
    if (plugins_txt.name.casefold() != "plugins.txt" if os.name == "nt" else plugins_txt.name != "Plugins.txt"):
        # libloot reads the file named Plugins.txt in the folder it is given, whatever path was passed here; a report
        # naming another file would describe a file libloot never read.
        raise ValueError("libloot reads only a file named Plugins.txt (any case on Windows); %s is named otherwise "
                         "(copy it to a folder as Plugins.txt and pass that)" % plugins_txt)
    ul = userlist_source(userlist)                                # before libloot: a wrong path costs nothing
    loot = loot or libloot_loader.load()
    kind = game_type(game)
    readable = (loot.LIBLOOT_VERSION_MAJOR, loot.LIBLOOT_VERSION_MINOR)
    g = loot.Game(getattr(loot.GameType, kind), game, plugins_txt.parent)
    if from_app is None:
        ml, pre, source = masterlist(kind, readable, offline, fetch,
                                     validate=lambda m, p: g.database().load_masterlist_with_prelude(m, p))
    else:
        ml, pre, app_userlist = app_files(from_app, kind)
        if userlist is None and app_userlist.is_file():
            userlist = app_userlist
        ul = userlist_source(userlist)
        source = {"masterlist": {"repo": "local", "branch": "app", "sha256": hashlib.sha256(ml.read_bytes()).hexdigest()},
                  "path": str(ml), "prelude": str(pre), "from_cache": False}
    if folders:
        g.set_additional_data_paths([Path(f) for f in folders])
    g.load_current_load_order_state()
    order = list(g.load_order())
    active = [p for p in order if g.is_plugin_active(p)]
    pc = _plugin_check()
    paths, missing = [], []
    for name in active:
        found = pc.locate(name, data, folders)
        (paths if found else missing).append(found or name)
    if missing:
        raise ValueError("active plugins not on disk (run plugin-check first): " + ", ".join(missing[:5]))
    g.load_plugins(paths)
    db = g.database()
    db.load_masterlist_with_prelude(ml, pre)
    if ul:
        db.load_userlist(Path(ul["path"]))                       # read-only: libloot never writes the userlist here
    proposed = list(g.sort_plugins(active))
    return {"game": kind, "libloot": loot.libloot_version(), "libloot_revision": loot.libloot_revision(),
            "masterlist": source, "userlist": ul, "plugins_txt": str(plugins_txt), "active": len(active),
            "moves": moves(active, proposed), "issues": issues(loot, db, active, present_check(active, data, folders)), "proposed": proposed,
            "note": "Advisory only: nothing was reordered. Wrye Bash / the mod manager owns the order; on a kept save "
                    "read KNOWLEDGEBASE.local.md `## My preferences` before moving anything."}


HEADER = '# This file was automatically generated by Mod Organizer.'
GAME_FOLDER = 'Skyrim Special Edition'


def app_dir(value):
    if value:
        return Path(value)
    value = os.environ.get('LOOT_APP_DIR')
    if not value:
        # The shared reader only accepts its registered keys. Reuse its literal parser
        # for this optional tool setting without expanding shell expressions.
        paths_file = skyrim_paths.TOOLKIT_ROOT / sg_paths.PATHS_FILE
        if paths_file.is_file():
            for line in paths_file.read_text(encoding='utf-8-sig').splitlines():
                match = re.fullmatch(r"\s*(?:export\s+)?LOOT_APP_DIR=(.*)", line)
                if match:
                    value = sg_paths.parse_value(match.group(1))
                    if value is None:
                        raise ValueError('LOOT_APP_DIR in skyrim-paths.env must be a literal path')
                    break
    if not value:
        raise ValueError('pass --from-app DIR or set LOOT_APP_DIR (environment or skyrim-paths.env)')
    return Path(value)


def app_files(folder, kind):
    game_folder = {'SkyrimSE': GAME_FOLDER, 'SkyrimVR': 'Skyrim VR'}[kind]
    game = Path(folder) / 'games' / game_folder
    ml, pre, ul = game / 'masterlist.yaml', Path(folder) / 'prelude' / 'prelude.yaml', game / 'userlist.yaml'
    for path in (ml, pre):
        if not path.is_file():
            raise ValueError(f'LOOT app file missing: {path} (run the LOOT app once, or pass --from-app DIR)')
    return ml, pre, ul


def read_lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding='utf-8-sig').splitlines() if l.strip() and not l.startswith('#')]


def read_locks(path: Path) -> list[tuple[str, int]]:
    """MO2 lockedorder.txt: 'Plugin.esp|index', index = position in the full load order (0-based)."""
    if not path.is_file():
        return []
    out = []
    for line in read_lines(path):
        name, _, idx = line.rpartition('|')
        out.append((name, int(idx)))
    return out


def apply_locks(order: list[str], locks: list[tuple[str, int]]) -> list[str]:
    """MO2's rule after a sort: each locked plugin goes back to its index (lowest index first); unknown names skip."""
    present = {p.lower() for p in order}
    locks = sorted((l for l in locks if l[0].lower() in present), key=lambda l: l[1])
    locked = {n.lower() for n, _ in locks}
    out = [p for p in order if p.lower() not in locked]
    by_lower = {p.lower(): p for p in order}
    for name, idx in locks:
        out.insert(min(idx, len(out)), by_lower[name.lower()])
    return out


def plugin_masters(path: Path) -> list[str]:
    """Master names from a plugin's TES4 header; [] when the header cannot be read."""
    import esp_records
    try:
        with open(path, 'rb') as fh:
            head = fh.read(24)
            if len(head) < 24 or head[:4] != b'TES4':
                return []
            size = int.from_bytes(head[4:8], 'little')
            return esp_records.masters(fh.read(size))
    except (OSError, ValueError):                            # esp_records.PluginError is a ValueError
        return []


def master_order_problems(order: list[str], paths: dict, locks: list[tuple[str, int]]) -> list[str]:
    """Each plugin that loads before one of its own masters, naming the lock that put it there."""
    pos = {p.lower(): i for i, p in enumerate(order)}
    locked = {n.lower() for n, _ in locks}
    out = []
    for p in order:
        path = paths.get(p.lower())
        for m in plugin_masters(path) if path else []:
            if m.lower() in pos and pos[m.lower()] > pos[p.lower()]:
                why = [x for x in (p, m) if x.lower() in locked]
                out.append(f'{p} loads before its master {m}' +
                           (f' (locked in lockedorder.txt: {", ".join(why)})' if why else ''))
    return out


def check_inputs(manifest: Path) -> int:
    """0 when every recorded profile file is as it was (present with the same bytes, or still absent)."""
    rows = json.loads(manifest.read_text(encoding='utf-8'))
    changed = []
    for f, digest in rows.items():
        path = Path(f)
        now = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if now != digest:
            changed.append(f'{path.name}: ' + ('appeared' if digest is None else 'gone' if now is None else 'changed'))
    for c in changed:
        print(f'input changed since the proposal: {c}', file=sys.stderr)
    if changed:
        print('Rerun loot_advisor --propose; nothing was applied.', file=sys.stderr)
    return 1 if changed else 0


def render(order: list[str], plugins_lines: list[str]) -> tuple[str, str]:
    """(loadorder.txt, plugins.txt) in MO2's format. plugins.txt keeps each original line (its '*' and spelling) and
    lists only the plugins it listed before (the implicit base-game and Creation Club plugins are not in it).
    An inactive line whose plugin the sort does not have (its file is gone) is dropped, as MO2 drops it on start;
    an active one still refuses."""
    orig = {l.lstrip('*').lower(): l for l in plugins_lines}
    lo = [HEADER] + order
    pl = [HEADER] + [orig[p.lower()] for p in order if p.lower() in orig]
    missing = set(orig) - {p.lower() for p in order}
    active = sorted(m for m in missing if orig[m].startswith('*'))
    if active:
        raise ValueError('plugins.txt lists plugins the sort does not have: ' + ', '.join(active[:5]))
    for m in sorted(missing):
        print(f'note: dropped inactive plugins.txt entry with no plugin file: {orig[m]}', file=sys.stderr)
    return '\r\n'.join(lo) + '\r\n', '\r\n'.join(pl) + '\r\n'


def sort_profile(profile: Path, loot_dir: Path, workdir: Path):
    game, _ = skyrim_paths.game_root()
    if game_type(game) != 'SkyrimSE':
        raise ValueError('--propose supports Skyrim SE/AE only; other game types are not supported')
    folders, problem = _plugin_check().mo2_folders(dict(os.environ, SKYRIM_LOADORDER_DIR=str(profile)))
    if problem:
        raise ValueError(problem)
    if not folders and not (profile / 'modlist.txt').is_file():
        raise ValueError('--propose requires an MO2 profile: no MO2 folders or modlist.txt found')
    ml, pre, ul = app_files(loot_dir, "SkyrimSE")
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / 'Plugins.txt').write_bytes((profile / 'plugins.txt').read_bytes())   # libloot reads only this name
    loot = libloot_loader.load()
    data = game / 'Data'
    g = loot.Game(getattr(loot.GameType, game_type(game)), game, workdir)
    g.set_additional_data_paths([Path(f) for f in folders])
    g.load_current_load_order_state()
    listed = list(g.load_order())
    current = [p for p in listed if g.is_plugin_active(p)]
    pc = _plugin_check()
    located = {n: pc.locate(n, data, folders) for n in listed}
    missing = [n for n in current if not located[n]]
    if missing:
        raise ValueError('active plugins not on disk: ' + ', '.join(map(str, missing[:5])))
    # Installed inactive plugins are sorted and kept, as LOOT's app does; an inactive entry with no file is
    # left out here and dropped (with a note) by render().
    installed = [n for n in listed if located[n]]
    paths = [located[n] for n in installed]
    g.load_plugins(paths)
    db = g.database()
    db.load_masterlist_with_prelude(ml, pre)
    if ul.is_file():
        db.load_userlist(ul)
    proposed = list(g.sort_plugins(installed))
    info = {'libloot': loot.libloot_version(), 'masterlist': ml, 'userlist': ul if ul.is_file() else None,
            'paths': {n.lower(): Path(located[n]) for n in installed},
            'folders': len(folders), 'issues': issues(loot, db, current, present_check(current, data, folders))}
    return current, proposed, moves, info


def propose(profile: Path, loot_dir: Path, out: Path | None = None) -> int:
    profile = profile.resolve()
    pl_txt, lo_txt, lock_txt = profile / 'plugins.txt', profile / 'loadorder.txt', profile / 'lockedorder.txt'
    if not pl_txt.is_file():
        print(f'COULD NOT SORT: no plugins.txt in {profile}', file=sys.stderr)
        return 2
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    if out is None:
        workspace = skyrim_paths.workspace_dir()
        if workspace is None:
            raise ValueError('set SKYRIM_WORKSPACE_DIR or pass --propose DIR')
        out = workspace / 'scratch' / 'loot-sort' / f'{profile.name}-{stamp}'
    if out.is_symlink():
        raise ValueError(f'proposal output {out} is a link; give a new folder')
    out = out.resolve()
    if out == profile or profile in out.parents:
        raise ValueError('proposal output must be outside the profile')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError(f'proposal output {out} already holds files; give a new or empty folder')
    out.mkdir(parents=True, exist_ok=True)
    # Every profile file the sort reads, present (its hash) or absent (null): the apply refuses if any differs.
    sums = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
            for f in (profile / 'modlist.txt', pl_txt, lo_txt, lock_txt)}

    def new_file(name, data: bytes):
        with open(out / name, 'xb') as fh:                   # never through a file or link already there
            fh.write(data)
    try:
        current, proposed, moves, info = sort_profile(profile, loot_dir, out / 'libloot-input')
    except Exception as exc:                                  # noqa: BLE001 (libloot raises its own types)
        print(f'COULD NOT SORT: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    locks = read_locks(lock_txt)
    final = apply_locks(proposed, locks)
    bad = master_order_problems(final, info.get('paths', {}), locks)
    if bad:
        for b in bad[:20]:
            print(f'COULD NOT SORT: {b}', file=sys.stderr)
        print('A lock puts a plugin before its master: fix lockedorder.txt (or unlock it in MO2), then rerun.',
              file=sys.stderr)
        return 2
    current_full = read_lines(lo_txt) if lo_txt.is_file() else current
    try:
        lo, pl = render(final, read_lines(pl_txt))
    except ValueError as exc:
        raise ValueError(f'could not render proposal: {exc}') from exc
    new_file('loadorder.txt', lo.encode())
    new_file('plugins.txt', pl.encode())
    mv = moves(current_full, final)
    new_file('moves.txt', (''.join(f'{m["plugin"]}  ->  after {m["after"] or "(top)"}\n' for m in mv)
                           or 'no moves\n').encode())
    iss = info['issues']
    new_file('issues.txt', (''.join(f'{i["kind"]:20} {i.get("plugin", "")}  '
                                    f'{ {k: v for k, v in i.items() if k not in ("kind", "plugin")} }\n'
                                    for i in iss) or 'none\n').encode())
    new_file('inputs.json', (json.dumps(sums, indent=1) + '\n').encode())
    same = lo_txt.is_file() and lo.encode() == lo_txt.read_bytes() and pl.encode() == pl_txt.read_bytes()
    print(f'libloot {info["libloot"]}; masterlist {info["masterlist"]}; userlist {"yes" if info["userlist"] else "none"}; '
          f'{info["folders"]} MO2 folders; {len(final)} plugins; locks {len(locks)}')
    print(f'{len(mv)} plugin(s) move; {sum(1 for i in iss if str(i.get("type", "")).lower() not in ("say",))} LOOT '
          f'finding(s) (issues.txt); proposal in {out}')
    for m in mv[:30]:
        print(f'  move {m["plugin"]} -> after {m["after"] or "(top)"}')
    if same:
        print('Already sorted: the proposal equals the profile byte for byte. Nothing to apply.')
        return 0
    q = lambda p: shlex.quote(str(p))
    backups = ' && '.join(f'cp {q(f)} {q(str(f) + ".bak-" + stamp)}' for f in (pl_txt, lo_txt) if f.is_file())
    print('\nApply (close MO2 first; it rewrites these files on exit). Backs up existing files, refuses if inputs changed:')
    print("! if pgrep -f ModOrganizer >/dev/null; then echo 'Close MO2 before applying' >&2; false; else "
          f'{q(sys.executable)} {q(Path(__file__).resolve())} --check-inputs {q(out / "inputs.json")} && {backups} && '
          f'cp {q(out / "plugins.txt")} {q(out / "loadorder.txt")} {q(profile)}/ && echo applied; fi')
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plugins-txt")
    ap.add_argument("--data")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true", help="use the last fetched masterlist; no network")
    ap.add_argument("--userlist", help="LOOT's userlist.yaml: apply the rules set in LOOT's app, as LOOT does")
    ap.add_argument('--from-app', nargs='?', const='', default=None, metavar='DIR',
                    help="read the LOOT app's local lists; default: LOOT_APP_DIR")
    ap.add_argument('--propose', nargs='?', const='', default=None, metavar='DIR',
                    help='write a proposal outside the profile; default: workspace/scratch/loot-sort/profile-stamp')
    ap.add_argument('--check-inputs', metavar='FILE', help="verify a proposal's inputs.json against the profile (exit 0/1)")
    args = ap.parse_args(argv)
    if args.check_inputs:
        return check_inputs(Path(args.check_inputs))
    try:
        if args.offline and (args.from_app is not None or args.propose is not None):
            raise ValueError('--offline cannot be combined with --from-app or --propose; app lists are already local')
        local_app = app_dir(args.from_app or '') if args.from_app is not None or args.propose is not None else None
        if args.propose is not None:
            plugins = Path(args.plugins_txt) if args.plugins_txt else Path(
                sg_paths.plugins_txt(os.environ, [str(skyrim_paths.TOOLKIT_ROOT / sg_paths.PATHS_FILE)]))
            if args.data or args.userlist or args.json:
                raise ValueError('--propose uses the configured game and app lists; do not combine with --data, --userlist or --json')
            return propose(plugins.parent, local_app, Path(args.propose) if args.propose else None)
        game, _ = skyrim_paths.game_root()
        data = Path(args.data) if args.data else game / "Data"
        plugins_txt = Path(args.plugins_txt) if args.plugins_txt else Path(
            sg_paths.plugins_txt(os.environ, [str(skyrim_paths.TOOLKIT_ROOT / sg_paths.PATHS_FILE)]))
        if not plugins_txt.is_file():
            raise ValueError("plugins.txt not found: " + str(plugins_txt))
        folders, problem = _plugin_check().mo2_folders(os.environ)
        if problem:
            raise ValueError(problem)
        if local_app is None:
            report = advise(plugins_txt, data, game, folders, args.offline, userlist=args.userlist)
        else:
            report = advise(plugins_txt, data, game, folders, args.offline, userlist=args.userlist, from_app=local_app)
    except (OSError, ValueError, libloot_loader.Unavailable) as exc:
        print(("COULD NOT SORT: " if args.propose is not None else "COULD NOT CHECK: ") + str(exc) + " -- this is not a clean result.", file=sys.stderr)
        return 2
    except Exception as exc:                                      # noqa: BLE001 (libloot raises its own types)
        print(("COULD NOT SORT: " if args.propose is not None else "COULD NOT CHECK: ") +
              "libloot: %s: %s -- this is not a clean result." % (type(exc).__name__, exc),
              file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        src = report["masterlist"]
        ml = src["masterlist"]
        label = ("local app sha256:" + ml["sha256"][:7] if ml["repo"] == "local" else
                 "%s %s@%s" % (ml["repo"], ml["branch"], ml["commit"][:7]))
        print("LOOT %s on %d active plugins; masterlist %s%s" % (
            report["libloot"], report["active"], label,
            " (CACHED: " + src.get("fetch_problem", "") + ")" if src.get("from_cache") else ""))
        print("userlist " + report["userlist"]["path"] if report["userlist"]
              else "no userlist: rules set in LOOT's app are not applied (--userlist PATH)")
        print("%d plugin(s) LOOT would move; %d issue(s)" % (len(report["moves"]), len(report["issues"])))
        for m in report["moves"]:
            print("  move   %s -> after %s" % (m["plugin"], m["after"] or "(top)"))
        for i in report["issues"]:
            detail = {k: v for k, v in i.items() if k not in ("kind", "plugin")}
            print("  %-19s %s %s" % (i["kind"], i.get("plugin", ""), json.dumps(detail, ensure_ascii=False)))
        print(report["note"])
    # A masterlist "say" message is information, not a finding: it is listed, and does not make the exit 1.
    findings = [i for i in report["issues"] if str(i.get("type", "")).lower() != "say"]
    return 1 if report["moves"] or findings else 0


if __name__ == "__main__":
    sys.exit(main())
