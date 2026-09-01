from pathlib import Path


def test_repository_metadata_apply_is_central_dispatch_only():
    workflow = Path(".github/workflows/repository-metadata-reconcile.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_call:" not in workflow
    assert "repository: ContextualWisdomLab/.github" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "github.repository != 'ContextualWisdomLab/.github'" in workflow
    assert "github.ref != 'refs/heads/main'" in workflow


def test_metadata_token_is_materialized_only_in_apply_step():
    workflow = Path(".github/workflows/repository-metadata-reconcile.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("CWL_REPOSITORY_METADATA_TOKEN: ${{ secrets.CWL_REPOSITORY_METADATA_TOKEN }}") == 1
    assert "--audit-deepwiki" in workflow
