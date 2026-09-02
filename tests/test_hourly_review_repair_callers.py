"""Contracts for the consolidated hourly review-repair caller.

Replaces the 18 near-identical per-repository ``<repo>-hourly-review-repair.yml``
caller files (and their 13 dedicated test modules) with one file,
``.github/workflows/hourly-review-repair.yml``, and one test module. See
``docs/doctoring/hourly-review-repair-single-file-consolidation.md`` and
``docs/adr/0021-hourly-review-repair-single-file-consolidation.md`` for why.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

_CALLER = Path(".github/workflows/hourly-review-repair.yml")
_REUSABLE_SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")

_FORMER_CALLERS = (
    "accounting-information-platform-hourly-review-repair.yml",
    "afipc-hourly-review-repair.yml",
    "bandscope-hourly-review-repair.yml",
    "clearfolio-hourly-review-repair.yml",
    "contextual-orchestrator-hourly-review-repair.yml",
    "disksage-hourly-review-repair.yml",
    "fast-mlsirm-hourly-review-repair.yml",
    "github-hourly-review-repair.yml",
    "governance-risk-compliance-hourly-review-repair.yml",
    "inkspan-hourly-review-repair.yml",
    "lineageweave-hourly-review-repair.yml",
    "metering-billing-platform-hourly-review-repair.yml",
    "nonnest2-hourly-review-repair.yml",
    "orgmetra-hourly-review-repair.yml",
    "originweave-hourly-review-repair.yml",
    "psychometrics-commons-hourly-review-repair.yml",
    "quarantine-sandbox-hourly-review-repair.yml",
    "semantic-data-portal-hourly-review-repair.yml",
)

# schedule -> exact list of {name, target_repository, base_branch,
# retry_hours, concurrency_group} the resolve-target lookup must produce,
# reproducing every field the 18 deleted files passed to
# pr-review-fix-scheduler.yml. max_prs ("50") and max_dispatches ("1") were
# uniform across all 18 originals and are asserted separately as static
# `with:` values rather than carried per-target.
_EXPECTED_TARGETS: dict[str, list[dict[str, str]]] = {
    "2 * * * *": [
        {
            "name": "afipc",
            "target_repository": "ContextualWisdomLab/aFIPC",
            "base_branch": "master",
            "retry_hours": "2",
            "concurrency_group": "afipc-hourly-review-repair",
        },
    ],
    "4 * * * *": [
        {
            "name": "lineageweave",
            "target_repository": "ContextualWisdomLab/LineageWeave",
            "base_branch": "*",
            "retry_hours": "2",
            "concurrency_group": "lineageweave-hourly-review-repair",
        },
    ],
    "9 * * * *": [
        {
            "name": "psychometrics-commons",
            "target_repository": "ContextualWisdomLab/psychometrics-commons",
            "base_branch": "main",
            "retry_hours": "2",
            "concurrency_group": "psychometrics-commons-hourly-review-repair",
        },
    ],
    "10 * * * *": [
        {
            "name": "originweave",
            "target_repository": "ContextualWisdomLab/OriginWeave",
            "base_branch": "main",
            "retry_hours": "2",
            "concurrency_group": "originweave-hourly-review-repair",
        },
    ],
    "14 * * * *": [
        {
            "name": "quarantine-sandbox",
            "target_repository": "ContextualWisdomLab/quarantine-sandbox-runtime",
            "base_branch": "develop",
            "retry_hours": "2",
            "concurrency_group": "quarantine-sandbox-hourly-review-repair",
        },
    ],
    "16 * * * *": [
        {
            "name": "nonnest2",
            "target_repository": "ContextualWisdomLab/nonnest2",
            "base_branch": "master",
            "retry_hours": "2",
            "concurrency_group": "nonnest2-hourly-review-repair",
        },
    ],
    "21 * * * *": [
        {
            "name": "github",
            "target_repository": "ContextualWisdomLab/.github",
            "base_branch": "main",
            "retry_hours": "1",
            "concurrency_group": "github-hourly-review-repair",
        },
    ],
    "23 * * * *": [
        {
            "name": "clearfolio",
            "target_repository": "ContextualWisdomLab/clearfolio",
            "base_branch": "main",
            "retry_hours": "1",
            "concurrency_group": "clearfolio-hourly-review-repair",
        },
    ],
    "27 * * * *": [
        {
            "name": "accounting-information-platform",
            "target_repository": "ContextualWisdomLab/accounting-information-platform",
            "base_branch": "develop",
            "retry_hours": "2",
            "concurrency_group": "accounting-information-platform-hourly-review-repair",
        },
    ],
    "34 * * * *": [
        {
            "name": "contextual-orchestrator",
            "target_repository": "ContextualWisdomLab/contextual-orchestrator",
            "base_branch": "main",
            "retry_hours": "2",
            "concurrency_group": "contextual-orchestrator-hourly-review-repair",
        },
    ],
    "37 * * * *": [
        {
            "name": "disksage",
            "target_repository": "ContextualWisdomLab/disksage",
            "base_branch": "main",
            "retry_hours": "2",
            "concurrency_group": "disksage-hourly-review-repair",
        },
    ],
    "43 * * * *": [
        {
            "name": "governance-risk-compliance",
            "target_repository": "ContextualWisdomLab/governance-risk-compliance",
            "base_branch": "develop",
            "retry_hours": "2",
            "concurrency_group": "governance-risk-compliance-hourly-review-repair",
        },
    ],
    # Minute 49 is the one collision the original 18 files carried: two
    # independent files (fast-mlsirm, metering-billing-platform) had each
    # chosen minute 49 without knowing about the other. The consolidated
    # lookup makes that sharing explicit and still dispatches each
    # repository exactly once per hour, via the matrix in
    # dispatch-review-repair.
    "49 * * * *": [
        {
            "name": "fast-mlsirm",
            "target_repository": "ContextualWisdomLab/fast-mlsirm",
            "base_branch": "main",
            "retry_hours": "2",
            "concurrency_group": "fast-mlsirm-hourly-review-repair",
        },
        {
            "name": "metering-billing-platform",
            "target_repository": "ContextualWisdomLab/metering-billing-platform",
            "base_branch": "develop",
            "retry_hours": "1",
            "concurrency_group": "metering-billing-platform-hourly-review-repair",
        },
    ],
    "53 * * * *": [
        {
            "name": "bandscope",
            "target_repository": "ContextualWisdomLab/bandscope",
            "base_branch": "develop",
            "retry_hours": "2",
            "concurrency_group": "bandscope-hourly-review-repair",
        },
    ],
    "56 * * * *": [
        {
            "name": "inkspan",
            "target_repository": "ContextualWisdomLab/inkspan",
            "base_branch": "main",
            "retry_hours": "2",
            "concurrency_group": "inkspan-hourly-review-repair",
        },
    ],
    "58 * * * *": [
        {
            "name": "orgmetra",
            "target_repository": "ContextualWisdomLab/Orgmetra",
            "base_branch": "develop",
            "retry_hours": "2",
            "concurrency_group": "orgmetra-hourly-review-repair",
        },
    ],
    "59 * * * *": [
        {
            "name": "semantic-data-portal",
            "target_repository": "ContextualWisdomLab/semantic-data-portal",
            "base_branch": "main",
            "retry_hours": "2",
            "concurrency_group": "semantic-data-portal-hourly-review-repair",
        },
    ],
}


def _read(path: Path) -> str:
    """Return one workflow as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _resolve_step_script(workflow_text: str) -> str:
    """Extract the resolve-target job's inline lookup script.

    Mirrors the extraction pattern already used in
    ``test_scheduler_validates_dispatch_authority_before_credentials``
    (``tests/test_pr_review_fix_hourly_contract.py``) for exercising an
    embedded ``run:`` block as a real subprocess instead of only pattern
    matching the YAML text.
    """
    marker = "        run: |\n"
    start = workflow_text.index(marker) + len(marker)
    lines = workflow_text[start:].splitlines()
    script_lines: list[str] = []
    for line in lines:
        if line.strip() == "":
            script_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < 10:
            break
        script_lines.append(line[10:])
    return "\n".join(script_lines)


