"""Contract tests for the centralized Traveling Agent PoC quality workflow."""
from pathlib import Path
import os
import json
import subprocess
import pytest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path(os.environ.get("TRAVELING_WORKFLOW_UNDER_TEST", ROOT / ".github/workflows/traveling-agent-poc-quality.yml"))


def load_workflow():
    assert WORKFLOW.is_file()
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_reusable_workflow_preserves_security_runner_and_concurrency_contract():
    workflow = load_workflow()
    assert workflow.get("on", workflow.get(True)) == {"workflow_call": None}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is True
    group = workflow["concurrency"]["group"]
    assert "github.repository" in group
    assert "github.event.pull_request.number" in group
    assert "github.ref" in group
    assert group == (
        "traveling-agent-poc-quality-${{ github.repository }}-"
        "${{ github.event.pull_request.number || format('{0}-{1}', github.event_name, github.ref) }}"
    )
    assert "github.sha" not in group and "github.run_id" not in group
    job = workflow["jobs"]["offline-contracts"]
    assert job["runs-on"] == {
        "group": "CWL CI isolated",
        "labels": ["self-hosted", "Linux", "X64", "cwlab-ci-isolated"],
    }
    assert job["timeout-minutes"] == 10
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "ubuntu-latest" not in source
    assert "secrets:" not in source
    assert "continue-on-error" not in source


def test_workload_steps_and_checkout_security_are_unchanged():
    workflow = load_workflow()
    steps = workflow["jobs"]["offline-contracts"]["steps"]
    assert [step["name"] for step in steps[-3:]] == [
        "Verify offline Python contracts",
        "Verify JavaScript syntax and real renderer contract",
        "Check whitespace",
    ]
    checkout = next(step for step in steps if "actions/checkout@" in step.get("uses", ""))
    assert checkout["uses"] == "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["fetch-depth"] == 0
    assert "github.event.pull_request.head.sha" in checkout["with"]["ref"]
    assert "github.sha" in checkout["with"]["ref"]
    assert steps[-3]["run"] == "python3 -m unittest discover -s poc/tests -v"
    assert steps[-2]["run"].splitlines() == [
        "node --check poc/web/app.js",
        "node poc/tests/ui_contract_test.js",
    ]


