#!/usr/bin/env python3
"""Build the pinned Spriggit fork (kxgcayh/Spriggit) on THIS machine.

    python tools/spriggit-fork/fetch.py [--check] [--force]

Fetches exactly the pinned commit with git (depth 1), refuses to build unless HEAD equals the pin
(git object hashes make that a content check), publishes a self-contained single-file CLI for this
platform with the .NET 10 SDK, and installs it atomically into tools/spriggit-fork/bin/.

Flags:
  --check  verify an existing install (pinned commit, binary SHA-256 from fetched.json), no network.
  --force  rebuild and reinstall even if already installed.

Exit: 0 on success, non-zero on error or mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE / "bin"

REPO = "https://github.com/kxgcayh/Spriggit.git"
BRANCH = "audit-fixes"
COMMIT = "90e6fc550e2f04b6a424c70ce57d9ad713da3255"
VERSION = "0.1.0-audit-fixes"


class FetchError(Exception):
    pass


def rid(system: str | None = None, machine: str | None = None) -> str:
    """.NET runtime identifier for this platform."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    os_part = {"darwin": "osx", "linux": "linux", "windows": "win"}.get(system)
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(machine)
    if not os_part or not arch:
        raise FetchError(f"unsupported platform: {system}/{machine}")
    return f"{os_part}-{arch}"


def binary_name(runtime: str) -> str:
    return "Spriggit.CLI.exe" if runtime.startswith("win-") else "Spriggit.CLI"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], cwd: Path) -> str:
    try:
        done = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    except FileNotFoundError:
        raise FetchError(f"{cmd[0]} not found on PATH")
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-15:])
        raise FetchError(f"{' '.join(cmd[:3])} failed (exit {done.returncode}):\n{tail}")
    return done.stdout


def check_install(dest: Path = BIN) -> tuple[bool, str]:
    """Verify an existing install. Returns (True, "") or (False, reason)."""
    meta_file = dest / "fetched.json"
    if not meta_file.is_file():
        return False, f"missing {meta_file}"
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except ValueError as e:
        return False, f"unreadable fetched.json: {e}"
    if meta.get("commit") != COMMIT:
        return False, f"installed commit {meta.get('commit')} is not the pinned {COMMIT}"
    binary = dest / str(meta.get("binary", ""))
    if not meta.get("binary") or not binary.is_file():
        return False, f"missing binary {binary}"
    if sha256(binary) != meta.get("sha256"):
        return False, f"hash mismatch for {binary.name}: the binary changed after the build"
    return True, ""


def build(dest: Path = BIN) -> Path:
    runtime = rid()
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="build-", dir=str(dest.parent)))
    try:
        src = work / "src"
        src.mkdir()
        run(["git", "init", "-q"], src)
        run(["git", "fetch", "-q", "--depth", "1", REPO, COMMIT], src)
        run(["git", "checkout", "-q", "FETCH_HEAD"], src)
        head = run(["git", "rev-parse", "HEAD"], src).strip()
        if head != COMMIT:
            raise FetchError(f"fetched HEAD {head} is not the pinned {COMMIT}")

        stage = work / "bin"
        cpus = max(1, (os.cpu_count() or 2) // 2)  # stay well under the 80% machine budget
        run([
            "dotnet", "publish", "Spriggit.CLI", "-c", "Release", "-r", runtime,
            "--self-contained", "true", "-p:PackAsTool=false", "-p:PublishSingleFile=true",
            # GitVersion needs full history; a depth-1 clone has none, so the version is set here.
            "-p:DisableGitVersionTask=true", f"-p:Version={VERSION}", f"-maxcpucount:{cpus}",
            "-o", str(stage),
        ], src)

        binary = stage / binary_name(runtime)
        if not binary.is_file():
            raise FetchError(f"publish produced no {binary.name}")
        meta = {"repo": REPO, "branch": BRANCH, "commit": COMMIT, "version": VERSION,
                "rid": runtime, "binary": binary.name, "sha256": sha256(binary)}
        (stage / "fetched.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

        if dest.exists():
            shutil.rmtree(str(dest))
        os.replace(str(stage), str(dest))
        return dest / binary.name
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the pinned Spriggit fork")
    parser.add_argument("--check", action="store_true", help="verify an existing install, no network")
    parser.add_argument("--force", action="store_true", help="rebuild and reinstall")
    args = parser.parse_args(argv)

    if args.check or not args.force:
        ok, reason = check_install(BIN)
        if args.check:
            if not ok:
                print(f"ERROR: {reason}", file=sys.stderr)
                return 1
            print(f"verified {BIN} (commit {COMMIT[:7]})")
            return 0
        if ok:
            print(f"already installed and verified in {BIN}")
            return 0

    try:
        binary = build(BIN)
    except (FetchError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"built {binary} (commit {COMMIT[:7]}, {rid()})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
