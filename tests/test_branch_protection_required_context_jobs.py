"""Pin every classic-branch-protection required context to the job that produces it.

This repository is excluded from the organization required-workflow ruleset
(``repository_name.exclude`` lists ``.github``), so its default branch is guarded by
*classic* branch protection with a fixed list of named required status contexts. A
context is matched by the **check-run name**, which GitHub takes from a job's ``name:``
when present and from the job id otherwise.

That makes a job rename a repository-wide outage, not a local edit: branch protection
keeps waiting for a context that nothing will ever report, so every pull request stays
blocked with no failing check to point at. Nothing else in this suite catches it --
these names are not pinned anywhere, and the two identifiers can drift apart. They
already have: the job id ``opencode-review-target`` reports the context
``opencode-review``, so renaming only the ``name:`` breaks protection while the job id
still looks correct.

The hazard is live because ``.github/workflows/`` is under active consolidation (21
consolidation/coalescing commits between 2026-09-01 and 2026-09-05), and folding jobs
together is exactly the edit that renames or removes them.

The blast radius is not limited to this repository. A sweep of all 76 organization
repositories on 2026-09-05 found 13 with classic protection, and several pin the *job
names* these central workflows declare: ``opencode-review`` and ``coverage-evidence``
are each required by 7 repositories, ``strix`` by 5, ``scan-pr-queue`` by 4,
``required-workflow-bootstrap`` by 3, and ``coverage-source-tree`` by 2. Renaming one
job here blocks every pull request in all of them at once, and those repositories
cannot see the change coming. ``admit-current-head`` is required by none, which is why
it is absent below.

If a context here is deliberately retired, update branch protection **first** -- in
every repository that requires it, not just this one -- then this test. Changing this
test alone re-arms the outage.
"""

from pathlib import Path

import yaml

WORKFLOW_DIR = Path(".github/workflows")

# Live `required_status_checks.contexts` on this repository's default branch,
# read from the branch-protection API on 2026-09-05, paired with the workflow
# file whose job definition reports each one.
REQUIRED_CONTEXT_SOURCES = {
    "CodeQL compatibility analysis": "codeql-pr.yml",
    "Detect CodeQL languages": "codeql-pr.yml",
    "coverage-evidence": "opencode-review.yml",
    "dependency-review": "security-scan.yml",
    "noema-review": "noema-review.yml",
    "opencode-review": "opencode-review.yml",
    "osv-scan": "security-scan.yml",
    "required-workflow-bootstrap": "opencode-review.yml",
    "scan-pr-queue": "pr-review-merge-scheduler.yml",
    "scorecard": "security-scan.yml",
    "trivy-fs": "security-scan.yml",
    # Required by sibling repositories but NOT by `.github` itself, so a sweep of
    # this repository's own protection would miss them. Measured 2026-09-05 across
    # all 76 organization repositories: `strix` is required by pg-erd-cloud,
    # bandscope, naruon, linux-cluster-ops and contextual-orchestrator;
    # `coverage-source-tree` by naruon and linux-cluster-ops. Renaming either job
    # in the central workflow blocks every pull request in those repositories.
    "strix": "strix.yml",
    "coverage-source-tree": "opencode-review.yml",
}

# `CodeQL compatibility analysis` is reported once per matrix language, so branch
# protection names the expanded contexts (`... (actions)`, `... (python)`) while the
# workflow declares the template.
MATRIX_NAME_TEMPLATES = {
    "CodeQL compatibility analysis": (
        "CodeQL compatibility analysis (${{ matrix.language }})"
    ),
}


def _effective_check_names(workflow_name: str) -> set[str]:
    """Return the check-run names one workflow can report.

    GitHub names a check run after the job's ``name:`` when it has one and after the
    job id **only when it does not**. Accepting either spelling unconditionally would
    pass a job whose id still matches while its ``name:`` was renamed away -- which is
    precisely the break this test exists to catch, since the renamed name is what
    branch protection would then wait for.
    """
    document = yaml.safe_load((WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8"))
    names = set()
    for job_id, job in (document.get("jobs") or {}).items():
        declared = job.get("name") if isinstance(job, dict) else None
        names.add(str(declared) if declared else str(job_id))
    return names


def _declares_context(workflow_name: str, context: str) -> bool:
    """Report whether one workflow can report `context` as a check-run name."""
    names = _effective_check_names(workflow_name)
    if context in names:
        return True
    template = MATRIX_NAME_TEMPLATES.get(context)
    return template is not None and template in names


def test_every_required_context_is_declared_by_a_job() -> None:
    """Each required status context is still declared as a job name or job id."""
    missing = []
    for context, workflow_name in sorted(REQUIRED_CONTEXT_SOURCES.items()):
        if not _declares_context(workflow_name, context):
            missing.append(f"{context!r} not declared by any job in {workflow_name}")
    assert not missing, (
        "Required status contexts lost their producing job. Branch protection will "
        "wait forever for these and every pull request will stay blocked:\n  "
        + "\n  ".join(missing)
    )


def test_required_context_workflow_files_exist() -> None:
    """Every workflow named as a context source is present."""
    absent = sorted(
        {
            workflow_name
            for workflow_name in REQUIRED_CONTEXT_SOURCES.values()
            if not (WORKFLOW_DIR / workflow_name).is_file()
        }
    )
    assert not absent, f"Required-context workflow files are missing: {absent}"


def test_matrix_templates_reference_only_known_contexts() -> None:
    """The matrix-template override table cannot name an unlisted context."""
    unknown = sorted(set(MATRIX_NAME_TEMPLATES) - set(REQUIRED_CONTEXT_SOURCES))
    assert not unknown, f"Matrix templates name unlisted contexts: {unknown}"
