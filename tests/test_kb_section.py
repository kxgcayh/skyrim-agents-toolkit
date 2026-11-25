import subprocess
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "kb-section.py"


@pytest.fixture
def kb(tmp_path):
    path = tmp_path / "KNOWLEDGEBASE.local.md"

    def run(data, *args, env=None):
        path.write_bytes(data)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--file", str(path), *args],
            capture_output=True, timeout=10, env=env,
        )

    return path, run


def test_listing(kb):
    _, run = kb
    first = "## First\né\n".encode("utf-8")
    second = b"## Second\nlast"
    data = b"Intro\n" + first + second
    result = run(data)
    assert result.returncode == 0
    assert result.stdout == (
        f"2  {len(first)}  First\n"
        f"4  {len(second)}  Second\n"
        f"Total: 2 sections, {len(data)} bytes\n"
    ).encode("utf-8")


@pytest.mark.parametrize("fence", [b"```python", b"~~~", b"  ````"])
def test_fences(kb, fence):
    _, run = kb
    closing = fence.strip().split(b"python")[0]
    shorter = b"```\n" if len(closing) == 4 else b""
    data = b"## Visible\n" + fence + b"\n## Hidden\n" + shorter + closing + b"\n## End\n"
    result = run(data)
    assert result.returncode == 0
    assert b"  Hidden\n" not in result.stdout
    assert b"  End\n" in result.stdout
    result = run(data, "Visible")
    assert b"## Hidden\n" in result.stdout


def test_multi_word_match_and_crlf(kb):
    _, run = kb
    body = "## Hook useful Candidates\r\névidence\r\n".encode("utf-8")
    result = run(body + b"## Hook only\r\nother\r\n", "HOOK", "candidates")
    assert result.returncode == 0
    assert result.stdout == b"KNOWLEDGEBASE.local.md:1\n" + body
    assert run(body, "hook candidates").stdout == result.stdout


def test_duplicate_headings(kb):
    _, run = kb
    result = run(b"## Same\none\n## Same\ntwo", "same")
    assert result.returncode == 0
    assert result.stdout == (
        b"KNOWLEDGEBASE.local.md:1\n## Same\none\n"
        b"KNOWLEDGEBASE.local.md:3\n## Same\ntwo\n"
    )


def test_max_bytes_cutoff(kb):
    _, run = kb
    first = "## Match é\ntext\n".encode("utf-8")
    second = b"## Match two\nmore\n"
    third = b"## Match three\nend\n"
    block = b"KNOWLEDGEBASE.local.md:1\n" + first
    data = first + second + third
    result = run(data, "match", "--max-bytes", str(len(block)))
    assert result.returncode == 0
    assert result.stdout == block + (
        "Omitted matched sections (LINE  BYTES  heading):\n"
        f"3  {len(second)}  Match two\n5  {len(third)}  Match three\n"
        f"Rerun with --max-bytes {len(block) + len(b'KNOWLEDGEBASE.local.md:3') + 1 + len(second)} to print it\n"
    ).encode("utf-8")
    budget = len(block) + len(b"KNOWLEDGEBASE.local.md:3\n") + len(second)
    assert b"KNOWLEDGEBASE.local.md:3\n" + second in run(
        data, "match", "--max-bytes", str(budget)
    ).stdout
    result = run(data, "match", "--max-bytes", str(len(block) - 1))
    assert result.stdout.startswith(b"Omitted matched sections")
    assert f"1  {len(first)}  Match é\n".encode("utf-8") in result.stdout
    assert f"Rerun with --max-bytes {len(block)} to print it\n".encode() in result.stdout
    assert run(first, "match", "--max-bytes", str(len(block))).stdout == block


def test_body_fallback_lists_sections_and_matching_lines(kb):
    _, run = kb
    first = b"## Tools\nPapyrusUtil is installed\nCheck VERSION first\n"
    second = b"## Notes\nPapyrusUtil alone\n"
    third = b"## History\nversion of PAPYRUSUTIL\n"
    result = run(first + second + third, "papyrusutil", "version")
    assert result.returncode == 0
    assert result.stdout == (
        f"1  {len(first)}  Tools  (matching lines: 2, 3)\n"
        f"6  {len(third)}  History  (matching lines: 7)\n"
    ).encode()
    assert b"is installed" not in result.stdout


def test_body_flag_overrides_heading_matches(kb):
    _, run = kb
    first = b"## PapyrusUtil\nNo details here\n"
    second = b"## Tools\nPapyrusUtil warning\n"
    data = first + second
    assert run(data, "papyrusutil").stdout == b"KNOWLEDGEBASE.local.md:1\n" + first
    result = run(data, "--body", "papyrusutil")
    assert result.returncode == 0
    assert result.stdout == f"3  {len(second)}  Tools  (matching lines: 4)\n".encode()
    assert run(first, "--body", "papyrusutil").returncode == 1


