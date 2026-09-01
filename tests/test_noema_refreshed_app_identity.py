"""Regression coverage for refreshed Noema GitHub App credentials."""

from scripts.ci import noema_review_gate as noema


def test_current_actor_accepts_refreshed_github_app_binding(monkeypatch):
    """A renewed installation token keeps the same independently bound App actor."""
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", "cwl-noema-review[bot]")
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", "146401636")
    monkeypatch.setenv(
        "NOEMA_REVIEW_TOKEN_SOURCE",
        "noema-review-github-app-refresh",
    )
    monkeypatch.setattr(
        noema,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("bound GitHub App metadata should avoid API fallback")
        ),
    )

    assert noema.current_actor() == "cwl-noema-review[bot]"
