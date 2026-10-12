"""Static contracts for the privileged repository metadata workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "repository-metadata-reconcile.yml"


def test_metadata_apply_uses_dedicated_least_privilege_credential() -> None:
    """Repository settings writes must not reuse the review/merge credential."""
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "secrets.CWL_REPOSITORY_METADATA_TOKEN" in source
    apply_source = source.split("  apply:", 1)[1]
    assert "secrets.PR_REVIEW_MERGE_TOKEN" not in apply_source
    assert "Require dedicated repository settings credential" in apply_source
    assert 'test -n "${GH_TOKEN}"' in apply_source


def test_metadata_validation_checks_out_published_evidence_ancestry() -> None:
    """The full-suite lineage guard must receive every published ancestor object."""
    source = WORKFLOW.read_text(encoding="utf-8")
    validate_source = source.split("jobs:\n  validate:", 1)[1].split("\n  apply:", 1)[0]
    checkout_source = validate_source.split("- name: Check out exact revision", 1)[1].split(
        "- name: Verify exact revision", 1
    )[0]

    assert "fetch-depth: 0" in checkout_source
