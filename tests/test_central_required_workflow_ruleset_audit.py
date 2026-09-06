import json
from copy import deepcopy
from io import StringIO
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
                    "do_not_enforce_on_create": True,
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
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
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


def repository_ruleset_payload() -> dict:
    """Return the expected strong default-branch policy for the owner repo."""

    return {
        "id": 17921150,
        "name": "Lock default branch",
        "target": "branch",
        "source_type": "Repository",
        "source": "ContextualWisdomLab/.github",
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


def test_expected_central_ruleset_passes(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO(json.dumps(ruleset_payload())))

    assert audit.main([]) == 0
    assert (
            "PASS: ruleset 18156473 enforces 7 central required workflows"
        in capsys.readouterr().out
    )


def test_central_ruleset_preserves_a_valid_code_scanning_gate() -> None:
    """A declared CodeQL code-scanning rule remains compatible with reconciliation."""

    payload = ruleset_payload()
    payload["rules"].append(
        {
            "type": "code_scanning",
            "parameters": {
                "code_scanning_tools": [
                    {
                        "tool": "CodeQL",
                        "alerts_threshold": "errors",
                        "security_alerts_threshold": "high_or_higher",
                    }
                ]
            },
        }
    )

    assert audit.audit_ruleset(payload) == []


def test_central_ruleset_rejects_unexpected_and_malformed_workflows() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["workflows"].extend(
        [
            {
                "repository_id": 1274066402,
                "path": ".github/workflows/unexpected.yml",
                "ref": "refs/heads/main",
            },
            {"repository_id": 1274066402, "path": 42, "ref": "refs/heads/main"},
        ]
    )

    errors = audit.audit_ruleset(payload)

    assert "unexpected workflow present in required set: .github/workflows/unexpected.yml" in errors
    assert "central required workflows contain 1 malformed entry" in errors


def test_central_ruleset_rejects_rebase_merge_method() -> None:
    payload = ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["allowed_merge_methods"].append("rebase")

    assert "only merge and squash may be allowed merge methods" in audit.audit_ruleset(payload)


def test_central_ruleset_rejects_bypass_actors() -> None:
    payload = ruleset_payload()
    payload["bypass_actors"] = [
        {
            "actor_id": None,
            "actor_type": "OrganizationAdmin",
            "bypass_mode": "always",
        }
    ]

    assert audit.audit_ruleset(payload) == [
        "central ruleset must not configure bypass actors",
    ]


def test_central_ruleset_rejects_missing_bypass_evidence() -> None:
    payload = ruleset_payload()
    del payload["bypass_actors"]

    assert audit.audit_ruleset(payload) == [
        "central ruleset must not configure bypass actors",
    ]


def test_inherited_ruleset_and_organization_scope_probes_pass() -> None:
    assert audit.audit_ruleset(inherited_ruleset_payload()) == []


def test_expected_repository_ruleset_passes() -> None:
    assert hasattr(audit, "audit_repository_ruleset"), (
        "the central audit must inspect the repository ruleset that protects .github"
    )
    assert audit.audit_repository_ruleset(repository_ruleset_payload()) == []


def test_repository_ruleset_rejects_unsatisfiable_review_controls() -> None:
    assert hasattr(audit, "audit_repository_ruleset"), (
        "the central audit must inspect the repository ruleset that protects .github"
    )
    payload = repository_ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["required_approving_review_count"] = 1
    review_rule["parameters"]["require_last_push_approval"] = True

    assert audit.audit_repository_ruleset(payload) == [
        "repository solo-maintainer ruleset must not require approving reviews",
        "repository solo-maintainer ruleset must not require last-push approval",
    ]


def test_repository_ruleset_rejects_rebase_merge_method() -> None:
    payload = repository_ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["allowed_merge_methods"].append("rebase")

    assert audit.audit_repository_ruleset(payload) == [
        "repository ruleset must allow only merge and squash",
    ]


def test_repository_ruleset_rejects_bypass_actors() -> None:
    payload = repository_ruleset_payload()
    payload["bypass_actors"] = [
        {
            "actor_id": None,
            "actor_type": "OrganizationAdmin",
            "bypass_mode": "always",
        }
    ]

    assert audit.audit_repository_ruleset(payload) == [
        "repository ruleset must not configure bypass actors",
    ]


def test_repository_ruleset_rejects_missing_bypass_evidence() -> None:
    payload = repository_ruleset_payload()
    del payload["bypass_actors"]

    assert audit.audit_repository_ruleset(payload) == [
        "repository ruleset must not configure bypass actors",
    ]


def test_repository_ruleset_reports_structural_and_protection_drift() -> None:
    payload = {
        "id": 0,
        "name": "drifted",
        "source_type": "Organization",
        "source": "ContextualWisdomLab",
        "target": "tag",
        "enforcement": "disabled",
        "conditions": None,
        "rules": "not-a-list",
    }

    assert audit.audit_repository_ruleset(payload) == [
        "expected repository ruleset id 17921150",
        "expected repository ruleset name Lock default branch",
        "repository ruleset source is not ContextualWisdomLab/.github",
        "repository ruleset target is not branch",
        "repository ruleset enforcement is not active",
        "repository ruleset must not configure bypass actors",
        "repository ruleset ref scope must be exactly the default branch",
        "expected one repository pull_request rule, found 0",
        "repository default-branch deletion protection is missing",
        "repository default-branch non-fast-forward protection is missing",
    ]


def test_repository_ruleset_rejects_malformed_review_parameters() -> None:
    payload = repository_ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"] = None

    assert audit.audit_repository_ruleset(payload) == [
        "repository solo-maintainer ruleset must not require approving reviews",
        "repository solo-maintainer ruleset must not require code-owner review",
        "repository ruleset stale-review dismissal on push is disabled",
        "repository solo-maintainer ruleset must not require last-push approval",
        "repository ruleset review-thread resolution protection is disabled",
        "repository ruleset must allow only merge and squash",
    ]


def test_repository_ruleset_cli_reports_passing_policy(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        audit.sys,
        "stdin",
        StringIO(json.dumps(repository_ruleset_payload())),
    )

    assert audit.main(["--repository"]) == 0
    assert (
        "PASS: repository ruleset 17921150 protects the default branch"
        in capsys.readouterr().out
    )


def test_ref_scope_rejects_all_branch_and_extra_proposal_branch_targets() -> None:
    for include in (
        ["~ALL"],
        ["~DEFAULT_BRANCH", "~ALL"],
        ["~DEFAULT_BRANCH", "refs/heads/feature/*"],
    ):
        payload = ruleset_payload()
        payload["conditions"]["ref_name"]["include"] = include

        assert audit.audit_ruleset(payload) == [
            "central ruleset ref scope must be exactly the default branch"
        ]


def test_ref_scope_rejects_branch_exclusions() -> None:
    """The strict default-branch ruleset must not hide excluded refs."""

    payload = ruleset_payload()
    payload["conditions"]["ref_name"]["exclude"] = ["refs/heads/release/*"]

    assert audit.audit_ruleset(payload) == [
        "central ruleset ref scope must be exactly the default branch"
    ]


def test_ref_scope_rejects_string_include() -> None:
    """The ruleset API contract requires an exact include list."""
    payload = ruleset_payload()
    payload["conditions"]["ref_name"]["include"] = "~ALL"

    assert audit.audit_ruleset(payload) == [
        "central ruleset ref scope must be exactly the default branch"
    ]


def test_workflows_must_not_block_branch_create_transition() -> None:
    payload = ruleset_payload()
    workflow_rule = next(rule for rule in payload["rules"] if rule["type"] == "workflows")
    workflow_rule["parameters"]["do_not_enforce_on_create"] = False

    assert audit.audit_ruleset(payload) == [
        "central required workflows block the branch create transition"
    ]


def test_multiple_workflow_rules_do_not_invent_create_transition_drift() -> None:
    """Report structural multiplicity without attributing a missing flag to it."""
    payload = ruleset_payload()
    payload["rules"].append(payload["rules"][0].copy())

    errors = audit.audit_ruleset(payload)

    assert "expected one workflows rule, found 2" in errors
    assert "central required workflows block the branch create transition" not in errors


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


def test_unsatisfiable_review_policy_reports_exact_drift() -> None:
    payload = ruleset_payload()
    review_rule = next(rule for rule in payload["rules"] if rule["type"] == "pull_request")
    review_rule["parameters"]["required_approving_review_count"] = 1
    review_rule["parameters"]["require_last_push_approval"] = True
    review_rule["parameters"]["required_review_thread_resolution"] = False

    errors = audit.audit_ruleset(payload)

    assert "central solo-maintainer ruleset must not require approving reviews" in errors
    assert "central solo-maintainer ruleset must not require last-push approval" in errors
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
        "central ruleset must not configure bypass actors",
        "central ruleset does not include all repositories",
        "central ruleset repository exclusions drifted: expected ['.github', 'IRT-bibliography-set', 'noema'], got []",
        "central ruleset ref scope must be exactly the default branch",
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


def test_audit_handles_duplicate_workflows_and_unsatisfiable_review_parameters() -> None:
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
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": False,
        "require_last_push_approval": True,
        "required_review_thread_resolution": False,
        "allowed_merge_methods": ["squash"],
    }

    errors = audit.audit_ruleset(payload)

    assert "central required workflow entry 0 is malformed" in errors
    assert "central required workflow entry 1 is malformed" in errors
    assert "central required workflow .github/workflows/security-scan.yml is configured 2 times" in errors
    assert "central solo-maintainer ruleset must not require approving reviews" in errors
    assert "stale-review dismissal on push is disabled" in errors
    assert "central solo-maintainer ruleset must not require last-push approval" in errors
    assert "review-thread resolution protection is disabled" in errors
    assert "only merge and squash may be allowed merge methods" in errors


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
    assert "central solo-maintainer ruleset must not require approving reviews" in errors
    assert "central solo-maintainer ruleset must not require last-push approval" in errors


