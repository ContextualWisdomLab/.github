"""Pin the run-identity signal both stale-run cleanup jobs select on.

``strix.yml`` and ``opencode-review.yml`` each carry a cleanup job whose whole
purpose is retiring superseded runs of their own workflow. Both selected those
runs with ``select(.name == "<declared workflow name>")``. Both workflows
declare ``run-name:``, and GitHub reports the *rendered* run-name in a run's
``name`` field -- so the equality matched nothing and each job was a silent
no-op. Measured 2026-09-07 against the live API: of the 100 most recent runs of
each workflow, 0 carried the bare declared name and 100 carried the rendered
``"<declared name> <repo>#<pr>@<sha>"`` form.

The repair adopts the signal ``noema-review.yml``'s cleanup job already uses
for the identical defect: ``.path``, which the same measurement confirmed
stable in both contexts -- ``.github/workflows/strix.yml`` on native runs in
``.github`` and on the nine ruleset-injected runs in ``bandscope``, which
carries no local copy of that workflow.

These tests execute the production jq against fixtures in the rendered shape,
so a revert to equality fails here rather than shipping green. Each selector
also gets a negative control: a foreign workflow's run attached to the same
pull request must not be selected, because the surviving ``$metadata_matches``
branch would otherwise let this job cancel other workflows' runs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import scripts.ci.pr_review_merge_scheduler_core as sched

STRIX_WORKFLOW = Path(".github/workflows/strix.yml")
OPENCODE_WORKFLOW = Path(".github/workflows/opencode-review.yml")


def _selector(workflow: Path, start_marker: str) -> str:
    """Return the jq program the named cleanup job runs, read from the workflow."""
    text = workflow.read_text(encoding="utf-8")
    start = text.index(start_marker) + len(start_marker)
    end = text.index('\n              \' <<<"$runs_json"', start)
    return text[start:end]


def _run_jq(selector: str, args: list[str], runs: dict[str, object]) -> list[str]:
    """Execute a selector against a runs payload, returning the selected ids."""
    jq = shutil.which("jq")
    if jq is None:  # pragma: no cover - environment without jq
        pytest.skip("jq is required to execute the production cleanup selector")
    result = subprocess.run(
        [jq, "-r", *args, selector],
        input=json.dumps(runs),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.split()


def _strix_selector() -> str:
    """Return the Strix cleanup job's jq selector."""
    return _selector(
        STRIX_WORKFLOW,
        '--arg action "$PR_ACTION" --arg repo "$TARGET_REPOSITORY"'
        ' --arg current "$CURRENT_RUN_ID" \'\n',
    )


def _opencode_selector() -> str:
    """Return the OpenCode review cleanup job's jq selector."""
    return _selector(
        OPENCODE_WORKFLOW,
        '--arg repo "$TARGET_REPOSITORY" --arg current "$CURRENT_RUN_ID" \'\n',
    )


def test_strix_cleanup_selects_a_superseded_run_whose_name_is_rendered() -> None:
    """The Strix cleanup selector matches the only run shape GitHub sends.

    ``name`` and ``display_title`` are identical here because that is what the
    API returns for a workflow declaring ``run-name:``; a fixture pairing a
    bare ``name`` with a rendered ``display_title`` describes no real run and
    is what let the equality survive.
    """
    old = f"Strix Security Scan owner/repo#7@{'a' * 40}"
    current = f"Strix Security Scan owner/repo#7@{'b' * 40}"
    runs = {
        "workflow_runs": [
            {
                "id": 4001,
                "path": ".github/workflows/strix.yml",
                "name": old,
                "display_title": old,
                "event": "pull_request_target",
                "pull_requests": [{"number": 7, "head": {"sha": "a" * 40}}],
            },
            {
                "id": 4002,
                "path": ".github/workflows/strix.yml",
                "name": current,
                "display_title": current,
                "event": "pull_request_target",
                "pull_requests": [{"number": 7, "head": {"sha": "b" * 40}}],
            },
        ]
    }
    selected = _run_jq(
        _strix_selector(),
        [
            "--arg", "pr", "7",
            "--arg", "head_sha", "b" * 40,
            "--arg", "action", "synchronize",
            "--arg", "repo", "owner/repo",
            "--arg", "current", "4002",
        ],
        runs,
    )
    assert selected == ["4001"]


