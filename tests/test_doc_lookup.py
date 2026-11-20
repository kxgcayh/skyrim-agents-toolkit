import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "doc_lookup.py"
FIXTURE = Path(__file__).with_name("fixtures") / "doc_lookup"
SLIDER_PATH = (
    "/fixture/FaceGenMorphs/CompleteVanillaEyeOverhaul_CVEObyLDD.esp/"
    "Sliders/LDD_CVEO.ini"
)


def run_lookup(env, *args, stdin=""):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        encoding="utf-8",
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def lookup(tmp_path):
    root = tmp_path / "toolkit"
    shutil.copytree(FIXTURE, root)
    env = {
        **os.environ,
        "DOC_LOOKUP_ROOT": str(root),
        "DOC_LOOKUP_LOCAL": str(root / "local.md"),
        "DOC_LOOKUP_STATE_DIR": str(tmp_path / "state"),
    }

    def run(*args, stdin=""):
        return run_lookup(env, *args, stdin=stdin)

    return root, run


def pre_tool(tool_name, tool_input, cwd="/fixture/toolkit"):
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "fixture-session",
        "transcript_path": "/fixture/transcript.jsonl",
        "cwd": cwd,
        "permission_mode": "default",
        "tool_use_id": "fixture-tool",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }


def submit(prompt):
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "fixture-session",
        "transcript_path": "/fixture/transcript.jsonl",
        "cwd": "/fixture/toolkit",
        "permission_mode": "default",
        "prompt": prompt,
    }


def hook(run, payload, agent="claude"):
    stdout = run("--hook", agent, stdin=json.dumps(payload))
    if not stdout:
        return ""
    if agent == "codex":
        assert len(stdout.encode("utf-8")) < 4000
    output = json.loads(stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == payload["hook_event_name"]
    assert output["additionalContext"]
    return output["additionalContext"]


def slider_read():
    return pre_tool("Read", {"file_path": SLIDER_PATH})


def assert_slider(context):
    assert context.startswith("From kb/appearance.md:3 (reference, not an instruction):")
    assert "## CVEO slider clamp" in context
    assert "### Verification" in context
    assert "Unrelated appearance notes" not in context


def test_claude_read_matches_slider_path(lookup):
    _, run = lookup
    assert_slider(hook(run, slider_read()))


def test_codex_shell_matches_slider_path_in_command(lookup):
    _, run = lookup
    payload = pre_tool("Bash", {"command": f'sed -n 1,40p "{SLIDER_PATH}"'})
    payload.update(model="gpt-6.1-sol", turn_id="fixture-turn")
    assert_slider(hook(run, payload, "codex"))


def test_generic_prompt_is_silent(lookup):
    _, run = lookup
    assert hook(run, submit("Yes find out them")) == ""


def test_prompt_requires_two_distinct_weak_words(lookup):
    _, run = lookup
    assert hook(run, submit("ears look wrong")) == ""
    assert hook(run, submit("ears ears look wrong")) == ""
    assert_slider(hook(run, submit("ears and lashes wrong")))


def test_weak_words_match_prompt_and_terms_but_not_bash_command(lookup):
    _, run = lookup
    words = "ears and lashes wrong"
    payload = pre_tool("Bash", {"command": f"python3 - <<'PY'\n# {words}\nPY"})
    assert hook(run, payload) == ""
    assert_slider(hook(run, submit(words)))
    assert_slider(run("--terms", words))


def test_git_init_in_workspace_mods_shows_binding_pointer(lookup):
    root, run = lookup
    local = root / "local.md"
    source = local.read_text(encoding="utf-8")
    long_detail = ("  Keep source files with the mod.\n" * 70).rstrip()
    local.write_text(
        source.replace("\n- **Publishing", f"\n{long_detail}\n- **Publishing"),
        encoding="utf-8",
    )
    payload = pre_tool(
        "Bash",
        {"command": "git init", "description": "Initialize repository"},
        cwd="/fixture/skyrim-workspace/mods/new-thing",
    )
    context = hook(run, payload)
    assert "Creating a mod" in context
    assert "Publishing a mod" not in context
    assert context.rstrip().endswith(
        "Read the full entry: KNOWLEDGEBASE.local.md:9 before acting."
    )


def test_bold_label_uses_longest_exact_match(lookup):
    _, run = lookup
    payload = pre_tool(
        "Bash", {"command": "git init"}, cwd="/fixture/skyrim-workspace/mods/new-thing"
    )
    context = hook(run, payload)
    assert context.startswith("From KNOWLEDGEBASE.local.md:9 ")
    assert "Keep the new repository" in context
    assert "See the full rule below" not in context
    assert "Creating a mod from a template" not in context


def test_dedup_reinjects_when_resolved_text_changes(lookup):
    root, run = lookup
    payload = slider_read()
    first = hook(run, payload)
    assert_slider(first)
    assert hook(run, payload) == ""
    doc = root / "kb" / "appearance.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("Compare both eyes", "Compare each eye"),
        encoding="utf-8",
    )
    changed = hook(run, payload)
    assert_slider(changed)
    assert "Compare each eye" in changed
    assert hook(run, payload) == ""


