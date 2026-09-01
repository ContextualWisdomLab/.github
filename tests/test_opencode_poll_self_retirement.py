"""Regression contract for self-retiring Required OpenCode verdict polls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


WORKFLOW = Path(".github/workflows/opencode-review.yml")


def _fail_closed_step() -> str:
    """Return the production current-head verdict polling step."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]


def _poll_loop() -> str:
    """Return only the long-running Reviews API polling loop."""
    step = _fail_closed_step()
    return step.split("          while :; do\n", 1)[1].split(
        "          done\n          if [ -z \"$verdict\" ]; then\n", 1
    )[0]


def _run_poll_loop(
    tmp_path: Path,
    *,
    head_sha: str,
    live_pr: dict[str, object],
    reviews: list[dict[str, object]] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Execute the production poll body against a deterministic fake ``gh``."""
    call_log = tmp_path / "gh-calls.log"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$GH_CALL_LOG"
[ "${1:-}" = "api" ] || exit 90
shift
if [ "${1:-}" = "--paginate" ]; then
  printf '%s\\n' "$GH_REVIEWS"
else
  printf '%s\\n' "$GH_LIVE_PR"
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    script = "\n".join(
        (
            "set -euo pipefail",
            'verdict=""',
            "while :; do",
            _poll_loop(),
            "done",
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}{os.pathsep}{env.get('PATH', '')}",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "42",
            "HEAD_SHA": head_sha,
            "GH_CALL_LOG": str(call_log),
            "GH_LIVE_PR": json.dumps(live_pr),
            "GH_REVIEWS": json.dumps(reviews or []),
        }
    )
    result = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines()
    return result, calls


def test_poll_revalidates_live_pr_before_every_reviews_api_read() -> None:
    """An occupied runner must retire itself when its PR head stops being live."""
    loop = _poll_loop()
    live_lookup = (
        'live_poll_pr="$(gh api '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"'
    )
    reviews_lookup = (
        'reviews="$(gh api --paginate '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews")"'
    )

    assert live_lookup in loop
    assert 'live_poll_head="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'live_poll_draft="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'live_poll_state="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'if [ "${live_poll_head,,}" != "${HEAD_SHA,,}" ]; then' in loop
    assert "superseded Required OpenCode Review poll" in loop
    assert 'if [ "$live_poll_state" = "closed" ]; then' in loop
    assert 'if [ "$live_poll_draft" = "true" ]; then' in loop
    assert reviews_lookup in loop
    assert loop.index(live_lookup) < loop.index(reviews_lookup)


def test_poll_live_state_revalidation_fails_closed_on_malformed_evidence() -> None:
    """Missing or malformed live-state evidence cannot turn a stale poll green."""
    loop = _poll_loop()
    assert (
        'if [ -z "$live_poll_head" ] || [ -z "$live_poll_draft" ] || '
        '[ -z "$live_poll_state" ]; then' in loop
    )
    assert "Could not validate live pull request state while polling" in loop
    assert (
        'if [ "$live_poll_state" != "open" ] && '
        '[ "$live_poll_state" != "closed" ]; then' in loop
    )


def test_poll_executes_superseded_head_retirement_before_reviews_read(
    tmp_path: Path,
) -> None:
    """A moved head exits non-passing before the Reviews API is consulted."""
    head_sha = "a" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": "b" * 40}, "draft": False, "state": "open"},
    )

    assert result.returncode == 1
    assert "retiring superseded Required OpenCode Review poll" in result.stdout
    assert calls == ["api repos/ContextualWisdomLab/example/pulls/42"]


def test_poll_executes_closed_pr_retirement_without_reviews_read(tmp_path: Path) -> None:
    """A closed current-head PR releases the occupied runner successfully."""
    head_sha = "c" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "closed"},
    )

    assert result.returncode == 0
    assert "PR closed while waiting" in result.stdout
    assert calls == ["api repos/ContextualWisdomLab/example/pulls/42"]


def test_poll_executes_live_state_read_before_current_head_review_read(
    tmp_path: Path,
) -> None:
    """A live head reads PR state first and then accepts only its current review."""
    head_sha = "d" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        reviews=[
            {
                "user": {"login": "opencode-agent[bot]"},
                "commit_id": head_sha,
                "state": "APPROVED",
                "body": "Source-backed current-head semantic review.",
            }
        ],
    )

    assert result.returncode == 0, result.stderr
    assert calls == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews",
    ]


def test_self_retirement_does_not_replace_semantic_review_with_a_short_timeout() -> None:
    """Capacity hygiene must not impose an arbitrary review inference deadline."""
    target_job = WORKFLOW.read_text(encoding="utf-8").split(
        "  opencode-review-target:\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]
    assert "timeout-minutes:" not in target_job.split("    steps:\n", 1)[0]
    assert "while :; do" in target_job
    assert "sleep 30" in target_job
