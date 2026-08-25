from pathlib import Path


CALLER = Path(".github/workflows/lineageweave-hourly-review-repair.yml")
REUSABLE_SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")
DOCTORING = Path("docs/doctoring/lineageweave-hourly-review-caller.md")


def test_lineageweave_uses_reserved_heartbeat_and_target() -> None:
    """The caller schedules the real LineageWeave repair boundary."""
    caller = CALLER.read_text(encoding="utf-8")

    assert REUSABLE_SCHEDULER.is_file()
    assert 'cron: "4 * * * *"' in caller
    assert "group: lineageweave-hourly-review-repair" in caller
    assert "cancel-in-progress: false" in caller
    assert "target_repository: ContextualWisdomLab/LineageWeave" in caller
    assert "base_branch: main" in caller
    assert 'max_prs: "50"' in caller
    assert 'max_dispatches: "1"' in caller
    assert 'retry_hours: "2"' in caller
    assert 'PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}' in caller
    assert 'OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}' in caller


def test_lineageweave_doctoring_preserves_allowlist_and_protected_merge_boundary() -> None:
    """The operational record tells maintainers what must be configured next."""
    doctoring = DOCTORING.read_text(encoding="utf-8")

    assert "minute `4`" in doctoring
    assert "OPENCODE_REPOSITORY_DISPATCH_TARGETS" in doctoring
    assert "ContextualWisdomLab/LineageWeave" in doctoring
    assert "independent approval" in doctoring
    assert "protected merge" in doctoring
