"""mod-sizes: largest first, plugin-name search, separators and links left out, hidden rows counted."""

from __future__ import annotations

import os
import subprocess
import sys

from conftest import REPO

TOOL = REPO / "tools" / "mod-sizes.py"


def run(tmp_path, *args):
    return subprocess.run([sys.executable, str(TOOL), *args, "--mods", str(tmp_path / "mods"),
                           "--profile", str(tmp_path)], capture_output=True, text=True)


def setup(tmp_path):
    mods = tmp_path / "mods"
    (mods / "Big Land").mkdir(parents=True)
    (mods / "Big Land" / "BSHeartland.esm").write_bytes(b"x" * 3000)
    (mods / "Small").mkdir()
    (mods / "Small" / "a.txt").write_bytes(b"x" * 10)
    (mods / "Group_separator").mkdir()
    (tmp_path / "modlist.txt").write_text("+Big Land\n-Small\n-Group_separator\n")
    return mods


def test_largest_first_and_counts(tmp_path):
    setup(tmp_path)
    out = run(tmp_path).stdout
    assert out.index("Big Land") < out.index("Small")
    assert "Group_separator" not in out
    assert "2 mods" in out and "not shown: 0" in out


def test_search_matches_a_plugin_name(tmp_path):
    setup(tmp_path)
    out = run(tmp_path, "bsheartland").stdout
    assert "Big Land" in out and "Small" not in out


def test_enabled_filter_and_top_count_hidden_rows(tmp_path):
    setup(tmp_path)
    assert "Small" not in run(tmp_path, "--enabled").stdout
    out = run(tmp_path, "--top", "1").stdout
    assert "Small" not in out and "not shown: 1" in out


def test_links_are_not_followed(tmp_path):
    mods = setup(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"x" * 500000)
    os.symlink(outside, mods / "Small" / "link.bin")
    assert " 1 files" in run(tmp_path, "Small").stdout


def test_missing_folder_exits_2(tmp_path):
    assert run(tmp_path).returncode == 2