def _run_lookup(script: str, schedule: str, tmp_path: Path) -> list[dict[str, str]]:
    """Execute the extracted lookup script for one schedule and parse its output."""
    output_file = tmp_path / f"gh_output_{abs(hash(schedule))}.txt"
    output_file.write_text("")
    result = subprocess.run(
        ["bash", "-c", script],
        env={"SCHEDULE": schedule, "GITHUB_OUTPUT": str(output_file), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"lookup script failed for schedule={schedule!r}: {result.stderr}"
    )
    match = re.match(r"targets=(.*)\n?\Z", output_file.read_text(), re.S)
    assert match, f"no targets= output for schedule={schedule!r}"
    return json.loads(match.group(1))


def test_all_eighteen_former_callers_are_deleted() -> None:
    """The 18 former per-repository files are fully replaced, not duplicated."""
    for filename in _FORMER_CALLERS:
        assert not Path(f".github/workflows/{filename}").exists(), (
            f"{filename} should have been deleted by the single-file consolidation"
        )
    assert _CALLER.is_file()


def test_schedule_list_has_every_distinct_minute_exactly_once() -> None:
    """The 17 distinct minutes (49 is intentionally shared) each appear once."""
    text = _read(_CALLER)
    cron_lines = re.findall(r'- cron: "([^"]+)"', text)

    assert len(cron_lines) == len(set(cron_lines)) == 17
    assert set(cron_lines) == set(_EXPECTED_TARGETS)


@pytest.mark.parametrize("schedule", sorted(_EXPECTED_TARGETS))
def test_resolve_target_lookup_matches_original_per_repo_parameters(
    schedule: str, tmp_path: Path
) -> None:
    """Every schedule resolves to the exact target(s) its deleted file(s) used."""
    script = _resolve_step_script(_read(_CALLER))

    assert _run_lookup(script, schedule, tmp_path) == _EXPECTED_TARGETS[schedule]


def test_resolve_target_lookup_fails_closed_on_an_unknown_schedule(
    tmp_path: Path,
) -> None:
    """An unrecognized schedule value must not dispatch to any repository."""
    script = _resolve_step_script(_read(_CALLER))
    output_file = tmp_path / "gh_output_unknown.txt"
    output_file.write_text("")

    result = subprocess.run(
        ["bash", "-c", script],
        env={
            "SCHEDULE": "0 0 * * *",
            "GITHUB_OUTPUT": str(output_file),
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert output_file.read_text() == ""


def test_max_prs_and_max_dispatches_stay_uniform_static_values() -> None:
    """The two fields that never varied across the 18 originals stay static."""
    text = _read(_CALLER)

    assert 'max_prs: "50"' in text
    assert 'max_dispatches: "1"' in text
    # They are static `with:` values, not carried through the per-target
    # lookup table (they never varied, so there is nothing to look up).
    assert '"max_prs"' not in text
    assert '"max_dispatches"' not in text


def test_dispatch_job_uses_a_per_repository_dynamic_concurrency_group() -> None:
    """Each repository keeps its own independent, non-cancelling lease.

    All 18 original files used SEPARATE `concurrency.group` values (one per
    repository), never a shared group. A `concurrency:` expression at job
    level may reference `matrix.*` because the matrix is resolved before the
    job starts (GitHub, n.d.-a), so keying the group on
    `matrix.concurrency_group` reproduces that per-repository isolation
    inside one job definition instead of one group shared by every
    schedule.
    """
    text = _read(_CALLER)

    assert "group: ${{ matrix.concurrency_group }}" in text
    assert "cancel-in-progress: false" in text
    assert "cancel-in-progress: true" not in text
    # No single hard-coded group name: isolation is per resolved target.
    for filename in _FORMER_CALLERS:
        repo_slug = filename.removesuffix("-hourly-review-repair.yml")
        assert f"group: {repo_slug}-hourly-review-repair" not in text


def test_dispatch_job_fans_out_over_the_resolved_targets_matrix() -> None:
    """The matrix consumes resolve-target's output for every schedule."""
    text = _read(_CALLER)

    assert "needs: resolve-target" in text
    assert (
        "include: ${{ fromJson(needs.resolve-target.outputs.targets) }}" in text
    )
    assert "fail-fast: false" in text
    assert "uses: ./.github/workflows/pr-review-fix-scheduler.yml" in text
    assert "target_repository: ${{ matrix.target_repository }}" in text
    assert "base_branch: ${{ matrix.base_branch }}" in text
    assert 'retry_hours: ${{ matrix.retry_hours }}' in text


def test_dispatch_job_grants_only_read_and_oidc_permissions() -> None:
    """Every resolved target gets the same narrow, explicit permission set."""
    text = _read(_CALLER)
    workflow_scope, jobs_scope = text.split("\njobs:\n", maxsplit=1)

    assert "\npermissions:\n  contents: read\n" in workflow_scope
    assert "\n    permissions:\n      contents: read\n      id-token: write\n" in jobs_scope
    for permission in (
        "actions: write",
        "issues: write",
        "contents: write",
        "pull-requests: write",
        "statuses: write",
    ):
        assert permission not in text


def test_dispatch_job_forwards_only_the_two_established_secrets() -> None:
    """No `secrets: inherit`, no gateway provider credential leakage."""
    text = _read(_CALLER)

    assert "PR_REVIEW_MERGE_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in text
    assert "OPENCODE_APPROVE_TOKEN: ${{ secrets.OPENCODE_APPROVE_TOKEN }}" in text
    assert "secrets: inherit" not in text
    assert "COPILOT_GITHUB_TOKEN" not in text
    assert "NVIDIA_NIM_API_KEY" not in text


def test_no_target_repository_is_hard_coded_in_the_shared_scheduler() -> None:
    """The reusable engine stays product-neutral for every consolidated target.

    ``ContextualWisdomLab/.github`` legitimately appears in the reusable
    workflow as the *default* ``autofix_repository`` (the central repository
    that owns ``pr-review-autofix.yml``, not a scanned product target), so
    the central self-caller is excluded from this check the same way the
    original per-repository tests only checked the product repositories
    (OriginWeave, aFIPC, nonnest2, quarantine-sandbox,
    contextual-orchestrator) and not the central repository's own name.
    """
    reusable_text = _read(_REUSABLE_SCHEDULER)

    for targets in _EXPECTED_TARGETS.values():
        for target in targets:
            if target["name"] == "github":
                continue
            assert target["target_repository"] not in reusable_text


def test_resolve_unreviewed_conflicts_is_explicit_and_matches_the_default() -> None:
    """Making the input explicit for every target changes nothing behaviorally.

    The reusable workflow's own `resolve_unreviewed_conflicts` input already
    defaults to `true`; 17 of the 18 original files omitted the key (relying
    on that default) and only the central `.github` self-caller set it
    explicitly. The consolidated file sets it explicitly and uniformly,
    which is behaviorally identical to the prior mixed omitted/explicit
    state for every one of the 18 targets.
    """
    caller_text = _read(_CALLER)
    reusable_text = _read(_REUSABLE_SCHEDULER)

    assert "resolve_unreviewed_conflicts: true" in caller_text
    policy_block = reusable_text.split("resolve_unreviewed_conflicts:", maxsplit=1)[
        1
    ].split("retry_hours:", maxsplit=1)[0]
    assert "default: true" in policy_block
