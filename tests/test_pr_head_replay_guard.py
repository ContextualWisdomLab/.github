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


def test_diff_evidence_overrides_repository_submodule_ignore_setting(tmp_path):
    """Replay evidence includes changed gitlinks despite a hostile local config."""
    submodule = tmp_path / "submodule"
    submodule.mkdir()
    git(submodule, "init", "-b", "main")
    git(submodule, "config", "user.name", "Test")
    git(submodule, "config", "user.email", "test@example.com")
    write(submodule, "payload.txt", "first\n")
    first_submodule_commit = commit(submodule, "submodule first")
    write(submodule, "payload.txt", "second\n")
    second_submodule_commit = commit(submodule, "submodule second")
    git(submodule, "checkout", first_submodule_commit)

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", str(submodule), "vendor/fixture")
    git(repo, "commit", "-m", "add submodule")
    base = git(repo, "rev-parse", "HEAD")
    git(repo / "vendor/fixture", "checkout", second_submodule_commit)
    git(repo, "add", "vendor/fixture")
    git(repo, "commit", "-m", "advance submodule")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "config", "diff.ignoreSubmodules", "all")

    assert first_submodule_commit != second_submodule_commit
    assert guard.git_output(repo, ["diff", "--name-only", base, head]) == "vendor/fixture"


def fixture_repo_with_base_tests(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a merged PR whose base merge brought a wrapper and its regression test."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    write(repo, "feature.txt", "base\n")
    commit(repo, "base")

    git(repo, "checkout", "-b", "feature")
    write(repo, "feature.txt", "feature\n")
    write(repo, "tests/test_feature.py", "def test_feature():\n    assert True\n    assert True\n\n\ndef test_edge():\n    assert True\n")
    commit(repo, "feature with tests")

    git(repo, "checkout", "main")
    write(repo, "src/wrapper.py", "def wrap():\n    return 'accessible'\n")
    write(repo, "tests/test_wrapper.py", "def test_wrap():\n    assert True\n")
    current_base = commit(repo, "base adds wrapper and regression test")

    git(repo, "checkout", "feature")
    git(repo, "merge", "--no-ff", "--no-edit", "main")
    merge_anchor = git(repo, "rev-parse", "HEAD")
    return repo, current_base, merge_anchor


def test_targeted_unmerge_of_base_work_fails_below_bulk_thresholds(tmp_path, capsys):
    """A small stale revert that drops base-merged files is blocked and named."""
    repo, current_base, merge_anchor = fixture_repo_with_base_tests(tmp_path)
    (repo / "src/wrapper.py").unlink()
    (repo / "tests/test_wrapper.py").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "stale targeted revert")
    head = git(repo, "rev-parse", "HEAD")

    evidence = guard.collect_evidence(repo, current_base, head)

    assert evidence.merge_anchor == merge_anchor
    assert evidence.unmerged_paths == ("src/wrapper.py", "tests/test_wrapper.py")
    assert evidence.unmerges_base_work
    assert evidence.regressed_test_paths == ("tests/test_wrapper.py",)
    assert evidence.suspicious_test_regression
    assert not evidence.suspicious_bulk_regression
    assert evidence.blocked
    assert guard.main(["--repo-root", str(repo), "--base-sha", current_base, "--head-sha", head]) == 1
    report = capsys.readouterr().out
    assert "Result: FAIL" in report
    assert "unmerged base work" in report
    assert "src/wrapper.py" in report
    assert "tests/test_wrapper.py" in report


def test_shrunk_test_without_replacement_fails(tmp_path):
    """Weakening an existing test file with no new test file is blocked."""
    repo, current_base, _ = fixture_repo_with_base_tests(tmp_path)
    write(repo, "tests/test_feature.py", "def test_feature():\n    assert True\n")
    head = commit(repo, "swap regression test for weaker one")

    evidence = guard.collect_evidence(repo, current_base, head)

    assert evidence.unmerged_paths == ()
    assert evidence.regressed_test_paths == ("tests/test_feature.py",)
    assert evidence.suspicious_test_regression
    assert evidence.blocked
    assert "reduced declared test cases" in guard.format_report(evidence)


def test_duplicate_assertion_cleanup_without_test_case_loss_passes(tmp_path):
    """Removing duplicate assertions while preserving test cases is not stale replay."""
    repo, current_base, _ = fixture_repo_with_base_tests(tmp_path)
    write(
        repo,
        "tests/test_feature.py",
        "def test_feature():\n    assert True\n\n\ndef test_edge():\n    assert True\n",
    )
    head = commit(repo, "remove duplicate assertion")

    evidence = guard.collect_evidence(repo, current_base, head)

    assert evidence.regressed_test_paths == ()
    assert evidence.unmerged_paths == ()
    assert not evidence.blocked


