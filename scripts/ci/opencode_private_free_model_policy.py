#!/usr/bin/env python3
"""Validate a trusted base-branch opt-in for private free-model review.

The checker reads only the fixed policy path from the pull request's base commit.
It refuses to enable free-model egress when the pull request changes that path,
so an untrusted head cannot opt itself into external processing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn


POLICY_PATH = ".github/opencode-private-free-models.json"
MAX_POLICY_BYTES = 4096
COMMIT_SHA_PATTERN = re.compile(r"\A[0-9a-fA-F]{40}\Z")
OBJECT_SHA_PATTERN = re.compile(r"\A(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
EXPECTED_POLICY: dict[str, object] = {
    "schema_version": 1,
    "allow_private_free_models": True,
    "repository_data_classification": "public_equivalent",
    "external_model_data_use_accepted": True,
}


class PolicyDenied(RuntimeError):
    """Expected fail-closed outcome for a missing or ineligible policy."""


class PolicyEvaluationError(RuntimeError):
    """Unexpected local error while evaluating the trusted Git tree."""


class DuplicateJsonKey(ValueError):
    """Raised when JSON contains ambiguous duplicate object keys."""


@dataclass(frozen=True)
class GitBlobEntry:
    """One exact regular blob entry returned by ``git ls-tree``."""

    mode: str
    object_type: str
    object_sha: str
    path: str


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse bounded command-line inputs for one pull-request evaluation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--explain",
        action="store_true",
        help="emit a bounded eligibility or denial reason",
    )
    return parser.parse_args(argv)


def isolated_git_environment() -> dict[str, str]:
    """Return a Git environment that ignores user and system configuration."""
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def run_git(repo_root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    """Run a noninteractive Git command against the materialized repository."""
    command = [
        "git",
        "-c",
        f"safe.directory={repo_root}",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(repo_root),
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            env=isolated_git_environment(),
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PolicyEvaluationError("Git policy evaluation could not run") from exc
    if check and result.returncode != 0:
        raise PolicyEvaluationError("Git policy evaluation failed")
    return result


def validate_commit_sha(value: str, label: str) -> str:
    """Validate one immutable full commit SHA without accepting revision syntax."""
    if not COMMIT_SHA_PATTERN.fullmatch(value):
        raise PolicyEvaluationError(f"{label} must be a full 40-character commit SHA")
    return value.lower()


def verify_commit(repo_root: Path, commit_sha: str) -> None:
    """Require the supplied SHA to resolve to a commit in the local object store."""
    run_git(repo_root, "cat-file", "-e", f"{commit_sha}^{{commit}}")


def require_policy_unchanged(repo_root: Path, base_sha: str, head_sha: str) -> None:
    """Deny when the reviewed head adds, removes, or modifies the policy path."""
    result = run_git(
        repo_root,
        "diff",
        "--quiet",
        "--no-ext-diff",
        base_sha,
        head_sha,
        "--",
        POLICY_PATH,
        check=False,
    )
    if result.returncode == 1:
        raise PolicyDenied(
            "policy changed in the reviewed head; merge it before a later PR can opt in"
        )
    if result.returncode != 0:
        raise PolicyEvaluationError("Git could not compare the policy path")


def parse_ls_tree_entry(raw_entry: bytes) -> GitBlobEntry:
    """Parse exactly one NUL-terminated ``git ls-tree`` record."""
    if not raw_entry.endswith(b"\x00"):
        raise PolicyEvaluationError("Git returned an unterminated policy tree entry")
    record = raw_entry[:-1]
    try:
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_sha = metadata.decode("ascii").split(" ", 2)
        path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise PolicyEvaluationError("Git returned an invalid policy tree entry") from exc
    return GitBlobEntry(
        mode=mode,
        object_type=object_type,
        object_sha=object_sha,
        path=path,
    )


def policy_blob_entry(repo_root: Path, base_sha: str) -> GitBlobEntry:
    """Return the base commit's fixed policy entry after strict mode checks."""
    result = run_git(repo_root, "ls-tree", "-z", base_sha, "--", POLICY_PATH)
    if not result.stdout:
        raise PolicyDenied(f"trusted base policy is missing at {POLICY_PATH}")
    if not result.stdout.endswith(b"\x00"):
        raise PolicyEvaluationError("Git returned an unterminated policy tree entry")
    entries = result.stdout[:-1].split(b"\x00")
    if len(entries) != 1 or not entries[0]:
        raise PolicyEvaluationError("Git returned more than one policy tree entry")
    entry = parse_ls_tree_entry(entries[0] + b"\x00")
    if entry.path != POLICY_PATH:
        raise PolicyEvaluationError("Git returned a different policy path")
    if entry.mode != "100644" or entry.object_type != "blob":
        raise PolicyDenied("trusted base policy must be one regular non-executable file")
    if not OBJECT_SHA_PATTERN.fullmatch(entry.object_sha):
        raise PolicyEvaluationError("Git returned an invalid policy blob SHA")
    return entry


