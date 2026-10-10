"""Source contracts for central procurement CI; runtime acceptance stays separate."""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/procurement-workbench-ci.yml"


class UniqueLoader(yaml.BaseLoader):
    """Preserve GitHub `on` and refuse duplicate YAML mapping keys."""


def unique_mapping(loader, node):
    """Reject duplicate or non-scalar keys before dictionary collapse."""
    result = {}
    for key_node, value_node in node.value:
        assert isinstance(key_node, yaml.ScalarNode), "non-scalar YAML key"
        key = loader.construct_object(key_node)
        assert key not in result, "duplicate YAML key"
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor("tag:yaml.org,2002:map", unique_mapping)


def workflow():
    """Read the candidate without changing event/Boolean scalar spellings."""
    return yaml.load(WORKFLOW.read_text(), Loader=UniqueLoader)


def job():
    """Return the unconditionally executed matrix job."""
    return workflow()["jobs"]["quality"]


def test_duplicate_yaml_keys_are_rejected():
    """A contradictory selector must not silently overwrite its predecessor."""
    with pytest.raises(AssertionError, match="duplicate YAML key"):
        yaml.load("jobs: {}\njobs: {}\n", Loader=UniqueLoader)


def test_owned_documents_exist_and_keep_activation_separate():
    """Source/test acceptance does not claim operational success."""
    paths = [
        "GOAL.md",
        "docs/doctoring/procurement-workbench-central-ci.md",
        "docs/doctoring/procurement-workbench-github-contexts.md",
    ]
    prose = "".join((ROOT / p).read_text() for p in paths)
    for phrase in (
        "ACTIVATION HOLD",
        "#2560",
        "#2565",
        "litellm.poinnetworks.net",
        "auto",
        "APPROVED",
        "unavailable",
    ):
        assert phrase in prose


def test_reusable_only_read_only_input_free():
    """No caller-controlled commands, refs, secrets or runner choices."""
    w = workflow()
    assert w["on"] == {"workflow_call": ""}
    assert w["permissions"] == {"contents": "read"}
    assert set(w["jobs"]) == {"quality"}
    assert "concurrency" not in w
    for step in job()["steps"]:
        assert "continue-on-error" not in step
        assert "secrets" not in step
    assert "if" not in job()


def test_fixed_self_hosted_matrix_preserves_all_gates():
    """Both interpreters execute all existing product quality commands."""
    j = job()
    assert j["runs-on"] == {
        "group": "CWL procurement CI",
        "labels": ["self-hosted", "linux", "x64"],
    }
    assert j["timeout-minutes"] == "15"
    assert j["strategy"] == {
        "fail-fast": "false",
        "max-parallel": "1",
        "matrix": {"python-version": ["3.12", "3.14"]},
    }
    names = [
        "Verify frozen lockfile",
        "Install frozen dependencies",
        "Run full pytest suite",
        "Run Ruff",
        "Check UI JavaScript syntax",
    ]
    commands = [
        "uv lock --check",
        "uv sync --frozen --group dev",
        'uv run pytest -q --basetemp "$PROCUREMENT_TEST_TEMP"',
        "uv run ruff check .",
        "node --check procurement/ui.js",
    ]
    steps = j["steps"]
    indices = []
    for name, command in zip(names, commands):
        index = next(i for i, s in enumerate(steps) if s["name"] == name)
        indices.append(index)
        s = steps[index]
        assert command in s["run"]
        assert "if" not in s
        assert s["working-directory"] == "${{ steps.prepare.outputs.source_absolute }}"
    assert indices == sorted(indices)


def test_identity_admission_precedes_all_actions():
    """Neither product nor central identity is controlled by caller inputs."""
    steps = job()["steps"]
    assert [s["name"] for s in steps[:4]] == [
        "Admit immutable central definition",
        "Admit fixed procurement source",
        "Prepare isolated job workspace",
        "Checkout admitted product source",
    ]
    assert next(i for i, s in enumerate(steps) if "uses" in s) == 3
    assert steps[0]["env"] == {"WORKFLOW_JOB_CONTEXT": "${{ toJSON(job) }}"}


