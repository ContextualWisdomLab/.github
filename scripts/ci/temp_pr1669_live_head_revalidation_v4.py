#!/usr/bin/env python3
"""Finish PR #1669 repair with complete destructive-boundary coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v3.py"
SCHEDULER = ROOT / "scripts/ci/pr_review_merge_scheduler.py"
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
SELF = Path(__file__).resolve()


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace exactly one generated scheduler fragment."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one generated anchor, found {count}")
    return text.replace(old, new, 1)


def append_coverage_regressions() -> None:
    """Cover every fail-closed and genuine-supersession cancellation branch."""
    text = TESTS.read_text(encoding="utf-8")
    marker = "def test_direct_revalidation_rejects_changed_run_identity"
    if marker in text:
        raise RuntimeError("destructive-boundary coverage regressions already present")
    text += r'''


@pytest.mark.parametrize(
    "run",
    [
        {
            "event": "repository_dispatch",
            "status": "queued",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 7}],
        },
        {
            "event": "pull_request",
            "status": "queued",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 8}],
        },
    ],
)
def test_direct_revalidation_rejects_changed_run_identity(monkeypatch, run):
    """A direct cancellation candidate must still be a direct run for the target PR."""
    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: run
        if "/actions/runs/" in path
        else {"state": "open", "draft": False, "head": {"sha": "b" * 40}},
    )
    assert sched._direct_pr_run_still_superseded("owner/repo", 7, "93") is False


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"status": "completed"},
    ],
)
def test_fresh_active_run_requires_mapping_and_active_state(monkeypatch, payload):
    """Only a mapping that still reports an active run can authorize cancellation."""
    monkeypatch.setattr(sched, "gh_api_json", lambda _path: payload)
    with pytest.raises(ValueError, match="is not active"):
        sched._fresh_active_run_for_cancellation("owner/repo", "94")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"state": "open", "draft": None, "head": {"sha": "b" * 40}},
    ],
)
def test_fresh_open_pr_requires_mapping_and_explicit_ready_state(monkeypatch, payload):
    """Unresolved or non-boolean readiness never grants destructive authority."""
    monkeypatch.setattr(sched, "gh_api_json", lambda _path: payload)
    with pytest.raises(ValueError):
        sched._fresh_open_pr_for_cancellation("owner/repo", 7)


def test_review_target_rejects_untrusted_dispatch_title():
    """A central dispatch without the exact target identity has no cancellation authority."""
    with pytest.raises(ValueError, match="trusted target identity"):
        sched._review_run_target_head(
            {"event": "repository_dispatch", "display_title": "unrelated"},
            "owner/repo",
            "OpenCode Review",
            7,
        )


def test_review_target_rejects_changed_direct_pr_association():
    """A direct review run must still belong to the target pull request."""
    with pytest.raises(ValueError, match="target pull request"):
        sched._review_run_target_head(
            {
                "event": "pull_request",
                "head_sha": "a" * 40,
                "pull_requests": [{"number": 8}],
            },
            "owner/repo",
            "OpenCode Review",
            7,
        )


def test_review_target_accepts_direct_pr_identity():
    """A direct review run with the target PR exposes its validated head."""
    assert sched._review_run_target_head(
        {
            "event": "pull_request",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 7}],
        },
        "owner/repo",
        "OpenCode Review",
        7,
    ) == "a" * 40


def test_review_revalidation_allows_genuine_stale_ready_head(monkeypatch):
    """A genuinely superseded central review remains cancellable after fresh reads."""
    run = {
        "event": "repository_dispatch",
        "status": "in_progress",
        "display_title": f"Required OpenCode Review owner/repo#7@{'a' * 40}",
    }
    monkeypatch.setattr(
        sched,
        "gh_api_json",
        lambda path: run
        if "/actions/runs/" in path
        else {"state": "open", "draft": False, "head": {"sha": "b" * 40}},
    )
    assert sched._review_run_still_superseded(
        "owner/repo", "OpenCode Review", 7, "ContextualWisdomLab/.github", "95"
    ) is True


def test_cancel_single_review_candidate_preserves_revalidated_current_run(monkeypatch):
    """The single-candidate path filters a run that is no longer proven stale."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "96")]),
    )
    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: False)
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda *_args, **_kwargs: cancelled.append(_args),
    )
    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", make_pr(number=7), dry_run=False
    ) == []
    assert cancelled == []


def test_cancel_single_review_candidate_cancels_revalidated_stale_run(monkeypatch):
    """The single-candidate path still cancels a run proven stale by fresh authority."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: ([], [("ContextualWisdomLab/.github", "97")]),
    )
    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, run_ids)),
    )
    assert sched.cancel_stale_opencode_runs(
        "owner/repo", "OpenCode Review", make_pr(number=7), dry_run=False
    ) == ["97"]
    assert cancelled == [("ContextualWisdomLab/.github", ["97"])]
'''
    TESTS.write_text(text, encoding="utf-8")


def main() -> int:
    """Run v3 transformation, complete coverage, add docstrings, and remove this helper."""
    subprocess.run([sys.executable, str(V3)], cwd=ROOT, check=True)
    text = SCHEDULER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    def cancel_one(run_id: str) -> str | None:\n        if not _direct_pr_run_still_superseded(repo, number, run_id):",
        "    def cancel_one(run_id: str) -> str | None:\n        \"\"\"Revalidate and cancel one direct workflow-run candidate when still stale.\"\"\"\n        if not _direct_pr_run_still_superseded(repo, number, run_id):",
        label="direct cancellation docstring",
    )
    text = replace_once(
        text,
        "    def cancel_one(run_ref: tuple[str, str]) -> str | None:\n        run_repo, run_id = run_ref",
        "    def cancel_one(run_ref: tuple[str, str]) -> str | None:\n        \"\"\"Revalidate and cancel one review-run candidate when still stale.\"\"\"\n        run_repo, run_id = run_ref",
        label="review cancellation docstring",
    )
    SCHEDULER.write_text(text, encoding="utf-8")
    append_coverage_regressions()
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