def test_utf8_output_with_cp1252_console(kb):
    _, run = kb
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    data = "## 漢字\nbody\n".encode("utf-8")
    for args, status in [((), 0), (("absent",), 1), (("漢字",), 0)]:
        result = run(data, *args, env=env)
        assert result.returncode == status, result.stderr
        assert "漢字".encode("utf-8") in result.stdout


def test_no_match(kb):
    _, run = kb
    data = b"".join(f"## Heading {i}\nbody\n".encode() for i in range(7))
    result = run(data, "absent")
    assert result.returncode == 1
    lines = result.stdout.decode().splitlines()
    assert lines[0] == "No matching sections. Closest headings:"
    assert len(lines) == 6
    assert run(b"## Hook candidates\ntext\n## Other\n", "hook", "candidatez").stdout.splitlines()[1].endswith(b"Hook candidates")


def test_missing_file(tmp_path):
    path = tmp_path / "missing.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(path)],
        capture_output=True, timeout=10,
    )
    assert result.returncode == 2
    assert b"Cannot read" in result.stderr
    assert str(path).encode() in result.stderr


def _split_kb(tmp_path):
    parent = tmp_path / "KNOWLEDGEBASE.local.md"
    parent.write_bytes(b"## My preferences\n- one\n## Index\n| Read | When |\n")
    folder = tmp_path / "kb.local"
    folder.mkdir()
    (folder / "mods.md").write_bytes(b"# Mods\n## Embers XD patch\nfire body\n")
    (folder / "tools.md").write_bytes(b"## DevBench timeouts\nslow body\n")
    return parent, folder


def _kb(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, timeout=10)


def test_split_listing_labels_every_file(tmp_path):
    parent, folder = _split_kb(tmp_path)
    out = _kb("--file", parent, "--dir", folder).stdout.decode()
    assert "KNOWLEDGEBASE.local.md:1  " in out
    assert "kb.local/mods.md:2  " in out and "kb.local/tools.md:1  " in out
    assert out.rstrip().endswith("in 3 files")


def test_split_heading_match_prints_the_child_section(tmp_path):
    parent, folder = _split_kb(tmp_path)
    result = _kb("--file", parent, "--dir", folder, "embers")
    assert result.returncode == 0
    assert result.stdout == b"kb.local/mods.md:2\n## Embers XD patch\nfire body\n"


def test_split_body_match_names_the_child(tmp_path):
    parent, folder = _split_kb(tmp_path)
    out = _kb("--file", parent, "--dir", folder, "--body", "slow").stdout.decode()
    assert out.startswith("kb.local/tools.md:1  ") and "(matching lines: 2)" in out


def test_file_alone_ignores_topic_files(tmp_path):
    parent, folder = _split_kb(tmp_path)
    out = _kb("--file", parent).stdout.decode()
    assert "mods.md" not in out and out.endswith(f"Total: 2 sections, {parent.stat().st_size} bytes\n")


def test_missing_dir_is_single_file(tmp_path):
    parent, _ = _split_kb(tmp_path)
    out = _kb("--file", parent, "--dir", tmp_path / "absent").stdout.decode()
    assert out.startswith("1  ")


def _indexed(tmp_path, extra=b""):
    parent, folder = _split_kb(tmp_path)
    parent.write_bytes(b"## My preferences\n- one\n## Index\n| Read | When |\n|---|---|\n"
                       b"| `kb.local/mods.md` | patching a mod |\n| `kb.local/tools.md` | DevBench and tools |\n" + extra)
    return parent, folder


def test_check_clean_split(tmp_path):
    parent, folder = _indexed(tmp_path)
    result = _kb("--check", "--file", parent, "--dir", folder)
    assert (result.returncode, result.stdout) == (0, b"")


def test_check_not_split_is_silent(tmp_path):
    parent, _ = _split_kb(tmp_path)
    result = _kb("--check", "--file", parent, "--dir", tmp_path / "absent")
    assert (result.returncode, result.stdout) == (0, b"")


def test_check_stray_parent_section_suggests_a_topic(tmp_path):
    parent, folder = _indexed(tmp_path, b"## DevBench timeouts again\nnew\n")
    result = _kb("--check", "--file", parent, "--dir", folder)
    assert result.returncode == 1
    assert b'"DevBench timeouts again" belongs in a topic file' in result.stdout
    assert b"closest topic file: kb.local/tools.md" in result.stdout


def test_check_unindexed_and_missing_files(tmp_path):
    parent, folder = _indexed(tmp_path)
    (folder / "crashes.md").write_bytes(b"## Crash X\n")
    (folder / "tools.md").unlink()
    out = _kb("--check", "--file", parent, "--dir", folder).stdout.decode()
    assert "kb.local/crashes.md has no row in the ## Index table" in out
    assert "## Index names kb.local/tools.md, which does not exist" in out


def test_check_flags_a_topic_name_kb_guard_cannot_watch(tmp_path):
    parent, folder = _indexed(tmp_path)
    (folder / "my notes.md").write_bytes(b"## X\n")
    out = _kb("--check", "--file", parent, "--dir", folder).stdout.decode()
    assert "kb.local/my notes.md has whitespace in its name" in out