def test_load_payload_rejects_non_object_and_main_logs_load_reason(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO("[]"))

    assert audit.main([]) == 2
    assert (
        "ERROR: unable to load ruleset JSON: ruleset JSON root must be an object"
        in capsys.readouterr().err
    )


def test_scheduled_audit_and_rollout_document_semgrep_and_noema_requirements() -> None:
    workflow = (REPO_ROOT / ".github/workflows/audit-central-ruleset.yml").read_text(
        encoding="utf-8"
    )
    rollout = (REPO_ROOT / "docs/org-required-workflow-rollout.md").read_text(
        encoding="utf-8"
    )

    assert 'cron: "11 2 * * *"' in workflow
    assert "repos/${ORG_LOGIN}/${RULESET_SENTINEL_REPOSITORY}/rulesets/${RULESET_ID}" in workflow
    assert 'orgs/${ORG_LOGIN}/repos?type=all&per_page=100' in workflow
    assert "RULESET_SCOPE repository=${repository} inherited=${inherited}" in workflow
    assert "HTTP 404" in workflow
    assert "audit_central_required_workflows.py" in workflow
    assert "Ruleset audit could not read inherited organization ruleset" in workflow
    assert 'STACKED_RULESET_ID: "21732164"' in workflow
    assert "audit_central_required_workflows.py --stacked" in workflow
    assert 'REPOSITORY_RULESET_ID: "17921150"' in workflow
    assert (
        "repos/${ORG_LOGIN}/.github/rulesets/${REPOSITORY_RULESET_ID}"
        in workflow
    )
    assert "audit_central_required_workflows.py --repository" in workflow
    assert "CWL Stacked OpenCode required workflow" in rollout
    assert 'ref_name.exclude=["~DEFAULT_BRANCH"]' in rollout
    assert "- `.github/workflows/noema-review.yml`" in rollout
    assert "- `.github/workflows/sast-semgrep.yml`" in rollout


