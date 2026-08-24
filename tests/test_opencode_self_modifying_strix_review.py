from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _workflow_function(name: str, next_name: str) -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start_marker = f"          {name}() {{\n"
    end_marker = f"\n\n          {next_name}() {{\n"
    start = workflow.index(start_marker)
    end = workflow.index(end_marker, start)
    return textwrap.dedent(workflow[start:end])


def _fixture_repo(tmp_path: Path, changed_path: str) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    target = repo / changed_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("base\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    base_sha = git(repo, "rev-parse", "HEAD")
    target.write_text("head\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "head")
    return repo, base_sha, git(repo, "rev-parse", "HEAD")


def _classify(
    repo: Path,
    base_sha: str,
    head_sha: str,
    evidence: str,
    tmp_path: Path,
) -> int:
    evidence_file = tmp_path / "evidence.log"
    evidence_file.write_text(evidence, encoding="utf-8")
    function = _workflow_function(
        "self_modifying_strix_base_failure",
        "leave_review_unchanged_for_self_modifying_strix_if_present",
    )
    script = "\n".join(
        (
            "set -euo pipefail",
            "self_healed_strix_dependency_base_failure() { return 1; }",
            function,
            'self_modifying_strix_base_failure "$1"',
        )
    )
    return subprocess.run(
        ["bash", "-c", script, "classifier", str(evidence_file)],
        cwd=repo,
        env={
            "PATH": "/usr/bin:/bin",
            "OPENCODE_SOURCE_WORKDIR": str(repo),
            "PR_BASE_SHA": base_sha,
            "PR_HEAD_SHA": head_sha,
        },
        check=False,
    ).returncode


def _provider_failure(base_sha: str) -> str:
    return "\n".join(
        (
            f"2026-08-24T13:15:09.1271786Z [command]/usr/bin/git checkout --progress --force {base_sha}",
            f"2026-08-24T13:15:09.1651569Z HEAD is now at {base_sha[:7]} trusted gate",
            "2026-08-24T13:36:17.3938869Z Primary model unavailable; retrying with fallback 'openai-direct/gpt-5.6-luna'.",
            "2026-08-24T13:36:22.0325148Z │  Error: 404 page not found  │",
            "2026-08-24T13:36:22.1229143Z Strix run failed for model 'openai-direct/gpt-5.6-luna' after 5s (exit code 1).",
            "2026-08-24T13:36:22.3504809Z Strix fallback model 'openai-direct/gpt-5.6-luna' emitted provider infrastructure or failure-signal output; trying next configured fallback if available.",
            "",
        )
    )


def test_provider_failure_from_exact_trusted_base_is_predecessor_evidence(
    tmp_path: Path,
) -> None:
    """A required Strix run executing the changed gate's base must not author a source verdict."""
    repo, base_sha, head_sha = _fixture_repo(
        tmp_path, "scripts/ci/strix_quick_gate.sh"
    )
    assert _classify(
        repo, base_sha, head_sha, _provider_failure(base_sha), tmp_path
    ) == 0


@pytest.mark.parametrize(
    "changed_path",
    ("README.md", ".github/workflows/unrelated.yml"),
)
def test_unrelated_pr_cannot_suppress_provider_failure(
    tmp_path: Path, changed_path: str
) -> None:
    repo, base_sha, head_sha = _fixture_repo(tmp_path, changed_path)
    assert _classify(
        repo, base_sha, head_sha, _provider_failure(base_sha), tmp_path
    ) != 0


def test_missing_exact_base_checkout_cannot_suppress_failure(tmp_path: Path) -> None:
    repo, base_sha, head_sha = _fixture_repo(
        tmp_path, "scripts/ci/strix_quick_gate.sh"
    )
    evidence = _provider_failure(base_sha).replace(
        f"git checkout --progress --force {base_sha}",
        f"git checkout --progress --force {head_sha}",
    )
    assert _classify(repo, base_sha, head_sha, evidence, tmp_path) != 0


def test_authoritative_vulnerability_evidence_remains_source_backed(
    tmp_path: Path,
) -> None:
    repo, base_sha, head_sha = _fixture_repo(
        tmp_path, "scripts/ci/strix_quick_gate.sh"
    )
    evidence = _provider_failure(base_sha) + (
        "2026-08-24T13:30:00.0000000Z │  Vulnerabilities 1  │\n"
        "2026-08-24T13:30:00.0000001Z │  Severity: HIGH  │\n"
    )
    assert _classify(repo, base_sha, head_sha, evidence, tmp_path) != 0
