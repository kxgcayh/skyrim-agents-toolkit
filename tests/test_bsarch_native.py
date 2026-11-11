"""tools/bsarch-native: build.py (pins, platform, compiler and lz4 discovery, --check) and the built `bsarch` binary.

BSArch is a Windows program that AutoMod's `archive` module starts for `create` (pack) and `extract` (unpack). On macOS
and Linux the toolkit builds a native stand-in from pinned source. The unit tests need no compiler. The binary tests run
only when `python tools/bsarch-native/build.py` has been run on this machine, and say so when they skip.
"""
from __future__ import annotations

import importlib.util
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "bsarch_native_build", Path(__file__).resolve().parent.parent / "tools" / "bsarch-native" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def _install(tmp_path: Path, pins: dict | None = None, sources: dict | None = None, body: bytes = b"binary") -> Path:
    dest = tmp_path / "bin"
    dest.mkdir()
    (dest / "bsarch").write_bytes(body)
    meta = {"pins": pins or {n: c for n, (_, c) in build.PINS.items()}, "sources": sources or build.source_hashes(),
            "binary": "bsarch", "sha256": build.sha256(dest / "bsarch")}
    (dest / "fetched.json").write_text(json.dumps(meta), encoding="utf-8")
    return dest


# --- build.py ------------------------------------------------------------------------------------

def test_the_pins_are_full_commit_ids():
    for name, (repo, commit) in build.PINS.items():
        assert repo.startswith("https://github.com/") and len(commit) == 40 and int(commit, 16) >= 0, name


def test_windows_is_refused_because_it_has_the_real_bsarch_exe():
    with pytest.raises(build.BuildError, match="Windows"):
        build.check_platform("Windows")
    build.check_platform("Darwin")
    build.check_platform("Linux")


def test_the_compiler_is_cxx_when_set_and_apples_clang_on_macos(tmp_path):
    assert build.pick_compiler({"CXX": "/x/mine"}, "Darwin") == "/x/mine"
    if Path("/usr/bin/clang++").is_file():
        # A Homebrew LLVM clang++ first on PATH failed against the macOS SDK (MEASURED 2026-11-12).
        assert build.pick_compiler({}, "Darwin") == "/usr/bin/clang++"


def test_static_lz4_is_found_under_a_prefix_and_a_miss_says_how_to_install(tmp_path):
    prefix = tmp_path / "p"
    (prefix / "include").mkdir(parents=True)
    (prefix / "lib").mkdir()
    (prefix / "include" / "lz4frame.h").write_text("", encoding="utf-8")
    (prefix / "lib" / "liblz4.a").write_bytes(b"!<arch>\n")
    assert build.find_static_lz4([tmp_path / "nowhere", prefix]) == (prefix / "lib" / "liblz4.a", prefix / "include")
    with pytest.raises(build.BuildError, match="brew install lz4"):
        build.find_static_lz4([tmp_path / "nowhere"])


def test_a_dynamic_only_lz4_is_not_accepted(tmp_path):
    (tmp_path / "include").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "include" / "lz4frame.h").write_text("", encoding="utf-8")
    (tmp_path / "lib" / "liblz4.dylib").write_bytes(b"x")
    with pytest.raises(build.BuildError):
        build.find_static_lz4([tmp_path])


def test_check_good(tmp_path):
    assert build.check_install(_install(tmp_path)) == (True, "")


def test_check_missing(tmp_path):
    ok, reason = build.check_install(tmp_path / "bin")
    assert not ok and "fetched.json" in reason


def test_check_a_stale_pin(tmp_path):
    pins = {n: c for n, (_, c) in build.PINS.items()}
    pins["mmio"] = "0" * 40
    ok, reason = build.check_install(_install(tmp_path, pins=pins))
    assert not ok and "mmio" in reason and "pinned" in reason


def test_check_a_shim_or_patch_changed_since_the_build(tmp_path):
    sources = dict(build.source_hashes())
    sources["shim"] = "0" * 64
    ok, reason = build.check_install(_install(tmp_path, sources=sources))
    assert not ok and "shim changed" in reason and "--force" in reason


def test_check_tampered(tmp_path):
    dest = _install(tmp_path)
    (dest / "bsarch").write_bytes(b"changed")
    ok, reason = build.check_install(dest)
    assert not ok and "hash mismatch" in reason


def test_check_only_never_builds(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "BIN", tmp_path / "bin")
    monkeypatch.setattr(build, "build", lambda dest: pytest.fail("--check must not build"))
    assert build.main(["--check"]) == 1


# --- the binary ----------------------------------------------------------------------------------

BINARY = build.BIN / "bsarch"
needs_binary = pytest.mark.skipif(
    sys.platform == "win32" or not BINARY.is_file() or not build.check_install(build.BIN)[0],
    reason="build it first: python tools/bsarch-native/build.py")


