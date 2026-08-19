import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_queue_health_workflow_is_scheduled_read_only_and_pinned() -> None:
    workflow = (ROOT / ".github/workflows/actions-queue-health.yml").read_text(encoding="utf-8")

    assert 'cron: "7 * * * *"' in workflow
    assert "workflow_dispatch:" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "actions: read" in workflow
    assert "pull-requests: read" in workflow
    assert "contents: write" not in workflow
    assert (
        "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN }}"
        in workflow
    )
    assert "GH_TOKEN: ${{ github.token }}" not in workflow
    assert "required for cross-repository queue reads" in workflow
    assert "gh run cancel" not in workflow
    assert "gh pr merge" not in workflow
    assert "step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920" in workflow
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "actions_queue_health.py" in workflow
    assert "actions_queue_health_repositories.json" in workflow


def test_queue_health_allowlist_is_explicit_and_bounded() -> None:
    payload = json.loads(
        (ROOT / "config/actions_queue_health_repositories.json").read_text(encoding="utf-8")
    )
    assert payload == {
        "repositories": [
            "ContextualWisdomLab/.github",
            "ContextualWisdomLab/TEPP",
            "ContextualWisdomLab/contextual-orchestrator",
            "ContextualWisdomLab/naruon",
        ]
    }
