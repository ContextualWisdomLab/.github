"""Regressions for dependency-review immutable identity validation."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _support_probe_script() -> str:
    """Return the executable shell body of the dependency-review support probe."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "security-scan.yml").read_text(
        encoding="utf-8"
    )
    step = "      - name: Check dependency review support\n"
    start = workflow.index(step)
    end = workflow.index("\n      - name:", start + len(step))
    block = workflow[start:end]
    run_marker = "        run: |\n"
    run_start = block.index(run_marker) + len(run_marker)
    return textwrap.dedent(block[run_start:])


def _run_probe(
    tmp_path: Path,
    repository: str,
    *,
    base_sha: str = "a" * 40,
    head_sha: str = "b" * 40,
    anonymous_status: str = "200",
    token_status: str = "200",
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Execute the probe with a fake curl and return process plus evidence paths."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl_marker = tmp_path / "curl-called"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "mode=anonymous\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"$arg\" == Authorization:* ]]; then mode=token; fi\n"
        "done\n"
        "printf '%s\\n' \"$mode\" >>\"${CURL_MARKER}\"\n"
        "if [ \"$mode\" = token ]; then\n"
        "  printf '%s' \"${TOKEN_STATUS:-200}\"\n"
        "else\n"
        "  printf '%s' \"${ANONYMOUS_STATUS:-200}\"\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env.get('PATH', '')}",
            "GH_TOKEN": "test-token",
            "BASE_SHA": base_sha,
            "HEAD_SHA": head_sha,
            "REPOSITORY": repository,
            "REPOSITORY_VISIBILITY": "public",
            "GITHUB_API_URL": "https://api.github.invalid",
            "GITHUB_OUTPUT": str(output),
            "CURL_MARKER": str(curl_marker),
            "ANONYMOUS_STATUS": anonymous_status,
            "TOKEN_STATUS": token_status,
        }
    )
    result = subprocess.run(
        ["bash", "-c", _support_probe_script()],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, curl_marker, output


def test_dependency_review_rejects_dot_path_components_before_curl(tmp_path: Path) -> None:
    """Reject dot-segment repository identities before any authenticated request."""
    for index, repository in enumerate(
        ("../.github", "ContextualWisdomLab/..", "ContextualWisdomLab/.", "./.github")
    ):
        case_dir = tmp_path / f"dot-{index}"
        case_dir.mkdir()
        result, curl_marker, _output = _run_probe(case_dir, repository)
        assert result.returncode != 0, repository
        assert not curl_marker.exists(), repository
        assert "repository identity" in result.stdout.lower(), repository


def test_dependency_review_rejects_non_owner_name_identity_before_curl(tmp_path: Path) -> None:
    """Reject repository values that are not exactly one owner/name pair."""
    for index, repository in enumerate(
        ("ContextualWisdomLab", "ContextualWisdomLab/Orgmetra/extra", "/Orgmetra")
    ):
        case_dir = tmp_path / f"shape-{index}"
        case_dir.mkdir()
        result, curl_marker, _output = _run_probe(case_dir, repository)
        assert result.returncode != 0, repository
        assert not curl_marker.exists(), repository
        assert "repository identity" in result.stdout.lower(), repository


def test_dependency_review_rejects_named_revisions_before_curl(tmp_path: Path) -> None:
    """Require immutable 40- or 64-hex Git object ids before comparison."""
    cases = (("main", "b" * 40), ("a" * 40, "develop"), ("a" * 39, "b" * 40))
    for index, (base_sha, head_sha) in enumerate(cases):
        case_dir = tmp_path / f"revision-{index}"
        case_dir.mkdir()
        result, curl_marker, _output = _run_probe(
            case_dir,
            "ContextualWisdomLab/Orgmetra",
            base_sha=base_sha,
            head_sha=head_sha,
        )
        assert result.returncode != 0, (base_sha, head_sha)
        assert not curl_marker.exists(), (base_sha, head_sha)
        assert "exact 40- or 64-character hexadecimal" in result.stdout.lower()


def test_dependency_review_allows_dotgithub_product_repository(tmp_path: Path) -> None:
    """Keep the organization .github product name valid while rejecting sentinels."""
    result, curl_marker, output = _run_probe(tmp_path, "ContextualWisdomLab/.github")
    assert result.returncode == 0, result.stdout + result.stderr
    assert curl_marker.exists()
    assert output.read_text(encoding="utf-8") == "supported=true\n"


def test_dependency_review_records_anonymous_and_job_token_canary(tmp_path: Path) -> None:
    """Distinguish public endpoint availability from the reusable-workflow token boundary."""
    result, curl_marker, output = _run_probe(
        tmp_path,
        "ContextualWisdomLab/ConceptWeave",
        anonymous_status="403",
        token_status="200",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert curl_marker.read_text(encoding="utf-8") == "anonymous\ntoken\n"
    assert output.read_text(encoding="utf-8") == "supported=true\n"
    assert "anonymous_http_status=403" in result.stdout
    assert "token_http_status=200" in result.stdout


def test_dependency_review_job_token_result_remains_authoritative(tmp_path: Path) -> None:
    """Fail closed when the job token cannot establish the exact comparison."""
    result, curl_marker, _output = _run_probe(
        tmp_path,
        "ContextualWisdomLab/ConceptWeave",
        anonymous_status="200",
        token_status="403",
    )
    assert result.returncode != 0
    assert curl_marker.read_text(encoding="utf-8") == "anonymous\ntoken\n"
    assert "anonymous_http_status=200" in result.stdout
    assert "token_http_status=403" in result.stdout
    assert "failing closed" in result.stdout.lower()