def test_strix_cleanup_retires_a_run_of_a_closed_pull_request() -> None:
    """A closed pull request's in-flight scan is retired with no successor run.

    This is the case the workflow-level ``concurrency`` group cannot reach: on
    ``synchronize`` a newer run supersedes the old one and GitHub cancels it,
    but ``closed`` and ``converted_to_draft`` start no successor, so the dead
    selector left those scans running to completion against the shared job
    ceiling for a pull request nobody is waiting on.
    """
    title = f"Strix Security Scan owner/repo#7@{'a' * 40}"
    runs = {
        "workflow_runs": [
            {
                "id": 4010,
                "path": ".github/workflows/strix.yml",
                "name": title,
                "display_title": title,
                "event": "pull_request_target",
                "pull_requests": [{"number": 7, "head": {"sha": "a" * 40}}],
            }
        ]
    }
    selected = _run_jq(
        _strix_selector(),
        [
            "--arg", "pr", "7",
            "--arg", "head_sha", "a" * 40,
            "--arg", "action", "closed",
            "--arg", "repo", "owner/repo",
            "--arg", "current", "4099",
        ],
        runs,
    )
    assert selected == ["4010"]


def test_strix_cleanup_leaves_another_workflows_run_alone() -> None:
    """A foreign workflow's run on the same pull request is never selected.

    ``$metadata_matches`` accepts any run whose ``pull_requests[]`` names this
    pull request, so without a workflow-identity filter this job would cancel
    every other central workflow's runs. ``.path`` is that filter.
    """
    foreign = f"Required OpenCode Review owner/repo#7@{'a' * 40}"
    runs = {
        "workflow_runs": [
            {
                "id": 4020,
                "path": ".github/workflows/opencode-review.yml",
                "name": foreign,
                "display_title": foreign,
                "event": "pull_request_target",
                "pull_requests": [{"number": 7, "head": {"sha": "a" * 40}}],
            }
        ]
    }
    selected = _run_jq(
        _strix_selector(),
        [
            "--arg", "pr", "7",
            "--arg", "head_sha", "b" * 40,
            "--arg", "action", "closed",
            "--arg", "repo", "owner/repo",
            "--arg", "current", "4099",
        ],
        runs,
    )
    assert selected == []


def test_opencode_cleanup_selects_a_superseded_run_whose_name_is_rendered() -> None:
    """The OpenCode review cleanup selector matches the rendered run shape."""
    old = f"Required OpenCode Review owner/repo#9@{'c' * 40}"
    current = f"Required OpenCode Review owner/repo#9@{'d' * 40}"
    runs = {
        "workflow_runs": [
            {
                "id": 5001,
                "path": ".github/workflows/opencode-review.yml",
                "name": old,
                "display_title": old,
                "event": "pull_request_target",
                "pull_requests": [{"number": 9, "head": {"sha": "c" * 40}}],
            },
            {
                "id": 5002,
                "path": ".github/workflows/opencode-review.yml",
                "name": current,
                "display_title": current,
                "event": "pull_request_target",
                "pull_requests": [{"number": 9, "head": {"sha": "d" * 40}}],
            },
        ]
    }
    selected = _run_jq(
        _opencode_selector(),
        [
            "--arg", "pr", "9",
            "--arg", "head_sha", "d" * 40,
            "--arg", "repo", "owner/repo",
            "--arg", "current", "5002",
        ],
        runs,
    )
    assert selected == ["5001"]


def test_opencode_cleanup_leaves_another_workflows_run_alone() -> None:
    """A Strix run on the same pull request is not cancelled by OpenCode cleanup."""
    foreign = f"Strix Security Scan owner/repo#9@{'c' * 40}"
    runs = {
        "workflow_runs": [
            {
                "id": 5010,
                "path": ".github/workflows/strix.yml",
                "name": foreign,
                "display_title": foreign,
                "event": "pull_request_target",
                "pull_requests": [{"number": 9, "head": {"sha": "c" * 40}}],
            }
        ]
    }
    selected = _run_jq(
        _opencode_selector(),
        [
            "--arg", "pr", "9",
            "--arg", "head_sha", "d" * 40,
            "--arg", "repo", "owner/repo",
            "--arg", "current", "5099",
        ],
        runs,
    )
    assert selected == []


