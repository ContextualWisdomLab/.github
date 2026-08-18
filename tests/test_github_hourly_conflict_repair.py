"""Regression contracts for unattended OpenCode merge-conflict repair."""

from pathlib import Path

from scripts.ci import pr_review_fix_scheduler as scheduler


_CALLER = Path(".github/workflows/github-hourly-review-repair.yml")
_REUSABLE_SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")


def _unreviewed_conflict() -> dict[str, object]:
    """Return a same-repository PR whose current head has no review yet."""
    return {
        "number": 1098,
        "isDraft": False,
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature/conflict",
        "headRefOid": "a" * 40,
        "headRepository": {"nameWithOwner": "ContextualWisdomLab/.github"},
        "mergeStateStatus": "DIRTY",
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
    }


def test_explicit_policy_dispatches_unreviewed_conflict() -> None:
    """Conflict repair must not wait for an approval invalidated by its own commit."""
    needs_repair, reasons = scheduler.needs_conflict_resolution(
        _unreviewed_conflict(),
        allow_unreviewed=True,
    )

    assert needs_repair
    assert "fresh review and checks" in reasons[0]


def test_default_library_policy_remains_backward_compatible() -> None:
    """Direct library callers retain the prior approval requirement unless opted in."""
    assert scheduler.needs_conflict_resolution(_unreviewed_conflict()) == (False, ())


def test_cli_exposes_unreviewed_conflict_policy() -> None:
    """The trusted workflow can opt into unreviewed conflict repair explicitly."""
    arguments = scheduler.parse_args(
        [
            "--repo",
            "ContextualWisdomLab/.github",
            "--base-branch",
            "main",
            "--resolve-unreviewed-conflicts",
        ]
    )

    assert arguments.resolve_unreviewed_conflicts is True


def test_reusable_scheduler_enables_policy_for_hourly_callers() -> None:
    """Central callers receive conflict repair by default without duplicating logic."""
    workflow = _REUSABLE_SCHEDULER.read_text(encoding="utf-8")

    assert "resolve_unreviewed_conflicts:" in workflow
    policy_block = workflow.split("resolve_unreviewed_conflicts:", maxsplit=1)[1].split(
        "retry_hours:", maxsplit=1
    )[0]
    assert "default: true" in policy_block
    assert "--resolve-unreviewed-conflicts" in workflow


def test_central_repository_has_hourly_self_caller() -> None:
    """The central repository itself is scanned instead of relying on product callers."""
    workflow = _CALLER.read_text(encoding="utf-8")

    assert 'cron: "21 * * * *"' in workflow
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in workflow
    assert "target_repository: ContextualWisdomLab/.github" in workflow
    assert "base_branch: main" in workflow
    assert "resolve_unreviewed_conflicts: true" in workflow
    assert 'max_dispatches: "1"' in workflow
    assert 'retry_hours: "1"' in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow


def test_scheduled_self_target_does_not_require_cross_repository_allowlist() -> None:
    """A protected same-repository schedule is valid even without cross-repo config."""
    workflow = _REUSABLE_SCHEDULER.read_text(encoding="utf-8")

    assert 'if [ "$TARGET_REPOSITORY" = "${GITHUB_REPOSITORY}" ]; then' in workflow
    assert "Self-targeted scheduler invocation uses the protected caller repository." in workflow
