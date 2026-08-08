from __future__ import annotations

import pytest

from organization_commercial_readiness_fixtures import FakeClient
from scripts.ci.organization_commercial_readiness_loop import GitHubError, main, run_once


def test_runtime_rejects_a_foreign_organization_before_inventory() -> None:
    """A variable org must never dispatch through the fixed CWL control plane."""
    client = FakeClient([], {})

    with pytest.raises(GitHubError, match="ContextualWisdomLab"):
        run_once(client, organization="OtherOrganization", rotation_seed=0)


def test_cli_rejects_a_well_formed_foreign_organization() -> None:
    """A syntactically valid foreign org is still outside this scheduler's scope."""
    client = FakeClient([], {})

    assert main(
        ["--organization", "OtherOrganization"], client_factory=lambda: client
    ) == 2
