"""Close JavaScript materialization and Noema defensive branch coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.ci import javascript_coverage_gate as js_gate
from scripts.ci import materialize_base_javascript_packages as js_materializer
from scripts.ci import noema_review_gate as noema


def test_javascript_changed_runtime_lines_ignores_deletion_only_hunk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A modified runtime file with no added lines does not create fake coverage work."""

    names = subprocess.CompletedProcess(
        args=["git"], returncode=0, stdout=b"src/runtime.ts\0", stderr=b""
    )
    monkeypatch.setattr(js_gate.subprocess, "run", lambda *_args, **_kwargs: names)
    monkeypatch.setattr(js_gate, "git", lambda *_args: "@@ -2 +2,0 @@")

    assert js_gate.changed_runtime_lines(tmp_path, "base", "head") == {}


def test_javascript_global_summary_ignores_noninteger_statement_lines() -> None:
    """Malformed Istanbul statement locations do not create line metrics."""

    summary = js_gate.summarize_final(
        {
            "src/runtime.ts": {
                "s": {"0": 1},
                "f": {},
                "b": {},
                "statementMap": {"0": {"start": {"line": "two"}}},
            }
        }
    )

    assert summary["statements"] == 100.0
    assert summary["lines"] == 100.0


def test_javascript_path_normalization_covers_direct_and_unmatched_paths(
    tmp_path: Path,
) -> None:
    """Absolute, relative, and unrelated Istanbul paths are handled explicitly."""

    repo = tmp_path.resolve()
    changed = {"src/runtime.ts"}
    assert (
        js_gate.normalize_coverage_path(str(repo / "src/runtime.ts"), repo, changed)
        == "src/runtime.ts"
    )
    assert js_gate.normalize_coverage_path("./src/runtime.ts", repo, changed) == (
        "src/runtime.ts"
    )
    assert js_gate.normalize_coverage_path("unrelated.ts", repo, changed) is None


def test_javascript_coverage_file_loader_accepts_absolute_and_unknown_entries(
    tmp_path: Path,
) -> None:
    """Coverage file loading handles absolute paths and ignores unknown JSON names."""

    repo = tmp_path / "repo"
    repo.mkdir()
    final = repo / "coverage-final.json"
    summary = repo / "coverage-summary.json"
    unknown = repo / "other.json"
    for path in (final, summary, unknown):
        path.write_text("{}", encoding="utf-8")
    listing = repo / "coverage-files.txt"
    listing.write_text(
        f"{final}\ncoverage-summary.json\nother.json\n", encoding="utf-8"
    )

    summaries, finals = js_gate.load_coverage_files(repo, listing)

    assert finals == [(final, {})]
    assert summaries == [(summary, {})]


def test_regular_base_paths_ignores_nonregular_or_unsafe_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Git trees, symlink modes, absolute paths, and traversal never enter inputs."""

    entries = b"\0".join(
        [
            b"100644 blob " + (b"a" * 40) + b"\tpackage.json",
            b"040000 tree " + (b"b" * 40) + b"\tsubtree",
            b"120000 blob " + (b"c" * 40) + b"\tsymlink",
            b"100644 blob " + (b"d" * 40) + b"\t../escape.json",
            b"100644 blob " + (b"e" * 40) + b"\t/absolute.json",
            b"",
        ]
    )
    monkeypatch.setattr(js_materializer, "_git", lambda *_args: entries)

    assert js_materializer._regular_base_paths(tmp_path, "a" * 40) == {
        "package.json"
    }


def test_base_npm_projects_handles_nonobject_packages_and_untracked_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """npm lock metadata may omit packages or name an untracked workspace safely."""

    regular_paths = {"package.json", "package-lock.json"}
    monkeypatch.setattr(
        js_materializer, "_regular_base_paths", lambda *_args: regular_paths
    )
    documents = {
        "package.json": json.dumps({"name": "fixture"}).encode(),
        "package-lock.json": json.dumps(
            {"lockfileVersion": 3, "packages": {"packages/missing": {}}}
        ).encode(),
    }

    def git_bytes(_root: Path, command: str, spec: str, *_args: str) -> bytes:
        assert command == "show"
        return documents[spec.split(":", 1)[1]]

    monkeypatch.setattr(js_materializer, "_git", git_bytes)
    projects = js_materializer.base_npm_projects(tmp_path, "a" * 40)
    assert projects[0][2].keys() == {"package.json", "package-lock.json"}

    documents["package-lock.json"] = json.dumps(
        {"lockfileVersion": 3, "packages": "not-an-object"}
    ).encode()
    projects = js_materializer.base_npm_projects(tmp_path, "a" * 40)
    assert projects[0][2].keys() == {"package.json", "package-lock.json"}


def test_noema_status_context_failure_is_blocking() -> None:
    """A non-success legacy status context remains a concrete review blocker."""

    pr = {
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    {
                        "__typename": "StatusContext",
                        "context": "legacy-security",
                        "state": "failure",
                    }
                ]
            }
        }
    }
    assert noema.blocking_checks(pr) == ["legacy-security: FAILURE"]


def test_noema_fetch_diff_truncates_to_prompt_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oversized diffs are bounded and explicitly marked truncated."""

    monkeypatch.setattr(noema, "run", lambda _args: "x" * (noema.MAX_DIFF_CHARS + 1))
    diff, truncated = noema.fetch_diff("owner/repo", 1)
    assert truncated is True
    assert len(diff) == noema.MAX_DIFF_CHARS


def test_noema_review_context_includes_locations_bodies_and_all_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review context retains a bounded line location and nonempty evidence sections."""

    pr = {
        "headRefOid": "a" * 40,
        "reviewThreads": {
            "nodes": [
                {
                    "path": "src/runtime.py",
                    "line": 7,
                    "isResolved": False,
                    "isOutdated": False,
                    "comments": {
                        "nodes": [
                            {"author": {"login": "reviewer"}, "body": "Fix this"},
                            {"author": {"login": "reviewer"}, "body": ""},
                        ]
                    },
                }
            ]
        },
    }
    rendered = noema.review_thread_context(pr)
    assert "src/runtime.py:7" in rendered
    assert "reviewer: Fix this" in rendered

    monkeypatch.setattr(noema, "load_codegraph_context", lambda: "graph")
    monkeypatch.setattr(noema, "changed_file_context", lambda *_args: "files")
    context = noema.build_review_context("owner/repo", 1, pr)
    assert "CodeGraph context" in context
    assert "Prior review threads" in context
    assert "Changed file context" in context
