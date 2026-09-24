"""Contract tests for the scheduled read-only Actions queue report."""

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
    assert "\n  pull-requests: read\n" not in workflow
    assert "\n      pull-requests: read\n" not in workflow
    assert "contents: write" not in workflow
    assert "uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1" in workflow
    assert "permission-actions: read" in workflow
    assert "permission-pull-requests: read" in workflow
    assert "repositories: ${{ steps.repository_scope.outputs.repositories }}" in workflow
    assert "config/actions_queue_health_repositories.json)" in workflow
    assert "GH_TOKEN: ${{ steps.observer_token.outputs.token || secrets.PR_REVIEW_MERGE_TOKEN || secrets.OPENCODE_APPROVE_TOKEN }}" in workflow
    assert "GH_TOKEN: ${{ github.token }}" not in workflow
    assert "required for cross-repository queue reads" in workflow
    assert "gh run cancel" not in workflow
    assert "gh pr merge" not in workflow
    assert "step-security/harden-runner@b09bb98e06d4d774595224525879c09bc6e98c40" in workflow
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "actions_queue_health.py" in workflow
    assert "actions_queue_health_repositories.json" in workflow
    assert "--credential-unavailable" in workflow
    assert "if: always()" in workflow


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


def test_missing_cross_repository_credential_writes_failed_evidence(tmp_path: Path) -> None:
    """Missing auth still leaves a bounded artifact and a non-success exit."""
    from scripts.ci import actions_queue_health as queue_health

    allowlist = tmp_path / "repositories.json"
    allowlist.write_text('{"repositories":["ContextualWisdomLab/.github"]}', encoding="utf-8")
    json_path = tmp_path / "report.json"
    html_path = tmp_path / "report.html"
    assert queue_health.main(
        [
            "--allowlist", str(allowlist),
            "--credential-unavailable",
            "--output-json", str(json_path),
            "--output-html", str(html_path),
        ]
    ) == 2
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert report["summary"]["observed_job_count"] == 0
    assert report["summary"]["collection_error_count"] == 1
    assert report["collection_errors"] == [
        {
            "repository": "ContextualWisdomLab/.github",
            "error": "cross_repository_read_credential_unavailable",
        }
    ]
    assert "scoped cross-repository Actions read credential" in report["summary"]["external_actions"][0]
    html_report = html_path.read_text(encoding="utf-8")
    assert "Cross-repository read access is unavailable." in html_report
    assert "Operator actions" in html_report
    assert "Run evidence could not be collected." in html_report
    assert "No queued or in-progress jobs observed." not in html_report


def test_partial_collection_remains_failed(tmp_path: Path) -> None:
    """A report artifact with missing repository evidence cannot be green."""
    from scripts.ci import actions_queue_health as queue_health

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps({
            "generated_at": "2026-09-24T00:00:00Z",
            "repositories": [],
            "collection_errors": [{
                "repository": "ContextualWisdomLab/.github",
                "error": "bounded active-run census exceeded",
            }],
        }),
        encoding="utf-8",
    )
    assert queue_health.main([
        "--snapshot", str(snapshot),
        "--output-json", str(tmp_path / "report.json"),
        "--output-html", str(tmp_path / "report.html"),
    ]) == 2


def test_credential_unavailable_requires_allowlist(tmp_path: Path) -> None:
    """The no-credential receipt must name its uncollected repository set."""
    from io import StringIO
    from scripts.ci import actions_queue_health as queue_health

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text('{"generated_at":"2026-09-24T00:00:00Z","repositories":[]}', encoding="utf-8")
    stderr = StringIO()
    assert queue_health.main([
        "--snapshot", str(snapshot),
        "--credential-unavailable",
        "--output-json", str(tmp_path / "report.json"),
        "--output-html", str(tmp_path / "report.html"),
    ], stderr=stderr) == 2
    assert "credential-unavailable requires an allowlist" in stderr.getvalue()
    assert not (tmp_path / "report.json").exists()
