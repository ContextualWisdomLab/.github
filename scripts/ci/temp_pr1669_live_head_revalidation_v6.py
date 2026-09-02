#!/usr/bin/env python3
"""Finish PR #1669 with exact RED proof and cancellation-boundary coverage."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
V5_PATH = ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v5.py"
SPEC = importlib.util.spec_from_file_location("pr1669_v5", V5_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load PR1669 v5 repair module")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)

SELF = Path(__file__).resolve()
repair.TEMP_PATHS = (
    ROOT / ".github/workflows/_temp_pr1669_live_head_revalidation_repair.yml",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_repair.py",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v2.py",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v3.py",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v4.py",
    ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v5.py",
    ROOT / "tests/test_pr1669_parallel_stale_cancellation.py",
    SELF,
)

DISPATCH_REGRESSIONS = r'''


def test_pr1669_opencode_dispatch_preserves_candidate_that_is_current_after_revalidation(monkeypatch):
    """OpenCode dispatch must preserve a candidate that became the live current-head run."""
    pr = make_pr(number=7, headRefOid="b" * 40)
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "96")]),
    )
    monkeypatch.setattr(
        sched,
        "_review_run_still_superseded",
        lambda *_args: False,
        raising=False,
    )
    direct_cancellations = []
    batch_cancellations = []
    dispatches = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: direct_cancellations.append((repo, list(run_ids))),
    )
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_run_refs",
        lambda refs: batch_cancellations.append(list(refs)),
    )
    monkeypatch.setattr(
        sched,
        "validated_pr_dispatch_fields",
        lambda _pr: ("main", "c" * 40, "b" * 40),
    )
    monkeypatch.setattr(sched, "validate_git_ref", lambda value: value)
    monkeypatch.setattr(sched, "repository_dispatch_target", lambda _repo: "ContextualWisdomLab/.github")
    monkeypatch.setattr(sched, "complete_paginated_pr_contexts", lambda *_args: [])
    monkeypatch.setattr(sched, "matching_actions_run_id", lambda *_args: None)
    monkeypatch.setattr(sched, "discover_opencode_required_run_id", lambda *_args: None)
    monkeypatch.setattr(sched, "run_github_dispatch", lambda *args, **kwargs: dispatches.append((args, kwargs)))

    assert sched.dispatch_opencode_review("owner/repo", "OpenCode Review", pr, dry_run=False) == "already_running"
    assert direct_cancellations == []
    assert batch_cancellations == []
    assert dispatches == []


def test_pr1669_strix_dispatch_preserves_candidate_that_is_current_after_revalidation(monkeypatch):
    """Strix dispatch must preserve a candidate that became the live current-head run."""
    pr = make_pr(number=7, headRefOid="b" * 40)
    monkeypatch.setattr(sched, "matching_actions_job_id", lambda *_args: None)
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_review_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "97")]),
    )
    monkeypatch.setattr(
        sched,
        "_review_run_still_superseded",
        lambda *_args: False,
        raising=False,
    )
    direct_cancellations = []
    batch_cancellations = []
    dispatches = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: direct_cancellations.append((repo, list(run_ids))),
    )
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_run_refs",
        lambda refs: batch_cancellations.append(list(refs)),
    )
    monkeypatch.setattr(sched, "active_workflow_runs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(sched, "repository_dispatch_target", lambda _repo: "ContextualWisdomLab/.github")
    monkeypatch.setattr(
        sched,
        "validated_pr_dispatch_fields",
        lambda _pr: ("main", "c" * 40, "b" * 40),
    )
    monkeypatch.setattr(sched, "run_github_dispatch", lambda *args, **kwargs: dispatches.append((args, kwargs)))

    assert sched.dispatch_strix_evidence("owner/repo", "Strix Security Scan", pr, dry_run=False) == "already_running"
    assert direct_cancellations == []
    assert batch_cancellations == []
    assert dispatches == []
'''

ORIGINAL_ADD_REGRESSIONS = repair.add_regressions_and_record_red
ORIGINAL_REPAIR_SOURCE = repair.repair_source


def add_regressions_and_record_red() -> None:
    """Install regressions and prove each selected defect fails as a test, not collection/setup."""
    text = repair.TESTS.read_text(encoding="utf-8")
    marker = "def test_pr1669_malformed_snapshot_head_never_classifies_direct_run_stale"
    if marker in text:
        raise RuntimeError("PR1669 regressions already present on input head")
    repair.TESTS.write_text(text + repair.REGRESSION_TESTS + DISPATCH_REGRESSIONS, encoding="utf-8")
    red_tests = (
        "test_pr1669_malformed_snapshot_head_never_classifies_direct_run_stale",
        "test_pr1669_snapshot_race_preserves_new_current_head",
        "test_pr1669_opencode_dispatch_preserves_candidate_that_is_current_after_revalidation",
        "test_pr1669_strix_dispatch_preserves_candidate_that_is_current_after_revalidation",
    )
    for test_name in red_tests:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                f"tests/test_pr_review_merge_scheduler.py::{test_name}",
                "-q",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        if result.returncode != 1 or "1 failed" not in output:
            print(output)
            raise RuntimeError(
                f"PR1669 RED proof for {test_name} was not one ordinary failing test "
                f"(pytest exit={result.returncode})"
            )
        print(f"PR1669_RED_CONFIRMED test={test_name} pytest_exit=1")


DISPATCH_CANCELLATION_HELPER = r'''
def _cancel_revalidated_review_run_refs(
    repo: str,
    workflow: str,
    pr: dict[str, Any],
    run_refs: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Cancel only review refs still proven stale immediately before each destructive call.

    A failed/malformed live read is preservation authority, not permission to
    dispatch a duplicate review. The returned first list therefore contains
    every active candidate that could not be proven stale; callers fold those
    refs into their current/busy set. Multiple candidates retain the scheduler's
    existing bounded executor and deterministic input ordering.
    """
    if not run_refs:
        return [], []
    number = int(pr["number"])

    def cancel_one(run_ref: tuple[str, str]) -> tuple[str, tuple[str, str]]:
        """Revalidate one candidate and cancel it only while it remains stale."""
        run_repo, run_id = run_ref
        if not _review_run_still_superseded(repo, workflow, number, run_repo, run_id):
            return "preserved", run_ref
        force_cancel_workflow_runs(run_repo, [run_id])
        return "cancelled", run_ref

    if len(run_refs) == 1:
        outcomes = [cancel_one(run_refs[0])]
    else:
        max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(run_refs))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            outcomes = list(executor.map(cancel_one, run_refs))
    preserved = [run_ref for state, run_ref in outcomes if state == "preserved"]
    cancelled = [run_ref for state, run_ref in outcomes if state == "cancelled"]
    return preserved, cancelled
