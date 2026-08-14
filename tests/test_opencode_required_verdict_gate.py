"""Fail-closed required OpenCode check when no current-head verdict exists."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_dispatch_status as dispatch_status


def _review(*, login: str, state: str, commit_id: str) -> dict[str, object]:
    """Return one GitHub Reviews API object."""
    return {"user": {"login": login}, "state": state, "commit_id": commit_id}


def test_current_head_opencode_verdict_reads_latest_matching_state() -> None:
    head = "a" * 40
    assert (
        dispatch_status.current_head_opencode_verdict(
            [
                _review(login="opencode-agent[bot]", state="APPROVED", commit_id=head),
                _review(
                    login="opencode-agent[bot]",
                    state="CHANGES_REQUESTED",
                    commit_id=head,
                ),
            ],
            head,
        )
        == "CHANGES_REQUESTED"
    )
    assert (
        dispatch_status.current_head_opencode_verdict(
            [_review(login="opencode-agent", state="APPROVED", commit_id=head)],
            head,
        )
        == "APPROVED"
    )


def test_current_head_opencode_verdict_ignores_other_actors_and_heads() -> None:
    head = "a" * 40
    assert (
        dispatch_status.current_head_opencode_verdict(
            [
                _review(login="coderabbitai[bot]", state="APPROVED", commit_id=head),
                _review(login="opencode-agent[bot]", state="APPROVED", commit_id="b" * 40),
                _review(login="opencode-agent[bot]", state="COMMENTED", commit_id=head),
            ],
            head,
        )
        is None
    )
    assert dispatch_status.current_head_opencode_verdict([], "") is None


def test_decide_required_verdict_check_fails_closed_without_verdict() -> None:
    head = "a" * 40
    decision = dispatch_status.decide_required_verdict_check(
        expected_head=head,
        pull_request={"head": {"sha": head}},
        reviews=[],
    )
    assert decision["state"] == "failure"
    assert "This required check is not a review" in decision["description"]
    stale = dispatch_status.decide_required_verdict_check(
        expected_head=head,
        pull_request={"head": {"sha": "c" * 40}},
        reviews=[_review(login="opencode-agent[bot]", state="APPROVED", commit_id=head)],
    )
    assert stale["state"] == "failure"
    approved = dispatch_status.decide_required_verdict_check(
        expected_head=head,
        pull_request={"head": {"sha": head}},
        reviews=[_review(login="opencode-agent[bot]", state="APPROVED", commit_id=head)],
    )
    assert approved == {
        "state": "success",
        "description": "Current-head OpenCode verdict: APPROVED.",
    }


def test_required_verdict_cli_exits_one_without_verdict(tmp_path: Path) -> None:
    head = "a" * 40
    pr_file = tmp_path / "pr.json"
    reviews_file = tmp_path / "reviews.json"
    pr_file.write_text(json.dumps({"head": {"sha": head}}), encoding="utf-8")
    reviews_file.write_text("[]", encoding="utf-8")
    assert (
        dispatch_status.main(
            [
                "--mode",
                "required-verdict",
                "--expected-head",
                head,
                "--pull-request-file",
                str(pr_file),
                "--reviews-file",
                str(reviews_file),
            ]
        )
        == 1
    )
    reviews_file.write_text(
        json.dumps(
            [_review(login="opencode-agent[bot]", state="CHANGES_REQUESTED", commit_id=head)]
        ),
        encoding="utf-8",
    )
    assert (
        dispatch_status.main(
            [
                "--mode",
                "required-verdict",
                "--expected-head",
                head,
                "--pull-request-file",
                str(pr_file),
                "--reviews-file",
                str(reviews_file),
            ]
        )
        == 0
    )


def test_dispatch_status_cli_still_requires_model_and_coverage(tmp_path: Path) -> None:
    head = "a" * 40
    pr_file = tmp_path / "pr.json"
    reviews_file = tmp_path / "reviews.json"
    pr_file.write_text(json.dumps({"head": {"sha": head}}), encoding="utf-8")
    reviews_file.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit, match="--model-outcome"):
        dispatch_status.main(
            [
                "--expected-head",
                head,
                "--pull-request-file",
                str(pr_file),
                "--reviews-file",
                str(reviews_file),
            ]
        )
