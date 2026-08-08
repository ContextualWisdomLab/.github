from __future__ import annotations

from scripts.ci.organization_commercial_readiness_loop import (
    WorkflowRecord,
    is_dedicated_writer_workflow,
)


def test_active_scheduled_writer_claims_the_repository_lease() -> None:
    """An enabled scheduled product writer excludes the generic coordinator."""
    workflow = WorkflowRecord(
        workflow_id=1,
        name="Hourly Product Development",
        path=".github/workflows/hourly-product-development.yml",
        state="active",
        content_sha="sha-1",
        content='on:\n  schedule:\n    - cron: "37 * * * *"\n',
    )

    assert is_dedicated_writer_workflow(workflow)
