"""Regression tests for Noema deleted-file review context."""

from __future__ import annotations

import base64

from scripts.ci import noema_review_gate as noema


def test_fetch_changed_files_preserves_path_and_status(monkeypatch):
    """The paginated Files API adapter must retain each file status."""
    monkeypatch.setattr(
        noema,
        "run",
        lambda args, stdin=None: "a.py\tmodified\n\nb.py\tremoved\nfuzz/x.py\tadded\n",
    )

    assert noema.fetch_changed_files("owner/repo", 7) == [
        ("a.py", "modified"),
        ("b.py", "removed"),
        ("fuzz/x.py", "added"),
    ]


def test_removed_file_context_uses_base_content(monkeypatch):
    """A deleted file must be reviewed from immutable pre-deletion evidence."""
    encoded = base64.b64encode(b"def doomed():\n    pass\n").decode("ascii")
    calls: list[str] = []

    def fake_run(args, stdin=None):
        target = args[2]
        calls.append(target)
        if target.endswith("/files"):
            return "fuzz/fuzz_opencode_normalize_output.py\tremoved\n"
        if "contents/fuzz/fuzz_opencode_normalize_output.py?ref=base-sha" in target:
            return encoded
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)

    context = noema.changed_file_context(
        "owner/repo", 1486, "head-sha", "base-sha"
    )

    assert "File removed in this PR. Pre-deletion content at base ref" in context
    assert "def doomed" in context
    assert not any("ref=head-sha" in target for target in calls)


def test_removed_file_context_fails_closed_without_base_sha(monkeypatch):
    """Missing base identity must be explicit and must not trigger a head fetch."""
    monkeypatch.setattr(
        noema,
        "fetch_changed_files",
        lambda repo, number: [("gone.py", "removed")],
    )
    monkeypatch.setattr(
        noema,
        "fetch_head_file_content",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected fetch")),
    )

    context = noema.changed_file_context("owner/repo", 7, "head-sha", "")

    assert "base SHA unavailable" in context


def test_removed_file_base_fetch_failure_is_distinct_from_head_failure(monkeypatch):
    """A base-side API failure must remain typed as base evidence failure."""
    monkeypatch.setattr(
        noema,
        "fetch_changed_files",
        lambda repo, number: [("gone.py", "removed")],
    )

    def fail_fetch(repo, path, ref):
        raise RuntimeError("HTTP 502: token ***")

    monkeypatch.setattr(noema, "fetch_head_file_content", fail_fetch)

    context = noema.changed_file_context(
        "owner/repo", 7, "head-sha", "base-sha"
    )

    assert "Unavailable from base content API" in context
    assert "Unavailable from head content API" not in context


def test_build_review_context_passes_live_base_ref(monkeypatch):
    """The GraphQL base identity must reach changed-file context construction."""
    observed: list[tuple[str, int, str, str]] = []
    monkeypatch.setattr(noema, "review_thread_context", lambda pr: "")
    monkeypatch.setattr(noema, "load_codegraph_context", lambda: "")

    def fake_context(repo, number, head_sha, base_sha=""):
        observed.append((repo, number, head_sha, base_sha))
        return "files"

    monkeypatch.setattr(noema, "changed_file_context", fake_context)

    result = noema.build_review_context(
        "owner/repo",
        7,
        {"headRefOid": "head-sha", "baseRefOid": "base-sha"},
    )

    assert observed == [("owner/repo", 7, "head-sha", "base-sha")]
    assert "## Changed file context\nfiles" in result