def _bsarch(*args: str):
    return subprocess.run([str(BINARY), *args], capture_output=True, text=True, timeout=60)


def _craft(path: Path, folder: str, name: str, data: bytes) -> None:
    """A minimal uncompressed v105 archive with one folder and one file; the hashes are zero (the reader ignores them)."""
    fbz = bytes([len(folder) + 1]) + folder.encode() + b"\0"
    names = name.encode() + b"\0"
    folders_at = 36
    block_at = folders_at + 24
    data_at = block_at + len(fbz) + 16 + len(names)
    head = struct.pack("<4sIIIIIIII", b"BSA\0", 105, 36, 3, 1, 1, len(folder) + 1, len(names), 0)
    folder_rec = struct.pack("<QIIQ", 0, 1, 0, block_at + len(names))
    file_rec = struct.pack("<QII", 0, len(data), data_at)
    path.write_bytes(head + folder_rec + fbz + file_rec + names + data)


@needs_binary
def test_pack_then_unpack_round_trips_and_writes_a_compressed_v105_archive(tmp_path):
    tree = tmp_path / "in"
    files = {"meshes/a/one.nif": b"n" * 5000, "scripts/Two.pex": bytes(range(256)) * 9, "sound/fx/t.wav": b"w" * 70000}
    for rel, data in files.items():
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_bytes(data)
    archive = tmp_path / "out.bsa"
    done = _bsarch("pack", str(tree), str(archive), "-sse", "-z", "-mt")
    assert done.returncode == 0, done.stderr
    magic, version, _, flags = struct.unpack("<4sIII", archive.read_bytes()[:16])
    assert magic == b"BSA\0" and version == 105 and flags & 4
    out = tmp_path / "back"
    assert _bsarch("unpack", str(archive), str(out)).returncode == 0
    for rel, data in files.items():
        assert (out / rel.lower()).read_bytes() == data, rel


@needs_binary
def test_tes5_writes_version_104_and_no_z_writes_no_compression_flag(tmp_path):
    tree = tmp_path / "in" / "d"
    tree.mkdir(parents=True)
    (tree / "f.txt").write_bytes(b"x" * 100)
    archive = tmp_path / "o.bsa"
    assert _bsarch("pack", str(tmp_path / "in"), str(archive), "-tes5").returncode == 0
    _, version, _, flags = struct.unpack("<4sIII", archive.read_bytes()[:16])
    assert version == 104 and not flags & 4


@needs_binary
def test_unpack_without_an_outdir_goes_to_a_folder_named_for_the_archive(tmp_path):
    archive = tmp_path / "Mod Name.bsa"
    _craft(archive, "meshes\\x", "a.nif", b"data")
    assert _bsarch("unpack", str(archive)).returncode == 0
    assert (tmp_path / "Mod Name" / "meshes" / "x" / "a.nif").read_bytes() == b"data"


@needs_binary
def test_the_crafted_archive_reader_is_valid_so_the_traversal_test_below_means_something(tmp_path):
    archive = tmp_path / "ok.bsa"
    _craft(archive, "meshes\\safe", "ok.nif", b"fine")
    out = tmp_path / "o"
    done = _bsarch("unpack", str(archive), str(out))
    assert done.returncode == 0, done.stderr
    assert (out / "meshes" / "safe" / "ok.nif").read_bytes() == b"fine"


@needs_binary
@pytest.mark.parametrize("folder", ["..\\..\\escape", "meshes\\..\\..\\escape", "C:\\Windows\\x", "\\abs\\x"])
def test_an_archive_entry_that_would_leave_the_output_folder_is_refused(tmp_path, folder):
    """A BSA from a third-party mod must not write outside the folder the caller chose."""
    archive = tmp_path / "evil.bsa"
    _craft(archive, folder, "pwn.txt", b"owned")
    out = tmp_path / "deep" / "out"
    done = _bsarch("unpack", str(archive), str(out))
    assert done.returncode == 1 and "unsafe path" in done.stderr, done.stderr
    assert not list(tmp_path.rglob("pwn.txt")), "a file was written"


@needs_binary
@pytest.mark.parametrize("args", [[], ["frob", "a", "b"], ["pack", "x"], ["unpack", "/nonexistent/none.bsa", "/tmp/never"]])
def test_a_bad_command_line_exits_1_with_a_message(args):
    done = _bsarch(*args)
    assert done.returncode == 1 and done.stderr.strip(), (args, done.stdout, done.stderr)


@needs_binary
def test_a_file_directly_in_the_pack_folder_is_refused_not_silently_dropped(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "loose.txt").write_text("x", encoding="utf-8")
    done = _bsarch("pack", str(tmp_path / "in"), str(tmp_path / "o.bsa"), "-sse")
    assert done.returncode == 1 and "root" in done.stderr
