from copy import deepcopy
from io import StringIO
import json
from pathlib import Path

from scripts.ci import audit_central_required_workflows as audit


REPO_ROOT = Path(__file__).resolve().parents[1]
def ruleset_payload() -> dict:
    """Return the expected live central required-workflow ruleset shape."""
    workflow_paths = (
        "codeql-pr.yml",
        "noema-review.yml",
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
        "bypass_actors": [],
        "conditions": {
            "repository_name": {
                "include": ["~ALL"],
                "exclude": ["noema", "IRT-bibliography-set", ".github"],
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
                    "required_approving_review_count": 2,
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


def inherited_ruleset_payload() -> dict:
    """Return the repository-inherited representation used by least-privilege CI."""
    payload = ruleset_payload()
    payload["conditions"].pop("repository_name")
    payload["source_type"] = "Organization"
    payload["source"] = "ContextualWisdomLab"
    payload[audit.INHERITED_SCOPE_FIELD] = {
        ".github": False,
        "IRT-bibliography-set": False,
        "argos": True,
        "naruon": True,
        "noema": False,
        "xtrmLLMBatchPython": True,
    }
    return payload


def stacked_ruleset_payload() -> dict:
    """Return the workflow-only non-default-branch ruleset shape."""
    return {
        "id": 21732164,
        "name": "CWL Stacked OpenCode required workflow",
        "target": "branch",
        "enforcement": "evaluate",
        "conditions": {
            "ref_name": {"include": ["~ALL"], "exclude": ["~DEFAULT_BRANCH"]},
        },
        "rules": [
            {
                "type": "workflows",
                "parameters": {
                    "do_not_enforce_on_create": True,
                    "workflows": [
                        {
                            "repository_id": 1274066402,
                            "path": ".github/workflows/opencode-review.yml",
                            "ref": "refs/heads/main",
                        }
                    ],
                },
            }
        ],
    }


def test_expected_central_ruleset_passes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO(json.dumps(ruleset_payload())))

    assert audit.main([]) == 0
    assert (
            "PASS: ruleset 18156473 enforces 7 central required workflows"
        in capsys.readouterr().out
    )


def test_central_ruleset_rejects_persistent_bypass_actor() -> None:
    """A standing actor cannot bypass the exact-head review and check gates."""
    payload = ruleset_payload()
    payload["bypass_actors"] = [
        {
            "actor_id": 1,
            "actor_type": "OrganizationAdmin",
            "bypass_mode": "always",
        }
    ]

    assert audit.audit_ruleset(payload) == [
        "central ruleset has persistent bypass actors: "
        "['OrganizationAdmin:1:always']"
    ]


def test_central_ruleset_rejects_missing_bypass_actor_data() -> None:
    """An incomplete live payload cannot prove that no bypass actor exists."""
    payload = ruleset_payload()
    payload.pop("bypass_actors")

    assert audit.audit_ruleset(payload) == [
        "central ruleset bypass actor data is missing"
    ]


def test_central_ruleset_rejects_malformed_bypass_actor_data() -> None:
    """Unreadable bypass configuration fails closed."""
    payload = ruleset_payload()
    payload["bypass_actors"] = "invalid"

    assert audit.audit_ruleset(payload) == [
        "central ruleset bypass actor data is malformed"
    ]


def test_central_ruleset_describes_malformed_bypass_actor_entry() -> None:
    """A malformed standing actor remains visible in the drift reason."""
    payload = ruleset_payload()
    payload["bypass_actors"] = ["invalid"]

    assert audit.audit_ruleset(payload) == [
        "central ruleset has persistent bypass actors: ['<malformed>']"
    ]


def test_inherited_ruleset_and_organization_scope_probes_pass() -> None:
    assert audit.audit_ruleset(inherited_ruleset_payload()) == []


def test_expected_stacked_ruleset_passes(monkeypatch, capsys) -> None:
    payload = stacked_ruleset_payload()
    payload["rules"][0]["parameters"]["workflows"][0]["sha"] = "a" * 40
    monkeypatch.setattr(audit.sys, "stdin", StringIO(json.dumps(payload)))

    assert audit.main(["--stacked"]) == 0
    assert (
        "PASS: ruleset 21732164 audits 1 central required workflows in evaluate mode"
        in capsys.readouterr().out
    )


def test_stacked_ruleset_rejects_merge_policy_and_wrong_scope() -> None:
    payload = stacked_ruleset_payload()
    payload["conditions"]["ref_name"] = {"include": ["~DEFAULT_BRANCH"], "exclude": []}
    payload["rules"].append({"type": "pull_request", "parameters": {}})

    assert audit.audit_stacked_ruleset(payload) == [
        "stacked ruleset does not include all branches",
        "stacked ruleset does not exclude only default branches",
        "stacked ruleset has forbidden rule types: ['pull_request']",
    ]


def test_stacked_ruleset_rejects_additional_excluded_refs() -> None:
    payload = stacked_ruleset_payload()
    payload["conditions"]["ref_name"]["exclude"].append("refs/heads/release/**")

    assert audit.audit_stacked_ruleset(payload) == [
        "stacked ruleset does not exclude only default branches"
    ]


def test_stacked_ruleset_rejects_wrong_workflow_contract() -> None:
    payload = stacked_ruleset_payload()
    payload["rules"][0]["parameters"] = None

    assert audit.audit_stacked_ruleset(payload) == [
        "stacked OpenCode workflow does not exempt branch creation",
        "stacked ruleset must require only the central OpenCode workflow",
    ]


def test_stacked_ruleset_reports_typeless_rules_as_drift() -> None:
    payload = stacked_ruleset_payload()
    payload["rules"].append({"parameters": {}})

    assert audit.audit_stacked_ruleset(payload) == [
        "stacked ruleset has forbidden rule types: ['<missing>']"
    ]


def test_stacked_ruleset_reports_structural_drift() -> None:
    assert audit.audit_stacked_ruleset({"rules": "invalid"}) == [
        "expected stacked ruleset id 21732164",
        "expected stacked ruleset name CWL Stacked OpenCode required workflow",
        "stacked ruleset target is not branch",
        "stacked ruleset enforcement is not evaluate",
        "stacked ruleset does not include all branches",
        "stacked ruleset does not exclude only default branches",
        "expected one stacked workflows rule, found 0",
        "stacked OpenCode workflow does not exempt branch creation",
        "stacked ruleset must require only the central OpenCode workflow",
    ]


def test_inherited_scope_allows_private_exclusion_outside_token_visibility() -> None:
    payload = inherited_ruleset_payload()
    payload[audit.INHERITED_SCOPE_FIELD].pop("IRT-bibliography-set")

    assert audit.audit_ruleset(payload) == []


def test_inherited_scope_reports_every_inclusion_and_exclusion_drift() -> None:
    payload = inherited_ruleset_payload()
    payload[audit.INHERITED_SCOPE_FIELD][".github"] = True
    payload[audit.INHERITED_SCOPE_FIELD]["argos"] = False
    payload[audit.INHERITED_SCOPE_FIELD]["naruon"] = False
    payload[audit.INHERITED_SCOPE_FIELD].pop("noema")

    errors = audit.audit_ruleset(payload)

    assert "central ruleset unexpectedly applies to excluded repository .github" in errors
    assert "central ruleset is not inherited by organization repository probes: ['argos', 'naruon']" in errors
    assert "inherited repository scope probes omit expected exclusions: ['noema']" in errors


def test_inherited_scope_rejects_non_boolean_probe_results() -> None:
    payload = inherited_ruleset_payload()
    payload[audit.INHERITED_SCOPE_FIELD]["naruon"] = "yes"

    errors = audit.audit_ruleset(payload)

    assert "inherited repository scope probes are not boolean for: ['naruon']" in errors
    assert "central ruleset is not inherited by organization repository probes: ['naruon']" in errors


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


def test_missing_noema_workflow_reports_exact_drift() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"] = [
        workflow
        for workflow in workflow_rule["parameters"]["workflows"]
        if workflow["path"] != ".github/workflows/noema-review.yml"
    ]

    errors = audit.audit_ruleset(payload)

    assert "missing central required workflow .github/workflows/noema-review.yml" in errors


def test_readded_osv_scanner_workflow_reports_duplicate_scan() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"].append(
        {
            "repository_id": 1274066402,
            "path": ".github/workflows/osv-scanner-pr.yml",
            "ref": "refs/heads/main",
        }
    )

    errors = audit.audit_ruleset(payload)

    assert (
        "unexpected workflow present in required set: .github/workflows/osv-scanner-pr.yml"
        in errors
    )


