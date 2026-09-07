"""Guard central security workflows against losing stacked-PR coverage."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_security_workflows_run_for_stacked_pull_requests() -> None:
    """Required PR security workflows must not filter out feature bases."""
    for workflow_name in ("security-scan.yml", "sast-semgrep.yml"):
        workflow = (REPO_ROOT / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        lines = workflow.splitlines()
        pull_request_index = lines.index("  pull_request:")
        pull_request_block = []
        for line in lines[pull_request_index + 1 :]:
            if line and not line.startswith(" "):
                break
            if line.startswith("  ") and not line.startswith("    ") and line.strip():
                break
            pull_request_block.append(line)
        assert "pull_request:" in workflow
        assert (
            "# Scan every PR base ref" in workflow
            or "# Do not restrict the base ref" in workflow
        )
        assert not any(line.strip().startswith("branches:") for line in pull_request_block)
