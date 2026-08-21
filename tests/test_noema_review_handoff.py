import json
import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.ci import noema_review_handoff as handoff


HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def test_standalone_cli_starts_outside_repository_root(tmp_path):
    """The workflow's direct script invocation must not depend on its cwd."""
    completed = subprocess.run(
        [sys.executable, str(Path(handoff.__file__).resolve()), "--help"],
        cwd=tmp_path,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )

    assert completed.returncode == 0
    assert "noema_review_handoff.py" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr


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


def test_noema_state_ignores_reviews_for_other_heads():
    reviews = [
        noema_review("APPROVED", OTHER_HEAD),
        noema_review("COMMENTED", HEAD),
    ]

    assert handoff.noema_review_state(reviews, HEAD) == "COMMENTED"
    assert handoff.noema_review_state([reviews[0]], HEAD) is None


def test_noema_state_ignores_forged_marker_from_other_actor():
    forged = noema_review()
    forged["user"] = {"login": "untrusted-reviewer"}
    unmarked = noema_review()
    unmarked["body"] = "review without the authenticated Noema marker"

    assert handoff.noema_review_state([forged], HEAD) is None
    assert handoff.noema_review_state([unmarked], HEAD) is None


def test_stale_initial_head_never_reads_reviews_or_dispatches(capsys):
    fake = FakeGitHub([[opencode_review()]], heads=[OTHER_HEAD])

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
    assert fake.review_pages == [[opencode_review()]]
    assert fake.dispatch_payloads == []
    assert "refused stale input" in capsys.readouterr().err


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
    assert "after poll 3/3" in capsys.readouterr().err


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


def test_missing_noema_verdict_times_out_closed(capsys):
    fake = FakeGitHub([[opencode_review()]])

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=1,
        interval_seconds=0,
        runner=fake,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    assert result == 1
    assert len(fake.dispatch_payloads) == 1
    assert "did not publish an exact-head verdict after 1 polls" in capsys.readouterr().err


def test_transient_poll_failure_retries_and_reaches_noema_verdict(capsys):
    fake = FakeGitHub(
        [
            [opencode_review()],
            [opencode_review(), noema_review()],
        ]
    )
    review_calls = 0
    observed_sleeps = []

    def transient_runner(args, stdin=None):
        nonlocal review_calls
        path = next((value for value in args if value.startswith("repos/")), "")
        if path.endswith("/reviews"):
            review_calls += 1
            if review_calls == 2:
                raise RuntimeError("temporary GitHub API outage")
        return fake(args, stdin)

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=3,
        interval_seconds=2,
        runner=transient_runner,
        sleeper=observed_sleeps.append,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    assert result == 0
    assert observed_sleeps == [2, 2]
    assert "Transient GitHub API failure" in capsys.readouterr().err


def test_consecutive_initial_failures_use_bounded_exponential_backoff(capsys):
    fake = FakeGitHub([[opencode_review(), noema_review()]])
    head_calls = 0
    observed_sleeps = []

    def transient_runner(args, stdin=None):
        nonlocal head_calls
        path = next((value for value in args if value.startswith("repos/")), "")
        if "/pulls/" in path and not path.endswith("/reviews"):
            head_calls += 1
            if head_calls < 3:
                raise RuntimeError("rate limited")
        return fake(args, stdin)

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=3,
        interval_seconds=2,
        runner=transient_runner,
        sleeper=observed_sleeps.append,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    assert result == 0
    assert observed_sleeps == [2, 4]
    assert "already published APPROVED" in capsys.readouterr().err


def test_final_transient_poll_failure_exhausts_without_dispatch(capsys):
    observed_sleeps = []

    def failing_runner(_args, _stdin=None):
        raise RuntimeError(
            "authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
        )

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=2,
        interval_seconds=2,
        runner=failing_runner,
        sleeper=observed_sleeps.append,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    log = capsys.readouterr().err
    assert result == 1
    assert observed_sleeps == [2]
    assert "exhausted its bounded polls" in log
    assert "was not dispatched after 2 bounded polls" in log
    assert "ghp_" not in log
    assert "[REDACTED]" in log


def test_transient_dispatch_failure_retries_then_reaches_verdict(capsys):
    fake = FakeGitHub(
        [
            [opencode_review()],
            [opencode_review()],
            [opencode_review(), noema_review()],
        ]
    )
    dispatch_calls = 0
    observed_sleeps = []

    def transient_runner(args, stdin=None):
        nonlocal dispatch_calls
        path = next((value for value in args if value.startswith("repos/")), "")
        if path.endswith("/dispatches"):
            dispatch_calls += 1
            if dispatch_calls == 1:
                raise RuntimeError(
                    "authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
                )
        return fake(args, stdin)

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=3,
        interval_seconds=2,
        runner=transient_runner,
        sleeper=observed_sleeps.append,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    log = capsys.readouterr().err
    assert result == 0
    assert observed_sleeps == [2, 2]
    assert dispatch_calls == 2
    assert len(fake.dispatch_payloads) == 1
    assert "Transient GitHub API failure while dispatching Noema" in log
    assert "ghp_" not in log
    assert "[REDACTED]" in log


