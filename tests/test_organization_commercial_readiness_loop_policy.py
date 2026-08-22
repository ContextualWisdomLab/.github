from __future__ import annotations

from pathlib import Path
from typing import Any

from organization_commercial_readiness_fixtures import (
    manual_workflow,
    pull,
    snapshot,
    workflow,
)
from scripts.ci.organization_commercial_readiness_loop import (
    ActionKind,
    ActionResult,
    RunRecord,
    RunReport,
    build_plan,
    choose_rotating,
    is_dedicated_writer_workflow,
    is_live_writer_run,
    is_manual_product_entrypoint,
    repository_is_eligible,
)

ROOT = Path(__file__).resolve().parents[1]


def test_static_and_live_writer_lease_policy() -> None:
    """Only active high-signal writers, including unreadable ones, hold leases."""
    scheduled = workflow(content='on:\n  schedule:\n    - cron: "1 * * * *"\n')
    disabled = workflow(state="disabled_manually", content=scheduled.content)
    manual = workflow(content="on:\n  workflow_dispatch:\n")
    merge = workflow(
        name="Required PR Review Merge Scheduler",
        path=".github/workflows/pr-review-merge-scheduler.yml",
        content='on:\n  schedule:\n    - cron: "*/15 * * * *"\n',
    )
    assert is_dedicated_writer_workflow(scheduled)
    assert is_dedicated_writer_workflow(workflow(content=None))
    assert not is_dedicated_writer_workflow(disabled)
    assert not is_dedicated_writer_workflow(manual)
    assert not is_dedicated_writer_workflow(merge)

    active = RunRecord(1, scheduled.name, scheduled.path, "in_progress", "a" * 40)
    complete = RunRecord(2, scheduled.name, scheduled.path, "completed", "b" * 40)
    assert is_live_writer_run(active)
    assert not is_live_writer_run(complete)


def test_product_entrypoint_requires_manual_nvidia_opt_in() -> None:
    """Product dispatch requires a marked, unscheduled, credential-isolated workflow."""
    safe = manual_workflow()
    assert is_manual_product_entrypoint(safe)
    assert not is_manual_product_entrypoint(workflow(state="disabled_manually", content="x"))
    assert not is_manual_product_entrypoint(workflow(content=None))
    for changed in (
        (safe.content or "") + 'schedule:\n  - cron: "1 * * * *"\n',
        (safe.content or "") + "COPILOT_GITHUB_TOKEN: forbidden\n",
        (safe.content or "").replace("# cwl-org-commercial-entrypoint: v1\n", ""),
        (safe.content or "").replace("concurrency:\n", ""),
    ):
        assert not is_manual_product_entrypoint(workflow(content=changed))


def test_repository_eligibility_is_owned_and_write_capable() -> None:
    """Archived, forked, disabled, foreign, central, and read-only repos are excluded."""
    base: dict[str, Any] = {
        "full_name": "ContextualWisdomLab/example",
        "default_branch": "main",
        "archived": False,
        "disabled": False,
        "fork": False,
        "permissions": {"push": True},
    }
    assert repository_is_eligible(base, "ContextualWisdomLab")
    variants = (
        {**base, "archived": True},
        {**base, "disabled": True},
        {**base, "fork": True},
        {**base, "default_branch": None},
        {**base, "full_name": "Other/example"},
        {**base, "full_name": "ContextualWisdomLab/.github"},
        {**base, "permissions": {"pull": True}},
    )
    assert all(not repository_is_eligible(item, "ContextualWisdomLab") for item in variants)