def test_test_refactor_with_replacement_passes(tmp_path):
    """Deleting a test while adding a replacement test file is not blocked."""
    repo, current_base, _ = fixture_repo_with_base_tests(tmp_path)
    (repo / "tests/test_feature.py").unlink()
    write(repo, "tests/test_feature_v2.py", "def test_feature_v2():\n    assert True\n\n\ndef test_edge_v2():\n    assert True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "rename test module")
    head = git(repo, "rev-parse", "HEAD")

    evidence = guard.collect_evidence(repo, current_base, head)

    assert evidence.regressed_test_paths == ("tests/test_feature.py",)
    assert evidence.added_test_files == 1
    assert not evidence.suspicious_test_regression
    assert evidence.unmerged_paths == ()
    assert not evidence.blocked


def test_is_test_path_covers_common_layouts():
    """Test-path detection recognizes directories, prefixes, suffixes, and spec names."""
    assert guard.is_test_path("tests/test_guard.py")
    assert guard.is_test_path("pkg/__tests__/button.js")
    assert guard.is_test_path("test_guard.py")
    assert guard.is_test_path("pkg/guard_test.go")
    assert guard.is_test_path("app/button.spec.ts")
    assert guard.is_test_path("app/button.test.tsx")
    assert guard.is_test_path("tests\\test_windows.py")
    assert not guard.is_test_path("scripts/ci/guard.py")
    assert not guard.is_test_path("docs/testing.md")


def test_test_case_count_fails_closed_and_supports_known_formats(
    monkeypatch,
    tmp_path,
):
    """Missing, invalid, supported, and unsupported test sources are classified."""

    def missing_source(_root, _args):
        raise RuntimeError("missing revision")

    monkeypatch.setattr(guard, "git_output", missing_source)
    assert guard.test_case_count(tmp_path, "base", "tests/test_missing.py") is None

    monkeypatch.setattr(
        guard,
        "git_output",
        lambda _root, _args: "def test_broken(",
    )
    assert guard.test_case_count(tmp_path, "base", "tests/test_broken.py") is None

    monkeypatch.setattr(
        guard,
        "git_output",
        lambda _root, _args: "def test_ok():\n    assert True\n",
    )
    assert guard.test_case_count(tmp_path, "base", "tests/test_ok.py") == 1

    supported_sources = (
        ("tests/guard.bats", '@test "works" {\n  true\n}\n'),
        ("tests/guard.go", "func TestGuard(t *testing.T) {}\n"),
        ("tests/guard.test.js", "test.concurrent.each(cases)('works', () => {});\n"),
        ("tests/guard.test.jsx", "it.only('works', () => {});\n"),
        ("tests/test_guard.R", "testthat::test_that('works', { expect_true(TRUE) })\n"),
        ("tests/guard_test.rs", "#[tokio::test]\nasync fn works() {}\n"),
        ("tests/guard.test.ts", "test.skip('works', () => {});\n"),
        ("tests/guard.test.tsx", "it.todo('works');\n"),
    )
    for path, source in supported_sources:
        monkeypatch.setattr(
            guard,
            "git_output",
            lambda _root, _args, source=source: source,
        )
        assert guard.test_case_count(tmp_path, "base", path) == 1

    assert guard.test_case_count(tmp_path, "base", "tests/README.md") is None


def test_signal_properties_require_their_evidence():
    """Unmerge and test-regression signals fire only on their exact evidence."""
    common = {"base_sha": "base", "head_sha": "head", "merge_anchor": "merge", "post_merge_commits": 1}
    assert not guard.ReplayEvidence(**common).blocked
    assert guard.ReplayEvidence(**common, unmerged_paths=("a.py",)).blocked
    assert guard.ReplayEvidence(**common, regressed_test_paths=("tests/test_a.py",)).blocked
    assert not guard.ReplayEvidence(
        **common, regressed_test_paths=("tests/test_a.py",), added_test_files=1
    ).blocked


def test_summarize_paths_bounds_long_lists():
    """Path lists in reports are capped with an explicit overflow count."""
    paths = [f"tests/test_{index}.py" for index in range(12)]
    summary = guard.summarize_paths(paths)
    assert summary.endswith("(+2 more)")
    assert "tests/test_9.py" in summary
    assert guard.summarize_paths(["one.py"]) == "one.py"


def test_test_file_changes_parses_status_and_numstat(monkeypatch, tmp_path):
    """Deleted, weakened, added, malformed, and non-test records are classified."""
    name_status = "\n".join(
        [
            "D\ttests/test_gone.py",
            "A\ttests/test_new.py",
            "M\ttests/test_kept.py",
            "D\tsrc/app_old.py",
            "badline",
        ]
    )
    numstat = "\n".join(
        [
            "1\t5\ttests/test_shrunk.py",
            "5\t1\ttests/test_grown.py",
            "-\t-\ttests/blob.bin",
            "2\t9\tsrc/big.py",
        ]
    )
    outputs = iter([name_status, numstat])
    monkeypatch.setattr(guard, "git_output", lambda _root, _args: next(outputs))
    monkeypatch.setattr(
        guard,
        "test_case_count",
        lambda _root, revision, _path: 2 if revision == "a" else 1,
    )

    regressed, added = guard.test_file_changes(tmp_path, "a", "b")

    assert regressed == ("tests/test_gone.py", "tests/test_shrunk.py")
    assert added == 1


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
