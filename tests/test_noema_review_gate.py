import base64
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.ci import noema_review_gate as noema


def test_gitleaks_ignore_is_exactly_scoped_to_superseded_uuid_fixture():
    entries = {
        line
        for line in Path(".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    fingerprint = (
        "6657eb76f0e2cf6dab9197cfa861a1f584653aba:"
        "tests/test_noema_review_gate.py:generic-api-key:187"
    )
    assert fingerprint in entries
    assert sum("tests/test_noema_review_gate.py" in entry for entry in entries) == 1


def test_noema_concurrency_and_live_head_cleanup_preserve_current_review():
    """Pin the invariants this cancellation mechanism must hold together.

    Several Devin Review rounds landed on this same cancellation mechanism in
    one day (see the matching ``docs/product-technical-gap-baseline.md``
    entry for the full narrative), each closing a gap the previous fix left
    open:

    1. A live new-head trigger must cancel a still-running older-head run of
       the same PR (proven end to end by
       ``test_superseded_cleanup_preserves_current_and_newer_run_ids``,
       executing the real production jq selector).
    2. A delayed ``workflow_run``/``repository_dispatch`` completion for an
       OLDER head must never cancel a genuinely current run -- pinned here by
       the head-inclusive concurrency group assertions below (native
       protection, independent of this step) AND by the step-level ``if:``
       gate restricting this explicit cancellation entirely to live
       ``pull_request_target`` triggers, so a workflow_run/repository_dispatch
       execution never even reaches this step.
    3. A cancellation step whose OWN trigger was confirmed live at the start
       of the job must still never cancel a run dispatched AFTER its own
       dispatch, even though its own multi-pass scan can take long enough in
       wall-clock time for such a run to appear in the active-runs listing:
       proven by ``test_superseded_cleanup_preserves_current_and_newer_run_ids``
       (a higher run id survives) and pinned structurally here via the
       ``.id < $current`` ordering guard plus the per-cancellation live-head
       re-check.
    4. That live-head re-check is a housekeeping safeguard, not the review
       itself: a transient failure reading it must stop cleanup without
       crashing the step (and thus the whole job) -- proven by
       ``test_superseded_cleanup_survives_a_transient_live_head_lookup_failure``.
    """
    workflow = Path(".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    concurrency = workflow.split("concurrency:", 1)[1].split("permissions:", 1)[0]
    assert "github.event.client_payload.pr_head_sha" in concurrency
    assert "github.event.pull_request.head.sha" in concurrency
    assert "github.event.workflow_run.pull_requests[0].head.sha" in concurrency
    assert "github.event.workflow_run.head_sha" not in concurrency
    assert "github.event.workflow_run.conclusion == 'cancelled'" in concurrency
    assert "format('cancelled-{0}', github.run_id)" in concurrency
    assert "'actionable'" in concurrency
    assert "cancel-in-progress: ${{" in concurrency
    assert "github.event_name != 'workflow_run'" in concurrency
    assert "github.event.workflow_run.conclusion != 'cancelled'" in concurrency
    assert "Cancel superseded Noema runs after live-head validation" in workflow
    assert workflow.index("Reject a stale trigger before credential or model setup") < workflow.index(
        "Cancel superseded Noema runs after live-head validation"
    )
    cleanup = workflow.split("Cancel superseded Noema runs after live-head validation", 1)[1]
    job_header = workflow.split("\n  noema-review:", 1)[1].split("    steps:", 1)[0]
    assert "actions: write" in job_header
    # Invariant 2 (step-level half): only a live pull_request_target trigger
    # may even attempt this cancellation -- workflow_run and
    # repository_dispatch executions (which can legitimately be delayed by
    # hours) skip this step entirely and rely solely on the head-inclusive
    # concurrency group above.
    assert (
        "if: github.event_name == 'pull_request_target' && env.PR_NUMBER != ''"
        in cleanup
    )
    assert 'select(.id < $current)' in cleanup
    # The live-head re-check must be error-guarded (an `if !` command
    # substitution), never a bare assignment under set -euo pipefail -- a
    # transient failure here must stop cleanup, not crash the whole job.
    assert cleanup.count('live_head="$(gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"') == 1
    assert (
        'if ! live_head="$(gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}" --jq \'.head.sha\''
        in cleanup
    )
    assert "could not re-verify the live PR head before cancelling" in cleanup
    assert '"${live_head,,}" != "${EXPECTED_HEAD,,}"' in cleanup
    assert 'endswith("@" + $head)' in cleanup
    assert "| not)" in cleanup


def test_noema_superseded_cleanup_selects_only_other_heads_of_same_pr():
    """Execute the workflow's jq selector against current, sibling, and foreign runs.

    ``$current`` must be passed with ``--argjson`` (a number), matching the
    production invocation (``--argjson current "$CURRENT_RUN_ID"``): jq's
    type ordering ranks every number below every string, so passing it as a
    string via ``--arg`` would make the selector's directional ``.id <
    $current`` guard vacuously true for every fixture row regardless of the
    actual id values, silently proving nothing about that guard (caught by
    review on PR #1507). With the numeric type restored, the fixture's ids
    must also be realistic: GitHub Actions run ids increase monotonically
    over time, so the "current" run (the latest trigger) has the *highest*
    id here, and the superseded same-PR sibling has a lower one — the
    opposite of this fixture's original (also-wrong) ordering, under which
    the directional guard's own vacuous-true bug happened to still produce
    the expected output for an unrelated reason."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production cleanup selector")
    workflow = Path(".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    start_marker = '--arg target "$TARGET_REPOSITORY" --arg head "$EXPECTED_HEAD" \'\n'
    start = workflow.index(start_marker) + len(start_marker)
    end = workflow.index('\n                \' <<<"$runs_json"', start)
    selector = workflow[start:end]
    workflow_path = ".github/workflows/noema-review.yml"
    runs = {
        "workflow_runs": [
            {"id": 98, "path": workflow_path, "name": "Required Noema Review", "display_title": "Required Noema Review owner/repo#7@old"},
            {"id": 99, "path": workflow_path, "name": "Required Noema Review", "display_title": "Required Noema Review owner/repo#8@old"},
            {"id": 100, "path": workflow_path, "name": "Required Noema Review", "display_title": "Required Noema Review owner/repo#7@current"},
            {"id": 97, "name": "Other", "display_title": "Required Noema Review owner/repo#7@old"},
        ]
    }
    result = subprocess.run(
        [jq, "-r", "--arg", "pr", "7", "--argjson", "current", "100", "--arg", "target", "owner/repo", "--arg", "head", "current", selector],
        input=json.dumps(runs),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.splitlines() == ["98"]
    assert "github.event.workflow_run.head_sha" not in workflow
    assert "EXPECTED_HEAD:" in workflow
    assert "--expected-head \"$EXPECTED_HEAD\"" in workflow
    assert '"${live_head,,}" != "${EXPECTED_HEAD,,}"' in workflow
    assert workflow.index("Reject a stale trigger before credential or model setup") < workflow.index(
        "Select fail-closed Noema reviewer credential"
    )


def test_noema_superseded_cleanup_matches_a_sibling_run_by_pull_requests_array():
    """A sibling-repo run whose display_title never rendered is still matched.

    Devin Review, PR #1507 ("Sibling Noema runs evade cancellation"): a
    required-workflow-ruleset run materialized in a sibling repository can
    carry the bare workflow name in ``name`` and the plain PR title (not
    this workflow's rendered run-name) in ``display_title`` -- exactly the
    shape ``tests/test_opencode_required_verdict_regression.py`` documents
    for the analogous OpenCode wake selector, and confirmed live against
    real sibling-repository runs during this fix. The selector must still
    match such a run via GitHub's own ``pull_requests[]`` array and exclude
    the live head via the direct ``head_sha`` comparison, since the head is
    also never embedded in a display_title that never rendered it.
    """
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production cleanup selector")
    workflow = Path(".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    start_marker = '--arg target "$TARGET_REPOSITORY" --arg head "$EXPECTED_HEAD" \'\n'
    start = workflow.index(start_marker) + len(start_marker)
    end = workflow.index('\n                \' <<<"$runs_json"', start)
    selector = workflow[start:end]
    workflow_path = ".github/workflows/noema-review.yml"
    current_head = "b" * 40
    old_head = "a" * 40
    runs = {
        "workflow_runs": [
            {
                "id": 98,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "Fix an unrelated example bug",
                "head_sha": old_head,
                "pull_requests": [{"number": 7}],
            },
            {
                "id": 99,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "A different pull request's title",
                "head_sha": old_head,
                "pull_requests": [{"number": 8}],
            },
            {
                "id": 100,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "Same PR, current push",
                "head_sha": current_head,
                "pull_requests": [{"number": 7}],
            },
            {
                "id": 97,
                "path": ".github/workflows/strix.yml",
                "name": "Required Noema Review",
                "display_title": "Fix an unrelated example bug",
                "head_sha": old_head,
                "pull_requests": [{"number": 7}],
            },
        ]
    }
    result = subprocess.run(
        [
            jq, "-r",
            "--arg", "pr", "7",
            "--argjson", "current", "101",
            "--arg", "target", "owner/repo",
            "--arg", "head", current_head,
            selector,
        ],
        input=json.dumps(runs),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.splitlines() == ["98"]


def test_noema_close_event_cancels_historical_head_runs():
    """Close cleanup must cancel active Noema runs across prior head groups."""
    workflow = Path(".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    cleanup = workflow.split("  cancel-closed-pr-runs:", 1)[1].split(
        "  noema-review:", 1
    )[0]
    assert "actions: write" in cleanup
    assert "Cancel queued and running Noema reviews for the closed pull request" in cleanup
    assert 'select((.name // "") | startswith("Required Noema Review"))' in cleanup
    assert 'select(.path == ".github/workflows/noema-review.yml")' in cleanup
    assert "CLOSED_PR_NUMBER" in cleanup
    assert "CURRENT_RUN_ID" in cleanup
    assert "/actions/runs/${run_id}/cancel" in cleanup
    # Devin Review finding on PR #1507 (bug 1, "Sibling Noema runs evade
    # cancellation"): GitHub does not consistently render this workflow's
    # run-name for an organization-required-workflow run materialized in a
    # sibling repository, so display_title alone (an exact `.name ==`
    # filter alone, too) can never match a sibling PR's runs. Selection is
    # PR-scoped by two independent, OR'd signals: the generated
    # display_title where GitHub does render it, and GitHub's own
    # pull_requests[] array otherwise -- reliably populated here because
    # this job only ever processes same-repository, non-fork pull requests
    # (unlike the general cross-fork case elsewhere in this org's tooling,
    # where pull_requests[] is documented to come back empty). Never a bare
    # head_sha, which two different open PRs can share.
    assert ".head_sha == $head_sha" not in cleanup
    assert "--arg head_sha" not in cleanup
    assert (
        '((.display_title // "") | startswith("Required Noema Review " + '
        '$target + "#" + $pr + "@"))'
    ) in cleanup
    assert (
        'or ((.pull_requests // []) | any(.number == ($pr | tonumber)))'
    ) in cleanup
    # Devin Review finding on PR #1507 (bug 2): a single sequential sweep
    # across the five active statuses could miss a run that transitioned
    # between statuses mid-sweep. Re-scan until a pass converges, bounded.
    # actions/runs (repo-wide, status server-filtered) is kept rather than
    # an unfiltered actions/workflows/noema-review.yml/runs snapshot: that
    # workflow-file-scoped endpoint is not guaranteed to resolve for
    # sibling-repository runs, since noema-review.yml is never itself
    # committed to those repositories (it applies there only through the
    # organization's required-workflow ruleset).
    assert 'runs_url="repos/${TARGET_REPOSITORY}/actions/runs?status=${status}&per_page=100"' in cleanup
    assert "max_passes=3" in cleanup
    assert 'while [ "$pass" -le "$max_passes" ]; do' in cleanup
    assert 'if [ "$pass" -ge 2 ] && [ "$pass_matches" -eq 0 ] && [ "$found_any" -eq 0 ]; then' in cleanup


def _extract_run_block(workflow_text: str, step_name: str) -> str:
    """Extract one step's ``run: |`` body from workflow YAML by indentation.

    Matches the extraction helper already used by
    ``tests/test_opencode_workflow_shell_syntax.py`` and
    ``tests/test_strix_repository_visibility_contract.py`` for the same
    purpose: find the named step, locate its ``run: |`` block, and collect
    lines until indentation returns to (or below) the block's own level --
    which correctly stops at the end of the block even when, as here, the
    step is the last (only) one in its job and the next line at the step's
    own indentation belongs to a different job entirely.
    """
    lines = workflow_text.splitlines()
    step_index = next(
        index for index, line in enumerate(lines) if line.strip() == f"- name: {step_name}"
    )
    run_index = next(
        index
        for index in range(step_index + 1, len(lines))
        if lines[index].strip() == "run: |"
    )
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    block_lines: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block_lines.append(line[run_indent + 2 :] if len(line) >= run_indent + 2 else "")
    return "\n".join(block_lines) + "\n"


def _close_cleanup_script() -> str:
    """Extract the close-cleanup step's real bash body from the workflow."""
    workflow = Path(".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    return _extract_run_block(
        workflow, "Cancel queued and running Noema reviews for the closed pull request"
    )


def _superseded_cleanup_script() -> str:
    """Extract the live-head supersession step's real bash body."""
    workflow = Path(".github/workflows/noema-review.yml").read_text(encoding="utf-8")
    return _extract_run_block(
        workflow, "Cancel superseded Noema runs after live-head validation"
    )


def test_superseded_cleanup_preserves_current_and_newer_run_ids(tmp_path: Path) -> None:
    """Execute cleanup and cancel only the same PR's older, different-head run."""
    current_head = "b" * 40
    workflow_path = ".github/workflows/noema-review.yml"
    runs = {"workflow_runs": [
        {"id": 100, "path": workflow_path, "name": "Required Noema Review", "display_title": "Required Noema Review ContextualWisdomLab/example#7@" + "a" * 40},
        {"id": 199, "path": workflow_path, "name": "Required Noema Review", "display_title": "Required Noema Review ContextualWisdomLab/example#7@" + current_head},
        {"id": 201, "path": workflow_path, "name": "Required Noema Review", "display_title": "Required Noema Review ContextualWisdomLab/example#7@" + "c" * 40},
        {"id": 99, "path": workflow_path, "name": "Required Noema Review", "display_title": "Required Noema Review ContextualWisdomLab/example#8@" + "a" * 40},
    ]}
    fixture = tmp_path / "runs.json"
    fixture.write_text(json.dumps(runs), encoding="utf-8")
    calls = tmp_path / "calls.txt"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_CALLS"
if [[ "$*" == *"/pulls/7"* ]]; then printf '%s\n' "$EXPECTED_HEAD"; exit 0; fi
if [[ "$*" == *"actions/runs?status="* ]]; then cat "$FAKE_RUNS"; exit 0; fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [shutil.which("bash") or "/bin/bash", "-c", _superseded_cleanup_script()],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
             "TARGET_REPOSITORY": "ContextualWisdomLab/example", "PR_NUMBER": "7",
             "EXPECTED_HEAD": current_head, "CURRENT_RUN_ID": "200",
             "FAKE_RUNS": str(fixture), "FAKE_CALLS": str(calls)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "/actions/runs/100/cancel" in recorded
    assert "/actions/runs/199/cancel" not in recorded
    assert "/actions/runs/201/cancel" not in recorded
    assert "/actions/runs/99/cancel" not in recorded


def test_superseded_cleanup_survives_a_transient_live_head_lookup_failure(
    tmp_path: Path,
) -> None:
    """A transient live-head re-check failure must stop cleanup, not crash the step.

    The live-head re-check this step performs before every single
    cancellation is a housekeeping safeguard, not the review itself. Before
    this fix, `live_head="$(gh api ...)"` was an unguarded command
    substitution under `set -euo pipefail`: a transient `gh api` failure
    (rate limit, network blip) on that one call would exit the whole step
    non-zero, failing this job and blocking a perfectly valid, live-head
    Noema review over an ancillary API hiccup unrelated to the review
    itself (Devin Review finding on PR #1507). The fix treats "cannot
    verify" the same as "verified stale": stop cancelling further runs, but
    exit 0 so the job -- and the actual review later in it -- proceeds.
    """
    current_head = "b" * 40
    runs = {
        "workflow_runs": [
            {
                "id": 100,
                "path": ".github/workflows/noema-review.yml",
                "name": "Required Noema Review",
                "display_title": "Required Noema Review ContextualWisdomLab/example#7@" + "a" * 40,
            },
        ]
    }
    fixture = tmp_path / "runs.json"
    fixture.write_text(json.dumps(runs), encoding="utf-8")
    calls = tmp_path / "calls.txt"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$FAKE_CALLS"
if [[ "$*" == *"/pulls/7"* ]]; then echo "gh: transient error" >&2; exit 1; fi
if [[ "$*" == *"actions/runs?status="* ]]; then cat "$FAKE_RUNS"; exit 0; fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [shutil.which("bash") or "/bin/bash", "-c", _superseded_cleanup_script()],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
             "TARGET_REPOSITORY": "ContextualWisdomLab/example", "PR_NUMBER": "7",
             "EXPECTED_HEAD": current_head, "CURRENT_RUN_ID": "200",
             "FAKE_RUNS": str(fixture), "FAKE_CALLS": str(calls)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"a transient live-head lookup failure must not crash this step "
        f"(it would fail the whole job); stderr={result.stderr!r}"
    )
    assert "/actions/runs/100/cancel" not in calls.read_text(encoding="utf-8")
    assert "could not re-verify the live PR head" in result.stderr


def _write_fake_gh(tmp_path: Path, *, body: str) -> dict[str, str]:
    """Write a fake `gh` executable and return a PATH-prefixed env base for it."""
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
        "GH_TOKEN": "synthetic-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/example",
        "CLOSED_PR_NUMBER": "42",
        "CURRENT_RUN_ID": "999",
    }


def test_close_cleanup_selector_is_pr_scoped_not_head_sha_scoped(tmp_path: Path) -> None:
    """Real jq execution: a shared head SHA must not leak cancellation across PRs.

    Devin Review finding on PR #1507 (bug 1). Two open pull requests (#42,
    the one closing, and #43, unrelated) share one head commit -- a real,
    if uncommon, GitHub scenario (e.g. a duplicate PR opened from the same
    branch against a different target). Only PR #42's run may be cancelled;
    PR #43's run, identical except for its PR association, must survive
    untouched. This pipes representative run JSON through the workflow's
    actual jq selector rather than grep-matching the YAML text. The fake
    `gh` here answers every status query with the same fixture (status
    filtering is not what this test is about); the status-filtering
    contract is covered separately below.
    """
    shared_head = "d" * 40
    fixture = {
        "workflow_runs": [
            {
                "id": 100,
                "path": ".github/workflows/noema-review.yml",
                "name": "Required Noema Review",
                "display_title": (
                    f"Required Noema Review ContextualWisdomLab/example#42@{shared_head}"
                ),
            },
            {
                "id": 200,
                "path": ".github/workflows/noema-review.yml",
                "name": "Required Noema Review",
                "display_title": (
                    f"Required Noema Review ContextualWisdomLab/example#43@{shared_head}"
                ),
            },
        ]
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    cancel_log = tmp_path / "cancelled-run-ids.txt"
    cancel_log.write_text("", encoding="utf-8")

    env = _write_fake_gh(
        tmp_path,
        body=textwrap.dedent(
            f"""\
            if [ "$1" = api ] && [ "$2" = --paginate ]; then
              cat {shlex.quote(str(fixture_path))}
              exit 0
            elif [ "$1" = api ] && [ "$2" = --method ] && [ "$3" = POST ]; then
              run_id="$(printf '%s' "$4" | sed -E 's#.*/runs/([0-9]+)/cancel#\\1#')"
              printf '%s\\n' "$run_id" >> {shlex.quote(str(cancel_log))}
              exit 0
            fi
            echo "unexpected gh invocation: $*" >&2
            exit 1
            """
        ),
    )

    bash_executable = shutil.which("bash") or "/bin/bash"
    result = subprocess.run(  # noqa: S603
        [bash_executable, "-c", _close_cleanup_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    cancelled_ids = {
        line.strip() for line in cancel_log.read_text(encoding="utf-8").splitlines() if line.strip()
    }
    assert cancelled_ids == {"100"}, (
        f"expected only PR #42's run (100) cancelled, got {cancelled_ids}; "
        f"stderr={result.stderr}"
    )


def test_close_cleanup_survives_a_run_transitioning_between_active_statuses(
    tmp_path: Path,
) -> None:
    """Real bash execution: a run that changes status mid-sweep is still cancelled.

    Devin Review finding on PR #1507 (bug 2). A run for the closed PR is not
    yet visible under any active status on the sweep's first pass (modeling
    it being "requested" when the already-fetched "queued" list was read,
    then becoming "queued" moments later, after the loop had already moved
    past checking "queued" for that pass) and only becomes visible, under
    "queued", starting with the *second* query for that status. A single
    sequential sweep (the pre-fix behavior) would find zero matches and
    leave this run running forever; the fixed multi-pass sweep must still
    cancel it. This also exercises the status query parameter end to end
    (the fake `gh` here filters by it, unlike the test above).
    """
    fixture = {
        "workflow_runs": [
            {
                "id": 300,
                "path": ".github/workflows/noema-review.yml",
                "name": "Required Noema Review",
                "display_title": (
                    f"Required Noema Review ContextualWisdomLab/example#42@{'d' * 40}"
                ),
            }
        ]
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    cancel_log = tmp_path / "cancelled-run-ids.txt"
    cancel_log.write_text("", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    env = _write_fake_gh(
        tmp_path,
        body=textwrap.dedent(
            f"""\
            if [ "$1" = api ] && [ "$2" = --paginate ]; then
              url="$3"
              status="$(printf '%s' "$url" | sed -E 's/.*status=([a-z_]+)&.*/\\1/')"
              counter_file={shlex.quote(str(state_dir))}"/count-${{status}}"
              count=0
              [ -f "$counter_file" ] && count="$(cat "$counter_file")"
              count=$((count + 1))
              printf '%s' "$count" > "$counter_file"
              if [ "$status" = queued ] && [ "$count" -eq 2 ]; then
                cat {shlex.quote(str(fixture_path))}
              else
                echo '{{"workflow_runs": []}}'
              fi
              exit 0
            elif [ "$1" = api ] && [ "$2" = --method ] && [ "$3" = POST ]; then
              run_id="$(printf '%s' "$4" | sed -E 's#.*/runs/([0-9]+)/cancel#\\1#')"
              printf '%s\\n' "$run_id" >> {shlex.quote(str(cancel_log))}
              exit 0
            fi
            echo "unexpected gh invocation: $*" >&2
            exit 1
            """
        ),
    )

    bash_executable = shutil.which("bash") or "/bin/bash"
    result = subprocess.run(  # noqa: S603
        [bash_executable, "-c", _close_cleanup_script()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    cancelled_ids = {
        line.strip() for line in cancel_log.read_text(encoding="utf-8").splitlines() if line.strip()
    }
    assert cancelled_ids == {"300"}, (
        f"the status-transitioning run must still be cancelled; got {cancelled_ids}; "
        f"stderr={result.stderr}"
    )
    # Prove the race is real: pass 1 alone (the pre-fix, single-sweep
    # behavior) found nothing, so only the fixed multi-pass loop caught it.
    assert "pass 1/3 matched 0 run(s)" in result.stderr
    assert "pass 2/3 matched 1 run(s)" in result.stderr


def fake_secret(*parts: str) -> str:
    return "".join(parts)


def make_pr(**overrides):
    """Build a minimal pull request payload for Noema tests."""
    value = {
        "number": 7,
        "title": "Noema",
        "body": "",
        "isDraft": False,
        "headRefOid": "head",
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": []}},
    }
    value.update(overrides)
    return value


def review(state="APPROVED", commit="head", login="opencode-agent", body="Result: APPROVE"):
    """Build a minimal review node for Noema tests."""
    return {
        "state": state,
        "body": body,
        "author": {"login": login},
        "commit": {"oid": commit},
    }


def test_run_split_repo_graphql_and_fetch_pr(monkeypatch):
    assert noema.run([sys.executable, "-c", "print('ok')"]).strip() == "ok"
    with pytest.raises(TypeError):
        noema.run("echo unsafe")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        noema.run([sys.executable, "-c", "import sys; sys.exit(5)"])

    assert noema.split_repo("owner/repo") == ("owner", "repo")

def test_scrub_sensitive_data():
    assert noema.scrub_sensitive_data(None) is None
    assert noema.scrub_sensitive_data("") == ""
    assert noema.scrub_sensitive_data("ok") == "ok"
    assert noema.scrub_sensitive_data("Bearer abcdef123") == "Bearer ***"
    assert noema.scrub_sensitive_data("TOKEN xyz_987") == "TOKEN ***"
    assert noema.scrub_sensitive_data(fake_secret("github_", "pat_", "123456789")) == "***"
    assert noema.scrub_sensitive_data(fake_secret("gh", "p_", "12345")) == "***"
    assert noema.scrub_sensitive_data("sk-abc-123_456") == "***"
    assert noema.scrub_sensitive_data("xoxb-1234-5678") == "***"
    assert noema.scrub_sensitive_data("AKIA1234567890ABCDEF") == "***"
    assert noema.scrub_sensitive_data("api_key=12345") == "api_key=***"
    assert noema.scrub_sensitive_data("client_secret='abc'") == "client_secret=***"
    assert noema.scrub_sensitive_data("password: xyz") == "password: ***"


def test_scrub_sensitive_data_authorization_headers():
    assert noema.scrub_sensitive_data("Authorization: Basic dXNlcjpwYXNz") == "Authorization: Basic ***"
    assert noema.scrub_sensitive_data("Proxy-Authorization: Basic dXNlcjpwYXNz") == "Proxy-Authorization: Basic ***"
    assert noema.scrub_sensitive_data("authorization: bearer xyz") == "authorization: bearer ***"


def test_split_repo_and_graphql(monkeypatch):
    with pytest.raises(ValueError):
        noema.split_repo("owner")
    with pytest.raises(ValueError):
        noema.split_repo("/repo")

    calls = []

    def fake_run(args, stdin=None):
        calls.append((args, stdin))
        return '{"data":{"repository":{"pullRequest":{"number":7}}}}'

    monkeypatch.setattr(noema, "run", fake_run)
    assert noema.graphql("query", owner="owner", number=7)["data"]["repository"]["pullRequest"]["number"] == 7
    assert "-f" in calls[0][0]
    assert "-F" in calls[0][0]
    assert noema.fetch_pr("owner/repo", 7) == {"number": 7}

    monkeypatch.setattr(noema, "graphql", lambda *args, **kwargs: {"data": {"repository": {"pullRequest": None}}})
    with pytest.raises(RuntimeError, match="was not found"):
        noema.fetch_pr("owner/repo", 8)


def test_existing_noema_review_matches_actor_and_head():
    noema_marker = "<!-- noema-review-gate head_sha=head -->"
    assert noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="noema", body=noema_marker)]}),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="human", body=noema_marker)]}),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="noema", body="review without gate marker")]}),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="", body=noema_marker)]}),
        "",
    )
    assert not noema.existing_noema_review(make_pr(reviews={"nodes": [review("DISMISSED", login="noema")]}), "noema")
    assert not noema.existing_noema_review(make_pr(reviews={"nodes": [review(commit="old", login="noema")]}), "noema")


