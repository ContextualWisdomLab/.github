"""Regression tests for test replacements inside existing files."""

from __future__ import annotations

from scripts.ci import pr_head_replay_guard as guard


def test_existing_test_file_can_supply_replacement_cases(monkeypatch, tmp_path):
    """A stronger refactor in an existing test file is valid replacement evidence."""
    name_status = "\n".join(
        [
            "M\ttests/test_old.py",
            "M\ttests/test_replacement.py",
        ]
    )
    numstat = "\n".join(
        [
            "1\t8\ttests/test_old.py",
            "8\t1\ttests/test_replacement.py",
        ]
    )

    def fake_git_output(_root, args):
        """Return the two diff views used by the replacement counter."""
        if args[:2] == ["diff", "--name-status"]:
            return name_status
        if args[:2] == ["diff", "--numstat"]:
            return numstat
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(guard, "git_output", fake_git_output)
    counts = {
        ("a", "tests/test_old.py"): 2,
        ("b", "tests/test_old.py"): 1,
        ("a", "tests/test_replacement.py"): 1,
        ("b", "tests/test_replacement.py"): 2,
    }
    monkeypatch.setattr(
        guard,
        "test_case_count",
        lambda _root, revision, path: counts[(revision, path)],
    )

    regressed, added_files = guard.test_file_changes(tmp_path, "a", "b")
    added_cases = guard.added_existing_test_cases(tmp_path, "a", "b")

    assert regressed == ("tests/test_old.py",)
    assert added_files == 0
    assert added_cases == 1
    evidence = guard.ReplayEvidence(
        base_sha="base",
        head_sha="head",
        merge_anchor="merge",
        post_merge_commits=1,
        regressed_test_paths=regressed,
        added_test_files=added_files,
        added_test_cases=added_cases,
    )
    assert not evidence.suspicious_test_regression
    assert not evidence.blocked
    assert "Added declared test cases in existing files: 1" in guard.format_report(evidence)


def test_existing_case_counter_ignores_non_growth_and_unevaluable_entries(
    monkeypatch,
    tmp_path,
):
    """Only supported existing test files with a positive case delta count as replacement."""
    numstat = "\n".join(
        [
            "malformed",
            "-\t-\ttests/blob.bin",
            "1\t-\ttests/blob2.bin",
            "3\t1\tsrc/app.py",
            "2\t2\ttests/test_same.py",
            "1\t5\ttests/test_missing_before.py",
            "5\t1\ttests/test_missing_after.py",
            "5\t1\ttests/test_shrunk.py",
        ]
    )
    monkeypatch.setattr(guard, "git_output", lambda _root, _args: numstat)
    counts = {
        ("a", "tests/test_same.py"): 1,
        ("b", "tests/test_same.py"): 1,
        ("a", "tests/test_missing_before.py"): None,
        ("b", "tests/test_missing_before.py"): 1,
        ("a", "tests/test_missing_after.py"): 1,
        ("b", "tests/test_missing_after.py"): None,
        ("a", "tests/test_shrunk.py"): 2,
        ("b", "tests/test_shrunk.py"): 1,
    }
    monkeypatch.setattr(
        guard,
        "test_case_count",
        lambda _root, revision, path: counts[(revision, path)],
    )

    assert guard.added_existing_test_cases(tmp_path, "a", "b") == 0
