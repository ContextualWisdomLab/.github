"""Formal-review receipt tests, including aFIPC stale-head and kaefa stub fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_review_receipt_gate as receipt


def review(
    *,
    commit: str,
    state: str = "CHANGES_REQUESTED",
    login: str = "opencode-agent[bot]",
    body: str = "",
    review_id: int = 1,
) -> dict[str, object]:
    """Build one REST pull-request review object."""
    if not body:
        body = (
            "## Pull request overview\n\n"
            "OpenCode reviewed the current-head product diff. Coverage is a separate gate.\n\n"
            f"- Head SHA: `{commit}`\n"
        )
    return {
        "id": review_id,
        "state": state,
        "body": body,
        "user": {"login": login},
        "commit_id": commit,
    }


def test_afipc_230_stale_changes_requested_are_not_current() -> None:
    """Stale OpenCode CHANGES_REQUESTED on old aFIPC heads cannot satisfy 5eda857."""
    stale = [
        review(commit=head, review_id=index)
        for index, head in enumerate(sorted(receipt.AFIPC_230_STALE_HEADS), start=10)
    ]
    found, reason = receipt.evaluate_receipts(stale, receipt.AFIPC_230_HEAD)
    assert found is None
    assert "stale" in reason
    current = review(commit=receipt.AFIPC_230_HEAD, state="COMMENTED", review_id=99)
    found, reason = receipt.evaluate_receipts([*stale, current], receipt.AFIPC_230_HEAD)
    assert found is current
    assert "formal review" in reason


def test_kaefa_79_stub_has_no_current_head_formal_receipt() -> None:
    """A 3-second green stub without a product-file review stays fail-closed."""
    found, reason = receipt.evaluate_receipts([], receipt.KAEFA_79_HEAD)
    assert found is None
    assert "no current-head formal" in reason


def test_draft_never_accepts_bot_approve_as_receipt() -> None:
    """Draft PRs may have a COMMENT product review, never a bot APPROVE receipt."""
    approve = review(
        commit=receipt.AFIPC_230_HEAD,
        state="APPROVED",
        body=(
            "OpenCode reviewed the current-head bounded evidence and found no blocking issues.\n"
            f"- Head SHA: `{receipt.AFIPC_230_HEAD}`\n"
            "- Result: APPROVE\n"
        ),
    )
    found, reason = receipt.evaluate_receipts(
        [approve], receipt.AFIPC_230_HEAD, is_draft=True
    )
    assert found is None
    assert "never receive bot APPROVE" in reason
    comment = review(commit=receipt.AFIPC_230_HEAD, state="COMMENTED")
    found, _ = receipt.evaluate_receipts(
        [comment], receipt.AFIPC_230_HEAD, is_draft=True
    )
    assert found is comment


def test_status_comment_and_mention_payloads_are_not_receipts() -> None:
    """Issue-comment status text and @mentions cannot green the required check."""
    status = review(
        commit=receipt.AFIPC_230_HEAD,
        body="## OpenCode Review Status\n\n- Gate result: `COMMENT`\n",
    )
    ok, reason = receipt.is_formal_receipt(
        status, receipt.AFIPC_230_HEAD, is_draft=False
    )
    assert ok is False
    assert "status-only" in reason or "malformed" in reason
    mention = review(commit=receipt.AFIPC_230_HEAD, body="@opencode-agent please review")
    ok, reason = receipt.is_formal_receipt(
        mention, receipt.AFIPC_230_HEAD, is_draft=False
    )
    assert ok is False
    assert "mention" in reason
    empty = review(commit=receipt.AFIPC_230_HEAD, body="   ")
    assert receipt.is_mention_or_malformed(str(empty["body"])) is True
    mismatched_body = review(
        commit=receipt.AFIPC_230_HEAD,
        body=(
            "## Pull request overview\n\n"
            f"- Head SHA: `{next(iter(receipt.AFIPC_230_STALE_HEADS))}`\n"
        ),
    )
    assert receipt.review_matches_head(mismatched_body, receipt.AFIPC_230_HEAD) is False
    found, reason = receipt.evaluate_receipts([mismatched_body], receipt.AFIPC_230_HEAD)
    assert found is None
    assert "stale" in reason
    ok, reason = receipt.is_formal_receipt(
        mismatched_body, receipt.AFIPC_230_HEAD, is_draft=False
    )
    assert ok is False
    assert "stale" in reason


def test_receipt_helpers_cover_graphql_and_invalid_identity() -> None:
    """GraphQL-shaped reviews and missing identity fields fail closed."""
    assert receipt.review_author({}) == ""
    assert receipt.review_author({"user": "bad"}) == ""
    assert receipt.review_commit({}) == ""
    assert receipt.review_commit({"commit": "bad"}) == ""
    assert receipt.review_matches_head(review(commit=receipt.AFIPC_230_HEAD), "") is False
    graphql = {
        "id": 7,
        "state": "COMMENTED",
        "body": "## Pull request overview\nOpenCode reviewed the current-head product diff.\n",
        "author": {"login": "github-actions[bot]"},
        "commit": {"oid": receipt.AFIPC_230_HEAD},
    }
    assert receipt.review_author(graphql) == "github-actions[bot]"
    assert receipt.review_commit(graphql) == receipt.AFIPC_230_HEAD
    ok, _ = receipt.is_formal_receipt(graphql, receipt.AFIPC_230_HEAD, is_draft=False)
    assert ok is True
    found, reason = receipt.evaluate_receipts(
        [review(commit=receipt.AFIPC_230_HEAD), "skip"],
        receipt.AFIPC_230_HEAD,
    )
    assert found is not None
    human_then_formal = receipt.evaluate_receipts(
        [
            review(commit=receipt.AFIPC_230_HEAD, review_id=2),
            review(commit=receipt.AFIPC_230_HEAD, login="seonghobae", review_id=3),
        ],
        receipt.AFIPC_230_HEAD,
    )
    assert human_then_formal[0] is not None
    stale_body = review(
        commit=receipt.AFIPC_230_HEAD,
        body=(
            "## Pull request overview\n\n"
            f"- Head SHA: `{next(iter(receipt.AFIPC_230_STALE_HEADS))}`\n"
        ),
    )
    found, reason = receipt.evaluate_receipts(
        ["skip", stale_body, stale_body],
        receipt.AFIPC_230_HEAD,
    )
    assert found is None
    assert "stale" in reason
    found, reason = receipt.evaluate_receipts([], "deadbeef")
    assert found is None
    assert "40-character" in reason
    human = review(commit=receipt.AFIPC_230_HEAD, login="seonghobae")
    ok, reason = receipt.is_formal_receipt(
        human, receipt.AFIPC_230_HEAD, is_draft=False
    )
    assert ok is False
    assert "not an OpenCode publisher" in reason
    pending = review(commit=receipt.AFIPC_230_HEAD, state="PENDING")
    ok, reason = receipt.is_formal_receipt(
        pending, receipt.AFIPC_230_HEAD, is_draft=False
    )
    assert ok is False
    assert "not a formal review verdict" in reason
    missing_id = review(commit=receipt.AFIPC_230_HEAD)
    missing_id.pop("id")
    ok, reason = receipt.is_formal_receipt(
        missing_id, receipt.AFIPC_230_HEAD, is_draft=False
    )
    assert ok is False
    assert "missing pullrequestreview id" in reason


def test_receipt_cli_and_fetch(tmp_path: Path, capsys, monkeypatch) -> None:
    """CLI accepts a current-head receipt file and annotates a missing receipt."""
    path = tmp_path / "reviews.json"
    path.write_text(
        json.dumps([review(commit=receipt.AFIPC_230_HEAD, state="COMMENTED")]),
        encoding="utf-8",
    )
    assert (
        receipt.main(
            [
                "--head-sha",
                receipt.AFIPC_230_HEAD,
                "--reviews-file",
                str(path),
            ]
        )
        == 0
    )
    assert "formal OpenCode receipt" in capsys.readouterr().out

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    assert (
        receipt.main(
            ["--head-sha", receipt.KAEFA_79_HEAD, "--reviews-file", str(empty)]
        )
        == 1
    )
    assert "receipt missing" in summary.read_text(encoding="utf-8").lower() or (
        "no current-head" in capsys.readouterr().err
    )

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert receipt.main(["--head-sha", receipt.AFIPC_230_HEAD]) == 1

    def fake_run(args, **kwargs):
        assert args[0] == "gh"
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [review(commit=receipt.AFIPC_230_HEAD, state="COMMENTED")]
                ),
                "stderr": "",
            },
        )()

    monkeypatch.setattr(receipt.subprocess, "run", fake_run)
    assert (
        receipt.main(
            [
                "--repo",
                "ContextualWisdomLab/aFIPC",
                "--pr-number",
                "230",
                "--head-sha",
                receipt.AFIPC_230_HEAD,
            ]
        )
        == 0
    )

    def fake_fail(args, **kwargs):
        return type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "nope"})()

    monkeypatch.setattr(receipt.subprocess, "run", fake_fail)
    with pytest.raises(receipt.ReceiptGateError, match="lookup failed"):
        receipt.fetch_reviews("ContextualWisdomLab/aFIPC", 230)

    def fake_bad(args, **kwargs):
        return type("Completed", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    monkeypatch.setattr(receipt.subprocess, "run", fake_bad)
    with pytest.raises(receipt.ReceiptGateError, match="malformed"):
        receipt.fetch_reviews("ContextualWisdomLab/aFIPC", 230)

    bad_file = tmp_path / "obj.json"
    bad_file.write_text("{}", encoding="utf-8")
    with pytest.raises(receipt.ReceiptGateError, match="JSON array"):
        receipt.load_reviews(str(bad_file))

    def unexpected_run(args, **kwargs):
        raise AssertionError(f"gh must not be invoked with unvalidated input: {args!r}")

    monkeypatch.setattr(receipt.subprocess, "run", unexpected_run)
    with pytest.raises(receipt.ReceiptGateError, match="owner/repo"):
        receipt.fetch_reviews("../evil", 230)
    monkeypatch.setattr(
        receipt.sys,
        "stdin",
        type(
            "Stdin",
            (),
            {
                "read": lambda self: json.dumps(
                    [review(commit=receipt.AFIPC_230_HEAD, state="COMMENTED")]
                )
            },
        )(),
    )
    assert receipt.load_reviews("-")[0]["commit_id"] == receipt.AFIPC_230_HEAD
