"""Regression tests for post-evidence pull-request identity retry semantics."""

import importlib.util
import json
from pathlib import Path
from subprocess import CompletedProcess


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/actions_queue_health.py"
SPEC = importlib.util.spec_from_file_location("actions_queue_health_post_evidence_retry", MODULE_PATH)
assert SPEC and SPEC.loader
queue_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(queue_health)


def _pull(head_sha: str = "head") -> dict:
    """Return one complete raw open-pull-request identity fixture."""
    return {
        "number": 1,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
        "head": {"sha": head_sha},
        "updated_at": "2026-09-02T14:00:00Z",
    }


def _incomplete_pull() -> dict:
    """Return a transiently incomplete identity fixture."""
    pull_request = _pull()
    pull_request["head"] = {"sha": ""}
    return pull_request


def _runner_with_post_evidence_identity_reads(*, persistent: bool):
    """Return a runner that makes the post-evidence identity read incomplete."""
    pull_reads = 0

    def runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Serve stable queue evidence with a transient or persistent final identity gap."""
        nonlocal pull_reads
        path = args[-1]
        if path == "repos/owner/repo":
            payload: object = {"default_branch": "main"}
        elif path == "repos/owner/repo/pulls?state=open&per_page=100":
            pull_reads += 1
            if pull_reads == 3 or (persistent and pull_reads >= 3):
                payload = [_incomplete_pull()]
            else:
                payload = [_pull()]
        elif "/actions/runs?" in path:
            payload = {"total_count": 0, "workflow_runs": []}
        else:  # pragma: no cover - any new endpoint must be explicitly governed.
            raise AssertionError(f"unexpected endpoint: {path}")
        return CompletedProcess(args, 0, json.dumps(payload), "")

    return runner


def test_post_evidence_identity_read_retries_one_transient_incomplete_snapshot(monkeypatch) -> None:
    """A transient incomplete post-evidence identity read receives one bounded retry."""
    monkeypatch.setattr(queue_health.time, "sleep", lambda _: None)
    snapshot = queue_health.collect_snapshot(
        ["owner/repo"],
        runner=_runner_with_post_evidence_identity_reads(persistent=False),
        generated_at="2026-09-02T14:00:00Z",
    )
    assert snapshot["collection_errors"] == []
    assert len(snapshot["repositories"]) == 1
    assert snapshot["repositories"][0]["pull_requests"][0]["head_sha"] == "head"


def test_post_evidence_identity_read_fails_closed_after_retry_remains_incomplete(monkeypatch) -> None:
    """Persistent incomplete post-evidence identity is repository-scoped failure."""
    monkeypatch.setattr(queue_health.time, "sleep", lambda _: None)
    snapshot = queue_health.collect_snapshot(
        ["owner/repo"],
        runner=_runner_with_post_evidence_identity_reads(persistent=True),
        generated_at="2026-09-02T14:00:00Z",
    )
    assert snapshot["repositories"] == []
    assert len(snapshot["collection_errors"]) == 1
    assert snapshot["collection_errors"][0]["repository"] == "owner/repo"
    assert "pull-request identity validation failed" in snapshot["collection_errors"][0]["error"]