def test_current_actor_fetch_diff_and_json_extraction(monkeypatch):
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", "cwl-noema-review[bot]")
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", "123")
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "noema-review-github-app")
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API not needed")))
    assert noema.current_actor() == "cwl-noema-review[bot]"

    monkeypatch.delenv("NOEMA_REVIEW_ACTOR")
    monkeypatch.delenv("NOEMA_REVIEW_INSTALLATION_ID")
    monkeypatch.delenv("NOEMA_REVIEW_TOKEN_SOURCE")
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "noema\n")
    assert noema.current_actor() == "noema"
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no gh")))
    assert noema.current_actor() == ""

    def app_identity(args, **kwargs):
        if args[2] == "user":
            return ""
        return "cwl-noema-review\n"

    monkeypatch.setattr(noema, "run", app_identity)
    assert noema.current_actor() == "cwl-noema-review[bot]"

    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "x" * (noema.MAX_DIFF_CHARS + 5))
    diff, truncated = noema.fetch_diff("owner/repo", 1)
    assert truncated
    assert len(diff) == noema.MAX_DIFF_CHARS

    assert noema.extract_json_object('{"decision":"approve"}') == {"decision": "approve"}
    assert noema.extract_json_object('prefix {"decision":"comment"} suffix') == {"decision": "comment"}
    with pytest.raises(RuntimeError, match="did not contain"):
        noema.extract_json_object("not-json")


