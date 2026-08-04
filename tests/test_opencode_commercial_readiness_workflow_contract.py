"""Contract tests for the reusable OpenCode commercial-readiness workflow.

The tests inspect workflow source text rather than loading YAML because YAML 1.1
parsers may coerce the top-level ``on`` key into a Boolean. Each assertion locks
one security-significant orchestration boundary that product callers depend on.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/opencode-commercial-readiness.yml")
DOCUMENTATION_PATH = Path("docs/opencode-commercial-readiness.md")


def _workflow_source() -> str:
    """Return the complete reusable workflow as UTF-8 text."""

    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _step_source(source: str, step_name: str) -> str:
    """Return one named step through the line before the following step."""

    marker = f"      - name: {step_name}\n"
    start = source.find(marker)
    assert start >= 0, f"missing workflow step: {step_name}"
    end = source.find("\n      - name: ", start + len(marker))
    return source[start:] if end < 0 else source[start:end]


def test_reusable_contract_requires_nvidia_nim_secret() -> None:
    """The central workflow must use OpenCode/NIM rather than Copilot."""

    source = _workflow_source()

    assert "workflow_call:" in source
    assert "NVIDIA_NIM_API_KEY:" in source
    assert "required: true" in source
    assert "opencode run" in source
    assert "https://integrate.api.nvidia.com/v1" in source
    assert "copilot" not in source.lower()
    assert "pull_request_target:" not in source


def test_model_and_publication_credentials_are_step_scoped() -> None:
    """Model execution and GitHub publication must not share credentials."""

    source = _workflow_source()
    before_steps = source[: source.index("    steps:\n")]
    agent_step = _step_source(source, "Execute OpenCode with NVIDIA NIM")
    verification_step = _step_source(
        source, "Run the caller-owned trusted verification contract"
    )
    publication_step = _step_source(
        source,
        "Publish the verified exact head without exposing credentials to the agent",
    )

    assert "NVIDIA_NIM_API_KEY" not in before_steps
    assert "NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in agent_step
    assert "GH_TOKEN:" not in agent_step
    assert "NVIDIA_NIM_API_KEY" not in verification_step
    assert "GH_TOKEN:" not in verification_step
    assert "GH_TOKEN: ${{ github.token }}" in publication_step
    assert "NVIDIA_NIM_API_KEY" not in publication_step
    assert source.count("persist-credentials: false") >= 2


def test_target_selection_rejects_forks_and_untrusted_authors() -> None:
    """Only trusted branches in the caller repository may reach OpenCode."""

    selection_step = _step_source(
        _workflow_source(),
        "Select one trusted pull request or the next bounded product slice",
    )

    assert "trusted_associations = {'OWNER', 'MEMBER', 'COLLABORATOR'}" in selection_step
    assert "head_repository.get('full_name') == repository" in selection_step
    assert "same_repository and trusted_author" in selection_step
    assert "dependabot[bot]" in selection_step
    assert "reviewThreads(first:100)" in selection_step
    assert "selected-product-gap.json" in selection_step
    assert "No labeled buyer-visible issue" in selection_step


def test_default_branch_policy_is_separate_and_immutable() -> None:
    """The model must not control the verification script that accepts its work."""

    source = _workflow_source()
    baseline_step = _step_source(
        source,
        "Establish immutable product policy and implementation baselines",
    )
    boundary_step = _step_source(
        source,
        "Enforce central and product trust boundaries",
    )
    verification_step = _step_source(
        source,
        "Run the caller-owned trusted verification contract",
    )

    assert "path: trusted-policy" in source
    assert "path: workspace" in source
    assert "sha256sum \"$trusted_script\"" in baseline_step
    assert "POLICY_DIGEST" in boundary_step
    assert "grep -Fx \"$VERIFICATION_SCRIPT\"" in boundary_step
    assert "sha256sum \"$trusted_script\"" in verification_step
    assert 'bash "$trusted_script" "$WORKSPACE_ROOT"' in verification_step
    assert 'python3 "$trusted_script" "$WORKSPACE_ROOT"' in verification_step


def test_caller_inputs_are_bounded_before_repository_writes() -> None:
    """Model, timeout, labels, version, and policy path need fixed bounds."""

    validation_step = _step_source(
        _workflow_source(), "Validate bounded caller inputs"
    )

    assert "5 <= timeout <= 40" in validation_step
    assert "[A-Za-z0-9._/-]+" in validation_step
    assert "verification_script must live below .github/scripts" in validation_step
    assert "script.suffix not in {'.sh', '.py'}" in validation_step
    assert "between 1 and 20 labels" in validation_step
    assert "latest or an explicit semantic version" in validation_step


def test_raw_model_output_is_suppressed_and_destroyed_on_secret_leak() -> None:
    """A model transcript must never become an Actions log or artifact."""

    agent_step = _step_source(
        _workflow_source(), "Execute OpenCode with NVIDIA NIM"
    )

    assert '> "$output_path" 2>&1' in agent_step
    assert "| tee" not in agent_step
    assert 'grep -Fq "$NVIDIA_NIM_API_KEY" "$output_path"' in agent_step
    assert 'rm -f "$output_path" "$config_path"' in agent_step
    assert "raw model output is intentionally suppressed" in agent_step
    assert "upload-artifact" not in agent_step


def test_static_boundary_rejects_history_and_review_policy_changes() -> None:
    """The implementation agent cannot alter review or repository trust."""

    boundary_step = _step_source(
        _workflow_source(), "Enforce central and product trust boundaries"
    )

    assert 'git merge-base --is-ancestor "$START_SHA" HEAD' in boundary_step
    assert 'git diff --check "$START_SHA" --' in boundary_step
    assert (
        "coderabbit|noema|opencode-review|review-agent|strix|security-review"
        in boundary_step
    )
    assert ".gitmodules" in boundary_step
    assert "ghp_" in boundary_step
    assert "github_pat_" in boundary_step
    assert "nvapi-" in boundary_step
    assert "PRIVATE KEY" in boundary_step
    assert "pull_request_target:" in boundary_step


def test_publication_fails_on_head_movement_and_keeps_new_work_draft() -> None:
    """Concurrent changes must win and new automated scope must stay Draft."""

    source = _workflow_source()
    publication_step = _step_source(
        source,
        "Publish the verified exact head without exposing credentials to the agent",
    )
    review_step = _step_source(
        source,
        "Request current-head review and arm only protected auto-merge",
    )

    assert "current_remote_sha" in publication_step
    assert 'current_remote_sha" != "$START_SHA' in publication_step
    assert "refusing to overwrite newer work" in publication_step
    assert re.search(r"gh pr create[\s\S]*--draft", publication_step)
    assert "trap 'git remote set-url origin" in publication_step
    assert "@coderabbitai review" in review_step
    assert 'if [[ "$is_draft" == \'false\' ]]' in review_step
    assert re.search(r"gh pr merge[\s\S]*--squash --auto", review_step)
    assert "--admin" not in source
    assert "gh pr ready" not in source
    assert "dismiss-review" not in source


def test_documentation_requires_immutable_caller_pin_and_domain_tests() -> None:
    """Operator guidance must preserve modularity and product-owned quality."""

    documentation = DOCUMENTATION_PATH.read_text(encoding="utf-8")

    assert "<immutable-40-character-commit-sha>" in documentation
    assert ".github/scripts/commercial_readiness_verify.sh" in documentation
    assert "true-parameter RMSE" in documentation
    assert "Rust CPU/GPU/multithreaded" in documentation
    assert "contextual-orchestrator" in documentation
    assert "APA 7th" in documentation
    assert "multi-word `snake_case`" in documentation
    assert "does not invoke GitHub Copilot" in documentation
    assert "NIST.SP.800-218" in documentation
    assert "NIST.AI.600-1" in documentation
