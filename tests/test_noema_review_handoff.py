import json
from subprocess import CompletedProcess

import pytest

from scripts.ci import noema_review_handoff as handoff


HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def opencode_review(head: str = HEAD) -> dict:
    """Build a minimal OpenCode approval passed to the injected checker."""
    return {
        "id": 7,
        "state": "APPROVED",
        "commit_id": head,
        "user": {"login": "opencode-agent[bot]"},
        "body": f"- Result: APPROVE\n- Head SHA: `{head}`",
    }


def noema_review(state: str = "APPROVED", head: str = HEAD) -> dict:
    return {
        "id": 8,
        "state": state,
        "commit_id": head,
        "user": {"login": "cwl-noema-review[bot]"},
        "body": (
            f"- Head SHA: `{head}`\n"
            f"<!-- noema-review-gate head_sha={head} decision={state.lower()} -->"
        ),
    }


class FakeGitHub:
    def __init__(
        self,
        review_pages: list[list[dict]],
        *,
        heads: list[str] | None = None,
    ) -> None:
        self.review_pages = list(review_pages)
        self.heads = list(heads or [HEAD])
        self.dispatch_payloads: list[dict] = []

    def __call__(self, args, stdin=None):
        path = next((value for value in args if value.startswith("repos/")), "")
        if path.endswith("/dispatches"):
            self.dispatch_payloads.append(json.loads(stdin or "{}"))
            return ""
        if path.endswith("/reviews"):
            pages = self.review_pages
            if len(self.review_pages) > 1:
                pages = [self.review_pages.pop(0)]
            return json.dumps(pages)
        if "/pulls/" in path:
            head = self.heads[0]
            if len(self.heads) > 1:
                head = self.heads.pop(0)
            return head
        raise AssertionError(f"unexpected gh args: {args!r}")


def test_existing_noema_approval_avoids_duplicate_dispatch(capsys):
    fake = FakeGitHub([[opencode_review(), noema_review()]])

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=2,
        interval_seconds=0,
        runner=fake,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    assert result == 0
    assert fake.dispatch_payloads == []
    assert "already published APPROVED" in capsys.readouterr().err


def test_missing_primary_approval_never_dispatches(capsys):
    fake = FakeGitHub([[]])

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=2,
        interval_seconds=0,
        runner=fake,
        approval_checker=lambda *_args, **_kwargs: False,
    )

    assert result == 1
    assert fake.dispatch_payloads == []
    assert "no reusable OpenCode App" in capsys.readouterr().err


def test_dispatches_exact_head_and_waits_for_noema_approval(capsys):
    fake = FakeGitHub(
        [
            [opencode_review()],
            [opencode_review()],
            [opencode_review(), noema_review()],
        ]
    )

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=3,
        interval_seconds=0,
        runner=fake,
        sleeper=lambda _: None,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    assert result == 0
    assert fake.dispatch_payloads == [
        {
            "event_type": "noema-review",
            "client_payload": {
                "target_repository": "ContextualWisdomLab/example",
                "pr_number": 7,
                "pr_head_sha": HEAD,
            },
        }
    ]
    assert "after poll 2/3" in capsys.readouterr().err


def test_noema_changes_requested_is_terminal(capsys):
    fake = FakeGitHub(
        [
            [opencode_review()],
            [opencode_review(), noema_review("CHANGES_REQUESTED")],
        ]
    )

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=2,
        interval_seconds=0,
        runner=fake,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    assert result == 1
    assert "CHANGES_REQUESTED" in capsys.readouterr().err


def test_head_change_stops_polling(capsys):
    fake = FakeGitHub(
        [[opencode_review()], [opencode_review()]],
        heads=[HEAD, OTHER_HEAD],
    )

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=2,
        interval_seconds=0,
        runner=fake,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    assert result == 2
    assert "head changed" in capsys.readouterr().err


def test_run_gh_redacts_credentials_from_failures(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return CompletedProcess(
            args=["gh", "api"],
            returncode=1,
            stdout="",
            stderr="authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456",
        )

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as error:
        handoff.run_gh(["api", "repos/ContextualWisdomLab/example"])

    assert "ghp_" not in str(error.value)
    assert "[REDACTED]" in str(error.value)
