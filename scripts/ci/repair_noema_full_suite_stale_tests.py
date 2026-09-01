#!/usr/bin/env python3
"""Repair stale full-suite fixtures exposed by the Noema incident branch.

The protected production contracts already enforce credential-source admission
for ``orchestrator/free`` and immutable merge-base evidence for deleted files.
These tests still described the superseded OpenAI-free and moving-base APIs.
"""

from __future__ import annotations

from pathlib import Path


POLICY_TEST_PATH = Path("tests/test_contextual_orchestrator_review_policy.py")
REMOVED_FILE_TEST_PATH = Path("tests/test_noema_removed_file_context.py")


REMOVED_FILE_TEST_SOURCE = '''"""Regression tests for Noema deleted-file review context."""

from __future__ import annotations

import base64
import json

from scripts.ci import noema_review_gate as noema


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_BASE_SHA = "c" * 40


def test_fetch_changed_files_preserves_path_and_status(monkeypatch):
    """The paginated Files API adapter must retain each file status."""
    payload = "\\n".join(
        [
            json.dumps(["a.py", "modified"]),
            json.dumps(["b.py", "removed"]),
            json.dumps(["fuzz/x.py", "added"]),
        ]
    ) + "\\n"
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: payload)

    assert noema.fetch_changed_files("owner/repo", 7) == [
        ("a.py", "modified"),
        ("b.py", "removed"),
        ("fuzz/x.py", "added"),
    ]


def test_removed_file_context_uses_merge_base_content(monkeypatch):
    """A deleted file must be reviewed from immutable merge-base evidence."""
    encoded = base64.b64encode(b"def doomed():\\n    pass\\n").decode("ascii")
    calls: list[str] = []
    removed_path = "fuzz/fuzz_opencode_normalize_output.py"

    def fake_run(args, stdin=None):
        target = args[2]
        calls.append(target)
        if target.endswith("/files"):
            return json.dumps([removed_path, "removed"]) + "\\n"
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
    assert "## Changed file context\\nfiles" in result
'''


def replace_region(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    """Replace one function region while rejecting an unexpected source tree."""
    if text.count(start_marker) != 1:
        raise SystemExit(
            f"expected one start marker {start_marker!r}, found {text.count(start_marker)}"
        )
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[:start] + replacement + text[end:]


def repair_policy_tests() -> None:
    """Use an admitted free-pool provider in generic cap and limit tests."""
    text = POLICY_TEST_PATH.read_text(encoding="utf-8")
    replacement = '''def test_build_catalog_applies_account_cap() -> None:
    """An account cap keeps one credential from absorbing the pool."""
    report = {
        "models": [
            {
                "provider": "nvidia_nim",
                "model": f"m{i}",
                "agent_id": f"nim_a{i}",
                "is_free": True,
                **FREE_PRICE,
            }
            for i in range(6)
        ]
        + [
            {
                "provider": "nvidia_nim_sub",
                "model": f"s{i}",
                "agent_id": f"nim_b{i}",
                "is_free": True,
                **FREE_PRICE,
            }
            for i in range(6)
        ]
        + [
            {
                "provider": "bytez",
                "model": f"o{i}",
                "agent_id": f"bytez_{i}",
                "is_free": True,
                **FREE_PRICE,
            }
            for i in range(3)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=12, account_cap=2
    )
    account_counts: dict[str, int] = {}
    for agent in result["agents"]:
        account = policy.provider_account(agent["provider_name"])
        account_counts[account] = account_counts.get(account, 0) + 1
    assert account_counts["nvidia_nim"] == 2
    assert account_counts["nvidia_nim_sub"] == 2
    assert account_counts["bytez"] == 2


def test_build_catalog_respects_limit() -> None:
    """The catalog never exceeds the configured agent limit."""
    report = {
        "models": [
            {
                "provider": "bytez",
                "model": f"m{i}",
                "agent_id": f"bytez_{i}",
                "is_free": True,
                **FREE_PRICE,
            }
            for i in range(20)
        ]
    }
    result = policy.build_zdr_prioritized_catalog(
        policy.parse_discovery_report(report), limit=5, account_cap=100
    )
    assert len(result["agents"]) == 5
'''
    text = replace_region(
        text,
        "def test_build_catalog_applies_account_cap() -> None:\n",
        "\n\ndef test_build_catalog_fails_closed_without_free_models() -> None:\n",
        replacement,
    )
    POLICY_TEST_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    """Apply the two deterministic fixture migrations."""
    repair_policy_tests()
    REMOVED_FILE_TEST_PATH.write_text(REMOVED_FILE_TEST_SOURCE, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
