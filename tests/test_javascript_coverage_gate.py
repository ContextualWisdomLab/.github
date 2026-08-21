"""Tests for changed-source JavaScript and TypeScript coverage evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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
        "\ncoverage/coverage-summary.json\ncoverage/coverage-final.json\n",
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


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "tests/runtime.ts",
        "src/runtime.d.ts",
        "vite.config.ts",
    ],
)
def test_non_runtime_javascript_paths_are_explicitly_excluded(path: str) -> None:
    assert not gate.is_runtime_source(path)


def test_git_command_error_is_scrubbed_into_runtime_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="fatal:"):
        gate.git(tmp_path, "status")


def test_changed_file_enumeration_error_is_visible(monkeypatch, tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess(
        args=["git"],
        returncode=1,
        stdout=b"",
        stderr=b"enumeration failed",
    )
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: completed)

    with pytest.raises(RuntimeError, match="enumeration failed"):
        gate.changed_runtime_lines(tmp_path, "base", "head")


def test_git_commands_mark_only_the_validated_repo_as_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def capture(command: list[str], **_kwargs) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(gate.subprocess, "run", capture)

    assert gate.git(tmp_path, "status") == ""
    assert gate.changed_runtime_lines(tmp_path, "base", "head") == {}

    resolved = tmp_path.resolve()
    expected_prefix = [
        "git",
        "-c",
        f"safe.directory={resolved}",
        "-C",
        str(resolved),
    ]
    assert len(commands) == 2
    assert all(command[:5] == expected_prefix for command in commands)
    assert commands[0][5:] == ["status"]
    assert commands[1][5:] == [
        "diff",
        "--name-only",
        "-z",
        "--diff-filter=ACMR",
        "base",
        "head",
    ]


def test_invalid_istanbul_locations_do_not_intersect() -> None:
    assert gate.location_range(None) is None
    assert gate.location_range({"start": {"line": "two"}}) is None
    assert gate.location_range({"start": {"line": 2}, "end": {}}) == (2, 2)
    assert not gate.intersects(None, {2})
    assert gate.intersects(
        {"start": {"line": 2}, "end": {"line": 4}},
        {4},
    )


def test_unmapped_and_unchanged_istanbul_units_are_ignored() -> None:
    invalid = {"start": {}, "end": {}}
    unchanged = {"start": {"line": 10}, "end": {"line": 10}}
    record = {
        "statementMap": {"invalid": invalid, "unchanged": unchanged},
        "s": {"invalid": 1, "unchanged": 1},
        "fnMap": {
            "invalid": {"loc": invalid},
            "unchanged": {"name": "unchanged", "loc": unchanged},
        },
        "f": {"invalid": 1, "unchanged": 1},
        "branchMap": {
            "invalid": {"type": "if", "locations": [invalid]},
            "unchanged": {"type": "if", "loc": unchanged},
        },
        "b": {"invalid": [1], "unchanged": [1]},
    }

    assert gate.changed_metric_counts([record], {2}) == {
        metric: (0, 0) for metric in gate.METRICS
    }


def test_coverage_path_normalization_handles_relative_suffix_and_ambiguity(
    tmp_path: Path,
) -> None:
    changed = {"frontend/src/runtime.ts"}
    assert (
        gate.normalize_coverage_path(
            "./frontend/src/runtime.ts", tmp_path, changed
        )
        == "frontend/src/runtime.ts"
    )
    assert (
        gate.normalize_coverage_path(
            "/different/root/frontend/src/runtime.ts", tmp_path, changed
        )
        == "frontend/src/runtime.ts"
    )
    assert (
        gate.normalize_coverage_path(
            "/different/root/src/runtime.ts",
            tmp_path,
            {"frontend/src/runtime.ts", "backend/src/runtime.ts"},
        )
        is None
    )
    assert (
        gate.normalize_coverage_path(
            str(tmp_path.parent / "outside" / "not-a-match.ts"),
            tmp_path,
            {"frontend/src/runtime.ts"},
        )
        is None
    )


def test_runtime_line_classifier_distinguishes_types_comments_and_code(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "runtime.ts"
    source.parent.mkdir()
    source.write_text(
        "\n"
        "/* block\n"
        " * comment\n"
        " */\n"
        "// line comment\n"
        "interface RuntimeShape {\n"
        "}\n"
        "export type RuntimeId = string;\n"
        "import type { Runtime } from './types';\n"
        "const runtimeValue = 1;\n",
        encoding="utf-8",
    )

    assert gate.likely_runtime_lines(
        tmp_path, "src/runtime.ts", set(range(1, 11))
    ) == [10]


def test_missing_or_invalid_coverage_evidence_fails_closed(
    tmp_path: Path, capsys
) -> None:
    missing = tmp_path / "missing.txt"
    assert gate.main(
        [
            "--repo-root",
            str(tmp_path),
            "--base-sha",
            "base",
            "--head-sha",
            "head",
            "--summary-list",
            str(missing),
        ]
    ) == 1
    assert "coverage evidence could not be evaluated" in capsys.readouterr().out


def test_changed_source_requires_coverage_final_json(
    tmp_path: Path, capsys
) -> None:
    repo, base_sha, head_sha = fixture_repo(tmp_path)
    coverage_dir = repo / "coverage"
    coverage_dir.mkdir()
    summary = coverage_dir / "coverage-summary.json"
    summary.write_text(
        json.dumps({"total": {metric: {"pct": 100} for metric in gate.METRICS}}),
        encoding="utf-8",
    )
    summary_list = repo / "coverage-files.txt"
    summary_list.write_text("coverage/coverage-summary.json\n", encoding="utf-8")

    assert run_gate(repo, base_sha, head_sha, summary_list) == 1
    assert "coverage-final.json is required" in capsys.readouterr().out


def test_runtime_looking_change_without_mapped_units_fails(
    tmp_path: Path, capsys
) -> None:
    repo, base_sha, head_sha = fixture_repo(tmp_path)
    summary_list = write_coverage(repo, statement_count=1)
    final_path = repo / "coverage" / "coverage-final.json"
    final_path.write_text(
        json.dumps(
            {
                str(repo / "src" / "calculate_total.ts"): {
                    "statementMap": {},
                    "s": {},
                    "fnMap": {},
                    "f": {},
                    "branchMap": {},
                    "b": {},
                }
            }
        ),
        encoding="utf-8",
    )

    assert run_gate(repo, base_sha, head_sha, summary_list) == 1
    assert "Istanbul mapped no execution units" in capsys.readouterr().out


def test_comment_only_change_without_mapped_units_passes(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    source = repo / "src" / "runtime.ts"
    source.parent.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Coverage Test")
    git(repo, "config", "user.email", "coverage@example.invalid")
    source.write_text("// base comment\n", encoding="utf-8")
    base_sha = commit(repo, "base")
    source.write_text("// changed comment\n", encoding="utf-8")
    head_sha = commit(repo, "comment only")
    coverage_dir = repo / "coverage"
    coverage_dir.mkdir()
    (coverage_dir / "coverage-final.json").write_text(
        json.dumps(
            {
                str(source): {
                    "statementMap": {},
                    "s": {},
                    "fnMap": {},
                    "f": {},
                    "branchMap": {},
                    "b": {},
                }
            }
        ),
        encoding="utf-8",
    )
    summary_list = repo / "coverage-files.txt"
    summary_list.write_text("coverage/coverage-final.json\n", encoding="utf-8")

    assert run_gate(repo, base_sha, head_sha, summary_list) == 0
    report = capsys.readouterr().out
    assert "comments, delimiters, or type-only declarations" in report
    assert "Result: PASS" in report