def test_audit_organization_codeql_coverage_step_has_freshness_and_credential_guard() -> None:
    workflow = (REPO_ROOT / ".github/workflows/audit-central-ruleset.yml").read_text(
        encoding="utf-8"
    )

    assert "Audit organization CodeQL coverage" in workflow
    assert (
        "ORG_WIDE_CREDENTIAL_AVAILABLE: ${{ secrets.PR_REVIEW_MERGE_TOKEN != '' "
        "|| secrets.OPENCODE_APPROVE_TOKEN != '' }}"
    ) in workflow
    assert 'if [ "$ORG_WIDE_CREDENTIAL_AVAILABLE" = "false" ]; then' in workflow
    assert (
        "::error::CodeQL coverage audit requires an org-scoped credential "
        "(PR_REVIEW_MERGE_TOKEN or OPENCODE_APPROVE_TOKEN) to reliably enumerate "
        "private organization repositories"
    ) in workflow
    assert (
        'if [ "$ORG_WIDE_CREDENTIAL_AVAILABLE" = "false" ]; then\n'
        '            echo "::error::CodeQL coverage audit requires an '
        "org-scoped credential (PR_REVIEW_MERGE_TOKEN or OPENCODE_APPROVE_TOKEN) "
        "to reliably enumerate private organization repositories; the "
        "repository-scoped github.token fallback cannot see them, which would "
        'silently narrow this audit to a subset of the organization."\n'
        "            exit 1\n"
        "          fi"
    ) in workflow
    assert (
        'repos/${ORG_LOGIN}/${repository}/code-scanning/default-setup" --jq .state'
        in workflow
    )
    assert (
        'if [ "$archived" != "true" ]; then\n'
        '              default_setup_state_json="$RUNNER_TEMP/codeql-default-setup-'
        '${repository//[^A-Za-z0-9_.-]/_}.json"'
    ) in workflow
    assert (
        "repos/${ORG_LOGIN}/${repository}/code-scanning/analyses?tool_name="
        "CodeQL&per_page=1"
    ) in workflow
    assert "--jq '.[0] | if . then {created_at, error} else null end'" in workflow
    assert "latest_codeql_analysis=null" in workflow
    assert (
        'if [ "$archived" != "true" ]; then\n'
        '              analysis_json="$RUNNER_TEMP/codeql-analysis-'
        '${repository//[^A-Za-z0-9_.-]/_}.json"'
    ) in workflow
    assert "python3 scripts/ci/audit_org_codeql_coverage.py" in workflow


