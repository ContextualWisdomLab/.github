#!/usr/bin/env python3
"""Apply the one-shot independent Noema LLM review repair with TDD."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/ci/noema_review_gate.py"
TEST = ROOT / "tests/test_noema_review_gate.py"
CHANGELOG = ROOT / "CHANGELOG.md"
DOCTORING = ROOT / "docs/doctoring/noema-independent-llm-review.md"
WORKFLOW = ROOT / ".github/workflows/one-shot-noema-independent-review-repair.yml"
SELF = ROOT / "scripts/ci/one_shot_noema_independent_review_repair.py"


def run(*args: str, expected: int = 0) -> None:
    """Run one command from the repository root and enforce its exit code."""
    completed = subprocess.run(args, cwd=ROOT, check=False)
    if completed.returncode != expected:
        raise SystemExit(
            f"command {args!r} returned {completed.returncode}; expected {expected}"
        )


def replace_once(source: str, old: str, new: str, label: str) -> str:
    """Replace exactly one reviewed source fragment."""
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label} fragment drifted: found {count}")
    return source.replace(old, new, 1)


def add_regression() -> None:
    """Append the direct independent-review regression before implementation."""
    source = TEST.read_text(encoding="utf-8")
    marker = "def test_noema_reviews_independently_of_opencode_and_ci_state("
    if marker in source:
        return
    source += r'''


def test_noema_reviews_independently_of_opencode_and_ci_state(monkeypatch):
    """Noema must invoke its LLM without waiting for another reviewer or CI."""
    pr = make_pr(
        reviews={"nodes": [review("CHANGES_REQUESTED", login="human")]},
        reviewThreads={
            "nodes": [{"isResolved": False, "isOutdated": False}]
        },
        statusCheckRollup={
            "contexts": {
                "nodes": [
                    {
                        "__typename": "StatusContext",
                        "context": "ci",
                        "state": "FAILURE",
                    }
                ]
            }
        },
    )
    events = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(
        noema,
        "build_review_context",
        lambda repo, number, current: "context",
    )
    monkeypatch.setattr(
        noema,
        "call_llm",
        lambda *args, **kwargs: events.append("llm")
        or {"decision": "comment", "summary": "independent", "findings": []},
    )
    monkeypatch.setattr(
        noema,
        "submit_review",
        lambda *args, **kwargs: events.append("review"),
    )

    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert events == ["llm", "review"]
'''
    TEST.write_text(source, encoding="utf-8")


def observe_red() -> None:
    """Prove the current chained reviewer behavior fails the new contract."""
    run(
        "python",
        "-m",
        "pytest",
        "tests/test_noema_review_gate.py",
        "-q",
        "-k",
        "reviews_independently_of_opencode_and_ci_state",
        expected=1,
    )


def implement() -> None:
    """Remove sequencing gates while preserving identity and idempotency gates."""
    source = GATE.read_text(encoding="utf-8")
    old = '''    if not current_primary_approval(pr):
        print("Current head does not have a primary OpenCode approval; Noema review skipped.")
        return 0
    if has_current_changes_requested(pr):
        print("Current head has requested changes; Noema review skipped.")
        return 0
    if has_unresolved_threads(pr):
        print("PR has unresolved review threads; Noema review skipped.")
        return 0
    blockers = blocking_checks(pr)
    if blockers:
        print("Blocking checks remain; Noema review skipped:")
        for blocker in blockers:
            print(f"- {blocker}")
        return 0
'''
    source = replace_once(source, old, "", "Noema sequencing gate")
    source = source.replace(
        '"""Inspect PR state and submit Noema\'s LLM review when gates are clean."""',
        '"""Independently inspect the exact PR head and submit Noema\'s LLM verdict."""',
        1,
    )
    GATE.write_text(source, encoding="utf-8")

    tests = TEST.read_text(encoding="utf-8")
    old_cases = '''    cases = [
        (make_pr(), "noema"),
        (make_pr(isDraft=True), "noema"),
        (make_pr(reviews={"nodes": [review(login="noema", body="<!-- noema-review-gate head_sha=head -->")]}), "noema"),
        (make_pr(reviews={"nodes": [review("CHANGES_REQUESTED"), review(body=marker_body)]}), "noema"),
        (make_pr(reviews={"nodes": [review(body=marker_body)]}, reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]}), "noema"),
        (make_pr(reviews={"nodes": [review(body=marker_body)]}, statusCheckRollup={"contexts": {"nodes": [{"__typename": "StatusContext", "context": "ci", "state": "FAILURE"}]}}), "noema"),
        (clean_pr, "opencode-agent"),
    ]
'''
    new_cases = '''    cases = [
        (make_pr(isDraft=True), "noema"),
        (make_pr(reviews={"nodes": [review(login="noema", body="<!-- noema-review-gate head_sha=head -->")]}), "noema"),
        (clean_pr, "opencode-agent"),
    ]
'''
    tests = replace_once(tests, old_cases, new_cases, "legacy skip cases")
    TEST.write_text(tests, encoding="utf-8")


