from pathlib import Path


def test_opencode_docker_evidence_never_exposes_host_daemon_to_pr_code() -> None:
    """Docker checks defer to peer CI instead of mounting a privileged daemon."""
    workflow = Path(".github/workflows/opencode-review-dispatch.yml").read_text(encoding="utf-8")

    assert "central coverage sandbox intentionally has no host Docker socket" in workflow
    assert "current-head repository Docker build/compose check" in workflow
    assert "/var/run/docker.sock" not in workflow
    assert 'docker build --pull=false -f "$dockerfile"' not in workflow
