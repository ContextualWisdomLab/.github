"""Shared deterministic fixtures for npm workspace resolver tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def run_git(repo: Path, *args: str) -> str:
    """Run one fixture Git command and return stripped standard output."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def write_json(path: Path, payload: object) -> None:
    """Write deterministic UTF-8 JSON for one fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def commit_all(repo: Path, message: str = "fixture") -> str:
    """Commit every fixture path and return the exact revision SHA."""
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return run_git(repo, "rev-parse", "HEAD")
