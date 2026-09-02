#!/usr/bin/env python3
"""Reconcile PR #1669 onto protected main and repair cancellation admission bugs."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

BASE = "acbb8e7ceef6d1fc0fee67d553a622ac5d707a9b"
PR_HEAD = "a37a428b2295d3753cdfc917c4e941d82a168b7d"
MAIN_HEAD = "6ba61e7fabb8f3794970746cb0f1ddfa136aad5f"
SCHEDULER = Path("scripts/ci/pr_review_merge_scheduler.py")
TESTS = Path("tests/test_pr_review_merge_scheduler.py")
CHANGELOG = Path("CHANGELOG.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")
SELF = Path("scripts/ci/source_fix_pr1669_current_main.py")
WORKFLOW = Path(".github/workflows/source-fix-pr1669-current-main.yml")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one local command and capture UTF-8 output."""
    return subprocess.run(args, check=check, text=True, capture_output=True)


def git_show(commit: str, path: Path) -> str:
    """Read one historical UTF-8 file from the exact commit."""
    return run("git", "show", f"{commit}:{path.as_posix()}").stdout


def merge_text_file(path: Path) -> None:
    """Three-way merge PR #1669's reviewed delta into the current-main file."""
    current = path.read_text(encoding="utf-8")
    if current != git_show(MAIN_HEAD, path):
        raise RuntimeError(f"{path}: checkout is not the expected protected-main baseline")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ours = root / "ours"
        base = root / "base"
        theirs = root / "theirs"
        ours.write_text(current, encoding="utf-8")
        base.write_text(git_show(BASE, path), encoding="utf-8")
        theirs.write_text(git_show(PR_HEAD, path), encoding="utf-8")
        result = run(
            "git",
            "merge-file",
            "-p",
            "-L",
            "protected-main",
            "-L",
            "common-base",
            "-L",
            "pr1669",
            str(ours),
            str(base),
            str(theirs),
            check=False,
        )
        if result.returncode != 0 or "<<<<<<<" in result.stdout:
            raise RuntimeError(f"{path}: semantic three-way merge conflicted; refusing lossy publication")
        path.write_text(result.stdout, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Apply one exact source repair and fail closed on concurrent layout drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact source block, found {count}")
    return text.replace(old, new, 1)


def add_red_tests() -> list[str]:
    """Append isolated regressions that must fail before the final source repair."""
    marker = "def test_pr1669_cancellation_failure_remains_preserved_for_direct_run"
    text = TESTS.read_text(encoding="utf-8")
    if marker in text:
        raise RuntimeError("PR1669 cancellation-result RED tests already exist; refusing duplicate fixture")
    block = r'''


def test_pr1669_cancellation_failure_remains_preserved_for_direct_run(monkeypatch):
    """A rejected direct force-cancel must not be reported as cancelled."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(sched, "stale_pr_run_ids", lambda *_args, **_kwargs: ["97"])
    monkeypatch.setattr(sched, "_direct_pr_run_still_superseded", lambda *_args: True)
    monkeypatch.setattr(sched, "force_cancel_workflow_runs", lambda *_args: {"97": "denied"})
    assert sched.cancel_stale_pr_runs("owner/repo", make_pr(number=7), dry_run=False) == []


def test_pr1669_cancellation_failure_remains_preserved_for_opencode_run(monkeypatch):
    """A rejected review force-cancel must remain busy instead of admitting a duplicate."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "96")]),
    )
    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)
    monkeypatch.setattr(sched, "force_cancel_workflow_runs", lambda *_args: {"96": "denied"})
    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", make_pr(number=7), dry_run=False
    ) == []


def test_pr1669_dispatch_helper_preserves_failed_cancellation(monkeypatch):
    """Dispatch cleanup must return a failed cancellation in its preserved set."""
    ref = ("ContextualWisdomLab/.github", "96")
    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)
    monkeypatch.setattr(sched, "force_cancel_workflow_runs", lambda *_args: {"96": "denied"})
    preserved, cancelled = sched._cancel_revalidated_review_run_refs(
        "owner/repo", "OpenCode Review", make_pr(number=7), [ref]
    )
    assert preserved == [ref]
    assert cancelled == []


def test_pr1669_central_run_revalidation_uses_dispatch_credential(monkeypatch):
    """Central repository_dispatch runs are re-read with central dispatch authority."""
    calls = []
    monkeypatch.setenv("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY", "ContextualWisdomLab/.github")

    def forbidden_target_read(_path):
        raise AssertionError("target-repository credential must not read a central workflow run")

    monkeypatch.setattr(sched, "gh_api_json", forbidden_target_read)
    monkeypatch.setattr(
        sched,
        "gh_api_json_via_dispatch_token",
        lambda path: calls.append(path) or {"status": "queued"},
    )
    payload = sched._fresh_active_run_for_cancellation("ContextualWisdomLab/.github", "95")
    assert payload["status"] == "queued"
    assert calls == ["repos/ContextualWisdomLab/.github/actions/runs/95"]
'''
    TESTS.write_text(text + block, encoding="utf-8")
    return [
        "test_pr1669_cancellation_failure_remains_preserved_for_direct_run",
        "test_pr1669_cancellation_failure_remains_preserved_for_opencode_run",
        "test_pr1669_dispatch_helper_preserves_failed_cancellation",
        "test_pr1669_central_run_revalidation_uses_dispatch_credential",
    ]


def prove_red(test_names: list[str]) -> None:
    """Require each new regression to fail as exactly one ordinary pytest failure."""
    for name in test_names:
        result = run(
            "python",
            "-m",
            "pytest",
            f"{TESTS.as_posix()}::{name}",
            "-q",
            check=False,
        )
        combined = result.stdout + result.stderr
        if result.returncode != 1 or "1 failed" not in combined:
            raise RuntimeError(
                f"{name}: expected one RED assertion failure, got exit={result.returncode}\n{combined[-2000:]}"
            )


def repair_scheduler() -> None:
    """Fix credential routing and failed-cancellation admission on the merged scheduler."""
    source = SCHEDULER.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '''def _fresh_active_run_for_cancellation(run_repo: str, run_id: str) -> dict[str, Any]:\n    """Return fresh active workflow-run evidence immediately before cancellation."""\n    payload = gh_api_json(f"repos/{run_repo}/actions/runs/{run_id}")\n''',
        '''def _fresh_active_run_for_cancellation(run_repo: str, run_id: str) -> dict[str, Any]:\n    """Return fresh active workflow-run evidence with repository-correct read authority."""\n    central_repo = (os.environ.get("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY") or "").strip()\n    use_dispatch_authority = bool(\n        central_repo and run_repo == validate_github_repository(central_repo)\n    )\n    reader = gh_api_json_via_dispatch_token if use_dispatch_authority else gh_api_json\n    payload = reader(f"repos/{run_repo}/actions/runs/{run_id}")\n''',
        "central run credential routing",
    )
    source = replace_once(
        source,
        '''        force_cancel_workflow_runs(repo, [run_id])\n        return run_id\n''',
        '''        failures = force_cancel_workflow_runs(repo, [run_id]) or {}\n        return None if run_id in failures else run_id\n''',
        "direct cancellation failure preservation",
    )
    source = replace_once(
        source,
        '''        force_cancel_workflow_runs(run_repo, [run_id])\n        return run_id\n''',
        '''        failures = force_cancel_workflow_runs(run_repo, [run_id]) or {}\n        return None if run_id in failures else run_id\n''',
        "review cancellation failure preservation",
    )
    source = replace_once(
        source,
        '''        force_cancel_workflow_runs(run_repo, [run_id])\n        return "cancelled", run_ref\n''',
        '''        failures = force_cancel_workflow_runs(run_repo, [run_id]) or {}\n        return ("preserved" if run_id in failures else "cancelled"), run_ref\n''',
        "dispatch cancellation failure preservation",
    )
    SCHEDULER.write_text(source, encoding="utf-8")


