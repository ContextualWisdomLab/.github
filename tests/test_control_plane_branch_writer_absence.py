"""Contracts that keep transient pull-request branch writers out of the control plane."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROHIBITED_FILE_PATTERNS = (
    ".github/workflows/one-shot-*.yml",
    ".github/workflows/one-shot-*.yaml",
    ".github/workflows/repair-pr*.yml",
    ".github/workflows/repair-pr*.yaml",
    "scripts/ci/apply_pr*.py",
)
PROHIBITED_DIRECTORY_PATTERNS = (
    ".github/pr*-patch",
    ".github/pr*-repair",
)


def test_transient_pull_request_branch_writers_are_absent() -> None:
    """Reject branch-local repair workflows, apply helpers, and encoded patches."""
    offending_files = sorted(
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for pattern in PROHIBITED_FILE_PATTERNS
        for path in REPOSITORY_ROOT.glob(pattern)
        if path.is_file()
    )
    offending_directories = sorted(
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for pattern in PROHIBITED_DIRECTORY_PATTERNS
        for path in REPOSITORY_ROOT.glob(pattern)
        if path.is_dir()
    )

    assert offending_files == []
    assert offending_directories == []
