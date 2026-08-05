"""Apply and self-remove the reviewed PR 782 conflict-scope repair.

This one-shot branch helper edits only the permanent workflow, tests, changelog,
and doctoring records required for the exact merge-conflict model write boundary.
The GitHub Actions caller runs the permanent focused suite before publishing the
result and removes this helper from the final pull-request tree.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent


WORKFLOW_PATH = Path(".github/workflows/pr-review-autofix.yml")
TEST_PATH = Path("tests/test_pr_review_conflict_scope.py")
DOCTORING_PATH = Path("docs/doctoring/hourly-nvidia-nim-autofix.md")
CHANGELOG_PATH = Path("CHANGELOG.md")
HELPER_WORKFLOW_PATH = Path(".github/workflows/repair-pr782-conflict-scope.yml")
HELPER_SCRIPT_PATH = Path("scripts/ci/repair_pr782_conflict_scope_once.py")


def _replace_exact(source: str, old: str, new: str, *, label: str) -> str:
    """Replace one exact source fragment or fail closed on drift."""
    if source.count(old) != 1:
        raise RuntimeError(f"expected exactly one {label} fragment")
    return source.replace(old, new, 1)


def _repair_workflow() -> None:
    """Bind model writes to Git's exact merge-conflict path allowlist."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    conflict_start = dedent(
        '''\
          if [ -n "$conflicted_files" ]; then
            prompt_file="${RUNNER_TEMP}/opencode-conflict-prompt.md"
        '''
    )
    bounded_conflict_start = dedent(
        '''\
          if [ -n "$conflicted_files" ]; then
            conflicted_paths_file="${RUNNER_TEMP}/opencode-conflicted-files.zlist"
            conflict_scope_snapshot="${RUNNER_TEMP}/opencode-conflict-workspace-before.json"
            git diff --name-only -z --diff-filter=U >"$conflicted_paths_file"
            python3 "$GITHUB_WORKSPACE/trusted-autofix-source/scripts/ci/pr_review_conflict_scope.py" snapshot \
              --root "$TARGET_WORKSPACE" \
              --output "$conflict_scope_snapshot"
            prompt_file="${RUNNER_TEMP}/opencode-conflict-prompt.md"
        '''
    )
    workflow = _replace_exact(
        workflow,
        conflict_start,
        bounded_conflict_start,
        label="conflict-model entry",
    )

    model_end = dedent(
        '''\
            restore_workspace_config
            trap - EXIT
          fi

          # Fail closed: never push unresolved conflict markers.
        '''
    )
    bounded_model_end = dedent(
        '''\
            restore_workspace_config
            trap - EXIT
            python3 "$GITHUB_WORKSPACE/trusted-autofix-source/scripts/ci/pr_review_conflict_scope.py" verify \
              --root "$TARGET_WORKSPACE" \
              --snapshot "$conflict_scope_snapshot" \
              --allowed-paths "$conflicted_paths_file"
          fi

          # Fail closed: never push unresolved conflict markers.
        '''
    )
    workflow = _replace_exact(
        workflow,
        model_end,
        bounded_model_end,
        label="conflict-model completion",
    )
    WORKFLOW_PATH.write_text(workflow, encoding="utf-8")