def update_docs() -> None:
    """Merge durable PR evidence without overwriting the concurrent cache ADR/change."""
    current = CHANGELOG.read_text(encoding="utf-8")
    bullet = (
        "- **Fail closed before cancelling stale PR workflow runs.** Validate snapshot `headRefOid` "
        "and re-read live PR/run identity at the destructive boundary; preserve runs when cancellation "
        "is rejected, and use central dispatch credentials for central `repository_dispatch` evidence.\n"
    )
    if bullet not in current:
        anchor = "## [Unreleased]\n"
        if current.count(anchor) != 1:
            raise RuntimeError("CHANGELOG Unreleased anchor drifted")
        current = current.replace(anchor, anchor + bullet, 1)
        CHANGELOG.write_text(current, encoding="utf-8")

    main_baseline = git_show(MAIN_HEAD, BASELINE)
    base_baseline = git_show(BASE, BASELINE)
    if main_baseline != base_baseline:
        raise RuntimeError("protected main changed the product-gap baseline concurrently; manual merge required")
    baseline = git_show(PR_HEAD, BASELINE)
    note = (
        "\n**2026-09-02 exact-head follow-up.** Failed force-cancel responses remain preservation/busy "
        "authority rather than duplicate-dispatch admission, and central workflow runs are re-read with "
        "the central dispatch credential before destructive cancellation.\n"
    )
    if note.strip() not in baseline:
        baseline += note
    BASELINE.write_text(baseline, encoding="utf-8")


def main() -> None:
    """Materialize current-main reconciliation, prove RED, repair, and retire one-shot files."""
    if run("git", "rev-parse", "HEAD").stdout.strip() == MAIN_HEAD:
        raise RuntimeError("repair must execute on the PR writer branch, not protected main")
    merge_text_file(SCHEDULER)
    merge_text_file(TESTS)
    tests = add_red_tests()
    prove_red(tests)
    repair_scheduler()
    update_docs()
    SELF.unlink(missing_ok=True)
    WORKFLOW.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
