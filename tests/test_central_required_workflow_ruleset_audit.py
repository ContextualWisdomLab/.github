import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = REPO_ROOT / "scripts/ci/audit_central_required_workflows.py"


def ruleset_payload() -> dict:
    """Return the expected live central required-workflow ruleset shape."""
    workflow_paths = (
        "close-empty-pr.yml",
        "opencode-review.yml",
        "pr-review-merge-scheduler.yml",
        "security-scan.yml",
        "strix.yml",
        "sast-semgrep.yml",
    )
    return {
        "id": 18156473,
        "name": "CWL Central required workflows",
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "repository_name": {
                "include": ["~ALL"],
                "exclude": ["noema", "argos", ".github"],
            },
            "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        },
        "rules": [
            {
                "type": "workflows",
                "parameters": {
                    "do_not_enforce_on_create": False,
                    "workflows": [
                        {
                            "repository_id": 1274066402,
                            "path": f".github/workflows/{path}",
                            "ref": "refs/heads/main",
                        }
                        for path in workflow_paths
                    ],
                },
            },
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 1,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": True,
                    "required_review_thread_resolution": True,
                    "required_reviewers": [],
                    "allowed_merge_methods": ["merge", "squash"],
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def run_audit(payload: dict) -> subprocess.CompletedProcess[str]:
    """Run the ruleset audit through its stdin contract."""
    return subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def test_expected_central_ruleset_passes() -> None:
    result = run_audit(ruleset_payload())

    assert result.returncode == 0
    assert "PASS: ruleset 18156473 enforces 6 central required workflows" in result.stdout


def test_missing_semgrep_workflow_reports_exact_drift() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"] = [
        workflow
        for workflow in workflow_rule["parameters"]["workflows"]
        if workflow["path"] != ".github/workflows/sast-semgrep.yml"
    ]

    result = run_audit(payload)

    assert result.returncode == 1
    assert (
        "ERROR: missing central required workflow .github/workflows/sast-semgrep.yml"
        in result.stderr
    )


def test_wrong_workflow_ref_reports_exact_drift() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"][-1]["ref"] = "refs/heads/stale"

    result = run_audit(payload)

    assert result.returncode == 1
    assert "must use source repository 1274066402 at refs/heads/main" in result.stderr


def test_review_policy_weakening_reports_exact_drift() -> None:
    payload = ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["require_last_push_approval"] = False
    review_rule["parameters"]["required_review_thread_resolution"] = False

    result = run_audit(payload)

    assert result.returncode == 1
    assert "ERROR: last-push approval protection is disabled" in result.stderr
    assert "ERROR: review-thread resolution protection is disabled" in result.stderr


def test_scheduled_audit_and_rollout_document_the_semgrep_requirement() -> None:
    workflow = (REPO_ROOT / ".github/workflows/audit-central-ruleset.yml").read_text(
        encoding="utf-8"
    )
    rollout = (REPO_ROOT / "docs/org-required-workflow-rollout.md").read_text(
        encoding="utf-8"
    )

    assert 'cron: "11 2 * * *"' in workflow
    assert "PR_REVIEW_MERGE_TOKEN" in workflow
    assert "orgs/ContextualWisdomLab/rulesets/18156473" in workflow
    assert "audit_central_required_workflows.py" in workflow
    assert "Ruleset audit could not read organization ruleset 18156473" in workflow
    assert "- `.github/workflows/sast-semgrep.yml`" in rollout
