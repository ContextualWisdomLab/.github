"""Regression tests for central JavaScript runtime-source classification."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci import javascript_coverage_gate as gate


def git(repo_root: Path, *args: str) -> str:
    """Run Git in a temporary regression fixture and return stdout."""
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def commit(repo_root: Path, message: str) -> str:
    """Commit the temporary fixture and return the immutable commit SHA."""
    git(repo_root, "add", ".")
    git(repo_root, "commit", "-m", message)
    return git(repo_root, "rev-parse", "HEAD")


def initialise_repo(repo_root: Path) -> None:
    """Create a deterministic Git repository for changed-file evidence tests."""
    repo_root.mkdir()
    git(repo_root, "init", "-b", "main")
    git(repo_root, "config", "user.name", "Coverage Scope Test")
    git(repo_root, "config", "user.email", "coverage-scope@example.invalid")


def empty_coverage_list(repo_root: Path) -> Path:
    """Write an empty Istanbul final report and return its list file."""
    coverage_dir = repo_root / "coverage"
    coverage_dir.mkdir()
    final_path = coverage_dir / "coverage-final.json"
    final_path.write_text(json.dumps({}), encoding="utf-8")
    summary_list = repo_root / "coverage-files.txt"
    summary_list.write_text("coverage/coverage-final.json\n", encoding="utf-8")
    return summary_list


def run_gate(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    summary_list: Path,
) -> int:
    """Run the current central coverage gate for one exact fixture head."""
    return gate.main(
        [
            "--repo-root",
            str(repo_root),
            "--base-sha",
            base_sha,
            "--head-sha",
            head_sha,
            "--summary-list",
            str(summary_list),
        ]
    )


@pytest.mark.parametrize(
    "path",
    [
        "vite.autosave.config.ts",
        "packages/editor/vitest.browser.config.ts",
        "webpack.server.config.js",
        "scripts/verify-framework-free-autosave-package.mjs",
        "scripts/verify-package.mjs",
        "packages/editor/scripts/check-bundle.cjs",
    ],
)
def test_tool_configs_and_repository_verifiers_are_not_product_runtime(
    path: str,
) -> None:
    """Exclude build/test configuration and bounded verification commands."""
    assert not gate.is_runtime_source(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/runtime.ts",
        "src/feature.config.ts",
        "scripts/serve-package.mjs",
        "src/scripts/verify-session.ts",
    ],
)
def test_runtime_modules_cannot_hide_behind_similar_names(path: str) -> None:
    """Keep product modules and non-verification scripts in blocking scope."""
    assert gate.is_runtime_source(path)


def test_tooling_only_change_is_explicitly_not_applicable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reproduce the Inkspan false positive without weakening runtime evidence."""
    repo_root = tmp_path / "repo"
    initialise_repo(repo_root)
    tooling_files = {
        "vite.autosave.config.ts": "export default { test: true };\n",
        "scripts/verify-framework-free-autosave-package.mjs": (
            "console.log('verify framework-free package');\n"
        ),
        "scripts/verify-package.mjs": "console.log('verify package');\n",
    }
    for relative_path, content in tooling_files.items():
        file_path = repo_root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    base_sha = commit(repo_root, "base tooling")
    tooling_updates = {
        "vite.autosave.config.ts": (
            "export default { test: true, version: 2 };\n"
        ),
        "scripts/verify-framework-free-autosave-package.mjs": (
            "console.log('verify framework-free package v2');\n"
        ),
        "scripts/verify-package.mjs": "console.log('verify package v2');\n",
    }
    for relative_path, content in tooling_updates.items():
        (repo_root / relative_path).write_text(content, encoding="utf-8")
    head_sha = commit(repo_root, "update tooling")
    summary_list = empty_coverage_list(repo_root)

    assert run_gate(repo_root, base_sha, head_sha, summary_list) == 0
    report = capsys.readouterr().out
    assert "No changed JavaScript/TypeScript runtime source files" in report
    assert "Result: PASS" in report


