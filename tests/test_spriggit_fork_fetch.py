"""Unit tests for tools/spriggit-fork/fetch.py (platform mapping, --check on good/tampered/stale installs)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "spriggit_fork_fetch", Path(__file__).resolve().parent.parent / "tools" / "spriggit-fork" / "fetch.py")
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)


def _install(tmp_path: Path, commit: str = fetch.COMMIT, body: bytes = b"binary") -> Path:
    dest = tmp_path / "bin"
    dest.mkdir()
    (dest / "Spriggit.CLI").write_bytes(body)
    meta = {"commit": commit, "binary": "Spriggit.CLI", "sha256": fetch.sha256(dest / "Spriggit.CLI")}
    (dest / "fetched.json").write_text(json.dumps(meta), encoding="utf-8")
    return dest


@pytest.mark.parametrize("system,machine,expected", [
    ("Darwin", "arm64", "osx-arm64"), ("Darwin", "x86_64", "osx-x64"),
    ("Linux", "aarch64", "linux-arm64"), ("Windows", "AMD64", "win-x64"),
])
def test_rid(system, machine, expected):
    assert fetch.rid(system, machine) == expected


def test_rid_unsupported():
    with pytest.raises(fetch.FetchError):
        fetch.rid("Plan9", "mips")


def test_binary_name():
    assert fetch.binary_name("win-x64") == "Spriggit.CLI.exe"
    assert fetch.binary_name("osx-arm64") == "Spriggit.CLI"


def test_check_good(tmp_path):
    assert fetch.check_install(_install(tmp_path)) == (True, "")


def test_check_missing(tmp_path):
    ok, reason = fetch.check_install(tmp_path / "bin")
    assert not ok and "fetched.json" in reason


def test_check_stale_commit(tmp_path):
    ok, reason = fetch.check_install(_install(tmp_path, commit="0" * 40))
    assert not ok and "pinned" in reason


def test_check_tampered(tmp_path):
    dest = _install(tmp_path)
    (dest / "Spriggit.CLI").write_bytes(b"changed")
    ok, reason = fetch.check_install(dest)
    assert not ok and "hash mismatch" in reason


def test_check_only_never_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "BIN", tmp_path / "bin")
    monkeypatch.setattr(fetch, "build", lambda dest: pytest.fail("--check must not build"))
    assert fetch.main(["--check"]) == 1
