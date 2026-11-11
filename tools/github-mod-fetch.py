#!/usr/bin/env python3
"""github-mod-fetch -- download a GitHub release asset as an MO2-installable archive with its download .meta.

Mod Organizer 2's "Install a new mod from archive" reads <archive>.meta from the archive's own folder and copies
its version, modid and categories over the installed mod's meta.ini. An archive without one installs as
version 0.0.0.0, and a bare .dll release asset is not an installable archive at all. This tool:

  1. resolves the release (latest, or --tag) through the GitHub REST API;
  2. picks one asset: an archive (.zip .7z .rar), or a bare .dll or plugin (.esp .esm .esl);
  3. downloads it, checking the size and, when GitHub publishes one, the SHA-256 digest;
  4. keeps an archive byte-for-byte, or wraps a bare .dll into SKSE/Plugins/ (a plugin into the zip root) with a
     root meta.ini pointing at the repository;
  5. writes <archive>.meta in the layout MO2 itself writes. The version is the release tag, minus one leading v.

Usage:
    python tools/github-mod-fetch.py <owner/repo | GitHub URL> --mod-category N
        [--tag T] [--asset NAME] [--file-category main|update|optional|old|miscellaneous]
        [--nexus-id N] [--name NAME] [--out DIR] [--dry-run] [--force]

--mod-category  Nexus mod category id (integer > 0), the .meta's category=. Required, never guessed:
                list them with `bash tools/nexus.sh raw /games/skyrimspecialedition.json`.
--out           default: the OS Downloads folder. The game folder and the MO2 instance are refused.
GITHUB_TOKEN    optional, raises the API rate limit. Nothing else about the user is sent.
Exit: 0 written (or planned, with --dry-run) · 1 network or verification failure · 2 bad usage / refused.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TOOLKIT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
USER_AGENT = "skyrim-ai-toolkit-github-mod-fetch"
ARCHIVE_EXTS = (".zip", ".7z", ".rar")
PLUGIN_EXTS = (".esp", ".esm", ".esl")
COMPANION_EXTS = (".pdb", ".ini", ".toml", ".json")
# Top-level entries MO2's Gamebryo data checker accepts as "this is a data folder" (plus any plugin/archive file).
DATA_DIRS = {"skse", "meshes", "textures", "scripts", "interface", "sound", "music", "seq", "strings", "grass",
             "lodsettings", "shadersfx", "video", "facegen", "materials", "calientetools", "netscriptframework",
             "fomod", "data"}
DATA_FILE_EXTS = PLUGIN_EXTS + (".bsa", ".ba2")
# Nexus file category ids, the values MO2 stores as fileCategory in a download's .meta.
FILE_CATEGORY_IDS = {"main": 1, "update": 2, "optional": 3, "old": 4, "miscellaneous": 5}


class Refused(Exception):
    """Bad usage or a refusal: exit 2."""


class Failed(Exception):
    """Network or verification failure: exit 1."""


# ---------------------------------------------------------------- .meta / meta.ini (MO2 layout)

def qsettings_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def tag_version(tag: str) -> str:
    """The .meta version is the release tag with one leading v/V removed, nothing else changed."""
    version = tag[1:] if tag[:1] in ("v", "V") and len(tag) > 1 else tag
    if not re.search(r"\d", version) or re.search(r"[\s\r\n=]", version):
        raise Refused(f"release tag {tag!r} is not a version; pass --tag with a versioned release")
    return version


def download_meta(*, mod_id: int, mod_name: str, version: str, file_category: int, mod_category: int,
                  file_name: str = "") -> str:
    """<archive>.meta as MO2 writes it after "Query info". Key order, empty values and the fileTime/userData
    literals are copied from a real MO2 .meta (same layout as mod-release's download_meta)."""
    name = qsettings_quote(mod_name) if re.search(r'[,;"=\\]|^\s|\s$', mod_name) else mod_name
    fname = qsettings_quote(file_name) if re.search(r'[,;"=\\]|^\s|\s$', file_name) else file_name
    lines = ["[General]", "gameName=SkyrimSE", f"modID={int(mod_id)}",
             f"modName={name}", f"version={version}", f"newestVersion={version}", "installed=false",
             "fileID=0", "url=", f"name={fname}", "description=",
             r"fileTime=@DateTime(\0\0\0\x10\0\x80\0\0\0\0\0\0\0\xff\xff\xff\xff\0)",
             f"fileCategory={file_category}", f"category={mod_category}", "repository=",
             r"userData=@Variant(\0\0\0\b\0\0\0\0)",
             "author=", "uploader=", "uploaderUrl=", "uninstalled=false", "paused=false", "removed=false"]
    return "\r\n".join(lines) + "\r\n"


def bundled_meta_ini(*, version: str, repo_url: str, mod_id: int, comments: str = "") -> str:
    """Root meta.ini for an archive this tool builds: MO2 keeps url/hasCustomURL ("Visit web page")."""
    lines = ["[General]", "gameName=SkyrimSE", f"version={version}", f"newestVersion={version}"]
    if mod_id:
        lines.append(f"modid={int(mod_id)}")
    lines += [f"url={repo_url}", "hasCustomURL=true"]
    if comments:
        lines.append(f"comments={qsettings_quote(comments)}")
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------- GitHub

def parse_repo(text: str) -> tuple[str, str]:
    text = text.strip()
    m = re.fullmatch(r"(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?", text) \
        or re.fullmatch(r"([\w.-]+)/([\w.-]+?)(?:\.git)?", text)
    if not m:
        raise Refused(f"not a GitHub repository: {text!r} (want owner/repo or a github.com URL)")
    return m.group(1), m.group(2)


def _request(url: str, accept: str = "application/vnd.github+json") -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def api_get(path: str) -> dict:
    try:
        with urllib.request.urlopen(_request(API + path), timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise Refused(f"GitHub says 404 for {path}: no such repository or release "
                          "(a repo with no releases is source-only: build it, this tool does not)") from None
        raise Failed(f"GitHub API {exc.code} for {path}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Failed(f"GitHub API request failed for {path}: {exc}") from None


def get_release(owner: str, repo: str, tag: str | None) -> dict:
    if tag:
        return api_get(f"/repos/{owner}/{repo}/releases/tags/{urllib.parse.quote(tag, safe='')}")
    return api_get(f"/repos/{owner}/{repo}/releases/latest")


def asset_kind(name: str) -> str | None:
    low = name.lower()
    if low.endswith(ARCHIVE_EXTS):
        return "archive"
    if low.endswith(".dll"):
        return "dll"
    if low.endswith(PLUGIN_EXTS):
        return "plugin"
    return None


def pick_asset(assets: list[dict], wanted: str | None) -> dict:
    if wanted:
        for a in assets:
            if a.get("name") == wanted:
                if not asset_kind(wanted):
                    raise Refused(f"--asset {wanted!r} is not an archive, .dll or plugin")
                return a
        raise Refused(f"--asset {wanted!r} is not in this release; assets: "
                      + ", ".join(a.get("name", "?") for a in assets))
    candidates = [a for a in assets if asset_kind(a.get("name", ""))]
    if not candidates:
        raise Refused("release has no archive, .dll or plugin asset (source-only release: build it, this tool "
                      "does not); assets: " + (", ".join(a.get("name", "?") for a in assets) or "none"))
    if len(candidates) > 1:
        raise Refused("several installable assets, pick one with --asset: "
                      + ", ".join(a["name"] for a in candidates))
    return candidates[0]


def companions(assets: list[dict], main: dict) -> list[dict]:
    """Assets sharing the .dll's stem with a companion extension (MyPlugin.pdb, MyPlugin.ini)."""
    stem = Path(main["name"]).stem.lower()
    return [a for a in assets if a is not main and Path(a.get("name", "")).stem.lower() == stem
            and a.get("name", "").lower().endswith(COMPANION_EXTS)]


def download(asset: dict) -> bytes:
    url = asset.get("browser_download_url") or ""
    if urllib.parse.urlparse(url).scheme != "https":
        raise Failed(f"asset {asset.get('name')!r} has no https download URL")
    try:
        with urllib.request.urlopen(_request(url, "application/octet-stream"), timeout=120) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise Failed(f"download failed for {asset.get('name')!r}: {exc}") from None
    verify(asset, data)
    return data


def verify(asset: dict, data: bytes) -> str:
    size = asset.get("size")
    if isinstance(size, int) and size != len(data):
        raise Failed(f"{asset.get('name')!r}: got {len(data)} bytes, GitHub lists {size}")
    sha = hashlib.sha256(data).hexdigest()
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:") and digest[7:].lower() != sha:
        raise Failed(f"{asset.get('name')!r}: SHA-256 {sha} does not match GitHub's {digest}")
    return sha


# ---------------------------------------------------------------- packaging

def safe_component(name: str) -> str:
    base = Path(name).name
    if not base or base in (".", "..") or base != name.replace("\\", "/").split("/")[-1]:
        raise Refused(f"unsafe asset name {name!r}")
    return base


def wrap(kind: str, files: list[tuple[str, bytes]], meta_ini: str) -> bytes:
    """A deterministic zip: a .dll (and companions) under SKSE/Plugins/, a plugin at the root, plus meta.ini."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            arc = ("SKSE/Plugins/" + name) if kind == "dll" else name
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
        info = zipfile.ZipInfo("meta.ini", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, meta_ini)
    return buf.getvalue()


def zip_top_level(data: bytes) -> list[str] | None:
    """Top-level entries of a zip, or None when it is not a zip (7z/rar are not listed)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return sorted({n.replace("\\", "/").split("/", 1)[0] for n in zf.namelist() if n.strip("/")})
    except zipfile.BadZipFile:
        return None


def looks_installable(top: list[str]) -> bool:
    return any(t.lower() in DATA_DIRS or t.lower().endswith(DATA_FILE_EXTS) for t in top)


# ---------------------------------------------------------------- output folder

def downloads_dir() -> Path:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                            ("d4", ctypes.c_ubyte * 8)]

            # FOLDERID_Downloads {374DE290-123F-4565-9164-39C4925E467B}
            fid = GUID(0x374DE290, 0x123F, 0x4565, (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path:
                    return Path(path)
        except (OSError, AttributeError):
            pass
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"
    if sys.platform != "darwin":
        dirs = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs"
        try:
            for line in dirs.read_text(encoding="utf-8").splitlines():
                m = re.fullmatch(r'\s*XDG_DOWNLOAD_DIR\s*=\s*"(.*)"\s*', line)
                if m:
                    return Path(m.group(1).replace("$HOME", str(Path.home())))
        except OSError:
            pass
    return Path.home() / "Downloads"


def protected_roots() -> list[Path]:
    """The game folder and the MO2 instance (mods/, overwrite/ and the instance holding downloads/)."""
    keys = ("SKYRIM_GAME_ROOT", "SKYRIM_MO2_MODS", "SKYRIM_MO2_OVERWRITE")
    values = {k: os.environ.get(k, "") for k in keys}
    if not all(values.values()):
        try:
            from skyguard import paths as sg_paths
            config = sg_paths.read_install(str(TOOLKIT), os.environ)
            for k in keys:
                values[k] = values[k] or config.first(k)
        except Exception:  # unconfigured toolkit: nothing known to protect beyond the env
            pass
    roots: list[Path] = []
    for key, value in values.items():
        if not value:
            continue
        p = Path(value)
        roots.append(p)
        if key != "SKYRIM_GAME_ROOT" and p.name.lower() in ("mods", "overwrite"):
            roots.append(p.parent)  # the MO2 instance, which holds downloads/ and profiles/
    return roots


def _resolved(p: Path) -> str:
    try:
        return os.path.normcase(str(p.resolve()))
    except OSError:
        return os.path.normcase(os.path.abspath(str(p)))


def check_out_dir(out: Path) -> None:
    target = _resolved(out)
    for root in protected_roots():
        r = _resolved(root)
        if target == r or target.startswith(r.rstrip("\\/") + os.sep):
            raise Refused(f"--out {out} is inside {root}: write to a folder outside the game and the MO2 instance, "
                          "then install with MO2's 'Install a new mod from archive'")


def write_new(path: Path, data: bytes, force: bool) -> None:
    if path.exists() and not force:
        raise Refused(f"{path} exists; pass --force to replace it")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".ghfetch_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- main

def plan(args: argparse.Namespace) -> dict:
    owner, repo = parse_repo(args.repo)
    if args.mod_category is None or args.mod_category <= 0:
        raise Refused("--mod-category must be a Nexus mod category id > 0 "
                      "(list: bash tools/nexus.sh raw /games/skyrimspecialedition.json)")
    release = get_release(owner, repo, args.tag)
    tag = release.get("tag_name") or ""
    version = tag_version(tag)
    assets = release.get("assets") or []
    main = pick_asset(assets, args.asset)
    kind = asset_kind(main["name"])
    name = safe_component(main["name"])
    extra = companions(assets, main) if kind == "dll" else []
    archive = name if kind == "archive" else f"{repo}-{version}.zip"
    return {"owner": owner, "repo": repo, "tag": tag, "version": version, "release": release, "main": main,
            "kind": kind, "extra": extra, "archive": safe_component(archive),
            "repo_url": f"https://github.com/{owner}/{repo}"}


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="github-mod-fetch", description=__doc__.split("\n\n")[0])
    ap.add_argument("repo")
    ap.add_argument("--mod-category", type=int, default=None)
    ap.add_argument("--tag")
    ap.add_argument("--asset")
    ap.add_argument("--file-category", choices=sorted(FILE_CATEGORY_IDS), default="main")
    ap.add_argument("--nexus-id", type=int, default=0)
    ap.add_argument("--name")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    try:
        p = plan(args)
        out = args.out or downloads_dir()
        check_out_dir(out)
        archive_path = out / p["archive"]
        meta_path = archive_path.with_name(archive_path.name + ".meta")
        meta = download_meta(mod_id=args.nexus_id, mod_name=args.name or p["repo"], version=p["version"],
                             file_category=FILE_CATEGORY_IDS[args.file_category], mod_category=args.mod_category,
                             file_name=p["main"]["name"])
        print(f"release   {p['owner']}/{p['repo']} {p['tag']} -> version {p['version']}")
        print(f"asset     {p['main']['name']} ({p['kind']}, {p['main'].get('size', '?')} bytes)"
              + "".join(f" + {a['name']}" for a in p["extra"]))
        layout = {"dll": "SKSE/Plugins/ + meta.ini", "plugin": "zip root + meta.ini", "archive": "kept as published"}
        print(f"archive   {archive_path}  [{layout[p['kind']]}]")
        print(f"meta      {meta_path}")
        if args.dry_run:
            print("\n--- .meta (dry run, nothing downloaded or written) ---")
            print(meta.replace("\r\n", "\n"), end="")
            return 0
        if not args.force:
            for path in (archive_path, meta_path):
                if path.exists():
                    raise Refused(f"{path} exists; pass --force to replace it")
        data = download(p["main"])
        if p["kind"] == "archive":
            payload = data
            top = zip_top_level(data)
            if top is None:
                print("note      not a zip; top level not listed (open it in MO2 to check)")
            else:
                print("contents  " + ", ".join(top))
                if not looks_installable(top):
                    print("WARNING   no data folder or plugin at the top level: MO2 will ask you to set the data "
                          "root in its manual installer")
        else:
            files = [(safe_component(p["main"]["name"]), data)]
            files += [(safe_component(a["name"]), download(a)) for a in p["extra"]]
            ini = bundled_meta_ini(version=p["version"], repo_url=p["repo_url"], mod_id=args.nexus_id)
            payload = wrap(p["kind"], files, ini)
        out.mkdir(parents=True, exist_ok=True)
        write_new(archive_path, payload, args.force)
        write_new(meta_path, meta.encode("utf-8"), args.force)
        print(f"sha256    {hashlib.sha256(data).hexdigest()}  {p['main']['name']}")
        print("next      MO2 > Install a new mod from archive > pick the archive above (keep the .meta beside it)")
        return 0
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except Failed as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run())
