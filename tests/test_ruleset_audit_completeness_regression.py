"""Regression tests for complete ruleset drift evidence and rollout policy."""

from pathlib import Path

from scripts.ci import audit_central_required_workflows as audit

REPO_ROOT = Path(__file__).resolve().parents[1]


def _central_payload() -> dict:
    """Return a minimal payload satisfying the declared central policy."""
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
                    "required_reviewers": [],
                    "dismiss_stale_reviews_on_push": True,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["merge", "squash"],
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def _repository_payload() -> dict:
    """Return a minimal payload satisfying the owner-repository policy."""
    return {
        "id": audit.REPOSITORY_RULESET_ID,
        "name": audit.REPOSITORY_RULESET_NAME,
        "source_type": "Repository",
        "source": audit.REPOSITORY_RULESET_SOURCE,
        "target": "branch",
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
                    "required_reviewers": [],
                    "dismiss_stale_reviews_on_push": True,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["merge", "squash"],
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def test_central_ruleset_rejects_creation_or_other_undeclared_rule_types() -> None:
    """A creation rule must not silently defeat the branch-create transition."""
    payload = _central_payload()
    payload["rules"].extend([{"type": "creation"}, {"type": "required_signatures"}])

    assert "central ruleset has forbidden rule types: ['creation', 'required_signatures']" in audit.audit_ruleset(payload)


def test_repository_ruleset_rejects_undeclared_rule_types() -> None:
    """The repository pass result must describe the complete protected policy."""
    payload = _repository_payload()
    payload["rules"].append({"type": "creation"})

    assert "repository ruleset has forbidden rule types: ['creation']" in audit.audit_repository_ruleset(payload)


def test_live_audit_collects_all_available_ruleset_drift_before_failing() -> None:
    """One ruleset failure must not suppress other already-fetched audit results."""
    workflow = (REPO_ROOT / ".github/workflows/audit-central-ruleset.yml").read_text(encoding="utf-8")

    assert "audit_status=0" in workflow
    assert workflow.count("if ! python3 scripts/ci/audit_central_required_workflows.py") == 3
    assert 'if [[ "$audit_status" -ne 0 ]]; then' in workflow


def test_disposable_focused_contract_is_removed_after_terminal_proof() -> None:
    """The temporary proof workflow must not survive its proven source-fix lifecycle."""
    proof_workflow = REPO_ROOT / ".github/workflows/solo-maintainer-ruleset-contract.yml"

    assert not proof_workflow.exists()


def test_rollout_guide_declares_solo_maintainer_review_policy() -> None:
    """Operator documentation must not reintroduce a fictional second human approval."""
    rollout = (REPO_ROOT / "docs/org-required-workflow-rollout.md").read_text(encoding="utf-8")

    assert "required_approving_review_count = 0" in rollout
    assert "require_last_push_approval = false" in rollout
    assert "The org's two-reviewer merge rule" not in rollout
    assert "two distinct approvals" not in rollout
