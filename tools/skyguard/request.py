"""The agent-neutral request (spec section 5 contract), built by an adapter from its agent's payload.

The spec's fields come first; the rest are what adapters already know and the engine needs (telemetry,
per-session coverage, the patch op per path). `failure` set = the adapter could not translate the payload;
a blocking role must then refuse (spec 5.1) -- it is never read as an empty, harmless request.
"""
from __future__ import annotations

from typing import NamedTuple, Optional, Tuple


# Payload nesting limit, shared by every adapter that decodes agent JSON (Claude, Codex, neutral entry). A hook payload is a
# handful of levels deep (tool_input / args / one nested MCP argument object); 200 leaves room for any real MCP
# argument tree while refusing hostile depth by NAME. The json module's own limit is not a contract: CPython 3.15
# parses 100,000 levels without RecursionError, and json.dumps of such a tree may still raise later.
MAX_DEPTH = 200


def too_deep(text: str, limit: int = MAX_DEPTH) -> bool:
    """True when [ / { nest deeper than `limit` outside JSON strings: one linear pass, BEFORE json.loads. Stray
    closers never lower the count below zero (malformed text cannot buy back depth; json.loads refuses it anyway)."""
    depth, in_str, esc = 0, False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}":
            if depth:
                depth -= 1
    return False


class Request(NamedTuple):
    v: int = 1
    agent: str = ""
    event: str = ""                   # pre_tool | session_start | other
    kind: str = ""                    # shell | write | mcp | other | none
    shell: Optional[str] = None       # bash | powershell | None
    command: str = ""
    paths: Tuple[str, ...] = ()
    ops: Tuple[str, ...] = ()         # parallel to paths: add|update|delete|move_from|move_to|write|edit
    mcp_tool: str = ""
    mcp_args: str = ""
    cwd: str = ""                     # the agent's cwd string, RAW: never normalized (may be /c/x or C:\x)
    tool_name: str = ""
    session_id: str = ""
    transcript_path: str = ""
    source: str = ""
    empty: bool = False
    failure: str = ""
    execution_cwd_known: bool = True  # false: native host supplied session cwd only
