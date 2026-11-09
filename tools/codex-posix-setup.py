#!/usr/bin/env python3
"""codex-posix-setup -- configure the Codex hooks on macOS/Linux without touching the frozen Windows renderer.

    python3 tools/codex-posix-setup.py [--root DIR] [--python PY] [--bash BASH]          # dry run
    python3 tools/codex-posix-setup.py ... --apply                                      # write

Fills `.codex/hooks.json` (`{{CODEX_ROOT_POSIX}}`, `{{CODEX_ROOT}}` -> the POSIX root, and the plain `bash`
launcher -> an absolute bash 4.4+, because Apple's /bin/bash 3.2 is rejected by the entry script) and the
`{{PYTHON_PATH}}` / `{{BASH_PATH}}` placeholders in `.codex/hooks/skyguard-entry.sh`. `commandWindows` is
rendered but unused off Windows. Reuses the root checks of tools/skyguard/codex_definitions.py.
Codex runs the hooks only after the user approves them (`/hooks` in codex); this never does that.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "skyguard"))
from codex_definitions import RootRefused, normalise_posix, root_problem  # noqa: E402

BASH_BAD = re.compile(r"[\s\"'$`\\]")


def bash_ok(bash: str) -> str | None:
    if BASH_BAD.search(bash) or not bash.startswith("/"):
        return "bash path must be absolute with no spaces or quotes: {!r}".format(bash)
    try:
        v = subprocess.run([bash, "-c", "echo ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
        major, minor = (int(x) for x in v.split("."))
    except Exception as e:  # noqa: BLE001
        return "cannot run {}: {}".format(bash, e)
    return None if (major, minor) >= (4, 4) else "bash {} is older than 4.4: {}".format(v, bash)


def render_hooks(template: str, root: str, bash: str) -> str:
    p = root_problem(root)
    if p:
        raise RootRefused(p)
    posix = normalise_posix(root)
    out = template.replace("{{CODEX_ROOT_POSIX}}", posix).replace("{{CODEX_ROOT}}", posix)
    out = out.replace('"command": "bash ', '"command": "{} '.format(bash))
    if "{{" in out:
        raise RootRefused("the template has a placeholder this tool does not fill")
    json.loads(out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="codex-posix-setup")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--bash", default=shutil.which("bash") or "/bin/bash")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    hooks, entry = root / ".codex/hooks.json", root / ".codex/hooks/skyguard-entry.sh"
    problem = bash_ok(a.bash)
    if problem:
        print("NOT configured:", problem, file=sys.stderr)
        return 2
    try:
        h_old, e_old = hooks.read_text(encoding="utf-8"), entry.read_text(encoding="utf-8")
        h_new = render_hooks(h_old, str(root), a.bash) if "{{CODEX_ROOT" in h_old else h_old
    except (RootRefused, OSError, ValueError) as e:
        print("NOT configured:", e, file=sys.stderr)
        return 2
    e_new = e_old.replace("{{PYTHON_PATH}}", a.python).replace("{{BASH_PATH}}", a.bash)
    print("hooks.json : {}".format("would render" if h_new != h_old else "already rendered"))
    print("entry .sh  : {}".format("would fill PY={} BASH_EXE={}".format(a.python, a.bash) if e_new != e_old else "already filled"))
    for line in h_new.splitlines():
        if '"command": "/' in line:
            print("  ", line.strip()[:170])
    if not a.apply:
        print("dry run: nothing written (add --apply)")
        return 0
    for path, new, old in ((hooks, h_new, h_old), (entry, e_new, e_old)):
        if new != old:
            tmp = path.with_name(path.name + ".new")
            tmp.write_text(new, encoding="utf-8", newline="")
            tmp.replace(path)
    print("written. Approve the 2 hooks in codex (/hooks) and keep this folder trusted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
