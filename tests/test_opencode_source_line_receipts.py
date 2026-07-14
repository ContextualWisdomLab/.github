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
