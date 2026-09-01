"""Regression tests for Noema deleted-file review context."""

from __future__ import annotations

import base64
import json

from scripts.ci import noema_review_gate as noema


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_BASE_SHA = "c" * 40


def test_fetch_changed_files_preserves_path_and_status(monkeypatch):
    """The paginated Files API adapter must retain each file status."""
    payload = "\n".join(
        [
            json.dumps(["a.py", "modified"]),
            json.dumps(["b.py", "removed"]),
            json.dumps(["fuzz/x.py", "added"]),
        ]
    ) + "\n"
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: payload)

    assert noema.fetch_changed_files("owner/repo", 7) == [
        ("a.py", "modified"),
        ("b.py", "removed"),
        ("fuzz/x.py", "added"),
    ]


def test_removed_file_context_uses_merge_base_content(monkeypatch):
    """A deleted file must be reviewed from immutable merge-base evidence."""
    encoded = base64.b64encode(b"def doomed():\n    pass\n").decode("ascii")
    calls: list[str] = []
    removed_path = "fuzz/fuzz_opencode_normalize_output.py"

    def fake_run(args, stdin=None):
        target = args[2]
        calls.append(target)
        if target.endswith("/files"):
            return json.dumps([removed_path, "removed"]) + "\n"
        if target == f"repos/owner/repo/compare/{BASE_SHA}...{HEAD_SHA}":
            return MERGE_BASE_SHA
        if f"contents/{removed_path}?ref={MERGE_BASE_SHA}" in target:
            return encoded
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)

    context = noema.changed_file_context(
        "owner/repo", 1486, HEAD_SHA, BASE_SHA
    )

    assert "File removed in this PR. Pre-deletion content at merge base" in context
    assert MERGE_BASE_SHA in context
    assert "def doomed" in context
    assert not any(f"ref={HEAD_SHA}" in target for target in calls)


def test_removed_file_context_fails_closed_without_base_sha(monkeypatch):
    """Missing base identity is explicit and never triggers a content fetch."""
    monkeypatch.setattr(
        noema,
        "fetch_changed_files",
        lambda repo, number: [("gone.py", "removed")],
    )
    monkeypatch.setattr(
        noema,
        "fetch_file_content_at_ref",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected content fetch")
        ),
    )

    context = noema.changed_file_context("owner/repo", 7, HEAD_SHA, "")

    assert "Merge-base lookup unavailable" in context
    assert "base SHA was unavailable or malformed" in context


def test_removed_file_merge_base_fetch_failure_is_distinct_from_head_failure(
    monkeypatch,
):
    """A merge-base API failure remains distinct from a head-side failure."""
    monkeypatch.setattr(
        noema,
        "fetch_changed_files",
        lambda repo, number: [("gone.py", "removed")],
    )
    monkeypatch.setattr(
        noema,
        "fetch_merge_base_sha",
        lambda repo, base_sha, head_sha: MERGE_BASE_SHA,
    )

    def fail_fetch(repo, path, ref):
        raise RuntimeError("HTTP 502: token ***")

    monkeypatch.setattr(noema, "fetch_file_content_at_ref", fail_fetch)

    context = noema.changed_file_context(
        "owner/repo", 7, HEAD_SHA, BASE_SHA
    )

    assert "Unavailable from merge-base content API" in context
    assert "Unavailable from head content API" not in context


def test_build_review_context_passes_live_base_and_changed_file_snapshot(
    monkeypatch,
):
    """The immutable PR identities and one status snapshot reach file context."""
    observed: list[tuple[str, int, str, str, tuple[tuple[str, str], ...]]] = []
    changed_files = [("gone.py", "removed")]
    monkeypatch.setattr(noema, "review_thread_context", lambda pr: "")

    def fake_context(
        repo,
        number,
        head_sha,
        base_sha="",
        supplied_changed_files=None,
    ):
        observed.append(
            (
                repo,
                number,
                head_sha,
                base_sha,
                tuple(supplied_changed_files or ()),
            )
        )
        return "files"

    monkeypatch.setattr(noema, "changed_file_context", fake_context)

    result = noema.build_review_context(
        "owner/repo",
        7,
        {"headRefOid": HEAD_SHA, "baseRefOid": BASE_SHA},
        changed_files,
    )

    assert observed == [
        ("owner/repo", 7, HEAD_SHA, BASE_SHA, (("gone.py", "removed"),))
    ]
    assert "## Changed file context\nfiles" in result
