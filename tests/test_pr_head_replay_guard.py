"""Tests for the post-merge stale agent replay guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.ci import pr_head_replay_guard as guard


def git(repo: Path, *args: str) -> str:
    """Run git in a temporary fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def commit(repo: Path, message: str) -> str:
    """Commit the current fixture tree and return its SHA."""
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write(repo: Path, name: str, text: str) -> None:
    """Write one fixture file, creating parents."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def fixture_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Create base, feature, and base-merge commits for replay tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    write(repo, "feature.txt", "base\n")
    original_base = commit(repo, "base")

    git(repo, "checkout", "-b", "feature")
    write(repo, "feature.txt", "feature\n")
    original_head = commit(repo, "feature")

    git(repo, "checkout", "main")
    for index in range(6):
        write(repo, f"base-{index}.txt", "base line\n" * 100)
    current_base = commit(repo, "advance base")

    git(repo, "checkout", "feature")
    git(repo, "merge", "--no-ff", "--no-edit", "main")
    merge_anchor = git(repo, "rev-parse", "HEAD")
    assert original_base != current_base
    return repo, current_base, original_head, merge_anchor


def test_no_merge_anchor_passes(tmp_path, capsys):
    """A normal unmerged feature branch has no post-merge replay surface."""
    repo, current_base, original_head, _ = fixture_repo(tmp_path)
    evidence = guard.collect_evidence(repo, current_base, original_head)

    assert evidence.merge_anchor is None
    assert not evidence.blocked
    assert "no base-descended merge commit" in guard.format_report(evidence)
    assert guard.main(["--repo-root", str(repo), "--base-sha", current_base, "--head-sha", original_head]) == 0
    assert "Result: PASS" in capsys.readouterr().out


def test_head_at_merge_anchor_passes(tmp_path):
    """The merge commit itself has no later stale patch to inspect."""
    repo, current_base, _, merge_anchor = fixture_repo(tmp_path)
    evidence = guard.collect_evidence(repo, current_base, merge_anchor)

    assert evidence.merge_anchor == merge_anchor
    assert evidence.post_merge_commits == 0
    assert not evidence.blocked
    assert "current HEAD is the latest base merge anchor" in guard.format_report(evidence)


def test_exact_pre_merge_tree_replay_fails(tmp_path, capsys):
    """Rewriting the merge tree back to the original PR tree is blocked exactly."""
    repo, current_base, original_head, merge_anchor = fixture_repo(tmp_path)
    git(repo, "read-tree", "--reset", "-u", original_head)
    replay_head = commit(repo, "stale agent replay")

    evidence = guard.collect_evidence(repo, current_base, replay_head)

    assert evidence.merge_anchor == merge_anchor
    assert evidence.exact_replay_of == original_head
    assert evidence.suspicious_bulk_regression
    assert evidence.blocked
    assert evidence.removed_files == 6
    assert evidence.deleted_lines == 600
    assert guard.main(["--repo-root", str(repo), "--base-sha", current_base, "--head-sha", replay_head]) == 1
    report = capsys.readouterr().out
    assert "Result: FAIL" in report
    assert original_head in report


def test_partial_bulk_replay_fails_without_exact_tree_match(tmp_path):
    """A modified stale snapshot is still blocked by conservative deletion magnitude."""
    repo, current_base, original_head, _ = fixture_repo(tmp_path)
    git(repo, "read-tree", "--reset", "-u", original_head)
    write(repo, "marker.txt", "not an exact tree\n")
    replay_head = commit(repo, "partial stale replay")

    evidence = guard.collect_evidence(repo, current_base, replay_head)

    assert evidence.exact_replay_of is None
    assert evidence.suspicious_bulk_regression
    assert evidence.blocked
    assert "bulk-replay signature" in guard.format_report(evidence)


def test_small_post_merge_fix_passes_and_numstat_skips_binary(tmp_path):
    """A focused follow-up stays below thresholds and binary numstat is tolerated."""
    repo, current_base, _, _ = fixture_repo(tmp_path)
    write(repo, "feature.txt", "feature after merge\n")
    write(repo, "binary.bin", "\x00\x01\n")
    head = commit(repo, "focused follow-up")

    evidence = guard.collect_evidence(repo, current_base, head)

    assert evidence.post_merge_commits == 1
    assert evidence.exact_replay_of is None
    assert not evidence.suspicious_bulk_regression
    assert not evidence.blocked
    assert "conservative bulk-regression thresholds" in guard.format_report(evidence)


def test_bulk_threshold_requires_removed_files_lines_and_ratio():
    """Every conservative bulk-regression threshold is required."""
    common = {"base_sha": "base", "head_sha": "head", "merge_anchor": "merge", "post_merge_commits": 1}
    assert not guard.ReplayEvidence(**common, removed_files=4, deleted_lines=1000).suspicious_bulk_regression
    assert not guard.ReplayEvidence(**common, removed_files=5, deleted_lines=499).suspicious_bulk_regression
    assert not guard.ReplayEvidence(
        **common, removed_files=5, added_lines=200, deleted_lines=600
    ).suspicious_bulk_regression
    assert guard.ReplayEvidence(
        **common, removed_files=5, added_lines=0, deleted_lines=500
    ).suspicious_bulk_regression


def test_diff_statistics_skips_non_numeric_numstat(monkeypatch, tmp_path):
    """Binary or malformed numstat records do not create fake line counts."""
    outputs = iter(["gone-a\ngone-b", "-\t-\tbinary.bin\nmalformed\n3\t4\ttext.txt"])
    monkeypatch.setattr(guard, "git_output", lambda _root, _args: next(outputs))

    assert guard.diff_statistics(tmp_path, "a", "b") == (2, 3, 4)


def test_invalid_commit_fails_closed_with_reason(tmp_path, capsys):
    """Missing git evidence fails closed and exposes the exact git reason."""
    repo, _, _, _ = fixture_repo(tmp_path)

    result = guard.main(
        ["--repo-root", str(repo), "--base-sha", "missing", "--head-sha", "also-missing"]
    )

    assert result == 2
    output = capsys.readouterr().out
    assert "Result: FAIL" in output
    assert "replay evidence could not be evaluated" in output
