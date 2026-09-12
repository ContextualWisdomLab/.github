"""Structure and shell-syntax contract for the new codeql-scan-dispatch.yml handler.

ContextualWisdomLab/.github#1772 designs this file as the native
(non-required-workflow) half of the CodeQL dispatch architecture, and
ContextualWisdomLab/.github#1778 wires the required entrypoint to it. This
guards the handler's structure and shell syntax, mirroring the established pattern in
tests/test_opencode_workflow_shell_syntax.py and
tests/test_codeql_pr_workflow_contract.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import audit_central_required_workflows as ruleset_audit
from tests.test_opencode_workflow_shell_syntax import _extract_run_block
from tests.test_required_workflow_queue_contract import (
    workflow_level_cancels_in_progress,
    workflow_level_concurrency_group,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-scan-dispatch.yml"
VALIDATE_STEP_NAME = "Bind workflow inputs to live organization pull request metadata"

RUN_BLOCK_STEP_NAMES = (
    "Exchange OpenCode app token for target repository metadata reads",
    "Bind workflow inputs to live organization pull request metadata",
    "Exchange OpenCode app token for target repository content reads",
    "Re-validate live pull request metadata before privileged scan",
    "Fetch the pinned CodeQL SARIF gate script",
    "Materialize pull request head for CodeQL scan",
    "Publish CodeQL dispatch status",
    "Exchange OpenCode app token for run settlement",
    "Settle exact CodeQL required run",
)


def test_codeql_scan_dispatch_run_blocks_are_valid_bash():
    """Every multi-line run: block in the new handler must be syntactically valid Bash."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    for step_name in RUN_BLOCK_STEP_NAMES:
        script = _extract_run_block(workflow_text, step_name)
        result = subprocess.run(
            [bash, "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{step_name}: {result.stderr}"


def test_codeql_scan_dispatch_workflow_structure():
    """The handler stays required-workflow-independent and reuses the shared SARIF gate."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: CodeQL Scan Dispatch" in workflow
    assert "types: [codeql-scan]" in workflow
    # No workflow_dispatch: test_no_central_workflow_exposes_branch_selected_manual_dispatch
    # (tests/test_required_workflow_queue_contract.py) forbids it on every
    # central workflow because it lets a caller pick an arbitrary ref to run
    # this token-minting, cross-repo-status-publishing workflow from.
    assert "workflow_dispatch:" not in workflow
    assert "validate-dispatch:" in workflow
    assert "  scan:" in workflow
    assert workflow.count("github/codeql-action/init@") == 1
    assert workflow.count("github/codeql-action/analyze@") == 1
    assert "scripts/ci/codeql_sarif_gate.py" in workflow
    assert '-f context="codeql-dispatch/${LANGUAGE}/${BASE_SHA}"' in workflow
    assert "github.event.client_payload.producer_source_sha" in workflow
    assert 'receipt_description="cwl1;h=${HEAD_SHA};w=codeql-scan-dispatch;r=${REQUIRED_RUN_ID};s=${PRODUCER_SOURCE_SHA}"' in workflow
    assert "OPENCODE_REPOSITORY_DISPATCH_ACTOR" in workflow
    # Deliberately NOT vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS: that allowlist
    # scopes a gradual ~12-repo OpenCode review rollout, while ruleset
    # 18156473 covers ~ALL org repos except noema/.github/IRT-bibliography-set
    # -- reusing the narrower list would silently break CodeQL dispatch for
    # every repo not already on the OpenCode rollout list. (The name is
    # mentioned in an explanatory comment, which is fine -- only an actual
    # `vars.` reference would reintroduce the bug.)
    assert "vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS" not in workflow
    # This file must never itself become subject to the required-workflow
    # codeql-action restriction: it must not be a pull_request-triggered file.
    assert "pull_request:" not in workflow
    assert "pull_request_target:" not in workflow


def test_codeql_scan_dispatch_keeps_current_head_language_shards_independent():
    """Sibling languages stay independent as jobs in one run, not as separate runs.

    The 60-job ceiling was one queued handler run per language. Putting
    ``required_language`` in the concurrency group was the 2026-09-05
    workaround after contextual-orchestrator#1049 / run 33938784437 cancelled
    sibling scans. Independence now comes from ``strategy.fail-fast: false``
    on this run's language matrix, so the group can be
    ``{workflow}-{repository}-{PR}`` and ``cancel-in-progress: true`` only
    drops a superseded HEAD of the same pull request.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    group_value = workflow_level_concurrency_group(workflow)
    header = workflow.split("\non:", 1)[0]
    scan = workflow.split("  scan:\n", 1)[1]
    strategy = scan.split("    strategy:\n", 1)[1].split("    steps:\n", 1)[0]

    assert "github.event.client_payload.target_repository" in group_value
    assert "github.event.client_payload.pr_number" in group_value
    assert "github.event.client_payload.required_language" not in group_value
    assert "unknown-language" not in group_value
    assert "required_language" not in header
    assert "fail-fast: false" in strategy
    assert "include: ${{ fromJSON(needs.validate-dispatch.outputs.matrix) }}" in strategy
    assert workflow_level_cancels_in_progress(workflow)


def _run_validate_step(tmp_path: Path, env_overrides: dict[str, str], pull_request: dict) -> subprocess.CompletedProcess[str]:
    """Execute the real validate-dispatch shell block against a fake `gh api`."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _extract_run_block(workflow_text, VALIDATE_STEP_NAME)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'endpoint="${!#}"\n'
        'case "$endpoint" in\n'
        '  repos/ContextualWisdomLab/.github/compare/*) printf \'%s\\n\' "$FAKE_SOURCE_COMPARE_JSON" ;;\n'
        '  repos/ContextualWisdomLab/*/git/commits/*) printf \'%s\\n\' "$FAKE_PRODUCER_COMMIT_JSON" ;;\n'
        '  *) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    output = tmp_path / "github-output"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull_request),
        "FAKE_SOURCE_COMPARE_JSON": "{}",
        "FAKE_PRODUCER_COMMIT_JSON": json.dumps(
            {
                "sha": "c" * 40,
                "parents": [{"sha": "a" * 40}, {"sha": "b" * 40}],
            }
        ),
        "GITHUB_OUTPUT": str(output),
        "DISPATCH_ACTOR": "seonghobae",
        "DISPATCH_SENDER": "seonghobae",
        "ALLOWED_DISPATCH_ACTOR": "seonghobae",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "SUPPLIED_BASE_REF": "main",
        "SUPPLIED_BASE_SHA": "a" * 40,
        "SUPPLIED_HEAD_ENVELOPE": "null",
        "SUPPLIED_HEAD_SCHEMA": "",
        "SUPPLIED_HEAD_REF": "feature",
        "SUPPLIED_HEAD_SHA": "b" * 40,
        "SUPPLIED_LEGACY_HEAD_REF": "feature",
        "SUPPLIED_LEGACY_HEAD_SHA": "b" * 40,
        "SUPPLIED_PRODUCER_SOURCE_SHA": "c" * 40,
        "SUPPLIED_MATRIX": json.dumps([{"language": "python", "build-mode": "none"}]),
        "SUPPLIED_REQUIRED_RUN_ID": "42",
        "SUPPLIED_REQUIRED_JOBS": json.dumps([{"language": "python", "job_id": 43}]),
        "SUPPLIED_RERUN_MODE": "",
        "SUPPLIED_RERUN_REQUEST": "null",
        "SUPPLIED_REQUIRED_JOB_ID": "",
        "SUPPLIED_REQUIRED_LANGUAGE": "",
        **env_overrides,
    }
    result = subprocess.run([bash], input=script, text=True, capture_output=True, check=False, env=env)
    result.output_path = output  # type: ignore[attr-defined]
    return result


def _matching_pull_request() -> dict:
    """A live PR payload that matches the default supplied metadata in _run_validate_step."""
    return {
        "state": "open",
        "merge_commit_sha": "c" * 40,
        "base": {"repo": {"full_name": "ContextualWisdomLab/naruon"}, "ref": "main", "sha": "a" * 40},
        "head": {"repo": {"full_name": "ContextualWisdomLab/naruon"}, "ref": "feature", "sha": "b" * 40},
    }


def test_codeql_scan_dispatch_validate_step_accepts_matching_live_metadata(tmp_path):
    """A dispatch whose metadata matches the live PR produces the expected GITHUB_OUTPUT."""
    result = _run_validate_step(tmp_path, {}, _matching_pull_request())

    assert result.returncode == 0, result.stderr
    output_text = result.output_path.read_text(encoding="utf-8")
    assert "target_repository=ContextualWisdomLab/naruon" in output_text
    assert "pr_number=42" in output_text
    assert "head_sha=" + "b" * 40 in output_text
    assert '[{"language":"python","build-mode":"none"}]' in output_text
    assert "required_run_id=42" in output_text
    assert "producer_source_sha=" + "c" * 40 in output_text
    assert '"job_id":43' in output_text.replace(" ", "")
    assert "required_job_id=" not in output_text
    assert "required_language=" not in output_text


def test_codeql_scan_dispatch_validate_step_rejects_unknown_head_schema(tmp_path):
    """Unknown nested-head schema versions fail before metadata can be trusted."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_HEAD_ENVELOPE": json.dumps(
                {"schema": "2", "ref": "feature", "sha": "b" * 40}
            ),
            "SUPPLIED_HEAD_SCHEMA": "2",
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "unsupported pr_head schema=2" in result.stdout


def test_codeql_scan_dispatch_validate_step_accepts_versioned_head_envelope(tmp_path):
    """Schema-one nested head metadata reaches the live validation success path."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_HEAD_ENVELOPE": json.dumps(
                {"schema": "1", "ref": "feature", "sha": "b" * 40}
            ),
            "SUPPLIED_HEAD_SCHEMA": "1",
            "SUPPLIED_HEAD_REF": "feature",
            "SUPPLIED_HEAD_SHA": "b" * 40,
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0
    assert (
        "Validated current live metadata for ContextualWisdomLab/naruon#42: base=main/"
        in result.stdout
    )
    assert "head=feature/" in result.stdout


@pytest.mark.parametrize(
    ("legacy_ref", "legacy_sha"),
    [
        ("feature-wrong", "b" * 40),
        ("feature", "c" * 40),
        ("feature", ""),
        ("", "b" * 40),
    ],
)
def test_codeql_scan_dispatch_validate_step_rejects_conflicting_dual_head_identity(
    tmp_path, legacy_ref, legacy_sha
):
    """Nested identity cannot shadow an unequal or partial legacy representation."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_HEAD_ENVELOPE": json.dumps(
                {"schema": "1", "ref": "feature", "sha": "b" * 40}
            ),
            "SUPPLIED_HEAD_SCHEMA": "1",
            "SUPPLIED_HEAD_REF": "feature",
            "SUPPLIED_HEAD_SHA": "b" * 40,
            "SUPPLIED_LEGACY_HEAD_REF": legacy_ref,
            "SUPPLIED_LEGACY_HEAD_SHA": legacy_sha,
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "conflicting nested and legacy pr_head identity" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_numeric_head_schema(tmp_path):
    """The JSON envelope schema stays a version string, not a numeric alias."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_HEAD_ENVELOPE": json.dumps(
                {"schema": 1, "ref": "feature", "sha": "b" * 40}
            ),
            "SUPPLIED_HEAD_SCHEMA": "1",
            "SUPPLIED_HEAD_REF": "feature",
            "SUPPLIED_HEAD_SHA": "b" * 40,
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "invalid pr_head envelope" in result.stdout


@pytest.mark.parametrize("missing_field", ["ref", "sha"])
def test_codeql_scan_dispatch_validate_step_rejects_incomplete_head_envelope(
    tmp_path, missing_field
):
    """A present envelope cannot borrow a required value from legacy fields."""
    envelope = {"schema": "1", "ref": "feature", "sha": "b" * 40}
    del envelope[missing_field]
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_HEAD_ENVELOPE": json.dumps(envelope),
            "SUPPLIED_HEAD_SCHEMA": "1",
            "SUPPLIED_LEGACY_HEAD_REF": "feature",
            "SUPPLIED_LEGACY_HEAD_SHA": "b" * 40,
            "SUPPLIED_HEAD_REF": "feature",
            "SUPPLIED_HEAD_SHA": "b" * 40,
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "invalid pr_head envelope" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_unversioned_head_envelope(tmp_path):
    """A nested head tuple without its schema version fails closed."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_HEAD_ENVELOPE": json.dumps({"ref": "feature", "sha": "b" * 40}),
            "SUPPLIED_HEAD_SCHEMA": "",
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "unsupported pr_head schema=<missing>" in result.stdout


def test_codeql_scan_dispatch_validate_step_accepts_nested_rerun_request(tmp_path):
    """The bounded ten-key producer envelope normalizes mode and job identities."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_REQUIRED_JOBS": "null",
            "SUPPLIED_RERUN_REQUEST": json.dumps(
                {
                    "mode": "failed",
                    "required_jobs": [{"language": "python", "job_id": 43}],
                }
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr
    output_text = result.output_path.read_text(encoding="utf-8")
    assert "rerun_mode=failed" in output_text
    assert '"job_id":43' in output_text.replace(" ", "")


def test_codeql_scan_dispatch_validate_step_binds_producer_revision(tmp_path):
    """Only the exact live base/head merge revision can invoke the handler."""
    missing = _run_validate_step(
        tmp_path / "missing",
        {"SUPPLIED_PRODUCER_SOURCE_SHA": ""},
        _matching_pull_request(),
    )
    wrong_revision = _run_validate_step(
        tmp_path / "wrong-revision",
        {
            "SUPPLIED_PRODUCER_SOURCE_SHA": "d" * 40,
            "FAKE_PRODUCER_COMMIT_JSON": json.dumps(
                {
                    "sha": "d" * 40,
                    "parents": [{"sha": "a" * 40}, {"sha": "b" * 40}],
                }
            ),
        },
        _matching_pull_request(),
    )
    wrong_parents = _run_validate_step(
        tmp_path / "wrong-parents",
        {
            "FAKE_PRODUCER_COMMIT_JSON": json.dumps(
                {
                    "sha": "c" * 40,
                    "parents": [{"sha": "f" * 40}, {"sha": "b" * 40}],
                }
            ),
        },
        _matching_pull_request(),
    )

    assert missing.returncode == 1
    assert wrong_revision.returncode == 1
    assert wrong_parents.returncode == 1
    assert "producer source" in missing.stdout.lower()
    assert "producer revision" in wrong_revision.stdout.lower()
    assert "producer revision" in wrong_parents.stdout.lower()


def test_codeql_scan_dispatch_accepts_exact_pull_request_merge_revision(tmp_path):
    """Bind the producer revision to the live PR base/head merge, not handler ancestry."""
    merge_sha = "e" * 40
    pull_request = _matching_pull_request()
    pull_request["merge_commit_sha"] = merge_sha
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_PRODUCER_SOURCE_SHA": merge_sha,
            "FAKE_SOURCE_COMPARE_JSON": json.dumps(
                {
                    "status": "diverged",
                    "behind_by": 1,
                    "base_commit": {"sha": "f" * 40},
                    "merge_base_commit": {"sha": "f" * 40},
                }
            ),
            "FAKE_PRODUCER_COMMIT_JSON": json.dumps(
                {
                    "sha": merge_sha,
                    "parents": [
                        {"sha": "a" * 40},
                        {"sha": "b" * 40},
                    ],
                }
            ),
        },
        pull_request,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_codeql_scan_dispatch_validate_step_accepts_legacy_rerun_mode(tmp_path):
    """An already queued top-level mode retains whole-attempt semantics."""
    result = _run_validate_step(
        tmp_path,
        {"SUPPLIED_RERUN_MODE": "all"},
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr
    assert "rerun_mode=all" in result.output_path.read_text(encoding="utf-8")


def test_codeql_scan_dispatch_validate_step_rejects_conflicting_rerun_envelopes(
    tmp_path,
):
    """A caller cannot supply both legacy and nested rerun authority."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_RERUN_REQUEST": json.dumps(
                {
                    "mode": "failed",
                    "required_jobs": [{"language": "python", "job_id": 43}],
                }
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "conflicting legacy and nested rerun envelopes" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_unknown_rerun_mode(tmp_path):
    """Only the two run-wide GitHub rerun operations are accepted."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_REQUIRED_JOBS": "null",
            "SUPPLIED_RERUN_REQUEST": json.dumps(
                {
                    "mode": "one-job",
                    "required_jobs": [{"language": "python", "job_id": 43}],
                }
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "rerun mode" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_duplicate_job_id(tmp_path):
    """Two language labels cannot authorize mutation of the same required job."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "actions", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps(
                [
                    {"language": "python", "job_id": 43},
                    {"language": "actions", "job_id": 43},
                ]
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "wake identity is missing" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_actor_mismatch(tmp_path):
    """A dispatch from an unauthorized actor is rejected before any live PR read."""
    result = _run_validate_step(tmp_path, {"DISPATCH_ACTOR": "someone-else"}, _matching_pull_request())

    assert result.returncode == 1
    assert "authorization rejected actor=" in result.stdout


def test_codeql_scan_dispatch_validate_step_accepts_any_listed_dispatcher(tmp_path):
    """ALLOWED_DISPATCH_ACTOR is a comma-separated allowlist shared by all three
    dispatch consumers; each listed identity passes when actor and sender both
    equal it, an unlisted one is rejected, and actor/sender that are two
    *different* listed identities are still rejected."""
    # _run_validate_step creates tmp_path/bin, so each invocation needs its
    # own directory.
    allowlist = "github-actions[bot], opencode-agent[bot]"
    for identity in ("github-actions[bot]", "opencode-agent[bot]"):
        result = _run_validate_step(
            tmp_path / identity.replace("[", "").replace("]", ""),
            {
                "ALLOWED_DISPATCH_ACTOR": allowlist,
                "DISPATCH_ACTOR": identity,
                "DISPATCH_SENDER": identity,
            },
            _matching_pull_request(),
        )
        assert result.returncode == 0, result.stderr
        assert f"Authorized repository_dispatch actor={identity}" in result.stdout

    unlisted = _run_validate_step(
        tmp_path / "unlisted",
        {
            "ALLOWED_DISPATCH_ACTOR": allowlist,
            "DISPATCH_ACTOR": "seonghobae",
            "DISPATCH_SENDER": "seonghobae",
        },
        _matching_pull_request(),
    )
    assert unlisted.returncode == 1
    assert "authorization rejected actor=seonghobae" in unlisted.stdout

    mismatched = _run_validate_step(
        tmp_path / "mismatched",
        {
            "ALLOWED_DISPATCH_ACTOR": allowlist,
            "DISPATCH_ACTOR": "opencode-agent[bot]",
            "DISPATCH_SENDER": "github-actions[bot]",
        },
        _matching_pull_request(),
    )
    assert mismatched.returncode == 1
    assert "authorization rejected actor=opencode-agent[bot]" in mismatched.stdout


def test_codeql_scan_dispatch_validate_step_accepts_any_org_repository(tmp_path):
    """Unlike opencode-review-dispatch.yml, any ContextualWisdomLab repo is accepted.

    CodeQL is meant to run for ~ALL org repos (ruleset 18156473's scope), not
    the curated ~12-repo OpenCode review rollout list -- a repo that would be
    rejected by that other allowlist must still be accepted here.
    """
    not_on_opencode_rollout_list = "ContextualWisdomLab/some-other-repo"
    pull_request = _matching_pull_request()
    pull_request["base"]["repo"]["full_name"] = not_on_opencode_rollout_list
    pull_request["head"]["repo"]["full_name"] = not_on_opencode_rollout_list

    result = _run_validate_step(
        tmp_path,
        {"TARGET_REPOSITORY": not_on_opencode_rollout_list},
        pull_request,
    )

    assert result.returncode == 0, result.stderr
    assert f"target_repository={not_on_opencode_rollout_list}" in result.output_path.read_text(encoding="utf-8")


def test_codeql_scan_dispatch_validate_step_rejects_non_org_target(tmp_path):
    """A dispatch targeting a repository outside ContextualWisdomLab is rejected."""
    result = _run_validate_step(
        tmp_path,
        {"TARGET_REPOSITORY": "some-other-org/repo"},
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "target outside ContextualWisdomLab" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_malformed_matrix(tmp_path):
    """Empty, invalid, or job-map-mismatched matrices fail closed; a multi-language payload is valid."""
    missing_build_mode = _run_validate_step(
        tmp_path / "missing-build-mode",
        {"SUPPLIED_MATRIX": json.dumps([{"language": "python"}])},
        _matching_pull_request(),
    )
    empty_matrix = _run_validate_step(
        tmp_path / "empty",
        {
            "SUPPLIED_MATRIX": "[]",
            "SUPPLIED_REQUIRED_JOBS": "[]",
        },
        _matching_pull_request(),
    )
    invalid_language = _run_validate_step(
        tmp_path / "invalid-language",
        {
            "SUPPLIED_MATRIX": json.dumps([{"language": "PYTHON", "build-mode": "none"}]),
            "SUPPLIED_REQUIRED_JOBS": json.dumps([{"language": "PYTHON", "job_id": 43}]),
        },
        _matching_pull_request(),
    )
    mismatched_jobs = _run_validate_step(
        tmp_path / "mismatched-jobs",
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "actions", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps([{"language": "python", "job_id": 43}]),
        },
        _matching_pull_request(),
    )

    assert missing_build_mode.returncode == 1
    assert empty_matrix.returncode == 1
    assert invalid_language.returncode == 1
    assert mismatched_jobs.returncode == 1
    assert "at least one valid language/build-mode shard" in missing_build_mode.stdout
    assert "at least one valid language/build-mode shard" in empty_matrix.stdout
    assert "at least one valid language/build-mode shard" in invalid_language.stdout
    assert "does not match the dispatched languages one-to-one" in mismatched_jobs.stdout


def test_codeql_scan_dispatch_validate_step_accepts_multi_language_payload(tmp_path):
    """One dispatch may carry every remaining language for the current head."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "javascript-typescript", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps(
                [
                    {"language": "javascript-typescript", "job_id": "55"},
                    {"language": "python", "job_id": 43},
                ]
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    output_text = result.output_path.read_text(encoding="utf-8")
    assert "javascript-typescript" in output_text
    assert '"job_id":55' in output_text.replace(" ", "")
    assert '"job_id":43' in output_text.replace(" ", "")


def test_codeql_scan_dispatch_validate_step_rejects_unproven_matrix_subset(tmp_path):
    """A partial scan cannot authorize waking an unscanned required language."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_MATRIX": json.dumps(
                [{"language": "actions", "build-mode": "none"}]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps(
                [
                    {"language": "python", "job_id": 43},
                    {"language": "actions", "job_id": 44},
                ]
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "does not match the dispatched languages one-to-one" in result.stdout


def test_codeql_scan_dispatch_validate_step_accepts_legacy_single_language_payload(tmp_path):
    """A queued pre-cutover payload still validates after required_jobs became mandatory.

    repository_dispatch always runs the default-branch file. Payloads that
    lined up before #2008 carry required_language + required_job_id and a
    one-shard matrix, with required_jobs absent (JSON null) or empty. Those
    fields synthesize required_jobs=[{language, job_id}] and must be accepted.
    """
    for empty_jobs, case_name in (("null", "missing"), ("[]", "empty-array")):
        result = _run_validate_step(
            tmp_path / case_name,
            {
                "SUPPLIED_REQUIRED_JOBS": empty_jobs,
                "SUPPLIED_REQUIRED_LANGUAGE": "python",
                "SUPPLIED_REQUIRED_JOB_ID": "43",
            },
            _matching_pull_request(),
        )

        assert result.returncode == 0, result.stderr + result.stdout
        output_text = result.output_path.read_text(encoding="utf-8")
        compact = output_text.replace(" ", "")
        assert '"language":"python"' in compact
        assert '"job_id":43' in compact
        assert "required_job_id=" not in output_text
        assert "required_language=" not in output_text


def test_codeql_scan_dispatch_validate_step_ignores_legacy_fields_when_required_jobs_present(
    tmp_path,
):
    """A current required_jobs array wins; leftover scalar fields are ignored."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "javascript-typescript", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps(
                [
                    {"language": "javascript-typescript", "job_id": "55"},
                    {"language": "python", "job_id": 43},
                ]
            ),
            "SUPPLIED_REQUIRED_LANGUAGE": "actions",
            "SUPPLIED_REQUIRED_JOB_ID": "999",
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    compact = result.output_path.read_text(encoding="utf-8").replace(" ", "")
    assert '"job_id":55' in compact
    assert '"job_id":43' in compact
    assert '"job_id":999' not in compact
    assert "actions" not in compact


def test_codeql_scan_dispatch_validate_step_rejects_unusable_legacy_payload(tmp_path):
    """Empty required_jobs still fail closed when the scalar identity cannot be synthesized."""
    missing_both = _run_validate_step(
        tmp_path / "missing-both",
        {"SUPPLIED_REQUIRED_JOBS": "null"},
        _matching_pull_request(),
    )
    language_mismatch = _run_validate_step(
        tmp_path / "language-mismatch",
        {
            "SUPPLIED_REQUIRED_JOBS": "[]",
            "SUPPLIED_REQUIRED_LANGUAGE": "javascript-typescript",
            "SUPPLIED_REQUIRED_JOB_ID": "43",
        },
        _matching_pull_request(),
    )
    multi_language_legacy = _run_validate_step(
        tmp_path / "multi-language-legacy",
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "javascript-typescript", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": "null",
            "SUPPLIED_REQUIRED_LANGUAGE": "python",
            "SUPPLIED_REQUIRED_JOB_ID": "43",
        },
        _matching_pull_request(),
    )
    invalid_job_id = _run_validate_step(
        tmp_path / "invalid-job-id",
        {
            "SUPPLIED_REQUIRED_JOBS": "null",
            "SUPPLIED_REQUIRED_LANGUAGE": "python",
            "SUPPLIED_REQUIRED_JOB_ID": "0",
        },
        _matching_pull_request(),
    )

    assert missing_both.returncode == 1
    assert language_mismatch.returncode == 1
    assert multi_language_legacy.returncode == 1
    assert invalid_job_id.returncode == 1
    assert "does not match the dispatched languages one-to-one" in missing_both.stdout
    assert "does not match the dispatched languages one-to-one" in language_mismatch.stdout
    assert "does not match the dispatched languages one-to-one" in multi_language_legacy.stdout
    assert "does not match the dispatched languages one-to-one" in invalid_job_id.stdout


def test_codeql_scan_dispatch_validate_step_rejects_stale_head_sha(tmp_path):
    """A dispatch whose supplied head SHA no longer matches the live PR head is rejected."""
    stale_pull_request = _matching_pull_request()
    stale_pull_request["head"]["sha"] = "c" * 40

    result = _run_validate_step(tmp_path, {}, stale_pull_request)

    assert result.returncode == 1
    assert "does not match the live pull request: head_sha" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_closed_pull_request(tmp_path):
    """A dispatch targeting a pull request that closed before this run started is rejected."""
    closed_pull_request = _matching_pull_request()
    closed_pull_request["state"] = "closed"

    result = _run_validate_step(tmp_path, {}, closed_pull_request)

    assert result.returncode == 1
    assert "rejected closed, missing, cross-fork, or malformed live metadata" in result.stdout


def test_codeql_scan_dispatch_is_not_in_the_required_workflow_ruleset_scope():
    """Guard against accidentally wiring this handler in as its own required workflow.

    It must stay reachable only via repository_dispatch -- admitting it
    through the ruleset would immediately hit the same codeql-action
    admission restriction documented in
    docs/doctoring/codeql-pr-required-workflow-always-fails.md.
    """
    required_paths = set(ruleset_audit.REQUIRED_WORKFLOW_PATHS)

    assert ".github/workflows/codeql-pr.yml" in required_paths
    assert ".github/workflows/codeql-scan-dispatch.yml" not in required_paths


def test_codeql_scan_dispatch_run_name_binds_base_and_required_run() -> None:
    """Public run identity includes base SHA and required run id without changing concurrency.

    The required shard cannot read client_payload. Encoding those fields in
    run-name lets it reject a same-head retarget or a different waiting
    required run. The #2008/#2009 group stays repository+PR so a newer HEAD
    of the same pull request still cancels its predecessor.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    header = workflow.split("\non:", 1)[0]
    group_value = workflow_level_concurrency_group(workflow)

    assert "github.event.client_payload.pr_head_sha" in header
    assert "github.event.client_payload.pr_base_sha" in header
    assert "github.event.client_payload.required_run_id" in header
    assert "github.event.client_payload.pr_base_sha" not in group_value
    assert "github.event.client_payload.required_run_id" not in group_value
    assert "github.event.client_payload.target_repository" in group_value
    assert "github.event.client_payload.pr_number" in group_value


def test_dispatch_publish_keeps_successful_scan_when_status_write_is_denied() -> None:
    """A clean SARIF gate must not fail the handler solely because POST /statuses 403s.

    opencode-agent is installed with statuses:read. Cross-repo github.token cannot
    write naruon commit statuses. The completed scan job is the remaining evidence.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    publish = workflow.split("      - name: Publish CodeQL dispatch status\n", 1)[1].split(
        "\n\n  settle-required-run:\n", 1
    )[0]

    assert "GATE_OUTCOME" in publish
    assert 'if [ "$GATE_OUTCOME" = "success" ]; then' in publish
    assert "exact completed scan and preserved SARIF artifact remain" in publish
    assert "continue-on-error:" not in publish
    assert "cancel-in-progress: true" not in publish


def test_dispatch_publish_rejects_superseded_metadata_and_legacy_context() -> None:
    """A stale handler cannot poison HEAD or publish an unbound legacy status.

    Run 34235814716 proved that a scan can become superseded after initial
    validation but before publication.  #1902's evidence-complete producer is
    integrated into the same successor, so publication requires successful
    live-metadata revalidation and emits only the base-bound receipt.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    revalidate = workflow.split(
        "      - name: Re-validate live pull request metadata before privileged scan\n",
        1,
    )[1].split("      - name: Fetch the pinned CodeQL SARIF gate script\n", 1)[0]
    publish = workflow.split("      - name: Publish CodeQL dispatch status\n", 1)[1].split(
        "\n\n  settle-required-run:\n", 1
    )[0]

    assert "        id: live_metadata\n" in revalidate
    assert "if: always() && steps.live_metadata.outcome == 'success'" in publish
    assert '-f context="codeql-dispatch/${LANGUAGE}/${BASE_SHA}"' in publish
    assert '-f context="codeql-dispatch/${LANGUAGE}"' not in publish
    assert "SARIF_UPLOAD_OUTCOME: ${{ steps.sarif_upload.outcome }}" in publish
    assert 'if [ "${SARIF_UPLOAD_OUTCOME:-}" != "success" ]; then' in publish
    assert 'actual_creator="$(jq -r' in publish
    assert "unexpected creator" in publish


def test_dispatch_settles_all_languages_with_one_run_wide_mutation() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    settlement = workflow.split("  settle-required-run:\n", 1)[1]

    assert "needs: [validate-dispatch, scan]" in settlement
    assert "always()" in settlement.split("    runs-on:", 1)[0]
    assert "actions: write" in settlement.split("    steps:\n", 1)[0]
    assert 'github_api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in settlement
    assert 'github_api "repos/${TARGET_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}"' in settlement
    assert 'github_api --paginate --slurp "repos/${TARGET_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}/jobs?per_page=100"' in settlement
    assert "rerun-failed-jobs" in settlement
    assert '"rerun"' in settlement
    assert "actions/jobs/${REQUIRED_JOB_ID}/rerun" not in workflow
    assert "sleep " not in settlement


def test_dispatch_settlement_has_only_trusted_actions_write_boundary() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    scan = workflow.split("  scan:\n", 1)[1]
    scan_permissions = scan.split("    strategy:\n", 1)[0]
    settlement = workflow.split("  settle-required-run:\n", 1)[1]
    settlement_permissions = settlement.split("    steps:\n", 1)[0]

    assert "actions: write" not in scan_permissions
    assert "actions: read" in scan_permissions
    assert "actions: write" in settlement_permissions
    assert "pull_request:" not in workflow
    assert "pull_request_target:" not in workflow
    assert "needs.validate-dispatch.outputs.required_run_id" in settlement
    assert "needs.validate-dispatch.outputs.required_jobs" in settlement
    assert "github.event.client_payload.required_job_id" not in scan


def _run_settlement_step(
    tmp_path: Path,
    *,
    pull: dict | None = None,
    run: dict | None = None,
    required_jobs: list[dict] | None = None,
    handler_jobs: list[dict] | None = None,
    handler_artifacts: list[dict] | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Execute the run-wide settlement block against fixture-backed API responses."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    head_sha = "b" * 40
    pull = pull or {
        "state": "open",
        "base": {
            "repo": {"full_name": "ContextualWisdomLab/naruon"},
            "ref": "main",
            "sha": "a" * 40,
        },
        "head": {
            "repo": {"full_name": "ContextualWisdomLab/naruon"},
            "ref": "feature",
            "sha": head_sha,
        },
    }
    run = run or {
        "id": 42,
        "event": "pull_request",
        "path": ".github/workflows/codeql-pr.yml",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "failure",
    }
    required_jobs = required_jobs or [
        {
            "id": 43,
            "run_id": 42,
            "head_sha": head_sha,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed",
            "conclusion": "failure",
        },
        {
            "id": 44,
            "run_id": 42,
            "head_sha": head_sha,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "completed",
            "conclusion": "failure",
        },
    ]
    handler_jobs = handler_jobs or [
        {
            "name": "CodeQL dispatch scan (python)",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "steps": [
                {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
            ],
        },
        {
            "name": "CodeQL dispatch scan (actions)",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "steps": [
                {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
            ],
        },
    ]
    handler_artifacts = handler_artifacts or [
        {
            "name": "codeql-dispatch-python-100-1",
            "expired": False,
            "size_in_bytes": 10,
        },
        {
            "name": "codeql-dispatch-actions-100-1",
            "expired": False,
            "size_in_bytes": 10,
        },
    ]
    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), "Settle exact CodeQL required run"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    post_log = tmp_path / "posts"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'endpoint="${!#}"\n'
        'if printf \'%s\\n\' "$@" | grep -qx POST; then\n'
        '  printf \'%s\\n\' "$endpoint" >>"$FAKE_POST_LOG"\n'
        '  if [ -n "${FAKE_WAKE_POST_FAIL_TOKEN:-}" ] && '
        '[ "${GH_TOKEN:-}" = "$FAKE_WAKE_POST_FAIL_TOKEN" ]; then\n'
        "    exit 1\n"
        "  fi\n"
        '  if [ -n "${FAKE_DENIED_TOKEN:-}" ] && '
        '[ "${GH_TOKEN:-}" = "$FAKE_DENIED_TOKEN" ]; then\n'
        "    exit 1\n"
        "  fi\n"
        '  if [ "${FAKE_WAKE_POST_FAIL_ALL:-}" = "1" ]; then\n'
        "    exit 1\n"
        "  fi\n"
        '  test "${FAKE_POST_EXIT:-0}" = 0 || exit "$FAKE_POST_EXIT"\n'
        "  exit 0\n"
        "fi\n"
        'test "${GH_TOKEN:-}" != "${FAKE_DENIED_TOKEN:-}" || exit 1\n'
        'case "$endpoint" in\n'
        '  */pulls/*) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        '  repos/ContextualWisdomLab/naruon/actions/runs/42/jobs*) printf \'%s\\n\' "$FAKE_REQUIRED_JOB_PAGES" ;;\n'
        '  repos/ContextualWisdomLab/naruon/actions/runs/42) printf \'%s\\n\' "$FAKE_RUN_JSON" ;;\n'
        '  repos/ContextualWisdomLab/.github/actions/runs/100/jobs*) printf \'%s\\n\' "$FAKE_HANDLER_JOB_PAGES" ;;\n'
        '  repos/ContextualWisdomLab/.github/actions/runs/100/artifacts*) printf \'%s\\n\' "$FAKE_HANDLER_ARTIFACT_PAGES" ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "FAKE_RUN_JSON": json.dumps(run),
        "FAKE_REQUIRED_JOB_PAGES": json.dumps([{"jobs": required_jobs}]),
        "FAKE_HANDLER_JOB_PAGES": json.dumps([{"jobs": handler_jobs}]),
        "FAKE_HANDLER_ARTIFACT_PAGES": json.dumps(
            [{"artifacts": handler_artifacts}]
        ),
        "FAKE_POST_LOG": str(post_log),
        "FAKE_POST_EXIT": "0",
        "FAKE_DENIED_TOKEN": "",
        "GH_TOKEN": "fake-token",
        "TARGET_APP_WAKE_TOKEN": "",
        "PR_REVIEW_MERGE_WAKE_TOKEN": "",
        "OPENCODE_APPROVE_WAKE_TOKEN": "",
        "GITHUB_WAKE_TOKEN": "fake-token",
        "HANDLER_READ_TOKEN": "handler-token",
        "GITHUB_REPOSITORY": "ContextualWisdomLab/.github",
        "GITHUB_RUN_ID": "100",
        "GITHUB_RUN_ATTEMPT": "1",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "BASE_REF": "main",
        "BASE_SHA": "a" * 40,
        "HEAD_REF": "feature",
        "HEAD_SHA": head_sha,
        "REQUIRED_RUN_ID": "42",
        "REQUIRED_JOBS": json.dumps(
            [
                {"language": "python", "job_id": 43},
                {"language": "actions", "job_id": 44},
            ]
        ),
        "RERUN_MODE": "failed",
    }
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [bash], input=script, text=True, capture_output=True, check=False, env=env
    )
    return result, post_log


def test_dispatch_settlement_reruns_two_languages_once(tmp_path: Path) -> None:
    result, post_log = _run_settlement_step(tmp_path)

    assert result.returncode == 0, result.stderr
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs"
    ]


def test_dispatch_settlement_fails_closed_when_no_credential(
    tmp_path: Path,
) -> None:
    result, post_log = _run_settlement_step(
        tmp_path,
        extra_env={
            "GH_TOKEN": "",
            "TARGET_APP_WAKE_TOKEN": "",
            "PR_REVIEW_MERGE_WAKE_TOKEN": "",
            "OPENCODE_APPROVE_WAKE_TOKEN": "",
            "GITHUB_WAKE_TOKEN": "",
        },
    )

    assert result.returncode == 1
    assert "could not read the current pull request" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_falls_back_when_target_app_token_cannot_rerun(
    tmp_path: Path,
) -> None:
    """A nonempty App token without Actions write must not shadow fallbacks."""
    result, post_log = _run_settlement_step(
        tmp_path,
        extra_env={
            "TARGET_APP_WAKE_TOKEN": "forbidden-app-token",
            "PR_REVIEW_MERGE_WAKE_TOKEN": "actions-write-token",
            "OPENCODE_APPROVE_WAKE_TOKEN": "",
            "GITHUB_WAKE_TOKEN": "",
            "GH_TOKEN": "",
            "FAKE_WAKE_POST_FAIL_TOKEN": "forbidden-app-token",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs"
        in post_log.read_text(encoding="utf-8")
    )
    assert "pr-review-merge-token" in result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
    ]


def test_dispatch_settlement_fails_closed_after_every_wake_is_denied(
    tmp_path: Path,
) -> None:
    """A clean scan is not authoritative until one exact-job wake is accepted."""
    result, post_log = _run_settlement_step(
        tmp_path,
        extra_env={
            "TARGET_APP_WAKE_TOKEN": "app-token",
            "PR_REVIEW_MERGE_WAKE_TOKEN": "merge-token",
            "OPENCODE_APPROVE_WAKE_TOKEN": "approve-token",
            "GITHUB_WAKE_TOKEN": "github-token",
            "GH_TOKEN": "",
            "FAKE_WAKE_POST_FAIL_ALL": "1",
        },
    )

    assert result.returncode == 1
    assert "could not enqueue verified run-wide recovery" in result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
    ]


def test_dispatch_settlement_retries_reads_with_next_configured_credential(
    tmp_path: Path,
) -> None:
    result, post_log = _run_settlement_step(
        tmp_path,
        extra_env={
            "GH_TOKEN": "target-token",
            "TARGET_APP_WAKE_TOKEN": "target-token",
            "PR_REVIEW_MERGE_WAKE_TOKEN": "fallback-token",
            "OPENCODE_APPROVE_WAKE_TOKEN": "",
            "GITHUB_WAKE_TOKEN": "",
            "FAKE_DENIED_TOKEN": "target-token",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "pr-review-merge-token" in result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs",
    ]


def test_dispatch_settlement_rejects_stale_head_and_closed_pr(tmp_path: Path) -> None:
    stale_result, stale_log = _run_settlement_step(
        tmp_path / "stale", pull={"state": "open", "head": {"sha": "c" * 40}}
    )
    closed_result, closed_log = _run_settlement_step(
        tmp_path / "closed", pull={"state": "closed", "head": {"sha": "b" * 40}}
    )

    assert stale_result.returncode == 1
    assert closed_result.returncode == 1
    assert not stale_log.exists()
    assert not closed_log.exists()


def test_dispatch_settlement_rejects_changed_repository_or_head_ref(tmp_path: Path) -> None:
    """Settlement revalidates the complete live PR repository/ref identity."""
    wrong_repository, wrong_repository_log = _run_settlement_step(
        tmp_path / "wrong-repository",
        pull={
            "state": "open",
            "base": {"repo": {"full_name": "ContextualWisdomLab/other"}, "ref": "main", "sha": "a" * 40},
            "head": {"repo": {"full_name": "ContextualWisdomLab/naruon"}, "ref": "feature", "sha": "b" * 40},
        },
    )
    changed_ref, changed_ref_log = _run_settlement_step(
        tmp_path / "changed-ref",
        pull={
            "state": "open",
            "base": {"repo": {"full_name": "ContextualWisdomLab/naruon"}, "ref": "main", "sha": "a" * 40},
            "head": {"repo": {"full_name": "ContextualWisdomLab/naruon"}, "ref": "other", "sha": "b" * 40},
        },
    )

    assert wrong_repository.returncode == 1
    assert changed_ref.returncode == 1
    assert not wrong_repository_log.exists()
    assert not changed_ref_log.exists()


def test_dispatch_settlement_rejects_successful_required_run(tmp_path: Path) -> None:
    """A completed success cannot be mutated as though it were a failed attempt."""
    result, post_log = _run_settlement_step(
        tmp_path,
        run={
            "id": 42,
            "event": "pull_request",
            "path": ".github/workflows/codeql-pr.yml",
            "head_sha": "b" * 40,
            "status": "completed",
            "conclusion": "success",
        },
    )

    assert result.returncode == 1
    assert not post_log.exists()


def test_dispatch_settlement_rejects_wrong_or_nonfailed_job_identity(tmp_path: Path) -> None:
    wrong_jobs = [
        {
            "id": 43,
            "run_id": 999,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed",
            "conclusion": "failure",
        },
        {
            "id": 44,
            "run_id": 42,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "completed",
            "conclusion": "failure",
        },
    ]
    wrong_job_result, wrong_job_log = _run_settlement_step(
        tmp_path / "wrong-job",
        required_jobs=wrong_jobs,
    )
    successful_jobs = [dict(job) for job in wrong_jobs]
    successful_jobs[0].update(run_id=42, conclusion="success")
    successful_job_result, successful_job_log = _run_settlement_step(
        tmp_path / "successful-job",
        required_jobs=successful_jobs,
    )

    assert wrong_job_result.returncode == 1
    assert successful_job_result.returncode == 1
    assert "missing or ambiguous exact job identity" in wrong_job_result.stdout
    assert not wrong_job_log.exists()
    assert not successful_job_log.exists()


def test_dispatch_settlement_all_mode_reruns_success_and_failure_jobs(tmp_path: Path) -> None:
    all_jobs = [
        {
            "id": 43,
            "run_id": 42,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed",
            "conclusion": "success",
        },
        {
            "id": 44,
            "run_id": 42,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "completed",
            "conclusion": "failure",
        },
    ]
    result, post_log = _run_settlement_step(
        tmp_path,
        required_jobs=all_jobs,
        extra_env={"RERUN_MODE": "all"},
    )

    assert result.returncode == 0, result.stderr
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun"
    ]


def test_dispatch_settlement_rejects_missing_handler_artifact(tmp_path: Path) -> None:
    result, post_log = _run_settlement_step(
        tmp_path,
        handler_artifacts=[
            {
                "name": "codeql-dispatch-python-100-1",
                "expired": False,
                "size_in_bytes": 10,
            }
        ],
    )

    assert result.returncode == 1
    assert "incomplete handler gate or SARIF evidence for actions" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_rejects_missing_handler_gate_steps(tmp_path: Path) -> None:
    """A terminal scan name alone is not authenticated gate evidence."""
    result, post_log = _run_settlement_step(
        tmp_path,
        handler_jobs=[
            {
                "name": "CodeQL dispatch scan (python)",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "steps": [],
            },
            {
                "name": "CodeQL dispatch scan (actions)",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "steps": [
                    {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                    {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
                ],
            },
        ],
    )

    assert result.returncode == 1
    assert "incomplete handler gate or SARIF evidence for python" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_rejects_unproven_matrix_subset(tmp_path: Path) -> None:
    """Every required shard needs current handler gate and artifact evidence."""
    result, post_log = _run_settlement_step(
        tmp_path,
        handler_jobs=[
            {
                "name": "CodeQL dispatch scan (actions)",
                "status": "completed",
                "conclusion": "success",
            }
        ],
        handler_artifacts=[
            {
                "name": "codeql-dispatch-actions-100-1",
                "expired": False,
                "size_in_bytes": 10,
            }
        ],
    )

    assert result.returncode == 1
    assert "incomplete handler gate or SARIF evidence for python" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_rejects_unrelated_failed_job(tmp_path: Path) -> None:
    unrelated = {
        "id": 45,
        "run_id": 42,
        "head_sha": "b" * 40,
        "name": "unrelated required job",
        "status": "completed",
        "conclusion": "failure",
    }
    result, post_log = _run_settlement_step(
        tmp_path,
        required_jobs=[
            {
                "id": 43,
                "run_id": 42,
                "head_sha": "b" * 40,
                "name": "CodeQL compatibility analysis (python)",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "id": 44,
                "run_id": 42,
                "head_sha": "b" * 40,
                "name": "CodeQL compatibility analysis (actions)",
                "status": "completed",
                "conclusion": "failure",
            },
            unrelated,
        ],
    )

    assert result.returncode == 1
    assert "unrelated failed jobs" in result.stdout
    assert not post_log.exists()


def test_codeql_scan_dispatch_serialises_the_matrix_payload() -> None:
    """The dispatched matrix reaches `env:` as JSON text, never as a raw sequence.

    `codeql-pr.yml` sends `client_payload.matrix` as an array. An `env:` value must be
    a scalar, so assigning the array directly makes GitHub reject that step when its
    `env:` is evaluated -- "A sequence was not expected" -- after the runner has been
    assigned and the earlier steps have already run. That shipped in #1776 and left this
    workflow at 0 successes across 136 attempts.

    No local tool catches it: `yaml.safe_load` parses the file and `actionlint` 1.7.12
    reports it clean, because it is an Actions template rule rather than YAML syntax.
    Only GitHub's own validator rejects it, so this string contract is the only guard
    that runs before a dispatch does. The validate step consumes the value through
    `jq`, so JSON text is what it already expects.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert (
        "SUPPLIED_MATRIX: ${{ toJSON(github.event.client_payload.matrix) }}" in workflow
    ), "SUPPLIED_MATRIX must be serialised with toJSON(); a bare array breaks template validation"
    assert (
        "SUPPLIED_MATRIX: ${{ github.event.client_payload.matrix" not in workflow
    ), "SUPPLIED_MATRIX must not assign the raw client_payload array to env:"
    assert (
        "SUPPLIED_REQUIRED_JOBS: ${{ toJSON(github.event.client_payload.required_jobs) }}"
        in workflow
    ), "SUPPLIED_REQUIRED_JOBS must be serialised with toJSON(); a bare array breaks template validation"
    assert (
        "SUPPLIED_RERUN_REQUEST: ${{ toJSON(github.event.client_payload.rerun_request) }}"
        in workflow
    ), "The bounded nested rerun envelope must be serialized before shell validation"
    assert (
        "SUPPLIED_REQUIRED_JOB_ID: ${{ github.event.client_payload.required_job_id || '' }}"
        in workflow
    ), "Queued pre-cutover payloads still supply required_job_id as a scalar"
    assert (
        "SUPPLIED_REQUIRED_LANGUAGE: ${{ github.event.client_payload.required_language || '' }}"
        in workflow
    ), "Queued pre-cutover payloads still supply required_language as a scalar"
    assert "SUPPLIED_LEGACY_HEAD_REF: ${{ github.event.client_payload.pr_head_ref || '' }}" in workflow
    assert "SUPPLIED_LEGACY_HEAD_SHA: ${{ github.event.client_payload.pr_head_sha || '' }}" in workflow
    assert "conflicting nested and legacy pr_head identity" in workflow
