#!/usr/bin/env python3
"""Permit live-authoritative stale-review cleanup on open draft PRs for PR #1669."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER = ROOT / "scripts/ci/pr_review_merge_scheduler.py"
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
DOCTORING = ROOT / "docs/doctoring/scheduler-stale-headrefoid-cancellation.md"
SELF = Path(__file__).resolve()

REGRESSIONS = r'''


def test_pr1669_opencode_open_draft_old_head_remains_cancellable(monkeypatch):
    """An old OpenCode run on an open draft must not block current-head review-only dispatch."""
    old_head = "a" * 40
    live_head = "b" * 40
    run = {
        "event": "repository_dispatch",
        "status": "in_progress",
        "display_title": f"Required OpenCode Review owner/repo#7@{old_head}",
    }

    def fake_api(path):
        if "/actions/runs/" in path:
            return run
        return {"state": "open", "draft": True, "head": {"sha": live_head}}

    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    assert sched._review_run_still_superseded(
        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "96"
    ) is True


def test_pr1669_strix_open_draft_old_head_remains_cancellable(monkeypatch):
    """An old Strix run on an open draft must not block current-head review-only dispatch."""
    old_head = "a" * 40
    live_head = "b" * 40
    run = {
        "event": "repository_dispatch",
        "status": "queued",
        "display_title": f"Strix Security Scan owner/repo#7@{old_head}",
    }

    def fake_api(path):
        if "/actions/runs/" in path:
            return run
        return {"state": "open", "draft": True, "head": {"sha": live_head}}

    monkeypatch.setattr(sched, "gh_api_json", fake_api)
    assert sched._review_run_still_superseded(
        "owner/repo", "Strix Security Scan", 7, "ContextualWisdomLab/.github", "97"
    ) is True
'''

OLD_HELPER = '''def _fresh_open_pr_for_cancellation(repo: str, number: int) -> dict[str, Any]:
    """Return fresh, still-open and explicitly ready pull-request authority."""
    payload = gh_api_json(f"repos/{repo}/pulls/{number}")
    if not isinstance(payload, dict) or str(payload.get("state") or "").lower() != "open":
        raise ValueError(f"PR #{number} in {repo} is not a resolvable open pull request")
    if payload.get("draft") is not False:
        raise ValueError(f"PR #{number} in {repo} is not live ready-for-review authority")
    validate_git_sha(str(((payload.get("head") or {}).get("sha")) or ""))
    return payload
'''

NEW_HELPER = '''def _fresh_open_pr_for_cancellation(repo: str, number: int) -> dict[str, Any]:
    """Return fresh open PR authority, including explicitly identified draft state."""
    payload = gh_api_json(f"repos/{repo}/pulls/{number}")
    if not isinstance(payload, dict) or str(payload.get("state") or "").lower() != "open":
        raise ValueError(f"PR #{number} in {repo} is not a resolvable open pull request")
    if payload.get("draft") not in {True, False}:
        raise ValueError(f"PR #{number} in {repo} has no authoritative live draft state")
    validate_git_sha(str(((payload.get("head") or {}).get("sha")) or ""))
    return payload
'''


def _prove_red(test_name: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/test_pr_review_merge_scheduler.py::{test_name}", "-q"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode != 1 or "1 failed" not in output:
        print(output)
        raise RuntimeError(
            f"PR1669 draft-review RED proof for {test_name} was not exactly one ordinary failing test "
            f"(pytest exit={result.returncode})"
        )
    print(f"PR1669_DRAFT_RED_CONFIRMED test={test_name} pytest_exit=1")


def main() -> int:
    """Install RED coverage, repair live cancellation authority, and self-retire."""
    tests = TESTS.read_text(encoding="utf-8")
    marker = "def test_pr1669_opencode_open_draft_old_head_remains_cancellable"
    if marker in tests:
        raise RuntimeError("PR1669 draft-review regressions already exist on input head")
    TESTS.write_text((tests.rstrip() + REGRESSIONS).rstrip() + "\n", encoding="utf-8")

    _prove_red("test_pr1669_opencode_open_draft_old_head_remains_cancellable")
    _prove_red("test_pr1669_strix_open_draft_old_head_remains_cancellable")

    source = SCHEDULER.read_text(encoding="utf-8")
    if source.count(OLD_HELPER) != 1:
        raise RuntimeError("PR1669 fresh-open cancellation helper drifted")
    SCHEDULER.write_text(source.replace(OLD_HELPER, NEW_HELPER, 1), encoding="utf-8")

    if DOCTORING.exists():
        doc = DOCTORING.read_text(encoding="utf-8")
        old = "- The live pull request must still be open, explicitly non-draft, and expose a\n  valid head SHA."
        new = "- The live pull request must still be open, expose an explicit live draft state, and\n  expose a valid head SHA. Open drafts remain eligible for stale review-run cleanup\n  because draft review-only dispatch is supported; merge admission stays independently draft-gated."
        if doc.count(old) != 1:
            raise RuntimeError("PR1669 doctoring draft-authority contract drifted")
        DOCTORING.write_text(doc.replace(old, new, 1), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_pr_review_merge_scheduler.py::test_pr1669_opencode_open_draft_old_head_remains_cancellable",
            "tests/test_pr_review_merge_scheduler.py::test_pr1669_strix_open_draft_old_head_remains_cancellable",
            "-q",
        ],
        cwd=ROOT,
        check=True,
    )
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