def test_extract_json_object_balances_wrapped_and_multiple_objects():
    """Decode one complete object without joining unrelated brace-bearing text."""
    verdict = {"decision": "approve", "summary": "balanced { text }"}
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            "prose {not JSON} before " + json.dumps(verdict) + " after {brace prose}"
        )
    assert noema.extract_json_object(
        json.dumps(verdict) + "\n" + json.dumps({"decision": "comment"})
    ) == verdict
    escaped = {"decision": "approve", "summary": 'escaped " { text }'}
    assert noema.extract_json_object(json.dumps(escaped)) == escaped


def test_extract_json_object_rejects_approval_after_malformed_top_level_candidate():
    """A malformed first candidate must not release a later approval verdict."""
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            '{"broken": invalid} {"decision":"approve","summary":"later"}'
        )


def test_extract_json_object_rejects_nested_recovery_from_malformed_outer_object():
    """A valid nested object must not escape its malformed outer object."""
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            'prefix {"broken": {"decision":"approve","summary":"nested"} trailing'
        )


def test_extract_json_object_rejects_nested_recovery_from_malformed_outer_array():
    """A valid nested object must not escape a malformed outer *array* either.

    Candidate discovery must track ``[``/``]`` depth alongside ``{``/``}``:
    without it, the inner object's own ``{`` is wrongly seen at depth zero
    (only brace nesting was tracked) and treated as a fresh top-level
    candidate, letting a complete inner object "recover" out of an
    unterminated outer array — the same class of bug
    ``test_extract_json_object_rejects_nested_recovery_from_malformed_outer_object``
    covers for an outer object wrapper."""
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            '[{"decision":"comment","summary":"ok","findings":[]}'
        )


