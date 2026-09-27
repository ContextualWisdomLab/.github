"""Behavior and workflow contracts for merge-conflict autofix file scoping."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import pr_review_conflict_scope as scope


_WORKFLOW = Path(".github/workflows/pr-review-autofix.yml")


def _git(root: Path, *arguments: str) -> None:
    """Run one deterministic Git command in a temporary fixture repository."""
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path) -> Path:
    """Create a repository containing allowed, disallowed, and symlink paths."""
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "tests@example.invalid")
    _git(root, "config", "user.name", "Tests")
    (root / "conflicted.txt").write_text("conflict-before\n", encoding="utf-8")
    (root / "stable.txt").write_text("stable-before\n", encoding="utf-8")
    (root / "target-a.txt").write_text("a\n", encoding="utf-8")
    os.symlink("target-a.txt", root / "linked.txt")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


def _allowed_file(path: Path, *relative_paths: str) -> Path:
    """Write an authoritative NUL-delimited allowed-path list."""
    path.write_bytes(b"".join(os.fsencode(item) + b"\0" for item in relative_paths))
    return path


@pytest.mark.parametrize("root_kind", ["missing", "file", "symlink"])
def test_invalid_repository_roots_fail_closed(
    tmp_path: Path, root_kind: str
) -> None:
    """Missing, regular-file, and symbolic-link roots are never trusted."""
    root = tmp_path / "candidate"
    if root_kind == "file":
        root.write_text("not a directory", encoding="utf-8")
    elif root_kind == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        os.symlink(target, root)

    with pytest.raises(ValueError, match="non-symlink directory"):
        scope.build_snapshot(root)


def test_repository_root_under_symlink_parent_fails_closed(tmp_path: Path) -> None:
    """A symlink parent cannot redirect the canonical repository root."""
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    _repository(real_parent)
    linked_parent = tmp_path / "linked"
    os.symlink(real_parent, linked_parent)

    with pytest.raises(ValueError, match="non-symlink directory"):
        scope.build_snapshot(linked_parent / "repository")


@pytest.mark.parametrize(
    "raw_path",
    [
        "",
        "/absolute",
        "../escape",
        "nested/../escape",
        "./relative",
        "a//b",
    ],
)
def test_invalid_repository_relative_paths_fail_closed(raw_path: str) -> None:
    """Empty, absolute, and traversal-bearing path names are rejected."""
    with pytest.raises(ValueError, match="repository path"):
        scope._validated_relative_path(raw_path)


def test_repository_relative_path_byte_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path longer than the configured byte bound is rejected."""
    monkeypatch.setattr(scope, "_MAX_PATH_BYTES", 3)
    with pytest.raises(ValueError, match="byte limit"):
        scope._validated_relative_path("long")


def test_verify_snapshot_allows_only_the_declared_conflict_path(tmp_path: Path) -> None:
    """A model may change a conflicted file but no unrelated tracked file."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist", "conflicted.txt")
    scope.write_snapshot(root, snapshot)

    (root / "conflicted.txt").write_text("resolved\n", encoding="utf-8")
    assert scope.verify_snapshot(root, snapshot, allowed) == ()

    (root / "stable.txt").write_text("model-touched\n", encoding="utf-8")
    assert scope.verify_snapshot(root, snapshot, allowed) == ("stable.txt",)


def test_verify_snapshot_detects_new_deleted_and_symlink_paths(tmp_path: Path) -> None:
    """New, deleted, and retargeted non-conflict paths fail closed."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist", "conflicted.txt")
    (root / "target-b.txt").write_text("b\n", encoding="utf-8")
    scope.write_snapshot(root, snapshot)

    (root / "stable.txt").unlink()
    (root / "new.txt").write_text("new\n", encoding="utf-8")
    (root / "linked.txt").unlink()
    os.symlink("target-b.txt", root / "linked.txt")

    assert scope.verify_snapshot(root, snapshot, allowed) == (
        "linked.txt",
        "new.txt",
        "stable.txt",
    )


def test_snapshot_records_missing_and_other_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fingerprinting remains deterministic for missing and non-file entries."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "directory").mkdir()
    monkeypatch.setattr(scope, "_git_paths", lambda _root: ("directory", "missing"))

    snapshot = scope.build_snapshot(root)

    assert snapshot["entries"]["directory"]["kind"] == "other"
    assert snapshot["entries"]["missing"] == {"kind": "missing"}


def test_git_path_inventory_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An excessive repository path inventory is rejected before hashing."""
    root = _repository(tmp_path)
    monkeypatch.setattr(scope, "_MAX_PATHS", 1)
    with pytest.raises(ValueError, match="path limit"):
        scope.build_snapshot(root)


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"schema_version": 1, "entries": {}, "extra": True},
        {"schema_version": 2, "entries": {}},
        {"schema_version": 1, "entries": []},
        {"schema_version": 1, "entries": {"path": "invalid"}},
        {"schema_version": 1, "entries": {"path": {"kind": "invalid"}}},
        {
            "schema_version": 1,
            "entries": {"path": {"kind": "missing", "extra": True}},
        },
        {"schema_version": 1, "entries": {"../escape": {"kind": "missing"}}},
    ],
)
def test_invalid_snapshot_documents_fail_closed(
    tmp_path: Path, document: object
) -> None:
    """Malformed or unsupported snapshot documents never become approval evidence."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(document), encoding="utf-8")
    allowed = _allowed_file(tmp_path / "allowed.zlist", "conflicted.txt")

    with pytest.raises(ValueError, match="snapshot|repository path"):
        scope.verify_snapshot(root, snapshot, allowed)


