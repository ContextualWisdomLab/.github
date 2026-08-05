"""Apply and self-remove the reviewed PR 782 conflict-scope repair.

The branch-only helper patches the permanent conflict workflow, updates its
operator evidence, removes every temporary repair artifact, and leaves final
publication to the tightly scoped GitHub Actions caller after the permanent
100% coverage, branch, docstring, syntax, and workflow-order gates pass.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


# This branch-only source exists solely to trigger and apply the bounded repair.
WORKFLOW_PATH = Path(".github/workflows/pr-review-autofix.yml")
DOCTORING_PATH = Path("docs/doctoring/hourly-nvidia-nim-autofix.md")
CHANGELOG_PATH = Path("CHANGELOG.md")
TEMPORARY_PATHS = (
    Path(".github/workflows/one-shot-pr782-conflict-scope-repair.yml"),
    Path(".github/workflows/repair-pr782-conflict-scope.yml"),
    Path("scripts/ci/repair_pr782_conflict_scope_once.py"),
)


def _replace_exact(source: str, old: str, new: str, *, label: str) -> str:
    """Replace one exact source fragment or fail closed on source drift."""
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"expected exactly one {label} fragment")
    return source.replace(old, new, 1)


def _repair_workflow() -> None:
    """Bind model writes to Git's exact merge-conflict path allowlist."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    conflict_start = '''          if [ -n "$conflicted_files" ]; then
            prompt_file="${RUNNER_TEMP}/opencode-conflict-prompt.md"
'''
    bounded_conflict_start = '''          if [ -n "$conflicted_files" ]; then
            conflicted_paths_file="${RUNNER_TEMP}/opencode-conflicted-files.zlist"
            conflict_scope_snapshot="${RUNNER_TEMP}/opencode-conflict-workspace-before.json"
            git diff --name-only -z --diff-filter=U >"$conflicted_paths_file"
            python3 "$GITHUB_WORKSPACE/trusted-autofix-source/scripts/ci/pr_review_conflict_scope.py" snapshot \\
              --root "$TARGET_WORKSPACE" \\
              --output "$conflict_scope_snapshot"
            prompt_file="${RUNNER_TEMP}/opencode-conflict-prompt.md"
'''
    workflow = _replace_exact(
        workflow,
        conflict_start,
        bounded_conflict_start,
        label="conflict-model entry",
    )

    model_end = '''            restore_workspace_config
            trap - EXIT
          fi

          # Fail closed: never push unresolved conflict markers.
'''
    bounded_model_end = '''            restore_workspace_config
            trap - EXIT
            python3 "$GITHUB_WORKSPACE/trusted-autofix-source/scripts/ci/pr_review_conflict_scope.py" verify \\
              --root "$TARGET_WORKSPACE" \\
              --snapshot "$conflict_scope_snapshot" \\
              --allowed-paths "$conflicted_paths_file"
          fi

          # Fail closed: never push unresolved conflict markers.
'''
    workflow = _replace_exact(
        workflow,
        model_end,
        bounded_model_end,
        label="conflict-model completion",
    )
    WORKFLOW_PATH.write_text(workflow, encoding="utf-8")


def _update_documentation() -> None:
    """Record the operational conflict-scope boundary and release evidence."""
    doctoring = DOCTORING_PATH.read_text(encoding="utf-8")
    section_heading = "## Conflict-resolution model write boundary"
    if section_heading not in doctoring:
        marker = "\n## GitHub write boundary\n"
        section = dedent(
            '''
            ## Conflict-resolution model write boundary

            A merge-conflict repair begins by merging the exact validated base SHA into
            the exact PR head. Immediately after Git records the unresolved paths, the
            worker writes two immutable local inputs before OpenCode receives the task:

            1. a NUL-delimited allowlist produced by `git diff --name-only -z
               --diff-filter=U`; and
            2. a deterministic snapshot of every tracked and non-ignored untracked
               worktree path after the base merge.

            The snapshot fingerprints regular-file content with SHA-256 and records file
            size, mode, symbolic-link target, deletion, and other entry types. This timing
            is deliberate: legitimate non-conflict changes introduced by the base merge
            are part of the pre-model baseline, while changes made later by the model are
            not.

            After OpenCode exits, the workflow restores the repository's prior OpenCode
            configuration and compares the current worktree to that pre-model snapshot.
            Only paths in Git's NUL-delimited conflict allowlist may differ. A created,
            deleted, modified, mode-changed, or retargeted path outside that set fails the
            job before `git add -A`, commit, or push. Path inventories and path byte
            lengths are bounded, malformed snapshot data fails closed, and diagnostic
            output JSON-escapes path names rather than emitting them as workflow commands.

            Ignored build caches are outside the comparison because `git add -A` does not
            publish them. Git metadata is outside the model's file-edit surface; the
            model process has no shell, GitHub token, or Actions OIDC credential. The
            later live-head, unresolved-marker, merge-tree, syntax, and push checks remain
            independent defenses.
            '''
        )
        if doctoring.count(marker) != 1:
            raise RuntimeError("expected exactly one GitHub write-boundary heading")
        DOCTORING_PATH.write_text(
            doctoring.replace(marker, "\n" + section + marker, 1), encoding="utf-8"
        )

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    bullet = (
        "- Snapshot the post-merge worktree before OpenCode conflict repair "
        "and reject every model-caused changed, created, deleted, or "
        "retargeted path outside Git's exact conflict allowlist before "
        "staging or push.\n"
    )
    if bullet not in changelog:
        anchor = "### Security\n\n"
        if changelog.count(anchor) != 1:
            raise RuntimeError("expected exactly one changelog Security heading")
        CHANGELOG_PATH.write_text(
            changelog.replace(anchor, anchor + bullet, 1), encoding="utf-8"
        )


def _remove_temporary_artifacts() -> None:
    """Delete both one-shot workflows and this branch-only helper."""
    for path in TEMPORARY_PATHS:
        if path.exists():
            path.unlink()


def main() -> None:
    """Apply the permanent repair and remove temporary implementation files."""
    _repair_workflow()
    _update_documentation()
    _remove_temporary_artifacts()


if __name__ == "__main__":
    main()