@pytest.mark.parametrize("payload", ['[} {"decision":"approve"}', '{] {"decision":"approve"}'])
def test_extract_json_object_rejects_recovery_after_mismatched_delimiter(payload):
    """A mismatched closer must not release a nested verdict candidate."""
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(payload)


def test_extract_json_object_rejects_nested_recovery_via_a_mismatched_closer():
    """A stray closer of the wrong bracket type must not fake-close a wrapper.

    Candidate discovery uses a bracket-*type* stack, not a plain up/down
    counter: a ``]`` only pops an innermost ``[``, and a ``}`` only pops an
    innermost ``{``. A plain counter that treated any closer as -1 would let
    a mismatched closer (which cannot legitimately close the container it
    appears in) prematurely signal "back to depth zero," so a later nested
    recovery object's own ``{`` would wrongly be seen as a fresh top-level
    candidate (Devin review on PR #1507). Covers both mismatch directions:
    a stray ``]`` inside an unterminated ``{``, and a stray ``}`` inside an
    unterminated ``[``."""
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            '{"broken": ]{"decision":"comment","summary":"ok","findings":[]}'
        )
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            '{"broken": [}{"decision":"comment","summary":"ok","findings":[]}'
        )


def test_extract_json_object_stops_discovery_after_any_mismatched_closer():
    """A mismatched closer must poison the *rest* of discovery, not just the
    bracket group it appears in.

    Merely making a mismatched closer a stack no-op (ignored rather than
    popped) is not enough on its own: a later, otherwise-well-formed pair
    can still validly re-close the stack down to empty despite the earlier
    mismatch, so a subsequent { would again look like a fresh top-level
    candidate. ``[} ] {...}`` -- the stray } is a no-op against the open [,
    but the following ] still legitimately closes that [, and the { after
    it would wrongly look top-level again if discovery kept scanning
    (Devin review on PR #1507). No candidate must be found past the
    mismatch at all."""
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            '[} ] {"decision":"comment","summary":"ok","findings":[]}'
        )
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(
            '{] } {"decision":"comment","summary":"ok","findings":[]}'
        )


def test_json_nesting_within_bound_does_not_undercount_past_a_mismatched_closer():
    """A mismatched closer must not make the bound-check think a candidate
    closed early, undercounting nesting that raw_decode would still walk
    through when this candidate is actually decoded. Covers both mismatch
    directions: a stray ``]`` inside an unterminated ``{``, and a stray
    ``}`` inside an unterminated ``[``."""
    deep = "[" * 5
    stray_bracket = '{"a": ]' + deep + "0" + "]" * 5 + "}"
    assert noema._json_nesting_within_bound(stray_bracket, 0, 100) is True
    assert noema._json_nesting_within_bound(stray_bracket, 0, 3) is False

    stray_brace = '{"a": [}0]}'
    assert noema._json_nesting_within_bound(stray_brace, 0, 100) is True


def test_extract_json_object_fails_closed_on_a_real_deep_payload():
    """A genuinely deep JSON payload must fail closed on this job's own runtime.

    Deliberately real input, not a monkeypatch: ``json.JSONDecoder.raw_decode``'s
    own recursion behavior is not a stable contract across Python versions —
    a real ``depth = max(20_000, sys.getrecursionlimit() * 2)`` nested array
    raises ``RecursionError`` on Python 3.11-3.13 but decodes successfully
    (no exception) on the Python 3.14 runner this job actually runs on (see
    ``extract_json_object``'s docstring for the verifying CI evidence). This
    test proves the *explicit* ``MAX_JSON_NESTING_DEPTH`` bound rejects real
    excessive nesting regardless of which behavior the running interpreter
    happens to have, rather than proving only that a raised RecursionError is
    handled (see the sibling ``..._on_a_recursion_error_from_the_decoder``
    test below for that narrower, supplemental contract)."""
    depth = max(20_000, sys.getrecursionlimit() * 2)
    nested = '{"decision":' + ("[" * depth) + "0" + ("]" * depth) + "}"
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(nested)


def test_extract_json_object_accepts_nesting_within_the_bound():
    """A legitimately nested verdict (well under the depth bound) still decodes."""
    nested = '{"decision":' + ("[" * 10) + "0" + ("]" * 10) + "}"
    assert noema.extract_json_object(nested) == {"decision": json.loads("[" * 10 + "0" + "]" * 10)}


def test_json_nesting_within_bound_handles_escaped_quotes_inside_strings():
    """An escaped quote inside a string must not be mistaken for the string's
    terminator: unrelated bracket characters that happen to follow inside the
    same string value must not be miscounted as real nesting depth, or a
    shallow, valid verdict would be wrongly rejected as excessively nested."""
    payload = '{"decision": "abc\\"' + ("[" * 200) + 'def"}'
    assert json.loads(payload) == {"decision": 'abc"' + ("[" * 200) + "def"}
    assert noema.extract_json_object(payload) == json.loads(payload)


def test_extract_json_object_fails_closed_on_a_recursion_error_from_the_decoder(monkeypatch):
    """Supplemental coverage: an actual RecursionError from raw_decode (should
    the running interpreter ever raise one within the bound) still reaches
    the same bounded, scrubbed diagnostic as every other decode failure
    here, on top of the explicit depth bound proven above."""
    def reject_deep_json(_decoder, _text, _start=0):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", reject_deep_json)
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object('{"item": {}}')


def test_extract_json_object_fails_closed_on_malformed_json():
    """A brace-wrapped but syntactically invalid LLM response must raise the
    same fail-closed RuntimeError this module uses for other unusable-verdict
    cases, never an unhandled json.JSONDecodeError (the reported CI crash).

    Devin Review security finding on PR #1507: the raised diagnostic must
    never embed the raw (even scrubbed) model response, because this is a
    public ``pull_request_target`` job and the finite scrub-pattern list
    cannot guarantee an LLM-echoed or hallucinated credential in an
    unrecognized shape is caught. Only a length and a content fingerprint
    are logged."""
    # Reproduces "Expecting property name enclosed in double quotes": an
    # unquoted/truncated key inside an otherwise brace-wrapped object.
    malformed = '{"decision":"approve", trailing garbage not: "quoted}'
    with pytest.raises(RuntimeError, match="was not valid JSON") as excinfo:
        noema.extract_json_object(malformed)
    assert not isinstance(excinfo.value, json.JSONDecodeError)
    message = str(excinfo.value)
    # The raw response text must never appear in the diagnostic.
    assert "approve" not in message
    assert "trailing garbage" not in message
    # A bounded, non-secret correlation diagnostic replaces it instead.
    assert f"response length={len(malformed)} chars" in message
    assert "sha256=" in message
    fingerprint = hashlib.sha256(malformed.encode("utf-8")).hexdigest()[:16]
    assert fingerprint in message

    # A response truncated mid-object hits the same decode failure.
    truncated = '{"decision":"approve","summary":"looks fine so far,'
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.extract_json_object(truncated)

    # A credential in a shape the finite scrub-pattern list does NOT
    # recognize (no "token"/"key"/"bearer" marker, no known provider prefix
    # — just a bare UUID-shaped value mid-sentence) must still never reach
    # the raised message, because raw content is never embedded at all.
    unrecognized_shape_secret = fake_secret(
        "3f29e1a7-8b44-4c1d", "-9e77-2a5f9c001234"
    )
    leaky = (
        '{"decision":"approve","summary":"use internal id '
        f"{unrecognized_shape_secret} to correlate, trailing garbage"
    )
    # Confirm this test is not vacuous: the existing finite regex scrubber
    # really does miss this shape.
    assert unrecognized_shape_secret in (noema.scrub_sensitive_data(leaky) or "")
    with pytest.raises(RuntimeError) as leaky_excinfo:
        noema.extract_json_object(leaky)
    leaky_message = str(leaky_excinfo.value)
    assert unrecognized_shape_secret not in leaky_message
    assert "approve" not in leaky_message
    assert "ghp_" not in leaky_message

    # A known-shape secret (would have matched the old finite scrubber too)
    # must also never appear, now that raw content is omitted outright.
    known_shape_leaky = '{"decision":"approve","summary":"token ghp_' + "a" * 36 + '", bad'
    with pytest.raises(RuntimeError) as known_excinfo:
        noema.extract_json_object(known_shape_leaky)
    assert "ghp_" not in str(known_excinfo.value)

    # Long malformed content produces a bounded diagnostic regardless of
    # input size — never logged in full, and never truncated-and-embedded
    # either; the diagnostic length does not grow with the input.
    huge = '{"decision":"approve", ' + ("x" * 5000) + " bad"
    with pytest.raises(RuntimeError) as huge_excinfo:
        noema.extract_json_object(huge)
    huge_message = str(huge_excinfo.value)
    assert "x" * 100 not in huge_message
    assert len(huge_message) < 500
    assert f"response length={len(huge)} chars" in huge_message

    # Devin Review follow-up finding: a malformed verdict containing an
    # escaped lone surrogate (valid inside a Python/JSON string, but not
    # representable in strict UTF-8) must not crash the fingerprint
    # computation itself with an unhandled UnicodeEncodeError -- it must
    # still fail closed with the same bounded RuntimeError.
    surrogate_bearing = '{"decision":"approve", "note": "\ud800", trailing bad'
    with pytest.raises(RuntimeError, match="was not valid JSON") as surrogate_excinfo:
        noema.extract_json_object(surrogate_bearing)
    assert not isinstance(surrogate_excinfo.value, UnicodeEncodeError)
    surrogate_message = str(surrogate_excinfo.value)
    assert "sha256=" in surrogate_message
    assert f"response length={len(surrogate_bearing)} chars" in surrogate_message


