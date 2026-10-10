"""Noema decides live draft state before provisioning the orchestrator sidecar.

``two_phase.py --prepare-verdict-file`` already skipped a draft pull request at
runtime ("PR is draft; Noema verdict preparation skipped."), but only after the
10-13 minute contextual-orchestrator sidecar provisioning had held a runner
(newsdom-api job 108077744310, .github job 106665379126). These contracts pin
the earlier, equivalent runtime check: it reads the live PR (never the event
snapshot, because ruleset-launched runs in other repositories do not receive
``ready_for_review``), fails open to today's full review path, and gates every
model-heavy step so a draft run still concludes successfully without a verdict.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

from tests.test_required_workflow_queue_contract import workflow_step, workflow_text

DRAFT_STEP = "Check live pull request draft state before sidecar provisioning"
DRAFT_GATE = "steps.live_draft.outputs.live_draft != 'true'"
EXPECTED_UPLOAD_CONDITION = (
    "always() && env.PR_NUMBER != '' && " + DRAFT_GATE
    + " && (steps.noema_sidecar.outcome == 'success'"
    + " || steps.noema_sidecar.outcome == 'failure'"
    + " || steps.noema_sidecar.outcome == 'cancelled')"
)
REVIEWER_TOKEN = (
    "GH_TOKEN: ${{ env.TARGET_REPOSITORY == 'ContextualWisdomLab/k-csap-skills' && "
    "steps.noema_github_app_token.outputs.token || (env.TARGET_REPOSITORY != "
    "'ContextualWisdomLab/k-csap-skills' && (secrets.NOEMA_REVIEW_TOKEN || "
    "steps.noema_github_app_token.outputs.token || steps.noema_oidc_token.outputs.token)) || '' }}"
)
GATED_MODEL_STEPS = (
    "Provision pinned Node.js for Noema document review",
    "Set up lock-compatible sidecar Python",
    "Admit existing personal LiteLLM auto route",
    "Provision contextual-orchestrator review sidecar",
    "Provision local reviewed HWP document reader",
    "Prepare Noema model verdict",
)


def _noema_job() -> str:
    """Return the ``noema-review`` job body only."""
    return workflow_text("noema-review.yml").split("\n  noema-review:\n", 1)[1]


def _step_index(job: str, name: str) -> int:
    """Return the offset of one exact step header inside the job body."""
    return job.index(f"      - name: {name}\n")


def _parsed_noema_job(workflow: str) -> dict:
    """Read the actual YAML job, retaining GitHub's literal ``on`` key."""
    return yaml.load(workflow, Loader=yaml.BaseLoader)["jobs"]["noema-review"]


def _sidecar_upload_is_fail_closed(workflow: str) -> bool:
    """Bind the exact gate to one case-normalized action, never a display-name decoy."""
    uploads = [
        step for step in _parsed_noema_job(workflow)["steps"]
        if str(step.get("uses", "")).casefold().startswith("actions/upload-artifact@")
    ]
    if len(uploads) != 1:
        return False
    upload = uploads[0]
    return (
        upload.get("name") == "Upload contextual-orchestrator sidecar evidence"
        and upload.get("if") == EXPECTED_UPLOAD_CONDITION
        and upload.get("with", {}).get("name") == "noema-sidecar-evidence"
        and "continue-on-error" not in upload
    )


def _noema_review_job_is_fail_closed(workflow: str) -> bool:
    """The review job itself must propagate upload and producer failures."""
    return "continue-on-error" not in _parsed_noema_job(workflow)