'''


def repair_source() -> None:
    """Apply v5 source repair and cover every direct review-dispatch cancellation path."""
    ORIGINAL_REPAIR_SOURCE()
    text = repair.SCHEDULER.read_text(encoding="utf-8")
    helper_anchor = "\ndef dispatch_opencode_review("
    if text.count(helper_anchor) != 1:
        raise RuntimeError("dispatch_opencode_review helper insertion anchor changed")
    if "def _cancel_revalidated_review_run_refs(" in text:
        raise RuntimeError("unexpected pre-existing dispatch cancellation helper")
    text = text.replace(
        helper_anchor,
        "\n" + DISPATCH_CANCELLATION_HELPER.strip() + "\n\n" + helper_anchor.lstrip("\n"),
        1,
    )
    old_opencode = '''        current_run_refs, stale_run_refs = active_opencode_run_refs(repo, workflow, pr)\n        force_cancel_workflow_run_refs(stale_run_refs)\n        if current_run_refs:\n'''
    new_opencode = '''        current_run_refs, stale_run_refs = active_opencode_run_refs(repo, workflow, pr)\n        preserved_run_refs, _cancelled_run_refs = _cancel_revalidated_review_run_refs(\n            repo, workflow, pr, stale_run_refs\n        )\n        current_run_refs = [*current_run_refs, *preserved_run_refs]\n        if current_run_refs:\n'''
    text = repair.replace_in_function(
        text,
        "dispatch_opencode_review",
        old_opencode,
        new_opencode,
    )
    old_strix = '''    current_run_refs, stale_run_refs = active_review_run_refs(\n        repo,\n        workflow,\n        pr,\n        run_title="Strix Security Scan",\n        workflow_aliases=frozenset({"Strix Security Scan"}),\n    )\n    force_cancel_workflow_run_refs(stale_run_refs)\n    if current_run_refs:\n'''
    new_strix = '''    current_run_refs, stale_run_refs = active_review_run_refs(\n        repo,\n        workflow,\n        pr,\n        run_title="Strix Security Scan",\n        workflow_aliases=frozenset({"Strix Security Scan"}),\n    )\n    preserved_run_refs, _cancelled_run_refs = _cancel_revalidated_review_run_refs(\n        repo, workflow, pr, stale_run_refs\n    )\n    current_run_refs = [*current_run_refs, *preserved_run_refs]\n    if current_run_refs:\n'''
    text = repair.replace_in_function(
        text,
        "dispatch_strix_evidence",
        old_strix,
        new_strix,
    )
    repair.SCHEDULER.write_text(text, encoding="utf-8")


def write_durable_evidence() -> None:
    """Write readable incident evidence and synchronize changelog/baseline truth."""
    repair.DOCTORING.write_text(
        """# Scheduler stale-head cancellation: fail closed at the destructive boundary

## Incident

On 2026-09-02, `ContextualWisdomLab/naruon#1528` had Strix run `33581213829`
cancelled while head `cf472cf77fb93325858f485a22e967449d7c387a` was still the pull
request's sole current head. The run-local Strix supersession job was skipped;
the shared merge scheduler remained a separate cancellation authority.

## Root cause

`stale_pr_run_ids()` and `active_review_run_refs()` converted an unresolved or
malformed `headRefOid` into non-authoritative comparison state. Their downstream
destructive paths trusted an earlier snapshot. A push between classification and
cancellation could therefore make a newly current run appear stale. The direct
OpenCode and Strix dispatch paths also cancelled their classified stale refs
without refreshing run and pull-request identity.

## Repair contract

- Snapshot heads pass the canonical 40-hex SHA validator. Missing or malformed
  heads preserve all active runs.
- Every direct and central-review cancellation candidate is re-read immediately
  before its destructive cancellation call.
- The live pull request must still be open, explicitly non-draft, and expose a
  valid head SHA.
- The candidate run must still be queued/in-progress and retain the expected
  direct PR association or trusted central dispatch target.
- A candidate that now matches the live head, or whose identity/state cannot be
  proven, is preserved and blocks duplicate dispatch rather than being cancelled.
- Genuine older-head runs remain cancellable, including the bounded parallel
  multi-candidate path.

This aligns the Python scheduler with the live-reference race contract already
used by `scripts/ci/revalidate_queue_cancellation.sh`.

## Verification

The one-shot publisher first installs isolated regressions and requires each one
to finish as exactly one ordinary pytest failure (`exit=1`, `1 failed`) before
production transformation. Collection/environment failures are not accepted as
RED evidence. Final verification runs the focused scheduler suite, complete
repository suite with 100% statement/branch coverage, 100% `scripts/ci`
docstring coverage, compileall, and diff hygiene. The publisher, workflow, and
all temporary repair artifacts delete themselves from the published successor.
""",
        encoding="utf-8",
    )
    changelog = repair.CHANGELOG.read_text(encoding="utf-8")
    bullet = (
        "- **Fail closed before cancelling stale PR workflow runs.** Validate snapshot `headRefOid` "
        "and re-read live PR/run identity immediately before destructive cancellation, including "
        "OpenCode/Strix dispatch cleanup, so a missing head or concurrent push cannot cancel the "
        "sole current-head evidence or trigger a duplicate review.\n"
    )
    if bullet not in changelog:
        if "## [Unreleased]\n" not in changelog:
            raise RuntimeError("CHANGELOG has no Unreleased heading")
        repair.CHANGELOG.write_text(
            changelog.replace("## [Unreleased]\n", "## [Unreleased]\n" + bullet, 1),
            encoding="utf-8",
        )
    baseline = repair.BASELINE.read_text(encoding="utf-8")
    marker = "## 2026-09-02 scheduler destructive-boundary stale-run repair"
    if marker not in baseline:
        repair.BASELINE.write_text(
            baseline
            + "\n\n"
            + marker
            + "\n\n"
            + "A live `ContextualWisdomLab/naruon#1528` incident proved the shared merge scheduler "
            + "could classify current evidence as stale from unresolved snapshot head authority. "
            + "The canonical repair validates snapshot SHA evidence and revalidates live PR/run "
            + "identity inside every destructive cancellation path, including direct OpenCode and "
            + "Strix dispatch cleanup. Fail-closed preservation also blocks duplicate dispatch when "
            + "fresh authority is unavailable. Exact RED proof rejects collection/environment "
            + "failures, and all one-shot publisher artifacts are removed from the final tree.\n",
            encoding="utf-8",
        )


repair.add_regressions_and_record_red = add_regressions_and_record_red
repair.repair_source = repair_source
repair.write_durable_evidence = write_durable_evidence


if __name__ == "__main__":
    raise SystemExit(repair.main())
