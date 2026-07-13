"""Tests for changed-source JavaScript and TypeScript coverage evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.ci import javascript_coverage_gate as gate


def git(repo: Path, *args: str) -> str:
    """Run git in a fixture repository and return stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def commit(repo: Path, message: str) -> str:
    """Commit the fixture tree and return its SHA."""
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def fixture_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Create a repository with one changed TypeScript runtime line."""
    repo = tmp_path / "repo"
    source = repo / "src" / "calculate_total.ts"
    source.parent.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Coverage Test")
    git(repo, "config", "user.email", "coverage@example.invalid")
    source.write_text(
        "export function calculateTotal(left: number, right: number) {\n"
        "  return left + right;\n"
        "}\n",
        encoding="utf-8",
    )
    base_sha = commit(repo, "base")
    source.write_text(
        "export function calculateTotal(left: number, right: number) {\n"
        "  return left - right;\n"
        "}\n",
        encoding="utf-8",
    )
    head_sha = commit(repo, "change calculation")
    return repo, base_sha, head_sha


def write_coverage(
    repo: Path,
    *,
    statement_count: int,
    include_source: bool = True,
    branch_counts: list[int] | None = None,
) -> Path:
    """Write Istanbul final and deliberately low global summary evidence."""
    coverage_dir = repo / "coverage"
    coverage_dir.mkdir()
    source = repo / "src" / "calculate_total.ts"
    final_data = {}
    if include_source:
        final_data[str(source)] = {
            "statementMap": {
                "0": {
                    "start": {"line": 2, "column": 2},
                    "end": {"line": 2, "column": 22},
                }
            },
            "s": {"0": statement_count},
            "fnMap": {
                "0": {
                    "name": "calculateTotal",
                    "decl": {
                        "start": {"line": 1, "column": 0},
                        "end": {"line": 1, "column": 30},
                    },
                    "loc": {
                        "start": {"line": 1, "column": 0},
                        "end": {"line": 3, "column": 1},
                    },
                }
            },
            "f": {"0": statement_count},
            "branchMap": (
                {
                    "0": {
                        "type": "if",
                        "locations": [
                            {
                                "start": {"line": 2, "column": 2},
                                "end": {"line": 2, "column": 22},
                            },
                            {
                                "start": {"line": 2, "column": 2},
                                "end": {"line": 2, "column": 22},
                            },
                        ],
                    }
                }
                if branch_counts is not None
                else {}
            ),
            "b": {"0": branch_counts} if branch_counts is not None else {},
        }
    (coverage_dir / "coverage-final.json").write_text(
        json.dumps(final_data), encoding="utf-8"
    )
    (coverage_dir / "coverage-summary.json").write_text(
        json.dumps(
            {
                "total": {
                    metric: {"pct": 42.0}
                    for metric in ("statements", "branches", "functions", "lines")
                }
            }
        ),
        encoding="utf-8",
    )
    summary_list = repo / "coverage-files.txt"
    summary_list.write_text(
        "coverage/coverage-summary.json\ncoverage/coverage-final.json\n",
        encoding="utf-8",
    )
    return summary_list


def run_gate(repo: Path, base_sha: str, head_sha: str, summary_list: Path) -> int:
    """Run the coverage gate against one fixture repository."""
    return gate.main(
        [
            "--repo-root",
            str(repo),
            "--base-sha",
            base_sha,
            "--head-sha",
            head_sha,
            "--summary-list",
            str(summary_list),
        ]
    )


def test_low_global_coverage_is_advisory_when_changed_units_are_covered(
    tmp_path: Path, capsys
) -> None:
    repo, base_sha, head_sha = fixture_repo(tmp_path)
    summary_list = write_coverage(repo, statement_count=1)

    assert run_gate(repo, base_sha, head_sha, summary_list) == 0
    report = capsys.readouterr().out
    assert "Global coverage advisory" in report
    assert "statements: 42.0%" in report
    assert "src/calculate_total.ts: statements 1/1" in report
    assert "Result: PASS" in report


def test_uncovered_changed_statement_fails_with_file_and_metric(
    tmp_path: Path, capsys
) -> None:
    repo, base_sha, head_sha = fixture_repo(tmp_path)
    summary_list = write_coverage(repo, statement_count=0)

    assert run_gate(repo, base_sha, head_sha, summary_list) == 1
    report = capsys.readouterr().out
    assert "src/calculate_total.ts: statements 0/1" in report
    assert "changed statements coverage is 0/1" in report
    assert "Result: FAIL" in report


def test_partially_covered_changed_branch_fails(tmp_path: Path, capsys) -> None:
    repo, base_sha, head_sha = fixture_repo(tmp_path)
    summary_list = write_coverage(
        repo,
        statement_count=1,
        branch_counts=[1, 0],
    )

    assert run_gate(repo, base_sha, head_sha, summary_list) == 1
    report = capsys.readouterr().out
    assert "src/calculate_total.ts: statements 1/1, branches 1/2" in report
    assert "changed branches coverage is 1/2" in report
    assert "Result: FAIL" in report


def test_changed_runtime_source_missing_from_instrumentation_fails(
    tmp_path: Path, capsys
) -> None:
    repo, base_sha, head_sha = fixture_repo(tmp_path)
    summary_list = write_coverage(repo, statement_count=0, include_source=False)

    assert run_gate(repo, base_sha, head_sha, summary_list) == 1
    report = capsys.readouterr().out
    assert "src/calculate_total.ts is absent from coverage-final.json" in report
    assert "Result: FAIL" in report


def test_test_only_change_has_explicit_not_applicable_result(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    test_file = repo / "src" / "calculate_total.test.ts"
    test_file.parent.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Coverage Test")
    git(repo, "config", "user.email", "coverage@example.invalid")
    test_file.write_text("test('base', () => {});\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    test_file.write_text("test('changed', () => {});\n", encoding="utf-8")
    head_sha = commit(repo, "test only")
    summary_list = write_coverage(repo, statement_count=0, include_source=False)

    assert run_gate(repo, base_sha, head_sha, summary_list) == 0
    report = capsys.readouterr().out
    assert "No changed JavaScript/TypeScript runtime source files" in report
    assert "Result: PASS" in report