@pytest.mark.parametrize(
    "mutation",
    [
        {},
        {"WORKFLOW_REPOSITORY": "attacker/repo"},
        {"WORKFLOW_SHA": ""},
        {"WORKFLOW_SHA": "main"},
        {
            "WORKFLOW_REF": "ContextualWisdomLab/.github/.github/workflows/procurement-workbench-ci.yml@main"
        },
        {"WORKFLOW_FILE_PATH": ".github/workflows/noema-review.yml"},
    ],
)
def test_actual_central_admission(tmp_path, mutation):
    """Execute fixed central identity with positive and negative controls."""
    repository = "ContextualWisdomLab/.github"
    file = ".github/workflows/procurement-workbench-ci.yml"
    sha = "a" * 40
    import json

    context = {
        "workflow_repository": repository,
        "workflow_sha": sha,
        "workflow_ref": f"{repository}/{file}@{sha}",
        "workflow_file_path": file,
    }
    context.update({key.lower(): value for key, value in mutation.items()})
    env = {**os.environ, "WORKFLOW_JOB_CONTEXT": json.dumps(context)}
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", job()["steps"][0]["run"]],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (1 if mutation else 0), result.stderr


@pytest.mark.parametrize(
    "event,mutations,expected",
    [
        ("pull_request", {}, 0),
        ("push", {}, 0),
        ("pull_request", {"HEAD_REPOSITORY": "attacker/fork"}, 1),
        ("pull_request", {"BASE_REPOSITORY": "attacker/fork"}, 1),
        ("pull_request", {"EVENT_REF": "refs/heads/attacker"}, 1),
        ("pull_request", {"PR_NUMBER": "8"}, 1),
        ("pull_request", {"PR_HEAD_SHA": ""}, 1),
        ("pull_request", {"PR_HEAD_SHA": "0" * 40}, 1),
        ("push", {"PUSH_DELETED": "true"}, 1),
        ("push", {"PUSH_SHA": "bad"}, 1),
        ("push", {"EVENT_REF": "refs/heads/feature"}, 1),
        ("workflow_dispatch", {}, 1),
    ],
)
def test_actual_product_admission_selects_event_specific_sha(
    tmp_path, event, mutations, expected
):
    """PR head is distinct from push/merge SHA; missing fields cannot fallback."""
    repository = "ContextualWisdomLab/procurement-workbench"
    output = tmp_path / "output"
    env = {
        **os.environ,
        "CALLER_REPOSITORY": repository,
        "EVENT_NAME": event,
        "EVENT_REF": "refs/pull/7/merge"
        if event == "pull_request"
        else "refs/heads/master",
        "PR_NUMBER": "7",
        "HEAD_REPOSITORY": repository,
        "BASE_REPOSITORY": repository,
        "PR_HEAD_SHA": "a" * 40,
        "PUSH_SHA": "b" * 40,
        "PUSH_DELETED": "false",
        "GITHUB_OUTPUT": str(output),
        **mutations,
    }
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", job()["steps"][1]["run"]],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == expected, result.stderr
    if not expected:
        sha = "a" * 40 if event == "pull_request" else "b" * 40
        assert output.read_text() == f"source_sha={sha}\n"
    else:
        assert not output.exists()


def test_central_identity_uses_serialized_documented_job_context():
    """Parse documented metadata without suppressing validator schema diagnostics."""
    assert job()["steps"][0]["env"] == {"WORKFLOW_JOB_CONTEXT": "${{ toJSON(job) }}"}


@pytest.mark.parametrize(
    "payload", ["{}", "[]", "null", "{bad json", '{"workflow_sha":17}']
)
def test_missing_or_malformed_serialized_context_rejects(tmp_path, payload):
    """The compatible serialization route must not default to caller identity."""
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", job()["steps"][0]["run"]],
        env={**os.environ, "WORKFLOW_JOB_CONTEXT": payload},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "procurement-ci:" in result.stderr


def test_action_pins_cache_and_output_wiring():
    """Checkout, actual cache location and cleanup consume the same producer."""
    steps = job()["steps"]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert uses == [
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e",
        "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
    ]
    assert all(re.fullmatch(r".+@[a-f0-9]{40}", s) for s in uses)
    checkout = steps[3]["with"]
    assert checkout == {
        "persist-credentials": "false",
        "clean": "true",
        "ref": "${{ steps.admit.outputs.source_sha }}",
        "path": "${{ steps.prepare.outputs.source_relative }}",
    }
    prepare = steps[2]
    assert prepare["id"] == "prepare"
    assert "GITHUB_ENV" not in prepare["run"]
    setup = next(s for s in steps if s["name"] == "Setup uv")["with"]
    assert setup["cache-local-path"] == "${{ steps.prepare.outputs.job_root }}/uv-cache"
    assert setup["enable-cache"] == setup["save-cache"] == "false"
    cleanup = steps[-1]
    assert cleanup["if"] == "${{ always() && steps.prepare.outcome == 'success' }}"
    assert (
        cleanup["env"]["CLEANUP_SOURCE"]
        == "${{ steps.prepare.outputs.source_absolute }}"
    )
    assert cleanup["env"]["CLEANUP_PRIVATE"] == "${{ steps.prepare.outputs.job_root }}"