def test_readded_scorecard_workflow_reports_duplicate_scan() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"].append(
        {
            "repository_id": 1274066402,
            "path": ".github/workflows/scorecard-pr.yml",
            "ref": "refs/heads/main",
        }
    )

    errors = audit.audit_ruleset(payload)

    assert (
        "unexpected workflow present in required set: .github/workflows/scorecard-pr.yml"
        in errors
    )


def test_missing_codeql_workflow_reports_exact_drift() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"] = [
        workflow
        for workflow in workflow_rule["parameters"]["workflows"]
        if workflow["path"] != ".github/workflows/codeql-pr.yml"
    ]

    errors = audit.audit_ruleset(payload)

    assert (
        "missing central required workflow .github/workflows/codeql-pr.yml"
        in errors
    )


def test_unrelated_extra_workflow_reports_unexpected_entry_sorted() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"].append(
        {
            "repository_id": 1274066402,
            "path": ".github/workflows/zzz-unrelated.yml",
            "ref": "refs/heads/main",
        }
    )
    workflow_rule["parameters"]["workflows"].append(
        {
            "repository_id": 1274066402,
            "path": ".github/workflows/aaa-unrelated.yml",
            "ref": "refs/heads/main",
        }
    )

    errors = audit.audit_ruleset(payload)

    unexpected_errors = [error for error in errors if "unexpected workflow present" in error]
    assert unexpected_errors == [
        "unexpected workflow present in required set: .github/workflows/aaa-unrelated.yml",
        "unexpected workflow present in required set: .github/workflows/zzz-unrelated.yml",
    ]


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
    review_rule["parameters"]["required_approving_review_count"] = 1
    review_rule["parameters"]["require_last_push_approval"] = False
    review_rule["parameters"]["required_review_thread_resolution"] = False

    errors = audit.audit_ruleset(payload)

    assert "exactly two approving reviews are not required" in errors
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
        "central ruleset bypass actor data is missing",
        "central ruleset does not include all repositories",
        "central ruleset repository exclusions drifted: expected ['.github', 'IRT-bibliography-set', 'noema'], got []",
        "central ruleset does not target every default branch",
        "expected one workflows rule, found 0",
        "missing central required workflow .github/workflows/codeql-pr.yml",
        "missing central required workflow .github/workflows/noema-review.yml",
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
    security_scan = next(
        workflow
        for workflow in workflows
        if isinstance(workflow, dict)
        and workflow.get("path") == ".github/workflows/security-scan.yml"
    )
    workflows.append(deepcopy(security_scan))
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"] = {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": False,
        "allowed_merge_methods": ["squash"],
    }

    errors = audit.audit_ruleset(payload)

    assert "central required workflow entry 0 is malformed" in errors
    assert "central required workflow entry 1 is malformed" in errors
    assert "central required workflow .github/workflows/security-scan.yml is configured 2 times" in errors
    assert "exactly two approving reviews are not required" in errors
    assert "stale-review dismissal on push is disabled" in errors
    assert "last-push approval protection is disabled" in errors
    assert "review-thread resolution protection is disabled" in errors
    assert "merge and squash are not both allowed merge methods" in errors


def test_audit_reports_each_malformed_workflow_entry_by_index() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"] = [
        "not-a-dict",
        {"path": 42},
        {"no_path_key": True},
    ]

    errors = audit.audit_ruleset(payload)

    assert "central required workflow entry 0 is malformed" in errors
    assert "central required workflow entry 1 is malformed" in errors
    assert "central required workflow entry 2 is malformed" in errors


def test_audit_handles_malformed_rule_parameter_shapes() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"] = None
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"] = None

    errors = audit.audit_ruleset(payload)

    assert "missing central required workflow .github/workflows/sast-semgrep.yml" in errors
    assert "exactly two approving reviews are not required" in errors


def test_load_payload_rejects_non_object_and_main_logs_load_reason(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO("[]"))

    assert audit.main([]) == 2
    assert (
        "ERROR: unable to load ruleset JSON: ruleset JSON root must be an object"
        in capsys.readouterr().err
    )


def test_scheduled_audit_and_rollout_document_semgrep_and_noema_requirements() -> None:
