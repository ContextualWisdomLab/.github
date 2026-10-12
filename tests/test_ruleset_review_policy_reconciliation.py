"""Scope-specific review-policy regression contracts for ruleset reconciliation."""

from copy import deepcopy

from scripts.ci import audit_central_required_workflows as audit
from tests.test_ruleset_governance_reconciliation import live_payload, module, target
from tests.test_solo_maintainer_ruleset_policy import (
    _central_ruleset_payload,
    _repository_ruleset_payload,
    _review_parameters,
)


def test_central_ruleset_requires_two_independent_approvals() -> None:
    """The fleet ruleset retains protected-main's two-approval contract."""

    compliant = _central_ruleset_payload()
    parameters = _review_parameters(compliant)
    parameters["required_approving_review_count"] = 2
    parameters["require_last_push_approval"] = True
    assert audit.audit_ruleset(compliant) == []

    drifted = deepcopy(compliant)
    _review_parameters(drifted)["required_approving_review_count"] = 0
    assert "exactly two approving reviews are not required" in audit.audit_ruleset(
        drifted
    )


def test_repository_ruleset_requires_one_independent_approval() -> None:
    """The owner repository must enforce an attainable independent review."""

    compliant = _repository_ruleset_payload()
    parameters = _review_parameters(compliant)
    parameters["required_approving_review_count"] = 1
    parameters["require_last_push_approval"] = True
    assert audit.audit_repository_ruleset(compliant) == []

    drifted = deepcopy(compliant)
    drifted_parameters = _review_parameters(drifted)
    drifted_parameters["required_approving_review_count"] = 0
    drifted_parameters["require_last_push_approval"] = False
    errors = audit.audit_repository_ruleset(drifted)
    assert "repository ruleset must require exactly one approving review" in errors
    assert "repository ruleset last-push approval protection is disabled" in errors


def test_reconciler_projects_scope_specific_review_policy() -> None:
    """One owner-plane writer must not flatten distinct review requirements."""

    organization = module._desired_payload(
        live_payload("organization"), target("organization")
    )
    repository = module._desired_payload(live_payload(), target())

    organization_parameters = _review_parameters(organization)
    repository_parameters = _review_parameters(repository)
    assert organization_parameters["required_approving_review_count"] == 2
    assert organization_parameters["require_last_push_approval"] is True
    assert repository_parameters["required_approving_review_count"] == 1
    assert repository_parameters["require_last_push_approval"] is True
