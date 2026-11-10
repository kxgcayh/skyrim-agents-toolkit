"""MCP server (stdio) for CrossOver on macOS: list bottles, run Windows programs, stop a bottle, launch MO2.

Standard library only: MCP over stdio is newline-delimited JSON-RPC 2.0, so no SDK is needed.
Register it with an MCP client as: python3 tools/crossover-mcp.py

Environment:
  CX_ROOT         CrossOver.app (default /Applications/CrossOver.app)
  CX_BOTTLE_PATH  folder holding the bottles (default ~/Library/Application Support/CrossOver/Bottles)
  CX_BOTTLE       default bottle name
  CX_MO2_DIR      default MO2 folder, Windows path (e.g. D:\\Modding\\MO2)

launch_mo2 starts a portable MO2 folder (one with portable.txt) freely. A folder without portable.txt runs a
global instance, which is the live mod setup, so it starts only when the call passes live=true.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

CX_ROOT = Path(os.environ.get("CX_ROOT", "/Applications/CrossOver.app"))
CX_BIN = CX_ROOT / "Contents/SharedSupport/CrossOver/bin"
BOTTLES = Path(os.path.expanduser(os.environ.get(
    "CX_BOTTLE_PATH", "~/Library/Application Support/CrossOver/Bottles")))
OUTPUT_CAP = 20000  # characters of output returned per call, from the end


class ToolError(Exception):
    pass


def bottle_dir(name: str | None) -> tuple[str, Path]:
    name = name or os.environ.get("CX_BOTTLE")
    if not name:
        raise ToolError("no bottle given and CX_BOTTLE is not set")
    path = BOTTLES / name
    if not (path / "cxbottle.conf").is_file():
        raise ToolError(f"bottle {name!r} not found in {BOTTLES}")
    return name, path


def wine_env() -> dict:
    return {**os.environ, "CX_BOTTLE_PATH": str(BOTTLES)}


def to_mac(bottle: Path, win_path: str) -> Path:
    """D:\\Modding\\MO2 -> the macOS path behind the bottle's D: drive."""
    if len(win_path) < 2 or win_path[1] != ":":
        raise ToolError(f"not a Windows drive path: {win_path!r}")
    drive = bottle / "dosdevices" / (win_path[0].lower() + ":")
    if not drive.exists():
        raise ToolError(f"drive {win_path[:2]} is not mapped in this bottle")
    rest = win_path[2:].replace("\\", "/").strip("/")
    return drive.resolve() / rest if rest else drive.resolve()


def tail(text: str) -> str:
    return text if len(text) <= OUTPUT_CAP else "[...cut...]\n" + text[-OUTPUT_CAP:]


