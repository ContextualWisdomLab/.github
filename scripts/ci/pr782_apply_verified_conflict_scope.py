#!/usr/bin/env python3
"""Apply the reviewed PR 782 conflict-resolution write-scope repair exactly once."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    """Replace one exact UTF-8 source fragment or fail closed on drift."""
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    if new in source:
        return
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement anchor, found {count}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


def apply_workflow_boundary() -> None:
    """Snapshot after merge and verify model writes before Git staging."""
    replace_once(
        ".github/workflows/pr-review-autofix.yml",
        '''          if [ -n "$conflicted_files" ]; then
            prompt_file="${RUNNER_TEMP}/opencode-conflict-prompt.md"
''',
        '''          conflicted_paths_file="${RUNNER_TEMP}/opencode-conflicted-files.zlist"
          conflict_scope_snapshot="${RUNNER_TEMP}/opencode-conflict-workspace-before.json"
          git diff --name-only -z --diff-filter=U >"$conflicted_paths_file"
          python "${GITHUB_WORKSPACE}/trusted-autofix-source/scripts/ci/pr_review_conflict_scope.py" snapshot \\
            --root "$TARGET_WORKSPACE" \\
            --output "$conflict_scope_snapshot"

          if [ -n "$conflicted_files" ]; then
            prompt_file="${RUNNER_TEMP}/opencode-conflict-prompt.md"
''',
    )
    replace_once(
        ".github/workflows/pr-review-autofix.yml",
        '''            restore_workspace_config
            trap - EXIT
          fi

          # Fail closed: never push unresolved conflict markers.
''',
        '''            restore_workspace_config
            trap - EXIT
          fi

          python "${GITHUB_WORKSPACE}/trusted-autofix-source/scripts/ci/pr_review_conflict_scope.py" verify \\
            --root "$TARGET_WORKSPACE" \\
            --snapshot "$conflict_scope_snapshot" \\
            --allowed-paths "$conflicted_paths_file"

          # Fail closed: never push unresolved conflict markers.
''',
    )


def apply_path_canonicalization() -> None:
    """Reject alternate spellings that can bypass exact path-set comparison."""
    replace_once(
        "scripts/ci/pr_review_conflict_scope.py",
        '''    path = Path(raw_path)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("repository path must be a normalized relative path")
    return raw_path
''',
        '''    path = Path(raw_path)
    normalized_path = path.as_posix()
    if (
        path.is_absolute()
        or normalized_path != raw_path
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("repository path must be a normalized relative path")
    return raw_path
''',
    )
    replace_once(
        "tests/test_pr_review_conflict_scope.py",
        '''    ["", "/absolute", "../escape", "nested/../escape"],
''',
        '''    [
        "",
        "/absolute",
        "../escape",
        "nested/../escape",
        "./relative",
        "a//b",
    ],
''',
    )


def apply_evidence_records() -> None:
    """Record the security boundary in permanent changelog and doctoring files."""
    replace_once(
        "CHANGELOG.md",
        "- Pin the repository-dispatch autofix helper checkout to the exact workflow-run SHA rather than a moving default branch.\n",
        "- Pin the repository-dispatch autofix helper checkout to the exact workflow-run SHA rather than a moving default branch.\n"
        "- Snapshot the post-merge worktree before the conflict-resolution model runs and fail closed before staging when the model creates, deletes, retargets, or edits any path outside Git's exact NUL-delimited conflict set.\n",
    )
    replace_once(
        "docs/doctoring/hourly-nvidia-nim-autofix.md",
        '''The workflow rejects any changed path
outside that allowlist, syntax-checks changed Python, validates workflow files
when `actionlint` is available, rechecks the live head before push, and refuses
to publish unresolved merge markers.
''',
        '''The workflow rejects any changed path
outside that allowlist, syntax-checks changed Python, validates workflow files
when `actionlint` is available, rechecks the live head before push, and refuses
to publish unresolved merge markers.

Conflict repair has a separate exact-write boundary. Immediately after the
protected-base merge, the worker records Git's NUL-delimited unmerged path set
and a deterministic SHA-256 snapshot of every tracked and non-ignored untracked
path. The snapshot records regular-file bytes, modes, symlink targets, missing
entries, and other filesystem objects without following symlinks. After
OpenCode exits and its temporary configuration is restored, the worker compares
the complete live worktree with that snapshot. Only the originally unmerged
paths may differ. Any unrelated creation, deletion, mode change, symlink
retarget, or content edit fails before `git add`, so prompt injection in a
conflict cannot broaden the write set. Paths must be canonical POSIX-style
repository-relative names; absolute, traversal-bearing, `./`-prefixed, and
repeated-separator forms fail closed.
''',
    )


def main() -> int:
    """Apply all permanent reviewed changes and return success."""
    apply_workflow_boundary()
    apply_path_canonicalization()
    apply_evidence_records()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
