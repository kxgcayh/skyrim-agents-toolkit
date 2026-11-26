import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import BASH


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).with_name("fixtures") / "doc_lookup"
READ = {
    "hook_event_name": "PreToolUse",
    "session_id": "wrapper-test",
    "tool_name": "Read",
    "tool_input": {"file_path": "/fixture/FaceGenMorphs/Sliders/LDD_CVEO.ini"},
}
PAYLOAD = json.dumps(READ).encode("utf-8")


@pytest.fixture
def hook_root(tmp_path):
    root = tmp_path / "fixture toolkit"
    shutil.copytree(FIXTURE, root)
    (root / "tools").mkdir()
    for script in ("doc-inject.sh", "doc_lookup.py"):
        shutil.copyfile(ROOT / "tools" / script, root / "tools" / script)
    return root


def run_hook(root, agent="claude", stdin=PAYLOAD):
    env = {
        **os.environ,
        "DOC_LOOKUP_ROOT": str(root),
        "DOC_LOOKUP_LOCAL": str(root / "local.md"),
        "DOC_LOOKUP_STATE_DIR": str(root / "test-state"),
    }
    return subprocess.run(
        [BASH, str(root / "tools" / "doc-inject.sh"), agent],
        input=stdin,
        capture_output=True,
        cwd=root.parent,
        env=env,
        timeout=10,
    )


def write_paths(root, value):
    (root / "skyrim-paths.env").write_text(f"SKYGUARD_PYTHON={value}\n", encoding="utf-8")


def assert_success(result):
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""


def assert_slider(result):
    assert_success(result)
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["additionalContext"].startswith("From kb/appearance.md:3 ")
    assert "## CVEO slider clamp" in output["additionalContext"]


def test_read_passes_resolver_stdout_through(hook_root):
    write_paths(hook_root, sys.executable)
    result = run_hook(hook_root)
    assert_slider(result)
    direct = subprocess.run(
        [sys.executable, "-B", str(hook_root / "tools" / "doc_lookup.py"), "--hook", "claude"],
        input=PAYLOAD,
        capture_output=True,
        env={
            **os.environ,
            "DOC_LOOKUP_ROOT": str(hook_root),
            "DOC_LOOKUP_LOCAL": str(hook_root / "local.md"),
            "DOC_LOOKUP_STATE_DIR": str(hook_root / "direct-state"),
        },
        timeout=10,
    )
    assert_success(direct)
    assert result.stdout == direct.stdout


@pytest.mark.parametrize(
    "failure", ["no-paths", "no-python-key", "missing-python", "empty-stdin", "interpreter-failure"]
)
def test_hook_failures_are_silent(hook_root, failure):
    if failure == "no-python-key":
        (hook_root / "skyrim-paths.env").write_text("OTHER_SETTING=value\n", encoding="utf-8")
    if failure == "missing-python":
        write_paths(hook_root, hook_root / "missing-python")
    if failure in {"empty-stdin", "interpreter-failure"}:
        write_paths(hook_root, sys.executable)
    if failure == "interpreter-failure":
        (hook_root / "tools" / "doc_lookup.py").write_text(
            "import sys\nprint('{\"hookSpecificOutput\":')\n"
            "print('error', file=sys.stderr)\nsys.exit(1)\n",
            encoding="utf-8",
        )
    result = run_hook(hook_root, stdin=b"" if failure == "empty-stdin" else PAYLOAD)
    assert_success(result)
    assert result.stdout == b""


def test_single_quoted_interpreter_is_unquoted(hook_root):
    write_paths(hook_root, f"'{sys.executable}'")
    assert_slider(run_hook(hook_root))


def test_uses_claude_paths_file_when_root_file_is_missing(hook_root):
    fallback = hook_root / ".claude"
    fallback.mkdir()
    write_paths(fallback, sys.executable)
    assert_slider(run_hook(hook_root))


def test_root_paths_file_takes_precedence(hook_root):
    fallback = hook_root / ".claude"
    fallback.mkdir()
    write_paths(fallback, hook_root / "missing-python")
    write_paths(hook_root, sys.executable)
    assert_slider(run_hook(hook_root))


def test_codex_argument_and_state_override_pass_through(hook_root):
    write_paths(hook_root, sys.executable)
    assert_slider(run_hook(hook_root, agent="codex"))
    assert (hook_root / "test-state" / "codex-wrapper-test.json").is_file()


def test_invalid_agent_argument_defaults_to_claude(hook_root):
    write_paths(hook_root, sys.executable)
    assert_slider(run_hook(hook_root, agent="invalid-agent"))
    assert (hook_root / "test-state" / "claude-wrapper-test.json").is_file()


def command_hook(path, timeout, **options):
    return {
        "type": "command",
        "command": f'bash "$CLAUDE_PROJECT_DIR/{path}"',
        "timeout": timeout,
        **options,
    }


