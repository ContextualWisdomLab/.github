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


def test_type_only_classifier_accepts_balanced_type_aliases(tmp_path: Path) -> None:
    """Recognize complete semicolon-terminated aliases without runtime tails."""
    source = tmp_path / "src" / "type_aliases.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "export type InlineAlias = string;\n"
        "export type UnionAlias =\n"
        "  | 'left'\n"
        "  | 'right';\n"
        "export type ObjectAlias = {\n"
        "  readonly value: string;\n"
        "  readonly nested: {\n"
        "    readonly count: number;\n"
        "  };\n"
        "};\n",
        encoding="utf-8",
    )

    assert gate.likely_runtime_lines(
        tmp_path,
        "src/type_aliases.ts",
        set(range(1, 11)),
    ) == []


def test_type_only_classifier_rejects_mixed_runtime_tails(tmp_path: Path) -> None:
    """Do not let declaration prefixes or comment braces hide runtime code."""
    source = tmp_path / "src" / "mixed_types.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "export interface InlineShape {} const inlineRuntime = 1;\n"
        "import type { InlineShape } from './shape.js'; runInline();\n"
        "interface MultilineShape {\n"
        "  readonly value: string;\n"
        "} runAfterInterface();\n"
        "import type {\n"
        "  MultilineShape,\n"
        "} from './shape.js'; runAfterImport();\n"
        "interface CommentedShape {\n"
        "  readonly value: string; /* brace { */\n"
        "}\n"
        "runAfterComment();\n"
        "import type { SingleLineShape } from './shape.js'\n"
        "runAfterSemicolonlessImport();\n"
        "import type {\n"
        "  MultilineShape,\n"
        "} from './shape.js'\n"
        "runAfterMultilineSemicolonlessImport();\n"
        "export type InlineAlias = string; runAfterTypeAlias();\n"
        "export type MultilineAlias =\n"
        "  | 'left'\n"
        "  | 'right'; runAfterMultilineType();\n",
        encoding="utf-8",
    )

    assert gate.likely_runtime_lines(
        tmp_path,
        "src/mixed_types.ts",
        set(range(1, 23)),
    ) == [1, 2, 5, 8, 12, 14, 18, 19, 22]


def test_type_only_classifier_fails_closed_on_lexical_edges(tmp_path: Path) -> None:
    """Reject malformed literals, stray closers, and unfinished declarations."""
    source = tmp_path / "src" / "lexical_edges.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "interface UnterminatedString {\n"
        "  readonly safe: '{';\n"
        "  readonly bad: 'unterminated {\n"
        "}\n"
        "runAfterUnterminatedString();\n"
        "interface StrayComment {\n"
        "  readonly bad: string; */\n"
        "}\n"
        "runAfterStrayComment();\n"
        "interface OpenComment {\n"
        "  readonly value: string; /* brace {\n"
        "  still comment\n"
        "  */\n"
        "}\n"
        "runAfterOpenComment();\n"
        "interface CloseTail {\n"
        "  /* comment\n"
        "  */ } runAfterCommentClose();\n"
        "export type UnterminatedAlias =\n"
        "  | 'left'\n",
        encoding="utf-8",
    )

    assert gate.likely_runtime_lines(
        tmp_path,
        "src/lexical_edges.ts",
        set(range(1, 21)),
    ) == [3, 5, 7, 9, 15, 18, 19, 20]
