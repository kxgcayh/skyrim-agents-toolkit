#!/usr/bin/env python3
"""nexus-collection -- turn a published Nexus collection into MO2-ready inputs. Stdlib only; needs bsdtar or 7z.

    nexus-collection.py plan     <slug> --out DIR [--mo2]    (--mo2: only modlist.txt [+ plugins.txt]) fetch the manifest, write the reference files (no mod download)
    nexus-collection.py download <slug> --out DIR [--apply]  archives + MO2 .meta files into DIR/downloads (dry run without --apply)

plan writes: collection.json (manifest), modlist.txt (MO2 order: HIGHEST priority first, like a profile's own),
plugins.txt (only when the manifest carries a real load order), downloads.tsv, fomod-choices.json. The key comes from tools/.nexus_api_key or $NEXUS_API_KEY and is
never printed. Needs a Premium key for download. Exit: 0 ok | 2 usage/response problem | 3 could not reach/auth.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API, GQL = "https://api.nexusmods.com", "https://api.nexusmods.com/v2/graphql"
UA = "skyrim-ai-toolkit-nexus-collection/1"
GAME_NAMES = {"skyrimspecialedition": "SkyrimSE"}


def key():
    try:
        with open(os.path.join(HERE, ".nexus_api_key")) as f:
            k = f.read().strip()
    except OSError:
        k = os.environ.get("NEXUS_API_KEY", "").strip()
    if not k:
        sys.exit("No Nexus API key (tools/.nexus_api_key or $NEXUS_API_KEY)\nRESULT: COULD-NOT-CHECK")
    return k


def call(url, data=None):
    h = {"apikey": KEY, "Accept": "application/json", "User-Agent": UA}
    if data is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data, h), timeout=30) as r:
            return json.load(r), r.headers
    except urllib.error.HTTPError as e:
        sys.exit("ERROR: Nexus answered HTTP {} for {}\nRESULT: COULD-NOT-CHECK".format(e.code, url.split("?")[0]))
    except (urllib.error.URLError, OSError, ValueError) as e:
        sys.exit("ERROR: {} ({})\nRESULT: COULD-NOT-CHECK".format(type(e).__name__, url.split("?")[0]))


def fetch_manifest(slug, out):
    q = '{ collection(slug:"%s") { name latestPublishedRevision { revisionNumber downloadLink } } }' % slug
    c = (call(GQL, {"query": q})[0].get("data") or {}).get("collection")
    rev = (c or {}).get("latestPublishedRevision") or {}
    path = rev.get("downloadLink") or ""
    if not re.fullmatch(r"/v2/collections/\d+/revisions/\d+/download_link", path):
        sys.exit("ERROR: no downloadable revision for slug '{}'".format(slug))
    uri = call(API + path)[0]["download_links"][0]["URI"]
    if not uri.startswith("https://"):
        sys.exit("ERROR: manifest link is not https")
    tool = shutil.which("bsdtar") or shutil.which("7zz") or shutil.which("7z")
    if not tool:
        sys.exit("ERROR: need bsdtar or 7z to unpack the manifest")
    with tempfile.TemporaryDirectory() as t:
        arc = os.path.join(t, "m.7z")
        with urllib.request.urlopen(urllib.request.Request(uri, headers={"User-Agent": UA}), timeout=60) as r, open(arc, "wb") as f:
            shutil.copyfileobj(r, f)
        cmd = [tool, "-xf", arc, "-C", t, "collection.json"] if "bsdtar" in tool else [tool, "x", "-y", "-o" + t, arc, "collection.json"]
        subprocess.run(cmd, check=True, capture_output=True)
        os.makedirs(out, exist_ok=True)
        shutil.copyfile(os.path.join(t, "collection.json"), os.path.join(out, "collection.json"))
    print("manifest: {} rev {}".format(c["name"], rev["revisionNumber"]))
    return json.load(open(os.path.join(out, "collection.json")))


def install_order(mods, rules):
    """Install order (first = lowest priority) from before/after rules; ties keep manifest order."""
    by_md5 = {m["source"].get("md5"): i for i, m in enumerate(mods)}
    by_logical = {m["source"].get("logicalFilename"): i for i, m in enumerate(mods)}
    succ, indeg = {i: set() for i in range(len(mods))}, [0] * len(mods)
    for r in rules:
        if r.get("type") not in ("before", "after"):
            continue
        a = by_md5.get(r["source"].get("fileMD5"), by_logical.get(r["source"].get("logicalFileName")))
        b = by_md5.get(r["reference"].get("fileMD5"), by_logical.get(r["reference"].get("logicalFileName")))
        if a is None or b is None or a == b:
            continue
        first, second = (a, b) if r["type"] == "before" else (b, a)
        if second not in succ[first]:
            succ[first].add(second)
            indeg[second] += 1
    order, ready = [], sorted(i for i in range(len(mods)) if indeg[i] == 0)
    while ready:
        i = ready.pop(0)
        order.append(i)
        for j in sorted(succ[i]):
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
        ready.sort()
    cyc = [i for i in range(len(mods)) if i not in set(order)]
    return order + cyc, len(cyc)


def safe(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")


def cmd_plan(slug, out, mo2_only=False):
    d = fetch_manifest(slug, out)
    mods = d["mods"]
    order, cyc = install_order(mods, d.get("modRules") or [])
    w = lambda n, lines: open(os.path.join(out, n), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    w("modlist.txt", ["# Generated from Nexus collection '{}' ({}). Highest priority first; optional mods disabled."
                      .format(d["info"]["name"], slug)] +
      [("-" if mods[i].get("optional") else "+") + safe(mods[i]["name"]) for i in reversed(order)])
    seen, plugins = set(), []
    for p in d.get("plugins") or []:
        if p["name"].lower() not in seen:
            seen.add(p["name"].lower())
            plugins.append(("*" if p.get("enabled", True) else "") + p["name"])
    full_order = len(plugins) >= 0.5 * len(mods)   # a few forced entries are not a load order
    if full_order:
        w("plugins.txt", ["# This file was automatically generated by Mod Organizer."] + plugins)
    else:
        print("no plugin load order in this collection ({} forced entries): run LOOT after installing".format(len(plugins)))
    if mo2_only:
        os.remove(os.path.join(out, "collection.json"))
        print("{} mods -> modlist.txt{} in {}".format(len(mods), " plugins.txt" if full_order else "", out))
        return
    w("downloads.tsv", ["modId\tfileId\tsize\tmd5\toptional\tname"] + [
        "{modId}\t{fileId}\t{fileSize}\t{md5}\t{o}\t{n}".format(o=int(bool(m.get("optional"))), n=m["name"], **m["source"])
        for m in mods])
    json.dump({m["name"]: m["choices"] for m in mods if m.get("choices")}, open(os.path.join(out, "fomod-choices.json"), "w"), indent=1)
    size = sum(m["source"]["fileSize"] for m in mods)
    print("{} files, {:.1f} GB, {} FOMOD choice sets, {} plugin entries; {} mod(s) in ordering cycles (kept manifest order)"
          .format(len(mods), size / 1e9, sum(1 for m in mods if m.get("choices")), len(plugins), cyc))
    print("wrote collection.json modlist.txt {}downloads.tsv fomod-choices.json -> {}".format("plugins.txt " if full_order else "", out))


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cmd_download(slug, out, apply):
    mf = os.path.join(out, "collection.json")
    d = json.load(open(mf)) if os.path.exists(mf) else fetch_manifest(slug, out)
    dom = d["info"]["domainName"]
    dl = os.path.join(out, "downloads")
    os.makedirs(dl, exist_ok=True)
    todo = 0
    for n, m in enumerate(d["mods"], 1):
        s = m["source"]
        info, hdr = call("{}/v1/games/{}/mods/{}/files/{}.json".format(API, dom, s["modId"], s["fileId"]))
        fname = safe(os.path.basename(info["file_name"]))
        dest = os.path.join(dl, fname)
        if os.path.exists(dest) and os.path.getsize(dest) == s["fileSize"] and md5_of(dest) == s["md5"]:
            state = "have"
        else:
            state = "get"
            todo += 1
        print("[{}/{}] {} {} ({:.1f} MB)".format(n, len(d["mods"]), state, fname, s["fileSize"] / 1e6))
        if int(hdr.get("x-rl-hourly-remaining", 999)) < 50:
            sys.exit("STOP: hourly API budget nearly spent; rerun after " + str(hdr.get("x-rl-hourly-reset")))
        if state == "get" and apply:
            link = call("{}/v1/games/{}/mods/{}/files/{}/download_link.json".format(API, dom, s["modId"], s["fileId"]))[0][0]["URI"]
            if not link.startswith("https://"):
                sys.exit("ERROR: download link is not https")
            req = urllib.request.Request(link, headers={"User-Agent": UA})   # the CDN 403s the bare Python-urllib agent
            with urllib.request.urlopen(req, timeout=60) as r, open(dest + ".part", "wb") as f:
                shutil.copyfileobj(r, f)
            if md5_of(dest + ".part") != s["md5"]:
                os.replace(dest + ".part", dest + ".BAD-MD5")
                print("  ! md5 mismatch, kept as .BAD-MD5")
                continue
            os.replace(dest + ".part", dest)
            time.sleep(0.3)
        if apply and os.path.exists(dest):
            open(dest + ".meta", "w", encoding="utf-8", newline="\n").write(
                "[General]\ngameName={}\nmodID={}\nfileID={}\nname={}\nversion={}\nnewestVersion=\nrepository=Nexus\n"
                "installed=false\nuninstalled=false\npaused=false\nremoved=false\n"
                .format(GAME_NAMES.get(dom, dom), s["modId"], s["fileId"], m["name"], m.get("version", "")))
    print("{} to download of {}{}".format(todo, len(d["mods"]), "" if apply else "  (dry run; pass --apply)"))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 4 or a[0] not in ("plan", "download") or a[2] != "--out" or not re.fullmatch(r"[a-z0-9]+", a[1]):
        sys.exit(__doc__)
    KEY = key()
    out = os.path.abspath(a[3])
    if a[0] == "plan":
        cmd_plan(a[1], out, "--mo2" in a[4:])
    else:
        cmd_download(a[1], out, "--apply" in a[4:])
