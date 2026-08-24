"""Exercise repository-name boundaries shared by CI trust-boundary callers."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "ci"))

from scripts.ci import agent_mention_router
from scripts.ci import agent_mention_sweep
from scripts.ci import noema_review_handoff
from scripts.ci import pr_auto_rebase
from scripts.ci import pr_review_autofix_context
from scripts.ci import pr_review_fix_scheduler
from scripts.ci import pr_review_merge_scheduler
from scripts.ci import verify_exact_artifact_sbom_handoff


REPOSITORY_PATTERNS = (
    agent_mention_router.REPOSITORY_RE,
    agent_mention_sweep.REPOSITORY_RE,
    noema_review_handoff.REPOSITORY_RE,
    pr_auto_rebase.REPO_RE,
    pr_review_autofix_context.REPO_RE,
    pr_review_fix_scheduler.REPO_RE,
    pr_review_merge_scheduler.GITHUB_REPOSITORY_RE,
    verify_exact_artifact_sbom_handoff._REPOSITORY_RE,
)

GENERIC_PATTERNS = REPOSITORY_PATTERNS[3:]


@pytest.mark.parametrize("pattern", REPOSITORY_PATTERNS)
def test_repository_patterns_preserve_central_github_and_reject_dot_boundaries(
    pattern: re.Pattern[str],
) -> None:
    """Allow the canonical ``.github`` repository but reject dot traversal forms."""
    assert pattern.fullmatch("ContextualWisdomLab/.github")
    assert pattern.fullmatch("ContextualWisdomLab/valid-repository")
    if pattern in GENERIC_PATTERNS:
        assert pattern.fullmatch("owner/valid-repository")
    assert not pattern.fullmatch("owner./repository")
    assert not pattern.fullmatch("owner/repository.")
    assert not pattern.fullmatch("owner/..repository")
    assert not pattern.fullmatch("owner/repo..name")


@pytest.mark.parametrize(
    "value",
    [".invalid", "invalid.", "invalid..name", "valid/name"],
)
def test_organization_pattern_rejects_dot_boundaries(value: str) -> None:
    """Keep organization-name validation component-scoped and slash-free."""
    assert agent_mention_sweep.ORG_NAME_RE.fullmatch(value) is None
    assert agent_mention_sweep.ORG_NAME_RE.fullmatch("valid")
