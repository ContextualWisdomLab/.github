"""Contract tests for the authoritative automation documentation graph."""

from __future__ import annotations

import re
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_DOCS = REPOSITORY_ROOT / "docs" / "automation"

REQUIRED_DOCUMENTS = (
    "README.md",
    "PRD.md",
    "TRD.md",
    "EVENT_CONTRACTS.md",
    "ARCHITECTURE.md",
    "DATA_MODEL.md",
    "ERD.md",
    "UML.md",
    "SECURITY.md",
    "THREAT_MODEL.md",
    "AUTONOMY_THREATS.md",
    "TEST_STRATEGY.md",
    "OPERABILITY.md",
    "INCIDENT_RUNBOOK.md",
    "RUNBOOK.md",
    "CONTINUATION_RUNBOOK.md",
    "TRACEABILITY.md",
    "DOCUMENTATION_AUDIT.md",
)

REQUIRED_ADRS = (
    "0001-branch-writer-leases-and-read-only-audit.md",
    "0002-exact-source-and-live-base-binding.md",
    "0003-classified-bounded-retries.md",
    "0004-explicit-secret-contracts.md",
    "0005-independent-review-authority.md",
    "0006-protected-main-operational-acceptance.md",
    "0007-work-conserving-maintenance.md",
    "0008-central-control-plane-and-thin-consumers.md",
    "0009-sandbox-evidence-redaction-boundary.md",
    "0010-agent-mention-routing-and-idempotency-ledger.md",
    "0011-provider-routing-and-credential-isolation.md",
    "0012-hash-pinned-toolchains-and-exact-base-materialization.md",
    "0013-autofix-and-merge-authority-separation.md",
    "0014-trusted-metadata-event-and-default-branch-dispatch.md",
    "0015-direct-or-auto-merge-state-machine.md",
    "0016-fail-closed-security-gate-composition.md",
)

ADR_SECTIONS = (
    "## Context",
    "## Decision drivers",
    "## Alternatives considered",
    "## Decision",
    "## Consequences",
    "## Failure and recovery",
    "## Security and governance impact",
    "## Tests and acceptance",
    "## Migration and rollback",
    "## Supersession conditions",
)

DATA_ENTITIES = (
    "automation_run",
    "repository_target",
    "pull_request_snapshot",
    "source_revision",
    "base_revision",
    "merge_revision",
    "check_evidence",
    "status_evidence",
    "review_evidence",
    "model_evidence",
    "workflow_evidence",
    "dependency_evidence",
    "incident_hypothesis",
    "remediation_candidate",
    "continuation_handoff",
    "handoff_record",
    "operational_acceptance",
    "secret_requirement",
    "writer_lease",
    "documentation_artifact",
    "traceability_record",
    "organization_target",
    "orchestration_run",
    "ruleset_snapshot",
    "dispatch_envelope",
    "invocation_claim",
    "scheduler_decision",
    "review_thread",
    "security_finding",
    "sandbox_evidence",
    "sbom_snapshot",
)

CONTROLLED_MATURITY_STATES = (
    "implemented_on_protected_main",
    "active_pr",
    "accepted_architecture",
    "planned",
    "research_only",
    "superseded",
    "out_of_scope",
)


def read_document(relative_path: str) -> str:
    """Return one automation document as UTF-8 text."""

    return (AUTOMATION_DOCS / relative_path).read_text(encoding="utf-8")


def test_authoritative_document_set_exists_and_is_indexed() -> None:
    """Every required document exists, has a heading, and appears in the index."""

    index = read_document("README.md")
    for relative_path in REQUIRED_DOCUMENTS:
        document_path = AUTOMATION_DOCS / relative_path
        assert document_path.is_file(), relative_path
        content = document_path.read_text(encoding="utf-8")
        assert content.startswith("# "), relative_path
        if relative_path != "README.md":
            assert f"({relative_path})" in index, relative_path

    assert (REPOSITORY_ROOT / "ARCHITECTURE.md").is_file()
    for entrypoint in ("README.md", "AGENTS.md", "CLAUDE.md", "ARCHITECTURE.md"):
        assert "docs/automation/README.md" in (
            REPOSITORY_ROOT / entrypoint
        ).read_text(encoding="utf-8")


