from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_codeql_pr_workflow_uploads_head_and_merge_sarif_for_ruleset_gate() -> None:
    workflow = (REPO_ROOT / ".github/workflows/codeql-pr.yml").read_text(
        encoding="utf-8"
    )

    assert "name: CodeQL PR" in workflow
    assert "branches: [main, master, develop]" in workflow
    assert "upload: always" in workflow
    assert "analyze-head:" in workflow
    assert "analyze-merge:" in workflow
    assert "CodeQL merge preview" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "github.event.pull_request.merge_commit_sha" in workflow
    assert "refs/pull/{0}/head" in workflow
    assert "refs/pull/{0}/merge" in workflow
    assert "security-events: write" in workflow