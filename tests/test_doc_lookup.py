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
def repo_local_index(tmp_path):
    commands = {
        "local-creating-a-mod": [r"\bgit\s+init\b", r"\bmkdir\b.*\bmods/"],
        "local-releasing": [r"release\.py", r"\bgh\s+release\b"],
        "local-patching-source": ["link-submodules", r"\bgit\s+clone\b", r"\bgit\s+submodule\b"],
        "local-nexus": [r"nexus\.sh", "nexus-download", "nexusmods-surfer"],
    }
    local = tmp_path / "KNOWLEDGEBASE.local.md"
    entries = [
        {"id": key, "file": local.name, "commands": patterns, "targets": ["Fixture guidance"]}
        for key, patterns in commands.items()
    ]
    entries.append({"id": "local-slider", "file": local.name, "paths": ["LDD_CVEO.ini"],
                    "targets": ["Fixture guidance"]})
    index = json.dumps({"version": 1, "entries": entries})
    local.write_text(f"## Fixture guidance\n\nSee LDD_CVEO.ini.\n\n## Doc index\n\n```json\n{index}\n```\n",
                     encoding="utf-8")
    return local


@pytest.fixture
def repo_lookup(repo_local_index, tmp_path):
    env = {**os.environ, "DOC_LOOKUP_ROOT": str(ROOT), "DOC_LOOKUP_LOCAL": str(repo_local_index),
           "DOC_LOOKUP_STATE_DIR": str(tmp_path / "state")}

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


@pytest.mark.parametrize("agent", ["claude", "codex"])
@pytest.mark.parametrize("command", [
    "python3 - <<EOF\nprint('ranking nexusmods-surfer VMAD values')\nEOF",
    "python3 - <<'EOF'\nprint('ranking')\nEOF",
    'cat > plan.md <<"EOF"\nranking Caprica MO2 Spriggit\nEOF',
    "cat > plan.md <<-EOF\n\tranking\n\tEOF",
    "cat <<EOF\nranking",  # unfinished input is still advisory
    "cat <<A <<'B'\nranking\nA\nranking\nB",
    "python3 -c \"print('ranking')\"",
    "node -e 'console.log(\"ranking\")'",
    "bash -lc 'echo ranking'",
    "fish -c 'echo ranking'",
    "git commit -m 'ranking'",
    "git commit --message='ranking'",
    "git commit -mranking",
    "git commit -F - <<EOF\nranking\nEOF",
    "git commit -m \"$(cat <<'EOF'\nranking\nEOF\n)\"",
    "cat <<< 'ranking'",
])
def test_command_embedded_text_is_silent(lookup, command, agent):
    _, run = lookup
    assert hook(run, pre_tool("Bash", {"command": command}), agent) == ""


@pytest.mark.parametrize("command", [
    "ranking --flag /fixture/file",
    "cat <<EOF; ranking\nignored\nEOF",
    "cat <<'EOF'\nignored\nEOF\nranking",
    "cat <<-EOF && ranking\n\tignored\n\tEOF",
    "python3 -c 'print(123)' && ranking",
])
def test_real_command_survives_embedded_text_filter(lookup, command):
    _, run = lookup
    payload = pre_tool("Bash", {"command": command})
    assert "## First" in hook(run, payload)
    assert hook(run, payload) == ""


