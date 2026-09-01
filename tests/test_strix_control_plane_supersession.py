"""Regression contract for race-safe Strix predecessor-run supersession."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"


def _step(workflow: str, name: str) -> str:
    """Return one named workflow step body without interpreting YAML."""
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    next_step = workflow.find("\n      - name: ", start + len(marker))
    if next_step == -1:
        return workflow[start:]
    return workflow[start:next_step]


def test_strix_does_not_use_unordered_native_same_pr_cancellation() -> None:
    """Delayed PR events must not be able to cancel a newer live-head scan."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    pre_jobs = workflow.split("jobs:", 1)[0]

    assert "strix-workflow-${{" not in pre_jobs
    assert "cancel-in-progress:" not in pre_jobs
    assert "cancel-superseded-pr-runs:" not in workflow


def test_strix_validates_live_pr_before_expensive_setup() -> None:
    """Reject stale pull_request_target evidence before provider setup starts."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    early = _step(workflow, "Validate live pull request before Strix setup")

    assert workflow.index("Validate live pull request before Strix setup") < workflow.index(
        "Set up Python"
    )
    assert "if: github.event_name == 'pull_request_target'" in early
    assert "GH_TOKEN: ${{ github.token }}" in early
    assert "pull-requests: read" in workflow.split("  strix:", 1)[1].split("    steps:", 1)[0]
    assert "if ! pull_request_json=" in early
    assert "TARGET_REPOSITORY:" in early
    assert "PR_NUMBER:" in early
    assert "EXPECTED_HEAD_SHA:" in early
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in early
    assert ".state" in early
    assert ".head.sha" in early
    assert '"$live_state" != "open"' in early
    assert '"$live_head_sha" != "$EXPECTED_HEAD_SHA"' in early
    assert "exit 1" in early


def test_strix_revalidates_before_provider_execution() -> None:
    """Close the runner-queue race before contextual-orchestrator work begins."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    recheck = _step(workflow, "Revalidate live pull request before provider execution")

    assert workflow.index(
        "Revalidate live pull request before provider execution"
    ) < workflow.index("Provision contextual-orchestrator Strix sidecar")
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in recheck
    assert '"$live_state" != "open"' in recheck
    assert '"$live_head_sha" != "$EXPECTED_HEAD_SHA"' in recheck
    assert "exit 1" in recheck


def test_strix_revalidates_before_evidence_publication() -> None:
    """A head/state change during scanning must not publish stale artifacts."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    recheck = _step(workflow, "Revalidate live pull request before evidence publication")

    assert workflow.index(
        "Revalidate live pull request before evidence publication"
    ) < workflow.index("Collect Strix reports for artifact upload")
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in recheck
    assert '"$live_state" != "open"' in recheck
    assert '"$live_head_sha" != "$EXPECTED_HEAD_SHA"' in recheck
    assert "exit 1" in recheck
    assert "id: live_publication" in recheck
    assert "always() && github.event_name == 'pull_request_target'" in recheck
    collect = _step(workflow, "Collect Strix reports for artifact upload")
    upload = _step(workflow, "Upload Strix reports artifact")
    assert "steps.live_publication.outputs.current == 'true'" in collect
    assert "steps.live_publication.outputs.current == 'true'" in upload


def test_strix_preserves_provider_serialization_and_timeout_repair() -> None:
    """Bound queued scans without regressing the current Strix timeout contract."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    strix_job = workflow.split("  strix:", 1)[1]
    concurrency = strix_job.split("concurrency:", 1)[1].split("runs-on:", 1)[0]

    assert "github.event.client_payload.target_repository" in concurrency
    assert "github.event.pull_request.base.repo.full_name" in concurrency
    assert "github.repository" in concurrency
    assert "cancel-in-progress: false" in concurrency
    assert "github.event.pull_request.number" not in concurrency
    assert "export LLM_TIMEOUT=300" in workflow
