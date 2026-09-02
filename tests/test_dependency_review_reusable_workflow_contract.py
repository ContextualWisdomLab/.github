"""Contract for the reusable Dependency Review workflow.

Replaces Argos's, mightyETL's, naruon's, newsdom-api's, and scopeweave's
independently hand-written ``dependency-review.yml`` files with one reusable
``workflow_call`` workflow, ``.github/workflows/dependency-review.yml``, plus
a thin caller left in each product repository. See
``docs/doctoring/dependency-review-reusable-workflow-consolidation.md`` and
``docs/adr/0024-dependency-review-reusable-workflow-consolidation.md`` for
why.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

_WORKFLOW = Path(".github/workflows/dependency-review.yml")

_CHECKOUT_PIN = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
_DEPENDENCY_REVIEW_PIN = "a1d282b36b6f3519aa1f3fc636f609c47dddb294"


def _workflow_text() -> str:
    """Read the reusable Dependency Review workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def _availability_probe_script() -> str:
    """Extract the dependency-graph preflight shell body for executable tests."""
    workflow = _workflow_text()
    step = "      - name: Check dependency graph availability\n"
    start = workflow.index(step)
    end = workflow.index("\n      - name:", start + len(step))
    block = workflow[start:end]
    run_marker = "        run: |\n"
    run_start = block.index(run_marker) + len(run_marker)
    script = textwrap.dedent(block[run_start:])
    return script.replace('${{ github.event_name }}', "pull_request")


