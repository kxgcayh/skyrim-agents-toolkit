"""Behavioral tests for tools/devbench-cli.sh against a mock DevBench server.

The exit codes are the contract -- anything scripting this wrapper branches on
them -- so they are asserted, not just the human-readable text.

Why this suite exists: from v3.3 to v3.5.1 `alive` diffed the frame counter
across two `inspect` calls, but every DevBench tool call runs on the game's main
thread and 504s after 5s when that thread is stuck. On a genuine hang the probe
hung too, and the result was indistinguishable from a closed game. The check
failed in precisely the case it existed for, and nothing caught it for three
releases.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import BASH, REPO, scratch_dir

CLI = REPO / "tools" / "devbench-cli.sh"
MOCK = Path(__file__).resolve().parent / "mock_devbench.py"


# Everything devbench-cli.sh shells out to, minus jq. `bash` is here because
# the test itself execs it.
NEEDED = ["bash", "curl", "sed", "head", "tr", "cat", "sleep", "env", "dirname"]

_nojq_dir: Path | None = None


def _path_without_jq() -> str:
    """A PATH with everything the script needs except jq.

    Dropping whole PATH entries that contain jq works on Windows, where jq sits
    in its own WinGet/choco directory. It is wrong on Linux: jq lives in
    /usr/bin alongside bash, curl and coreutils, so dropping that directory
    takes the interpreter with it and the run dies with
    "No such file or directory: 'bash'" having tested nothing.
    """
    if os.name == "nt":
        keep = []
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if not entry:
                continue
            d = Path(entry)
            if (d / "jq").exists() or (d / "jq.exe").exists():
                continue
            keep.append(entry)
        return os.pathsep.join(keep)

    global _nojq_dir
    if _nojq_dir is None:
        _nojq_dir = Path(scratch_dir("toolkit-nojq-"))
        for name in NEEDED:
            real = shutil.which(name)
            if real:
                # A COPY (Linux CI run 38187755448): the test harness barrier refuses a symlink to a file outside the
                # fixture -- writing through it would write /usr/bin/bash -- so symlink_to raised and left the
                # directory without curl for every later test.
                if sys.platform == "darwin":   # a copied system binary is killed on macOS (signature/SIP): forward to the real one
                    (_nojq_dir / name).write_text('#!/bin/bash\nexec "%s" "$@"\n' % real, encoding="utf-8")
                    (_nojq_dir / name).chmod(0o755)
                else:
                    shutil.copy(real, _nojq_dir / name)
    return str(_nojq_dir)


def held_dead_port():
    """A port guaranteed to refuse connections, held open for the caller.

    Binding without listening is what makes this reliable: the port cannot be
    grabbed by another process while the test runs, and a connect attempt is
    refused rather than accepted. The old "bind port 0, close it, assume it
    stays free" approach was a race that would surface as a spurious failure.
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    return s, s.getsockname()[1]


def _wait_until_listening(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.25)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


