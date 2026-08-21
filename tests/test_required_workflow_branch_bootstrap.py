from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_WORKFLOWS = (
    "close-empty-pr.yml",
    "noema-review.yml",
    "opencode-review.yml",
    "pr-review-merge-scheduler.yml",
    "sast-semgrep.yml",
    "security-scan.yml",
    "strix.yml",
)


def test_required_workflows_materialize_checks_on_non_default_branch_pushes() -> None:
    """Every all-branch ruleset gate must emit a check before a PR exists."""

    for workflow_name in REQUIRED_WORKFLOWS:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / workflow_name
        ).read_text(encoding="utf-8")
        assert "push:\n    branches: ['**']" in workflow, workflow_name


def test_push_bootstrap_never_executes_pr_or_provider_mutations() -> None:
    """A branch push may satisfy gates but cannot impersonate a pull request."""

    close_empty = (
        REPO_ROOT / ".github" / "workflows" / "close-empty-pr.yml"
    ).read_text(encoding="utf-8")
    security_scan = (
        REPO_ROOT / ".github" / "workflows" / "security-scan.yml"
    ).read_text(encoding="utf-8")
    noema = (
        REPO_ROOT / ".github" / "workflows" / "noema-review.yml"
    ).read_text(encoding="utf-8")

    assert "github.event_name == 'pull_request_target' && github.event.action != 'closed'" in close_empty
    assert security_scan.count("github.event_name == 'pull_request' && github.event.action != 'closed'") == 4
    assert "github.event_name != 'push' && (" in noema