@pytest.mark.parametrize("payload", [None, b"\xff", b"{"])
def test_undecodable_snapshot_inputs_fail_closed(
    tmp_path: Path, payload: bytes | None
) -> None:
    """Missing, non-UTF-8, and malformed JSON snapshots are rejected."""
    snapshot = tmp_path / "snapshot.json"
    if payload is not None:
        snapshot.write_bytes(payload)
    with pytest.raises(ValueError, match="snapshot document could not be decoded"):
        scope._load_snapshot(snapshot)


def test_valid_missing_and_other_fingerprints_round_trip(tmp_path: Path) -> None:
    """Supported non-file fingerprint schemas remain loadable and deterministic."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    "missing": {"kind": "missing"},
                    "other": {"kind": "other", "mode": 493},
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = scope._load_snapshot(snapshot)

    assert loaded["missing"] == {"kind": "missing"}
    assert loaded["other"] == {"kind": "other", "mode": 493}


def test_snapshot_entry_inventory_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A decoded snapshot cannot exceed the configured entry limit."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {"path": {"kind": "missing"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(scope, "_MAX_PATHS", 0)

    with pytest.raises(ValueError, match="snapshot entries exceed"):
        scope._load_snapshot(snapshot)


def test_unknown_allowed_path_fails_closed(tmp_path: Path) -> None:
    """The authoritative allowlist cannot name a path absent from the snapshot."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    scope.write_snapshot(root, snapshot)
    allowed = _allowed_file(tmp_path / "allowed.zlist", "not-in-snapshot.txt")

    with pytest.raises(ValueError, match="absent"):
        scope.verify_snapshot(root, snapshot, allowed)


def test_missing_allowed_path_file_fails_closed(tmp_path: Path) -> None:
    """A missing conflict-path inventory cannot authorize model changes."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    scope.write_snapshot(root, snapshot)

    with pytest.raises(ValueError, match="allowed-path inventory"):
        scope.verify_snapshot(root, snapshot, tmp_path / "missing.zlist")


def test_allowed_path_inventory_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An excessive conflict allowlist is rejected before comparison."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    scope.write_snapshot(root, snapshot)
    allowed = _allowed_file(tmp_path / "allowed.zlist", "a", "b")
    monkeypatch.setattr(scope, "_MAX_PATHS", 1)

    with pytest.raises(ValueError, match="path limit"):
        scope.verify_snapshot(root, snapshot, allowed)


def test_cli_reports_violation_and_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI returns a nonzero code only for a verified scope violation."""
    root = _repository(tmp_path)
    snapshot = tmp_path / "nested" / "snapshot.json"
    allowed = _allowed_file(tmp_path / "allowed.zlist", "conflicted.txt")

    assert scope.main(["snapshot", "--root", str(root), "--output", str(snapshot)]) == 0
    assert snapshot.is_file()
    (root / "stable.txt").write_text("changed\n", encoding="utf-8")
    assert (
        scope.main(
            [
                "verify",
                "--root",
                str(root),
                "--snapshot",
                str(snapshot),
                "--allowed-paths",
                str(allowed),
            ]
        )
        == 1
    )
    assert "stable.txt" in capsys.readouterr().err

    (root / "stable.txt").write_text("stable-before\n", encoding="utf-8")
    (root / "conflicted.txt").write_text("resolved\n", encoding="utf-8")
    assert (
        scope.main(
            [
                "verify",
                "--root",
                str(root),
                "--snapshot",
                str(snapshot),
                "--allowed-paths",
                str(allowed),
            ]
        )
        == 0
    )
    assert "verified" in capsys.readouterr().out.lower()


def test_workflow_snapshots_after_merge_and_verifies_before_staging() -> None:
    """The conflict worker enforces its model-write boundary before git add."""
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    conflict_start = workflow.index(
        "      - name: Merge base branch and resolve conflicts with OpenCode"
    )
    conflict = workflow[conflict_start:]
    merge = conflict.index('git merge --no-commit --no-ff "$PR_BASE_SHA"')
    snapshot = conflict.index("pr_review_conflict_scope.py\" snapshot")
    model = conflict.index('title "PR #${PR_NUMBER} merge conflict resolution"')
    verify = conflict.index("pr_review_conflict_scope.py\" verify")
    conflict_add = conflict.index("# Fail closed: never push unresolved conflict markers.")

    assert merge < snapshot < model < verify < conflict_add
    assert 'git diff --name-only -z --diff-filter=U >"$conflicted_paths_file"' in conflict
    assert '--allowed-paths "$conflicted_paths_file"' in conflict