def test_extract_llm_message_content_happy_paths():
    """A well-formed envelope returns its stripped content; a missing (not
    malformed) choices/message/content field is treated leniently, matching
    the pre-fix code's behavior for an absent field."""
    envelope = json.dumps({"choices": [{"message": {"content": "  {\"decision\":\"approve\"}  "}}]})
    assert noema.extract_llm_message_content(envelope) == '{"decision":"approve"}'

    assert noema.extract_llm_message_content(json.dumps({})) == ""
    assert noema.extract_llm_message_content(json.dumps({"choices": []})) == ""
    assert noema.extract_llm_message_content(json.dumps({"choices": [{}]})) == ""
    assert noema.extract_llm_message_content(json.dumps({"choices": [{"message": None}]})) == ""
    assert (
        noema.extract_llm_message_content(json.dumps({"choices": [{"message": {"content": None}}]}))
        == ""
    )


def test_extract_llm_message_content_fails_closed_on_malformed_raw_body():
    """Devin Review bug finding on PR #1507: a malformed raw HTTP body must
    raise the same bounded RuntimeError call_llm's repair path already uses
    for a malformed verdict, never an unhandled json.JSONDecodeError."""
    with pytest.raises(RuntimeError, match="response body was not valid JSON"):
        noema.extract_llm_message_content("not json at all")


@pytest.mark.parametrize("body", ["[]", "null", '"just a string"', "5"])
def test_extract_llm_message_content_fails_closed_on_non_object_top_level(body):
    """A syntactically valid but non-object top-level JSON value (array,
    null, bare string, bare number) must fail closed instead of crashing on
    the next `.get(...)` call, exactly as Devin's finding described."""
    with pytest.raises(RuntimeError, match="response body was not a JSON object"):
        noema.extract_llm_message_content(body)


@pytest.mark.parametrize("choices", [{"a": 1}, "choices-as-string", 5])
def test_extract_llm_message_content_fails_closed_on_wrong_shaped_choices(choices):
    """A present-but-wrong-shaped (non-list) 'choices' field must fail
    closed instead of crashing on `choices[0]`."""
    with pytest.raises(RuntimeError, match="'choices' was not a list"):
        noema.extract_llm_message_content(json.dumps({"choices": choices}))


@pytest.mark.parametrize("first_choice", [None, 1, "text"])
def test_extract_llm_message_content_fails_closed_on_wrong_shaped_choice_element(first_choice):
    """A choices[0] that is not a JSON object must fail closed instead of
    crashing on `.get("message")`."""
    with pytest.raises(RuntimeError, match=r"choices\[0\] was not a JSON object"):
        noema.extract_llm_message_content(json.dumps({"choices": [first_choice]}))


@pytest.mark.parametrize("message", [[1, 2], "text", 5])
def test_extract_llm_message_content_fails_closed_on_wrong_shaped_message(message):
    """A present-but-wrong-shaped (non-object) 'message' field must fail
    closed instead of crashing on `.get("content")`."""
    with pytest.raises(RuntimeError, match="'message' was not a JSON object"):
        noema.extract_llm_message_content(json.dumps({"choices": [{"message": message}]}))


@pytest.mark.parametrize("content", [5, [1, 2], {"a": 1}])
def test_extract_llm_message_content_fails_closed_on_non_string_content(content):
    """A present-but-non-string 'content' field must fail closed instead of
    crashing on `.strip()`."""
    with pytest.raises(RuntimeError, match="'content' was not a string"):
        noema.extract_llm_message_content(
            json.dumps({"choices": [{"message": {"content": content}}]})
        )


def test_decode_llm_response_body_happy_path():
    """A well-formed UTF-8 response body decodes normally."""
    assert noema.decode_llm_response_body("hello world".encode("utf-8")) == "hello world"


def test_decode_llm_response_body_fails_closed_on_invalid_utf8():
    """Devin Review bug finding on PR #1507 round 3: a gateway reply
    containing invalid UTF-8 must raise the same bounded RuntimeError
    call_llm's repair path already uses for a malformed envelope, never an
    unhandled UnicodeDecodeError. The raised message must never embed the
    raw response bytes — even an attempted-decode fragment near the bad
    byte — matching extract_json_object's no-raw-content pattern, since a
    body containing invalid UTF-8 could still contain a credential-adjacent
    byte sequence."""
    secret_like_prefix = b"token=ghp_deadbeef1234567890"
    raw_bytes = secret_like_prefix + bytes([0xFF]) + b"unrecoverable tail bytes"
    with pytest.raises(RuntimeError) as excinfo:
        noema.decode_llm_response_body(raw_bytes)
    message = str(excinfo.value)
    assert "not valid UTF-8" in message
    assert "ghp_" not in message
    assert "unrecoverable tail" not in message
    fingerprint = hashlib.sha256(raw_bytes).hexdigest()[:16]
    assert f"response length={len(raw_bytes)} bytes" in message
    assert f"sha256={fingerprint}" in message


