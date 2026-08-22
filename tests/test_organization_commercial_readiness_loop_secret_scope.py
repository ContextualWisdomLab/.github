from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "organization-commercial-readiness-loop.yml"
)


def test_coordinator_token_is_scoped_only_to_the_dispatch_step() -> None:
    """Third-party actions never receive either cross-repository credential."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    before_dispatch, dispatch_step = source.split(
        "      - name: Coordinate one bounded fleet pass\n", maxsplit=1
    )

    assert "PR_REVIEW_MERGE_TOKEN" not in before_dispatch
    assert "GH_TOKEN:" not in before_dispatch
    assert "env:\n          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in dispatch_step
    assert "steps.opencode_app_token.outputs.token" not in source
    artifact_step = dispatch_step.split(
        "      - name: Preserve the exact fleet receipt\n", maxsplit=1
    )[1]
    assert "GH_TOKEN:" not in artifact_step
    assert "PR_REVIEW_MERGE_TOKEN" not in artifact_step
    assert "steps.opencode_app_token.outputs.token" not in artifact_step
