"""Workflow contract for trusted current-head Actions queue cleanup."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def _workflow_text() -> str:
    """Return the trusted scheduler workflow text under test."""
    return WORKFLOW.read_text(encoding="utf-8")


def test_queue_hygiene_resolves_live_refs_before_classifying_runs() -> None:
    """PR-list SHA snapshots must not authorize destructive cancellation."""
    workflow = _workflow_text()
    assert "ORG_QUEUE_HYGIENE_MAX_REF_LOOKUPS" in workflow
    assert '"/repos/${head_repo}/git/ref/heads/${encoded_head_ref}"' in workflow
    assert "open_pr_heads_json=\"{}\"" in workflow
    assert ".head.sha" not in workflow.split("# Queue hygiene, part 1:", 1)[1].split(
        "# Queue hygiene, part 2:", 1
    )[0]


def test_each_destructive_candidate_gets_final_trusted_revalidation() -> None:
    """Both superseded and aged-orphan paths must use the trusted helper."""
    workflow = _workflow_text()
    queue_block = workflow.split("# Queue hygiene, part 1:", 1)[1]
    assert "bash scripts/ci/revalidate_queue_cancellation.sh" in queue_block
    assert '"$open_pr_heads_json" \\\n                    superseded' in queue_block
    assert '"$open_pr_heads_json" \\\n                    aged-orphan' in queue_block
    assert 'gh api -X POST "/repos/${repo_full_name}/actions/runs/${run_id}/cancel"' not in queue_block


def test_current_main_queue_pressure_controls_remain_intact() -> None:
    """The repair must retain the current protected-main queue-pressure policy."""
    workflow = _workflow_text()
    assert '- cron: "0 * * * *"' in workflow
    assert "github.event_name == 'pull_request_review'" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "ORG_SWEEP_ROTATION_INDEX=$(( $(date -u +%s) / 3600 ))" in workflow
