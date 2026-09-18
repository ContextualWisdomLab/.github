"""Regression contract for scheduler GitHub repository identity validation."""

from scripts.ci import pr_review_merge_scheduler as sched


def test_scheduler_repository_identity_rejects_dot_traversal_components() -> None:
    """Reject dot traversal and trailing-dot components before GitHub API use."""
    accepted_repository_names = (
        "ContextualWisdomLab/pg-llm-batch",
        "ContextualWisdomLab/.github",
    )
    rejected_repository_names = (
        "ContextualWisdomLab/..",
        "ContextualWisdomLab/repository.",
        "ContextualWisdomLab./repository",
        "Contextual..WisdomLab/repository",
        "ContextualWisdomLab/repo..name",
        "../repository",
    )

    for repository_name in accepted_repository_names:
        assert sched.GITHUB_REPOSITORY_RE.fullmatch(repository_name) is not None

    for repository_name in rejected_repository_names:
        assert sched.GITHUB_REPOSITORY_RE.fullmatch(repository_name) is None