def test_adrs_are_indexed_and_use_the_complete_decision_template() -> None:
    """The ADR index and every decision retain the required analysis sections."""

    adr_index = read_document("adr/README.md")
    for relative_path in REQUIRED_ADRS:
        assert f"({relative_path})" in adr_index
        content = read_document(f"adr/{relative_path}")
        assert content.startswith("# ADR-")
        assert "Status:" in content and "Date:" in content
        for section in ADR_SECTIONS:
            assert section in content, f"{relative_path}: {section}"


def test_markdown_links_and_mermaid_fences_are_well_formed() -> None:
    """Local links resolve and every Markdown/Mermaid fence is balanced."""

    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for document_path in AUTOMATION_DOCS.rglob("*.md"):
        content = document_path.read_text(encoding="utf-8")
        assert content.count("```") % 2 == 0, document_path
        for target in link_pattern.findall(content):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            relative_target = target.split("#", 1)[0]
            assert (document_path.parent / relative_target).resolve().exists(), (
                document_path,
                target,
            )


def test_architecture_references_real_control_plane_sources() -> None:
    """Architecture terms remain tied to current workflow and script filenames."""

    architecture = read_document("ARCHITECTURE.md") + read_document("TRD.md")
    required_sources = (
        ".github/workflows/opencode-review.yml",
        ".github/workflows/opencode-review-dispatch.yml",
        ".github/workflows/noema-review.yml",
        ".github/workflows/strix.yml",
        "scripts/ci/pr_review_merge_scheduler.py",
        "scripts/ci/pr_review_fix_scheduler.py",
        "scripts/ci/redact_sensitive_log.py",
        "scripts/ci/sandboxed_verify.py",
        "scripts/ci/sandboxed_web_e2e.py",
    )
    for relative_path in required_sources:
        assert (REPOSITORY_ROOT / relative_path).exists(), relative_path
        assert Path(relative_path).name in architecture, relative_path


def test_conceptual_erd_uses_explicit_two_word_snake_case_entities() -> None:
    """The evidence model preserves authority entities and naming conventions."""

    data_model = read_document("DATA_MODEL.md")
    for entity_name in DATA_ENTITIES:
        assert re.fullmatch(r"[a-z]+(?:_[a-z]+)+", entity_name)
        assert entity_name in data_model
    assert "conceptual and logical" in data_model
    assert "not a claim" in data_model
    assert "pull_request_snapshot }o--|| source_revision" in data_model
    assert "automation_run }o--o| source_revision" in data_model
    assert "merge_revision ||--o{ operational_acceptance" in data_model
    assert "source_revision ||--o{ operational_acceptance" not in data_model
    assert "orchestration_run o|--o{ automation_run" in data_model
    assert "source_revision o|--o{ workflow_evidence" in data_model
    assert "standalone automation_run" in data_model
    assert "Runtime receipt and issuer aliases" in data_model
    assert "string source_kind" in data_model


def test_whole_conversation_audit_has_controlled_maturity_and_ownership() -> None:
    """Conversation-derived claims stay status-bound and product semantics stay leaf-owned."""

    audit = read_document("DOCUMENTATION_AUDIT.md")
    index = read_document("README.md")
    for state in CONTROLLED_MATURITY_STATES:
        assert f"`{state}`" in audit
    for leaf_product in (
        "TEPP",
        "OriginWeave",
        "EmbedRelay",
        "MHTML ETL",
        "LifeOS",
        "BandScope",
        "Inkspan",
        "pg-erd-cloud",
        "naruon",
        "AppGuardrail",
    ):
        assert leaf_product in audit
    audit_normalized = " ".join(audit.casefold().split())
    assert "candidate evidence" in audit_normalized
    assert "product-specific detail remains owned by the product repository" in audit_normalized
    assert "DOCUMENTATION_AUDIT.md" in index