def test_non_verification_script_remains_fail_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Require instrumentation when an executable scripts module is product code."""
    repo_root = tmp_path / "repo"
    initialise_repo(repo_root)
    runtime_script = repo_root / "scripts" / "serve-package.mjs"
    runtime_script.parent.mkdir()
    runtime_script.write_text("export const port = 8000;\n", encoding="utf-8")
    base_sha = commit(repo_root, "base runtime script")
    runtime_script.write_text("export const port = 8080;\n", encoding="utf-8")
    head_sha = commit(repo_root, "change runtime script")
    summary_list = empty_coverage_list(repo_root)

    assert run_gate(repo_root, base_sha, head_sha, summary_list) == 1
    report = capsys.readouterr().out
    assert "scripts/serve-package.mjs is absent from coverage-final.json" in report
    assert "Result: FAIL" in report


def test_runtime_path_without_diff_hunks_is_not_measured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ignore a runtime path when Git reports no added or modified line hunk."""
    enumerated = subprocess.CompletedProcess(
        args=["git"],
        returncode=0,
        stdout=b"src/runtime.ts\0",
        stderr=b"",
    )
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: enumerated)
    monkeypatch.setattr(gate, "git", lambda *args, **kwargs: "")

    assert gate.changed_runtime_lines(tmp_path, "base", "head") == {}


def test_global_summary_ignores_non_integer_statement_locations() -> None:
    """Treat malformed line metadata as absent instead of inventing coverage."""
    summary = gate.summarize_final(
        {
            "runtime.ts": {
                "statementMap": {
                    "0": {
                        "start": {"line": "one"},
                        "end": {"line": "one"},
                    }
                },
                "s": {"0": 1},
                "fnMap": {},
                "f": {},
                "branchMap": {},
                "b": {},
            }
        }
    )

    assert summary == {
        "statements": 100.0,
        "branches": 100.0,
        "functions": 100.0,
        "lines": 100.0,
    }


def test_coverage_path_nonmatches_fall_through_safely(tmp_path: Path) -> None:
    """Reject unmatched absolute and relative Istanbul paths without ambiguity."""
    changed_paths = {"src/runtime.ts"}

    assert (
        gate.normalize_coverage_path(
            str(tmp_path / "src" / "other.ts"),
            tmp_path,
            changed_paths,
        )
        is None
    )
    assert (
        gate.normalize_coverage_path(
            "src/other.ts",
            tmp_path,
            changed_paths,
        )
        is None
    )


def test_coverage_loader_accepts_absolute_paths_and_ignores_other_json(
    tmp_path: Path,
) -> None:
    """Load bounded final evidence while ignoring an unrelated listed JSON file."""
    final_path = tmp_path / "coverage-final.json"
    other_path = tmp_path / "metadata.json"
    final_path.write_text("{}", encoding="utf-8")
    other_path.write_text("{}", encoding="utf-8")
    summary_list = tmp_path / "coverage-files.txt"
    summary_list.write_text(
        f"{other_path}\n{final_path}\n",
        encoding="utf-8",
    )

    summaries, finals = gate.load_coverage_files(tmp_path, summary_list)

    assert summaries == []
    assert finals == [(final_path, {})]


def test_unmatched_coverage_record_does_not_mask_matching_runtime_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Skip unrelated Istanbul records and still enforce the changed runtime file."""
    repo_root = tmp_path / "repo"
    initialise_repo(repo_root)
    source = repo_root / "src" / "runtime.ts"
    source.parent.mkdir()
    source.write_text("export const value = 1;\n", encoding="utf-8")
    base_sha = commit(repo_root, "base runtime")
    source.write_text("export const value = 2;\n", encoding="utf-8")
    head_sha = commit(repo_root, "change runtime")
    coverage_dir = repo_root / "coverage"
    coverage_dir.mkdir()
    coverage_record = {
        "statementMap": {
            "0": {
                "start": {"line": 1, "column": 0},
                "end": {"line": 1, "column": 23},
            }
        },
        "s": {"0": 1},
        "fnMap": {},
        "f": {},
        "branchMap": {},
        "b": {},
    }
    final_path = coverage_dir / "coverage-final.json"
    final_path.write_text(
        json.dumps(
            {
                str(repo_root / "src" / "unrelated.ts"): coverage_record,
                str(source): coverage_record,
            }
        ),
        encoding="utf-8",
    )
    summary_list = repo_root / "coverage-files.txt"
    summary_list.write_text("coverage/coverage-final.json\n", encoding="utf-8")

    assert run_gate(repo_root, base_sha, head_sha, summary_list) == 0
    assert "src/runtime.ts: statements 1/1" in capsys.readouterr().out