def test_run_name_identifies_workflow_accepts_both_forms_github_sends() -> None:
    """Both the rendered and the bare run name identify their workflow."""
    assert sched.run_name_identifies_workflow(
        f"Strix Security Scan owner/repo#7@{'a' * 40}", "Strix Security Scan"
    )
    assert sched.run_name_identifies_workflow("Strix Security Scan", "Strix Security Scan")


def test_run_name_identifies_workflow_requires_a_word_boundary() -> None:
    """A name that extends the candidate without a separator is rejected.

    This is the whole of what the required space buys, and the assertion is
    written to say so rather than to imply the predicate resolves identity by
    itself: "Strix Security Scan Extended" *is* accepted, and is safe only
    because no central workflow name prefixes another and every call site pins
    identity again by ``.path``, ``display_title``, or pull-request metadata.
    """
    assert not sched.run_name_identifies_workflow(
        "Strix Security Scanner owner/repo#7@abc", "Strix Security Scan"
    )
    assert not sched.run_name_identifies_workflow("", "Strix Security Scan")
    assert sched.run_name_identifies_workflow(
        "Strix Security Scan Extended", "Strix Security Scan"
    )


def test_no_central_workflow_name_prefixes_another() -> None:
    """Pin the premise that makes a prefix accept safe for these workflows.

    :func:`scripts.ci.pr_review_merge_scheduler_core.run_name_identifies_workflow`
    accepts a candidate followed by a space, so a new workflow named as an
    extension of an existing one ("Strix Security Scan Extended") would start
    answering for it. Nothing else in the repository would notice; this test is
    the notice.
    """
    # Both extensions, though every workflow here is currently ``.yml``. A
    # single ``*.yml`` glob would drop a future ``.yaml`` workflow out of the
    # premise silently, and the count guard below would not notice either --
    # 35 files minus one is still comfortably over the floor. A test whose
    # whole purpose is announcing a change nobody would otherwise see must not
    # be bypassable by a file extension.
    workflows = sorted(
        {
            *Path(".github/workflows").glob("*.yml"),
            *Path(".github/workflows").glob("*.yaml"),
        }
    )
    names = sorted(
        {
            line.split(":", 1)[1].strip().strip("\"'")
            for workflow in workflows
            for line in workflow.read_text(encoding="utf-8").splitlines()
            if line.startswith("name:")
        }
    )
    # Refuse a vacuous pass: an empty or mis-rooted glob makes the collision
    # check below trivially true, which is the exact shape this repository has
    # shipped before (an audit reporting "PASS: all 0 repositories").
    assert len(names) >= 30
    # Every workflow file must contribute a name, or a file could drop out of
    # the premise by losing its top-level ``name:`` rather than its extension.
    assert len(names) == len(workflows)
    collisions = [
        (shorter, longer)
        for shorter in names
        for longer in names
        if shorter != longer and longer.startswith(f"{shorter} ")
    ]
    assert collisions == []


def test_stale_pr_run_ids_matches_a_rendered_workflow_run_name(monkeypatch) -> None:
    """``stale_pr_run_ids`` narrows by workflow using the name GitHub sends.

    Its only production caller passes no ``workflow``, so the equality this
    replaces never ran; the parameter stayed a trap that silently returned no
    runs for any caller that did supply one.
    """
    monkeypatch.setattr(sched, "validate_git_sha", lambda value: str(value))
    rendered = f"Required OpenCode Review owner/repo#1@{'a' * 40}"
    runs = [
        {"name": rendered, "id": 61, "head_sha": "old", "pull_requests": [{"number": 1}]},
        {"name": rendered, "id": 62, "head_sha": "head", "pull_requests": [{"number": 1}]},
        {
            "name": f"Strix Security Scan owner/repo#1@{'a' * 40}",
            "id": 63,
            "head_sha": "old",
            "pull_requests": [{"number": 1}],
        },
    ]
    monkeypatch.setattr(
        sched, "active_workflow_runs", lambda repo, statuses=("queued", "in_progress"): runs
    )
    pr = {"number": 1, "headRefOid": "head"}

    assert sched.stale_pr_run_ids(
        "owner/repo", pr, workflow="Required OpenCode Review"
    ) == ["61"]