def _extend_edge_case_tests() -> None:
    """Cover every fail-closed branch in the permanent conflict-scope helper."""
    tests = TEST_PATH.read_text(encoding="utf-8")
    marker = "def test_invalid_repository_and_path_inputs_fail_closed("
    if marker in tests:
        return
    tests += dedent(
        '''


def test_invalid_repository_and_path_inputs_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject missing or symbolic roots and malformed repository paths."""
    with pytest.raises(ValueError, match="repository root"):
        scope.build_snapshot(tmp_path / "missing")

    root = tmp_path / "root"
    root.mkdir()
    root_link = tmp_path / "root-link"
    os.symlink(root, root_link)
    with pytest.raises(ValueError, match="repository root"):
        scope.build_snapshot(root_link)

    with pytest.raises(ValueError, match="empty"):
        scope._validated_relative_path("")
    monkeypatch.setattr(scope, "_MAX_PATH_BYTES", 1)
    with pytest.raises(ValueError, match="byte limit"):
        scope._validated_relative_path("ab")
    monkeypatch.setattr(scope, "_MAX_PATH_BYTES", 4_096)
    for unsafe_path in ("/absolute", "../escape", "nested/../escape"):
        with pytest.raises(ValueError, match="normalized relative"):
            scope._validated_relative_path(unsafe_path)


def test_post_normalization_path_limit_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defend against a hostile Sequence that under-reports its length."""

    class MisreportedPaths:
        """Yield two paths while deliberately reporting a length of one."""

        def __len__(self) -> int:
            """Return the hostile under-reported length."""
            return 1

        def __iter__(self):
            """Yield more elements than ``__len__`` reports."""
            return iter(("a", "b"))

    monkeypatch.setattr(scope, "_MAX_PATHS", 1)
    with pytest.raises(ValueError, match="path limit"):
        scope._bounded_paths(  # type: ignore[arg-type]
            MisreportedPaths(), source_name="hostile inventory"
        )


def test_snapshot_decode_schema_and_entry_limits_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject undecodable, extra-field, oversized, and non-string-key snapshots."""
    root = _repository(tmp_path)
    allowed = _allowed_file(tmp_path / "allowed.zlist", "conflicted.txt")
    snapshot = tmp_path / "snapshot.json"

    snapshot.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="decoded"):
        scope.verify_snapshot(root, snapshot, allowed)

    snapshot.write_text(
        json.dumps({"schema_version": 1, "entries": {}, "extra": True}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unexpected fields"):
        scope.verify_snapshot(root, snapshot, allowed)

    snapshot.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "a": {"kind": "missing"},
                    "b": {"kind": "missing"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(scope, "_MAX_PATHS", 1)
    with pytest.raises(ValueError, match="entries exceed"):
        scope.verify_snapshot(root, snapshot, allowed)

    monkeypatch.setattr(scope, "_MAX_PATHS", 100_000)
    monkeypatch.setattr(
        scope.json,
        "loads",
        lambda _payload: {
            "schema_version": 1,
            "entries": {1: {"kind": "missing"}},
        },
    )
    with pytest.raises(ValueError, match="path keys"):
        scope.verify_snapshot(root, snapshot, allowed)


def test_snapshot_fingerprint_schema_and_allowed_file_errors_fail_closed(
    tmp_path: Path,
) -> None:
    """Reject unknown fingerprint forms and unreadable conflict inventories."""
    for invalid in (
        {"kind": "unknown"},
        {"kind": "missing", "extra": True},
    ):
        with pytest.raises(ValueError, match="fingerprint schema"):
            scope._validated_fingerprint(invalid)

    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    scope.write_snapshot(root, snapshot)
    with pytest.raises(ValueError, match="allowed-path inventory"):
        scope.verify_snapshot(root, snapshot, tmp_path / "missing.zlist")
        '''
    )
    TEST_PATH.write_text(tests, encoding="utf-8")


def _update_documentation() -> None:
    """Record the operational conflict-scope boundary and release note."""
    doctoring = DOCTORING_PATH.read_text(encoding="utf-8")
    marker = "\n## GitHub write boundary\n"
    section = dedent(
        '''
        ## Conflict-resolution model write boundary

        A merge-conflict repair begins by merging the exact validated base SHA into the
        exact PR head. Immediately after Git records the unresolved paths, the worker
        writes two immutable local inputs before OpenCode receives the task:

        1. a NUL-delimited allowlist produced by `git diff --name-only -z
           --diff-filter=U`; and
        2. a deterministic snapshot of every tracked and non-ignored untracked
           worktree path after the base merge.

        The snapshot fingerprints regular-file content with SHA-256 and records file
        size, mode, symbolic-link target, deletion, and other entry types. This timing
        is deliberate: legitimate non-conflict changes introduced by the base merge are
        part of the pre-model baseline, while changes made later by the model are not.

        After OpenCode exits, the workflow restores the repository's prior OpenCode
        configuration and compares the current worktree to that pre-model snapshot.
        Only paths in Git's NUL-delimited conflict allowlist may differ. A created,
        deleted, modified, mode-changed, or retargeted path outside that set fails the
        job before `git add -A`, commit, or push. Path inventories and path byte lengths
        are bounded, malformed snapshot data fails closed, and diagnostic output JSON-
        escapes path names rather than emitting them as workflow commands.

        Ignored build caches are outside the comparison because `git add -A` does not
        publish them. Git metadata is also outside the model's file-edit surface; the
        model process has no shell, GitHub token, or Actions OIDC credential. The later
        live-head, unresolved-marker, merge-tree, syntax, and push checks remain
        independent defenses.
        '''
    )
    if "## Conflict-resolution model write boundary" not in doctoring:
        if doctoring.count(marker) != 1:
            raise RuntimeError("expected exactly one GitHub write-boundary heading")
        doctoring = doctoring.replace(marker, "\n" + section + marker, 1)
        DOCTORING_PATH.write_text(doctoring, encoding="utf-8")

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    anchor = "### Security\n\n"
    bullet = (
        "- Snapshot the post-merge worktree before OpenCode conflict repair "
        "and reject every model-caused changed, created, deleted, or "
        "retargeted path outside Git's exact conflict allowlist before "
        "staging or push.\n"
    )
    if bullet not in changelog:
        if changelog.count(anchor) != 1:
            raise RuntimeError("expected exactly one changelog Security heading")
        CHANGELOG_PATH.write_text(
            changelog.replace(anchor, anchor + bullet, 1), encoding="utf-8"
        )


def main() -> None:
    """Apply the permanent repair and remove both temporary branch helpers."""
    _repair_workflow()
    _extend_edge_case_tests()
    _update_documentation()
    HELPER_WORKFLOW_PATH.unlink()
    HELPER_SCRIPT_PATH.unlink()


if __name__ == "__main__":
    main()
