"""Tests for trusted current-head source-line receipt generation."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from scripts.ci import adversarial_evidence
from scripts.ci import opencode_review_normalize_output as normalizer
from scripts.ci import opencode_source_line_receipts as receipts


def git(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
) -> str:
    """Run Git in a fixture repository and return stripped stdout."""
    return (
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        .stdout.decode("utf-8")
        .strip()
    )


def commit(repo: Path, message: str) -> str:
    """Commit all fixture changes and return the immutable commit SHA."""
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def init_repo(tmp_path: Path) -> Path:
    """Create a Git repository with deterministic local author metadata."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Receipt Test")
    git(repo, "config", "user.email", "receipt@example.invalid")
    return repo


def write_manifest(repo: Path, tmp_path: Path, base_sha: str, head_sha: str) -> Path:
    """Write the same newline-delimited changed-path shape used by the workflow."""
    manifest = tmp_path / "opencode-changed-files.txt"
    changed = git(
        repo,
        "diff",
        "--name-only",
        "--find-renames",
        base_sha,
        head_sha,
    )
    manifest.write_text(f"{changed}\n" if changed else "", encoding="utf-8")
    return manifest


def receipt_map(
    values: tuple[receipts.SourceLineReceipt, ...],
) -> dict[tuple[str, int], str]:
    """Index generated receipts by their exact path and positive line."""
    return {(value.path, value.line): value.digest for value in values}