def _run_availability_probe(
    tmp_path: Path,
    repository: str,
    *,
    base_sha: str = "a" * 40,
    head_sha: str = "b" * 40,
    http_status: str = "200",
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Execute the real preflight shell against a marker-only fake curl."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl_marker = tmp_path / "curl-called"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "authorized=false\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"$arg\" == Authorization:* ]]; then authorized=true; fi\n"
        "done\n"
        "printf '%s\\n' \"$authorized\" >>\"${CURL_MARKER}\"\n"
        "printf '%s' \"${HTTP_STATUS:-200}\"\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env.get('PATH', '')}",
            "GH_TOKEN": "test-token",
            "BASE_SHA": base_sha,
            "HEAD_SHA": head_sha,
            "REPOSITORY": repository,
            "GITHUB_API_URL": "https://api.github.invalid",
            "GITHUB_OUTPUT": str(output),
            "CURL_MARKER": str(curl_marker),
            "HTTP_STATUS": http_status,
        }
    )
    result = subprocess.run(
        ["bash", "-c", _availability_probe_script()],
        cwd=Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, curl_marker, output


def test_declares_workflow_call_with_four_inputs_and_recorded_defaults() -> None:
    """Every genuinely varying field found while auditing the five originals is an input."""
    workflow = _workflow_text()
    assert "on:\n  workflow_call:\n    inputs:" in workflow
    for name in (
        "fail_on_severity:",
        "allow_ghsas:",
        "continue_on_error:",
        "comment_summary_in_pr:",
    ):
        assert name in workflow

    assert 'default: "moderate"' in workflow
    assert 'default: ""' in workflow
    assert "default: false" in workflow
    assert 'default: "on-failure"' in workflow


def test_step_order_is_harden_then_checkout_then_preflight_then_dependency_review() -> None:
    """Runner hardening, checkout, capability proof, then the gated action stay ordered."""
    workflow = _workflow_text()
    order = [
        "Harden the runner",
        "actions/checkout@",
        "Check dependency graph availability",
        "Dependency review",
    ]
    positions = [workflow.index(marker) for marker in order]
    assert positions == sorted(positions), "steps are out of order"


def test_dependency_review_runs_only_after_a_confirmed_successful_comparison() -> None:
    """The action must execute only after the compare endpoint returned HTTP 200."""
    workflow = _workflow_text()
    assert (
        "if: steps.dependency_graph.outputs.available == 'true'\n"
        "        continue-on-error: ${{ inputs.continue_on_error }}"
        in workflow
    )
    assert 'if [ "$status" = "200" ]; then' in workflow
    assert 'echo "available=true" >>"$GITHUB_OUTPUT"' in workflow


def test_inputs_are_forwarded_to_the_dependency_review_action() -> None:
    """Every caller-varying action input must reach the pinned action untouched."""
    workflow = _workflow_text()
    assert "fail-on-severity: ${{ inputs.fail_on_severity }}" in workflow
    assert "allow-ghsas: ${{ inputs.allow_ghsas }}" in workflow
    assert "comment-summary-in-pr: ${{ inputs.comment_summary_in_pr }}" in workflow


def test_harden_runner_audits_egress() -> None:
    """naruon's harden-runner control applies uniformly in the reusable owner."""
    workflow = _workflow_text()
    assert "step-security/harden-runner@" in workflow
    assert "egress-policy: audit" in workflow


def test_action_pins_are_current_and_uniform() -> None:
    """Checkout and Dependency Review use one immutable current pin."""
    workflow = _workflow_text()
    assert f"actions/checkout@{_CHECKOUT_PIN}" in workflow
    assert f"actions/dependency-review-action@{_DEPENDENCY_REVIEW_PIN}" in workflow


def test_uniform_fields_are_hardcoded_not_parameterized() -> None:
    """Uniform least-privilege and checkout controls stay static."""
    workflow = _workflow_text()
    assert "permissions:\n  contents: read\n  pull-requests: read" in workflow
    assert "persist-credentials: false" in workflow


def test_example_caller_preserves_required_permission_envelope() -> None:
    """Thin callers must explicitly pass the reusable job's read permission ceiling."""
    workflow = _workflow_text()
    assert (
        "#   permissions:\n"
        "#     contents: read\n"
        "#     pull-requests: read\n"
        "#   concurrency:"
        in workflow
    )


def test_example_caller_requires_immutable_protected_main_pin() -> None:
    """The canonical example must never teach consumers to execute a mutable owner ref."""
    workflow = _workflow_text()
    assert "@<protected-main-commit-sha>" in workflow
    assert "uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@main" not in workflow


def test_forces_node24_runtime_for_js_actions() -> None:
    """newsdom-api's Node24 opt-in applies uniformly, not only to one caller."""
    workflow = _workflow_text()
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true" in workflow


def test_availability_check_uses_the_dependency_graph_compare_api() -> None:
    """The preflight must query the real capability, not infer from visibility."""
    workflow = _workflow_text()
    assert "dependency-graph/compare" in workflow
    assert "github.event.repository.private" not in workflow
    assert '-H "Authorization: Bearer ${GH_TOKEN}"' in workflow


def test_pull_request_http_403_and_404_are_not_normalized_to_unavailable() -> None:
    """Authorization-shaped HTTP responses are ambiguous and must remain blocking."""
    workflow = _workflow_text()
    assert 'if [ "$status" = "403" ] || [ "$status" = "404" ]' not in workflow
    assert "skipping the dependency-review hard gate" not in workflow
    assert "Dependency graph unavailable note" not in workflow
    assert "::error::Dependency graph comparison failed with HTTP" in workflow
    assert "exit 1" in workflow


def test_availability_check_only_runs_the_gate_for_pull_request_events() -> None:
    """A non-pull_request trigger may skip because it has no PR base/head identity."""
    workflow = _workflow_text()
    assert '"${{ github.event_name }}" != "pull_request"' in workflow


def test_preflight_rejects_named_revisions_before_transport(tmp_path: Path) -> None:
    """Named or malformed revisions never reach the dependency-graph endpoint."""
    for index, (base_sha, head_sha) in enumerate(
        (("main", "b" * 40), ("a" * 40, "develop"), ("a" * 39, "b" * 40))
    ):
        case_dir = tmp_path / f"revision-{index}"
        case_dir.mkdir()
        result, curl_marker, _output = _run_availability_probe(
            case_dir,
            "ContextualWisdomLab/Orgmetra",
            base_sha=base_sha,
            head_sha=head_sha,
        )
        assert result.returncode != 0, (base_sha, head_sha)
        assert not curl_marker.exists(), (base_sha, head_sha)
        assert "exact 40- or 64-character hexadecimal" in result.stdout.lower()


def test_preflight_rejects_malformed_repository_before_transport(tmp_path: Path) -> None:
    """Only one non-dot owner/name repository identity may reach transport."""
    repositories = (
        "ContextualWisdomLab",
        "ContextualWisdomLab/Orgmetra/extra",
        "/Orgmetra",
        "../.github",
        "ContextualWisdomLab/..",
        "ContextualWisdomLab/.",
        "./.github",
    )
    for index, repository in enumerate(repositories):
        case_dir = tmp_path / f"repository-{index}"
        case_dir.mkdir()
        result, curl_marker, _output = _run_availability_probe(case_dir, repository)
        assert result.returncode != 0, repository
        assert not curl_marker.exists(), repository
        assert "repository identity" in result.stdout.lower(), repository


def test_preflight_accepts_dotgithub_and_uses_job_token(tmp_path: Path) -> None:
    """The legitimate .github repository reaches exactly one authenticated compare."""
    result, curl_marker, output = _run_availability_probe(
        tmp_path, "ContextualWisdomLab/.github"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert curl_marker.read_text(encoding="utf-8") == "true\n"
    assert output.read_text(encoding="utf-8") == "available=true\n"


def test_dependency_review_comment_summary_defaults_to_on_failure() -> None:
    """The shared UX defaults to on-failure while remaining caller-overridable."""
    workflow = _workflow_text()
    assert "comment_summary_in_pr:" in workflow
    assert 'default: "on-failure"' in workflow
    assert "comment-summary-in-pr: ${{ inputs.comment_summary_in_pr }}" in workflow