def test_codeql_gap_bootstrap_uses_trusted_opencode_identity_without_pr_head_execution() -> None:
    """Backlog item 38 stays on trusted main and treats installation tokens as opaque."""
    workflow = (REPO_ROOT / ".github/workflows/audit-central-ruleset.yml").read_text(
        encoding="utf-8"
    )
    bootstrap_step = workflow.split(
        "- name: Exchange OpenCode app token for CodeQL setup writes\n", 1
    )[1]

    assert "id-token: write" in workflow
    assert "audience=${OIDC_AUDIENCE}" in bootstrap_step
    assert "/exchange_github_app_token" in bootstrap_step
    assert "token<<OPENCODE_TOKEN" in bootstrap_step
    assert "bootstrap_codeql_pull_requests.py" in bootstrap_step
    assert '"scripts/ci/bootstrap_codeql_pull_requests.py"' in workflow
    assert "pull_request_target:" not in workflow
    assert "pull_request:" not in workflow
    assert "refs/pull/" not in bootstrap_step
    assert "ghs_" not in bootstrap_step
    assert "length" not in bootstrap_step
    assert (
        "central-required-workflow-ruleset-audit-${{ github.event_name == "
        "'repository_dispatch' && github.event.action || github.event_name }}"
        in workflow
    )