def test_work_conservation_forbids_meta_action_and_soft_timeout_completion() -> None:
    """Meta/control events cannot replace execution or the double exit proof."""

    adr = read_document("adr/0007-work-conserving-maintenance.md")
    audit = read_document("DOCUMENTATION_AUDIT.md")
    uml = read_document("UML.md")
    corpus = adr + "\n" + audit
    for phrase in (
        "prompt update",
        "documentation assessment",
        "Draft/Ready",
        "auto-merge",
        "soft timeout",
        "second fresh sweep",
        "execution/tool-budget exhaustion",
    ):
        assert phrase.casefold() in corpus.casefold()
    assert "intermediate event" in corpus
    assert "## 11. Writer lease and branch rotation" in uml
    assert "## 12. Documentation assessment to repository mutation and continuation" in uml
    assert "supplemental visualization" in uml


def test_autonomy_threats_and_continuation_reason_codes_are_explicit() -> None:
    """Premature termination and split authority stay tied to operational ledger semantics."""

    threats = read_document("AUTONOMY_THREATS.md")
    runbook = read_document("CONTINUATION_RUNBOOK.md")
    for threat_name in (
        "premature termination",
        "false quiescence",
        "split-brain authority",
    ):
        assert threat_name in threats
    for reason_code in (
        "EXECUTABLE_NOW",
        "WAIT_CHECK_PENDING",
        "WAIT_EXTERNAL_APPROVAL",
        "WAIT_WRITER_LEASE",
        "META_INTERMEDIATE",
        "SWEEP1_EMPTY",
        "SWEEP2_EMPTY",
        "RUN_BUDGET_EXHAUSTED",
    ):
        assert reason_code in runbook
    assert "cwl.automation-continuation/v1" in runbook
    assert "Elapsed time exceeds N minutes" in runbook
    assert "source_head_sha" in runbook
    assert "live_base_tip_sha" in runbook
    for handoff_phrase in (
        "task-state or run-artifact",
        "NON_CLEAN_CONTINUATION",
        "acknowledges its `run_identity`",
        "Missing handoff state never authorizes a clean exit",
    ):
        assert handoff_phrase in runbook


def test_remediation_continuation_and_documentation_entities_are_explicit() -> None:
    """RCA alternatives, handoff, documentation and traceability stay first-class logical concepts."""

    erd = read_document("ERD.md")
    data_model = read_document("DATA_MODEL.md")
    for entity_name in (
        "remediation_candidate",
        "continuation_handoff",
        "documentation_artifact",
        "traceability_record",
    ):
        assert re.fullmatch(r"[a-z]+(?:_[a-z]+)+", entity_name)
        assert entity_name in erd
        assert entity_name in data_model
    assert "no physical database is implied" in erd
    assert "must first add an ADR" in erd


def test_standards_baseline_keeps_final_and_draft_versions_distinct() -> None:
    """Normative standards stay current and draft replacements cannot masquerade as final."""

    standards = (
        REPOSITORY_ROOT / "docs" / "doctoring" / "automation-control-plane-standards.md"
    ).read_text(encoding="utf-8")
    for final_standard in (
        "SLSA version 1.2",
        "NIST SP 800-218 version 1.1",
        "ISO/IEC/IEEE 42010:2022",
        "ISO/IEC/IEEE 29148:2018",
        "ISO/IEC 25010:2023",
    ):
        assert final_standard in standards
    assert "SLSA version 1.1" not in standards
    assert "Edition 3 Draft International Standard" in standards
    assert "informative only until published" in standards
    assert "Initial Public Draft" in standards
    assert "informative until final" in standards


def test_event_contracts_version_legacy_and_explicit_interfaces() -> None:
    """Versioned messages remain distinct from explicit legacy compatibility paths."""

    contracts = read_document("EVENT_CONTRACTS.md")
    index = read_document("README.md")
    for schema_name in (
        "cwl.agent-invocation/v2",
        "merge-scheduler-agent-review-v2",
        "pr-review-merge-scheduler/v2",
        "SANDBOXED_VERIFY_RESULT",
        "SANDBOXED_WEB_E2E_RESULT",
    ):
        assert schema_name in contracts
    for identity_field in (
        "source_head_sha",
        "pr_base_snapshot_sha",
        "live_base_tip_sha",
    ):
        assert identity_field in contracts
    assert "legacy_implicit_v1" in contracts
    assert "versioned object must never be accepted as legacy" in contracts
    assert "no blanket inheritance fallback" in contracts
    assert "EVENT_CONTRACTS.md" in index