def test_call_llm_repairs_one_malformed_envelope_before_failing_closed(monkeypatch):
    """The envelope-level fail-closed path integrates with the existing
    verdict-repair boundary: a malformed gateway reply gets one repair-retry
    request before failing closed, exactly like a malformed verdict JSON
    already does."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    bodies = iter(
        (
            "not-json-at-all",
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"decision": "comment", "summary": "Recovered", "findings": []}
                                )
                            }
                        }
                    ]
                }
            ),
        )
    )
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return next(bodies).encode()

    def open_response(_opener, request, **_kwargs):
        requests.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())

    verdict = noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")

    assert verdict["summary"] == "Recovered"
    assert len(requests) == 2
    assert "prior verdict was rejected" in requests[1]["messages"][1]["content"]


def test_call_llm_skips_repair_retry_when_head_moves_before_it_fires(monkeypatch):
    """CodeRabbit finding on PR #1507: ``expected_head`` is checked before
    model work and before publication, but the one-time repair-retry request
    inside ``call_llm`` used to fire unconditionally on a malformed first
    verdict, even if the PR head had already moved. That burns a second,
    potentially multi-hour ``NOEMA_LLM_TIMEOUT_SECONDS`` call on a review
    ``inspect_and_review``'s own post-call stale-head check would discard
    anyway. ``call_llm`` must instead re-check the live head via ``fetch_pr``
    before the retry request and fail closed with
    ``StaleHeadDuringRepairRetryError`` — cleanly, not a crash — issuing only
    the one doomed first request."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    open_calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            # Malformed: missing "choices" triggers call_llm's fail-closed
            # RuntimeError path on the very first attempt.
            return b"[]"

    def open_response(_opener, request, **_kwargs):
        open_calls.append(request)
        return Response()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", open_response)
    # The live PR head has moved on since the trigger fetched "head".
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr(headRefOid="new"))

    with pytest.raises(noema.StaleHeadDuringRepairRetryError, match="stale before repair retry"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")
    # Only the first, already-doomed request was made — the repair-retry
    # request never fired once the live head no longer matched.
    assert len(open_calls) == 1


def test_call_llm_still_repairs_once_when_head_has_not_moved(monkeypatch):
    """A matching live head must not block the existing one-time repair
    retry — this is a narrow addition to the existing repair boundary, not a
    behavior change for the unstale case."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    contents = iter(
        (
            "not-json-at-all",
            json.dumps({"decision": "comment", "summary": "Recovered", "findings": []}),
        )
    )
    open_calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            content = next(contents)
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def open_response(_opener, request, **_kwargs):
        open_calls.append(request)
        return Response()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr(headRefOid="head"))

    verdict = noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")

    assert verdict["summary"] == "Recovered"
    assert len(open_calls) == 2


def test_inspect_and_review_reports_stale_before_repair_retry_cleanly(monkeypatch):
    """``inspect_and_review`` must treat a stale-during-repair-retry signal
    exactly like its own pre-model and pre-publication stale checks: a clean
    skip (return 0), never an unhandled exception or a published review."""
    pr = make_pr()
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, value: "context")

    def fake_call_llm(*args, **kwargs):
        raise noema.StaleHeadDuringRepairRetryError(
            "Pull request head changed during review; stale before repair retry."
        )

    monkeypatch.setattr(noema, "call_llm", fake_call_llm)
    monkeypatch.setattr(
        noema,
        "submit_review",
        lambda *args, **kwargs: pytest.fail("stale-during-repair verdict must not publish"),
    )

    assert noema.inspect_and_review("owner/repo", 7, "head") == 0


def test_call_llm_fails_closed_after_repeated_malformed_envelope(monkeypatch):
    """Two consecutive malformed envelopes must produce a single clean
    top-level RuntimeError diagnostic, never an unhandled traceback — but
    the first still gets a repair-retry request like a malformed verdict
    would."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    open_calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            # Top-level JSON is a bare list — no "choices" object to speak of.
            return b"[]"

    def open_response(_opener, request, **_kwargs):
        open_calls.append(request)
        return Response()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())

    with pytest.raises(RuntimeError, match="response body was not a JSON object"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")
    assert len(open_calls) == 2


def test_call_llm_fails_closed_after_repeated_invalid_utf8_response(monkeypatch):
    """Devin Review bug finding on PR #1507 round 3: a gateway reply
    containing invalid UTF-8 bytes used to raise UnicodeDecodeError before
    extract_llm_message_content or the verdict-JSON repair boundary ever
    ran, crashing the required review check with an unhandled traceback.
    It must instead integrate with the existing repair-retry boundary
    exactly like a malformed JSON envelope already does: one repair-retry
    request, then a single clean top-level RuntimeError when the retry
    response is *also* invalid UTF-8 — never an unhandled traceback."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    open_calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            # Invalid UTF-8: a lone continuation byte with no lead byte.
            return b"not utf-8 at all: \x80\x81\xfe"

    def open_response(_opener, request, **_kwargs):
        open_calls.append(request)
        return Response()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())

    with pytest.raises(RuntimeError, match="response body was not valid UTF-8"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")
    # One initial request plus exactly one repair-retry request — not an
    # unbounded retry loop, and not a crash on the first attempt.
    assert len(open_calls) == 2
    assert "prior verdict was rejected" in json.loads(open_calls[1].data)["messages"][1]["content"]


@pytest.mark.parametrize("choices", [{"a": 1}, 5])
def test_call_llm_fails_closed_on_wrong_shaped_gateway_choices(monkeypatch, choices):
    """A malformed (non-list) choices field surfaces through call_llm's
    fail-closed path rather than crashing the required review job."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": choices}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())

    with pytest.raises(RuntimeError, match="'choices' was not a list"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")


@pytest.mark.parametrize(
    ("actor", "installation_id", "source"),
    [
        ("opencode-agent[bot]", "123", "noema-review-pat"),
        ("not a bot", "123", "noema-review-github-app"),
        ("cwl-noema-review[bot]", "not-numeric", "noema-review-github-app"),
    ],
)
def test_current_actor_rejects_unbound_action_identity(monkeypatch, actor, installation_id, source):
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", actor)
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", installation_id)
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", source)
    with pytest.raises(RuntimeError, match="identity binding is invalid"):
        noema.current_actor()


def test_review_context_builders_include_codegraph_threads_and_files(monkeypatch, tmp_path):
    assert noema.truncate_text("abc", 10) == "abc"
    assert "truncated 2 characters" in noema.truncate_text("abcdef", 4)
    assert "missing PR head SHA" in noema.changed_file_context("owner/repo", 7, "")

    original_fetch_paths = noema.fetch_changed_file_paths
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: [])
    assert "no changed files" in noema.changed_file_context("owner/repo", 7, "head")
    monkeypatch.setattr(noema, "fetch_changed_file_paths", original_fetch_paths)

    encoded = base64.b64encode(b"print('hello')\n").decode("ascii")
    calls = []

    def fake_run(args, stdin=None):
        calls.append(args)
        target = args[2]
        if target.endswith("/files"):
            return "src/a.py\nREADME.md\nempty.txt\n"
        if "contents/src/a.py" in target:
            return encoded
        if "contents/README.md" in target:
            raise RuntimeError("Command failed: token secret")
        if "contents/empty.txt" in target:
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)
    codegraph_path = tmp_path / "codegraph.md"
    codegraph_path.write_text("call graph: src/a.py -> tests", encoding="utf-8")
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(codegraph_path))
    pr = make_pr(
        headRefOid="head sha",
        reviewThreads={
            "nodes": [
                {
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/a.py",
                    "line": 3,
                    "comments": {"nodes": [{"author": {"login": "reviewer"}, "body": "check call site"}]},
                },
                {
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "README.md",
                    "comments": {"nodes": []},
                },
            ]
        },
    )

    context = noema.build_review_context("owner/repo", 7, pr)

    assert "## CodeGraph context" in context
    assert "call graph: src/a.py -> tests" in context
    assert "Thread open at src/a.py:3" in context
    assert "reviewer: check call site" in context
    assert "### src/a.py" in context
    assert "print('hello')" in context
    assert "Unavailable from head content API" in context
    assert "No UTF-8 text content available" in context
    assert any("/files" in call[2] for call in calls)


def test_review_context_reports_omitted_files_and_missing_codegraph(monkeypatch, tmp_path):
    monkeypatch.delenv("NOEMA_CODEGRAPH_CONTEXT_PATH", raising=False)
    assert noema.load_codegraph_context() == ""

    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(tmp_path / "missing.md"))
    assert "CodeGraph context unavailable" in noema.load_codegraph_context()

    paths = [f"src/file_{index}.py" for index in range(noema.MAX_CONTEXT_FILES + 1)]
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)
    monkeypatch.setattr(noema, "fetch_head_file_content", lambda repo, path, head_sha: "x")

    context = noema.changed_file_context("owner/repo", 7, "head")

    assert "1 changed files omitted from context budget" in context


class FakeResponse:
    """Small context-manager response for urllib monkeypatches."""

    def __init__(self, payload):
        """Store a JSON-serializable response payload."""
        self.payload = payload

    def __enter__(self):
        """Return the response for with-statement use."""
        return self

    def __exit__(self, *args):
        """Propagate exceptions from the with-statement body."""
        return False

    def read(self):
        """Return the payload as encoded JSON bytes."""
        return json.dumps(self.payload).encode("utf-8")


def test_call_llm_handles_configuration_and_verdicts(monkeypatch):
    monkeypatch.setattr(noema, "validate_substantive_verdict", lambda *_args: None)
    pr = make_pr()
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: pr)
    monkeypatch.delenv("NOEMA_LLM_API_URL", raising=False)
    monkeypatch.delenv("NOEMA_LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    monkeypatch.setenv("NOEMA_LLM_API_URL", "file:///etc/passwd")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "review-model")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "approve",
                                    "summary": "ok",
                                    "findings": [
                                        {"severity": "low", "file": "a.py", "line": 1, "side": "RIGHT", "message": "checked"},
                                        {"severity": "medium", "file": "b.py", "line": 2, "side": "LEFT", "message": "checked"},
                                    ],
                                }
                            )
                        }
                    }
                ]
            }
        )

    # Since we replaced urlopen with build_opener, we mock build_opener
    class FakeOpener:
        def __init__(self, call_func):
            self.call_func = call_func
        def open(self, request, timeout=None):
            return self.call_func(request, timeout)

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    verdict = noema.call_llm("owner/repo", 1, pr, "diff", True, "head", "extra review context")
    assert verdict["decision"] == "approve"
    assert seen["url"] == "https://llm.example.test/chat"
    assert seen["timeout"] == 14400
    assert seen["body"]["model"] == "review-model"
    assert "extra review context" in seen["body"]["messages"][1]["content"]

    def fake_urlopen_defer(request, timeout=None):
        return FakeResponse({"choices": [{"message": {"content": '{"decision":"defer"}'}}]})

    monkeypatch.setattr(
        noema.urllib.request,
        "build_opener",
        lambda *args: FakeOpener(fake_urlopen_defer)
    )
    with pytest.raises(RuntimeError, match="unsupported decision"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    # Test case-insensitive valid URL
    monkeypatch.setenv("NOEMA_LLM_API_URL", "HTTPS://llm.example.test/chat")
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    assert noema.call_llm("owner/repo", 1, pr, "diff", True, "head")["decision"] == "approve"

    # Test invalid scheme (and no original URL in error)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "file:///etc/passwd")
    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    # Test localhost rejection
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://localhost/chat")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    # Test missing hostname
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http:///chat")
    with pytest.raises(ValueError, match="URL must have a valid hostname"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    # Test internal IP rejection
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://169.254.169.254/chat")
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    import socket
    original_getaddrinfo = socket.getaddrinfo

    # Test DNS resolution bypass
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://resolved-to-local.example.com/chat")
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host == "resolved-to-local.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    # Test unresolved hostname does not break
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://unresolved.example.com/chat")
    def fake_getaddrinfo_error(host, port, *args, **kwargs):
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_error)
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    assert noema.call_llm("owner/repo", 1, pr, "diff", True, "head")["decision"] == "approve"

    # Test invalid IP string from getaddrinfo (unlikely but theoretically possible)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://weird-dns.example.com/chat")
    def fake_getaddrinfo_invalid_ip(host, port, *args, **kwargs):
        if host == "weird-dns.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not_an_ip", 0))]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_invalid_ip)
    assert noema.call_llm("owner/repo", 1, pr, "diff", True, "head")["decision"] == "approve"


def test_noema_redirect_handler_rejects_redirects():
    """Noema must not follow redirects after validating the initial URL."""
    handler = noema.NoRedirectHandler()
    request = noema.urllib.request.Request("https://llm.example.test/chat")

    with pytest.raises(noema.urllib.error.HTTPError):
        handler.redirect_request(
            request,
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="http://169.254.169.254/latest/meta-data/",
        )


def test_call_llm_rejects_control_character_scheme_evasion(monkeypatch):
    """A URL with an embedded tab is normalized by urlparse to an http scheme
    with a valid hostname, but its raw form does not start with http:// — the
    startswith guard must still reject it to prevent SSRF via control-character
    scheme evasion."""
    pr = make_pr()
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http\t://sneaky.example.com/chat")

    import socket

    def raise_gaierror(host, port, *args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    with pytest.raises(ValueError, match="must start with http:// or https://"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")


def test_call_llm_rejects_non_http_parsed_scheme(monkeypatch):
    """Keep the parsed-scheme SSRF guard covered as defense in depth."""
    pr = make_pr()
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    parsed = noema.urllib.parse.ParseResult("file", "llm.example.test", "/chat", "", "", "")
    monkeypatch.setattr(noema.urllib.parse, "urlparse", lambda _: parsed)

    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")


def test_format_findings_and_submit_review(monkeypatch):
    findings = noema.format_findings(
        [
            {"severity": "high", "file": "a.py", "line": 3, "side": "RIGHT", "message": "bad"},
            {"severity": "low", "file": "b.py", "line": 0, "message": "note"},
            "skip",
            {"message": ""},
        ]
    )
    assert findings == ["- [high] a.py:3 (RIGHT): bad", "- [low] b.py: note"]

    calls = []
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "oidc")
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: calls.append((args, json.loads(stdin))) or "")
    noema.submit_review(
        "owner/repo",
        7,
        make_pr(),
        "noema",
        {"decision": "request_changes", "summary": "fix it", "findings": [{"file": "a.py", "line": 1, "side": "RIGHT", "message": "bad"}]},
    )
    payload = calls[0][1]
    assert payload["event"] == "REQUEST_CHANGES"
    assert payload["commit_id"] == "head"
    assert "Noema LLM review" in payload["body"]
    assert "oidc" in payload["body"]

    calls.clear()
    noema.submit_review("owner/repo", 7, make_pr(), "", {"decision": "comment"})
    assert calls[0][1]["event"] == "COMMENT"
    assert "No blocking findings" in calls[0][1]["body"]


