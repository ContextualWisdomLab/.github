"""Execute candidate-job admission from real YAML, before runner allocation.

This bounded interpreter is not the complete Actions expression engine.
Refused jobs are unexecuted, not passing quality evidence.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
JOBS = (
    ("agent-mention-router-quality-ci.yml", "quality", ("push",)),
    ("agent-review-runtime-quality-ci.yml", "agent_review_runtime_quality", ()),
    ("trusted-uv-materializer-quality-ci.yml", "minimum-python-contract", ("push",)),
    ("trusted-uv-materializer-quality-ci.yml", "full-quality-gate", ("push",)),
    ("exact-head-coverage-quality-gate.yml", "quality-gate", ("push", "workflow_dispatch")),
)


def document(filename):
    """Preserve the Actions 'on' key using the real declared YAML parser."""
    return yaml.load((ROOT / ".github/workflows" / filename).read_text(), Loader=yaml.BaseLoader)


def admitted(expression, context):
    """Interpret only Boolean operations, comparisons and context attributes."""
    if expression is None:
        return True  # Actual absent job.if defaults to success().
    expression = expression.strip()
    if expression.startswith("${{"):
        assert expression.endswith("}}")
        expression = expression[3:-2].strip()
    translated = expression.replace("&&", " and ").replace("||", " or ").strip()
    tree = ast.parse("(" + translated + ")", mode="eval")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bool)):
            return node.value
        if isinstance(node, ast.Name) and node.id == "github":
            return context
        if isinstance(node, ast.Attribute):
            parent = visit(node.value)
            return parent.get(node.attr, "") if isinstance(parent, dict) else ""
        if isinstance(node, ast.BoolOp):
            values = [bool(visit(value)) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = visit(node.left), visit(node.comparators[0])
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise AssertionError(f"unsupported admission node: {ast.dump(node)}")

    result = visit(tree)
    assert type(result) is bool
    return result


def context(event="pull_request"):
    """Provide a valid same-repository PR independent of workflow conditions."""
    return {"event_name": event, "repository": "owner/repo", "ref": "refs/heads/main",
            "event": {"pull_request": {"head": {"sha": "a" * 40,
                        "repo": {"full_name": "owner/repo"}}}}}


def assert_fork_refused(expression):
    """The negative must reach the fork decision, not fail during parsing."""
    fork = context()
    fork["event"]["pull_request"]["head"]["repo"]["full_name"] = "attacker/fork"
    assert admitted(expression, fork) is False, "fork candidate admitted before runner allocation"


@pytest.mark.parametrize("filename,job,events", JOBS)
def test_candidate_job_refuses_fork_before_runner(filename, job, events):
    """Every actual candidate consumer rejects fork scheduling."""
    expression = document(filename)["jobs"][job].get("if")
    assert admitted(expression, context()) is True
    assert_fork_refused(expression)


@pytest.mark.parametrize("filename,job,events", JOBS)
@pytest.mark.parametrize("missing", ("head", "repo", "full_name", "sha", "repository"))
def test_missing_pr_metadata_is_not_same_repo(filename, job, events, missing):
    """Absent identity or exact-head metadata must fail closed."""
    value = context()
    head = value["event"]["pull_request"]["head"]
    if missing == "repository":
        value.pop("repository")
        head["repo"]["full_name"] = ""
    elif missing == "head":
        value["event"]["pull_request"].pop("head")
    elif missing == "full_name":
        head["repo"].pop("full_name")
    else:
        head.pop(missing)
    assert admitted(document(filename)["jobs"][job].get("if"), value) is False


@pytest.mark.parametrize("filename,job,events", JOBS)
@pytest.mark.parametrize("event", ("push", "workflow_dispatch", "pull_request_target", "schedule"))
def test_non_pr_admission_preserves_supported_paths(filename, job, events, event):
    """Only supported main-branch push/manual paths bypass PR metadata."""
    value = context(event)
    value["event"] = {}
    expression = document(filename)["jobs"][job].get("if")
    assert admitted(expression, value) is (event in events)
    value["ref"] = "refs/heads/untrusted"
    assert admitted(expression, value) is False


@pytest.mark.parametrize("filename,job,events", JOBS)
def test_fork_oracle_detects_weakened_actual_condition(filename, job, events):
    """A tautological same-repo comparison must hit the fork assertion."""
    expression = document(filename)["jobs"][job].get("if")
    assert expression is not None
    needle = "github.event.pull_request.head.repo.full_name == github.repository"
    assert expression.count(needle) == 1
    weakened = expression.replace(needle, "github.repository == github.repository")
    assert admitted(weakened, context()) is True
    with pytest.raises(AssertionError, match="fork candidate admitted before runner allocation"):
        assert_fork_refused(weakened)


# Hashes of complete parsed predecessor documents, including preallocation guards.
PREDECESSOR_DOCUMENTS = {
    "agent-mention-router-quality-ci.yml": "59e130fd1368d6db3f4e008accd366dc655306889553c5b8ecf1687c9f543d11",
    "agent-review-runtime-quality-ci.yml": "d54b335ba924a97890d4547532505b2fbd4e9af5ca1b49a78b537e57e6458dd5",
    "trusted-uv-materializer-quality-ci.yml": "497fc97437b427c0c3e304107c4c0bbd286334c7f593dd9415fad2e729fd479d",
    "exact-head-coverage-quality-gate.yml": "edc69da721d0aa030876a49760be8adc92a1130338bbf80865c5066b32588a8f",
}
REFUSAL_JOB = "refuse-unsupported-pr"


def refusal_outcome(job, value, directory):
    """Execute the parsed trusted static shell only when its condition admits it."""
    if not admitted(job.get("if"), value):
        return "skipped"
    step, = job["steps"]
    result = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=directory, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=5,
    )
    return "failure" if result.returncode == 1 else "success"


@pytest.mark.parametrize("filename", PREDECESSOR_DOCUMENTS)
@pytest.mark.parametrize("variant", ("fork", "head", "repo", "full_name", "sha", "repository"))
def test_rejected_pr_has_explicit_failure_without_candidate_allocation(filename, variant, tmp_path):
    """Actual refusal shell supplies failure; candidate jobs remain unallocated."""
    workflow = document(filename)
    assert REFUSAL_JOB in workflow["jobs"], "explicit fail-closed refusal job missing"
    value = context()
    head = value["event"]["pull_request"]["head"]
    if variant == "fork":
        head["repo"]["full_name"] = "attacker/fork"
    elif variant == "repository":
        value.pop("repository")
        head["repo"]["full_name"] = ""
    elif variant == "head":
        value["event"]["pull_request"].pop("head")
    elif variant == "full_name":
        head["repo"].pop("full_name")
    else:
        head.pop(variant)
    for name, job_id, _events in JOBS:
        if name == filename:
            assert admitted(workflow["jobs"][job_id].get("if"), value) is False
    assert refusal_outcome(workflow["jobs"][REFUSAL_JOB], value, tmp_path) == "failure"


@pytest.mark.parametrize("filename", PREDECESSOR_DOCUMENTS)
def test_refusal_is_only_complete_document_addition(filename):
    """Preserve every predecessor field, guard and job ID; permit only one new job."""
    workflow = document(filename)
    assert REFUSAL_JOB in workflow["jobs"], "explicit fail-closed refusal job missing"
    job = workflow["jobs"].pop(REFUSAL_JOB)
    serialized = json.dumps(workflow, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(serialized).hexdigest() == PREDECESSOR_DOCUMENTS[filename]
    assert set(job) == {"name", "if", "runs-on", "permissions", "timeout-minutes", "steps"}
    assert job["permissions"] == {}
    assert job["timeout-minutes"] == "2"
    assert job["runs-on"] == {
        "group": "CWL CI isolated",
        "labels": ["self-hosted", "linux", "x64", "cwlab-ci-isolated"],
    }
    assert len(job["steps"]) == 1
    step, = job["steps"]
    assert set(step) == {"name", "shell", "run"}
    assert step["shell"] == "bash --noprofile --norc -e -o pipefail {0}"
    assert step["run"] == "exit 1\n"
    assert "${{" not in step["run"]


@pytest.mark.parametrize("filename,job,events", JOBS)
def test_legitimate_pr_and_non_pr_do_not_run_refusal(filename, job, events, tmp_path):
    """Same-repo PRs and authorized non-PR paths retain their admission results."""
    workflow = document(filename)
    refusal = workflow["jobs"][REFUSAL_JOB]
    assert refusal_outcome(refusal, context(), tmp_path) == "skipped"
    assert admitted(workflow["jobs"][job].get("if"), context()) is True
    for event in ("push", "workflow_dispatch", "schedule", "pull_request_target"):
        value = context(event)
        # Keep fork metadata to prove the event gate, not its incidental absence.
        value["event"]["pull_request"]["head"]["repo"]["full_name"] = "attacker/fork"
        assert refusal_outcome(refusal, value, tmp_path) == "skipped"
        assert admitted(workflow["jobs"][job].get("if"), value) is (event in events)


@pytest.mark.parametrize("filename", PREDECESSOR_DOCUMENTS)
def test_refusal_oracle_detects_weakened_shell_and_condition(filename, tmp_path):
    """A zero exit or disabled rejection must not masquerade as explicit failure."""
    job = document(filename)["jobs"][REFUSAL_JOB]
    fork = context()
    fork["event"]["pull_request"]["head"]["repo"]["full_name"] = "attacker/fork"
    assert refusal_outcome(job, fork, tmp_path) == "failure"
    weakened = copy.deepcopy(job)
    assert weakened["steps"][0]["run"] == "exit 1\n"
    weakened["steps"][0]["run"] = "exit 0\n"
    assert refusal_outcome(weakened, fork, tmp_path) == "success"
    weakened = copy.deepcopy(job)
    weakened["if"] = "github.event_name == 'never'"
    assert refusal_outcome(weakened, fork, tmp_path) == "skipped"
