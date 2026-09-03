"""Contract for the job-level `changed-scope` runner-admission gate.

Trigger-level `paths`/`paths-ignore` filters on a REQUIRED workflow are a
no-go: org ruleset `18156473` runs these workflows in each target
repository's context and ignores every `on:` filter there (confirmed live:
`bandscope` has no local `codeql-pr.yml`/`strix.yml`/`security-scan.yml`, yet
ruleset-injected runs of all three exist), and `.github` itself is excluded
from the ruleset and uses classic branch protection, where a path-filtered
required context would stay Pending forever instead of reporting.

The safe mechanism is a job-level `if:` gate: a `changed-scope` job classifies
the PR's changed files (fail-open on any read failure) and downstream jobs
add `needs: changed-scope` plus an output-gated `if:`. `strix.yml` keeps its
existing `paths-ignore:` too -- it is the one documented exception, verified
live to be natively triggered (not ruleset-injected) in the three repositories
the ruleset excludes -- see
`docs/doctoring/required-workflow-path-filter-boundary.md`.

See also `tests/test_required_security_runner_image_contract.py` and
`tests/test_required_review_runner_image_contract.py`, which pin the
`runs-on: ubuntu-24.04` counts these gate jobs add.
"""

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github/workflows"

# The five workflows that got a copy of the canonical `changed-scope` gate job.
GATE_WORKFLOWS = (
    "security-scan.yml",
    "sast-semgrep.yml",
    "strix.yml",
    "scorecard-pr.yml",
    "osv-scanner-pr.yml",
)

# Workflows that must never gain a trigger-level paths/paths-ignore filter.
# strix.yml is the single documented exception (native-run doc/image skip).
NO_TRIGGER_FILTER_WORKFLOWS = (
    "security-scan.yml",
    "sast-semgrep.yml",
    "codeql-pr.yml",
    "scorecard-pr.yml",
    "osv-scanner-pr.yml",
    "close-empty-pr.yml",
    "opencode-review.yml",
    "noema-review.yml",
    "pr-review-merge-scheduler.yml",
)

# Jobs whose admission is now conditional on a `changed-scope`/`detect-languages`
# output, keyed by workflow filename.
GATED_JOBS = {
    "security-scan.yml": ("osv-scan", "dependency-review", "trivy-fs", "scorecard"),
    "sast-semgrep.yml": ("semgrep",),
    "strix.yml": ("strix",),
    "scorecard-pr.yml": ("analysis",),
    "osv-scanner-pr.yml": ("osv-scan",),
}


def _read(filename: str) -> str:
    return (WORKFLOWS_DIR / filename).read_text(encoding="utf-8")


def _top_level_job_block(workflow: str, job_name: str) -> str:
    """Return the body text of one top-level ``jobs:`` entry.

    Scoped from the job's own ``  <job_name>:`` header line up to (but not
    including) the next line with exactly two leading spaces followed by a
    bare identifier and colon -- i.e. the next top-level job key.
    """
    jobs_index = workflow.index("\njobs:\n")
    body = workflow[jobs_index + len("\njobs:\n") :]
    start_match = re.search(rf"(?m)^  {re.escape(job_name)}:\s*$", body)
    assert start_match, f"job {job_name!r} not found"
    rest = body[start_match.start() :]
    next_job = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$", rest[1:])
    end = next_job.start() + 1 if next_job else len(rest)
    return rest[:end]


def _on_block(workflow: str) -> str:
    """Return the text of the top-level ``on:`` mapping."""
    match = re.search(r"(?m)^on:\n((?:.*\n)*?)(?=^\S|\Z)", workflow)
    assert match, "workflow has no top-level 'on:' block"
    return match.group(1)


def test_gate_job_is_byte_identical_across_the_five_workflows_apart_from_if():
    """The `changed-scope` block must not drift between its five copies."""
    normalized_blocks = set()
    for filename in GATE_WORKFLOWS:
        workflow = _read(filename)
        block = _top_level_job_block(workflow, "changed-scope")
        normalized = "\n".join(
            line for line in block.splitlines() if not line.strip().startswith("if:")
        )
        normalized_blocks.add(normalized)
    assert len(normalized_blocks) == 1, (
        "changed-scope gate copies drifted; keep them byte-identical apart "
        "from the single 'if:' line"
    )


