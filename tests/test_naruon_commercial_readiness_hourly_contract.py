"""Static contracts for the Naruon hourly commercial-readiness automation."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def workflow_text(name: str) -> str:
    """Return one central workflow as UTF-8 text."""
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def trigger_contract(workflow: str) -> str:
    """Return the workflow trigger section before the concurrency declaration."""
    return workflow.split("concurrency:", 1)[0]


def test_hourly_loop_has_fixed_schedule_and_no_branch_selected_dispatch() -> None:
    """The hourly entrypoint must be default-branch-only and fixed to Naruon."""
    workflow = workflow_text("naruon-commercial-readiness-hourly.yml")
    trigger = trigger_contract(workflow)

    assert 'cron: "7 * * * *"' in trigger
    assert "repository_dispatch:" in trigger
    assert "types: [naruon-commercial-readiness-hourly]" in trigger
    assert "workflow_dispatch:" not in trigger
    assert "TARGET_REPOSITORY: ContextualWisdomLab/naruon" in workflow
    assert "TARGET_BASE_BRANCH: develop" in workflow
    assert "DISPATCH_REPOSITORY: ContextualWisdomLab/.github" in workflow


def test_hourly_loop_dispatches_fix_merge_and_zero_queue_development() -> None:
    """Every hourly run must drain PRs before it is allowed to develop."""
    workflow = workflow_text("naruon-commercial-readiness-hourly.yml")

    assert '"event_type": "pr-review-fix-scheduler"' in workflow
    assert '"event_type": "merge-scheduler"' in workflow
    assert '"event_type": "naruon-commercial-readiness-development"' in workflow
    assert 'if [ "$OPEN_PR_COUNT" -ne 0 ]; then' in workflow
    assert 'review_dispatch_limit: "-1"' in workflow
    assert 'stale_opencode_minutes: "60"' in workflow
    assert 'startsWith("autonomous/commercial-readiness-")' in workflow


def test_development_worker_uses_a_fixed_trusted_dispatch() -> None:
    """The development worker must reject caller-controlled repositories and refs."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")
    trigger = trigger_contract(workflow)

    assert "repository_dispatch:" in trigger
    assert "types: [naruon-commercial-readiness-development]" in trigger
    assert "workflow_dispatch:" not in trigger
    assert 'TARGET_REPOSITORY: "ContextualWisdomLab/naruon"' in workflow
    assert 'TARGET_BASE_BRANCH: "develop"' in workflow
    assert 'EXPECTED_TARGET_REPOSITORY: "ContextualWisdomLab/naruon"' in workflow
    assert 'EXPECTED_TARGET_BASE_BRANCH: "develop"' in workflow
    assert 'github.event.client_payload.target_repository != env.EXPECTED_TARGET_REPOSITORY' in workflow
    assert 'github.event.client_payload.base_branch != env.EXPECTED_TARGET_BASE_BRANCH' in workflow


def test_development_worker_revalidates_zero_prs_and_single_agent_work() -> None:
    """Product development must stop when any competing PR or agent branch exists."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert 'open_pr_count="$(gh api --paginate' in workflow
    assert 'if [ "$open_pr_count" -ne 0 ]; then' in workflow
    assert "autonomous/commercial-readiness-" in workflow
    assert 'if [ "$autonomous_branch_count" -ne 0 ]; then' in workflow
    assert 'if [ "$live_base_sha" != "$BASE_SHA" ]; then' in workflow
    assert 'if [ "$publish_open_pr_count" -ne 0 ]; then' in workflow


def test_development_worker_blocks_sensitive_and_unreviewable_changes() -> None:
    """Autonomous edits remain small, test-backed, and outside control-plane files."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert "MAX_CHANGED_FILES=12" in workflow
    assert "MAX_CHANGED_LINES=1200" in workflow
    assert "^\\.github/workflows/" in workflow
    assert "^\\.env" in workflow
    assert "BEGIN.*PRIVATE KEY" in workflow
    assert 'grep -Eq "(^|/)test[^/]*\\.|(^|/)tests?/"' in workflow
    assert 'grep -Fxq "CHANGELOG.md"' in workflow
    assert "git push origin HEAD:develop" not in workflow
    assert "git push --force" not in workflow


def test_development_worker_runs_repository_validation() -> None:
    """A generated PR must pass both backend and frontend repository contracts."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert "python -m ruff check ." in workflow
    assert "python -m pytest -q" in workflow
    assert "pnpm install --frozen-lockfile" in workflow
    assert "pnpm run lint" in workflow
    assert "pnpm run typecheck" in workflow
    assert "pnpm test" in workflow
    assert "pnpm run build" in workflow
    assert "git diff --check" in workflow


def test_development_worker_opens_one_pr_and_dispatches_review() -> None:
    """Successful development is published only through a normal reviewed PR."""
    workflow = workflow_text("naruon-commercial-readiness-development.yml")

    assert 'DEVELOPMENT_BRANCH="autonomous/commercial-readiness-${GITHUB_RUN_ID}"' in workflow
    assert 'git push origin "HEAD:${DEVELOPMENT_BRANCH}"' in workflow
    assert "gh pr create" in workflow
    assert '"event_type": "merge-scheduler"' in workflow
    assert 'review_dispatch_limit: "-1"' in workflow
    assert 'merge_mode: "direct_or_auto"' in workflow
    assert "--draft" not in workflow