def _upload_admitted(workflow: str, pr: str, draft: str, outcome: str) -> bool:
    """Evaluate the actual condition's bounded grammar; unknown expressions fail."""
    uploads = [
        step for step in _parsed_noema_job(workflow)["steps"]
        if str(step.get("uses", "")).casefold().startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1
    terms = {
        "always()": True,
        "env.PR_NUMBER != ''": bool(pr),
        DRAFT_GATE: draft != "true",
        "steps.noema_sidecar.outcome == 'success'": outcome == "success",
        "steps.noema_sidecar.outcome == 'failure'": outcome == "failure",
        "steps.noema_sidecar.outcome == 'cancelled'": outcome == "cancelled",
    }
    values = []
    for part in uploads[0]["if"].split(" && "):
        if part.startswith("(") and part.endswith(")"):
            alternatives = part[1:-1].split(" || ")
            assert all(term in terms for term in alternatives), part
            values.append(any(terms[term] for term in alternatives))
        else:
            assert part in terms, part
            values.append(terms[part])
    return all(values)


@pytest.mark.parametrize("pr", ["", "2565"])
@pytest.mark.parametrize("draft", ["true", "false", ""])
@pytest.mark.parametrize("outcome", ["", "skipped", "unknown", "success", "failure", "cancelled"])
def test_upload_admission_requires_current_terminal_producer(pr: str, draft: str, outcome: str) -> None:
    """Absent/skipped producers cannot publish stale files; terminal diagnostics survive."""
    admitted = _upload_admitted(workflow_text("noema-review.yml"), pr, draft, outcome)
    assert admitted == (
        bool(pr) and draft != "true" and outcome in {"success", "failure", "cancelled"}
    ), (pr, draft, outcome)


def test_upload_action_identity_oracle_rejects_decoys_and_failure_bypasses() -> None:
    """Keep the owner's unique casefold oracle and quoted/spaced failure controls."""
    workflow = workflow_text("noema-review.yml")
    assert _sidecar_upload_is_fail_closed(workflow)
    assert _noema_review_job_is_fail_closed(workflow)
    assert not _sidecar_upload_is_fail_closed(
        workflow.replace(EXPECTED_UPLOAD_CONDITION, EXPECTED_UPLOAD_CONDITION + " || true", 1)
    )
    marker = "      - name: Upload contextual-orchestrator sidecar evidence\n"
    for bypass in ("continue-on-error: true", '"continue-on-error": true', "continue-on-error : true"):
        assert not _sidecar_upload_is_fail_closed(
            workflow.replace(marker, marker + "        " + bypass + "\n", 1)
        ), bypass
        assert not _noema_review_job_is_fail_closed(
            workflow.replace("  noema-review:\n", "  noema-review:\n    " + bypass + "\n", 1)
        ), bypass
    run_decoy = marker + f"        if: {EXPECTED_UPLOAD_CONDITION}\n        run: 'true'\n\n"
    assert _sidecar_upload_is_fail_closed(workflow.replace(marker, run_decoy + marker, 1))
    assert not _sidecar_upload_is_fail_closed(
        workflow.replace(marker, run_decoy + marker + "        continue-on-error: true\n", 1)
    )
    action = next(
        step["uses"] for step in _parsed_noema_job(workflow)["steps"]
        if str(step.get("uses", "")).casefold().startswith("actions/upload-artifact@")
    )
    mixed_case = workflow.replace(
        f"uses: {action}", f"uses: Actions/Upload-Artifact@{action.split('@', 1)[1]}", 1
    )
    assert mixed_case != workflow
    assert _sidecar_upload_is_fail_closed(mixed_case)
    action_decoy = (
        marker + f"        if: {EXPECTED_UPLOAD_CONDITION}\n        uses: {action}\n"
        + "        with:\n          name: noema-sidecar-evidence\n          path: CHANGELOG.md\n\n"
    )
    assert not _sidecar_upload_is_fail_closed(mixed_case.replace(marker, action_decoy + marker, 1))
    assert not _sidecar_upload_is_fail_closed(mixed_case.replace(
        marker, action_decoy + marker + "        continue-on-error: true\n", 1
    ))
    assert _noema_review_job_is_fail_closed(workflow.replace(
        "  continue-noema-transport:\n", "  continue-noema-transport:\n    continue-on-error: true\n", 1
    ))


def test_live_draft_check_runs_after_head_validation_and_before_sidecar() -> None:
    """The draft decision sits between live-head validation and model provisioning."""
    job = _noema_job()
    order = [
        "Validate current pull request head",
        "Resolve Noema target repository visibility",
        DRAFT_STEP,
        *GATED_MODEL_STEPS,
    ]
    offsets = [_step_index(job, name) for name in order]
    assert offsets == sorted(offsets), order
    assert job.count(f"      - name: {DRAFT_STEP}\n") == 1


def test_live_draft_step_reads_the_live_pull_request_with_the_reviewer_token() -> None:
    """Reuse the Validate step's live REST lookup and token instead of the event payload."""
    workflow = workflow_text("noema-review.yml")
    step = workflow_step(workflow, DRAFT_STEP)
    validate = workflow_step(workflow, "Validate current pull request head")

    assert "if: env.PR_NUMBER != ''" in step
    assert "id: live_draft" in step
    assert REVIEWER_TOKEN in step
    assert REVIEWER_TOKEN in validate
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in step
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in validate
    assert "jq -e -s" in step
    assert "set -uo pipefail" not in step
    assert "set -euo pipefail" in step
    # Ruleset-launched runs never see ready_for_review, so neither this check
    # nor any trigger-level filter may trust the event's draft snapshot.
    assert "github.event.pull_request.draft" not in workflow


def test_model_heavy_steps_are_gated_on_the_live_draft_output() -> None:
    """Sidecar, HWP reader, and verdict preparation are all skipped for a live draft."""
    workflow = workflow_text("noema-review.yml")
    for name in GATED_MODEL_STEPS:
        step = workflow_step(workflow, name)
        expected = f"env.PR_NUMBER != '' && {DRAFT_GATE}"
        if name == "Provision contextual-orchestrator review sidecar":
            expected += " && steps.personal_route.outputs.selected != 'true'"
        condition = next(line.strip()[4:] for line in step.splitlines()
                         if line.strip().startswith("if: "))
        assert condition == expected, name
        # Evaluate every supported conjunction, so draft=true denies both routes;
        # additional OR terms or omitted guards fail the exact contract above.
        for pr in ("", "2565"):
            for draft in ("true", "false", ""):
                for personal in ("true", "false", ""):
                    terms = {"env.PR_NUMBER != ''": bool(pr),
                             DRAFT_GATE: draft != "true",
                             "steps.personal_route.outputs.selected != 'true'": personal != "true"}
                    admitted = all(terms[term] for term in condition.split(" && "))
                    wanted = bool(pr) and draft != "true"
                    if name == "Provision contextual-orchestrator review sidecar":
                        wanted = wanted and personal != "true"
                    assert admitted == wanted, (name, pr, draft, personal)


def test_downstream_publication_treats_unset_prepare_outputs_as_skipped() -> None:
    """A skipped prepare step leaves outputs unset, which already means "no publication"."""
    workflow = workflow_text("noema-review.yml")
    for name in (
        "Refresh repository-scoped Noema GitHub App token for publication",
        "Publish prepared Noema verdict on the exact live head",
    ):
        assert "steps.noema_prepare.outputs.prepared == 'true'" in workflow_step(workflow, name)
    continuation = workflow.split("  continue-noema-transport:\n", 1)[1]
    assert "needs.noema-review.result == 'failure'" in continuation
    assert "needs.noema-review.outputs.transport_capacity_unavailable == 'true'" in continuation
    assert "needs.noema-review.outputs.transport_retry_eligible == 'true'" in continuation
    assert _noema_review_job_is_fail_closed(workflow)
    assert _sidecar_upload_is_fail_closed(workflow)


def test_trigger_types_are_unchanged_by_the_runtime_draft_check() -> None:
    """The draft decision stays runtime-only; the trigger surface is not narrowed."""
    workflow = workflow_text("noema-review.yml")
    assert (
        "    types: [opened, synchronize, reopened, ready_for_review, converted_to_draft, closed]\n"
        in workflow
    )


def _run_draft_step(tmp_path: Path, gh_body: str, gh_token: str = "synthetic-token") -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Execute the draft step's bash with a fake ``gh`` and return its outputs."""
    bash_executable = shutil.which("bash") or "/bin/bash"
    script = textwrap.dedent(
        workflow_step(workflow_text("noema-review.yml"), DRAFT_STEP).split("        run: |\n", 1)[1]
    )
    script = script.replace("/tmp/noema-live-draft-error", str(tmp_path / "live-draft-error"))
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(f"#!/usr/bin/env bash\n{gh_body}\n", encoding="utf-8")
    fake_gh.chmod(0o755)
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    result = subprocess.run(  # noqa: S603, S607
        [bash_executable, "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "7",
            "GH_TOKEN": gh_token,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    return result, outputs


def _live_pr(draft: object) -> str:
    """Render a fake ``gh api`` body that prints one live PR JSON object."""
    payload = json.dumps({"state": "open", "draft": draft, "head": {"sha": "a" * 40}})
    return f"printf '%s' '{payload}'"


def test_live_draft_missing_token_fails_closed_before_lookup(tmp_path: Path) -> None:
    """Missing reviewer authority cannot proceed to a live lookup or model setup."""
    marker = tmp_path / "lookup-reached"
    result, outputs = _run_draft_step(tmp_path, f"touch '{marker}'", gh_token="")
    assert result.returncode != 0
    assert outputs == {}
    assert not marker.exists()
    assert "::error::" in result.stdout


def test_live_draft_pr_skips_model_review_with_a_clear_notice(tmp_path: Path) -> None:
    """A live draft sets live_draft=true and explains the skip; the step succeeds."""
    result, outputs = _run_draft_step(tmp_path, _live_pr(True))
    assert result.returncode == 0, result.stderr
    assert outputs == {"live_draft": "true"}
    assert "PR is draft; Noema model review skipped before sidecar provisioning." in result.stdout


def test_live_ready_pr_continues_to_model_review(tmp_path: Path) -> None:
    """A ready PR keeps today's review path."""
    result, outputs = _run_draft_step(tmp_path, _live_pr(False))
    assert result.returncode == 0, result.stderr
    assert outputs == {"live_draft": "false"}
    assert "skipped before sidecar provisioning" not in result.stdout


def test_live_draft_lookup_failure_fails_open(tmp_path: Path) -> None:
    """An API failure is treated as not-draft so review behavior is unchanged."""
    result, outputs = _run_draft_step(tmp_path, "echo 'HTTP 502' >&2\nexit 1")
    assert result.returncode == 0, result.stderr
    assert outputs == {"live_draft": "false"}
    assert "could not read the live pull request draft state" in result.stdout
    assert "HTTP 502" in result.stderr


def test_malformed_or_missing_draft_field_fails_open(tmp_path: Path) -> None:
    """Non-JSON bodies, a missing field, or a non-true value never claim draft."""
    for body in ("printf 'not json'", "printf '{}'", _live_pr("true"), _live_pr(None)):
        result, outputs = _run_draft_step(tmp_path, body)
        assert result.returncode == 0, (body, result.stderr)
        assert outputs == {"live_draft": "false"}, body


def test_valid_draft_prefix_with_trailing_data_continues_review(tmp_path: Path) -> None:
    """Only one completely parsed JSON object can authorize the Draft skip."""
    for payload in ('{"draft":true} trailing-invalid', '{"draft":true}\n42', '{"draft":true}\n{"draft":true}'):
        result, outputs = _run_draft_step(tmp_path, f"printf '%s' '{payload}'")
        assert result.returncode == 0, result.stderr
        assert outputs == {"live_draft": "false"}, payload
        assert "skipped before sidecar provisioning" not in result.stdout
