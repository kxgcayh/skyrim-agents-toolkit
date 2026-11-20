"""`git checkout -- <paths>` / `git restore <paths>`: the folder git runs in (`-C`, repeated `-C`, `--work-tree`) decides
what the pathspecs name, and a discard is S-GIT-DISCARD's (ask) unless it reaches inside a save store (S-SAVE-STORE).

Found 2026-11-18: `git -C <workspace repo> checkout -- .` run from the toolkit root was refused with S-SAVE-STORE: the
pathspec `.` was read against the agent's working directory (the toolkit root, an install dir holding the toolkit's own
save store) and counted as the store's ancestor. Git overwrites tracked files only and every store is untracked, so an
ancestor pathspec cannot reach it; the corpus rows rtb-git-* already ask for every discard in the install.
"""
import sys

import pytest

from conftest import REPO, GAME_ROOT, scratch_dir

sys.path.insert(0, str(REPO / "tools"))
from skyguard import audit, paths, shell_rules  # noqa: E402

GAME = GAME_ROOT
PARENT, LEAF = GAME.rsplit("/", 1)
STORE_FILE = GAME + "/.modding-agent-harness/backups/saves/a.ess"
WORK = "C:/Synthetic Work/skyrim-workspace/mods/some-patch"
ELSEWHERE = "C:/Elsewhere/scratch"  # holds no store and is no ancestor of one
NOHOME = scratch_dir("git-restore-base-nohome-")
ENV0 = {"USERPROFILE": NOHOME, "HOME": NOHOME}


def _judge(command, cwd):
    a = audit.Audit("")
    a.raw = lambda line: None
    v = shell_rules.decide(command, paths.roots("C:/p6t12/Skyrim VR", "", {"SKYRIM_GAME_ROOT": GAME}), a, cwd=cwd,
                           shell="bash", env=ENV0)
    return v.decision, {rid for rid, _ in a.fired}


@pytest.mark.parametrize("command", [
    f'git -C "{WORK}" checkout -- .',
    f'git -C "{WORK}" checkout HEAD -- .',
    f'git -C "{WORK}" restore .',
    f'git --work-tree="{WORK}" checkout -- .',
    f'git --work-tree "{WORK}" checkout -- .',
    'git -C "C:/Synthetic Work" -C skyrim-workspace/mods/some-patch checkout -- .',
])
def test_a_restore_in_another_repo_run_from_the_install_is_allowed(command):
    assert _judge(command, cwd=GAME) == ("allow", set())


@pytest.mark.parametrize("command", [
    f'git -C "{GAME}" checkout -- .',
    f'git -C "{GAME}" restore .',
    f'git --work-tree="{GAME}" checkout -- .',
    f'git -C "../../{GAME[3:]}" checkout -- .',       # relative to the working directory
    f'git -C "{PARENT}" -C "{LEAF}" checkout -- .',   # each -C is relative to the one before
])
def test_a_discard_in_the_install_from_elsewhere_asks(command):
    assert _judge(command, cwd=ELSEWHERE) == ("ask", {"S-GIT-DISCARD"})


def test_a_discard_of_the_whole_install_asks_and_is_not_a_save_store_hit():
    assert _judge("git checkout -- .", cwd=GAME) == ("ask", {"S-GIT-DISCARD"})
    assert _judge("git checkout -- .", cwd=WORK) == ("allow", set())


@pytest.mark.parametrize("command", [
    f'git checkout -- "{STORE_FILE}"',
    f'git -C "{GAME}" checkout -- .modding-agent-harness/backups/saves/a.ess',
    f'git -C "{GAME}" restore -SW .modding-agent-harness/backups/saves/a.ess',
    f'git --namespace x -C "{GAME}" checkout -- .modding-agent-harness/backups/saves/a.ess',
])
def test_a_pathspec_inside_the_store_is_still_denied(command):
    decision, fired = _judge(command, cwd=ELSEWHERE)
    assert decision == "deny" and "S-SAVE-STORE" in fired, (decision, fired)


def test_restore_of_the_index_only_touches_no_working_file():
    for flag in ("--staged", "-S"):
        _, fired = _judge(f'git -C "{GAME}" restore {flag} .modding-agent-harness/backups/saves/a.ess', cwd=ELSEWHERE)
        assert "S-SAVE-STORE" not in fired, (flag, fired)


def test_git_clean_in_the_install_still_protects_the_store():
    decision, fired = _judge(f'git -C "{GAME}" clean -fdx', cwd=ELSEWHERE)
    assert decision == "deny" and "S-SAVE-STORE" in fired, (decision, fired)
