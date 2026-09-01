"""Regressions for dependency-review repository identity validation."""

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


def _run_probe(tmp_path: Path, repository: str) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Execute the probe with a fake curl and return process plus evidence paths."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl_marker = tmp_path / "curl-called"
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'called\\n' >\"${CURL_MARKER}\"\n"
        "printf '200'\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env.get('PATH', '')}",
            "GH_TOKEN": "test-token",
            "BASE_SHA": "a" * 40,
            "HEAD_SHA": "b" * 40,
            "REPOSITORY": repository,
            "REPOSITORY_VISIBILITY": "public",
            "GITHUB_API_URL": "https://api.github.invalid",
            "GITHUB_OUTPUT": str(output),
            "CURL_MARKER": str(curl_marker),
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
        case_dir = tmp_path / str(index)
        case_dir.mkdir()
        result, curl_marker, _output = _run_probe(case_dir, repository)
        assert result.returncode != 0, repository
        assert not curl_marker.exists(), repository
        assert "repository identity" in result.stdout.lower(), repository


def test_dependency_review_allows_dotgithub_product_repository(tmp_path: Path) -> None:
    """Keep the organization .github product name valid while rejecting sentinels."""
    result, curl_marker, output = _run_probe(tmp_path, "ContextualWisdomLab/.github")
    assert result.returncode == 0, result.stdout + result.stderr
    assert curl_marker.exists()
    assert output.read_text(encoding="utf-8") == "supported=true\n"
