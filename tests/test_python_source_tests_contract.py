"""Executable identity admission and static reusable source-test contracts."""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

WORKFLOW_PATH = Path(".github/workflows/python-source-tests.yml")


def workflow_source():
    """Read the owner workflow under test."""
    return WORKFLOW_PATH.read_text()


def identity_script():
    """Extract the actual pre-checkout guard without reimplementing its logic."""
    source = workflow_source()
    return textwrap.dedent(
        source.split("      - name: Validate pull request identity", 1)[1]
        .split("        run: |\n", 1)[1]
        .split("      - name:", 1)[0]
    )


@pytest.mark.parametrize(
    "input_number,event_number,event_name,head_sha,valid",
    [
        ("42", "42", "pull_request", "a" * 40, True),
        ("0", "0", "pull_request", "a" * 40, False),
        ("", "42", "pull_request", "a" * 40, False),
        ("-1", "-1", "pull_request", "a" * 40, False),
        ("1.5", "1.5", "pull_request", "a" * 40, False),
        ("42", "43", "pull_request", "a" * 40, False),
        ("42", "42", "pull_request_target", "a" * 40, False),
        ("42", "42", "workflow_dispatch", "a" * 40, False),
        ("42", "42", "pull_request", "main", False),
        ("$(touch injected)", "42", "pull_request", "a" * 40, False),
        ("42", "42", "pull_request", "a" * 40 + "\n", False),
    ],
)
def test_identity_guard(
    input_number, event_number, event_name, head_sha, valid, tmp_path
):
    """Only matching native PR identity can reach a checkout."""
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            identity_script(),
        ],
        env={
            "PATH": os.environ["PATH"],
            "INPUT_PR_NUMBER": input_number,
            "EVENT_PR_NUMBER": event_number,
            "EVENT_NAME": event_name,
            "PR_HEAD_SHA": head_sha,
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is valid
    assert not (tmp_path / "injected").exists()
    if not valid:
        assert result.stdout == ""
        assert result.stderr == "invalid_pull_request_identity\n"


def test_source_test_workflow_contract():
    """Keep fixed commands, immutable tooling and least-privilege PR isolation."""
    source = workflow_source()
    assert "  workflow_call:" in source
    assert "  pull_request:" not in source
    assert "type: number" in source
    assert (
        "group: ${{ github.workflow }}-${{ github.repository }}-${{ github.event.pull_request.number || github.run_id }}"
        in source
    )
    assert "cancel-in-progress: true" in source
    assert "runs-on: ubuntu-24.04" in source
    assert "timeout-minutes: 15" in source
    assert "contents: read" in source
    assert "persist-credentials: false" in source
    assert "ref: ${{ github.event.pull_request.head.sha }}" in source
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in source
    assert "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9" in source
    assert 'version: "0.12.10"' in source
    assert "enable-cache: false" in source
    assert "uv sync --locked --no-install-project" in source
    assert "uv run --no-sync python -m pytest tests" in source
    assert 'extra_args+=(--extra "$PROJECT_EXTRA")' in source
    assert '"${extra_args[@]}"' in source
    assert (
        source.index("Validate pull request identity")
        < source.index("Checkout native PR head")
        < source.index("Verify checked-out revision")
        < source.index("Install locked test dependencies")
    )
    for forbidden in (
        "secrets:",
        "secrets.",
        "services:",
        "continue-on-error",
        "--system",
        "eval ",
        "upload-artifact",
        "actions/cache",
        "inputs.command",
        "secrets: inherit",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    "project_extra", ["", "dev", "dev; touch injected", "$(touch injected)"]
)
def test_extra_is_one_literal_argument(tmp_path, project_extra):
    """Optional extras cannot become shell commands or additional uv options."""
    import json

    source = workflow_source()
    script = textwrap.dedent(
        source.split("      - name: Install locked test dependencies", 1)[1]
        .split("        run: |\n", 1)[1]
        .split("      - name:", 1)[0]
    )
    executable = tmp_path / "uv"
    executable.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n"
    )
    executable.chmod(0o755)
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        env={
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "PROJECT_EXTRA": project_extra,
        },
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == ["sync", "--locked", "--no-install-project"] + (
        ["--extra", project_extra] if project_extra else []
    )
    assert not (tmp_path / "injected").exists()


def test_concurrency_does_not_trust_pre_admission_input():
    """A rejected caller cannot choose another PR's cancellation group."""
    source = workflow_source()
    concurrency_block = source.split("concurrency:\n", 1)[1].split("\njobs:", 1)[0]
    assert "inputs." not in concurrency_block
    assert "github.event.pull_request.number || github.run_id" in concurrency_block
    assert "cancel-in-progress: true" in concurrency_block
