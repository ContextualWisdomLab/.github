"""Contracts for centrally owned, isolated GRC Product execution."""

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/grc-product.yml"


def workflow_text() -> str:
    """Read the central contract, failing explicitly before implementation."""
    assert WORKFLOW.is_file(), "GRC Product execution must be centrally owned"
    return WORKFLOW.read_text(encoding="utf-8")


def admission_script() -> str:
    """Extract the actual pre-checkout shell rather than emulate its decision."""
    source = workflow_text().split(
        "      - name: Admit GRC caller before checkout\n", 1
    )[1]
    block = source.split("        run: |\n", 1)[1].split("      - name:", 1)[0]
    return "\n".join(line[10:] for line in block.splitlines())


def test_central_grc_product_contract_exists() -> None:
    """Execution is reusable and has no schedule or privileged trigger."""
    source = workflow_text()
    assert "on:\n  workflow_call:\n" in source
    assert "inputs:" not in source
    assert "pull_request_target" not in source
    assert "secrets:" not in source


def test_only_dedicated_self_hosted_group_is_admitted() -> None:
    """No hosted fallback or privileged central pool executes product code."""
    source = workflow_text()
    assert "group: CWL CI isolated" in source
    assert "labels: [self-hosted, Linux, X64, cwlab-ci-isolated]" in source
    assert len(re.findall(r"^    runs-on:", source, re.M)) == 1
    assert "ubuntu-24.04" not in source
    assert "timeout-minutes: 20" in source
    config = REPO_ROOT / ".github/actionlint.yaml"
    assert config.is_file(), "Custom runner labels require repository actionlint config"
    assert "    - cwlab-ci-isolated" in config.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in source


def test_actual_precheckout_admission_accepts_only_supported_caller_events() -> None:
    """Unsupported callers/forks/events fail, not skip to a false green."""
    script = admission_script()
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)
    repository = "ContextualWisdomLab/governance-risk-compliance"
    for event, caller, head, accepted in (
        ("pull_request", repository, repository, True),
        ("push", repository, "", True),
        ("workflow_dispatch", repository, "", True),
        ("pull_request", repository, "external/grc", False),
        ("pull_request", repository, "", False),
        ("push", "external/grc", "", False),
        ("repository_dispatch", repository, "", False),
        ("schedule", repository, "", False),
    ):
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
            env={
                **os.environ,
                "CALLER_REPOSITORY": caller,
                "CALLER_EVENT": event,
                "HEAD_REPOSITORY": head,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert (result.returncode == 0) is accepted, (event, caller, head)


def test_exact_head_and_checkout_identity_are_preserved() -> None:
    """Checkout uses caller context with no credential persistence."""
    source = workflow_text()
    assert source.index("Admit GRC caller before checkout") < source.index(
        "actions/checkout@"
    )
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in source
    assert "persist-credentials: false" in source
    assert "SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in source
    assert 'test "$(git rev-parse HEAD)" = "$SOURCE_SHA"' in source
    for ref in re.findall(r"uses: (\S+)", source):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref), ref


def test_original_quality_and_clean_tree_gates_are_not_lowered() -> None:
    """All original commands and thresholds execute centrally."""
    source = workflow_text()
    for command in (
        "uv sync --locked --extra dev",
        "uv run ruff check cwl_grc tests",
        "uv run interrogate --fail-under 100 cwl_grc",
        "uv run pytest --cov=cwl_grc --cov-branch",
        "--cov-report=term-missing --cov-fail-under=100",
        "uv run python -m compileall -q cwl_grc tests",
        "uv lock --check",
        "git diff --check",
        'test -z "$(git status --porcelain)"',
    ):
        assert command in source, command
    assert "continue-on-error" not in source
    assert 'python-version: "3.12"' in source


def test_concurrency_lives_only_in_caller() -> None:
    """Reusable/caller concurrency cannot cancel its own parent run."""
    assert "concurrency:" not in workflow_text()


def test_uv_cache_is_job_private_and_removed_on_failure() -> None:
    """No persisted PR cache crosses execution trust contexts."""
    source = workflow_text()
    assert "enable-cache: false" in source
    assert 'version: "0.12.5"' in source
    assert (
        "cache-local-path: ${{ runner.temp }}/grc-uv-${{ github.run_id }}-"
        "${{ github.run_attempt }}-${{ github.job }}"
    ) in source
    assert (
        "UV_CACHE_DIR: ${{ runner.temp }}/grc-uv-${{ github.run_id }}-"
        "${{ github.run_attempt }}-${{ github.job }}"
    ) in source
    assert "      - name: Remove job-private uv cache\n        if: always()" in source
    assert 'rm -rf -- "$UV_CACHE_DIR"' in source


def test_existing_hardening_action_is_retained() -> None:
    """Self-hosted image-agent acceptance stays an operator prerequisite."""
    source = workflow_text()
    assert "step-security/harden-runner@b09bb98e06d4d774595224525879c09bc6e98c40" in source
    assert "egress-policy: audit" in source
