#!/usr/bin/env python3
"""master-update-impact -- what does a new version of a master plugin break in the ACTIVE load order? READ-ONLY.

Compares an old and a new copy of one master (e.g. BSHeartland.esm 2.0.0 and 2.0.1), then reads every active plugin
that has it as a master and reports, per plugin:
  dangling   overrides of a record the new version no longer defines (the override now injects a stray record)
  keeps-old  overrides of a record the new version changed, where the plugin carries the OLD value of a changed field:
             where the plugin wins, it reverts the update's fix
  own        the plugin has its own value in every changed field (intended, but review it against the new value)
  current    the plugin already matches the new value in every changed field
VMAD (scripts) is compared parsed, with properties sorted, so a re-save that only reorders properties is not a change;
other fields are compared as bytes, as a multiset per tag (subrecord order ignored).

Uses tools/esp_records.py (the independent byte parser) and plugin-check.py's load-order resolution: plugins.txt plus
the enabled Mod Organizer 2 folders (highest priority first), else Data.

Usage:  python tools/master-update-impact.py OLD NEW [--name MASTER] [--plugins-txt PATH] [--data DIR]
                                               [--top N] [--json]
        OLD/NEW are the two copies of the master (keep the old one before updating). --name defaults to NEW's file
        name. --top limits the records listed per plugin (default 15; --json lists all).
Exit:   0 no active plugin overrides a removed or changed record · 1 something to review (or a file read only
        partly: INCONCLUSIVE) · 2 could not check (named), never "clean"
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from esp_records import PluginError, read, subrecs          # noqa: E402

_spec = importlib.util.spec_from_file_location("plugin_check", HERE / "plugin-check.py")
plugin_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin_check)


# --- VMAD, parsed -----------------------------------------------------------------------------------------------------
_FIXED = {0: 0, 1: 8, 3: 4, 4: 4, 5: 1}           # property type -> value size (0 = no value: an empty property)


def vmad_canon(data: bytes):
    """(version, object format, scripts sorted by name with properties sorted by name, trailing fragment bytes), or
    None when the layout is not one this reader knows (a struct property, a truncated body): compare bytes then."""
    try:
        ver, fmt, count = struct.unpack_from("<hhH", data, 0)
        i = 6

        def wstring(i):
            n = struct.unpack_from("<H", data, i)[0]
            if i + 2 + n > len(data):
                raise ValueError("wstring past the end")
            return data[i + 2:i + 2 + n], i + 2 + n

        def value(t, i):
            if t in _FIXED:
                return data[i:i + _FIXED[t]], i + _FIXED[t]
            if t == 2:
                return wstring(i)
            if 11 <= t <= 15:
                n = struct.unpack_from("<I", data, i)[0]
                j, items = i + 4, []
                for _ in range(n):
                    v, j = value(t - 10, j)
                    items.append(v)
                return tuple(items), j
            raise ValueError("property type {}".format(t))

        scripts = []
        for _ in range(count):
            name, i = wstring(i)
            status = data[i] if ver >= 4 else 0
            i += 1 if ver >= 4 else 0
            n = struct.unpack_from("<H", data, i)[0]
            i += 2
            props = []
            for _ in range(n):
                pname, i = wstring(i)
                t = data[i]
                pstatus = data[i + 1] if ver >= 4 else 0
                i += 2 if ver >= 4 else 1
                v, i = value(t, i)
                props.append((pname.lower(), t, pstatus, v))
            scripts.append((name.lower(), status, tuple(sorted(props))))
        if i > len(data):
            return None
        return ver, fmt, tuple(sorted(scripts)), data[i:]
    except (struct.error, IndexError, ValueError):
        return None


def tag_values(tag, values):
    out = []
    for v in values:
        c = vmad_canon(v) if tag == "VMAD" else None
        out.append(("canon", c) if c is not None else ("bytes", v))
    return collections.Counter(out)


def fields(body):
    by = collections.defaultdict(list)
    for t, v in subrecs(body, problems=[]):
        by[t].append(v)
    return by


def changed_tags(a, b):
    """Tags whose values differ between two field maps (VMAD parsed); [] when only the order changed."""
    return sorted(t for t in set(a) | set(b) if tag_values(t, a.get(t, [])) != tag_values(t, b.get(t, [])))


# --- the master: old against new ---------------------------------------------------------------------------------------
def own_records(plugin):
    """{object id: Record} of the records the plugin defines itself."""
    n = len(plugin.masters)
    return {r.formid & 0xFFFFFF: r for r in plugin.records if r.formid >> 24 == n}


def master_diff(old, new):
    o, n = own_records(old), own_records(new)
    removed = {k: o[k] for k in o.keys() - n.keys()}
    added = {k: n[k] for k in n.keys() - o.keys()}
    changed, order_only = {}, 0
    for k in o.keys() & n.keys():
        if o[k].sha1 == n[k].sha1 and o[k].flags == n[k].flags and o[k].type == n[k].type:
            continue
        fa, fb = fields(o[k].body), fields(n[k].body)
        tags = changed_tags(fa, fb)
        if not tags and o[k].flags == n[k].flags and o[k].type == n[k].type:
            order_only += 1
            continue
        changed[k] = (o[k], n[k], fa, fb, tags or ["(record flags)"])
    return removed, added, changed, order_only


# --- the load order --------------------------------------------------------------------------------------------------
def active_order(plugins_txt: Path, data: Path, game: Path):
    rows = plugin_check.parse_plugins(plugins_txt.read_bytes())
    order = []
    for name in plugin_check.implicit_masters(game, data) + [n for n, active in rows if active]:
        if name.casefold() not in {x.casefold() for x in order}:
            order.append(name)
    return order


def impact(old_path, new_path, name, plugins_txt, data, game, folders):
    old, new = read(old_path), read(new_path)
    removed, added, changed, order_only = master_diff(old, new)
    aligned_master = [m.casefold() for m in old.masters] == [m.casefold() for m in new.masters]
    expect = [m.casefold() for m in new.masters] + [name.casefold()]
    problems = ["old: " + p for p in old.problems] + ["new: " + p for p in new.problems]
    order = active_order(plugins_txt, data, game)
    deps, missing = [], []
    for plug in order:
        if plug.casefold() == name.casefold():
            continue
        path = plugin_check.locate(plug, data, folders)
        if path is None:
            missing.append(plug)
            continue
        try:
            head = plugin_check.plugin_header(path)
        except Exception as exc:                      # a header this reader refuses: named, never skipped silently
            problems.append("{}: header unreadable ({})".format(plug, exc))
            continue
        if name.casefold() not in [m.casefold() for m in head["masters"]]:
            continue
        p = read(path)
        problems += ["{}: {}".format(plug, x) for x in p.problems]
        idx = [m.casefold() for m in p.masters].index(name.casefold())
        aligned = [m.casefold() for m in p.masters[:len(expect)]] == expect and aligned_master
        rows = []
        for r in p.records:
            if r.formid >> 24 != idx:
                continue
            k = r.formid & 0xFFFFFF
            if k in removed:
                rows.append({"id": k, "type": r.type, "edid": removed[k].edid or r.edid, "kind": "dangling",
                             "fields": []})
            elif k in changed:
                ro, rn, fa, fb, tags = changed[k]
                mine = fields(r.body)
                verdict = {}
                for t in tags:
                    if t.startswith("("):
                        continue
                    v = tag_values(t, mine.get(t, []))
                    verdict[t] = ("old" if v == tag_values(t, fa.get(t, [])) else
                                  "new" if v == tag_values(t, fb.get(t, [])) else "own")
                kind = ("keeps-old" if "old" in verdict.values() else
                        "own" if "own" in verdict.values() else "current")
                if not aligned and kind != "current":
                    kind = "review"           # master lists differ: FormIDs inside fields are not byte-comparable
                rows.append({"id": k, "type": rn.type, "edid": rn.edid, "kind": kind,
                             "fields": sorted(verdict.items())})
        if rows:
            deps.append({"plugin": plug, "path": str(path), "folder": path.parent.name, "aligned": aligned,
                         "rows": rows})
    # Winner among the dependents: the last one in the load order that overrides the record.
    last = {}
    for d in deps:
        for row in d["rows"]:
            last[row["id"]] = d["plugin"]
    for d in deps:
        for row in d["rows"]:
            row["wins"] = last[row["id"]] == d["plugin"]
    return {
        "master": name, "old": str(old_path), "new": str(new_path),
        "old_records": len(own_records(old)), "new_records": len(own_records(new)),
        "removed": len(removed), "added": len(added), "changed": len(changed), "order_only": order_only,
        "removed_by_type": dict(collections.Counter(r.type for r in removed.values()).most_common()),
        "changed_by_type": dict(collections.Counter(c[1].type for c in changed.values()).most_common()),
        "master_lists_equal": aligned_master, "active_plugins": len(order), "missing_on_disk": missing,
        "dependents": deps, "problems": problems,
    }


KINDS = ("dangling", "keeps-old", "own", "review", "current")


def report_text(rep, top):
    print("master {}: old {} records, new {}; removed {} ({}), added {}, changed {} (+{} reordered only)".format(
        rep["master"], rep["old_records"], rep["new_records"], rep["removed"],
        ", ".join("{} {}".format(t, n) for t, n in list(rep["removed_by_type"].items())[:6]) or "-",
        rep["added"], rep["changed"], rep["order_only"]))
    if not rep["master_lists_equal"]:
        print("NOTE: old and new master lists differ; field comparisons are marked review")
    print("{} active plugins; {} override a removed or changed record:".format(
        rep["active_plugins"], len(rep["dependents"])))
    for d in rep["dependents"]:
        c = collections.Counter(r["kind"] for r in d["rows"])
        wins = sum(1 for r in d["rows"] if r["wins"])
        print("  {} [{}]  {}  (wins {} of {})".format(
            d["plugin"], d["folder"], "  ".join("{} {}".format(k, c[k]) for k in KINDS if c[k]), wins,
            len(d["rows"])))
        shown = [r for r in d["rows"] if r["kind"] != "current"][:top]
        for r in shown:
            f = " ".join("{}={}".format(t, v) for t, v in r["fields"])
            print("    {:9} {:06X} {} {}{}{}".format(r["kind"].upper(), r["id"], r["type"], r["edid"],
                                                 "  " + f if f else "", "" if r["wins"] else "  (loses)"))
        hidden = len([r for r in d["rows"] if r["kind"] != "current"]) - len(shown)
        if hidden > 0:
            print("    ... {} more (--top or --json)".format(hidden))
    for m in rep["missing_on_disk"]:
        print("MISSING active plugin not on disk: " + m)
    for p in rep["problems"]:
        print("PROBLEM " + p)
    if rep["problems"]:
        print("INCONCLUSIVE: {} problem(s) above".format(len(rep["problems"])))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--name")
    ap.add_argument("--plugins-txt")
    ap.add_argument("--data")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        game, _ = plugin_check.skyrim_paths.game_root()
        data = Path(args.data) if args.data else game / "Data"
        plugins_txt = Path(args.plugins_txt) if args.plugins_txt else Path(plugin_check.sg_paths.plugins_txt(
            os.environ, [str(plugin_check.skyrim_paths.TOOLKIT_ROOT / plugin_check.sg_paths.PATHS_FILE)]))
        if not plugins_txt.is_file():
            raise ValueError("plugins.txt not found: " + str(plugins_txt))
        for p in (args.old, args.new):
            if not Path(p).is_file():
                raise ValueError("not a file: " + p)
        folders, problem = plugin_check.mo2_folders(os.environ)
        if problem:
            raise ValueError(problem)
        rep = impact(Path(args.old), Path(args.new), args.name or Path(args.new).name, plugins_txt, data, game,
                     folders)
    except (OSError, ValueError, PluginError, plugin_check.Refusal) as exc:
        print("COULD NOT CHECK: " + str(exc) + " -- this is not a clean result.", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rep, indent=1))
    else:
        report_text(rep, args.top)
    review = any(r["kind"] != "current" for d in rep["dependents"] for r in d["rows"])
    return 1 if review or rep["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
