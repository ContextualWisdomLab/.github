from copy import deepcopy
from io import StringIO
import json
from pathlib import Path

from scripts.ci import audit_central_required_workflows as audit


REPO_ROOT = Path(__file__).resolve().parents[1]
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


def test_expected_central_ruleset_passes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO(json.dumps(ruleset_payload())))

    assert audit.main([]) == 0
    assert (
        "PASS: ruleset 18156473 enforces 6 central required workflows"
        in capsys.readouterr().out
    )


def test_missing_semgrep_workflow_reports_exact_drift(capsys, tmp_path) -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"] = [
        workflow
        for workflow in workflow_rule["parameters"]["workflows"]
        if workflow["path"] != ".github/workflows/sast-semgrep.yml"
    ]

    payload_path = tmp_path / "ruleset.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    assert audit.main([str(payload_path)]) == 1
    assert (
        "ERROR: missing central required workflow .github/workflows/sast-semgrep.yml"
        in capsys.readouterr().err
    )


def test_wrong_workflow_ref_reports_exact_drift() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"][-1]["ref"] = "refs/heads/stale"

    errors = audit.audit_ruleset(payload)

    assert any(
        "must use source repository 1274066402 at refs/heads/main" in error
        for error in errors
    )


def test_review_policy_weakening_reports_exact_drift() -> None:
    payload = ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["require_last_push_approval"] = False
    review_rule["parameters"]["required_review_thread_resolution"] = False

    errors = audit.audit_ruleset(payload)

    assert "last-push approval protection is disabled" in errors
    assert "review-thread resolution protection is disabled" in errors


def test_audit_reports_all_structural_and_protection_drift() -> None:
    payload = {
        "id": 0,
        "name": "drifted",
        "target": "tag",
        "enforcement": "disabled",
        "conditions": None,
        "rules": "not-a-list",
    }

    errors = audit.audit_ruleset(payload)

    assert errors == [
        "expected ruleset id 18156473",
        "expected ruleset name CWL Central required workflows",
        "central ruleset target is not branch",
        "central ruleset enforcement is not active",
        "central ruleset does not include all repositories",
        "central ruleset repository exclusions drifted: expected ['.github', 'argos', 'noema'], got []",
        "central ruleset does not target every default branch",
        "expected one workflows rule, found 0",
        "missing central required workflow .github/workflows/close-empty-pr.yml",
        "missing central required workflow .github/workflows/opencode-review.yml",
        "missing central required workflow .github/workflows/pr-review-merge-scheduler.yml",
        "missing central required workflow .github/workflows/security-scan.yml",
        "missing central required workflow .github/workflows/strix.yml",
        "missing central required workflow .github/workflows/sast-semgrep.yml",
        "expected one pull_request rule, found 0",
        "default-branch deletion protection is missing",
        "default-branch non-fast-forward protection is missing",
    ]


def test_audit_reports_malformed_duplicate_workflows_and_weak_review_parameters() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflows = workflow_rule["parameters"]["workflows"]
    workflows.insert(0, "malformed")
    workflows.insert(1, {"path": 42})
    workflows.append(deepcopy(workflows[-1]))
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"] = {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": False,
        "allowed_merge_methods": ["squash"],
    }

    errors = audit.audit_ruleset(payload)

    assert "central required workflow .github/workflows/sast-semgrep.yml is configured 2 times" in errors
    assert "at least one approving review is not required" in errors
    assert "stale-review dismissal on push is disabled" in errors
    assert "last-push approval protection is disabled" in errors
    assert "review-thread resolution protection is disabled" in errors
    assert "merge and squash are not both allowed merge methods" in errors


def test_audit_handles_malformed_rule_parameter_shapes() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"] = None
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"] = None

    errors = audit.audit_ruleset(payload)

    assert "missing central required workflow .github/workflows/sast-semgrep.yml" in errors
    assert "at least one approving review is not required" in errors


def test_load_payload_rejects_non_object_and_main_logs_load_reason(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO("[]"))

    assert audit.main([]) == 2
    assert (
        "ERROR: unable to load ruleset JSON: ruleset JSON root must be an object"
        in capsys.readouterr().err
    )


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
