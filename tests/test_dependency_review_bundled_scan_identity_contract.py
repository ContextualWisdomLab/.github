"""Regression contract for the bundled Security Scan Dependency Review preflight."""

from __future__ import annotations

from pathlib import Path


_WORKFLOW = Path(".github/workflows/security-scan.yml")


def _workflow_text() -> str:
    """Return the bundled Security Scan workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_bundled_scan_requires_exact_git_object_ids_before_transport() -> None:
    """Named or malformed base/head revisions must fail before compare transport."""
    workflow = _workflow_text()
    assert "git_object_id='^[0-9a-f]{40}([0-9a-f]{24})?$'" in workflow
    assert 'if ! [[ "${BASE_SHA}" =~ $git_object_id ]]' in workflow
    assert '! [[ "${HEAD_SHA}" =~ $git_object_id ]]' in workflow
    assert "exact 40- or 64-character hexadecimal base and head revisions" in workflow
    assert "Named refs are not evidence" in workflow


def test_bundled_scan_requires_one_non_dot_owner_name_identity() -> None:
    """Repository identity validation keeps .github legal but rejects path sentinels."""
    workflow = _workflow_text()
    assert "repository_identity='^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'" in workflow
    assert 'if ! [[ "${REPOSITORY}" =~ $repository_identity ]]' in workflow
    assert 'repository_owner="${REPOSITORY%%/*}"' in workflow
    assert 'repository_name="${REPOSITORY#*/}"' in workflow
    assert '[ "${repository_owner}" = "." ]' in workflow
    assert '[ "${repository_owner}" = ".." ]' in workflow
    assert '[ "${repository_name}" = "." ]' in workflow
    assert '[ "${repository_name}" = ".." ]' in workflow


def test_bundled_scan_uses_job_token_and_fails_closed_on_non_200() -> None:
    """Only an authenticated successful exact comparison may admit Dependency Review."""
    workflow = _workflow_text()
    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert '-H "Authorization: Bearer ${GH_TOKEN}"' in workflow
    assert 'if [ "$curl_status" -ne 0 ] || [ "$http_status" != "200" ]; then' in workflow
    assert 'echo "supported=true" >>"$GITHUB_OUTPUT"' in workflow
    assert "actions/dependency-review-action@a1d282b36b6f3519aa1f3fc636f609c47dddb294" in workflow
