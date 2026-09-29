"""Control-pool review workflows must not occupy a runner for draft pull requests.

On 2026-09-29, 325 of 836 queued control-pool runs were for draft PRs; each
only concluded "draft, no verdict required". Entry jobs now skip drafts at
the job level, so no runner is assigned. This is safe only because every
workflow re-runs on `ready_for_review` (same head), where the real gate runs,
and because merge readiness comes from an opencode-agent review, not from
these check results.
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
    "codeql-pr.yml",
    "pr-review-merge-scheduler.yml",
]
DRAFT_GUARD = (
    "(github.event.pull_request.draft != true || github.event.action == 'converted_to_draft' "
    "|| github.event.action == 'closed')"
)


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


def test_opencode_verdict_gate_still_runs_on_ready_for_review() -> None:
    """The fail-closed verdict gate is untouched for ready (non-draft) events."""
    doc = _load("opencode-review.yml")
    target = doc["jobs"]["opencode-review-target"]
    steps = [s.get("name", "") for s in target["steps"]]
    assert "Fail closed without a current-head OpenCode verdict" in steps
    assert "draft" not in str(target.get("if", ""))
