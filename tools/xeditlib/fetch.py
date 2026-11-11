#!/usr/bin/env python3
"""Fetch the pinned xeditlib JS wrapper and native libraries onto THIS machine.

    python tools/xeditlib/fetch.py [--check] [--force]

Downloads the pinned upstream commit archive from GitHub, extracts in memory,
verifies each file against a pinned SHA-256 manifest, and installs the package files
atomically into tools/xeditlib/lib/.

Flags:
  --check  verify an existing install against the manifest, no network, exit 0/1.
  --force  refetch and reinstall even if already installed.

Exit: 0 on success, non-zero on error or mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import tarfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
PACKAGE = HERE / "lib"

REPO = "https://github.com/kxgcayh/xeditlib"
COMMIT = "96326630099662f14578d273d40b7d9cf7220277"
VERSION = "1.1.0"
URL = f"https://codeload.github.com/kxgcayh/xeditlib/tar.gz/{COMMIT}"

MANIFEST = {
    "Fallout3.Hardcoded.dat": "ff685663e55cd455d4bffe3ff6ef223eb21874c835bfa8d2006d1063f3ff50e9",
    "Fallout4.Hardcoded.dat": "ef95f923a19f74fed579f79c047e312c33ba468aa03d532aad7ec8b44503bea4",
    "FalloutNV.Hardcoded.dat": "b65cedf647abe2b1e4b8c184a6b101cdfd721ab5651b4185a556eea2a0a9b72b",
    "LICENSE": "07a5c5e4aac6c4eda67565a716c8f4967dc318abe03098e5dee6a8fa7672d619",
    "Oblivion.Hardcoded.dat": "8eac9b94562428558454e3840445a5d65a0fd5a8cba0a137965b9c37c626223e",
    "README.md": "fae867843889b7d404a4c510e46aee8175a9bcafabfdef96151dcd89162221ba",
    "Skyrim.Hardcoded.dat": "0e8e506d458dca083087ef0411cbb9335dc9c0bbb7033e006fffa01a6e3d9f68",
    "THIRD_PARTY_NOTICES.txt": "708c90667bcce00c2d7b82f530e14f61d20055d6e4d52677ec777307ae82a9cd",
    "XEditLib.dll": "5599144df4138b65541fa5296ef8fbf3acc73ca821ab1296496af77370055648",
    "cli.js": "0d8ad56eebcab72a9858b1cc23cbeed030548b22a9d92fb8d331897e00f85e55",
    "esp.js": "74baeceed1d37d2547ab6a9bd044ab8839bd3c6a4291ce8773c4905d12e28285",
    "icudtl.dat": "02db39ba465fc8b7a4cd280732760f29911edde87b331bf7cea7677e94d483e0",
    "libXEditLib.dylib": "373547cd0f18173607b01e65ab287096985a0938422bcdf1a7609b6ea8b4f36a",
    "package.json": "81f174c8d57467d83d45a2fe9b6b2ab7576965290afb238766ba55fdf1e68a2d",
    "paths.js": "f9dc436d75bb4d1ef8943f0d7843dbf36dcb417d438c1645ed32a0360d991460",
    "xelib.js": "bc1f6209fcd0a4ae7bb3f069e64521c8d156619f3c02edc688f377bba0fad07d",
}

SKIPPED_PREFIXES = ("tests/", "examples/")
SKIPPED_FILES = (".gitignore", "package-lock.json")


class FetchError(Exception):
    pass


def download(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "skyrim-ai-assistant-toolkit-xeditlib-fetch/1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def verify_archive(data: bytes) -> dict[str, bytes]:
    """Extract and verify tar.gz bytes in memory. Returns {relpath: bytes} on success, raises FetchError on failure."""
    try:
        fileobj = io.BytesIO(data)
        tar = tarfile.open(fileobj=fileobj, mode="r:gz")
    except Exception as e:
        raise FetchError(f"archive extraction failed: {e}")

    extracted: dict[str, bytes] = {}
    with tar:
        for member in tar.getmembers():
            norm_name = member.name.replace("\\", "/")
            rel = PurePosixPath(norm_name)

            if rel.is_absolute():
                raise FetchError(f"archive contains absolute path: {member.name}")
            if ".." in rel.parts:
                raise FetchError(f"archive contains path traversal (..): {member.name}")
            if member.issym() or member.islnk():
                raise FetchError(f"archive contains link (symlink/hardlink): {member.name}")

            # Strip the top directory (e.g. xeditlib-<commit>/...)
            if len(rel.parts) <= 1:
                continue

            subpath = str(PurePosixPath(*rel.parts[1:]))

            if member.isdir():
                continue

            # Check if this member is skipped
            if any(subpath.startswith(prefix) for prefix in SKIPPED_PREFIXES) or subpath in SKIPPED_FILES:
                continue

            f = tar.extractfile(member)
            if f is None:
                raise FetchError(f"failed to extract file: {member.name}")
            content = f.read()

            extracted[subpath] = content

    # Verify extracted files against MANIFEST
    for fname, expected_hash in MANIFEST.items():
        if fname not in extracted:
            raise FetchError(f"missing manifest file in archive: {fname}")
        got_hash = hashlib.sha256(extracted[fname]).hexdigest()
        if got_hash != expected_hash:
            raise FetchError(
                f"hash mismatch for {fname}: expected {expected_hash}, got {got_hash}"
            )

    # Check for unexpected files in extracted package
    for fname in extracted:
        if fname not in MANIFEST:
            raise FetchError(f"unexpected unmanifested file in archive: {fname}")

    return extracted


def check_install(dest: Path = PACKAGE) -> tuple[bool, str]:
    """Verify an existing install against the pinned manifest. Returns (True, "") or (False, reason)."""
    if not dest.is_dir():
        return False, f"destination directory {dest} does not exist"

    meta_file = dest / "fetched.json"
    if not meta_file.is_file():
        return False, f"missing fetched.json metadata in {dest}"

    for fname, expected_hash in MANIFEST.items():
        target = dest / fname
        if not target.is_file():
            return False, f"missing file: {fname}"
        got_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if got_hash != expected_hash:
            return False, f"hash mismatch for {fname}: expected {expected_hash}, got {got_hash}"

    return True, ""


def install(files: dict[str, bytes], dest: Path = PACKAGE) -> None:
    """Write package files and fetched.json into a staging directory, then replace dest atomically."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="stage-", dir=str(dest.parent)))
    try:
        for rel, body in files.items():
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)

        meta = {
            "repo": REPO,
            "commit": COMMIT,
            "version": VERSION,
            "files": MANIFEST,
            "hashes": MANIFEST,
        }
        (stage / "fetched.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        if dest.exists():
            shutil.rmtree(str(dest), ignore_errors=True)
        os.replace(str(stage), str(dest))
    finally:
        if stage.exists():
            shutil.rmtree(str(stage), ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch and verify xeditlib")
    parser.add_argument("--check", action="store_true", help="verify existing install against manifest")
    parser.add_argument("--force", action="store_true", help="force refetch and reinstall")
    args = parser.parse_args(argv)

    if args.check:
        ok, reason = check_install(PACKAGE)
        if not ok:
            print(f"ERROR: {reason}", file=sys.stderr)
            return 1
        print(f"verified {PACKAGE} against pinned manifest ({len(MANIFEST)} files)")
        return 0

    if not args.force:
        ok, _ = check_install(PACKAGE)
        if ok:
            print(f"already installed and verified in {PACKAGE}")
            return 0

    try:
        data = download(URL)
        files = verify_archive(data)
        install(files, PACKAGE)
    except (FetchError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"fetched and verified {PACKAGE} ({len(MANIFEST)} files, commit {COMMIT[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
