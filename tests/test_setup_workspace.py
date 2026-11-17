"""setup.sh and the workspace folder: where every new file goes, never the toolkit (docs/workspace.md)."""

from __future__ import annotations

import sys
from pathlib import Path

from conftest import REPO, claude_md, key_path, run_setup

sys.path.insert(0, str(REPO / "tools"))
from skyguard import paths  # noqa: E402
import skyrim_paths  # noqa: E402

KEY = "SKYRIM_WORKSPACE_DIR"
TEMPLATE_FILES = ("README.md", "AGENTS.md", "CLAUDE.md", "link-submodules.sh", "toolkit.env")


def _workspace(game: Path) -> Path:
    return game.parent / "skyrim-workspace"


def _recorded(game: Path) -> str:
    cfg = paths.read_config(game / paths.PATHS_FILE, {})
    return (cfg.file.get(KEY) or ("",))[0]


def test_setup_creates_the_workspace_next_to_the_toolkit(game_dir):
    r = run_setup(game_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    ws = _workspace(game_dir)
    for d in ("mods", "tools", "reports", "scratch"):
        assert (ws / d).is_dir(), d
    for f in TEMPLATE_FILES:
        assert (ws / f).is_file(), f
    assert _recorded(game_dir) == ws.as_posix()
    assert "Workspace:" in r.stdout


def test_the_pointer_names_the_toolkit(game_dir):
    run_setup(game_dir)
    line = (_workspace(game_dir) / "toolkit.env").read_text(encoding="utf-8").strip()
    assert line.startswith("SKYRIM_TOOLKIT_DIR='") and line.endswith("'")
    assert Path(line[len("SKYRIM_TOOLKIT_DIR='"):-1]).resolve() == game_dir.resolve()


def test_claude_md_gets_the_workspace_line_filled(game_dir):
    run_setup(game_dir)
    line = key_path(game_dir, "Workspace")
    assert _workspace(game_dir).as_posix() in line, line
    assert "{{WORKSPACE_DIR}}" not in claude_md(game_dir)


def test_an_existing_workspace_file_is_never_overwritten(game_dir):
    ws = _workspace(game_dir)
    ws.mkdir()
    (ws / "README.md").write_text("mine\n", encoding="utf-8")
    (ws / "AGENTS.md").write_text("my rules\n", encoding="utf-8")
    run_setup(game_dir)
    assert (ws / "README.md").read_text(encoding="utf-8") == "mine\n"
    assert (ws / "AGENTS.md").read_text(encoding="utf-8") == "my rules\n"
    assert (ws / "toolkit.env").is_file()


def test_a_second_run_changes_nothing_but_the_pointer_when_the_toolkit_moved(game_dir):
    run_setup(game_dir)
    ws = _workspace(game_dir)
    before = {f: (ws / f).read_bytes() for f in TEMPLATE_FILES}
    r = run_setup(game_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert {f: (ws / f).read_bytes() for f in TEMPLATE_FILES} == before
    (ws / "toolkit.env").write_text("SKYRIM_TOOLKIT_DIR='/old/place'\n", encoding="utf-8")
    run_setup(game_dir)
    assert (ws / "toolkit.env").read_bytes() == before["toolkit.env"]


def test_no_workspace_records_none_and_creates_nothing(game_dir):
    r = run_setup(game_dir, args=("--no-workspace",))
    assert r.returncode == 0, r.stdout + r.stderr
    assert not _workspace(game_dir).exists()
    assert _recorded(game_dir) == ""
    assert "not set" in key_path(game_dir, "Workspace")
    assert skyrim_paths.workspace_dir({}, toolkit=game_dir) is None


def test_workspace_flag_names_the_folder(game_dir, tmp_path):
    target = tmp_path / "elsewhere" / "my work"
    r = run_setup(game_dir, args=("--workspace", str(target)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (target / "AGENTS.md").is_file()
    assert not _workspace(game_dir).exists()
    assert _recorded(game_dir) == target.as_posix()
    assert skyrim_paths.workspace_dir({}, toolkit=game_dir) == target


def test_a_path_set_by_hand_survives_a_rerun(game_dir, tmp_path):
    run_setup(game_dir)
    mine = tmp_path / "hand-set"
    mine.mkdir()
    env = game_dir / paths.PATHS_FILE
    text = env.read_text(encoding="utf-8").splitlines()
    text = [f"{KEY}='{mine.as_posix()}'" if ln.startswith(KEY + "=") else ln for ln in text]
    env.write_text("\n".join(text) + "\n", encoding="utf-8")
    r = run_setup(game_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _recorded(game_dir) == mine.as_posix()
    assert (mine / "toolkit.env").is_file()


def test_a_workspace_inside_the_toolkit_is_refused(game_dir):
    inside = game_dir / "work"
    r = run_setup(game_dir, args=("--workspace", str(inside)))
    assert r.returncode == 0, r.stdout + r.stderr
    assert not inside.exists()
    assert "NOT created" in r.stdout


def test_the_two_flags_contradict(game_dir):
    r = run_setup(game_dir, args=("--workspace", "/x", "--no-workspace"))
    assert r.returncode == 2
    assert not (game_dir / paths.PATHS_FILE).exists()


def test_the_key_is_read_but_never_guarded(game_dir):
    run_setup(game_dir)
    cfg = paths.read_install(str(game_dir), {})
    assert cfg.first(KEY) == _workspace(game_dir).as_posix()
    assert KEY not in paths.ENV_KEYS and KEY not in paths.PROTECTION_KEYS
    assert skyrim_paths.workspace_dir({}, toolkit=game_dir) == _workspace(game_dir)
    assert skyrim_paths.workspace_dir({KEY: "/from/env"}, toolkit=game_dir) == Path("/from/env")
