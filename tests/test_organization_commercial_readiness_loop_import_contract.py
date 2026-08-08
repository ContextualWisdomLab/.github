from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_WORKFLOW = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "organization-commercial-readiness-loop-quality-ci.yml"
)


def test_quality_gate_uses_import_stable_test_support() -> None:
    """Hosted and complete-suite collection must resolve the same helper module."""
    source = QUALITY_WORKFLOW.read_text(encoding="utf-8")

    assert "--import-mode=importlib" in source
    assert '"organization_commercial_readiness_fixtures.py"' in source
    assert "tests/organization_commercial_readiness_fixtures.py" not in source
    assert "--include='scripts/ci/organization_commercial_readiness_loop.py' \\\n            -m pytest" not in source
