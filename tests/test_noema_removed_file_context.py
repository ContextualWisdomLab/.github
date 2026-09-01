"""Regression tests for Noema deleted-file review context."""

from __future__ import annotations

import base64

import pytest

from scripts.ci import noema_review_gate as noema


def test_fetch_changed_files_preserves_path_and_status(monkeypatch):
    """The paginated Files API adapter must retain each file status."""
    monkeypatch.setattr(
        noema,
        "run",
        lambda args, stdin=None: (
            '["a.py", "modified"]\n\n["b.py", "removed"]\n["fuzz/x.py", "added"]\n'
        ),
    )

    assert noema.fetch_changed_files("owner/repo", 7) == [
        ("a.py", "modified"),
        ("b.py", "removed"),
        ("fuzz/x.py", "added"),
    ]


def test_fetch_changed_files_rejects_malformed_json_line(monkeypatch):
    """A non-JSON line from the paginated Files API must fail closed."""
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: "not-json\n")

    with pytest.raises(RuntimeError, match="malformed"):
        noema.fetch_changed_files("owner/repo", 7)


def test_fetch_changed_files_rejects_malformed_record_shape(monkeypatch):
    """A JSON record that isn't a two-element string pair must fail closed."""
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: '["only-one"]\n')

    with pytest.raises(RuntimeError, match="malformed"):
        noema.fetch_changed_files("owner/repo", 7)


def test_fetch_merge_base_sha_rejects_malformed_head_sha():
    """A malformed head SHA must fail closed distinctly from a malformed base SHA."""
    with pytest.raises(RuntimeError, match="head SHA"):
        noema.fetch_merge_base_sha("owner/repo", "a" * 40, "not-a-sha")


def test_fetch_merge_base_sha_rejects_malformed_compare_response(monkeypatch):
    """A compare response without a valid merge-base SHA must fail closed."""
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: "")

    with pytest.raises(RuntimeError, match="merge-base SHA"):
        noema.fetch_merge_base_sha("owner/repo", "a" * 40, "b" * 40)


def test_removed_file_context_section_without_merge_base_or_error():
    """No merge-base SHA and no lookup error must report head-side inapplicability."""
    section = noema.removed_file_context_section("owner/repo", "gone.py", "", "")

    assert "no head-side content applicable" in section
    assert "merge-base SHA unavailable" in section


def test_removed_file_context_section_reports_empty_merge_base_content(monkeypatch):
    """A successful but empty merge-base fetch must be reported explicitly."""
    monkeypatch.setattr(noema, "fetch_file_content_at_ref", lambda repo, path, ref: "")

    section = noema.removed_file_context_section("owner/repo", "gone.py", "c" * 40, "")

    assert "no UTF-8 text content available from merge-base content API" in section


def test_removed_file_context_uses_merge_base_content(monkeypatch):
    """A deleted file must be reviewed from immutable pre-deletion evidence."""
    encoded = base64.b64encode(b"def doomed():\n    pass\n").decode("ascii")
    head_sha = "a" * 40
    base_sha = "b" * 40
    merge_base_sha = "c" * 40
    calls: list[str] = []

    def fake_run(args, stdin=None):
        target = args[2]
        calls.append(target)
        if target.endswith("/files"):
            return '["fuzz/fuzz_opencode_normalize_output.py", "removed"]\n'
        if target == f"repos/owner/repo/compare/{base_sha}...{head_sha}":
            return merge_base_sha
        if (
            f"contents/fuzz/fuzz_opencode_normalize_output.py?ref={merge_base_sha}"
            in target
        ):
            return encoded
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)

    context = noema.changed_file_context("owner/repo", 1486, head_sha, base_sha)

    assert "File removed in this PR. Pre-deletion content at merge base" in context
    assert merge_base_sha in context
    assert "def doomed" in context
    assert not any(f"ref={head_sha}" in target for target in calls)


def test_removed_file_context_fails_closed_without_base_sha(monkeypatch):
    """Missing base identity must be explicit and must not trigger a content fetch."""
    monkeypatch.setattr(
        noema,
        "fetch_changed_files",
        lambda repo, number: [("gone.py", "removed")],
    )
    monkeypatch.setattr(
        noema,
        "fetch_file_content_at_ref",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected fetch")),
    )

    context = noema.changed_file_context("owner/repo", 7, "head-sha", "")

    assert "Merge-base lookup unavailable" in context
    assert "PR base SHA was unavailable or malformed" in context


def test_removed_file_base_fetch_failure_is_distinct_from_head_failure(monkeypatch):
    """A merge-base content API failure must remain typed as merge-base evidence failure."""
    monkeypatch.setattr(
        noema,
        "fetch_changed_files",
        lambda repo, number: [("gone.py", "removed")],
    )
    monkeypatch.setattr(
        noema, "fetch_merge_base_sha", lambda repo, base_sha, head_sha: "c" * 40
    )

    def fail_fetch(repo, path, ref):
        raise RuntimeError("HTTP 502: token ***")

    monkeypatch.setattr(noema, "fetch_file_content_at_ref", fail_fetch)

    context = noema.changed_file_context("owner/repo", 7, "a" * 40, "b" * 40)

    assert "Unavailable from merge-base content API" in context
    assert "Unavailable from head content API" not in context


def test_build_review_context_passes_live_base_ref(monkeypatch):
    """The GraphQL base identity must reach changed-file context construction."""
    observed: list[tuple[str, int, str, str, object]] = []
    monkeypatch.setattr(noema, "review_thread_context", lambda pr: "")

    def fake_context(repo, number, head_sha, base_sha="", changed_files=None):
        observed.append((repo, number, head_sha, base_sha, changed_files))
        return "files"

    monkeypatch.setattr(noema, "changed_file_context", fake_context)

    result = noema.build_review_context(
        "owner/repo",
        7,
        {"headRefOid": "head-sha", "baseRefOid": "base-sha"},
    )

    assert observed == [("owner/repo", 7, "head-sha", "base-sha", None)]
    assert "## Changed file context\nfiles" in result
