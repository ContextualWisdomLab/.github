"""Regression contracts for superseded historical autonomous-loop guidance."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_DOCS = REPOSITORY_ROOT / "docs" / "automation"


def _read(relative_path: str) -> str:
    """Return one canonical automation document as UTF-8 text."""

    return (AUTOMATION_DOCS / relative_path).read_text(encoding="utf-8")


def test_historical_fixed_wall_clock_cutoffs_are_explicitly_superseded() -> None:
    """Old 45-minute/minute-35 caps cannot override work-conserving exit proof."""

    audit = _read("DOCUMENTATION_AUDIT.md")
    decision = _read("adr/0007-work-conserving-maintenance.md")
    corpus = f"{audit}\n{decision}"

    assert "fixed 45-minute execution budget" in audit
    assert "minute-35 write cutoff" in audit
    assert "superseded" in audit
    assert "fixed wall-clock cutoff" in decision
    assert "practical execution/tool-budget exhaustion" in decision
    assert "second fresh sweep" in decision


def test_historical_copilot_agent_task_alias_is_explicitly_superseded() -> None:
    """The old Agent Tasks token alias cannot re-enter development credentials."""

    audit = _read("DOCUMENTATION_AUDIT.md")
    secret_decision = _read("adr/0004-explicit-secret-contracts.md")
    corpus = f"{audit}\n{secret_decision}"

    assert "historical Agent Tasks guidance" in audit
    assert "`COPILOT_GITHUB_TOKEN`" in audit
    assert "superseded" in audit
    assert "must not be reused as a GitHub API credential alias" in secret_decision
    assert "purpose-bound explicit secret" in secret_decision
    assert "NVIDIA_NIM_API_KEY" in corpus


def test_user_redirection_requires_same_invocation_multi_lane_continuation() -> None:
    """A user-reported early stop must trigger work, not another report-only run."""

    decision = _read("adr/0007-work-conserving-maintenance.md")
    runbook = _read("CONTINUATION_RUNBOOK.md")
    corpus = f"{decision}\n{runbook}".lower()

    assert "user_redirection_incident" in corpus
    assert "same invocation" in corpus
    assert "zero completion credit" in corpus
    assert "at least two materially distinct" in corpus
    assert "non-documentation" in corpus
    assert "two fresh whole-queue sweeps" in corpus


def test_user_redirection_is_visible_in_behavior_and_traceability_graphs() -> None:
    """Keep premature-stop recovery represented beyond prose runbook guidance."""

    uml = _read("UML.md")
    traceability = _read("TRACEABILITY.md")

    for required in (
        "USER_REDIRECTION_INCIDENT",
        "same invocation",
        "non-documentation",
        "two fresh whole-queue sweeps",
    ):
        assert required in uml
        assert required in traceability

    assert "PRD-06" in traceability
    assert "tests/test_automation_historical_loop_supersession_contract.py" in traceability
    assert "PR #905" in traceability
    assert "active_pr" in traceability