def test_claude_settings_wire_doc_inject_and_preserve_guard_hooks():
    source = (ROOT / "agent" / "targets" / "claude" / "settings.json").read_bytes()
    assert (ROOT / ".claude" / "settings.json").read_bytes() == source
    hooks = json.loads(source)["hooks"]
    inject = {
        "type": "command",
        "command": 'bash "$CLAUDE_PROJECT_DIR/tools/doc-inject.sh" claude',
        "timeout": 10,
    }
    assert hooks == {
        "PreToolUse": [
            {
                "matcher": "Bash|PowerShell|Monitor",
                "hooks": [
                    command_hook(
                        ".claude/hooks/protect-bash.sh", 60,
                        statusMessage="Checking command safety...", onFailure="block",
                    ),
                    command_hook(
                        ".claude/hooks/snapshot-before-tool.sh", 60,
                        statusMessage="Snapshotting scripts...",
                    ),
                ],
            },
            {
                "matcher": "Edit|Write|NotebookEdit",
                "hooks": [
                    command_hook(
                        ".claude/hooks/protect-files.sh", 60,
                        statusMessage="Checking file protection...", onFailure="block",
                    ),
                    command_hook(
                        ".claude/hooks/backup-before-edit.sh", 60,
                        statusMessage="Backing up file...",
                    ),
                ],
            },
            {
                "matcher": "mcp__.*[Dd][Ee][Vv][-_. ]?[Bb][Ee][Nn][Cc][Hh].*",
                "hooks": [
                    command_hook(
                        ".claude/hooks/protect-mcp.sh", 60,
                        statusMessage="Checking DevBench call...", onFailure="block",
                    ),
                ],
            },
            {"matcher": "Read|Grep|Glob|Bash|Edit|Write|NotebookEdit", "hooks": [inject]},
        ],
        "UserPromptSubmit": [{"hooks": [command_hook("tools/session-charter.sh", 30), inject]}],
        "SessionStart": [{
            "hooks": [
                command_hook(
                    ".claude/hooks/session-kb-guard.sh", 120,
                    statusMessage="Snapshotting the knowledgebase...",
                )
            ],
        }],
        "PostToolUse": [{
            "matcher": "Bash|PowerShell|Monitor|Edit|Write|NotebookEdit|mcp__.*",
            "hooks": [command_hook(".claude/hooks/save-sentinel.sh", 60)],
        }],
    }


def test_codex_hooks_wire_doc_inject_and_preserve_guard_hooks():
    source_bytes = (ROOT / "agent" / "targets" / "codex" / "hooks.json").read_bytes()
    source_hooks = json.loads(source_bytes)["hooks"]

    assert sorted(source_hooks) == ["PostToolUse", "PreToolUse", "SessionStart", "UserPromptSubmit"]
    assert len(source_hooks["SessionStart"][0]["hooks"]) == 1
    assert "skyguard-entry" in source_hooks["SessionStart"][0]["hooks"][0]["command"]

    pre_hooks = source_hooks["PreToolUse"][0]["hooks"]
    assert len(pre_hooks) == 2
    assert "skyguard-entry" in pre_hooks[0]["command"]
    assert pre_hooks[0]["timeout"] == 60

    assert pre_hooks[1] == {
        "type": "command",
        "command": 'bash "{{CODEX_ROOT_POSIX}}/tools/doc-inject.sh" codex',
        "commandWindows": 'bash "{{CODEX_ROOT}}/tools/doc-inject.sh" codex',
        "timeout": 10,
        "statusMessage": "Skyrim toolkit: checking documentation",
    }

    (prompt_group,) = source_hooks["UserPromptSubmit"]
    prompt_hooks = prompt_group["hooks"]
    assert len(prompt_hooks) == 2
    assert prompt_hooks[0] == pre_hooks[1]
    assert "skyguard-entry" in prompt_hooks[1]["command"] and prompt_hooks[1]["command"].endswith(" prompt")

    (post_group,) = source_hooks["PostToolUse"]
    assert len(post_group["hooks"]) == 1
    assert "skyguard-entry" in post_group["hooks"][0]["command"]
    assert post_group["hooks"][0]["command"].endswith(" post-tool")


def test_codex_definitions_render_wires_doc_inject():
    sys.path.insert(0, str(ROOT / "tools"))
    from skyguard.codex_definitions import render
    template = (ROOT / "agent" / "targets" / "codex" / "hooks.json").read_text(encoding="utf-8")
    rendered = render(template, "C:/Games/Skyrim", "/c/Games/Skyrim")
    hooks = json.loads(rendered)["hooks"]

    pre = hooks["PreToolUse"][0]["hooks"]
    assert len(pre) == 2
    assert pre[1]["command"] == 'bash "/c/Games/Skyrim/tools/doc-inject.sh" codex'
    assert pre[1]["commandWindows"] == 'bash "C:/Games/Skyrim/tools/doc-inject.sh" codex'
    assert pre[1]["timeout"] == 10
    (prompt_group,) = hooks["UserPromptSubmit"]
    assert prompt_group["hooks"][0] == pre[1]
    assert len(prompt_group["hooks"]) == 2


def test_codex_prompt_submit_passes_prompt_to_resolver(hook_root):
    write_paths(hook_root, sys.executable)
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "wrapper-test",
        "cwd": str(hook_root),
        "prompt": "My ears and lashes look wrong.",
    }
    result = run_hook(hook_root, "codex", json.dumps(payload).encode("utf-8"))
    assert_success(result)
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    assert "## CVEO slider clamp" in output["additionalContext"]
