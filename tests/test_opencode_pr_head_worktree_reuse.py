"""A persistent runner checkout must tolerate a PR-head worktree whose directory vanished.

On 2026-09-29 `cwlab-s1-04` had `_work/_temp` emptied to recover disk. The
trusted `.github` checkout outlives jobs and still registered
`$RUNNER_TEMP/opencode-pr-head`, so every review failed with
"is a missing but already registered worktree" before OpenCode ran.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml"
STEP = "Materialize pull request head for OpenCode review data"


def _materialize_tail() -> str:
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["opencode-review-target"]["steps"]
    script = next(s for s in steps if s.get("name") == STEP)["run"]
    start = script.index('rm -rf "$OPENCODE_SOURCE_WORKDIR"')
    end = script.index("git worktree add --detach")
    end = script.index("\n", end)
    return "set -euo pipefail\n" + script[start:end]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def test_vanished_registered_worktree_is_recreated(tmp_path: Path) -> None:
    tmp_path = tmp_path.resolve()
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "x")
    head = _git(repo, "rev-parse", "HEAD").strip()
    worktree = tmp_path / "temp" / "opencode-pr-head"
    _git(repo, "worktree", "add", "-q", "--detach", str(worktree), head)
    # Runner temp cleanup empties `_temp` but keeps the directory itself.
    subprocess.run(["rm", "-rf", str(worktree)], check=True)

    result = subprocess.run(
        ["bash", "-c", _materialize_tail()],
        cwd=repo,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "OPENCODE_SOURCE_WORKDIR": str(worktree),
             "PR_HEAD_SHA": head},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert _git(worktree, "rev-parse", "HEAD").strip() == head