def test_collects_modified_new_and_rename_receipts_with_exact_line_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Receipts use raw splitlines bytes and pass the trusted normalizer."""
    repo = init_repo(tmp_path)
    source = repo / "src" / "calculate_total.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"first\r\nvalue = 1\r\nlast\r\n")
    renamed = repo / "docs" / "old_name.md"
    renamed.parent.mkdir()
    renamed.write_text("stable documentation\n", encoding="utf-8")
    deleted = repo / "deleted.txt"
    deleted.write_text("removed\n", encoding="utf-8")
    base_sha = commit(repo, "base")

    changed_line = "caf\N{LATIN SMALL LETTER E WITH ACUTE} = 2".encode()
    source.write_bytes(b"first\r\n" + changed_line + b"\r\nlast\r\n")
    new_source = repo / "src" / "new_rule.py"
    new_source.write_bytes(b"first rule\n\nlast rule\n")
    git(repo, "mv", "docs/old_name.md", "docs/new_name.md")
    deleted.unlink()
    head_sha = commit(repo, "change sources")
    manifest = write_manifest(repo, tmp_path, base_sha, head_sha)

    generated, notices = receipts.collect_receipts(repo, base_sha, head_sha, manifest)
    indexed = receipt_map(generated)

    assert (
        indexed[("src/calculate_total.py", 2)]
        == hashlib.sha256(changed_line).hexdigest()
    )
    assert indexed[("src/new_rule.py", 1)] == hashlib.sha256(b"first rule").hexdigest()
    assert indexed[("src/new_rule.py", 3)] == hashlib.sha256(b"last rule").hexdigest()
    assert (
        indexed[("docs/new_name.md", 1)]
        == hashlib.sha256(b"stable documentation").hexdigest()
    )
    assert any("deleted.txt: deleted paths" in notice for notice in notices)

    selected = next(
        value
        for value in generated
        if value.path == "src/calculate_total.py" and value.line == 2
    )
    evidence = (
        f"source trace at {selected.path}:{selected.line} returned the changed value; "
        f"source-line-sha256={selected.digest}"
    )
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(repo))
    assert (
        normalizer.adversarial_probe_source_receipt_error(
            evidence, selected.path, selected.line
        )
        == ""
    )
    assert (
        adversarial_evidence.adversarial_evidence_rejection_reason(
            evidence, selected.path, selected.line
        )
        is None
    )


def test_rendered_packet_is_bounded_and_does_not_expose_source_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI exposes only receipts and explains their limited provenance."""
    repo = init_repo(tmp_path)
    source = repo / "src" / "secret_name.py"
    source.parent.mkdir(parents=True)
    source.write_text("old value\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    source.write_text("sensitive source body\n", encoding="utf-8")
    head_sha = commit(repo, "head")
    manifest = write_manifest(repo, tmp_path, base_sha, head_sha)

    result = receipts.main(
        [
            "--repo-root",
            str(repo),
            "--diff-base",
            base_sha,
            "--head-sha",
            head_sha,
            "--changed-files",
            str(manifest),
        ]
    )
    captured = capsys.readouterr()

    assert result == 0
    assert "- Result: PASS" in captured.out
    assert f"- Head SHA: `{head_sha}`" in captured.out
    assert "`src/secret_name.py:1` `source-line-sha256=" in captured.out
    assert "source-line binding only" in captured.out
    assert "sensitive source body" not in captured.out
    assert captured.err == ""


def test_repository_binding_rejects_wrong_head_nonancestor_and_dirty_tree(
    tmp_path: Path,
) -> None:
    """Receipts cannot be generated from a stale, unrelated, or modified tree."""
    repo = init_repo(tmp_path)
    source = repo / "source.py"
    source.write_text("base\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    source.write_text("head\n", encoding="utf-8")
    head_sha = commit(repo, "head")

    with pytest.raises(receipts.ReceiptError, match="does not match requested head"):
        receipts.validate_repository(repo, base_sha, base_sha)

    empty_tree = git(repo, "mktree", input_bytes=b"")
    unrelated_sha = git(repo, "commit-tree", empty_tree, "-m", "unrelated")
    with pytest.raises(receipts.ReceiptError, match="not an ancestor"):
        receipts.validate_repository(repo, unrelated_sha, head_sha)

    source.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="tracked modifications"):
        receipts.validate_repository(repo, base_sha, head_sha)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../outside.py",
        "/absolute.py",
        "safe\\windows.py",
        "double//slash.py",
        "quoted/`path.py",
        ".git/config",
        "control/\u0001.py",
    ],
)
def test_changed_manifest_rejects_unsafe_paths(
    tmp_path: Path, unsafe_path: str
) -> None:
    """Untrusted path syntax cannot escape or inject the Markdown receipt packet."""
    manifest = tmp_path / "opencode-changed-files.txt"
    manifest.write_text(f"{unsafe_path}\n", encoding="utf-8")

    with pytest.raises(receipts.ReceiptError, match="unsafe|control"):
        receipts.load_changed_paths(manifest)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_skips_symlink_binary_oversize_and_deleted_sources(tmp_path: Path) -> None:
    """Only safe regular bounded text files receive source-line receipts."""
    repo = init_repo(tmp_path)
    deleted = repo / "deleted.txt"
    deleted.write_text("delete me\n", encoding="utf-8")
    base_sha = commit(repo, "base")

    valid = repo / "src" / "valid.py"
    valid.parent.mkdir()
    valid.write_text("valid = True\n", encoding="utf-8")
    (repo / "linked.py").symlink_to("src/valid.py")
    (repo / "binary.dat").write_bytes(b"binary\0payload")
    (repo / "oversize.txt").write_bytes(b"x" * (receipts.MAX_SOURCE_BYTES + 1))
    deleted.unlink()
    head_sha = commit(repo, "unsafe sources")
    manifest = write_manifest(repo, tmp_path, base_sha, head_sha)

    generated, notices = receipts.collect_receipts(repo, base_sha, head_sha, manifest)

    assert {value.path for value in generated} == {"src/valid.py"}
    assert any("linked.py: path is a symlink" in notice for notice in notices)
    assert any("binary.dat: source file is binary" in notice for notice in notices)
    assert any("oversize.txt: source file exceeds" in notice for notice in notices)
    assert any("deleted.txt: deleted paths" in notice for notice in notices)


