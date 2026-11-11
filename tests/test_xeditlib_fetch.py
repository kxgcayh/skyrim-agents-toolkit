"""Unit tests for tools/xeditlib/fetch.py (path traversal, manifest checks, --check on good/tampered)."""
from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "xeditlib"))
import fetch


def _create_tar_gz(members: list[dict[str, Any]]) -> bytes:
    """Build an in-memory tar.gz archive from a list of dicts describing members."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for m in members:
            name = m["name"]
            data = m.get("data", b"")
            ti = tarfile.TarInfo(name=name)
            if "type" in m:
                ti.type = m["type"]
                if ti.type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    ti.linkname = m.get("linkname", "target")
            else:
                ti.type = tarfile.REGTYPE
                ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data) if ti.type == tarfile.REGTYPE else None)
    return buf.getvalue()


def test_path_traversal_rejection_dot_dot():
    bad_tar = _create_tar_gz([
        {"name": "xeditlib-commit/../evil.txt", "data": b"evil"},
    ])
    with pytest.raises(fetch.FetchError, match="path traversal"):
        fetch.verify_archive(bad_tar)


def test_path_traversal_rejection_absolute_path():
    bad_tar = _create_tar_gz([
        {"name": "/etc/evil.txt", "data": b"evil"},
    ])
    with pytest.raises(fetch.FetchError, match="absolute path"):
        fetch.verify_archive(bad_tar)


def test_symlink_rejection():
    bad_tar = _create_tar_gz([
        {"name": "xeditlib-commit/symlink.txt", "type": tarfile.SYMTYPE, "linkname": "target"},
    ])
    with pytest.raises(fetch.FetchError, match="link"):
        fetch.verify_archive(bad_tar)


def test_hardlink_rejection():
    bad_tar = _create_tar_gz([
        {"name": "xeditlib-commit/hardlink.txt", "type": tarfile.LNKTYPE, "linkname": "target"},
    ])
    with pytest.raises(fetch.FetchError, match="link"):
        fetch.verify_archive(bad_tar)


def test_manifest_mismatch_corrupted_hash():
    # Build a tar containing all manifest files with dummy content (hash mismatch)
    members = []
    for fname in fetch.MANIFEST:
        members.append({"name": f"xeditlib-commit/{fname}", "data": b"corrupted content"})
    bad_tar = _create_tar_gz(members)
    with pytest.raises(fetch.FetchError, match="hash mismatch"):
        fetch.verify_archive(bad_tar)


def test_manifest_mismatch_missing_file(monkeypatch: pytest.MonkeyPatch):
    dummy_manifest = {
        "file1.txt": hashlib.sha256(b"content1").hexdigest(),
        "file2.txt": hashlib.sha256(b"content2").hexdigest(),
    }
    monkeypatch.setattr(fetch, "MANIFEST", dummy_manifest)
    # Build a tar missing file2.txt
    members = [{"name": "xeditlib-commit/file1.txt", "data": b"content1"}]
    bad_tar = _create_tar_gz(members)
    with pytest.raises(fetch.FetchError, match="missing manifest file"):
        fetch.verify_archive(bad_tar)


def test_manifest_unexpected_file(monkeypatch: pytest.MonkeyPatch):
    dummy_manifest = {
        "file1.txt": hashlib.sha256(b"content1").hexdigest(),
    }
    monkeypatch.setattr(fetch, "MANIFEST", dummy_manifest)
    # Build a tar containing file1.txt plus unexpected file
    members = [
        {"name": "xeditlib-commit/file1.txt", "data": b"content1"},
        {"name": "xeditlib-commit/unexpected.dat", "data": b"surprise"},
    ]
    bad_tar = _create_tar_gz(members)
    with pytest.raises(fetch.FetchError, match="unexpected unmanifested file"):
        fetch.verify_archive(bad_tar)


def test_check_good_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup tmp_path with dummy files matching dummy manifest hashes
    dummy_manifest = {
        "file1.txt": hashlib.sha256(b"hello world").hexdigest(),
        "file2.js": hashlib.sha256(b"console.log('hi');").hexdigest(),
    }
    monkeypatch.setattr(fetch, "MANIFEST", dummy_manifest)
    monkeypatch.setattr(fetch, "PACKAGE", tmp_path)

    (tmp_path / "file1.txt").write_bytes(b"hello world")
    (tmp_path / "file2.js").write_bytes(b"console.log('hi');")
    meta = {
        "repo": fetch.REPO,
        "commit": fetch.COMMIT,
        "version": fetch.VERSION,
        "hashes": dummy_manifest,
    }
    (tmp_path / "fetched.json").write_text(json.dumps(meta), encoding="utf-8")

    ok, reason = fetch.check_install(tmp_path)
    assert ok is True
    assert reason == ""
    assert fetch.main(["--check"]) == 0


def test_check_tampered_install_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dummy_manifest = {
        "file1.txt": hashlib.sha256(b"hello world").hexdigest(),
        "file2.js": hashlib.sha256(b"console.log('hi');").hexdigest(),
    }
    monkeypatch.setattr(fetch, "MANIFEST", dummy_manifest)
    monkeypatch.setattr(fetch, "PACKAGE", tmp_path)

    (tmp_path / "file1.txt").write_bytes(b"hello world")
    # file2.js is missing
    (tmp_path / "fetched.json").write_text("{}", encoding="utf-8")

    ok, reason = fetch.check_install(tmp_path)
    assert ok is False
    assert "missing file: file2.js" in reason
    assert fetch.main(["--check"]) == 1


def test_check_tampered_install_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dummy_manifest = {
        "file1.txt": hashlib.sha256(b"hello world").hexdigest(),
    }
    monkeypatch.setattr(fetch, "MANIFEST", dummy_manifest)
    monkeypatch.setattr(fetch, "PACKAGE", tmp_path)

    (tmp_path / "file1.txt").write_bytes(b"tampered content")
    (tmp_path / "fetched.json").write_text("{}", encoding="utf-8")

    ok, reason = fetch.check_install(tmp_path)
    assert ok is False
    assert "hash mismatch for file1.txt" in reason
    assert fetch.main(["--check"]) == 1


def test_check_tampered_install_missing_fetched_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dummy_manifest = {"file1.txt": hashlib.sha256(b"hello world").hexdigest()}
    monkeypatch.setattr(fetch, "MANIFEST", dummy_manifest)
    monkeypatch.setattr(fetch, "PACKAGE", tmp_path)

    (tmp_path / "file1.txt").write_bytes(b"hello world")

    ok, reason = fetch.check_install(tmp_path)
    assert ok is False
    assert "missing fetched.json" in reason
    assert fetch.main(["--check"]) == 1


def test_check_nonexistent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    nonexistent = tmp_path / "no_such_dir"
    monkeypatch.setattr(fetch, "PACKAGE", nonexistent)

    ok, reason = fetch.check_install(nonexistent)
    assert ok is False
    assert "does not exist" in reason
    assert fetch.main(["--check"]) == 1