def test_inspect_and_review_skip_paths(monkeypatch):
    clean_pr = make_pr()
    calls = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok", "findings": []})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7, "head") == 0
    assert calls

    cases = [
        (make_pr(isDraft=True), "noema"),
        (make_pr(reviews={"nodes": [review(login="noema", body="<!-- noema-review-gate head_sha=head -->")]}), "noema"),
    ]
    for pr, actor in cases:
        calls.clear()
        monkeypatch.setattr(noema, "fetch_pr", lambda repo, number, pr=pr: pr)
        monkeypatch.setattr(noema, "current_actor", lambda actor=actor: actor)
        assert noema.inspect_and_review("owner/repo", 7, "head") == 0
        assert calls == []

    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "")
    with pytest.raises(RuntimeError, match="identity could not be verified"):
        noema.inspect_and_review("owner/repo", 7, "head")

    monkeypatch.setattr(noema, "current_actor", lambda: "opencode-agent")
    with pytest.raises(RuntimeError, match="independent reviewer credential"):
        noema.inspect_and_review("owner/repo", 7, "head")


def test_inspect_and_review_does_not_wait_for_other_reviews_or_checks(monkeypatch):
    pr = make_pr(
        reviews={"nodes": [review("CHANGES_REQUESTED")]},
        reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]},
        statusCheckRollup={"contexts": {"nodes": [{"__typename": "StatusContext", "context": "ci", "state": "FAILURE"}]}},
    )
    calls = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, value: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok"})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7, "head") == 0
    assert calls


def test_stale_trigger_stops_before_identity_or_model_work(monkeypatch):
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr(headRefOid="new"))
    monkeypatch.setattr(
        noema,
        "current_actor",
        lambda: pytest.fail("stale execution must stop before identity lookup"),
    )
    assert noema.inspect_and_review("owner/repo", 7, "old") == 0


def test_expected_head_comparison_is_case_insensitive(monkeypatch):
    seen = []
    monkeypatch.setattr(
        noema,
        "fetch_pr",
        lambda repo, number: make_pr(headRefOid="a" * 40, isDraft=True),
    )
    monkeypatch.setattr(noema, "current_actor", lambda: seen.append("actor") or "noema")
    assert noema.inspect_and_review("owner/repo", 7, "A" * 40) == 0
    assert seen == ["actor"]


def test_head_movement_stops_before_review_publication(monkeypatch):
    pull_requests = iter((make_pr(), make_pr(headRefOid="new")))
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: next(pull_requests))
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(
        noema,
        "call_llm",
        lambda *args, **kwargs: {"decision": "approve", "summary": "ok"},
    )
    monkeypatch.setattr(
        noema,
        "submit_review",
        lambda *args, **kwargs: pytest.fail("stale verdict must not publish"),
    )
    assert noema.inspect_and_review("owner/repo", 7, "head") == 0


def test_uppercase_expected_head_is_not_stale_before_model_work(monkeypatch):
    """An uppercase --expected-head must match GitHub's lowercase live SHA (Devin Review, PR #1507)."""
    pr = make_pr(headRefOid="abc123def0")
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, value: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok"})
    calls = []
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7, "ABC123DEF0") == 0
    assert calls


def test_uppercase_expected_head_is_not_stale_before_publication(monkeypatch):
    """The pre-publication re-check must also compare case-insensitively."""
    pull_requests = iter((make_pr(headRefOid="abc123def0"), make_pr(headRefOid="abc123def0")))
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: next(pull_requests))
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(
        noema,
        "call_llm",
        lambda *args, **kwargs: {"decision": "approve", "summary": "ok"},
    )
    calls = []
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7, "ABC123DEF0") == 0
    assert calls


def test_call_llm_rejects_empty_review_content(monkeypatch):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"decision":"approve"}'}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    with pytest.raises(RuntimeError, match="substantive summary"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")


def test_call_llm_fails_closed_on_malformed_json_response(monkeypatch):
    """Reproduces the reported CI crash: an LLM response whose content is
    truncated/malformed JSON must fail the review cleanly through call_llm's
    existing RuntimeError path, never as an unhandled json.JSONDecodeError."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            # Malformed: an unquoted property name after the decision key,
            # matching "Expecting property name enclosed in double quotes".
            malformed_content = '{"decision":"approve", trailing garbage not: "quoted}'
            return json.dumps({"choices": [{"message": {"content": malformed_content}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    with pytest.raises(RuntimeError, match="was not valid JSON"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")


def test_call_llm_repairs_one_malformed_json_response(monkeypatch):
    """Ask once for corrected JSON before failing the required review closed."""
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    contents = iter(
        (
            '{"decision":"approve", trailing garbage not: "quoted}',
            json.dumps({"decision": "comment", "summary": "Repaired JSON", "findings": []}),
        )
    )
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            content = next(contents)
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def open_response(_opener, request, **_kwargs):
        requests.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", open_response)
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())

    verdict = noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")

    assert verdict["summary"] == "Repaired JSON"
    assert len(requests) == 2
    assert "prior verdict was rejected" in requests[1]["messages"][1]["content"]


@pytest.mark.parametrize("message", [[], {}, 0, "   "])
def test_call_llm_rejects_malformed_blocking_findings(monkeypatch, message):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    verdict = {
        "decision": "request_changes",
        "summary": "blocking issue",
        "findings": [{"severity": "high", "file": "a.py", "line": 1, "side": "RIGHT", "message": message}],
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    with pytest.raises(RuntimeError, match="malformed finding"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")


@pytest.mark.parametrize(
    ("findings", "error"),
    [
        (None, "list of objects"),
        ([0], "list of objects"),
        ([{"severity": "info", "file": "a.py", "line": 1, "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": 1, "line": 1, "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": " ", "line": 1, "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": "a.py", "line": "1", "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": "a.py", "line": 0, "message": "bad"}], "malformed finding"),
        ([], "substantive finding"),
    ],
)
def test_call_llm_rejects_invalid_findings_contract(monkeypatch, findings, error):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    verdict = {"decision": "request_changes", "summary": "blocking issue", "findings": findings}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    with pytest.raises(RuntimeError, match=error):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")


def test_call_llm_rejects_generic_approve_without_changed_line_evidence(monkeypatch):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    verdict = {"decision": "approve", "summary": "No blocking issues found.", "findings": []}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    with pytest.raises(RuntimeError, match="parseable changed-line evidence"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False, "head")


def test_call_llm_repairs_one_rejected_changed_line_verdict(monkeypatch):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    diff = """--- a/tool.py
+++ b/tool.py
@@ -1 +1 @@
-old = True
+new = True
"""
    invalid = {
        "decision": "approve",
        "summary": "Checked the replacement.",
        "findings": [],
        "reviewed_lines": [
            {"path": "tool.py", "line": 2, "side": "RIGHT", "analysis": "Checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Callers were not executed.",
            "probes": [],
        },
    }
    valid = {
        **invalid,
        "reviewed_lines": [
            {"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "Checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Callers were not executed.",
            "probes": [
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The assignment was removed.",
                    "attack_or_counterexample": "Inspect the added hunk line.",
                    "evidence": "The RIGHT-side assignment remains present.",
                    "outcome": "falsified",
                },
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The value became false.",
                    "attack_or_counterexample": "Read the replacement literal.",
                    "evidence": "The literal is True.",
                    "outcome": "falsified",
                },
            ],
        },
    }
    payloads = []

    class Response:
        def __init__(self, verdict):
            self.verdict = verdict

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(self.verdict)}}]}
            ).encode()

    class Opener:
        def open(self, request, timeout):
            assert timeout == noema.NOEMA_LLM_TIMEOUT_SECONDS
            payloads.append(json.loads(request.data))
            return Response(invalid if len(payloads) == 1 else valid)

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())

    assert noema.call_llm("owner/repo", 7, make_pr(), diff, False, "head")["decision"] == "approve"
    assert len(payloads) == 2
    assert "trusted validator" in payloads[1]["messages"][1]["content"]


def test_substantive_approve_requires_exact_changed_lines_and_falsified_probes():
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1,2 +1,2 @@
-old = True
+new = True
 keep = 1
"""
    verdict = {
        "decision": "approve",
        "summary": "The changed assignment preserves the required invariant.",
        "findings": [],
        "reviewed_lines": [
            {"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "The new assignment is explicit."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Runtime consumers outside this diff were not executed.",
            "probes": [
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The value becomes false.",
                    "attack_or_counterexample": "Trace the literal assigned at the changed line.",
                    "evidence": "The changed source assigns the boolean literal True.",
                    "outcome": "falsified",
                },
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The assignment is removed.",
                    "attack_or_counterexample": "Compare the added side with the deleted side.",
                    "evidence": "The RIGHT-side hunk contains one replacement assignment.",
                    "outcome": "falsified",
                },
            ],
        },
    }
    noema.validate_substantive_verdict(verdict, diff)

    verdict["adversarial_validation"]["probes"][0]["outcome"] = "confirmed"
    with pytest.raises(RuntimeError, match="approve cannot contain a confirmed"):
        noema.validate_substantive_verdict(verdict, diff)


