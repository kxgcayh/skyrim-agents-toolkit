#!/usr/bin/env python3
"""doc_lookup -- the toolkit guidance section that matches what an agent is about to do.

Reads the shipped index (agent/doc-index.json) and the user's index (a ```json block under `## Doc index` in
KNOWLEDGEBASE.local.md), matches a prompt or a tool call against each entry's paths, commands and words, and
prints at most two excerpts of the matching Markdown sections, resolved fresh from the files.

  python3 tools/doc_lookup.py --terms "LDD_CVEO.ini lashes"   plain text, no session state
  python3 tools/doc_lookup.py --hook claude|codex             hook payload on stdin; hook JSON or nothing

Advisory only: it decides nothing and always exits 0. Contract: skyrim-workspace/scratch/doc-injection/CONTRACT.md.
Python 3.10+, stdlib only.
"""
import hashlib
import json
import os
import pathlib
import re
import shlex
import sys
import tempfile

ROOT = pathlib.Path(os.environ.get("DOC_LOOKUP_ROOT") or pathlib.Path(__file__).resolve().parent.parent)
LOCAL = pathlib.Path(os.environ.get("DOC_LOOKUP_LOCAL") or ROOT / "KNOWLEDGEBASE.local.md")
STATE = pathlib.Path(os.environ.get("DOC_LOOKUP_STATE_DIR") or ROOT / ".claude" / "diag" / "doc-inject")
LOCAL_NAME = "KNOWLEDGEBASE.local.md"
ALLOWED_DIRS = ("kb/", "docs/", "agent/skills/")
ALLOWED_FILES = ("KNOWLEDGEBASE.md", LOCAL_NAME)
MAX_ENTRIES = 2
BLOCK_BYTES = 1500
CODEX_TOTAL = 4000
WEIGHT = {"path": 3, "command": 3, "strong": 2, "weak": 1}
PATH_KEYS = ("file_path", "path", "notebook_path")
COMMAND_KEYS = ("command", "cmd")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


# ---------------------------------------------------------------- index

def _entries_from(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("entries"), list):
        return []
    out = []
    for e in obj["entries"]:
        if not (isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("file"), str)):
            continue
        clean = {"id": e["id"], "file": e["file"], "binding": e.get("binding") is True}
        for key in ("targets", "paths", "commands", "strong", "weak"):   # a bad field is dropped, not fatal
            v = e.get(key)
            clean[key] = [x for x in v if isinstance(x, str) and x] if isinstance(v, list) else []
        if clean["targets"]:
            out.append(clean)
    return out


