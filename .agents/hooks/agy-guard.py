#!/usr/bin/env python3
"""AGY <-> skyguard adapter. Translates AGY PreToolUse hook payload -> neutral engine request -> AGY response.

AGY hook input (stdin):
  {
    "toolCall": {"name": "<tool>", "args": {...}},
    "conversationId": "...",
    "workspacePaths": [...],
    ...
  }

AGY hook output (stdout):
  {
    "decision": "allow" | "deny" | "ask" | "force_ask",
    "reason": "...",
  }

The neutral adapter accepts:
  {"v":1, "agent":"agy", "event":"pre_tool", "kind":"shell"|"write"|"mcp"|"other",
   "command":"...", "paths":[...], "tool_name":"...", "cwd":"..."}

And returns:
  {"v":1, "decision":"allow"|"deny"|"ask", "reason":"...", "context":"...", "status":"...", "code":"..."}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Locate the toolkit root (two levels above this file: .agents/hooks/agy-guard.py -> root)
# ---------------------------------------------------------------------------
_SELF = Path(__file__).resolve()
ROOT = _SELF.parent.parent.parent  # .agents/hooks/ -> .agents/ -> root

RUNPY = str(ROOT / "tools" / "skyguard" / "run.py")
PROJECT = str(ROOT)
PYTHON = sys.executable  # the Python that launched us — always works

# AGY tool names -> skyguard kinds
# run_command   -> shell (bash on mac)
# write_file    -> write
# edit_file     -> write
# call_mcp_tool -> mcp
# everything else -> other (not guarded, allowed)

_SHELL_TOOLS = {"run_command"}
_WRITE_TOOLS = {"write_file", "edit_file"}
_MCP_TOOLS   = {"call_mcp_tool"}


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def _cwd(payload: dict) -> str:
    """The folder the tool call runs in: agy's own top-level `cwd`, else the first workspace folder, else the toolkit.
    Measured 2026-11-18 (agy, PreToolUse run_command): the payload carries `cwd`; `run_command` has no folder argument
    (agy writes `cd <dir> && ...`, which the shell parser follows), and a `cd` in one call does not carry over to the
    next, so `cwd` stays the session folder. It can differ from workspacePaths[0] in a multi-folder workspace, where
    only `cwd` says which folder the command runs in. A missing, empty or relative value is not trusted."""
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and os.path.isabs(cwd):
        return cwd
    workspace_paths = payload.get("workspacePaths") or []
    first = workspace_paths[0] if isinstance(workspace_paths, list) and workspace_paths else None
    return first if isinstance(first, str) and first else str(ROOT)


def _make_request(tool_name: str, args: dict, cwd: str) -> dict | None:
    """Build the neutral-adapter request dict. Returns None for 'other' (always allow)."""
    if tool_name in _SHELL_TOOLS:
        cmd = args.get("CommandLine", "")
        return {
            "v": 1, "agent": "agy", "event": "pre_tool",
            "kind": "shell", "shell": "bash",
            "command": cmd,
            "paths": [], "ops": [],
            "tool_name": tool_name, "cwd": cwd,
        }

    if tool_name in _WRITE_TOOLS:
        path = args.get("Path", "")
        return {
            "v": 1, "agent": "agy", "event": "pre_tool",
            "kind": "write",
            "command": "",
            "paths": [path] if path else [],
            "ops": ["edit"] if path else [],
            "tool_name": tool_name, "cwd": cwd,
        }

    if tool_name in _MCP_TOOLS:
        server = args.get("ServerName", "")
        mcp_tool = args.get("ToolName", "")
        mcp_args_obj = args.get("Arguments", {})
        full_tool = f"mcp__{server}__{mcp_tool}" if server and mcp_tool else mcp_tool
        return {
            "v": 1, "agent": "agy", "event": "pre_tool",
            "kind": "mcp",
            "command": "",
            "paths": [], "ops": [],
            "mcp_tool": full_tool,
            "mcp_args": json.dumps(mcp_args_obj) if mcp_args_obj else "",
            "tool_name": tool_name, "cwd": cwd,
        }

    # other: not judged, always allow
    return None


def _run_engine(request: dict) -> dict:
    """Call run.py neutral pre-tool and return the parsed verdict."""
    payload = json.dumps(request, ensure_ascii=False)
    try:
        result = subprocess.run(
            [PYTHON, RUNPY, "neutral", "pre-tool",
             "--root", PROJECT, "--project", PROJECT],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=55,
        )
    except subprocess.TimeoutExpired:
        return {"decision": "deny",
                "reason": "GUARD INERT: skyguard engine timed out (AGY hook). Cannot evaluate."}
    except Exception as e:
        return {"decision": "deny",
                "reason": f"GUARD INERT: failed to launch skyguard engine: {e}"}

    stdout = result.stdout.decode("utf-8", errors="replace").strip()

    # Neutral adapter prefixes output with "SKYGUARD-OK\n" then JSON
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break

    # Engine failed or returned non-JSON
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    return {
        "decision": "deny",
        "reason": (f"GUARD INERT: skyguard engine returned unexpected output "
                   f"(exit {result.returncode}). "
                   f"Run: bash tools/hook-canary.sh\n"
                   f"stderr: {stderr[:300]}" if stderr else ""),
    }


def _to_agy(verdict: dict) -> dict:
    """Translate neutral verdict -> AGY PreToolUse response."""
    decision = verdict.get("decision", "deny")
    reason = verdict.get("reason", "") or verdict.get("context", "")

    # Map neutral decisions to AGY decisions
    # neutral: allow / deny / ask
    # AGY:     allow / deny / ask / force_ask
    if decision == "allow":
        out = {"decision": "allow"}
        if reason:
            out["reason"] = reason
        return out
    if decision == "deny":
        return {"decision": "deny", "reason": reason}
    # ask -> ask (AGY respects the user's "always allow" cache; force_ask ignores it)
    return {"decision": "ask", "reason": reason}


def _run_session_start(payload: dict) -> str:
    """Run run.py neutral session-start and return the session banner text."""
    raw = json.dumps(payload, ensure_ascii=False)
    try:
        result = subprocess.run(
            [PYTHON, RUNPY, "neutral", "session-start",
             "--root", PROJECT, "--project", PROJECT],
            input=raw.encode("utf-8"),
            capture_output=True,
            timeout=115,
        )
    except Exception as e:
        return f"SKYGUARD: session-start failed: {e}"

    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    if result.returncode != 0 or "SKYGUARD-OK" not in stdout.splitlines():
        err = " ".join(result.stderr.decode("utf-8", errors="replace").split())[:300]
        return f"SKYGUARD: session-start failed (exit {result.returncode}){': ' + err if err else ''}"
    if stdout.startswith("SKYGUARD-OK\n"):
        return stdout[len("SKYGUARD-OK\n"):].strip()
    elif stdout == "SKYGUARD-OK":
        return ""
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "SKYGUARD-OK":
            return "\n".join(lines[i + 1:]).strip()
    return stdout


def main() -> None:
    payload = _read_stdin()

    if not payload:
        # Empty payload: guard inert, deny to be safe
        out = {"decision": "deny",
               "reason": "GUARD INERT: AGY guard received no payload. Refusing."}
        print(json.dumps(out))
        return

    if payload.get("hookEventName") == "SessionStart" or payload.get("event") == "session_start":
        text = _run_session_start(payload)
        out = {"injectSteps": [{"systemMessage": {"systemMessage": text}}]}
        print(json.dumps(out))
        return

    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {}) or {}

    request = _make_request(tool_name, args, _cwd(payload))

    if request is None:
        # "other" kind — not guarded, allow silently
        print(json.dumps({"decision": "allow"}))
        return

    verdict = _run_engine(request)
    out = _to_agy(verdict)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
