"""Close reporting, SBOM, JavaScript, Noema, and scheduler edge coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import javascript_coverage_gate as js_gate
from scripts.ci import noema_review_gate as noema
from scripts.ci import noema_review_handoff as handoff
from scripts.ci import pr_review_autofix_context as autofix_context
from scripts.ci import pr_review_merge_scheduler as merge_scheduler
from scripts.ci import sanitize_github_output_summary as sanitizer
from scripts.ci import sbom_inventory_aggregator as sbom


def test_sanitizer_without_trailing_newline_stays_without_one() -> None:
    """Sanitization preserves the absence of a final newline."""

    assert sanitizer.sanitize_text("plain") == "plain"


def test_sbom_defensive_relationship_and_license_shapes() -> None:
    """Malformed relationship and license entries fail closed to NOASSERTION."""

    assert sbom._spdx_described_ids({"relationships": "bad"}) == set()
    assert sbom._spdx_described_ids(
        {
            "relationships": [
                {"relationshipType": "DESCRIBES", "relatedSpdxElement": 7}
            ]
        }
    ) == set()
    assert sbom._cyclonedx_license({"licenses": []}) == sbom.NOASSERTION
    assert sbom._cyclonedx_license(
        {"licenses": [{"license": "MIT"}, {"license": {"id": ""}}]}
    ) == sbom.NOASSERTION


def test_javascript_absolute_unmatched_path_falls_through_suffix_matching(
    tmp_path: Path,
) -> None:
    """An unrelated absolute coverage path falls through to the bounded suffix check."""

    repo = tmp_path.resolve()
    assert (
        js_gate.normalize_coverage_path(
            str(repo / "src" / "unrelated.ts"), repo, {"src/runtime.ts"}
        )
        is None
    )


def test_javascript_main_ignores_unmatched_coverage_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Coverage records that cannot map to a changed path are ignored before failure."""

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "runtime.ts").write_text("export const value = 1;\n")
    listing = repo / "coverage-files.txt"
    listing.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        js_gate,
        "load_coverage_files",
        lambda *_args: (
            [],
            [
                (
                    repo / "coverage-final.json",
                    {"/outside/unrelated.ts": {"s": {}, "f": {}, "b": {}}},
                )
            ],
        ),
    )
    monkeypatch.setattr(
        js_gate,
        "changed_runtime_lines",
        lambda *_args: {"src/runtime.ts": {1}},
    )

    assert (
        js_gate.main(
            [
                "--repo-root",
                str(repo),
                "--base-sha",
                "a" * 40,
                "--head-sha",
                "b" * 40,
                "--summary-list",
                str(listing),
            ]
        )
        == 1
    )
    assert "missing instrumentation" in capsys.readouterr().out


def test_noema_nonblocking_status_small_diff_and_empty_context_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success statuses, small diffs, invalid thread lines, and empty sections stay clean."""

    assert noema.blocking_checks(
        {
            "statusCheckRollup": {
                "contexts": {
                    "nodes": [
                        {
                            "__typename": "StatusContext",
                            "context": "legacy-security",
                            "state": "SUCCESS",
                        }
                    ]
                }
            }
        }
    ) == []

    monkeypatch.setattr(noema, "run", lambda _args: "small diff")
    assert noema.fetch_diff("owner/repo", 1) == ("small diff", False)

    pr = {
        "headRefOid": "a" * 40,
        "reviewThreads": {
            "nodes": [
                {
                    "path": "src/runtime.py",
                    "line": None,
                    "comments": {
                        "nodes": [
                            {"author": {"login": "reviewer"}, "body": "note"}
                        ]
                    },
                }
            ]
        },
    }
    assert "src/runtime.py:" in noema.review_thread_context(pr)

    monkeypatch.setattr(noema, "load_codegraph_context", lambda: "")
    monkeypatch.setattr(noema, "review_thread_context", lambda _pr: "")
    monkeypatch.setattr(noema, "changed_file_context", lambda *_args: "")
    assert noema.build_review_context("owner/repo", 1, pr) == ""


def test_noema_handoff_skips_nonterminal_marker_review() -> None:
    """A marker-bearing review with a nonterminal state does not end polling."""

    head = "a" * 40
    reviews = [
        {
            "commit_id": head,
            "user": {"login": handoff.NOEMA_REVIEW_AUTHOR},
            "body": handoff.NOEMA_REVIEW_MARKER,
            "state": "pending",
        }
    ]
    assert handoff.noema_review_state(reviews, head) is None


def test_autofix_context_ignores_unknown_rollup_node() -> None:
    """Unknown status-rollup node types are ignored without emitting false evidence."""

    assert autofix_context.check_summary([{"__typename": "Unknown"}]) == []


def test_merge_scheduler_blocked_wait_reason_without_review_note() -> None:
    """An already-approved BLOCKED PR omits the unsatisfied-review suffix."""

    reason = merge_scheduler.auto_merge_wait_reason(
        "BLOCKED", {"reviewDecision": "APPROVED"}
    )
    assert "GitHub reviewDecision" not in reason
    assert "mergeability is BLOCKED" in reason
