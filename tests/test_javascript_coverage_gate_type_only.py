"""Regression tests for type-only TypeScript changed-source coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.ci import javascript_coverage_gate as gate


def git(repo: Path, *args: str) -> str:
    """Run Git in a fixture repository and return stripped stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def commit(repo: Path, message: str) -> str:
    """Commit the fixture tree and return the resulting exact SHA."""
    git(repo, "add", ".")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def test_missing_type_only_source_does_not_require_istanbul_instrumentation(
    tmp_path: Path, capsys
) -> None:
    """Permit an omitted file only when every changed line is type-only."""
    repo = tmp_path / "repo"
    source = repo / "src" / "types.ts"
    source.parent.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Coverage Test")
    git(repo, "config", "user.email", "coverage@example.invalid")
    source.write_text(
        "import type {\n"
        "  JSONContent,\n"
        "} from './document.js';\n"
        "\n"
        "/** Detached editor state. */\n"
        "export interface EditorSnapshot {\n"
        "  readonly document: JSONContent;\n"
        "  readonly value: string;\n"
        "}\n"
        "\n"
        "/** Supported serialization modes. */\n"
        "export type EditorMode =\n"
        "  | 'markdown'\n"
        "  | 'html';\n",
        encoding="utf-8",
    )
    base_sha = commit(repo, "base type surface")
    source.write_text(
        "import type {\n"
        "  JSONContent,\n"
        "} from './document.js';\n"
        "\n"
        "/** Detached editor state. */\n"
        "export interface EditorSnapshot {\n"
        "  readonly document: JSONContent;\n"
        "  readonly value: string;\n"
        "  /** Destination-free reading-order projection. */\n"
        "  readonly plainText: string;\n"
        "}\n"
        "\n"
        "/** Supported serialization modes. */\n"
        "export type EditorMode =\n"
        "  | 'markdown'\n"
        "  | 'html';\n",
        encoding="utf-8",
    )
    head_sha = commit(repo, "extend type surface")

    coverage_dir = repo / "coverage"
    coverage_dir.mkdir()
    (coverage_dir / "coverage-final.json").write_text("{}\n", encoding="utf-8")
    (coverage_dir / "coverage-summary.json").write_text(
        json.dumps(
            {
                "total": {
                    metric: {"pct": 100.0}
                    for metric in gate.METRICS
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

    assert (
        gate.main(
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
        == 0
    )
    report = capsys.readouterr().out
    assert "type-only declarations" in report
    assert "Result: PASS" in report