def test_collection_caps_are_deterministic_and_visible(tmp_path: Path) -> None:
    """Per-file and global bounds select stable paths and report truncation."""
    repo = init_repo(tmp_path)
    for name in ("a.py", "b.py", "c.py"):
        (repo / name).write_text("old\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    for name in ("a.py", "b.py", "c.py"):
        (repo / name).write_text(f"new {name}\n", encoding="utf-8")
    head_sha = commit(repo, "head")
    manifest = write_manifest(repo, tmp_path, base_sha, head_sha)

    generated, notices = receipts.collect_receipts(
        repo,
        base_sha,
        head_sha,
        manifest,
        max_per_file=1,
        max_total=2,
    )

    assert [(value.path, value.line) for value in generated] == [
        ("a.py", 1),
        ("b.py", 1),
    ]
    assert notices[-1] == "receipt output truncated at the global 2-receipt limit"


def test_deletion_only_cli_fails_closed_with_visible_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A PR with no current-head source line fails before model review with a reason."""
    repo = init_repo(tmp_path)
    deleted = repo / "deleted.py"
    deleted.write_text("gone = True\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    deleted.unlink()
    head_sha = commit(repo, "delete")
    manifest = write_manifest(repo, tmp_path, base_sha, head_sha)

    result = receipts.main(
        [
            "--repo-root",
            str(repo),
            "--diff-base",
            base_sha,
            "--head-sha",
            head_sha,
            "--changed-files",
            str(manifest),
        ]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert "- Result: UNAVAILABLE" in captured.out
    assert "deleted.py: deleted paths have no current-head source line" in captured.out
    assert "produced no eligible current-head lines" in captured.err


def test_git_and_sha_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git stderr and malformed immutable identities fail with bounded reasons."""
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=2, stdout=b"", stderr=b"bounded git failure"
    )
    monkeypatch.setattr(receipts.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(receipts.ReceiptError, match="bounded git failure"):
        receipts.git_bytes(tmp_path, "status")
    with pytest.raises(receipts.ReceiptError, match="40-character"):
        receipts.validated_sha("not-a-sha", "head SHA")


def test_repository_resolution_and_git_predicate_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repository binding rejects missing, nested, mismatched, and indeterminate trees."""
    missing = tmp_path / "missing"
    with pytest.raises(receipts.ReceiptError, match="could not be resolved"):
        receipts.validate_repository(missing, "a" * 40, "b" * 40)

    regular_file = tmp_path / "regular.txt"
    regular_file.write_text("not a repository\n", encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="must be a directory"):
        receipts.validate_repository(regular_file, "a" * 40, "b" * 40)

    repo = init_repo(tmp_path)
    source = repo / "source.py"
    source.write_text("base\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    source.write_text("head\n", encoding="utf-8")
    head_sha = commit(repo, "head")
    nested = repo / "nested"
    nested.mkdir()
    with pytest.raises(receipts.ReceiptError, match="worktree top level"):
        receipts.validate_repository(nested, base_sha, head_sha)

    real_git_bytes = receipts.git_bytes

    def mismatched_base(root: Path, *args: str) -> bytes:
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return f"{repo}\n".encode()
        if args[:3] == ("rev-parse", "--verify", "HEAD^{commit}"):
            return f"{head_sha}\n".encode()
        if args[:2] == ("rev-parse", "--verify"):
            return f"{'c' * 40}\n".encode()
        return real_git_bytes(root, *args)

    monkeypatch.setattr(receipts, "git_bytes", mismatched_base)
    with pytest.raises(receipts.ReceiptError, match="diff base did not resolve"):
        receipts.validate_repository(repo, base_sha, head_sha)

    monkeypatch.setattr(receipts, "git_bytes", real_git_bytes)
    monkeypatch.setattr(
        receipts, "git_returncode", lambda *args: (2, "predicate failed")
    )
    with pytest.raises(receipts.ReceiptError, match="verify diff-base ancestry"):
        receipts.validate_repository(repo, base_sha, head_sha)

    predicate_results = iter(((0, ""), (2, "cleanliness failed")))
    monkeypatch.setattr(
        receipts, "git_returncode", lambda *args: next(predicate_results)
    )
    with pytest.raises(receipts.ReceiptError, match="verify current-head worktree"):
        receipts.validate_repository(repo, base_sha, head_sha)


def test_manifest_boundaries_and_duplicates_fail_closed(tmp_path: Path) -> None:
    """Manifest materialization rejects unsafe file types, bytes, size, and duplicates."""
    with pytest.raises(receipts.ReceiptError, match="empty or oversized"):
        receipts.safe_changed_path("")

    target = tmp_path / "target.txt"
    target.write_text("safe.py\n", encoding="utf-8")
    symlink = tmp_path / "manifest-link.txt"
    symlink.symlink_to(target)
    with pytest.raises(receipts.ReceiptError, match="must not be a symlink"):
        receipts.load_changed_paths(symlink)

    with pytest.raises(receipts.ReceiptError, match="must be a regular file"):
        receipts.load_changed_paths(tmp_path)

    oversized = tmp_path / "oversized.txt"
    oversized.write_bytes(b"a" * (receipts.MAX_MANIFEST_BYTES + 1))
    with pytest.raises(receipts.ReceiptError, match="exceeds the bounded"):
        receipts.load_changed_paths(oversized)

    invalid_utf8 = tmp_path / "invalid-utf8.txt"
    invalid_utf8.write_bytes(b"source.py\n\xff")
    with pytest.raises(receipts.ReceiptError, match="could not be read"):
        receipts.load_changed_paths(invalid_utf8)

    duplicates = tmp_path / "duplicates.txt"
    duplicates.write_text("source.py\nsource.py\n", encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="duplicate path"):
        receipts.load_changed_paths(duplicates)


def test_diff_and_source_edge_cases_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-UTF paths, zero-line hunks, and unsafe source material stay unreceipted."""
    monkeypatch.setattr(receipts, "git_bytes", lambda *args: b"\xff\0")
    with pytest.raises(receipts.ReceiptError, match="non-UTF-8"):
        receipts.diff_paths(tmp_path, "a" * 40, "b" * 40, "ACMR")

    monkeypatch.setattr(receipts, "git_bytes", lambda *args: b"@@ -1 +1,0 @@\n-old\n")
    assert (
        receipts.changed_line_numbers(
            tmp_path, "a" * 40, "b" * 40, "source.py", limit=4
        )
        == ()
    )

    source_root = tmp_path / "source-root"
    source_root.mkdir()
    directory = source_root / "directory"
    directory.mkdir()
    with pytest.raises(receipts.SourceUnavailable, match="not a regular"):
        receipts.source_lines(source_root, "directory")
    with pytest.raises(receipts.SourceUnavailable, match="could not be read safely"):
        receipts.source_lines(source_root, "missing.py")

    empty = source_root / "empty.py"
    empty.write_bytes(b"")
    with pytest.raises(receipts.SourceUnavailable, match="no current-head lines"):
        receipts.source_lines(source_root, "empty.py")

    assert receipts.first_nonempty_line((b"", b"   ")) == 1
    with pytest.raises(receipts.ReceiptError, match="outside current-head"):
        receipts.source_line_receipt("source.py", 0, (b"line",))


def test_collection_bounds_manifest_mismatch_and_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Collection caps, immutable scope, and mode-only fallback remain deterministic."""
    repo = init_repo(tmp_path)
    source = repo / "source.py"
    source.write_text("first\nsecond\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    source.write_text("first\nchanged\n", encoding="utf-8")
    head_sha = commit(repo, "head")
    manifest = write_manifest(repo, tmp_path, base_sha, head_sha)

    with pytest.raises(receipts.ReceiptError, match="max_per_file"):
        receipts.collect_receipts(repo, base_sha, head_sha, manifest, max_per_file=0)
    with pytest.raises(receipts.ReceiptError, match="max_total"):
        receipts.collect_receipts(repo, base_sha, head_sha, manifest, max_total=0)

    mismatched_manifest = tmp_path / "mismatched.txt"
    mismatched_manifest.write_text("ghost.py\n", encoding="utf-8")
    with pytest.raises(receipts.ReceiptError, match="absent from the immutable diff"):
        receipts.collect_receipts(repo, base_sha, head_sha, mismatched_manifest)

    monkeypatch.setattr(receipts, "changed_line_numbers", lambda *args, **kwargs: ())
    generated, notices = receipts.collect_receipts(repo, base_sha, head_sha, manifest)
    assert [(value.path, value.line) for value in generated] == [("source.py", 1)]
    assert notices == ()


def test_cli_reports_trusted_generation_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI logs a bounded reason when immutable input validation fails."""
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("source.py\n", encoding="utf-8")

    result = receipts.main(
        [
            "--repo-root",
            str(tmp_path),
            "--diff-base",
            "a" * 40,
            "--head-sha",
            "invalid",
            "--changed-files",
            str(manifest),
        ]
    )
    captured = capsys.readouterr()

    assert result == 1
    assert "Trusted source-line receipt generation failed" in captured.err
