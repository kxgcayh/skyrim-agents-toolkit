"""Tests for the AGY guard adapter (.agents/hooks/agy-guard.py) and neutral session-start."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from conftest import REPO

AGY_GUARD = REPO / ".agents" / "hooks" / "agy-guard.py"


def _run_guard(payload: dict, env: dict | None = None) -> dict:
    e = dict(os.environ)
    if env:
        e.update(env)
    proc = subprocess.run(
        [sys.executable, str(AGY_GUARD)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        check=True,
        env=e,
    )
    return json.loads(proc.stdout.decode("utf-8"))


# ---- _to_agy unit tests -------------------------------------------------------------

def _agy_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("agy_guard_session", str(AGY_GUARD))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_to_agy_plain_allow():
    mod = _agy_module()

    out = mod._to_agy({"decision": "allow", "reason": "", "context": ""})
    assert out == {"decision": "allow"}


def test_to_agy_allow_with_advisory_note():
    mod = _agy_module()

    note = "Note: this writes Skyrim.ini; a later INI in the load chain can override it."
    out = mod._to_agy({"decision": "allow", "reason": "", "context": note})
    assert out == {"decision": "allow", "reason": note}


def test_to_agy_deny():
    mod = _agy_module()

    out = mod._to_agy({"decision": "deny", "reason": "Blocked: forbidden"})
    assert out == {"decision": "deny", "reason": "Blocked: forbidden"}


def test_to_agy_ask():
    mod = _agy_module()

    out = mod._to_agy({"decision": "ask", "reason": "Requires confirmation"})
    assert out == {"decision": "ask", "reason": "Requires confirmation"}


# ---- P09 end-to-end advisory note ---------------------------------------------------

def test_p09_offline_probe_includes_note():
    payload = {
        "toolCall": {
            "name": "run_command",
            "args": {
                "CommandLine": 'echo "[x]" >> "/Users/x/Documents/My Games/Skyrim Special Edition/Skyrim.ini"'
            },
        },
        "conversationId": "test-p09",
        "workspacePaths": [str(REPO)],
    }
    out = _run_guard(payload)
    assert out.get("decision") == "allow"
    assert "Note: this writes Skyrim.ini" in out.get("reason", "")


# ---- SessionStart hook contract ----------------------------------------------------

def test_session_start_hook_injects_system_message(monkeypatch, capsys):
    """agy's SessionStart (flat handler list, `hookEventName` in the input) answers with one injected system message
    carrying the shared session text. The text itself is run.py's (tests/test_session_vault_note.py, neutral row);
    stubbed here so the test never snapshots or starts anything in the real install."""
    mod = _agy_module()
    seen = {}

    def fake(payload):
        seen["payload"] = payload
        return "SESSION-TEXT"

    monkeypatch.setattr(mod, "_run_session_start", fake)
    monkeypatch.setattr(mod, "_read_stdin", lambda: {"hookEventName": "SessionStart", "conversationId": "c1"})
    mod.main()
    out = json.loads(capsys.readouterr().out)
    assert out == {"injectSteps": [{"systemMessage": {"systemMessage": "SESSION-TEXT"}}]}
    assert seen["payload"]["conversationId"] == "c1"


@pytest.mark.parametrize("stdout,text", [
    (b"SKYGUARD-OK\nline one\nline two\n", "line one\nline two"),
    (b"SKYGUARD-OK", ""),
    (b"noise\nSKYGUARD-OK\nbody\n", "body"),
])
def test_session_start_strips_the_marker(monkeypatch, stdout, text):
    mod = _agy_module()
    calls = []

    class R:
        returncode = 0

    def fake_run(argv, **kw):
        calls.append(argv)
        r = R()
        r.stdout = stdout
        return r

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._run_session_start({"hookEventName": "SessionStart"}) == text
    assert calls[0][2:4] == ["neutral", "session-start"]


def test_session_start_failure_is_said_not_raised(monkeypatch):
    mod = _agy_module()
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert "session-start failed" in mod._run_session_start({})


@pytest.mark.parametrize("rc,stdout,stderr", [(1, b"", b"Traceback: boom"), (0, b"half a banner", b"")])
def test_session_start_without_the_marker_is_said_not_silent(monkeypatch, rc, stdout, stderr):
    """A broken session-start (exit 1, or output with no SKYGUARD-OK marker) must not inject an empty message."""
    mod = _agy_module()

    class R:
        pass

    def fake_run(argv, **kw):
        r = R()
        r.returncode, r.stdout, r.stderr = rc, stdout, stderr
        return r

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    text = mod._run_session_start({})
    assert text.startswith("SKYGUARD: session-start failed (exit {})".format(rc))
    if stderr:
        assert "boom" in text


# ---- working folder ------------------------------------------------------------------
# agy's PreToolUse payload carries a top-level `cwd` (measured 2026-11-18 with a logging hook: keys artifactDirectoryPath,
# conversationId, cwd, hookEventName, lastUserInput, modelName, stepIdx, toolCall, transcriptPath, workspacePaths).
# The adapter used workspacePaths[0] only, so a command run in another folder of a multi-folder workspace was judged
# against the wrong folder.

def _request_cwd(monkeypatch, capsys, payload):
    mod = _agy_module()
    seen = {}
    monkeypatch.setattr(mod, "_read_stdin", lambda: payload)
    monkeypatch.setattr(mod, "_run_engine", lambda request: seen.setdefault("request", request) and {"decision": "allow"})
    mod.main()
    capsys.readouterr()
    return seen["request"]["cwd"]


def _call(**top):
    return {"hookEventName": "PreToolUse", "toolCall": {"name": "run_command", "args": {"CommandLine": "pwd"}}, **top}


def test_the_payload_cwd_wins_over_the_first_workspace_folder(monkeypatch, capsys, tmp_path):
    first = str(tmp_path / "first")
    second = str(tmp_path / "second")
    p = _call(cwd=second, workspacePaths=[first, second])
    assert _request_cwd(monkeypatch, capsys, p) == second


@pytest.mark.parametrize("cwd", [None, "", "relative/dir", 7])
def test_a_missing_or_untrusted_cwd_falls_back_to_the_first_workspace_folder(monkeypatch, capsys, cwd):
    p = _call(workspacePaths=["/work/first"], **({} if cwd is None else {"cwd": cwd}))
    assert _request_cwd(monkeypatch, capsys, p) == "/work/first"


def test_without_either_the_toolkit_root_is_used(monkeypatch, capsys):
    mod = _agy_module()
    assert _request_cwd(monkeypatch, capsys, _call()) == str(mod.ROOT)