def test_final_dispatch_failure_exhausts_without_dispatch(capsys):
    fake = FakeGitHub([[opencode_review()]])

    def failing_dispatch_runner(args, stdin=None):
        path = next((value for value in args if value.startswith("repos/")), "")
        if path.endswith("/dispatches"):
            raise RuntimeError("temporary dispatch outage")
        return fake(args, stdin)

    result = handoff.run_handoff(
        "ContextualWisdomLab/example",
        7,
        HEAD,
        attempts=1,
        interval_seconds=0,
        runner=failing_dispatch_runner,
        approval_checker=lambda *_args, **_kwargs: True,
    )

    log = capsys.readouterr().err
    assert result == 1
    assert fake.dispatch_payloads == []
    assert "dispatch exhausted its bounded polls" in log
    assert "was not dispatched after 1 bounded polls" in log


def test_run_gh_returns_stdout_on_success(monkeypatch):
    observed = {}

    def fake_run(*_args, **_kwargs):
        observed.update(_kwargs)
        return CompletedProcess(
            args=["gh", "api"],
            returncode=0,
            stdout="current-head\n",
            stderr="",
        )

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    assert handoff.run_gh(["api", "repos/ContextualWisdomLab/example"]) == "current-head\n"
    assert observed["timeout"] == handoff.GH_COMMAND_TIMEOUT_SECONDS


def test_run_gh_turns_process_timeout_into_bounded_failure(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise handoff.subprocess.TimeoutExpired(["gh", "api"], 60)

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out after 60 seconds"):
        handoff.run_gh(["api", "repos/ContextualWisdomLab/example"])


def test_run_gh_redacts_credentials_from_failures(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return CompletedProcess(
            args=["gh", "api"],
            returncode=1,
            stdout="",
            stderr=(
                "authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456; "
                "api key=opaque-api-key"
            ),
        )

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as error:
        handoff.run_gh(["api", "repos/ContextualWisdomLab/example"])

    assert "ghp_" not in str(error.value)
    assert "opaque-api-key" not in str(error.value)
    assert "[REDACTED]" in str(error.value)


def test_run_gh_reports_exit_code_when_cli_has_no_output(monkeypatch):
    def fake_run(*_args, **_kwargs):
        return CompletedProcess(args=["gh", "api"], returncode=9, stdout="", stderr="")

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="exit code 9"):
        handoff.run_gh(["api", "repos/ContextualWisdomLab/example"])


def test_parse_args_accepts_valid_handoff():
    args = handoff.parse_args(
        [
            "--repo",
            "ContextualWisdomLab/example",
            "--pr-number",
            "7",
            "--head-sha",
            HEAD,
            "--attempts",
            "3",
            "--interval-seconds",
            "0.5",
        ]
    )

    assert args.repo == "ContextualWisdomLab/example"
    assert args.pr_number == 7
    assert args.head_sha == HEAD
    assert args.attempts == 3
    assert args.interval_seconds == 0.5


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("--repo", "external/example", "ContextualWisdomLab repository"),
        ("--pr-number", "0", "pr-number must be positive"),
        ("--head-sha", "short", "40-character Git SHA"),
        ("--attempts", "0", "attempts must be positive"),
        ("--interval-seconds", "-1", "interval-seconds must be non-negative"),
    ],
)
def test_parse_args_rejects_unsafe_inputs(argument, value, message, capsys):
    argv = [
        "--repo",
        "ContextualWisdomLab/example",
        "--pr-number",
        "7",
        "--head-sha",
        HEAD,
        "--attempts",
        "3",
        "--interval-seconds",
        "0",
    ]
    argv[argv.index(argument) + 1] = value

    with pytest.raises(SystemExit, match="2"):
        handoff.parse_args(argv)

    assert message in capsys.readouterr().err


def test_main_passes_validated_arguments_to_handoff(monkeypatch):
    observed = {}

    def fake_handoff(repo, number, head_sha, *, attempts, interval_seconds):
        observed.update(
            repo=repo,
            number=number,
            head_sha=head_sha,
            attempts=attempts,
            interval_seconds=interval_seconds,
        )
        return 17

    monkeypatch.setattr(handoff, "run_handoff", fake_handoff)

    result = handoff.main(
        [
            "--repo",
            "ContextualWisdomLab/example",
            "--pr-number",
            "7",
            "--head-sha",
            HEAD,
            "--attempts",
            "4",
            "--interval-seconds",
            "1.25",
        ]
    )

    assert result == 17
    assert observed == {
        "repo": "ContextualWisdomLab/example",
        "number": 7,
        "head_sha": HEAD,
        "attempts": 4,
        "interval_seconds": 1.25,
    }