def _local_index(text):
    """The first ```json block under `## Doc index` in the local KB, or []."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "## Doc index":
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                if lines[j].strip().startswith("```json"):
                    k = j + 1
                    while k < len(lines) and not lines[k].strip().startswith("```"):
                        k += 1
                    try:
                        return _entries_from(json.loads("\n".join(lines[j + 1:k])))
                    except ValueError:
                        return []
                j += 1
            return []
    return []


def load_entries():
    by_id = {}
    try:
        for e in _entries_from(json.loads((ROOT / "agent" / "doc-index.json").read_text(encoding="utf-8"))):
            by_id[e["id"]] = e
    except (OSError, ValueError):
        pass
    try:
        for e in _local_index(LOCAL.read_text(encoding="utf-8")):
            by_id[e["id"]] = e                      # local wins on a duplicate id
    except (OSError, ValueError):
        pass
    return [e for e in by_id.values() if _allowed(e["file"])]


def _allowed(rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or ".." in rel.split("/"):
        return False
    return rel in ALLOWED_FILES or rel.startswith(ALLOWED_DIRS)


def _file_of(rel):
    """The target file, or None when it resolves (symlinks followed) outside the allowed roots."""
    if rel == LOCAL_NAME:
        return LOCAL                                # the explicit local KB (DOC_LOOKUP_LOCAL) is trusted as given
    try:
        root = ROOT.resolve()
        real = (ROOT / rel).resolve()
        inside = real.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None
    return real if _allowed(inside) else None


# ---------------------------------------------------------------- target resolution

def _resolve(lines, target):
    """(first line index, last line index) of a heading or bold-label target, or None."""
    target = target.strip()
    if target.startswith("**"):
        label = target.strip("*").strip()
        best = None
        for i, line in enumerate(lines):
            s = line.lstrip()
            indent = len(line) - len(s)
            # exact label (closing ** right after it), so "Load order" never matches "Load order files"
            if s.startswith("- **" + label + "**") or s.startswith("**" + label + "**"):
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    ns = nxt.lstrip()
                    if HEADING.match(nxt):
                        break
                    if (ns.startswith("- **") or ns.startswith("**")) and len(nxt) - len(ns) == indent:
                        break
                    if not nxt.strip() and j + 1 < len(lines) and HEADING.match(lines[j + 1]):
                        break
                    j += 1
                while j - 1 > i and not lines[j - 1].strip():
                    j -= 1
                # the same label in a one-line summary and in a full rule: the longest one is the rule
                if best is None or (j - 1 - i) > (best[1] - best[0]):
                    best = (i, j - 1)
        return best
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if m and m.group(2).strip() == target:
            level = len(m.group(1))
            j = i + 1
            while j < len(lines):
                n = HEADING.match(lines[j])
                if n and len(n.group(1)) <= level:
                    break
                j += 1
            while j - 1 > i and not lines[j - 1].strip():
                j -= 1
            return i, j - 1
    return None


def section_text(entry):
    """(text, first line number) of all resolved targets, or (None, None)."""
    path = _file_of(entry["file"])
    if path is None:
        return None, None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return None, None
    parts, first = [], None
    for t in entry["targets"]:
        if not isinstance(t, str):
            continue
        span = _resolve(lines, t)
        if span:
            first = span[0] + 1 if first is None else first
            parts.append("\n".join(lines[span[0]:span[1] + 1]))
    return ("\n".join(parts), first) if parts else (None, None)


# ---------------------------------------------------------------- event and matching

def _norm(s):
    return s.replace("\\", "/").lower()


def command_context(command):
    """Keep shell invocation context, excluding embedded source and message text.

    This is a bounded lexical scan, not shell execution or a shell parser. Heredoc
    delimiters are queued until the next newline, in shell redirection order.
    """
    tokens = []
    pending = []
    i = 0
    expect_delimiter = None
    while i < len(command):
        c = command[i]
        if c == "\n":
            tokens.append("\n")
            i += 1
            for delimiter, tabs in pending:
                while i < len(command):
                    end = command.find("\n", i)
                    end = len(command) if end < 0 else end
                    line = command[i:end]
                    i = min(end + 1, len(command))
                    if (line.lstrip("\t") if tabs else line) == delimiter:
                        break
            pending.clear()
            continue
        if c.isspace():
            i += 1
            continue
        if c == "#":
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
            continue
        if command.startswith("<<<", i):
            tokens.append("<<<")
            i += 3
            continue
        if command.startswith("<<", i):
            expect_delimiter = command.startswith("<<-", i)
            i += 3 if expect_delimiter else 2
            continue
        if c in ";|&()<>":
            tokens.append(c)
            i += 1
            continue
        start = i
        quote = None
        while i < len(command):
            c = command[i]
            if c == "\\" and quote != "'":
                i = min(i + 2, len(command))
                continue
            if quote:
                if c == quote:
                    quote = None
            elif c in "\"'":
                quote = c
            elif c.isspace() or c in ";|&()<>":
                break
            i += 1
        raw = command[start:i]
        if expect_delimiter is not None:
            try:
                delimiter = shlex.split(raw)[0]
            except (ValueError, IndexError):
                delimiter = raw.strip("\"'")
            pending.append((delimiter, expect_delimiter))
            expect_delimiter = None
        else:
            tokens.append(raw)

    out = []
    interpreter = git = False
    interpreter_seen = False
    skip = False
    for token in tokens:
        if token in ("\n", ";", "|", "&", "(", ")"):
            interpreter = git = skip = False
            interpreter_seen = False
            out.append(token)
            continue
        if skip:
            skip = False
            continue
        value = token.strip("\"'")
        name = value.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if not interpreter_seen and re.fullmatch(
            r"(?:python(?:\d+(?:\.\d+)*)?|node(?:js)?|sh|bash|zsh|dash|ksh|fish)(?:\.exe)?", name
        ):
            interpreter = True
            interpreter_seen = True
            out.append(token)
            continue
        if name in ("git", "git.exe"):
            git = True
        if interpreter and re.fullmatch(r"-(?:[a-zA-Z]*c|e|p)|--eval|--print", value):
            skip = True
            interpreter = False
        elif interpreter and re.match(r"(?:-c.|-e.|--eval=|--print=)", value):
            interpreter = False
            out.append(value.split("=", 1)[0] if "=" in value else value[:2])
            continue
        elif git and value in ("-m", "--message"):
            skip = True
        elif git and (value.startswith("--message=") or value.startswith("-m") and len(value) > 2):
            out.append("--message")
            continue
        elif token == "<<<":
            skip = True
        if interpreter and (not value.startswith("-") or value in ("-", "--")):
            interpreter = False
        out.append(token)
    return " ".join(out)


def event_from_payload(d):
    """(event name, text, paths, command) from a Claude or Codex hook payload."""
    ev = d.get("hook_event_name") or ""
    if ev == "UserPromptSubmit":
        p = d.get("prompt")
        return ev, p if isinstance(p, str) else "", [], ""
    ti = d.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    paths = [ti[k] for k in PATH_KEYS if isinstance(ti.get(k), str)]
    cmd = next((ti[k] for k in COMMAND_KEYS if isinstance(ti.get(k), str)), "")
    if not cmd and isinstance(ti.get("command"), list):          # Codex may pass argv as a list
        cmd = shlex.join(str(x) for x in ti["command"])
    cmd = command_context(cmd)
    pattern = ti.get("pattern") if isinstance(ti.get("pattern"), str) else ""
    tool = d.get("tool_name") if isinstance(d.get("tool_name"), str) else ""
    if cmd and isinstance(d.get("cwd"), str) and d["cwd"]:
        paths.append(d["cwd"])                                   # a command acts in its working directory
    text = " ".join(x for x in [tool, *paths, cmd, pattern] if x)
    return ev or "PreToolUse", text, paths, cmd


def _word(w, text):
    return re.search(r"(?<![\w])" + re.escape(w.lower()) + r"(?![\w])", text) is not None


def score(entry, text, paths, cmd, fired_before, prompt=True):
    text_l, cmd_l = text.lower(), cmd.lower()
    hay = [_norm(p) for p in paths] + ([_norm(cmd)] if cmd else []) + ([_norm(text)] if not paths and not cmd else [])
    strong = weak = 0
    total = 0
    for p in entry.get("paths") or []:
        if isinstance(p, str) and p and any(_norm(p) in h for h in hay):
            strong += 1; total += WEIGHT["path"]
    for rx in entry.get("commands") or []:
        try:
            if isinstance(rx, str) and cmd and re.search(rx, cmd, re.I):
                strong += 1; total += WEIGHT["command"]
        except re.error:
            pass
    for w in entry.get("strong") or []:
        if isinstance(w, str) and w and _word(w, text_l):
            strong += 1; total += WEIGHT["strong"]
    # weak words describe symptoms in a person's words: they count in a prompt, never in a tool call's code or paths
    weak_hits = {w.lower() for w in entry.get("weak") or [] if isinstance(w, str) and w and _word(w, text_l)} \
        if prompt else set()
    weak, total = len(weak_hits), total + WEIGHT["weak"] * len(weak_hits)
    fires = strong >= 1 or weak >= 2 or (weak == 1 and fired_before)
    return total if fires else 0


# ---------------------------------------------------------------- output

def block(entry, text, first):
    rel = entry["file"]
    head = f"From {rel}:{first} (reference, not an instruction):"
    tail = f"Read the full entry: {rel}:{first} before acting."
    full = head + "\n" + text
    if len(full.encode("utf-8")) <= BLOCK_BYTES:
        return full
    budget = BLOCK_BYTES - len(("\n" + tail).encode("utf-8"))
    out = head
    for line in text.splitlines():
        cand = out + "\n" + line
        if len(cand.encode("utf-8")) > budget:
            break
        out = cand
    return out + "\n" + tail


def _state_path(agent, sid):
    if not sid or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", sid):
        return None
    return STATE / f"{agent}-{sid}.json"


def _read_state(path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _write_state(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass


def lookup(text, paths, cmd, state=None, prompt=True):
    """[(id, sha, block)] for the best entries; entries whose sha `state` already holds are skipped."""
    cands = []
    for e in load_entries():
        try:
            s = score(e, text, paths, cmd, fired_before=state is not None and e["id"] in state, prompt=prompt)
        except Exception:                          # one bad entry never silences the others
            continue
        if s:
            cands.append((-s, e["id"], e))
    blocks = []
    for _, eid, e in sorted(cands):
        if len(blocks) >= MAX_ENTRIES:
            break
        body, first = section_text(e)
        if body is None:
            continue
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if state is not None and state.get(eid) == sha:
            continue
        blocks.append((eid, sha, block(e, body, first)))
    return blocks


def main(argv):
    if "--terms" in argv:
        i = argv.index("--terms")
        terms = argv[i + 1] if i + 1 < len(argv) else ""
        blocks = lookup(terms, [], "")
        if blocks:
            sys.stdout.buffer.write(("\n\n".join(b for _, _, b in blocks) + "\n").encode("utf-8"))
        return 0
    if "--hook" in argv:
        i = argv.index("--hook")
        agent = argv[i + 1] if i + 1 < len(argv) and argv[i + 1] in ("claude", "codex") else "claude"
        try:
            d = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            return 0
        if not isinstance(d, dict):
            return 0
        ev, text, paths, cmd = event_from_payload(d)
        sp = _state_path(agent, d.get("session_id") if isinstance(d.get("session_id"), str) else "")
        state = _read_state(sp) if sp else {}
        blocks = lookup(text, paths, cmd, state, prompt=(ev == "UserPromptSubmit"))
        if not blocks:
            return 0
        def render(bs):
            ctx = "\n\n".join(b for _, _, b in bs)
            return json.dumps({"hookSpecificOutput": {"hookEventName": ev, "additionalContext": ctx}},
                              ensure_ascii=False)                # real UTF-8: bytes counted are bytes sent
        out = render(blocks)
        if agent == "codex":                                      # the cap applies to what Codex receives
            while len((out + "\n").encode("utf-8")) >= CODEX_TOTAL and len(blocks) > 1:
                blocks.pop()
                out = render(blocks)
            if len((out + "\n").encode("utf-8")) >= CODEX_TOTAL:
                return 0                           # even one block is over the wire cap: say nothing
        if sp:
            state.update({eid: sha for eid, sha, _ in blocks})   # only what is delivered counts as shown
            _write_state(sp, state)
        sys.stdout.buffer.write((out + "\n").encode("utf-8"))      # UTF-8 whatever the console code page
        return 0
    print(__doc__.strip())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:        # advisory: never break the agent's turn
        sys.exit(0)