def test_exact_head_and_stable_interface_contracts_are_explicit() -> None:
    """Critical invalidation, dispatch, marker, and receipt shapes stay named."""

    uml = read_document("UML.md")
    trd = read_document("TRD.md")
    assert "GateClean --> Stale" in uml
    assert "direct_or_auto" in uml
    for marker in ("SANDBOXED_VERIFY_RESULT", "SANDBOXED_WEB_E2E_RESULT"):
        assert marker in trd
    for field in ("allowed_env", "elapsed_seconds", "evidence_note", "exit_code"):
        assert field in trd
    assert 'pr-review-merge-scheduler/v2' in trd
    assert "cwl-agent-invocation-" in trd


def test_traceability_has_exact_identifiers_and_accountability_columns() -> None:
    """The matrix carries stable IDs and exact implementation accountability."""

    traceability = read_document("TRACEABILITY.md")
    assert "#888` is closed/unmerged `superseded`" in traceability
    assert "#906` is closed/unmerged `superseded`" in traceability
    assert "#1031` is the current open `active_pr`" in traceability
    assert "Every #1031 head change invalidates" in traceability
    for number in range(1, 15):
        assert f"`PRD-{number:02d}`" in traceability
    for requirement_id in (
        "TRD-EVT-01",
        "TRD-REV-01",
        "TRD-AUTH-01",
        "TRD-RUN-01",
        "TRD-WRITE-01",
        "TRD-SEC-01",
        "TRD-RETRY-01",
        "TRD-LOG-01",
        "TRD-IF-01",
        "TRD-RET-01",
    ):
        assert requirement_id in traceability
    for heading in (
        "Implementation/source locator",
        "Test/evidence locator",
        "Required gate / receipt authority",
        "Owner / closure target",
        "Maturity",
    ):
        assert heading in traceability


def test_security_and_operations_contracts_keep_authorities_separate() -> None:
    """High-risk credential, evidence, privacy, and closure rules stay explicit."""

    corpus = "\n".join(
        read_document(relative_path)
        for relative_path in (
            "PRD.md",
            "TRD.md",
            "EVENT_CONTRACTS.md",
            "SECURITY.md",
            "THREAT_MODEL.md",
            "AUTONOMY_THREATS.md",
            "OPERABILITY.md",
            "CONTINUATION_RUNBOOK.md",
            "INCIDENT_RUNBOOK.md",
            "TRACEABILITY.md",
        )
    )
    for required_term in (
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "secrets: inherit",
        "pull_request_target",
        "repository_dispatch",
        "expected-head",
        "qualifying independent",
        "protected-main",
        "PII",
    ):
        assert required_term in corpus


def test_timeless_architecture_does_not_embed_transient_run_identity() -> None:
    """Stable design documents avoid historical exact heads and run identifiers."""

    stable_corpus = "\n".join(
        read_document(relative_path)
        for relative_path in (
            "PRD.md",
            "TRD.md",
            "EVENT_CONTRACTS.md",
            "ARCHITECTURE.md",
            "DATA_MODEL.md",
            "UML.md",
            "SECURITY.md",
            "AUTONOMY_THREATS.md",
            "CONTINUATION_RUNBOOK.md",
        )
    )
    assert re.search(r"\b[0-9a-f]{40}\b", stable_corpus) is None
    assert re.search(r"\brun(?:_id)?[ =`]\d{8,}\b", stable_corpus, re.IGNORECASE) is None