def test_rotation_and_plan_are_bounded_and_dependency_safe() -> None:
    """Review and development rotate independently without drafts, stacks, or leases."""
    assert choose_rotating(("a", "b", "c"), 1, 2) == ("b", "c")
    assert choose_rotating(("a", "b", "c"), 2, 4) == ("c", "a", "b")
    assert choose_rotating((), 1, 1) == ()
    assert choose_rotating(("a",), 1, 0) == ()

    records = (
        snapshot("ContextualWisdomLab/review-a", pulls=(pull(1),)),
        snapshot("ContextualWisdomLab/review-b", pulls=(pull(2),)),
        snapshot("ContextualWisdomLab/product", workflows=(manual_workflow(),)),
        snapshot("ContextualWisdomLab/draft", pulls=(pull(3, draft=True),)),
        snapshot("ContextualWisdomLab/stack", pulls=(pull(4, base_ref="feature/base"),)),
        snapshot(
            "ContextualWisdomLab/leased",
            workflows=(workflow(content='on:\n  schedule:\n    - cron: "1 * * * *"\n'),),
            pulls=(pull(5),),
        ),
    )
    plan = build_plan(records, rotation_seed=1)
    assert [(item.kind, item.repository) for item in plan] == [
        (ActionKind.REVIEW_REPAIR, "ContextualWisdomLab/review-b"),
        (ActionKind.PRODUCT_DEVELOPMENT, "ContextualWisdomLab/product"),
    ]
    assert plan[1].workflow_id == 9


def test_snapshot_fingerprint_ignores_api_order_only() -> None:
    """Reordered workflow and PR lists retain one exact-state fingerprint."""
    a = snapshot(
        "ContextualWisdomLab/example",
        workflows=(workflow(workflow_id=2), workflow(workflow_id=1)),
        pulls=(pull(2), pull(1)),
    )
    b = snapshot(
        "ContextualWisdomLab/example",
        workflows=(workflow(workflow_id=1), workflow(workflow_id=2)),
        pulls=(pull(1), pull(2)),
    )
    assert a.fingerprint == b.fingerprint


def test_report_formats_actions_empty_state_and_errors() -> None:
    """JSON and Markdown receipts preserve bounded action and failure evidence."""
    report = RunReport(
        "ContextualWisdomLab",
        1,
        ("ContextualWisdomLab/leased",),
        (("ContextualWisdomLab/broken", "error|detail\nnext"),),
        (ActionResult(ActionKind.REVIEW_REPAIR, "ContextualWisdomLab/a", "dry_run", "a|b"),),
        True,
    )
    assert '"dry_run": true' in report.to_json()
    assert "a\\|b" in report.to_markdown()
    empty = RunReport("ContextualWisdomLab", 0, (), (), (), False)
    assert "No safe target" in empty.to_markdown()


def test_workflow_and_doctoring_contracts() -> None:
    """Permanent files retain cadence, token, coverage, and realistic-scope controls."""
    workflow_source = (
        ROOT / ".github/workflows/organization-commercial-readiness-loop.yml"
    ).read_text()
    quality = (
        ROOT
        / ".github/workflows/organization-commercial-readiness-loop-quality-ci.yml"
    ).read_text()
    doctoring = (
        ROOT / "docs/doctoring/organization-commercial-readiness-loop.md"
    ).read_text()
    assert 'cron: "7 * * * *"' in workflow_source
    assert "cancel-in-progress: false" in workflow_source
    assert 'MAX_REVIEW_DISPATCHES: "1"' in workflow_source
    assert 'MAX_DEVELOPMENT_DISPATCHES: "1"' in workflow_source
    assert (
        "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || "
        "steps.opencode_app_token.outputs.token }}"
    ) in workflow_source
    assert "id-token: write" in workflow_source
    assert "OIDC_AUDIENCE: opencode-github-action" in workflow_source
    assert "OPENCODE_APPROVE_TOKEN" not in workflow_source
    assert "workflow_dispatch:" not in workflow_source
    assert "|| github.token" not in workflow_source
    assert "NVIDIA_NIM_API_KEY" not in workflow_source
    assert "COPILOT_GITHUB_TOKEN" not in workflow_source
    assert "github.run_number" in workflow_source
    assert "persist-credentials: false" in workflow_source
    assert "--branch" in quality and "--fail-under=100" in quality
    assert "--import-mode=importlib" in quality
    assert "organization_commercial_readiness_fixtures.py" in quality
    assert "github.event.pull_request.head.sha" in quality
    assert "disabled workflow does not hold a lease" in doctoring
    assert "manual-only, explicitly marked" in doctoring
    assert "does not make every repository directly writable" in doctoring
    assert "GITHUB_TOKEN" in doctoring and "APA 7" in doctoring