def wine(bottle: str, exe: str, args: list[str], workdir: str | None, wait: bool, timeout: float,
         dry_run: bool = False) -> str:
    cmd = [str(CX_BIN / "wine"), "--bottle", bottle, "--no-convert", "--no-gui"]
    if workdir:
        cmd += ["--workdir", workdir]
    if not wait:
        cmd.append("--no-wait")
    cmd += [exe, *args]
    if dry_run:
        return "would run: " + shlex.join(cmd)
    try:
        if not wait:
            # a detached child would hold captured pipes open until it exits, so give it no pipes
            p = subprocess.Popen(cmd, env=wine_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            return f"started; wine exit code {p.wait(timeout)}"
        # stdin/stdout never inherited: stdout is the MCP channel
        p = subprocess.run(cmd, check=False, env=wine_env(), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        raise ToolError(f"timed out after {timeout:g}s; the program may still run (stop_bottle ends it)\n{tail(out)}")
    return f"exit code {p.returncode}\n--- stdout ---\n{tail(p.stdout)}\n--- stderr ---\n{tail(p.stderr)}"


def list_bottles(_):
    if not BOTTLES.is_dir():
        raise ToolError(f"{BOTTLES} does not exist (set CX_BOTTLE_PATH)")
    names = sorted(p.name for p in BOTTLES.iterdir() if (p / "cxbottle.conf").is_file())
    return "\n".join(names) or f"no bottles in {BOTTLES}"


def run(a):
    name, _ = bottle_dir(a.get("bottle"))
    return wine(name, a["exe"], a.get("args", []), a.get("workdir"), a.get("wait", True), a.get("timeout", 120))


def stop_bottle(a):
    name, path = bottle_dir(a.get("bottle"))
    p = subprocess.run([str(CX_BIN / "wineserver"), "-k"], check=False, env={**wine_env(), "WINEPREFIX": str(path)},
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    return f"wineserver -k in {name}: exit code {p.returncode} {p.stderr.strip()}"


def launch_mo2(a):
    name, path = bottle_dir(a.get("bottle"))
    mo2 = a.get("mo2_dir") or os.environ.get("CX_MO2_DIR")
    if not mo2:
        raise ToolError("no mo2_dir given and CX_MO2_DIR is not set")
    mac = to_mac(path, mo2)
    if not (mac / "ModOrganizer.exe").is_file():
        raise ToolError(f"no ModOrganizer.exe in {mo2} ({mac})")
    portable = (mac / "portable.txt").is_file()
    if not portable and not a.get("live") and not a.get("dry_run"):
        raise ToolError(
            f"{mo2} has no portable.txt, so it opens a global instance: the live mod setup. "
            "Pass live=true only when the user asked to launch the live instance.")
    args = []
    if a.get("instance"):
        args += ["-i", a["instance"]]
    if a.get("profile"):
        args += ["-p", a["profile"]]
    if a.get("executable"):  # an MO2 executable entry, started through the virtual file system
        args.append(f"moshortcut://{a.get('instance', '')}:{a['executable']}")
    out = wine(name, mo2.rstrip("\\") + "\\ModOrganizer.exe", args, mo2, wait=False, timeout=60,
               dry_run=a.get("dry_run", False))
    kind = "portable" if portable else "LIVE global instance" + ("" if a.get("live") else ", needs live=true")
    return f"{'dry run, nothing started' if a.get('dry_run') else 'started MO2'} ({kind}) from {mo2}\n{out}"


def mo2_log(a):
    _, path = bottle_dir(a.get("bottle"))
    if a.get("instance"):
        users = path / "drive_c/users"
        logs = [u / "AppData/Local/ModOrganizer" / a["instance"] / "logs" for u in users.iterdir()]
    else:
        mo2 = a.get("mo2_dir") or os.environ.get("CX_MO2_DIR")
        if not mo2:
            raise ToolError("give instance (global) or mo2_dir (portable), or set CX_MO2_DIR")
        logs = [to_mac(path, mo2) / "logs"]
    for d in logs:
        f = d / "mo_interface.log"
        if f.is_file():
            lines = f.read_text(errors="replace").splitlines()[-int(a.get("lines", 200)):]
            return f"{f}\n" + "\n".join(lines)
    raise ToolError("mo_interface.log not found in: " + ", ".join(map(str, logs)))


def screenshot(a):
    """The whole screen as a PNG image; the file never outlives the call."""
    fd, png = tempfile.mkstemp(prefix="crossover-mcp-", suffix=".png")
    os.close(fd)
    try:
        subprocess.run(["screencapture", "-x", png], check=True, stdin=subprocess.DEVNULL, capture_output=True,
                       timeout=30)
        if os.path.getsize(png) == 0:
            raise ToolError("screencapture wrote nothing: grant Screen Recording to the app running this server")
        subprocess.run(["sips", "-Z", str(int(a.get("max_size", 1400))), png], check=True,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        data = Path(png).read_bytes()
    finally:
        os.unlink(png)
    return [{"type": "image", "data": base64.b64encode(data).decode(), "mimeType": "image/png"}]


BOTTLE = {"type": "string", "description": "bottle name; default $CX_BOTTLE"}
TOOLS = {
    "list_bottles": (list_bottles, "List CrossOver bottles.", {}, []),
    "run": (run, ("Run a Windows program in a bottle and return its exit code and output. Paths are Windows paths "
                  "(D:\\..., Z:\\ is the Mac root). Builtins work too: reg, cmd, tasklist, winepath."), {
        "bottle": BOTTLE,
        "exe": {"type": "string", "description": "Windows path or name of the program"},
        "args": {"type": "array", "items": {"type": "string"}, "description": "arguments, each passed intact"},
        "workdir": {"type": "string", "description": "Windows working directory"},
        "wait": {"type": "boolean", "description": "wait for exit and capture output (default true); false for GUI apps"},
        "timeout": {"type": "number", "description": "seconds, default 120"},
    }, ["exe"]),
    "stop_bottle": (stop_bottle, ("Kill every Windows process in a bottle (wineserver -k). Unsaved work is lost. "
                                  "Also clears a stale display session after a crash."), {"bottle": BOTTLE}, []),
    "launch_mo2": (launch_mo2, ("Start Mod Organizer 2 in a bottle without waiting. A portable folder starts "
                                "freely; a global (live) instance needs live=true."), {
        "bottle": BOTTLE,
        "mo2_dir": {"type": "string", "description": "Windows path of the MO2 folder; default $CX_MO2_DIR"},
        "live": {"type": "boolean", "description": "required true to start a global instance (the live mod setup); "
                                                   "set it only when the user asked for the live instance"},
        "instance": {"type": "string", "description": "global instance name (-i)"},
        "profile": {"type": "string", "description": "profile name (-p)"},
        "executable": {"type": "string", "description": "MO2 executable entry to start through MO2, e.g. SKSE"},
        "dry_run": {"type": "boolean", "description": "return the command and instance kind without starting MO2"},
    }, []),
    "mo2_log": (mo2_log, "Return the end of MO2's mo_interface.log.", {
        "bottle": BOTTLE,
        "instance": {"type": "string", "description": "global instance name, e.g. SSEAE"},
        "mo2_dir": {"type": "string", "description": "portable MO2 folder (Windows path); default $CX_MO2_DIR"},
        "lines": {"type": "integer", "description": "default 200"},
    }, []),
    "screenshot": (screenshot, ("Capture the screen (e.g. to check a Wine window opened). The image file is deleted "
                                "as soon as it is read."), {
        "max_size": {"type": "integer", "description": "longest side in pixels, default 1400"},
    }, []),
}


def handle(msg: dict):
    method, params = msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "crossover", "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema":
                           {"type": "object", "properties": props, "required": req}}
                          for n, (_, d, props, req) in TOOLS.items()]}
    if method == "tools/call":
        tool = TOOLS.get(params.get("name"))
        if not tool:
            raise KeyError(params.get("name"))
        try:
            out = tool[0](params.get("arguments") or {})
            return {"content": out if isinstance(out, list) else [{"type": "text", "text": out}]}
        except (ToolError, OSError, KeyError, ValueError, subprocess.SubprocessError) as e:
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        if "id" not in msg:  # notification
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
        except LookupError as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"unknown: {e}"}}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