def test_workflow_secret_registry_is_exact_and_debt_is_explicit() -> None:
    """The value-free registry equals workflow references and names known debt."""

    security = read_document("SECURITY.md")
    registry = security.split("### 3.2", 1)[1].split("## 4", 1)[0]
    registered = set(
        re.findall(r"^\| `([A-Z][A-Z0-9_]*)` \|", registry, re.MULTILINE)
    )
    reference_pattern = re.compile(
        r"""secrets(?:\.([A-Z][A-Z0-9_]*)|\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\])"""
    )
    observed: set[str] = set()
    workflow_root = REPOSITORY_ROOT / ".github" / "workflows"
    workflow_paths = tuple(workflow_root.rglob("*.yml")) + tuple(
        workflow_root.rglob("*.yaml")
    )
    for workflow_path in workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        for dot_name, bracket_name in reference_pattern.findall(workflow):
            observed.add(dot_name or bracket_name)

    expected_registry = {
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "GCP_SA_KEY",
        "NOEMA_GITHUB_APP_PRIVATE_KEY",
        "NOEMA_LLM_API_KEY",
        "NOEMA_REVIEW_TOKEN",
        "NVIDIA_NIM_API_KEY",
        "OPENAI_API_KEY",
        "OPENCODE_APPROVE_TOKEN",
        "OPENCODE_ZEN_API_KEY",
        "OPENROUTER_API_KEY",
        "PR_REVIEW_MERGE_TOKEN",
        "SBOM_INVENTORY_TOKEN",
        "STRIX_GITHUB_MODELS_TOKEN",
        "STRIX_OPENAI_API_KEY",
        "VERTEX_LOCATION",
    }
    assert registered == expected_registry
    assert observed == registered

    for known_debt in (
        ".github/workflows/pr-review-fix-scheduler.yml",
        ".github/workflows/pr-review-merge-scheduler.yml",
        ".github/workflows/pr-auto-rebase.yml",
        ".github/workflows/deploy-pages.yml",
    ):
        assert known_debt in security
    assert "registry proves name inventory, not reusable-call mapping" in security
    assert "target contract, not a claim that every protected-main path" in security


def test_current_lineage_threat_maturity_and_gap_objects_are_exact() -> None:
    """Lineage and maturity stay bound to current PRs/issues, not stale claims."""

    threat_model = read_document("THREAT_MODEL.md")
    redaction_adr = read_document(
        "adr/0009-sandbox-evidence-redaction-boundary.md"
    )
    for document in (threat_model, redaction_adr):
        assert "#842" not in document
        assert "/pull/842" not in document
        assert "https://github.com/ContextualWisdomLab/.github/pull/888" in document
        assert "https://github.com/ContextualWisdomLab/.github/pull/906" in document
        assert "https://github.com/ContextualWisdomLab/.github/pull/1031" in document
        assert "closed unmerged" in document
        assert "superseded" in document
        assert "Draft" in document

    traceability_section = threat_model.split(
        "## 7. Exact source and test traceability", 1
    )[1]
    observed_threat_maturity = dict(
        re.findall(
            r"^\| (TM-\d{2}) \|[^\n]*\| `([a-z_]+)` \|$",
            traceability_section,
            re.MULTILINE,
        )
    )
    assert observed_threat_maturity == {
        "TM-01": "active_pr",
        "TM-02": "accepted_architecture",
        "TM-03": "active_pr",
        "TM-04": "implemented_on_protected_main",
        "TM-05": "implemented_on_protected_main",
        "TM-06": "implemented_on_protected_main",
        "TM-07": "implemented_on_protected_main",
        "TM-08": "implemented_on_protected_main",
        "TM-09": "accepted_architecture",
        "TM-10": "active_pr",
        "TM-11": "planned",
        "TM-12": "accepted_architecture",
        "TM-13": "accepted_architecture",
        "TM-14": "implemented_on_protected_main",
        "TM-15": "accepted_architecture",
    }

    trd = read_document("TRD.md")
    traceability = read_document("TRACEABILITY.md")
    gap_objects = {
        "IG-001": (
            "https://github.com/ContextualWisdomLab/.github/pull/1021",
            "active_pr",
        ),
        "IG-002": (
            "https://github.com/ContextualWisdomLab/.github/issues/772",
            "planned",
        ),
        "IG-003": (
            "https://github.com/ContextualWisdomLab/.github/issues/889",
            "planned",
        ),
        "IG-004": (
            "https://github.com/ContextualWisdomLab/.github/issues/890",
            "planned",
        ),
        "IG-005": (
            "https://github.com/ContextualWisdomLab/.github/issues/891",
            "planned",
        ),
        "IG-006": (
            "https://github.com/ContextualWisdomLab/.github/issues/892",
            "planned",
        ),
        "IG-007": (
            "https://github.com/ContextualWisdomLab/.github/issues/893",
            "planned",
        ),
        "IG-008": (
            "https://github.com/ContextualWisdomLab/.github/pull/899",
            "active_pr",
        ),
    }
    traceability_lines = traceability.splitlines()
    for gap_id, (object_url, maturity) in gap_objects.items():
        assert gap_id in trd
        assert object_url in trd
        gap_line = next(
            line for line in traceability_lines if line.startswith(f"| `{gap_id}`")
        )
        assert object_url in gap_line
        assert gap_line.endswith(f"| `{maturity}` |")


