"""Security regressions for exact-head PR review evidence binding."""

from scripts.ci import pr_review_autofix_context as context


def test_current_reviews_rejects_predecessor_body_head_sha(monkeypatch):
    """A stale review body cannot promote predecessor evidence to the live head."""
    head = "a" * 40
    stale_head = "b" * 40
    pages = [
        [
            {
                "commit_id": stale_head,
                "state": "CHANGES_REQUESTED",
                "body": f"This predecessor review mentions current head {head}.",
                "user": {"login": "opencode-agent"},
            },
            {
                "commit_id": head,
                "state": "APPROVED",
                "body": "Exact-head approval.",
                "user": {"login": "independent-reviewer"},
            },
        ]
    ]

    monkeypatch.setattr(context, "run_json", lambda args: pages)

    assert context.current_reviews("owner/repo", 7, head) == [pages[0][1]]
