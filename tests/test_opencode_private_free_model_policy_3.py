"""Integration tests for private-repository OpenCode free-model eligibility."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY_CHECKER = ROOT / "scripts" / "ci" / "opencode_private_free_model_policy.py"
POLICY_PATH = Path(".github/opencode-private-free-models.json")
SPEC = importlib.util.spec_from_file_location("opencode_private_free_model_policy", POLICY_CHECKER)
assert SPEC is not None and SPEC.loader is not None
POLICY_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = POLICY_MODULE
SPEC.loader.exec_module(POLICY_MODULE)

VALID_POLICY = {
    "schema_version": 1,
    "allow_private_free_models": True,
    "repository_data_classification": "public_equivalent",
    "external_model_data_use_accepted": True,
}


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with deterministic Git identity and no global config."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "OpenCode Policy Test",
            "GIT_AUTHOR_EMAIL": "opencode-policy@example.invalid",
            "GIT_COMMITTER_NAME": "OpenCode Policy Test",
            "GIT_COMMITTER_EMAIL": "opencode-policy@example.invalid",
        }
    )
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def git(repo: Path, *args: str) -> str:
    """Run Git and return stripped stdout, failing the test on errors."""
    result = run("git", *args, cwd=repo)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    """Commit every tracked and untracked fixture and return its SHA."""
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write_policy(repo: Path, value: object = VALID_POLICY) -> None:
    """Write one UTF-8 policy document under the fixed governance path."""
    path = repo / POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    """Create one isolated Git repository with an initial ordinary file."""
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "--initial-branch=main")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    commit_all(repo, "initial")
    return repo


def evaluate(repo: Path, base_sha: str, head_sha: str, *extra: str) -> subprocess.CompletedProcess[str]:
    """Evaluate the policy through its real ``main`` function for coverage."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    arguments = [
        "--repo-root",
        str(repo),
        "--base-sha",
        base_sha,
        "--head-sha",
        head_sha,
        *extra,
    ]
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            returncode = POLICY_MODULE.main(arguments)
        except SystemExit as exc:
            returncode = int(exc.code)
    return subprocess.CompletedProcess(
        args=arguments,
        returncode=returncode,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
    )


def test_symlink_policy_fails_closed(repository: Path) -> None:
    """The governance file must be a regular non-executable Git blob."""
    outside = repository / "outside.json"
    outside.write_text(json.dumps(VALID_POLICY), encoding="utf-8")
    policy = repository / POLICY_PATH
    policy.parent.mkdir(parents=True, exist_ok=True)
    try:
        policy.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")
    base_sha = commit_all(repository, "add symlink policy")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "regular" in result.stderr.casefold()


def test_read_policy_blob_rejects_truncation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The immutable blob byte count must match the Git object metadata."""
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, b"5\n", b""),
            subprocess.CompletedProcess([], 0, b"four", b""),
        ]
    )
    monkeypatch.setattr(POLICY_MODULE, "run_git", lambda *_args, **_kwargs: next(responses))
    entry = POLICY_MODULE.GitBlobEntry("100644", "blob", "0" * 40, POLICY_PATH.as_posix())

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="truncated"):
        POLICY_MODULE.read_policy_blob(tmp_path, entry)


def test_policy_blob_entry_rejects_multiple_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An impossible ambiguous tree response fails as an internal error."""
    record = b"100644 blob " + b"0" * 40 + b"\t" + POLICY_PATH.as_posix().encode()
    monkeypatch.setattr(
        POLICY_MODULE,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, record + b"\x00" + record + b"\x00", b""),
    )

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="more than one"):
        POLICY_MODULE.policy_blob_entry(tmp_path, "0" * 40)


def test_policy_blob_entry_rejects_invalid_blob_sha(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Only full immutable blob identifiers are accepted from the tree parser."""
    record = b"100644 blob short\t" + POLICY_PATH.as_posix().encode() + b"\x00"
    monkeypatch.setattr(
        POLICY_MODULE,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, record, b""),
    )

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="blob SHA"):
        POLICY_MODULE.policy_blob_entry(tmp_path, "0" * 40)


def test_missing_base_policy_fails_closed(repository: Path) -> None:
    """A private repository without explicit governance remains ineligible."""
    base_sha = git(repository, "rev-parse", "HEAD")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "ineligible" in result.stderr.casefold()
    assert "missing" in result.stderr.casefold()


def test_unexpected_git_diff_status_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Git diff errors are distinct from a legitimate changed policy."""
    monkeypatch.setattr(
        POLICY_MODULE,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 2, b"", b"failure"),
    )

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="compare"):
        POLICY_MODULE.require_policy_unchanged(tmp_path, "0" * 40, "1" * 40)


def test_policy_added_by_reviewed_head_cannot_activate_itself(repository: Path) -> None:
    """A PR cannot opt its own untrusted head into external free-model review."""
    base_sha = git(repository, "rev-parse", "HEAD")
    write_policy(repository)
    head_sha = commit_all(repository, "self opt in")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "changed" in result.stderr.casefold()


def test_denial_can_remain_silent() -> None:
    """Expected missing-policy outcomes do not add noise without explanation."""
    with pytest.raises(SystemExit) as raised:
        POLICY_MODULE.deny("hidden reason", False)

    assert raised.value.code == 1