def _whitespace_step():
    steps = load_workflow()["jobs"]["offline-contracts"]["steps"]
    return next(step for step in steps if step["name"] == "Check whitespace")


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_whitespace_probe_rejects_committed_trailing_space_in_pr_range(tmp_path):
    """A clean checkout must still check committed base-to-head content."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "tracked.txt").write_text("committed trailing space  \n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "bad head")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    env = {
        **os.environ,
        "EVENT_NAME": "pull_request",
        "BASE_SHA": base,
        "HEAD_SHA": head,
        "BEFORE_SHA": "",
        "AFTER_SHA": head,
    }
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", _whitespace_step()["run"]],
        cwd=repo, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, result.stdout + result.stderr


def test_whitespace_probe_accepts_clean_committed_pr_range(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "tracked.txt").write_text("cleaner\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "clean head")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    env = {
        **os.environ,
        "EVENT_NAME": "pull_request",
        "BASE_SHA": base,
        "HEAD_SHA": head,
        "BEFORE_SHA": "",
        "AFTER_SHA": head,
    }
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", _whitespace_step()["run"]],
        cwd=repo, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("event, root", [
    ("pull_request", False), ("push", False), ("push", True),
    ("workflow_dispatch", False), ("workflow_dispatch", True),
])
@pytest.mark.parametrize("bad", [False, True])
def test_whitespace_event_ranges(tmp_path, event, root, bad):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    if not root:
        (repo / "base.txt").write_text("base\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "base")
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    else:
        base = "0" * 40
    (repo / "candidate.txt").write_text("candidate  \n" if bad else "candidate\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "candidate")
    if event in ("pull_request", "push") and not root:
        # The earlier bad addition remains in a multi-commit event range.
        (repo / "later.txt").write_text("later clean commit\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-qm", "later")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _git(repo, "status", "--porcelain").stdout == ""
    env = {**os.environ, "EVENT_NAME": event, "BASE_SHA": base,
           "HEAD_SHA": head, "BEFORE_SHA": base, "AFTER_SHA": head}
    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", _whitespace_step()["run"]],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=10)
    assert (result.returncode == 0) is (not bad), result.stdout + result.stderr
    if bad:
        assert "trailing whitespace" in result.stdout, result.stdout + result.stderr


@pytest.mark.parametrize("mutation", [
    "missing_base", "bad_base", "missing_before", "bad_before", "wrong_head",
    "wrong_after", "unsupported", "shallow",
])
def test_whitespace_range_fails_closed(tmp_path, mutation):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "clean.txt").write_text("clean\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "root")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    env = {**os.environ, "EVENT_NAME": "pull_request", "BASE_SHA": head,
           "HEAD_SHA": head, "BEFORE_SHA": head, "AFTER_SHA": head}
    if mutation in ("missing_base", "bad_base"):
        env["BASE_SHA"] = "a" * 40 if mutation == "missing_base" else "$(touch sentinel)"
    elif mutation in ("missing_before", "bad_before", "wrong_after"):
        env["EVENT_NAME"] = "push"
        if mutation == "wrong_after":
            env["AFTER_SHA"] = "0" * 40
        else:
            env["BEFORE_SHA"] = "a" * 40 if mutation == "missing_before" else ""
    elif mutation == "wrong_head":
        env["HEAD_SHA"] = "a" * 40
    elif mutation == "unsupported":
        env["EVENT_NAME"] = "pull_request_target"
    else:
        (repo / ".git/shallow").write_text(head + "\n")
    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", _whitespace_step()["run"]],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not (repo / "sentinel").exists()


def test_whitespace_policy_uses_env_without_expression_interpolation():
    step = _whitespace_step()
    assert "${{" not in step["run"]
    assert step["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha || github.sha }}",
        "BEFORE_SHA": "${{ github.event.before }}",
        "AFTER_SHA": "${{ github.event.after }}",
    }
    assert "complete history" in step["run"]


def test_admission_rejects_forks_and_non_main_non_pr_runs():
    steps = load_workflow()["jobs"]["offline-contracts"]["steps"]
    admission = steps[0]
    assert admission["name"] == "Admit owned same-repository caller"
    script = admission["run"]
    assert "ContextualWisdomLab/traveling-agent" in script
    assert "pull_request" in script and "push" in script and "workflow_dispatch" in script
    assert "pr['head']['repo']['full_name']" in script
    assert "pr['base']['ref'] == 'main'" in script
    assert "GITHUB_EVENT_PATH" in script


@pytest.mark.parametrize("event, mutation, allowed", [
    ("pull_request", "none", True),
    ("push", "none", True),
    ("workflow_dispatch", "none", True),
    ("pull_request", "fork", False),
    ("pull_request", "base_repo", False),
    ("pull_request", "base_branch", False),
    ("pull_request", "missing_sha", False),
    ("pull_request", "bad_sha", False),
    ("pull_request", "sha_mismatch", False),
    ("push", "tag", False),
    ("workflow_dispatch", "branch", False),
    ("pull_request_target", "none", False),
    ("pull_request", "foreign_caller", False),
])
def test_actual_admission_shell(tmp_path, event, mutation, allowed):
    """Execute actual workflow shell with inert event JSON; no GitHub/runner claim."""
    repo = "ContextualWisdomLab/traveling-agent"
    sha = "a" * 40
    payload = {"pull_request": {
        "head": {"repo": {"full_name": repo}, "sha": sha},
        "base": {"repo": {"full_name": repo}, "ref": "main"},
    }}
    ref = "refs/heads/main"
    if mutation == "fork":
        payload["pull_request"]["head"]["repo"]["full_name"] = "outsider/fork"
    if mutation == "base_repo":
        payload["pull_request"]["base"]["repo"]["full_name"] = "outsider/base"
    if mutation == "base_branch":
        payload["pull_request"]["base"]["ref"] = "develop"
    if mutation == "missing_sha":
        del payload["pull_request"]["head"]["sha"]
    if mutation == "bad_sha":
        payload["pull_request"]["head"]["sha"] = "not-a-commit"
    if mutation == "sha_mismatch":
        payload["pull_request"]["head"]["sha"] = "b" * 40
    if mutation == "tag":
        ref = "refs/tags/main"
    if mutation == "branch":
        ref = "refs/heads/develop"
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(payload))
    env = {"PATH": os.environ["PATH"], "CALLER_REPOSITORY": repo,
           "CALLER_EVENT": event, "GITHUB_EVENT_PATH": str(event_path),
           "GITHUB_REF": ref, "EXPECTED_SHA": sha}
    if mutation == "foreign_caller":
        env["CALLER_REPOSITORY"] = "outsider/repository"
    script = load_workflow()["jobs"]["offline-contracts"]["steps"][0]["run"]
    result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                            env=env, capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr


def test_pr_denied_before_runner_admission():
    gate = load_workflow()["jobs"]["offline-contracts"]["if"]
    assert "github.repository == 'ContextualWisdomLab/traveling-agent'" in gate
    assert "github.event.pull_request.head.repo.full_name == github.repository" in gate
    assert "github.event.pull_request.base.repo.full_name == github.repository" in gate
    assert "github.event.pull_request.base.ref == 'main'" in gate
    assert "github.ref == 'refs/heads/main'" in gate
    assert "github.event_name == 'push'" in gate
    assert "github.event_name == 'workflow_dispatch'" in gate


@pytest.mark.parametrize("case, allowed", [
    ("valid", True), ("wrong_head", False), ("missing_node", False),
    ("version_failure", False), ("nonexecutable_node", False),
    ("relative_tool_path", False),
])
def test_actual_toolchain_guard(tmp_path, case, allowed):
    tools = tmp_path / "tools"
    tools.mkdir()
    sha = "a" * 40
    for tool in ("python3", "node", "git"):
        path = tools / tool
        content = "#!/bin/sh\n"
        if tool == "git":
            content += 'if [ "$1" = rev-parse ]; then printf "%s\\n" "' + sha + '"; exit 0; fi\n'
        content += "exit 0\n"
        if case == "version_failure" and tool == "node":
            content = "#!/bin/sh\nexit 7\n"
        path.write_text(content)
        path.chmod(0o755)
    if case == "missing_node":
        (tools / "node").unlink()
    if case == "nonexecutable_node":
        (tools / "node").chmod(0o644)
    env = {"PATH": "tools" if case == "relative_tool_path" else str(tools),
           "EXPECTED_SHA": "b" * 40 if case == "wrong_head" else sha}
    script = load_workflow()["jobs"]["offline-contracts"]["steps"][2]["run"]
    result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) is allowed, result.stdout + result.stderr


def _documented_caller():
    doc = (ROOT / "docs/traveling-agent-poc-quality.md").read_text(encoding="utf-8")
    return yaml.safe_load(doc.split("```yaml\n", 1)[1].split("```", 1)[0])


def _group_key(group, repository, event, ref, number=None):
    """Evaluate only the two supported, asserted expression forms; never eval."""
    fallback = "${{ github.event.pull_request.number || format('{0}-{1}', github.event_name, github.ref) }}"
    rendered = group.replace(fallback, str(number) if number else f"{event}-{ref}")
    rendered = rendered.replace("${{ github.repository }}", repository)
    rendered = rendered.replace("${{ github.ref }}", ref)
    assert "${{" not in rendered, "Unsupported concurrency expression"
    return rendered


def test_caller_probe_push_and_dispatch_do_not_collide():
    group = _documented_caller()["concurrency"]["group"]
    keys = [_group_key(group, "ContextualWisdomLab/traveling-agent", event, "refs/heads/main")
            for event in ("push", "workflow_dispatch")]
    assert keys[0] != keys[1], keys


def test_caller_pr_coalescing_and_supplier_namespace():
    group = _documented_caller()["concurrency"]["group"]
    repo = "ContextualWisdomLab/traveling-agent"
    key = _group_key(group, repo, "pull_request", "refs/pull/42/merge", 42)
    assert key == _group_key(group, repo, "pull_request", "refs/pull/42/head", 42)
    assert key != _group_key(group, repo, "pull_request", "refs/pull/43/merge", 43)
    assert key != _group_key(group, "other/repository", "pull_request", "refs/pull/42/merge", 42)
    assert key != _group_key(load_workflow()["concurrency"]["group"], repo,
                             "pull_request", "refs/pull/42/merge", 42)
    assert "github.sha" not in group and "github.event.pull_request.head.sha" not in group


def test_documented_caller_preserves_original_events_and_workflow_concurrency():
    caller = _documented_caller()
    assert caller.get("on", caller.get(True)) == {
        "pull_request": None, "push": {"branches": ["main"]}, "workflow_dispatch": None,
    }
    assert caller["permissions"] == {"contents": "read"}
    assert caller["concurrency"] == {
        "group": (
            "poc-quality-${{ github.repository }}-"
            "${{ github.event.pull_request.number || format('{0}-{1}', github.event_name, github.ref) }}"
        ), "cancel-in-progress": True,
    }
    assert caller["jobs"] == {"offline-contracts": {
        "uses": "ContextualWisdomLab/.github/.github/workflows/traveling-agent-poc-quality.yml@<CENTRAL_PROTECTED_MAIN_SHA>",
    }}