def document() -> None:
    """Record the independent reviewer decision and operational evidence."""
    changelog = CHANGELOG.read_text(encoding="utf-8")
    bullet = (
        "- Restored `cwl-noema-review` as an independent LLM reviewer: exact-head "
        "Noema review no longer waits for OpenCode approval, successful checks, or "
        "resolved threads before invoking the configured model; merge policy remains "
        "separately fail-closed.\n"
    )
    marker = "### Fixed\n\n"
    if bullet not in changelog:
        if marker not in changelog:
            raise SystemExit("CHANGELOG Fixed section missing")
        CHANGELOG.write_text(
            changelog.replace(marker, marker + bullet, 1), encoding="utf-8"
        )
    DOCTORING.write_text(
        """# Independent Noema LLM review

## Decision

`cwl-noema-review` is an independent reviewer, not a post-OpenCode approval
step. It may inspect and publish a review for a non-draft exact head regardless
of another reviewer's state, check conclusions, or unresolved discussion.
Branch protection, required checks, review-thread resolution, and merge
schedulers remain authoritative for merge eligibility.

## Root cause

Commit `ea79ee97678421c4f3770c21eef1dc2eeea9ce51` added the OpenCode-to-Noema
handoff and also made `noema_review_gate.py` require a primary OpenCode approval,
zero unresolved threads, and zero failed or running checks before `call_llm()`.
Production run `31589096336` therefore completed successfully while logging
`Current head does not have a primary OpenCode approval; Noema review skipped.`
The configured LLM was never called.

## Safety boundary

The change does not weaken exact-head binding, draft exclusion, reviewer
identity separation, duplicate exact-head Noema review suppression, credential
selection, endpoint validation, diff bounds, secret scrubbing, or GitHub merge
rules. A Noema review is evidence from one independent model; it is not proof
that tests pass or permission to merge.

## Verification

The regression proves the LLM and review publisher run despite a missing
OpenCode approval, a current changes-requested review, an unresolved thread,
and a failed check. Existing draft, duplicate-review, and primary-actor skip
contracts remain. Python 3.14 focused and full suites, statement and branch
coverage, docstrings, compileability, and clean-tree checks are required before
publication.
""",
        encoding="utf-8",
    )


def verify() -> None:
    """Run focused and repository-wide quality evidence."""
    run("python", "-m", "coverage", "erase")
    run(
        "python",
        "-m",
        "coverage",
        "run",
        "--branch",
        "-m",
        "pytest",
        "tests/test_noema_review_gate.py",
        "-q",
    )
    run(
        "python",
        "-m",
        "coverage",
        "report",
        "--include=scripts/ci/noema_review_gate.py",
        "--show-missing",
        "--fail-under=100",
    )
    run(
        "python",
        "-m",
        "interrogate",
        "--fail-under=100",
        "scripts/ci/noema_review_gate.py",
    )
    run(
        "python",
        "-m",
        "compileall",
        "-q",
        "scripts/ci/noema_review_gate.py",
        "tests/test_noema_review_gate.py",
    )
    run("python", "-m", "pytest", "-q")
    run("git", "diff", "--check")


def publish() -> None:
    """Remove transient files, commit the verified diff, and push it."""
    WORKFLOW.unlink()
    SELF.unlink()
    run("git", "config", "user.name", "github-actions[bot]")
    run(
        "git",
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )
    run("git", "add", "-A")
    run("git", "commit", "-m", "fix(review): restore independent Noema LLM review")
    run("git", "push", "origin", "HEAD:fix/noema-independent-llm-review")


def main() -> None:
    """Execute RED, implementation, documentation, GREEN, and publication."""
    add_regression()
    observe_red()
    implement()
    document()
    verify()
    publish()


if __name__ == "__main__":
    main()
