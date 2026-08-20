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
    outputs = iter([name_status, numstat])
    monkeypatch.setattr(guard, "git_output", lambda _root, _args: next(outputs))

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

    regressed, added_files, added_cases = guard.test_file_changes(tmp_path, "a", "b")

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