class Server:
    def __init__(self, mode: str):
        # Port 0: the server binds, then tells us which port it got. Choosing a
        # port here and hoping it is still free when the child binds it is a
        # race that shows up as an intermittent "never started listening".
        self.proc = subprocess.Popen(
            [sys.executable, str(MOCK), "0", mode],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        line = self.proc.stdout.readline().strip()
        if not line.startswith("PORT="):
            self.stop()
            raise RuntimeError(f"mock server ({mode}) did not announce a port: {line!r}")
        self.port = int(line.split("=", 1)[1])
        if not _wait_until_listening(self.port):
            self.stop()
            raise RuntimeError(f"mock server ({mode}) never started listening")

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def server(request):
    s = Server(request.param)
    yield s
    s.stop()


def run_cli(*args, port: int, mask_jq: bool = False):
    env = dict(os.environ)
    env["DEVBENCH_PORT"] = str(port)
    if mask_jq:
        env["PATH"] = _path_without_jq()
        # Prove the mask worked. If jq were still reachable this test would run
        # the jq path and pass while claiming to cover the fallback -- a test
        # that examines nothing must never report success.
        probe = subprocess.run([BASH, "-c", "command -v jq"], env=env,
                               capture_output=True, text=True)
        assert probe.returncode != 0, (
            f"jq still resolvable after masking: {probe.stdout.strip()!r}")
    return subprocess.run(
        [BASH, str(CLI), *args],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=120,
    )


# ----------------------------------------------------------------- liveness

@pytest.mark.parametrize("server", ["running"], indirect=True)
def test_running_game_reports_running(server):
    r = run_cli("alive", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RUNNING" in r.stdout


@pytest.mark.parametrize("server", ["paused"], indirect=True)
def test_paused_game_is_not_called_a_hang(server):
    """A frozen frame alone is not evidence of a hang -- menus and loading
    screens freeze it too. The old check cried wolf every time."""
    r = run_cli("alive", port=server.port)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NOT ADVANCING" in r.stdout
    assert "HUNG" not in r.stdout, "a pause was reported as a hang"


@pytest.mark.parametrize("server", ["hung"], indirect=True)
def test_starved_main_thread_is_reported_as_hung(server):
    """Frame frozen AND pendingTasks piling up while lastTaskFrame stalls."""
    r = run_cli("alive", port=server.port)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "HUNG" in r.stdout or "STARVED" in r.stdout


@pytest.mark.parametrize("server", ["notingame"], indirect=True)
def test_no_save_loaded_is_its_own_state(server):
    """frame < 0 means the server is up but nothing is loaded -- distinct from
    both running and hung, and it gets its own exit code."""
    r = run_cli("alive", port=server.port)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "NOT IN GAME" in r.stdout


@pytest.mark.parametrize("server", ["legacy"], indirect=True)
def test_pre_1_11_devbench_falls_back_and_says_so(server):
    """Older DevBench has no /api/health. The wrapper must degrade to the legacy
    frame diff rather than fail, and must say that it did."""
    r = run_cli("alive", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RUNNING" in r.stdout
    assert "predates" in r.stderr or "legacy" in r.stderr.lower()


def test_dead_port_is_distinguishable_from_a_hang():
    """No server at all: exit 1, with the closed-game message."""
    sock, port = held_dead_port()
    try:
        r = run_cli("alive", port=port)
    finally:
        sock.close()
    assert r.returncode == 1
    assert "no response" in (r.stdout + r.stderr).lower()


# ----------------------------------------------------------- HTTP semantics

@pytest.mark.parametrize("server", ["busy504"], indirect=True)
def test_504_is_reported_as_a_busy_main_thread(server):
    """504 means the server is fine and the game is busy. Before v3.5.1 any
    JSON body counted as success and this printed as though it worked."""
    r = run_cli("state", port=server.port)
    assert r.returncode != 0, "a 504 was treated as success"
    assert "504" in r.stderr


@pytest.mark.parametrize("server", ["badarg400"], indirect=True)
def test_400_is_reported_as_a_bad_argument(server):
    r = run_cli("inspect", "vm", port=server.port)
    assert r.returncode != 0, "a 400 was treated as success"
    assert "400" in r.stderr


# ------------------------------------------------------------------- no jq

@pytest.mark.parametrize("server,code,words", [("running", 0, ("RUNNING",)), ("hung", 2, ("HUNG", "STARVED")),
                                               ("notingame", 3, ("NOT IN GAME",))], indirect=["server"])
def test_liveness_still_works_without_jq(server, code, words):
    """jget's no-jq branch is hand-rolled sed and is the least-exercised code in
    the script; every verdict must survive losing jq -- the SAME verdict as with jq
    (v4.0.0 review L4a L7: any of 0/2/3 used to pass, so a hang read as running passed)."""
    r = run_cli("alive", port=server.port, mask_jq=True)
    assert "instance:" in r.stdout, r.stdout + r.stderr
    assert r.returncode == code, r.stdout + r.stderr
    assert any(w in r.stdout for w in words), r.stdout
    assert r.returncode in (0, 2, 3), f"unexpected exit {r.returncode}"


@pytest.mark.parametrize("server", ["capture", "incomplete"], indirect=True)
def test_exec_uses_its_own_capture(server):
    import json
    command = 'help "quoted"\npath\\file'
    r = run_cli("exec", command, port=server.port, mask_jq=True)
    assert r.returncode == (0 if server.proc.args[-1] == "capture" else 3), r.stderr
    assert json.loads(r.stdout)["lines"] == [command]


@pytest.mark.parametrize("server", ["echo"], indirect=True)
@pytest.mark.parametrize("tool", ["gfx", "dialogue"])
def test_tool_shortcuts_preserve_arguments(server, tool):
    import json
    args = {"action": "inspect", "snapshot": "observed", "index": 2}
    r = run_cli(tool, json.dumps(args), port=server.port)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"path": "/api/tool/" + tool, "args": args}


@pytest.mark.parametrize("server", ["echo"], indirect=True)
def test_notify_escapes_text_without_jq(server):
    import json
    message = 'a "quote"\nnext\tpath\\file'
    r = run_cli("notify", message, port=server.port, mask_jq=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["args"]["args"] == [message]


# ------------------------------------------------- review regressions (strict mock: invalid JSON -> 400)

@pytest.mark.parametrize("server", ["strict"], indirect=True)
@pytest.mark.parametrize("value, expected", [
    ("00012345", "00012345"),   # leading zeros are not a JSON number: must be sent as a string (FormID text)
    ("0013298", "0013298"),
    ("800", 800), ("-5", -5), ("1.5", 1.5), ("0", 0), ("0.25", 0.25),
])
def test_inspect_leading_zero_value_is_sent_as_a_string(server, value, expected):
    import json
    r = run_cli("inspect", "refs", f"formId={value}", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    sent = json.loads(r.stdout)["args"]["formId"]
    assert sent == expected and type(sent) is type(expected)


@pytest.mark.parametrize("server", ["strict"], indirect=True)
def test_call_value_prints_an_error_body_compact(server):
    import json
    r = run_cli("call", "ObjectReference", "Reject", "[]", "--value", port=server.port)
    assert r.returncode == 4, r.stdout + r.stderr
    assert r.stdout.strip() == json.dumps({"error": "arg 1: expected Float got Int", "code": 400}, separators=(",", ":"))


@pytest.mark.parametrize("server", ["running"], indirect=True)
def test_raw_is_accepted_before_the_command(server):
    r = run_cli("--raw", "ping", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Unknown command" not in r.stderr
    import json
    assert json.loads(r.stdout) == {"ok": True}


def test_coerce_args_with_three_arguments_does_not_trip_set_u():
    import re
    src = CLI.read_text(encoding="utf-8")
    fn = re.search(r"^coerce_args\(\) \{.*?^\}", src, re.S | re.M).group(0)
    r = subprocess.run([BASH, "-uc", fn + '\nHAVE_JQ=0\ncoerce_args ObjectReference SetAngle "[0,0,90]"'],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "[0,0,90]"


def _logs(tmp_path, monkeypatch_env):
    env = dict(os.environ)
    env["DEVBENCH_PAPYRUS_LOG"] = str(tmp_path / "Papyrus.0.log")
    env["DEVBENCH_DIAG_DIR"] = str(tmp_path / "diag")
    return env


def _cli_env(env, *args):
    return subprocess.run([BASH, str(CLI), *args], cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)


def test_logdiff_detects_rotation_of_a_log_shorter_than_256_bytes(tmp_path):
    env = _logs(tmp_path, None)
    log = tmp_path / "Papyrus.0.log"
    log.write_text("old session header line 1\nshort\n")            # 32 bytes at the mark
    assert _cli_env(env, "logmark").returncode == 0
    log.write_text("[11/12/2026 - 01:00:00AM] NEW SESSION header aaaa\n"
                   "[11/12/2026 - 01:00:01AM] second line bbbbbbbbbbbb\n")   # rotated, now longer than the mark
    r = _cli_env(env, "logdiff")
    assert "rotated or replaced" in r.stderr, r.stderr
    assert r.stdout.startswith("[11/12/2026 - 01:00:00AM] NEW SESSION"), r.stdout


def test_logdiff_does_not_cry_rotation_when_a_short_log_only_grew(tmp_path):
    env = _logs(tmp_path, None)
    log = tmp_path / "Papyrus.0.log"
    log.write_text("[11/12/2026 - 01:00:00AM] header\n")
    assert _cli_env(env, "logmark").returncode == 0
    with log.open("a") as fh:
        fh.write("[11/12/2026 - 01:00:05AM] appended line\n")
    r = _cli_env(env, "logdiff")
    assert "rotated" not in r.stderr, r.stderr
    assert r.stdout == "[11/12/2026 - 01:00:05AM] appended line\n"


def test_logdiff_errors_does_not_latch_on_a_continuation_line(tmp_path):
    env = _logs(tmp_path, None)
    log = tmp_path / "Papyrus.0.log"
    log.write_text("[11/12/2026 - 01:00:00AM] start\n")
    assert _cli_env(env, "logmark").returncode == 0
    with log.open("a") as fh:
        fh.write("[11/12/2026 - 01:00:01AM] info entry\n   continuation mentions a warning word\n   second continuation\n"
                 "[11/12/2026 - 01:00:02AM] error: real\n   stack frame\n"
                 "[11/12/2026 - 01:00:03AM] info after\n   plain continuation\n")
    r = _cli_env(env, "logdiff", "--errors")
    assert r.stdout == "[11/12/2026 - 01:00:02AM] error: real\n   stack frame\n", r.stdout


# ------------------------------------------- live-test commands (2026-11-13): form, call specs, waitcall, msgbox,
# coc, goto, named marks and entry filters. Mode "sim" in mock_devbench.py is a small stateful game.

def _sim_state(port):
    import json
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/tool/sim", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


@pytest.mark.parametrize("server", ["sim"], indirect=True)
@pytest.mark.parametrize("spec, expected", [
    ("BSHeartland.esm:0012F7", "0x160012F7"), ("0012F7:bsheartland.ESM", "0x160012F7"),
    ("BSHeartland.esm:3B0012F7", "0x160012F7"),        # a full ID's load index is replaced
    ("Some Patch.esp:000800", "0xFE324800"), ("Some Patch.esp:FE001800", "0xFE324800"),
    ("0x14", "0x14"),
])
def test_form_resolves_full_and_light_plugins(server, spec, expected):
    r = run_cli("form", spec, port=server.port)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == expected


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_form_unknown_plugin_fails_cleanly(server):
    r = run_cli("form", "Missing.esp:000800", port=server.port)
    assert r.returncode == 1 and "plugin not loaded: Missing.esp" in r.stderr, r.stderr


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_call_resolves_plugin_relative_forms_in_args_and_self(server):
    import json
    r = run_cli("call", "ObjectReference", "Echo", '[{"form":"Some Patch.esp:000800"},false]',
                '{"form":"BSHeartland.esm:0012F7"}', "--value", port=server.port)
    assert r.returncode == 0, r.stderr
    sent = json.loads(r.stdout)
    assert sent["args"] == [{"form": "0xFE324800"}, False] and sent["self"] == {"form": "0x160012F7"}


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_waitcall_polls_until_the_value_matches(server):
    r = run_cli("waitcall", "Actor", "HasSpell", '[{"form":"0x313A9AF6"}]', '{"form":"0x14"}',
                "--equals", "true", "--timeout", "10", "--every", "0.2", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("MATCHED") and _sim_state(server.port)["hasspell"] == 3


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_waitcall_times_out_with_the_last_value(server):
    r = run_cli("waitcall", "ObjectReference", "GetAngleZ", "[]", '{"form":"0x14"}',
                "--equals", "0", "--timeout", "1", "--every", "0.2", port=server.port)
    assert r.returncode == 3 and "last value 90" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_msgbox_answers_by_label(server):
    r = run_cli("msgbox", "--wait", "2", "--answer", "leave", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"Pray?"' in r.stdout and "ANSWERED: Leave (index 1)" in r.stdout
    assert _sim_state(server.port)["answer"] == 1


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_msgbox_unknown_button_does_not_click(server):
    r = run_cli("msgbox", "--answer", "Maybe", port=server.port)
    assert r.returncode == 4 and "no button 'Maybe'" in r.stderr
    assert _sim_state(server.port)["answer"] is None


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_coc_waits_for_the_load_and_the_cell(server):
    t = time.time()
    r = run_cli("coc", "GoodCell", "--timeout", "20", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("ARRIVED: GoodCell") and time.time() - t >= 1.5


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_coc_rejected_cell_exits_4(server):
    r = run_cli("coc", "NoSuchCell", port=server.port)
    assert r.returncode == 4 and "rejected" in r.stderr


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_goto_moves_beside_the_ref_not_onto_it(server):
    r = run_cli("goto", "BSHeartland.esm:0012F7", "--dist", "150", port=server.port)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("AT: 0x160012F7")
    target, dx, dy, dz, match = _sim_state(server.port)["moveto"]
    assert target == {"form": "0x160012F7"} and match is False
    assert abs(dx - 150.0) < 0.2 and abs(dy) < 0.2 and dz == 20.0    # angle 90: in front = +X


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_goto_if_unloaded_leaves_the_player_alone_when_loaded(server):
    r = run_cli("goto", "0x14", "--if-unloaded", port=server.port)
    assert r.returncode == 0 and r.stdout.startswith("ALREADY LOADED")
    assert _sim_state(server.port)["moveto"] is None


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_goto_ref_not_in_memory_says_coc_first(server):
    r = run_cli("goto", "0x16000999", port=server.port)
    assert r.returncode == 4 and "'coc' to its cell first" in r.stderr


def test_named_marks_do_not_collide(tmp_path):
    env = _logs(tmp_path, None)
    log = tmp_path / "Papyrus.0.log"
    log.write_text("[11/13/2026 - 01:00:00AM] start\n")
    assert _cli_env(env, "logmark", "--name", "listener").returncode == 0
    with log.open("a") as fh:
        fh.write("[11/13/2026 - 01:00:01AM] one\n")
    assert _cli_env(env, "logmark", "--name", "test").returncode == 0
    with log.open("a") as fh:
        fh.write("[11/13/2026 - 01:00:02AM] two\n")
    assert _cli_env(env, "logdiff", "--name", "test").stdout == "[11/13/2026 - 01:00:02AM] two\n"
    assert _cli_env(env, "logdiff", "--name", "listener").stdout.count("\n") == 2
    assert _cli_env(env, "logdiff").returncode == 1                      # the unnamed mark was never set
    assert _cli_env(env, "logmark", "--name", "../x").returncode == 1


def test_logdiff_ref_and_grep_keep_whole_entries(tmp_path):
    env = _logs(tmp_path, None)
    log = tmp_path / "Papyrus.0.log"
    log.write_text("[11/13/2026 - 01:00:00AM] start\n")
    assert _cli_env(env, "logmark").returncode == 0
    with log.open("a") as fh:
        fh.write("[11/13/2026 - 04:20:02PM] error: Cannot call Show() on a None object, aborting function call\n"
                 "stack:\n\t[ (3B015490)].TempleBlessingScript.OnActivate() - \"TempleBlessingScript.psc\" Line ?\n"
                 "[11/13/2026 - 04:20:03PM] error: Unable to call RegisterForSingleUpdate\n"
                 "stack:\n\t[None].MAG_ResistanceTracker_Script.OnEffectStart() - \"x.psc\" Line ?\n"
                 "[11/13/2026 - 04:20:04PM] [BHKS] info line mentioning templeblessingscript\n")
    r = _cli_env(env, "logdiff", "--ref", "0x3b015490")
    assert r.stdout.startswith("[11/13/2026 - 04:20:02PM] error: Cannot call Show()") and r.stdout.count("[11/13") == 1
    assert "(3B015490)" in r.stdout                                        # the stack line came along
    r = _cli_env(env, "logdiff", "--errors", "--grep", "TempleBlessing")
    assert r.stdout.count("[11/13") == 1 and "3B015490" in r.stdout        # info line dropped by --errors
    r = _cli_env(env, "logdiff", "--grep", "templeblessing")
    assert r.stdout.count("[11/13") == 2


@pytest.mark.parametrize("server", ["sim"], indirect=True)
def test_coc_unknown_cell_with_no_console_output_fails_fast(server):
    t = time.time()
    r = run_cli("coc", "SilentBadCell", "--timeout", "60", port=server.port)
    assert r.returncode == 4 and "did nothing" in r.stderr, r.stdout + r.stderr
    assert time.time() - t < 20                       # not the 60 s timeout
