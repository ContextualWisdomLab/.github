"""Fail-closed regression for malformed ruleset merge-method payloads."""

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.ci import audit_central_required_workflows as audit


def _review_parameters() -> dict[str, object]:
    return {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": True,
        "require_last_push_approval": False,
        "required_review_thread_resolution": True,
        "required_reviewers": [],
        "require_extra_approval_for_unattributed_changes": True,
        "allowed_merge_methods": ["merge", "squash"],
    }


def _central_payload() -> dict[str, object]:
    return {
        "id": audit.RULESET_ID,
        "name": audit.RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "repository_name": {
                "include": ["~ALL"],
                "exclude": sorted(audit.EXPECTED_EXCLUSIONS),
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
            {"type": "pull_request", "parameters": _review_parameters()},
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def _repository_payload() -> dict[str, object]:
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
            {"type": "pull_request", "parameters": _review_parameters()},
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def _set_allowed_merge_methods(payload: dict[str, object], value: object) -> None:
    rules = payload["rules"]
    assert isinstance(rules, list)
    review_rule = next(
        rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "pull_request"
    )
    parameters = review_rule["parameters"]
    assert isinstance(parameters, dict)
    parameters["allowed_merge_methods"] = value


@pytest.mark.parametrize(
    "malformed",
    [None, 7, "merge", {"merge": True}, ("merge", "squash")],
)
def test_central_audit_reports_malformed_merge_method_shape_without_raising(
    malformed: object,
) -> None:
    payload = deepcopy(_central_payload())
    _set_allowed_merge_methods(payload, malformed)

    errors = audit.audit_ruleset(payload)

    assert "only merge and squash may be allowed merge methods" in errors


@pytest.mark.parametrize(
    "malformed",
    [None, 7, "merge", {"merge": True}, ("merge", "squash")],
)
def test_repository_audit_reports_malformed_merge_method_shape_without_raising(
    malformed: object,
) -> None:
    payload = deepcopy(_repository_payload())
    _set_allowed_merge_methods(payload, malformed)

    errors = audit.audit_repository_ruleset(payload)

    assert "repository ruleset must allow only merge and squash" in errors


def test_valid_merge_method_list_remains_accepted() -> None:
    assert audit.audit_ruleset(_central_payload()) == []
    assert audit.audit_repository_ruleset(_repository_payload()) == []
