"""Contracts for trusted CodeGraph evidence in the independent Noema reviewer."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOEMA_WORKFLOW = ROOT / ".github/workflows/noema-review.yml"
NOEMA_GATE = ROOT / "scripts/ci/noema_review_gate.py"
CODEGRAPH_HELPER = ROOT / "scripts/ci/noema_codegraph_context.sh"


def test_noema_workflow_materializes_trusted_codegraph_before_review() -> None:
    """The trusted workflow must produce exact-head CodeGraph evidence before model work."""
    workflow = NOEMA_WORKFLOW.read_text(encoding="utf-8")
    materialize = workflow.index("Materialize trusted Noema CodeGraph evidence")
    review = workflow.index("Run Noema LLM review and submit verdict")
    assert materialize < review
    assert "NOEMA_CODEGRAPH_CONTEXT_PATH: ${{ runner.temp }}/noema-codegraph-evidence.md" in workflow
    assert 'NOEMA_REQUIRE_CODEGRAPH_CONTEXT: "1"' in workflow
    assert "scripts/ci/noema_codegraph_context.sh" in workflow


def test_noema_codegraph_helper_keeps_pr_source_data_only() -> None:
    """CodeGraph setup may parse exact-head source but must not execute target-owned tooling."""
    helper = CODEGRAPH_HELPER.read_text(encoding="utf-8")
    for required in (
        "CODEGRAPH_NO_DOWNLOAD=1",
        "refs/pull/${PR_NUMBER}/head",
        "EXPECTED_HEAD_SHA",
        "PR_BASE_SHA",
        "unset GH_TOKEN",
        "codegraph-package/package-lock.json",
        "codegraph-package/package.json",
        '"$CODEGRAPH_BIN" init -i',
        '"$CODEGRAPH_BIN" explore',
        "# Trusted CodeGraph current-head evidence",
        "Head SHA:",
    ):
        assert required in helper
    for forbidden in (
        "pytest",
        "npm test",
        "npm run",
        "cargo test",
        "go test",
        "gradle",
        "mvn test",
    ):
        assert forbidden not in helper


def test_noema_gate_requires_exact_head_bound_codegraph_when_workflow_requests_it() -> None:
    """The model gate must fail closed if required structural evidence is absent or stale."""
    source = NOEMA_GATE.read_text(encoding="utf-8")
    assert "NOEMA_REQUIRE_CODEGRAPH_CONTEXT" in source
    assert "NOEMA_CODEGRAPH_CONTEXT_PATH" in source
    assert "Trusted CodeGraph current-head evidence" in source
    assert "CodeGraph context head does not match the pull request head" in source