def test_substantive_verdict_fail_closed_boundaries():
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1 +1 @@
-old = True
+new = True
"""
    valid = {
        "decision": "approve",
        "summary": "The replacement keeps the invariant.",
        "findings": [],
        "reviewed_lines": [{"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "The replacement is explicit."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Callers were not executed.",
            "probes": [
                {"path": "tool.py", "line": 1, "side": "RIGHT", "hypothesis": "The value is false.", "attack_or_counterexample": "Read the literal.", "evidence": "The literal is True.", "outcome": "falsified"},
                {"path": "tool.py", "line": 1, "side": "RIGHT", "hypothesis": "The assignment vanished.", "attack_or_counterexample": "Inspect the added line.", "evidence": "One assignment is present.", "outcome": "falsified"},
            ],
        },
    }

    assert noema.validate_substantive_verdict({"decision": "comment"}, diff) is None
    invalid_cases = [
        (lambda value: value.pop("reviewed_lines"), "at least one reviewed"),
        (lambda value: value.update(reviewed_lines=[None]), "reviewed line 1 must be an object"),
        (lambda value: value["reviewed_lines"][0].update(analysis=""), "requires concrete analysis"),
        (lambda value: value.pop("adversarial_validation"), "requires adversarial_validation"),
        (lambda value: value["adversarial_validation"].update(status="failed"), "status=passed"),
        (lambda value: value["adversarial_validation"].update(residual_risk=""), "requires residual_risk"),
        (lambda value: value["adversarial_validation"].update(probes=[]), "at least 2 concrete probe"),
        (lambda value: value["adversarial_validation"].update(probes=[None, None]), "probe 1 must be an object"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(line=2), "not an exact changed-side line"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(hypothesis=""), "requires hypothesis"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(attack_or_counterexample=""), "requires attack_or_counterexample"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(evidence=""), "requires evidence"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(outcome="unknown"), "outcome must be"),
        (lambda value: value["adversarial_validation"]["probes"].__setitem__(1, dict(value["adversarial_validation"]["probes"][0])), "duplicates an earlier probe"),
    ]
    for mutate, message in invalid_cases:
        candidate = json.loads(json.dumps(valid))
        mutate(candidate)
        with pytest.raises(RuntimeError, match=message):
            noema.validate_substantive_verdict(candidate, diff)


def test_changed_diff_locations_handles_new_files_and_no_newline_marker():
    diff = """diff --git a/new.py b/new.py
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+enabled = True
\\ No newline at end of file
"""
    assert noema.changed_diff_locations(diff) == {("new.py", 1, "RIGHT")}
    malformed_side_lines = """--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
-impossible deletion
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
+impossible addition
"""
    assert noema.changed_diff_locations(malformed_side_lines) == set()
    impossible_addition = """--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
+impossible addition
"""
    assert noema.changed_diff_locations(impossible_addition) == set()


def test_changed_diff_locations_decodes_git_quoted_utf8_paths():
    diff = '''diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"
--- "a/caf\\303\\251.py"
+++ "b/caf\\303\\251.py"
@@ -1 +1 @@
-old = True
+new = True
'''
    assert noema.changed_diff_locations(diff) == {
        ("café.py", 1, "LEFT"),
        ("café.py", 1, "RIGHT"),
    }
    assert noema.parse_diff_path('"unterminated', "a/") == ""


def test_changed_diff_locations_keeps_diff_like_hunk_content():
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1,2 +1,2 @@
---deleted content
-old tail
+++added content
+new tail
"""
    assert noema.changed_diff_locations(diff) == {
        ("tool.py", 1, "LEFT"),
        ("tool.py", 2, "LEFT"),
        ("tool.py", 1, "RIGHT"),
        ("tool.py", 2, "RIGHT"),
    }


def test_complete_changed_paths_preserve_material_probe_requirement():
    diff = """--- a/docs/note.md
+++ b/docs/note.md
@@ -1 +1 @@
-old
+new
"""
    verdict = {
        "decision": "approve",
        "summary": "Documentation remains accurate.",
        "findings": [],
        "reviewed_lines": [
            {"path": "docs/note.md", "line": 1, "side": "RIGHT", "analysis": "Replacement checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Runtime file was outside the prompt diff.",
            "probes": [
                {
                    "path": "docs/note.md",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The replacement is empty.",
                    "attack_or_counterexample": "Inspect the added line.",
                    "evidence": "The added line is nonempty.",
                    "outcome": "falsified",
                }
            ],
        },
    }
    with pytest.raises(RuntimeError, match="at least 2 concrete probe"):
        noema.validate_substantive_verdict(
            verdict, diff, ["docs/note.md", "src/runtime.py"]
        )


def test_substantive_verdict_rejects_non_changed_location_and_accepts_left_deletion():
    diff = """diff --git a/docs/old.md b/docs/old.md
--- a/docs/old.md
+++ /dev/null
@@ -3 +0,0 @@
-obsolete claim
"""
    verdict = {
        "decision": "approve",
        "summary": "The obsolete claim is removed.",
        "findings": [],
        "reviewed_lines": [
            {"path": "docs/old.md", "line": 3, "side": "LEFT", "analysis": "The deleted claim was obsolete."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "External links were not crawled.",
            "probes": [
                {
                    "path": "docs/old.md",
                    "line": 3,
                    "side": "LEFT",
                    "hypothesis": "The obsolete claim remains documented.",
                    "attack_or_counterexample": "Inspect the deletion-side hunk.",
                    "evidence": "The only changed line deletes the obsolete claim.",
                    "outcome": "falsified",
                }
            ],
        },
    }
    noema.validate_substantive_verdict(verdict, diff)
    verdict["reviewed_lines"][0]["line"] = 4
    with pytest.raises(RuntimeError, match="not an exact changed-side line"):
        noema.validate_substantive_verdict(verdict, diff)


def test_request_changes_requires_confirmed_probe_at_finding_location():
    diff = """diff --git a/config.yml b/config.yml
--- a/config.yml
+++ b/config.yml
@@ -1 +1 @@
-safe: true
+safe: false
"""
    verdict = {
        "decision": "request_changes",
        "summary": "The safety gate is disabled.",
        "findings": [{"severity": "high", "file": "config.yml", "line": 1, "side": "RIGHT", "message": "Keep the gate enabled."}],
        "reviewed_lines": [
            {"path": "config.yml", "line": 1, "side": "RIGHT", "analysis": "The new value disables the gate."}
        ],
        "adversarial_validation": {
            "status": "failed",
            "residual_risk": "No runtime override was inspected.",
            "probes": [
                {
                    "path": "config.yml",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The safety gate is disabled.",
                    "attack_or_counterexample": "Read the effective changed value.",
                    "evidence": "The RIGHT-side value is false.",
                    "outcome": "confirmed",
                },
                {
                    "path": "config.yml",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The key was renamed instead.",
                    "attack_or_counterexample": "Compare the key name on both sides.",
                    "evidence": "Both sides retain the key name safe.",
                    "outcome": "falsified",
                },
            ],
        },
    }
    noema.validate_substantive_verdict(verdict, diff)
    verdict["findings"][0]["side"] = "LEFT"
    with pytest.raises(RuntimeError, match="confirmed probe on a published finding"):
        noema.validate_substantive_verdict(verdict, diff)
    verdict["findings"][0]["side"] = "RIGHT"
    verdict["adversarial_validation"]["probes"][0]["outcome"] = "falsified"
    with pytest.raises(RuntimeError, match="confirmed probe on a published finding"):
        noema.validate_substantive_verdict(verdict, diff)
    verdict["adversarial_validation"]["probes"][0]["outcome"] = "confirmed"
    verdict["findings"][0]["line"] = 2
    with pytest.raises(RuntimeError, match="confirmed probe on a published finding"):
        noema.validate_substantive_verdict(verdict, diff)


def test_format_review_evidence_renders_only_structured_entries():
    lines = noema.format_review_evidence(
        {
            "reviewed_lines": [None, {"path": "a.py", "line": 2, "side": "RIGHT", "analysis": "checked"}],
            "adversarial_validation": {
                "residual_risk": "none observed",
                "probes": [None, {"path": "a.py", "line": 2, "side": "RIGHT", "outcome": "falsified", "hypothesis": "breaks", "evidence": "source trace passes"}],
            },
        }
    )
    assert any("a.py:2" in line and "checked" in line for line in lines)
    assert any("falsified" in line and "source trace passes" in line for line in lines)


def test_parse_args_and_main(monkeypatch):
    parsed = noema.parse_args(
        ["--repo", "owner/repo", "--pr-number", "9", "--expected-head", "a" * 40]
    )
    assert parsed.repo == "owner/repo"
    assert parsed.pr_number == 9
    assert parsed.expected_head == "a" * 40

    seen = []
    monkeypatch.setattr(
        noema,
        "inspect_and_review",
        lambda repo, number, head: seen.append((repo, number, head)) or 0,
    )
    assert (
        noema.main(
            ["--repo", "owner/repo", "--pr-number", "9", "--expected-head", "a" * 40]
        )
        == 0
    )
    assert seen == [("owner/repo", 9, "a" * 40)]

    with pytest.raises(SystemExit, match="--pr-number must be positive"):
        noema.main(
            ["--repo", "owner/repo", "--pr-number", "0", "--expected-head", "a" * 40]
        )
    with pytest.raises(SystemExit, match="--expected-head must be a canonical lowercase"):
        noema.main(
            ["--repo", "owner/repo", "--pr-number", "9", "--expected-head", "bad"]
        )
    with pytest.raises(SystemExit, match="--expected-head must be a canonical lowercase"):
        noema.main(
            ["--repo", "owner/repo", "--pr-number", "9", "--expected-head", "A" * 40]
        )
