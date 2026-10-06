"""Regression contracts for review-repair full-suite dependency closure."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/agent-review-runtime-quality-ci.yml")


def test_review_repair_full_suite_installs_noema_document_dependency() -> None:
    """Full-suite review-repair collection must provision Noema's XML reader."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    install_step = workflow.split(
        "- name: Install exact Noema document dependencies",
        maxsplit=1,
    )[1].split("- name: Verify Noema token-lifetime contracts", maxsplit=1)[0]

    assert "steps.affected_suites.outputs.noema == 'true'" in install_step
    assert "steps.affected_suites.outputs.review_repair == 'true'" in install_step
    assert "requirements-noema-document-ci-hashes.txt" in install_step