def test_current_executable_policy_corrections_are_machine_checked() -> None:
    """Historical ledgers cannot silently override current executable policy."""

    root_readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    rollout = (REPOSITORY_ROOT / "docs/org-required-workflow-rollout.md").read_text(
        encoding="utf-8"
    )
    historical_audit = (REPOSITORY_ROOT / "PR_GOVERNANCE_AUDIT.md").read_text(
        encoding="utf-8"
    )
    nvidia_note = (
        REPOSITORY_ROOT / "docs/nvidia-nim-opencode-hotfix.md"
    ).read_text(encoding="utf-8")
    scorecard = (REPOSITORY_ROOT / "docs/scorecard-governance.md").read_text(
        encoding="utf-8"
    )
    ruleset_audit = (
        REPOSITORY_ROOT / "scripts/ci/audit_central_required_workflows.py"
    ).read_text(encoding="utf-8")

    assert "exactly two approving reviews" in root_readme
    assert "cannot invoke Bash, task/subagents, or webfetch" in root_readme
    for correction_ledger in (rollout, historical_audit):
        assert "cancel-in-progress: true" in correction_ledger
        assert "https://github.com/ContextualWisdomLab/.github/issues/889" in (
            correction_ledger
        )
        assert "central autofix worker" in correction_ledger

    assert "NVIDIA_NIM_API_KEY" in nvidia_note
    assert "No legacy secret alias is accepted" in nvidia_note
    assert "No branch-protection or ruleset bypass is authorized" in nvidia_note
    assert "exactly two eligible approvals" in scorecard
    assert 'EXPECTED_EXCLUSIONS = {".github", "IRT-bibliography-set", "noema"}' in (
        ruleset_audit
    )
    assert "if approving_reviews != 2:" in ruleset_audit

    mention_contract = read_document("review-agent-comment-invocation.md")
    assert "dispatch evidence" in mention_contract
    assert "at-most-once dead-letter" in mention_contract
    assert "https://github.com/ContextualWisdomLab/.github/issues/893" in (
        mention_contract
    )
    sbom_inventory = (REPOSITORY_ROOT / "docs/sbom/inventory.md").read_text(
        encoding="utf-8"
    )
    assert "unmaterialized generated-artifact state" in sbom_inventory
    assert "not proof that the organization has zero" in " ".join(sbom_inventory.split())


def test_documentation_changes_trigger_full_quality_ci() -> None:
    """The documentation graph has a permanent exact-head full-suite gate."""

    workflow = (
        REPOSITORY_ROOT
        / ".github/workflows/automation-documentation-quality-ci.yml"
    ).read_text(encoding="utf-8")
    assert "name: Automation Documentation Quality CI" in workflow
    for watched_path in (
        '"docs/**"',
        '"*.md"',
        '"tests/**"',
        '"requirements-opencode-review-ci-hashes.txt"',
    ):
        assert watched_path in workflow
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert "persist-credentials: false" in workflow
    assert "python -m coverage run -m pytest tests -q" in workflow
    assert "python -m coverage report --fail-under=100" in workflow
    assert "python -m compileall -q tests" in workflow
