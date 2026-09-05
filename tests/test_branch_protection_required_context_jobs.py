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

If a context here is deliberately retired, update branch protection **first**, then this
test. Changing this test alone re-arms the outage.
"""

from pathlib import Path

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
}

# `CodeQL compatibility analysis` is reported once per matrix language, so branch
# protection names the expanded contexts (`... (actions)`, `... (python)`) while the
# workflow declares the template.
MATRIX_NAME_TEMPLATES = {
    "CodeQL compatibility analysis": (
        "name: CodeQL compatibility analysis (${{ matrix.language }})"
    ),
}


def _declares_context(workflow_name: str, context: str) -> bool:
    """Report whether one workflow declares `context` as a check-run name.

    GitHub names a check run after the job's ``name:`` when it has one and after the
    job id otherwise, so either spelling keeps the context reporting.
    """
    text = (WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")
    template = MATRIX_NAME_TEMPLATES.get(context)
    if template is not None:
        return template in text
    if f"name: {context}\n" in text:
        return True
    return f"\n  {context}:\n" in text


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
