"""Regression contract for solo-maintainer protected-branch governance."""

from pathlib import Path

from scripts.ci import audit_central_required_workflows as audit

REPO_ROOT = Path(__file__).resolve().parents[1]
FOCUSED_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/solo-maintainer-ruleset-contract.yml"


def _central_ruleset_payload() -> dict:
    """Return the desired organization ruleset for a one-human-maintainer fleet."""
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
                        for path in audit.REQUIRED_WORKFLOW_PATHS
                    ],
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
                    "required_reviewers": [],
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["merge", "squash"],
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def _repository_ruleset_payload() -> dict:
    """Return the desired .github repository ruleset under the same model."""
    return {
        "id": audit.REPOSITORY_RULESET_ID,
        "name": audit.REPOSITORY_RULESET_NAME,
        "target": "branch",
        "source_type": "Repository",
        "source": audit.REPOSITORY_RULESET_SOURCE,
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        },
        "rules": [
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "required_reviewers": [],
                    "require_extra_approval_for_unattributed_changes": True,
                    "allowed_merge_methods": ["merge", "squash"],
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def test_central_ruleset_accepts_zero_approvals_without_last_push_approval() -> None:
    """A one-human fleet must not require an approval its sole author cannot give."""
    assert audit.audit_ruleset(_central_ruleset_payload()) == []


def test_repository_ruleset_accepts_zero_approvals_without_last_push_approval() -> None:
    """The control-plane repository must use the same satisfiable admission model."""
    assert audit.audit_repository_ruleset(_repository_ruleset_payload()) == []


def test_central_ruleset_rejects_synthetic_required_reviewer() -> None:
    """A named reviewer cannot manufacture independence in a one-human fleet."""
    payload = _central_ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["required_reviewers"] = [
        {"reviewer_id": 1234, "reviewer_type": "User"}
    ]

    assert audit.audit_ruleset(payload) == [
        "central solo-maintainer ruleset must not configure required reviewers"
    ]


def test_repository_ruleset_rejects_synthetic_required_reviewer() -> None:
    """The owner repository cannot reintroduce the same deadlock by reviewer identity."""
    payload = _repository_ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["required_reviewers"] = [
        {"reviewer_id": 1234, "reviewer_type": "User"}
    ]

    assert audit.audit_repository_ruleset(payload) == [
        "repository solo-maintainer ruleset must not configure required reviewers"
    ]


def test_focused_workflow_executes_main_ruleset_regressions() -> None:
    """The temporary proof workflow must execute, not merely parse, both suites."""
    workflow = " ".join(FOCUSED_WORKFLOW_PATH.read_text(encoding="utf-8").split())

    assert (
        "python -m pytest -q tests/test_central_required_workflow_ruleset_audit.py "
        "tests/test_solo_maintainer_ruleset_policy.py"
    ) in workflow
    assert "compile(regression_path.read_text" not in workflow