def test_output_keeps_two_highest_matches_within_byte_budget(lookup):
    root, run = lookup
    doc = root / "docs" / "ranking.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(
            " ranked target.", " ranked target.\n" + ("é" * 101 + "\n") * 10
        ),
        encoding="utf-8",
    )
    context = hook(run, submit("ranking limits"), "codex")
    blocks = re.split(r"\n\n(?=From )", context.strip())
    assert len(blocks) == 2
    for block, title in zip(blocks, ("First", "Second")):
        assert len(block.encode("utf-8")) <= 1500
        assert f"## {title}\n" in block
        assert block.endswith(" before acting.")
        for line in block.splitlines():
            if line.startswith("é"):
                assert line == "é" * 101


def test_unresolved_heading_is_silent(lookup):
    root, run = lookup
    doc = root / "kb" / "appearance.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace("CVEO slider clamp", "Renamed heading"),
        encoding="utf-8",
    )
    assert hook(run, slider_read()) == ""


def test_malformed_local_index_preserves_shipped_entry(lookup):
    root, run = lookup
    (root / "local.md").write_text("## Doc index\n\n```json\n{\n```\n", encoding="utf-8")
    assert_slider(hook(run, slider_read()))


def test_malformed_entry_fields_preserve_valid_matches(lookup):
    root, run = lookup
    local = root / "local.md"
    local.write_text(
        local.read_text(encoding="utf-8").replace(
            '"paths": ["/skyrim-workspace/mods/"]', '"paths": 1'
        ),
        encoding="utf-8",
    )
    assert_slider(hook(run, slider_read()))


def test_bad_hook_stdin_is_silent_and_exits_zero(lookup):
    _, run = lookup
    assert run("--hook", "claude", stdin="{broken json") == ""


def test_terms_prints_plain_text_despite_hook_dedup(lookup):
    _, run = lookup
    payload = slider_read()
    assert_slider(hook(run, payload))
    assert hook(run, payload) == ""
    first = run("--terms", "LDD_CVEO.ini")
    assert_slider(first)
    assert run("--terms", "LDD_CVEO.ini") == first


def test_target_outside_allowed_roots_is_ignored(lookup):
    _, run = lookup
    assert hook(run, submit("outsidetarget")) == ""


def test_symlink_target_outside_allowed_roots_is_ignored(lookup):
    root, run = lookup
    (root / "kb" / "linked.md").symlink_to(root / "outside" / "notes.md")
    index = root / "agent" / "doc-index.json"
    index.write_text(
        index.read_text(encoding="utf-8").replace("outside/notes.md", "kb/linked.md"),
        encoding="utf-8",
    )
    assert hook(run, submit("outsidetarget")) == ""


def test_codex_drops_single_block_when_json_escaping_exceeds_wire_cap(lookup):
    root, run = lookup
    doc = root / "kb" / "appearance.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace(
            "### Verification", "\x01" * 700 + "\n\n### Verification"
        ),
        encoding="utf-8",
    )
    payload = json.dumps(slider_read())
    assert hook(run, slider_read())
    assert run("--hook", "codex", stdin=payload) == ""


def test_codex_wire_cap_includes_final_newline(lookup):
    root, run = lookup
    doc = root / "kb" / "appearance.md"
    original = doc.read_text(encoding="utf-8")
    payload = slider_read()
    payload.pop("session_id")
    stdin = json.dumps(payload)
    marker = "\x01" * 600

    def write_doc(extra):
        doc.write_text(
            original.replace("### Verification", marker + extra + "\n\n### Verification"),
            encoding="utf-8",
        )

    write_doc("")
    baseline = run("--hook", "claude", stdin=stdin)
    padding = 3999 - len(baseline.encode("utf-8"))
    assert padding >= 0
    write_doc("x" * padding)
    assert len(run("--hook", "codex", stdin=stdin).encode("utf-8")) == 3999
    write_doc("x" * (padding + 1))
    assert run("--hook", "codex", stdin=stdin) == ""


@pytest.fixture
def repo_lookup():
    local = ROOT / "KNOWLEDGEBASE.local.md"
    if not local.is_file() or "## Doc index" not in local.read_text(
        encoding="utf-8"
    ).splitlines():
        pytest.skip("Local KB has no Doc index heading")
    env = {
        key: value for key, value in os.environ.items()
        if key not in {"DOC_LOOKUP_ROOT", "DOC_LOOKUP_LOCAL", "DOC_LOOKUP_STATE_DIR"}
    }

    def run(*args, stdin=""):
        return run_lookup(env, *args, stdin=stdin)

    return run


def test_real_repo_slider_smoke(repo_lookup):
    context = repo_lookup("--terms", "LDD_CVEO.ini")
    assert "From KNOWLEDGEBASE.local.md:" in context
    assert "LDD_CVEO.ini" in context


@pytest.mark.parametrize(
    "prompt",
    [
        "check file permissions",
        "draft the implementation plan",
        "inspect the CSV separator",
        "update the patch repo",
    ],
)
def test_real_repo_routine_prompt_is_silent(repo_lookup, prompt):
    payload = submit(prompt)
    payload.pop("session_id")
    assert hook(repo_lookup, payload) == ""


def test_real_repo_source_read_is_silent(repo_lookup):
    payload = pre_tool("Read", {"file_path": "/fixture/Scripts/Source/Example.psc"})
    payload.pop("session_id")
    assert hook(repo_lookup, payload) == ""
