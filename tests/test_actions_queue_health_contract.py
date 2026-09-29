"""Contract tests for the scheduled read-only Actions queue report."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_queue_health_workflow_is_scheduled_read_only_and_pinned() -> None:
    """Keep the scheduled collector bounded, read-only, and supply-chain pinned."""
    workflow = (ROOT / ".github/workflows/actions-queue-health.yml").read_text(encoding="utf-8")

    assert 'cron: "7 * * * *"' in workflow
    assert "workflow_dispatch:" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 30" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "actions: read" in workflow
    assert "pull-requests: read" not in workflow
    assert "contents: write" not in workflow
    workflow_permissions = workflow.split("permissions:\n", 1)[1].split("\njobs:\n", 1)[0]
    assert workflow_permissions == "  contents: read\n  actions: read\n"
    collect_permissions = workflow.split("  collect:\n", 1)[1].split(
        "    permissions:\n", 1
    )[1].split("    steps:\n", 1)[0]
    assert collect_permissions == "      contents: read\n      actions: read\n"
    assert (
        "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN }}"
        in workflow
    )
    assert "GH_TOKEN: ${{ github.token }}" not in workflow
    assert "required for cross-repository queue reads" in workflow
    assert "gh run cancel" not in workflow
    assert "gh pr merge" not in workflow
    assert "step-security/harden-runner@b09bb98e06d4d774595224525879c09bc6e98c40" in workflow
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "actions_queue_health.py" in workflow
    assert "actions_queue_health_repositories.json" in workflow


def test_queue_health_allowlist_is_explicit_and_bounded() -> None:
    """Keep the first product slice limited to its reviewed repositories."""
    payload = json.loads(
        (ROOT / "config/actions_queue_health_repositories.json").read_text(encoding="utf-8")
    )
    assert payload == {
        "repositories": [
            "ContextualWisdomLab/.github",
            "ContextualWisdomLab/ConceptWeave",
            "ContextualWisdomLab/ELUNVERA",
            "ContextualWisdomLab/LineageWeave",
            "ContextualWisdomLab/OriginWeave",
            "ContextualWisdomLab/TEPP",
            "ContextualWisdomLab/contextual-orchestrator",
            "ContextualWisdomLab/disksage",
            "ContextualWisdomLab/fast-mlsirm",
            "ContextualWisdomLab/mhtml-etl-gateway",
            "ContextualWisdomLab/naruon",
            "ContextualWisdomLab/noema",
            "ContextualWisdomLab/pg-llm-batch",
            "ContextualWisdomLab/quarantine-sandbox-runtime",
        ]
    }


def test_queue_health_core_does_not_duplicate_executable_entrypoints() -> None:
    """Keep collection and CLI orchestration solely in the executable module."""
    core_path = ROOT / "scripts/ci/actions_queue_health_core.py"
    tree = ast.parse(core_path.read_text(encoding="utf-8"))
    top_level_functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }

    assert "collect_snapshot" not in top_level_functions
    assert "main" not in top_level_functions
