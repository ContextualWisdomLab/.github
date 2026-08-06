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
    (coverage_dir / "coverage-final.json").write_text(
        json.dumps({"unrelated.ts": {"s": {}, "f": {}, "b": {}}}),
        encoding="utf-8",
    )
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
        "  | 'right'; runAfterMultilineType();\n"
        "export type SemicolonlessAlias = string\n"
        "runAfterSemicolonlessType();\n",
        encoding="utf-8",
    )

    assert gate.likely_runtime_lines(
        tmp_path,
        "src/mixed_types.ts",
        set(range(1, 25)),
    ) == [1, 2, 5, 8, 12, 14, 18, 19, 22, 23, 24]


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


def test_changed_runtime_lines_ignores_deletion_only_hunks(tmp_path: Path) -> None:
    """Do not invent changed executable lines for a deletion-only hunk."""
    repo = tmp_path / "repo"
    source = repo / "src" / "runtime.ts"
    source.parent.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Coverage Test")
    git(repo, "config", "user.email", "coverage@example.invalid")
    source.write_text(
        "export const retained = 1;\nexport const removed = 2;\n",
        encoding="utf-8",
    )
    base_sha = commit(repo, "base runtime")
    source.write_text("export const retained = 1;\n", encoding="utf-8")
    head_sha = commit(repo, "remove runtime line")

    assert gate.changed_runtime_lines(repo, base_sha, head_sha) == {}


def test_summary_and_path_helpers_cover_fallthrough_cases(tmp_path: Path) -> None:
    """Exercise invalid line metadata and nonmatching normalized paths."""
    metrics = gate.summarize_final(
        {
            "invalid.ts": {
                "s": {"0": 1},
                "f": {},
                "b": {},
                "statementMap": {"0": {"start": {"line": "invalid"}}},
            }
        }
    )
    assert metrics == {
        "statements": 100.0,
        "branches": 100.0,
        "functions": 100.0,
        "lines": 100.0,
    }

    changed_paths = {"src/runtime.ts"}
    assert (
        gate.normalize_coverage_path(
            str(tmp_path / "other.ts"), tmp_path, changed_paths
        )
        is None
    )
    assert (
        gate.normalize_coverage_path("./other.ts", tmp_path, changed_paths)
        is None
    )


def test_delimiter_state_helpers_reject_unmatched_closers() -> None:
    """Cover balanced nesting and every fail-closed unmatched closer."""
    assert gate._advance_interface_state("{{} nested", 0) == (1, None)
    assert gate._advance_type_alias_state("()[]{}", (0, 0, 0)) == (
        (0, 0, 0),
        None,
        True,
    )
    assert gate._advance_type_alias_state(")", (0, 0, 0)) == (
        (0, 0, 0),
        None,
        False,
    )
    assert gate._advance_type_alias_state("]", (0, 0, 0)) == (
        (0, 0, 0),
        None,
        False,
    )
    assert gate._advance_type_alias_state("}", (0, 0, 0)) == (
        (0, 0, 0),
        None,
        False,
    )


def test_classifier_fails_closed_on_unfinished_state(tmp_path: Path) -> None:
    """Retain changed evidence for every unfinished lexical or type state."""
    cases = {
        "unfinished_import.ts": "import type {\n  Missing,\n",
        "unfinished_interface.ts": "interface Missing {\n  value: string;\n",
        "unfinished_alias.ts": "export type Missing =\n  | 'left'\n",
        "unfinished_comment.ts": "/* open comment\nstill open\n",
    }
    for name, content in cases.items():
        source = tmp_path / "src" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")
        assert gate.likely_runtime_lines(
            tmp_path,
            f"src/{name}",
            {1, 2},
        ) == [1, 2]


def test_classifier_rejects_malformed_tail_after_comment_close(
    tmp_path: Path,
) -> None:
    """Do not repair malformed code after a multiline comment closes."""
    source = tmp_path / "src" / "malformed_comment_tail.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "interface Broken {\n"
        "  /* comment\n"
        "  */ 'unterminated\n"
        "}\n",
        encoding="utf-8",
    )

    assert gate.likely_runtime_lines(
        tmp_path,
        "src/malformed_comment_tail.ts",
        {1, 2, 3, 4},
    ) == [3]


def test_load_coverage_files_accepts_absolute_and_ignores_unknown_names(
    tmp_path: Path,
) -> None:
    """Load named evidence from mixed paths and skip unrelated JSON files."""
    summary = tmp_path / "coverage-summary.json"
    final = tmp_path / "coverage-final.json"
    ignored = tmp_path / "ignored.json"
    summary.write_text("{}\n", encoding="utf-8")
    final.write_text("{}\n", encoding="utf-8")
    ignored.write_text("{}\n", encoding="utf-8")
    summary_list = tmp_path / "coverage-files.txt"
    summary_list.write_text(
        f"\n{summary}\ncoverage-final.json\nignored.json\n",
        encoding="utf-8",
    )

    summaries, finals = gate.load_coverage_files(tmp_path, summary_list)
    assert summaries == [(summary, {})]
    assert finals == [(final, {})]
