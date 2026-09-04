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

import os
from pathlib import Path
import subprocess
import textwrap


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


def _support_script() -> str:
    """Extract the Bash body so the retry/fail-closed state machine can execute."""
    step = _support_step()
    marker = "        run: |\n"
    return textwrap.dedent(step.split(marker, 1)[1])


def _write_fake_curl(bin_dir: Path) -> Path:
    """Create a deterministic curl double that emits status and safe GitHub headers."""
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
headers=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -D) headers="$2"; shift 2 ;;
    *) shift ;;
  esac
done
count=0
if [ -f "$FAKE_COUNT_FILE" ]; then count="$(cat "$FAKE_COUNT_FILE")"; fi
count=$((count + 1))
printf '%s' "$count" >"$FAKE_COUNT_FILE"
IFS=',' read -r -a codes <<<"$FAKE_CODES"
index=$((count - 1))
if [ "$index" -ge "${#codes[@]}" ]; then index=$((${#codes[@]} - 1)); fi
code="${codes[$index]}"
printf 'HTTP/2 %s\\r\\nX-GitHub-Request-Id: req-%s\\r\\nX-RateLimit-Remaining: 4999\\r\\nRetry-After: 0\\r\\n\\r\\n' "$code" "$count" >"$headers"
printf '%s' "$code"
""",
        encoding="utf-8",
    )
    curl.chmod(0o700)
    return curl


def _run_support_probe(
    tmp_path: Path,
    *,
    codes: str,
    visibility: str = "public",
    is_fork: str = "false",
) -> tuple[subprocess.CompletedProcess[str], int, str]:
    """Execute the exact workflow script with deterministic HTTP observations."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_curl(bin_dir)
    count_file = tmp_path / "curl-count"
    github_output = tmp_path / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_COUNT_FILE": str(count_file),
            "FAKE_CODES": codes,
            "GH_TOKEN": "test-token",
            "BASE_SHA": "base-sha",
            "HEAD_SHA": "head-sha",
            "REPOSITORY": "ContextualWisdomLab/example",
            "REPOSITORY_VISIBILITY": visibility,
            "REPOSITORY_IS_FORK": is_fork,
            "GITHUB_OUTPUT": str(github_output),
        }
    )
    result = subprocess.run(
        ["bash", "-c", _support_script()],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    attempts = int(count_file.read_text(encoding="utf-8"))
    outputs = github_output.read_text(encoding="utf-8") if github_output.exists() else ""
    return result, attempts, outputs


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
    assert "-o /dev/null" in step
    assert "Failing closed" in step


def test_public_nonfork_403_then_200_reaches_the_hard_gate(tmp_path: Path) -> None:
    """A bounded same-token re-observation may succeed only after an actual HTTP 200."""
    result, attempts, outputs = _run_support_probe(tmp_path, codes="403,403,200")

    assert result.returncode == 0, result.stderr
    assert attempts == 3
    assert outputs == "supported=true\n"
    assert "attempt=1 http_status=403" in result.stdout
    assert "attempt=3 http_status=200" in result.stdout
    assert "X-GitHub-Request-Id=req-3" in result.stdout


def test_persistent_public_nonfork_403_stays_fail_closed(tmp_path: Path) -> None:
    """Three authenticated 403 observations never become support evidence."""
    result, attempts, outputs = _run_support_probe(tmp_path, codes="403,403,403")

    assert result.returncode != 0
    assert attempts == 3
    assert outputs == ""
    assert "Failing closed" in result.stdout
    assert "HTTP 403" in result.stdout
    assert "request req-3" in result.stdout


def test_private_403_is_not_retried_as_a_public_anomaly(tmp_path: Path) -> None:
    """Private repositories retain the original immediate fail-closed behavior."""
    result, attempts, outputs = _run_support_probe(
        tmp_path, codes="403,200", visibility="private"
    )

    assert result.returncode != 0
    assert attempts == 1
    assert outputs == ""


def test_public_fork_403_is_not_retried_as_a_nonfork_anomaly(tmp_path: Path) -> None:
    """Forks retain the documented unsupported/fail-closed boundary."""
    result, attempts, outputs = _run_support_probe(tmp_path, codes="403,200", is_fork="true")

    assert result.returncode != 0
    assert attempts == 1
    assert outputs == ""
