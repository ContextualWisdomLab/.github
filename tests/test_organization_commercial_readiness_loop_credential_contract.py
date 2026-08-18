from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "organization-commercial-readiness-loop.yml"
)


def test_central_schedule_has_no_branch_selected_or_reviewer_credential_path() -> None:
    """The fleet coordinator must be schedule-only and use maintainer authority."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" not in source
    assert "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in source
    assert "persist-credentials: false" in source
    assert "OPENCODE_APPROVE_TOKEN" not in source
    assert "DRY_RUN" not in source
    assert "inputs.dry_run" not in source
