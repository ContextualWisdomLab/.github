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


def test_current_reviews_keeps_malformed_binding_after_eight_exact_head_reviews(
    monkeypatch,
):
    """A malformed change-request binding remains blocking after review truncation."""
    head = "a" * 40
    malformed = {
        "commit_id": "not-a-valid-commit-binding",
        "state": "CHANGES_REQUESTED",
        "body": "Untrusted malformed-binding prose.",
        "user": {"login": "review-agent"},
    }
    exact_head_reviews = [
        {
            "commit_id": head,
            "state": "APPROVED",
            "body": f"Exact-head approval {index}.",
            "user": {"login": f"reviewer-{index}"},
        }
        for index in range(8)
    ]
    pages = [[malformed, *exact_head_reviews]]

    monkeypatch.setattr(context, "run_json", lambda args: pages)

    reviews = context.current_reviews("owner/repo", 7, head)

    assert len(reviews) == 9
    assert reviews[0]["commit_id"] == malformed["commit_id"]
    assert reviews[0]["state"] == "CHANGES_REQUESTED"
    assert reviews[0]["body"] == (
        "Review commit binding is malformed; treating this as a blocking "
        "diagnostic only and ignoring the review body."
    )
    assert reviews[1:] == exact_head_reviews
