"""Regression contract for anomalous public dependency-review HTTP 403 responses.

The organization-required Security Scan on ConceptWeave foundation head
8e8783286eac7567803568d9a91010daaf028074 reached a real hosted runner and
failed in dependency-review preflight with HTTP 403 even though the target is a
public, non-fork repository and the job token has ``contents: read``. GitHub's
published endpoint contract permits public access without authentication and
otherwise documents 403 for private repositories without the required security
entitlement or forks. Keep this anomaly fail-closed, but do not make one
transient/ambiguous token response the only observation before rejecting a
public non-fork target.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _support_step() -> str:
    """Return the dependency-review support preflight from the required workflow."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "security-scan.yml").read_text(
        encoding="utf-8"
    )
    marker = "      - name: Check dependency review support\n"
    start = workflow.index(marker)
    end = workflow.index("\n      - name: Dependency review\n", start)
    return workflow[start:end]


def test_public_nonfork_403_gets_bounded_same_token_reobservation() -> None:
    """Retry an anomalous public/non-fork 403 without ever treating 403 as success."""
    step = _support_step()

    assert "REPOSITORY_IS_FORK:" in step
    assert "github.event.repository.fork" in step
    assert "for attempt in 1 2 3" in step
    assert '"$http_status" = "403"' in step
    assert '"$repository_visibility" = "public"' in step
    assert '"${REPOSITORY_IS_FORK:-}" = "false"' in step
    assert "sleep" in step
    assert 'if [ "$curl_status" -ne 0 ] || [ "$http_status" != "200" ]; then' in step
    assert 'echo "supported=true" >>"$GITHUB_OUTPUT"' in step


def test_public_403_diagnostics_keep_request_identity_without_response_body_dump() -> None:
    """Retain bounded GitHub request/rate evidence while keeping response bodies private."""
    step = _support_step()

    assert "X-GitHub-Request-Id" in step
    assert "Retry-After" in step
    assert "X-RateLimit-Remaining" in step
    assert "DEPENDENCY_REVIEW_SUPPORT" in step
    assert "cat " not in step
    assert "Failing closed" in step
