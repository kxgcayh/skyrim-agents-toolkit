#!/usr/bin/env python3
"""nexus-download.py -- the file list and the one-file download behind `nexus.sh files` / `nexus.sh download`.

    nexus-download.py --list                 < files.json        print file ids, versions, categories, sizes
    nexus-download.py <output file or dir>   < download_link.json  (env INFO = the file's files/<id>.json)

The mirror list arrives on STDIN, never in argv or the environment: its URLs are signed for the account and must not
be readable from a process listing. They are never printed either. A download is written to a temporary file in the
destination folder and moved into place only when it is complete and its size matches what Nexus lists for the file;
an existing destination is never overwritten. Ported from the Moonlight Peaks modding toolkit's downloader (MIT, same
author), with the toolkit's own User-Agent instead of a browser one (tests/test_nexus.py pins that rule).

Exit codes: 0 done, 2 bad usage or destination, 3 could not check (bad response, or no mirror completed).
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "skyrim-ai-assistant-toolkit-nexus/1 (+https://github.com/WingedGuardian/skyrim-ai-assistant-toolkit)"
MAX_BYTES = 4 * 1024 * 1024 * 1024
CHUNK = 1024 * 1024
UMASK = os.umask(0)
os.umask(UMASK)


def err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def list_files(payload) -> int:
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        err("invalid Nexus file-list response.")
        return 3
    rows = [f for f in files if isinstance(f, dict)]
    rows.sort(key=lambda f: f.get("uploaded_timestamp") or 0, reverse=True)
    for f in rows:
        kb = f.get("size_kb")
        size = f"{kb} KB" if isinstance(kb, int) else "? KB"
        print("ID: {} | {} | v{} | {} | {} | {} | {}".format(
            f.get("file_id", "?"), f.get("name") or "?", f.get("version") or "?",
            f.get("category_name") or "?", size, (f.get("uploaded_time") or "?")[:10], f.get("file_name") or "?"))
    print(f"LISTED: {len(rows)} file(s)")
    print("RESULT: OK")
    return 0


def safe_name(name) -> str | None:
    if not isinstance(name, str) or not name or name in (".", ".."):
        return None
    if any(c in name for c in "/\\\0:") or name.strip() != name:
        return None
    return name


def resolve_target(arg: str, info: dict) -> Path | None:
    target = Path(arg).expanduser()
    if target.is_dir():
        name = safe_name(info.get("file_name"))
        if name is None:
            err("Nexus gave no usable file name; pass an output file path instead of a folder.")
            return None
        target = target / name
    if target.exists() or target.is_symlink():
        err(f"destination already exists, not overwritten: {target}")
        return None
    if not target.parent.is_dir():
        err(f"destination folder does not exist: {target.parent}")
        return None
    return target


def fetch(url: str, temp: Path, expected: int | None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        if urllib.parse.urlsplit(resp.geturl()).scheme != "https":
            raise ValueError("redirected off HTTPS")
        if resp.headers.get_content_type() == "text/html":
            raise ValueError("the server returned an HTML page, not the file")
        length = resp.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES:
            raise ValueError("file exceeds the size limit")
        total, digest = 0, hashlib.sha256()
        with open(temp, "wb") as out:
            while chunk := resp.read(CHUNK):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("file exceeds the size limit")
                digest.update(chunk)
                out.write(chunk)
    if total == 0 or (length and total != int(length)):
        raise ValueError("empty or incomplete download")
    if expected is not None and total != expected:
        raise ValueError(f"size {total} differs from the {expected} bytes Nexus lists for this file")
    return total, digest.hexdigest()


def download(arg: str, mirrors, info: dict) -> int:
    if not isinstance(mirrors, list):
        err("invalid Nexus mirror response.")
        return 3
    target = resolve_target(arg, info)
    if target is None:
        return 2
    expected = info.get("size_in_bytes")
    expected = expected if isinstance(expected, int) and expected > 0 else None
    # Reserve the name first (O_EXCL), so a file that appears meanwhile is never overwritten; os.replace then swaps
    # the finished temp file onto our own empty placeholder. Works where hard links do not (FAT, exFAT, SMB).
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        os.close(fd)
    except FileExistsError:
        err(f"destination already exists, not overwritten: {target}")
        return 2
    except OSError as exc:
        err(f"cannot create the destination ({type(exc).__name__}).")
        return 2
    done = False
    try:
        for index, mirror in enumerate(mirrors, 1):
            url = mirror.get("URI") if isinstance(mirror, dict) else None
            if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme != "https":
                continue
            fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".nexus-download-")
            os.close(fd)
            temp = Path(tmp)
            try:
                total, sha = fetch(url, temp, expected)
                os.chmod(temp, 0o666 & ~UMASK)  # mkstemp makes it 0600; give the saved file the user's normal mode
                os.replace(temp, target)
                done = True
                print(f"Downloaded: {target} ({total} bytes)")
                print(f"SHA-256: {sha}")
                print("RESULT: OK")
                return 0
            except (OSError, ValueError, http.client.HTTPException) as exc:
                status = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else (
                    str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
                name = mirror.get("short_name") if isinstance(mirror.get("short_name"), str) else f"mirror {index}"
                print(f"Mirror {index} ({name}) failed: {status}", file=sys.stderr)
            finally:
                temp.unlink(missing_ok=True)
        err("no mirror completed the download.")
        return 3
    finally:
        if not done:
            target.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: nexus-download.py --list | <output file or folder>", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
    except (ValueError, UnicodeDecodeError):
        err("the Nexus response is not JSON.")
        return 3
    if argv[0] == "--list":
        return list_files(payload)
    try:
        info = json.loads(os.environ.get("INFO") or "{}")
    except ValueError:
        info = {}
    if not isinstance(info, dict):
        info = {}
    return download(argv[0], payload, info)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