def read_policy_blob(repo_root: Path, entry: GitBlobEntry) -> bytes:
    """Read a bounded immutable blob directly from the trusted base tree."""
    size_result = run_git(repo_root, "cat-file", "-s", entry.object_sha)
    try:
        size = int(size_result.stdout.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise PolicyEvaluationError("Git returned an invalid policy blob size") from exc
    if size > MAX_POLICY_BYTES:
        raise PolicyDenied(f"trusted base policy exceeds {MAX_POLICY_BYTES} bytes")
    blob_result = run_git(repo_root, "cat-file", "blob", entry.object_sha)
    if len(blob_result.stdout) != size:
        raise PolicyEvaluationError("Git returned a truncated policy blob")
    return blob_result.stdout


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build a JSON object while rejecting every duplicate key."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_policy(raw_policy: bytes) -> dict[str, object]:
    """Decode strict UTF-8 JSON and require the canonical policy declaration."""
    try:
        text = raw_policy.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PolicyDenied("trusted base policy must be valid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except DuplicateJsonKey as exc:
        raise PolicyDenied(str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise PolicyDenied("trusted base policy must be valid JSON") from exc
    if not isinstance(value, dict) or value.keys() != EXPECTED_POLICY.keys():
        raise PolicyDenied("trusted base policy must exactly match the canonical declaration")
    for key, expected in EXPECTED_POLICY.items():
        actual = value[key]
        if type(actual) is not type(expected) or actual != expected:
            raise PolicyDenied(
                "trusted base policy must exactly match the canonical declaration"
            )
    return value


def evaluate_policy(repo_root: Path, base_sha: str, head_sha: str) -> None:
    """Raise unless the immutable base policy safely enables free-model egress."""
    resolved_root = repo_root.resolve(strict=True)
    if not resolved_root.is_dir() or not (resolved_root / ".git").exists():
        raise PolicyDenied("materialized source is not a Git repository")
    normalized_base = validate_commit_sha(base_sha, "base SHA")
    normalized_head = validate_commit_sha(head_sha, "head SHA")
    verify_commit(resolved_root, normalized_base)
    verify_commit(resolved_root, normalized_head)
    require_policy_unchanged(resolved_root, normalized_base, normalized_head)
    entry = policy_blob_entry(resolved_root, normalized_base)
    parse_policy(read_policy_blob(resolved_root, entry))


def deny(reason: str, explain: bool) -> NoReturn:
    """Exit with the expected ineligible status and optional bounded reason."""
    if explain:
        print(f"ineligible: {reason}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    """Run one fail-closed policy evaluation."""
    arguments = parse_arguments(argv)
    try:
        evaluate_policy(arguments.repo_root, arguments.base_sha, arguments.head_sha)
    except (FileNotFoundError, PolicyDenied) as exc:
        deny(str(exc) or "policy denied", arguments.explain)
    except PolicyEvaluationError as exc:
        if arguments.explain:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    if arguments.explain:
        print(f"eligible: trusted unchanged base policy at {POLICY_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI integration
    raise SystemExit(main())
