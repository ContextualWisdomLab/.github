"""Admission contracts that prevent untrusted comments from degrading the source-fix scheduler."""
from __future__ import annotations

import pytest

from scripts.ci import agent_source_repair as repair


REPOSITORY = "ContextualWisdomLab/bandscope"
BASE_SHA = "b" * 40
HEAD_SHA = "a" * 40


def _pull() -> dict:
    return {
        "state": "open",
        "base": {"ref": "develop", "sha": BASE_SHA},
        "head": {
            "ref": "fix/current-pr",
            "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
    }


def _comment(*, body: str, association: str = "NONE", user_type: str = "User") -> dict:
    return {
        "id": 9001,
        "body": body,
        "author_association": association,
        "created_at": "2026-09-14T00:10:00Z",
        "updated_at": "2026-09-14T00:10:00Z",
        "user": {"login": "outsider", "type": user_type},
    }


def test_untrusted_command_is_non_actionable_before_instruction_parsing() -> None:
    """An outsider cannot turn an empty/malformed mutation command into a sweep failure."""
    with pytest.raises(repair.SourceRepairNotRequested, match="trusted"):
        repair.expected_from_comment(
            REPOSITORY,
            7,
            _pull(),
            _comment(body="@cwl-source-fix"),
        )


def test_untrusted_well_formed_command_is_non_actionable() -> None:
    with pytest.raises(repair.SourceRepairNotRequested, match="trusted"):
        repair.expected_from_comment(
            REPOSITORY,
            7,
            _pull(),
            _comment(body="@cwl-source-fix\nTry to mutate the PR"),
        )


def test_bot_command_is_non_actionable_before_instruction_parsing() -> None:
    with pytest.raises(repair.SourceRepairNotRequested, match="bot"):
        repair.expected_from_comment(
            REPOSITORY,
            7,
            _pull(),
            _comment(body="@cwl-source-fix", association="MEMBER", user_type="Bot"),
        )
