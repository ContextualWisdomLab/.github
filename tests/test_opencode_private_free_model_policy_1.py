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


@pytest.mark.parametrize(
    "policy",
    [
        {**VALID_POLICY, "unknown_field": "not allowed"},
        {**VALID_POLICY, "schema_version": 2},
        {**VALID_POLICY, "schema_version": True},
        {**VALID_POLICY, "allow_private_free_models": False},
        {**VALID_POLICY, "allow_private_free_models": 1},
        {**VALID_POLICY, "repository_data_classification": "internal"},
        {**VALID_POLICY, "external_model_data_use_accepted": False},
    ],
)
def test_noncanonical_policy_fails_closed(repository: Path, policy: dict[str, object]) -> None:
    """Missing, type-confused, unknown, or weaker declarations fail closed."""
    write_policy(repository, policy)
    base_sha = commit_all(repository, "add invalid policy")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "canonical" in result.stderr.casefold()


def test_valid_policy_on_base_and_unchanged_head_is_eligible(repository: Path) -> None:
    """A reviewed base policy enables free models for a later code-only PR."""
    write_policy(repository)
    base_sha = commit_all(repository, "add policy")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "eligible" in result.stdout.casefold()
    assert POLICY_PATH.as_posix() in result.stdout


def test_malformed_json_policy_fails_closed(repository: Path) -> None:
    """Syntactically invalid JSON is an expected ineligible policy."""
    path = repository / POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    base_sha = commit_all(repository, "malformed policy")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "valid JSON" in result.stderr


@pytest.mark.parametrize(
    ("raw_tree", "error_fragment"),
    [
        (
            b"100644 blob " + b"0" * 40 + b"\t.github/opencode-private-free-models.json",
            "unterminated",
        ),
        (
            b"100644 blob " + b"0" * 40 + b"\t.github/opencode-private-free-models.json\x00\x00",
            "more than one",
        ),
    ],
)
def test_policy_tree_requires_exact_single_nul_terminated_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_tree: bytes,
    error_fragment: str,
) -> None:
    """Truncated or extra-empty ``ls-tree -z`` records fail closed before parsing."""
    monkeypatch.setattr(
        POLICY_MODULE,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, raw_tree, b""),
    )

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match=error_fragment):
        POLICY_MODULE.policy_blob_entry(tmp_path, "0" * 40)


def test_read_policy_blob_rejects_invalid_size(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Non-numeric object sizes cannot bypass the byte bound."""
    monkeypatch.setattr(
        POLICY_MODULE,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, b"invalid\n", b""),
    )
    entry = POLICY_MODULE.GitBlobEntry("100644", "blob", "0" * 40, POLICY_PATH.as_posix())

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="blob size"):
        POLICY_MODULE.read_policy_blob(tmp_path, entry)


def test_main_internal_error_can_remain_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The wrapper receives status 2 without leaking local error details."""

    def fail_evaluation(*_args: object, **_kwargs: object) -> None:
        raise POLICY_MODULE.PolicyEvaluationError("private detail")

    monkeypatch.setattr(POLICY_MODULE, "evaluate_policy", fail_evaluation)
    result = evaluate(tmp_path, "0" * 40, "1" * 40)

    assert result.returncode == 2
    assert result.stderr == ""


def test_run_git_rejects_failed_checked_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Unexpected nonzero Git commands do not become policy denials."""
    monkeypatch.setattr(
        POLICY_MODULE.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 9, b"", b"failure"),
    )

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="failed"):
        POLICY_MODULE.run_git(tmp_path, "status")


def test_main_success_can_remain_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Successful eligibility can be consumed only as an exit status."""
    monkeypatch.setattr(POLICY_MODULE, "evaluate_policy", lambda *_args, **_kwargs: None)
    result = evaluate(tmp_path, "0" * 40, "1" * 40)

    assert result.returncode == 0
    assert result.stdout == ""


def test_invalid_commit_sha_returns_evaluation_error(repository: Path) -> None:
    """Revision syntax cannot replace immutable full commit identifiers."""
    result = evaluate(repository, "HEAD", "0" * 40, "--explain")

    assert result.returncode == 2
    assert "40-character" in result.stderr
