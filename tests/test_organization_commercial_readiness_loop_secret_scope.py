from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "organization-commercial-readiness-loop.yml"
)


def test_maintainer_token_is_scoped_only_to_the_dispatch_step() -> None:
    """Third-party setup actions must never receive the cross-repository token."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    before_dispatch, dispatch_step = source.split(
        "      - name: Coordinate one bounded fleet pass\n", maxsplit=1
    )

    assert "PR_REVIEW_MERGE_TOKEN" not in before_dispatch
    assert "GH_TOKEN:" not in before_dispatch
    assert "env:\n          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in dispatch_step


def test_missing_maintainer_token_is_an_auditable_noop() -> None:
    """Absent cross-repository authority must not create a failing empty receipt."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert '"status": "skipped_credential_unavailable"' in source
    assert "organization-commercial-readiness-loop.json" in source
    assert "Provision PR_REVIEW_MERGE_TOKEN" in source
    assert "No cross-repository dispatch was attempted" in source
