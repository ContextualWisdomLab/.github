"""Contracts for consolidating the central repository's PR Gitleaks scan."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from tests.test_opencode_workflow_shell_syntax import _extract_run_block


WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"


def _workflow(filename: str) -> str:
    return (WORKFLOWS / filename).read_text(encoding="utf-8")


def _on_block(workflow: str) -> str:
    match = re.search(r"(?m)^on:\n((?:.*\n)*?)(?=^\S|\Z)", workflow)
    assert match
    return match.group(1)


def _gitleaks_job(workflow: str) -> str:
    return workflow.split("  gitleaks:\n", 1)[1].split("\n  trivy-fs:", 1)[0]


def test_secret_scan_keeps_only_non_pr_backstops() -> None:
    """The standalone workflow retains every non-PR Gitleaks entry point."""
    trigger = _on_block(_workflow("secret-scan.yml"))

    assert "pull_request:" not in trigger
    assert "push:" in trigger
    assert "schedule:" in trigger
    assert 'types: [secret-scan]' in trigger


def test_security_scan_owns_the_fail_closed_pr_gitleaks_job() -> None:
    """The required bundle preserves the central PR Gitleaks hard gate."""
    workflow = _workflow("security-scan.yml")
    job = _gitleaks_job(workflow)

    assert "needs: changed-scope" not in job
    assert "github.event.action != 'closed'" in job
    assert "github.repository == 'ContextualWisdomLab/.github'" in job
    assert 'GITLEAKS_VERSION: "8.30.1"' in job
    assert 'GITLEAKS_SHA256: "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"' in job
    assert 'log_opts="${merge_base}..${HEAD_SHA}"' in job
    assert '--log-opts="${log_opts}"' in job
    assert "gitleaks-results.upload.sarif" in job
    assert "github/codeql-action/upload-sarif@cdf488f595d80d6e07e03d4674febd5ab45fa938 # v4.37.9" in job
    assert "if: steps.gitleaks.outputs.rc != '0'" in job
    assert "exit 1" in job


def test_gitleaks_binds_commit_range_to_live_base_merge_base() -> None:
    """A stale PR event base must not make Gitleaks rescan merged main history."""
    job = _gitleaks_job(_workflow("security-scan.yml"))
    permissions = job.split("    steps:\n", 1)[0]

    assert "pull-requests: read" in permissions
    assert 'gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}"' in job
    assert 'BASE_SHA="$(jq -r ".base.sha" <<<"${live_pr}")"' in job
    assert 'HEAD_SHA="$(jq -r ".head.sha" <<<"${live_pr}")"' in job
    assert 'merge_base="$(git merge-base "${BASE_SHA}" "${HEAD_SHA}")"' in job
    assert 'log_opts="${merge_base}..${HEAD_SHA}"' in job
    assert 'log_opts="${{ github.event.pull_request.base.sha }}..' not in job
    assert 'log_opts="${BASE_SHA}..${HEAD_SHA}"' not in job


def test_gitleaks_uses_only_the_authenticated_live_base_config() -> None:
    """A PR must not weaken secret policy through its own Gitleaks config."""
    job = _gitleaks_job(_workflow("security-scan.yml"))

    assert 'git cat-file -e "${BASE_SHA}:.gitleaks.toml"' in job
    assert 'git show "${BASE_SHA}:.gitleaks.toml"' in job
    assert 'config_args=(--config "${trusted_config}")' in job
    assert "if [ -f .gitleaks.toml ]" not in job
    assert "config_args=(--config .gitleaks.toml)" not in job


def test_gitleaks_keeps_fork_pull_requests_scannable() -> None:
    """A canonical base and exact head suffice; the head may live in a fork."""
    job = _gitleaks_job(_workflow("security-scan.yml"))

    assert 'base_repository="$(jq -r ".base.repo.full_name"' in job
    assert 'head_repository="$(jq -r ".head.repo.full_name"' not in job
    assert '[ "${head_repository}" != "${GITHUB_REPOSITORY}" ]' not in job


def test_gitleaks_executes_only_the_live_merge_base_range(tmp_path: Path) -> None:
    """Execute the workflow shell against a stale event-base repository graph."""
    git = shutil.which("git")
    bash = shutil.which("bash")
    if git is None or bash is None:
        pytest.skip("git and bash are required")

    origin = tmp_path / "origin.git"
    checkout = tmp_path / "checkout"
    subprocess.run([git, "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run([git, "init", "-b", "main", str(checkout)], check=True, capture_output=True)

    def run_git(*args: str) -> str:
        result = subprocess.run(
            [git, *args], cwd=checkout, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    run_git("config", "user.name", "Gitleaks Contract")
    run_git("config", "user.email", "gitleaks-contract@example.invalid")
    run_git("remote", "add", "origin", str(origin))
    (checkout / "README.md").write_text("old event base\n", encoding="utf-8")
    run_git("add", "README.md")
    run_git("commit", "-m", "old event base")
    stale_base = run_git("rev-parse", "HEAD")
    (checkout / "base-fixture.txt").write_text("already merged\n", encoding="utf-8")
    run_git("add", "base-fixture.txt")
    run_git("commit", "-m", "current base")
    live_base = run_git("rev-parse", "HEAD")
    run_git("push", "origin", "main")
    run_git("switch", "-c", "fork-feature")
    (checkout / "metadata.json").write_text("{}\n", encoding="utf-8")
    run_git("add", "metadata.json")
    run_git("commit", "-m", "metadata delta")
    head_sha = run_git("rev-parse", "HEAD")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$FAKE_PULL_JSON\"\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    gitleaks = checkout / "gitleaks"
    gitleaks.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$@\" >\"$FAKE_GITLEAKS_ARGS\"\n",
        encoding="utf-8",
    )
    gitleaks.chmod(0o755)

    script = _extract_run_block(
        _workflow("security-scan.yml"), "Run gitleaks on PR commit range"
    )
    args_file = tmp_path / "gitleaks-args.txt"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GH_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "ContextualWisdomLab/.github",
        "PR_NUMBER": "2041",
        "EVENT_BASE_REF": "main",
        "EVENT_HEAD_SHA": head_sha,
        "GITHUB_OUTPUT": str(tmp_path / "github-output.txt"),
        "RUNNER_TEMP": str(tmp_path),
        "FAKE_GITLEAKS_ARGS": str(args_file),
        "FAKE_PULL_JSON": json.dumps(
            {
                "state": "open",
                "base": {
                    "repo": {"full_name": "ContextualWisdomLab/.github"},
                    "ref": "main",
                    "sha": live_base,
                },
                "head": {
                    "repo": {"full_name": "outside/fork"},
                    "sha": head_sha,
                },
            }
        ),
    }
    result = subprocess.run(
        [bash], cwd=checkout, env=env, input=script, text=True,
        capture_output=True, check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert f"--log-opts={live_base}..{head_sha}" in args
    assert all(stale_base not in arg for arg in args)


def test_document_only_prs_still_admit_gitleaks() -> None:
    """Gitleaks remains independent from the document-only changed-scope gate."""
    workflow = _workflow("security-scan.yml")
    job = _gitleaks_job(workflow)

    assert "needs.changed-scope.outputs" not in job
    assert "*.md" not in job