def test_gate_job_and_codeql_scope_step_share_one_doc_pattern_line():
    """The doc/image-only `case` line must be identical everywhere, and safe.

    `LICENSE.*` (matches the executable `LICENSE.py`) and `*.svg` (carries
    script) must never appear in it -- see the correction that replaced
    `LICENSE.*` with the explicit `LICENSE`/`LICENSE.txt`/`COPYING`/
    `COPYING.txt`/`NOTICE`/`NOTICE.txt` names.
    """
    doc_pattern_lines = set()
    for filename in (*GATE_WORKFLOWS, "codeql-pr.yml"):
        workflow = _read(filename)
        matches = [
            line for line in workflow.splitlines() if "*.md|*.markdown" in line
        ]
        assert len(matches) == 1, f"{filename} should have exactly one doc-pattern case line"
        doc_pattern_lines.add(matches[0])

    assert len(doc_pattern_lines) == 1, "doc-pattern case line drifted between files"
    (line,) = doc_pattern_lines
    assert "LICENSE.*" not in line
    assert "*.svg" not in line
    assert "LICENSE" in line
    assert "COPYING" in line
    assert "NOTICE" in line


def test_gate_jobs_run_on_ubuntu_24_04():
    """Every `changed-scope` job must use the non-starved pinned image."""
    for filename in GATE_WORKFLOWS:
        block = _top_level_job_block(_read(filename), "changed-scope")
        assert "runs-on: ubuntu-24.04" in block, filename
        assert "runs-on: ubuntu-latest" not in block, filename


def test_no_trigger_level_path_filter_on_required_workflows():
    """Required workflows must gate at job level, never at trigger level.

    A ruleset-injected run in another repository ignores the trigger-level
    `on:` filter entirely (bandscope has no local `security-scan.yml` etc.
    yet ruleset-injected runs exist), and `.github`'s own classic protection
    would leave a path-filtered required context Pending forever.
    """
    for filename in NO_TRIGGER_FILTER_WORKFLOWS:
        on_block = _on_block(_read(filename))
        assert not re.search(r"(?m)^\s*paths:", on_block), filename
        assert not re.search(r"(?m)^\s*paths-ignore:", on_block), filename

    # strix.yml is the single documented exception: it natively triggers (is
    # not ruleset-injected) in the three repositories the ruleset excludes.
    strix = _read("strix.yml")
    on_block = _on_block(strix)
    assert re.search(r"(?m)^\s*paths-ignore:", on_block)
    assert "docs/doctoring/required-workflow-path-filter-boundary.md" in strix


def test_gated_jobs_keep_the_close_guard_and_add_an_output_dependent_condition():
    """Each gated job's `if:` must still guard `closed` and add a needs-output term."""
    for filename, job_names in GATED_JOBS.items():
        workflow = _read(filename)
        for job_name in job_names:
            block = _top_level_job_block(workflow, job_name)
            assert "github.event.action != 'closed'" in block, (filename, job_name)
            assert re.search(r"needs\.[\w-]+\.outputs\.\w+", block), (
                filename,
                job_name,
            )


def test_codeql_pr_gates_analyze_head_at_step_level_not_job_level():
    """`analyze-head` must gate its steps, not the whole job.

    Decisive live evidence (run `33708209086`): a job-level skip on a job
    whose `strategy.matrix` comes from another job's output publishes the
    literal, unexpanded `${{ matrix.language }}` check-run name instead of
    the required `CodeQL compatibility analysis (actions|python)` contexts,
    so those required checks never appear. Gating the steps instead lets the
    job run (~20s), succeed, and publish the correctly expanded names. Since
    the dispatch+poll rewrite (docs/adr/0025-codeql-required-workflow-dispatch-architecture.md),
    `analyze-head` has two steps: the dispatch step's `if:` additionally
    restricts it to the first matrix shard (see
    tests/test_codeql_pr_workflow_contract.py::test_codeql_pr_dispatches_once_not_once_per_matrix_shard),
    while the poll step runs unconditionally on `code == 'true'` alone -- both
    still gate at step level, never at job level. `analyze-merge` no longer
    exists: it was required nowhere (PR #1766) and was dropped, not migrated.
    """
    workflow = _read("codeql-pr.yml")

    detect_languages = _top_level_job_block(workflow, "detect-languages")
    assert not re.search(r"(?m)^    needs:", detect_languages)

    analyze_head = _top_level_job_block(workflow, "analyze-head")
    assert not re.search(r"(?m)^    if:", analyze_head)
    assert analyze_head.count("needs.detect-languages.outputs.code == 'true'") == 2
    assert "analyze-merge:" not in workflow


def test_each_gate_workflow_keeps_an_always_admitted_job():
    """A fully-skipped run must conclude `success`, never `skipped`.

    Every one of the five workflows needs at least one job with no `needs:`
    and no needs-output-dependent `if:` -- the `changed-scope` job itself
    qualifies -- so a doc-only PR's run still has a job that runs and
    succeeds instead of every job skipping and the run itself reporting
    `skipped` (an undocumented conclusion for a required check).
    """
    for filename in GATE_WORKFLOWS:
        block = _top_level_job_block(_read(filename), "changed-scope")
        assert not re.search(r"(?m)^    needs:", block), filename
        job_if = re.search(r"(?m)^    if: (.*)$", block)
        assert job_if is not None, filename
        assert "needs." not in job_if.group(1), filename
