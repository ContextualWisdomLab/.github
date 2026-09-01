"""Regression tests for Noema deleted-file review context."""

from __future__ import annotations

import base64
import json

from scripts.ci import noema_review_gate as noema


def test_fetch_changed_files_preserves_path_and_status(monkeypatch):
    """The paginated Files API adapter must retain each file status."""
    monkeypatch.setattr(
        noema,
        "run",
        lambda args, stdin=None: (
            json.dumps(["a.py", "modified"])
            + "\n\n"
            + json.dumps(["b.py", "removed"])
            + "\n"
            + json.dumps(["fuzz/x.py", "added"])
            + "\n"
        ),
    )

    assert noema.fetch_changed_files("owner/repo", 7) == [
        ("a.py", "modified"),
        ("b.py", "removed"),
        ("fuzz/x.py", "added"),
    ]


def test_removed_file_context_uses_merge_base_content(monkeypatch):
    """A deleted file must be reviewed from immutable merge-base evidence."""
    head_sha = "a" * 40
    base_sha = "b" * 40
    merge_base_sha = "c" * 40
    encoded = base64.b64encode(b"def doomed():\n    pass\n").decode("ascii")
    calls: list[str] = []

    def fake_run(args, stdin=None):
        target = args[2]
        calls.append(target)
        if target.endswith("/files"):
            return json.dumps(["fuzz/fuzz_opencode_normalize_output.py", "removed"]) + "\n"
        if target == f"repos/owner/repo/compare/{base_sha}...{head_sha}":
            return merge_base_sha
        if f"contents/fuzz/fuzz_opencode_normalize_output.py?ref={merge_base_sha}" in target:
            return encoded
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)

    context = noema.changed_file_context("owner/repo", 1486, head_sha, base_sha)

    assert f"Pre-deletion content at merge base `{merge_base_sha}`" in context
    assert "def doomed" in context
    assert not any(f"ref={head_sha}" in target for target in calls)


def test_fetch_changed_files_rejects_malformed_json_line(monkeypatch):
    """A non-JSON line from the Files API must fail closed, not crash raw."""
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: "not json\n")

    try:
        noema.fetch_changed_files("owner/repo", 7)
    except RuntimeError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for malformed JSON line")


def test_fetch_changed_files_rejects_malformed_record_shape(monkeypatch):
    """A well-formed JSON line that is not a two-element string pair must fail closed."""
    monkeypatch.setattr(
        noema, "run", lambda args, stdin=None: json.dumps(["only-one-field"]) + "\n"
    )

    try:
        noema.fetch_changed_files("owner/repo", 7)
    except RuntimeError as exc:
        assert "malformed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for malformed record shape")


def test_fetch_merge_base_sha_rejects_malformed_head_sha():
    """An invalid head SHA must be rejected before any network call is attempted."""
    try:
        noema.fetch_merge_base_sha("owner/repo", "a" * 40, "not-a-sha")
    except RuntimeError as exc:
        assert "PR head SHA was unavailable or malformed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for malformed head SHA")


def test_fetch_merge_base_sha_rejects_malformed_compare_response(monkeypatch):
    """A compare response lacking a valid merge-base SHA must fail closed."""
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: "")

    try:
        noema.fetch_merge_base_sha("owner/repo", "a" * 40, "b" * 40)
    except RuntimeError as exc:
        assert "did not contain a valid merge-base SHA" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for malformed compare response")


def test_removed_file_context_section_without_merge_base_or_error():
    """No merge-base SHA and no recorded error must still be explicit, not silent."""
    context = noema.removed_file_context_section("owner/repo", "gone.py", "", "")

    assert "merge-base SHA unavailable for pre-deletion content" in context


def test_removed_file_context_section_empty_merge_base_content(monkeypatch):
    """An empty (non-UTF-8-decodable) merge-base blob must be reported, not silently dropped."""
    monkeypatch.setattr(noema, "fetch_file_content_at_ref", lambda repo, path, ref: "")

    context = noema.removed_file_context_section("owner/repo", "gone.py", "c" * 40, "")

    assert "no UTF-8 text content available from merge-base content API" in context


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

    context = noema.changed_file_context("owner/repo", 7, "a" * 40, "")

    assert "PR base SHA was unavailable or malformed" in context
    assert "Merge-base lookup unavailable" in context


def test_removed_file_merge_base_content_failure_is_distinct_from_head_failure(monkeypatch):
    """A merge-base content API failure must remain typed as merge-base evidence failure."""
    head_sha = "a" * 40
    base_sha = "b" * 40
    merge_base_sha = "c" * 40

    monkeypatch.setattr(
        noema,
        "fetch_changed_files",
        lambda repo, number: [("gone.py", "removed")],
    )
    monkeypatch.setattr(
        noema, "fetch_merge_base_sha", lambda repo, base, head: merge_base_sha
    )

    def fail_fetch(repo, path, ref):
        raise RuntimeError("HTTP 502: token ***")

    monkeypatch.setattr(noema, "fetch_file_content_at_ref", fail_fetch)

    context = noema.changed_file_context("owner/repo", 7, head_sha, base_sha)

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