def test_audit_organization_codeql_coverage_step_verifies_sentinel_repository_completeness() -> None:
    """Devin finding: 'Private repositories disappear from audit'.

    ORG_WIDE_CREDENTIAL_AVAILABLE only proves *some* org-scoped secret
    exists, not that the specific credential used (PR_REVIEW_MERGE_TOKEN
    when present) can see the full organization. A fine-grained token with
    an incomplete repository allowlist does not 403 on the enumeration
    call -- it silently returns a smaller repository list. This pins the
    real post-enumeration completeness check: known-private, non-archived
    sentinel repositories must all appear in the enumerated list, or the
    step fails loudly instead of silently auditing a partial organization.
    """
    workflow = (REPO_ROOT / ".github/workflows/audit-central-ruleset.yml").read_text(
        encoding="utf-8"
    )

    codeql_step = workflow.split('- name: "Audit organization CodeQL coverage"\n', 1)
    if len(codeql_step) == 1:
        codeql_step = workflow.split("- name: Audit organization CodeQL coverage\n", 1)
    assert len(codeql_step) == 2, "CodeQL coverage step not found in workflow"
    step_body = codeql_step[1]

    assert 'PRIVATE_REPOSITORY_COVERAGE_SENTINELS=(' in step_body
    assert '"xtrmLLMBatchPython"' in step_body
    assert '"linux-cluster-ops"' in step_body
    assert '"gyeot"' in step_body
    assert (
        'jq -e --arg name "$sentinel" \'any(.[]; .name == $name)\' "$repositories_json"'
        in step_body
    )
    assert 'missing_sentinels=()' in step_body
    assert (
        'if [ "${#missing_sentinels[@]}" -gt 0 ]; then\n'
        '            echo "::error::CodeQL coverage audit\'s organization '
        'repository enumeration is missing known-private sentinel '
        "repository(ies): ${missing_sentinels[*]}."
    ) in step_body
    # The sentinel check must run against the same repositories_json used to
    # drive the per-repository coverage loop below it, and must exit before
    # that loop starts on a partial list.
    sentinel_check_index = step_body.index("PRIVATE_REPOSITORY_COVERAGE_SENTINELS=(")
    coverage_loop_index = step_body.index("printf '[]\\n' >\"$coverage_json\"")
    assert sentinel_check_index < coverage_loop_index
    exit_index = step_body.index(
        "exit 1", step_body.index("missing_sentinels[@]")
    )
    assert exit_index < coverage_loop_index


def test_central_semgrep_filters_source_suppressions_and_gates_on_sarif_results() -> None:
    workflow = (REPO_ROOT / ".github/workflows/sast-semgrep.yml").read_text(
        encoding="utf-8"
    )

    assert "--output=semgrep-results.raw.sarif" in workflow
    assert (
        'SEMGREP_IMAGE: "semgrep/semgrep@sha256:'
        "2b33f46ba66cf8cc2ad59ccfa7d22951fd00c632c38f1339e84ec8e6e641a942\""
    ) in workflow
    assert (
        workflow.count(
            "2b33f46ba66cf8cc2ad59ccfa7d22951fd00c632c38f1339e84ec8e6e641a942"
        )
        == 1
    )
    semgrep_job = workflow.split("\n  semgrep:\n", 1)[1]
    job_header, steps = semgrep_job.split("\n    steps:\n", 1)
    assert 'SEMGREP_IMAGE: "semgrep/semgrep@sha256:' in job_header
    assert 'echo "Using ${SEMGREP_IMAGE}"' in steps
    assert 'docker manifest inspect "${SEMGREP_IMAGE}"' in steps
    assert '--entrypoint semgrep \\\n            "${SEMGREP_IMAGE}" \\\n' in steps
    assert "Verify pinned Semgrep manifest" in workflow
    assert "Remove explicitly suppressed findings from Semgrep SARIF" in workflow
    assert ".suppressions // []" in workflow
    assert "SEMGREP_SUPPRESSED_COUNT" in workflow
    assert "semgrep_sarif.outputs.finding_count != '0'" in workflow
    assert 'SEMGREP_FINDING_COUNT:-missing}' in workflow
    assert "--output=semgrep-results.sarif" not in workflow
