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


def test_duplicate_json_key_fails_closed(repository: Path) -> None:
    """Ambiguous duplicate keys cannot exploit parser last-value behavior."""
    path = repository / POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"schema_version":1,"schema_version":1,'
        '"allow_private_free_models":true,'
        '"repository_data_classification":"public_equivalent",'
        '"external_model_data_use_accepted":true}\n',
        encoding="utf-8",
    )
    base_sha = commit_all(repository, "add duplicate policy")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "duplicate" in result.stderr.casefold()


def test_invalid_utf8_policy_fails_closed(repository: Path) -> None:
    """The policy is deterministic UTF-8 rather than locale-dependent bytes."""
    path = repository / POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe")
    base_sha = commit_all(repository, "add invalid utf8 policy")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "utf-8" in result.stderr.casefold()


def test_oversized_policy_fails_closed(repository: Path) -> None:
    """A bounded policy cannot hide content behind an oversized document."""
    path = repository / POLICY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(" " * 5000, encoding="utf-8")
    base_sha = commit_all(repository, "add oversized policy")
    (repository / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    head_sha = commit_all(repository, "code change")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "4096" in result.stderr


def test_policy_modified_by_reviewed_head_fails_closed(repository: Path) -> None:
    """Any policy mutation takes effect only after merge on a subsequent PR."""
    write_policy(repository)
    base_sha = commit_all(repository, "add policy")
    policy = dict(VALID_POLICY)
    policy["repository_data_classification"] = "confidential"
    write_policy(repository, policy)
    head_sha = commit_all(repository, "change policy")

    result = evaluate(repository, base_sha, head_sha, "--explain")

    assert result.returncode == 1
    assert "changed" in result.stderr.casefold()


def test_policy_blob_entry_rejects_wrong_returned_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Git output must bind to the fixed governance path exactly."""
    record = b"100644 blob " + b"0" * 40 + b"\t.github/wrong.json\x00"
    monkeypatch.setattr(
        POLICY_MODULE,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, record, b""),
    )

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="different"):
        POLICY_MODULE.policy_blob_entry(tmp_path, "0" * 40)


def test_policy_blob_entry_accepts_sha256_object_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Git object-format migration does not reject a valid 64-character blob ID."""
    object_sha = b"a" * 64
    record = b"100644 blob " + object_sha + b"\t.github/opencode-private-free-models.json\x00"
    monkeypatch.setattr(
        POLICY_MODULE,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, record, b""),
    )

    entry = POLICY_MODULE.policy_blob_entry(tmp_path, "0" * 40)

    assert entry.object_sha == object_sha.decode("ascii")


def test_run_git_wraps_process_start_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """OS-level Git launch failures become bounded evaluation errors."""
    def fail_run(*_args: object, **_kwargs: object) -> object:
        raise OSError("unavailable")

    monkeypatch.setattr(POLICY_MODULE.subprocess, "run", fail_run)

    with pytest.raises(POLICY_MODULE.PolicyEvaluationError, match="could not run"):
        POLICY_MODULE.run_git(tmp_path, "status")


@pytest.mark.parametrize(
    "record",
    [
        b"100644 blob " + b"0" * 40 + b"\t.github/policy.json",
        b"invalid\x00",
        b"100644 blob " + b"0" * 40 + b"\t\xff\x00",
    ],
)
def test_invalid_ls_tree_records_are_rejected(record: bytes) -> None:
    """Malformed or non-UTF-8 tree records never select a policy blob."""
    with pytest.raises(POLICY_MODULE.PolicyEvaluationError):
        POLICY_MODULE.parse_ls_tree_entry(record)


def test_non_git_directory_fails_closed(tmp_path: Path) -> None:
    """A plain directory cannot impersonate a materialized repository."""
    result = evaluate(tmp_path, "0" * 40, "1" * 40, "--explain")

    assert result.returncode == 1
    assert "not a Git repository" in result.stderr

