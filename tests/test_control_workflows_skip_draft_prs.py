"""Review workflows may skip drafts only when Ready re-admission is observable.

On 2026-09-29, 325 of 836 queued control-pool runs were for draft PRs; each
only concluded "draft, no verdict required". Model-review entry jobs skip
drafts at the job level so no runner is assigned. CodeQL is deliberately
excluded: organization ruleset consumers do not receive `ready_for_review`,
so a draft-skipped exact head would never receive its security evidence.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
# noema-review.yml is deliberately excluded: it must read the live draft state,
# never the event snapshot (tests/test_noema_draft_admission_before_sidecar.py).
WORKFLOWS = [
    "opencode-review.yml",
    "strix.yml",
    "pr-review-merge-scheduler.yml",
]
DRAFT_GUARD = "github.event.pull_request.draft != true"


def _load(name: str) -> dict:
    return yaml.safe_load((REPO_ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def _pr_types(doc: dict) -> list[str]:
    on = doc.get(True) or doc.get("on")
    types: list[str] = []
    for event in ("pull_request", "pull_request_target"):
        if isinstance(on.get(event), dict):
            types += on[event].get("types", [])
    return types


def _entry_jobs(doc: dict) -> dict[str, dict]:
    return {k: j for k, j in doc["jobs"].items() if not j.get("needs")}


# required-workflow-bootstrap must never carry an `if:` (its branch-protection
# context is always created; scripts/ci/test_strix_quick_gate.sh enforces it).
# It decides admission itself, so its dependents still skip draft PRs.
UNGUARDED_ENTRY_JOBS = {"required-workflow-bootstrap"}


def _is_cancellation_job(job_name: str, job: dict) -> bool:
    """Cancellation sweeps stay as they are; they exist for synchronize/draft/close events."""
    return job_name.startswith("cancel-") or job_name in UNGUARDED_ENTRY_JOBS


def test_required_workflow_bootstrap_has_no_if() -> None:
    assert "if" not in _load("opencode-review.yml")["jobs"]["required-workflow-bootstrap"]


@pytest.mark.parametrize("name", WORKFLOWS)
def test_ready_for_review_reruns_the_workflow(name: str) -> None:
    """A draft-skipped head must be re-evaluated when it becomes ready."""
    assert "ready_for_review" in _pr_types(_load(name))


@pytest.mark.parametrize("name", WORKFLOWS)
def test_entry_jobs_skip_draft_prs(name: str) -> None:
    doc = _load(name)
    for job_name, job in _entry_jobs(doc).items():
        if _is_cancellation_job(job_name, job):
            continue
        assert DRAFT_GUARD in str(job.get("if", "")), f"{name}:{job_name} lacks the draft guard"


def test_codeql_materializes_draft_heads_without_scanning_draft_conversion() -> None:
    """Draft heads scan, while conversion only retires the prior same-PR run."""
    doc = _load("codeql-pr.yml")
    assert "converted_to_draft" in _pr_types(doc)
    detect_languages = doc["jobs"]["detect-languages"]
    condition = str(detect_languages.get("if", ""))
    assert "pull_request.draft" not in condition
    assert condition == (
        "github.event.action != 'closed' && "
        "github.event.action != 'converted_to_draft'"
    )
QUEUE_RETIREMENT_WORKFLOWS = [
    "pr-review-merge-scheduler.yml",
    "sast-semgrep.yml",
    "security-scan.yml",
    "python-security.yml",
]


@pytest.mark.parametrize("name", QUEUE_RETIREMENT_WORKFLOWS)
def test_converted_to_draft_retires_queued_run_without_runner(name: str) -> None:
    """A draft transition cancels the same-PR queue without taking a runner."""
    doc = _load(name)
    assert "converted_to_draft" in _pr_types(doc)
    for job_name, job in _entry_jobs(doc).items():
        if _is_cancellation_job(job_name, job):
            continue
        condition = str(job.get("if", ""))
        assert "github.event.pull_request.draft != true" in condition
        assert "github.event.action == 'converted_to_draft'" not in condition


def test_opencode_verdict_gate_still_runs_on_ready_for_review() -> None:
    """The fail-closed verdict gate is untouched for ready (non-draft) events."""
    doc = _load("opencode-review.yml")
    target = doc["jobs"]["opencode-review-target"]
    steps = [s.get("name", "") for s in target["steps"]]
    assert "Fail closed without a current-head OpenCode verdict" in steps
    assert "draft" not in str(target.get("if", ""))
