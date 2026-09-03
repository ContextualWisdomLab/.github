"""Independent exact-inventory regressions for the central required-workflow audit."""

from copy import deepcopy

from scripts.ci import audit_central_required_workflows as audit


EXPECTED_REQUIRED_WORKFLOW_PATHS = (
    ".github/workflows/close-empty-pr.yml",
    ".github/workflows/noema-review.yml",
    ".github/workflows/opencode-review.yml",
    ".github/workflows/pr-review-merge-scheduler.yml",
    ".github/workflows/security-scan.yml",
    ".github/workflows/strix.yml",
    ".github/workflows/sast-semgrep.yml",
    ".github/workflows/osv-scanner-pr.yml",
    ".github/workflows/scorecard-pr.yml",
)


def _ruleset_payload() -> dict:
    """Build an independent nine-workflow live-policy oracle."""
    return {
        "id": audit.RULESET_ID,
        "name": audit.RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "repository_name": {
                "include": ["~ALL"],
                "exclude": [".github", "IRT-bibliography-set", "noema"],
            },
            "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        },
        "rules": [
            {
                "type": "workflows",
                "parameters": {
                    "do_not_enforce_on_create": True,
                    "workflows": [
                        {
                            "repository_id": audit.SOURCE_REPOSITORY_ID,
                            "path": path,
                            "ref": audit.SOURCE_REF,
                        }
                        for path in EXPECTED_REQUIRED_WORKFLOW_PATHS
                    ]
                },
            },
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["merge", "squash"],
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def test_production_inventory_matches_independent_nine_path_oracle() -> None:
    """Prevent the production tuple from silently rewriting the test oracle."""
    assert audit.REQUIRED_WORKFLOW_PATHS == EXPECTED_REQUIRED_WORKFLOW_PATHS


def test_independent_nine_path_payload_passes() -> None:
    """Prove the hard-coded live-policy oracle is accepted unchanged."""
    assert audit.audit_ruleset(_ruleset_payload()) == []


def test_unexpected_live_workflow_fails_closed() -> None:
    """Reject a policy addition that is absent from the canonical exact inventory."""
    payload = deepcopy(_ruleset_payload())
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"].append(
        {
            "repository_id": audit.SOURCE_REPOSITORY_ID,
            "path": ".github/workflows/unreviewed-extra.yml",
            "ref": audit.SOURCE_REF,
        }
    )

    errors = audit.audit_ruleset(payload)

    assert errors == [
        "unexpected workflow present in required set: .github/workflows/unreviewed-extra.yml"
    ]
