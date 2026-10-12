"""Regression contract for scheduler GitHub repository identity validation."""

import pytest

from scripts.ci import pr_review_merge_scheduler as sched


def test_scheduler_repository_identity_rejects_dot_traversal_components() -> None:
    """Reject non-canonical GitHub repository components before GitHub API use."""
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
        assert sched.validate_github_repository(repository_name) == repository_name

    for repository_name in rejected_repository_names:
        with pytest.raises(ValueError, match="invalid GitHub repository"):
            sched.validate_github_repository(repository_name)