@pytest.mark.parametrize("command, expected", [
    ("caprica --game skyrim Script.psc", "kb-papyrus-compile"),
    ("champollion Example.pex -p /tmp/out", "kb-papyrus-compile"),
    ("bash tools/spriggit-cli.sh serialize --input Example.esp", "kb-spriggit"),
    ("spriggit serialize --input Example.esp", "kb-spriggit"),
    ("bash tools/nexusmods-surfer/run.sh 123", "local-nexus"),
    ("bash tools/nexus.sh mod 123", "local-nexus"),
    ("nexus-download 123", "local-nexus"),
    ("xelib inspect Example.esp", "kb-mo2-layout"),
    ("xeditlib inspect Example.esp", "kb-mo2-layout"),
    ("git init", "local-creating-a-mod"),
    ("mkdir /fixture/mods/example", "local-creating-a-mod"),
    ("git clone https://example.com/repo", "local-patching-source"),
    ("git submodule status", "local-patching-source"),
    ("bash tools/link-submodules.sh", "local-patching-source"),
    ("gh release view", "local-releasing"),
    ("python3 tools/release.py --help", "local-releasing"),
    ("python3 tools/foo.py -c tools/nexusmods-surfer/x.json", "local-nexus"),
    ("python3 -m tools.foo -c tools/nexusmods-surfer/x.json", "local-nexus"),
])
def test_repository_command_regexes_survive_filter(command, expected, repo_local_index, monkeypatch):
    import importlib.util
    monkeypatch.setenv("DOC_LOOKUP_ROOT", str(ROOT))
    monkeypatch.setenv("DOC_LOOKUP_LOCAL", str(repo_local_index))
    spec = importlib.util.spec_from_file_location("doc_lookup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entries = {entry["id"]: entry for entry in module.load_entries()}
    _, text, paths, cmd = module.event_from_payload(pre_tool("Bash", {"command": command}))
    assert module.score(entries[expected], text, paths, cmd, False, prompt=False) > 0


def test_explicit_paths_survive_code_filter(lookup):
    _, run = lookup
    payload = pre_tool("Bash", {"command": "python3 -c 'print(123)'", "path": SLIDER_PATH})
    assert_slider(hook(run, payload))


def test_codex_argv_keeps_inline_code_as_one_argument(lookup):
    _, run = lookup
    assert hook(run, pre_tool("Bash", {"command": ["python3", "-c", "print('ranking')"]}), "codex") == ""


@pytest.mark.parametrize("command", [
    "python3 tools/foo.py -c ranking",
    "python3 -m tools.foo -c ranking",
    "python3 -- tools/foo.py -c ranking",
    "bash tools/x.sh -e ranking",
    "node script.js -p ranking",
    "python3 tools/foo.py bash -c ranking",
    "ssh -c ranking host",
    "customsh -c ranking",
    "fishlike -c ranking",
    "python3 -c 'print(123)' ; node script.js -p ranking",
])
def test_script_flags_and_non_shell_programs_preserve_arguments(lookup, command):
    _, run = lookup
    assert "## First" in hook(run, pre_tool("Bash", {"command": command}))


@pytest.mark.parametrize("command", [
    "python3 - <<EOF\nprint('nexusmods-surfer VMAD values')\nEOF",
    "cat > note.md <<'EOF'\nracemenu-headpart-sliders\nEOF",
    "git commit -F - <<EOF\nCaprica MO2 layout Spriggit\nEOF",
    "cat > plan.md <<EOF\nCaprica MO2 layout Spriggit\nEOF",
    "python3 -c \"print('nexusmods-surfer VMAD values')\"",
    "node -e 'console.log(\"VMAD Caprica Spriggit\")'",
    "bash -c 'echo nexusmods-surfer VMAD'",
    "python3 -W ignore -c \"print('nexusmods-surfer VMAD values')\"",
    "python3 -X dev -c \"print('nexusmods-surfer VMAD values')\"",
    "node -r ./hook.js -e 'console.log(\"VMAD Caprica Spriggit\")'",
    "bash -o pipefail -c 'echo nexusmods-surfer VMAD'",
])
def test_reported_false_positives_against_repository_index(repo_lookup, command):
    payload = pre_tool("Bash", {"command": command})
    payload.pop("session_id")
    assert hook(repo_lookup, payload) == ""


def test_devbench_invocation_keeps_command_path(lookup):
    root, run = lookup
    index = root / "agent" / "doc-index.json"
    data = json.loads(index.read_text())
    data["entries"].append({
        "id": "devbench", "file": "docs/ranking.md", "targets": ["Third"],
        "commands": [r"devbench-cli\.sh"],
    })
    index.write_text(json.dumps(data))
    assert "## Third" in hook(run, pre_tool("Bash", {
        "command": "bash tools/devbench-cli.sh health",
    }))
