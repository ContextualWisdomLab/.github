"""Regression coverage for live draft/head validation in required OpenCode review."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_opencode_required_verdict_regression import (
    HEAD,
    fail_closed_script,
    request_review_script,
)


def _write_live_state_gh(
    bin_dir: Path,
    *,
    live_draft: bool,
    live_head: str = HEAD,
    live_state: str = "open",
    later_exit: int = 19,
    approved_receipt: bool = False,
    live_payload_override: dict[str, object] | None = None,
) -> None:
    """Serve live PR state and optionally one approved receipt helper fixture.

    ``live_payload_override`` replaces the whole live-PR JSON body outright,
    for exercising a missing/null/non-string/unexpected ``state`` field that
    the convenience ``live_draft``/``live_head``/``live_state`` parameters
    cannot express.

    Also stubs ``sleep`` to return instantly: ``fail_closed_script()``'s
    transport-failure retry path really does ``sleep "$poll_interval_seconds"``
    (60s) between attempts, and this fixture's later-call sentinel exit code
    drives that path to its 3-failure fail-closed threshold in
    ``test_stale_draft_verdict_event_does_not_exempt_live_ready_pr`` -- without
    this stub that test performs two genuine 60s sleeps (~120s real
    wall-clock time per run) instead of running fast.
    """
    payload = json.dumps(
        live_payload_override
        if live_payload_override is not None
        else {"draft": live_draft, "head": {"sha": live_head}, "state": live_state}
    )
    helper_source = """def fetch_reviews(repository, number):
    return [{\"state\": \"APPROVED\"}]


def evaluate_receipts(reviews, head_sha, *, is_draft):
    if is_draft:
        return None, \"draft\"
    return {\"state\": \"APPROVED\"}, \"approved\"
"""
    helper_b64 = base64.b64encode(helper_source.encode()).decode()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/pulls/1437\" ]]; then\n"
        f"  printf '%s' {json.dumps(payload)}\n"
        "  exit 0\n"
        "fi\n"
        + (
            "if [[ \"$*\" == api\\ repos/ContextualWisdomLab/.github/contents/scripts/ci/opencode_review_receipt_gate.py?ref=* ]]; then\n"
            f"  printf '%s' {json.dumps(helper_b64)}\n"
            "  exit 0\n"
            "fi\n"
            if approved_receipt
            else ""
        )
        + f"exit {later_exit}\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | 0o111)
    fake_sleep = bin_dir / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(fake_sleep.stat().st_mode | 0o111)


def _run_step(
    tmp_path: Path,
    script: str,
    *,
    live_draft: bool,
    live_head: str = HEAD,
    live_state: str = "open",
    event_draft: bool = True,
    action: str = "converted_to_draft",
    approved_receipt: bool = False,
    live_payload_override: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute one production step against independently controlled live state."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production step body")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_live_state_gh(
        bin_dir,
        live_draft=live_draft,
        live_head=live_head,
        live_state=live_state,
        approved_receipt=approved_receipt,
        live_payload_override=live_payload_override,
    )
    return subprocess.run(
        [bash, "-c", script],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "fake-token",
            "OIDC_AUDIENCE": "opencode-github-action",
            "OPENCODE_API_BASE_URL": "https://api.opencode.ai",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "1437",
            "HEAD_SHA": HEAD,
            "PR_ACTION": action,
            "PR_DRAFT": "true" if event_draft else "false",
            "BASE_BRANCH": "main",
            "WORKFLOW_SHA": "c" * 40,
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_stale_draft_request_event_does_not_exempt_live_ready_pr(
    tmp_path: Path,
) -> None:
    """A stale draft request snapshot continues into the ready-PR review path."""
    result = _run_step(tmp_path, request_review_script(), live_draft=False)

    assert result.returncode == 19
    assert "Event draft snapshot is stale" in result.stdout


def test_stale_draft_verdict_event_does_not_exempt_live_ready_pr(
    tmp_path: Path,
) -> None:
    """A stale draft verdict snapshot cannot publish a success for a ready PR.

    Unlike ``request_review_script()``'s single unguarded live-PR fetch, this
    step's post-draft-check Reviews API poll retries a transport failure up
    to ``max_poll_transport_failures`` times (with a stubbed, instant backoff
    "sleep" between attempts -- see ``_write_live_state_gh``) before failing
    closed with its own exit 1 and diagnostic -- so the fixture's synthetic
    unmocked-call sentinel exit code never reaches this script's own exit
    status, unlike the sibling test above. The "stale" continuation message
    is still emitted first, proving the step did not silently exempt the
    live-ready PR from verdict polling.
    """
    result = _run_step(tmp_path, fail_closed_script(), live_draft=False)

    assert result.returncode == 1
    assert "Event draft snapshot is stale" in result.stdout
    assert "Reviews API read failed during one-shot current-head verdict admission" in result.stdout


@pytest.mark.parametrize("script", (request_review_script(), fail_closed_script()))
def test_stale_ready_event_exempts_live_draft_pr(
    tmp_path: Path,
    script: str,
) -> None:
    """A delayed ready event cannot keep dispatching or polling after live draft conversion."""
    result = _run_step(
        tmp_path,
        script,
        live_draft=True,
        event_draft=False,
        action="ready_for_review",
    )

    assert result.returncode == 0, result.stderr
    assert "still a draft on the live exact head" in result.stdout


def test_stale_draft_request_reuses_live_ready_approval(tmp_path: Path) -> None:
    """Validated live-ready state must be used by the receipt gate, not stale metadata."""
    result = _run_step(
        tmp_path,
        request_review_script(),
        live_draft=False,
        event_draft=True,
        action="converted_to_draft",
        approved_receipt=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Current-head substantive OpenCode verdict already exists" in result.stdout


@pytest.mark.parametrize("script", (request_review_script(), fail_closed_script()))
def test_draft_exemption_applies_even_when_live_head_has_moved(
    tmp_path: Path,
    script: str,
) -> None:
    """A still-draft PR exempts before the head-match check ever runs.

    #1697 reordered the live-state checks so closed/draft admission is
    evaluated before the head-SHA-match check (a draft PR whose live head
    moved between the event snapshot and this step's own live re-fetch must
    not fail closed with red-X noise -- see
    ``ContextualWisdomLab/contextual-orchestrator`` PR #1000). The
    head-moved branch is therefore unreachable while still draft: this
    exercise now exempts via the draft check, not the head-match check.
    Equivalent direct coverage of the production step lives in
    ``test_opencode_required_verdict_regression.py``'s
    ``test_request_review_step_exempts_a_draft_pr_whose_live_head_has_moved``
    and ``test_fail_closed_step_exempts_a_draft_pr_whose_live_head_has_moved``.
    """
    result = _run_step(tmp_path, script, live_draft=True, live_head="b" * 40)

    assert result.returncode == 0, result.stderr
    assert "still a draft on the live exact head" in result.stdout
    assert "head moved" not in result.stdout


@pytest.mark.parametrize("script", (request_review_script(), fail_closed_script()))
def test_stale_non_closed_event_exempts_a_live_closed_pr(
    tmp_path: Path,
    script: str,
) -> None:
    """A delayed non-closed event cannot dispatch or poll against a live-closed PR.

    Devin Review on `#1568` found that `live_pr` only ever extracted `head`
    and `draft` -- a delayed `synchronize`/`ready_for_review`/etc. event
    arriving after the PR was actually closed would ignore that live closed
    state entirely and could still fetch the receipt-gate helper, exchange
    an OIDC token, dispatch a scheduler wake, or poll the Reviews API
    indefinitely. Both admission blocks now also validate live `state` and
    exit before any of that when it is `"closed"`, exactly like the
    pre-existing `PR_ACTION == "closed"` short-circuit for a genuinely
    closed *event*.
    """
    result = _run_step(
        tmp_path,
        script,
        live_draft=False,
        live_state="closed",
        event_draft=False,
        action="synchronize",
    )

    assert result.returncode == 0, result.stderr
    assert "PR is closed on the live exact head" in result.stdout


@pytest.mark.parametrize("script", (request_review_script(), fail_closed_script()))
def test_live_closed_state_takes_precedence_over_live_draft(
    tmp_path: Path,
    script: str,
) -> None:
    """A live-closed PR is reported as closed, not draft, even if also draft."""
    result = _run_step(
        tmp_path,
        script,
        live_draft=True,
        live_state="closed",
        event_draft=False,
        action="synchronize",
    )

    assert result.returncode == 0, result.stderr
    assert "PR is closed on the live exact head" in result.stdout
    assert "still a draft on the live exact head" not in result.stdout


@pytest.mark.parametrize("script", (request_review_script(), fail_closed_script()))
@pytest.mark.parametrize(
    "live_payload_override",
    (
        {"draft": False, "head": {"sha": HEAD}},
        {"draft": False, "head": {"sha": HEAD}, "state": None},
        {"draft": False, "head": {"sha": HEAD}, "state": 1},
        {"draft": False, "head": {"sha": HEAD}, "state": "merged"},
    ),
    ids=("missing", "null", "non-string", "unexpected-value"),
)
def test_live_invalid_state_fails_closed(
    tmp_path: Path,
    script: str,
    live_payload_override: dict[str, object],
) -> None:
    """A missing, null, non-string, or unrecognized live `state` fails closed.

    GitHub's own REST API only ever reports `"open"` or `"closed"`; anything
    else is treated as untrustworthy live evidence rather than assumed open
    (Devin Review on `#1568`).
    """
    result = _run_step(
        tmp_path,
        script,
        live_draft=False,
        event_draft=False,
        action="synchronize",
        live_payload_override=live_payload_override,
    )

    assert result.returncode == 1
    assert "Could not validate live pull request state" in result.stdout
