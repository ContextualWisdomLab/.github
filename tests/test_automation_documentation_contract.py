"""Contract tests for the central automation documentation spine."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_DOCS = ROOT / "docs" / "automation"

REQUIRED_DOCUMENTS = (
    "README.md",
    "PRD.md",
    "TRD.md",
    "ARCHITECTURE.md",
    "UML.md",
    "ERD.md",
    "SECURITY.md",
    "THREAT_MODEL.md",
    "TEST_STRATEGY.md",
    "OPERABILITY.md",
    "INCIDENT_RUNBOOK.md",
    "TRACEABILITY.md",
    "DOCUMENTATION_COVERAGE.md",
)

REQUIRED_ADRS = (
    "0001-writer-lease-and-read-only-fleet-auditor.md",
    "0002-exact-head-and-live-base-binding.md",
    "0003-classified-bounded-retries.md",
    "0004-minimal-reusable-workflow-secrets.md",
    "0005-independent-review-governance.md",
    "0006-protected-main-operational-closure.md",
    "0007-work-conserving-automation.md",
    "0008-central-control-plane-thin-leaf-contract.md",
)

ADR_SECTIONS = (
    "## Context",
    "## Decision drivers",
    "## Considered alternatives",
    "## Decision",
    "## Consequences",
    "## Failure and recovery",
    "## Security and governance",
    "## Verification",
    "## Migration and rollback",
    "## Supersession",
)

PRD_IDS = tuple(f"PRD-{number:03d}" for number in range(1, 14))
THREAT_IDS = tuple(f"TM-{number:03d}" for number in range(1, 15))


class AutomationDocumentationContractTests(unittest.TestCase):
    """Keep the control-plane documentation complete, linked, and code-current."""

    def test_required_documentation_spine_exists_and_is_indexed(self) -> None:
        """Every canonical document must exist and be linked from the index."""

        index = (AUTOMATION_DOCS / "README.md").read_text(encoding="utf-8")
        for relative_path in REQUIRED_DOCUMENTS:
            path = AUTOMATION_DOCS / relative_path
            self.assertTrue(path.is_file(), relative_path)
            self.assertIn(f"]({relative_path})", index, relative_path)

    def test_required_adrs_have_complete_decision_records(self) -> None:
        """Every minimum ADR must be indexed and contain the governed sections."""

        index_path = AUTOMATION_DOCS / "adr" / "README.md"
        self.assertTrue(index_path.is_file())
        index = index_path.read_text(encoding="utf-8")
        for relative_path in REQUIRED_ADRS:
            path = index_path.parent / relative_path
            self.assertTrue(path.is_file(), relative_path)
            self.assertIn(f"]({relative_path})", index, relative_path)
            body = path.read_text(encoding="utf-8")
            self.assertRegex(body, r"(?m)^# ADR-\d{4}: ")
            self.assertRegex(body, r"(?m)^Status: (?:Accepted|Proposed|Superseded|Rejected)")
            self.assertRegex(body, r"(?m)^Date: \d{4}-\d{2}-\d{2}$")
            self.assertRegex(body, r"(?m)^Owner: \S.+$")
            for section in ADR_SECTIONS:
                self.assertIn(section, body, f"{relative_path}: {section}")

    def test_mermaid_diagrams_are_balanced_and_supported(self) -> None:
        """Diagram-as-code fences must be balanced and use supported diagram types."""

        allowed = ("flowchart ", "sequenceDiagram", "stateDiagram-v2", "erDiagram")
        for relative_path in ("ARCHITECTURE.md", "UML.md", "ERD.md"):
            body = (AUTOMATION_DOCS / relative_path).read_text(encoding="utf-8")
            blocks = re.findall(r"```mermaid\n(.*?)\n```", body, flags=re.DOTALL)
            self.assertTrue(blocks, relative_path)
            self.assertEqual(body.count("```mermaid"), len(blocks), relative_path)
            for block in blocks:
                first_line = block.lstrip().splitlines()[0]
                self.assertTrue(first_line.startswith(allowed), first_line)

    def test_workflow_references_resolve_to_tracked_files(self) -> None:
        """Backticked workflow paths in canonical docs must resolve in this tree."""

        for relative_path in REQUIRED_DOCUMENTS:
            body = (AUTOMATION_DOCS / relative_path).read_text(encoding="utf-8")
            for workflow in set(re.findall(r"`(\.github/workflows/[^`]+\.yml)`", body)):
                self.assertTrue((ROOT / workflow).is_file(), f"{relative_path}: {workflow}")

    def test_evidence_authorities_and_domain_entities_are_explicit(self) -> None:
        """Authority separation and evidence identity must not collapse into prose shortcuts."""

        technical = (AUTOMATION_DOCS / "TRD.md").read_text(encoding="utf-8")
        traceability = (AUTOMATION_DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
        data_model = (AUTOMATION_DOCS / "ERD.md").read_text(encoding="utf-8")
        for term in (
            "check evidence",
            "status evidence",
            "formal review evidence",
            "merge authority",
            "release authority",
        ):
            self.assertIn(term, technical.lower())
        for entity in (
            "automation_run",
            "repository_target",
            "pull_request_snapshot",
            "source_revision",
            "base_revision",
            "check_evidence",
            "review_evidence",
            "workflow_evidence",
            "dependency_evidence",
            "incident_hypothesis",
            "handoff_record",
            "operational_acceptance",
            "secret_requirement",
            "writer_lease",
        ):
            self.assertIn(entity, data_model)
        self.assertIn("conceptual", data_model.lower())
        self.assertIn("persisted", data_model.lower())
        self.assertIn("ContextualWisdomLab/.github#840", traceability)
        self.assertIn("ContextualWisdomLab/.github#842", traceability)

    def test_entry_points_link_the_authoritative_index(self) -> None:
        """Agent and maintainer entry points must discover the canonical spine."""

        expected_link = "docs/automation/README.md"
        for relative_path in (
            "README.md",
            "AGENTS.md",
            "CLAUDE.md",
            "docs/CWL-MASTER-CONTEXT.md",
        ):
            body = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn(expected_link, body, relative_path)

    def test_local_markdown_links_resolve(self) -> None:
        """Canonical relative Markdown links must resolve to a file in this tree."""

        for path in AUTOMATION_DOCS.rglob("*.md"):
            body = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
                target = target.split("#", 1)[0].split("?", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                self.assertTrue((path.parent / target).resolve().is_file(), f"{path}: {target}")

    def test_secret_registry_exactly_covers_workflow_secret_names(self) -> None:
        """Every workflow secret name needs a value-free governed registry row."""

        workflow_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        )
        used_names = set(re.findall(r"secrets\.([A-Z][A-Z0-9_]*)", workflow_text))
        security = (AUTOMATION_DOCS / "SECURITY.md").read_text(encoding="utf-8")
        registry_names = set(
            re.findall(r"(?m)^\| `([A-Z][A-Z0-9_]*)` \|", security)
        )
        self.assertEqual(used_names, registry_names)
        self.assertIn("minimum scope", security.lower())
        self.assertIn("rotation or revocation", security.lower())

    def test_requirement_and_threat_ids_are_fully_traced(self) -> None:
        """No product requirement or registered threat may be orphaned."""

        product = (AUTOMATION_DOCS / "PRD.md").read_text(encoding="utf-8")
        threats = (AUTOMATION_DOCS / "THREAT_MODEL.md").read_text(encoding="utf-8")
        trace = (AUTOMATION_DOCS / "TRACEABILITY.md").read_text(encoding="utf-8")
        for requirement_id in PRD_IDS:
            self.assertIn(requirement_id, product)
            self.assertIn(requirement_id, trace)
        for threat_id in THREAT_IDS:
            self.assertIn(threat_id, threats)
            self.assertIn(threat_id, trace)

        technical = (AUTOMATION_DOCS / "TRD.md").read_text(encoding="utf-8")
        for gap_id in (f"IG-00{number}" for number in range(1, 9)):
            self.assertIn(gap_id, technical)
        for issue_number in (772, 840, 842, 889, 890, 891, 892, 893, 894):
            self.assertIn(f"ContextualWisdomLab/.github#{issue_number}", trace)

    def test_documented_live_invariants_match_executable_contracts(self) -> None:
        """Prevent known dated-prose contradictions from returning."""

        strix = (ROOT / ".github" / "workflows" / "strix.yml").read_text(
            encoding="utf-8"
        )
        concurrency = strix.split("concurrency:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("cancel-in-progress: true", concurrency)
        self.assertIn("github.event.pull_request.number", concurrency)
        self.assertNotIn("github.event.pull_request.head.sha", concurrency)

        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        rollout = (ROOT / "docs" / "org-required-workflow-rollout.md").read_text(
            encoding="utf-8"
        )
        audit = (ROOT / "PR_GOVERNANCE_AUDIT.md").read_text(encoding="utf-8")
        for body in (root_readme, rollout, audit):
            self.assertNotIn("cancel-in-progress: false", body)
            self.assertNotIn("scopes PR Strix concurrency by head SHA", body)
        self.assertIn("PR-number concurrency", root_readme)

        reviewer_prompt = (ROOT / "code-reviewer-prompt.md").read_text(encoding="utf-8")
        reviewer_config = (ROOT / "opencode.jsonc").read_text(encoding="utf-8")
        self.assertIn("Bash, task/subagents, webfetch", reviewer_prompt)
        for denied_tool in ('"bash": "deny"', '"task": "deny"', '"webfetch": "deny"'):
            self.assertIn(denied_tool, reviewer_config)
        for body in (root_readme, rollout):
            self.assertNotIn("run safe local verification commands", body)

        scorecard = (ROOT / "docs" / "scorecard-governance.md").read_text(
            encoding="utf-8"
        )
        ruleset_auditor = (
            ROOT / "scripts" / "ci" / "audit_central_required_workflows.py"
        ).read_text(encoding="utf-8")
        self.assertIn("exactly two eligible", scorecard)
        self.assertIn('approving_reviews != 2', ruleset_auditor)
        self.assertNotIn("single-maintainer approval gate", scorecard)

        self.assertIn("central autofix worker", rollout)
        self.assertNotIn("keep autofix workflows repo-local", audit.lower())
        self.assertNotIn("fork or external-head PRs remain reviewable", rollout)
        self.assertIn("ContextualWisdomLab/.github#889", rollout)

    def test_canonical_docs_have_no_placeholders(self) -> None:
        """Canonical documents must not carry ambiguous unfinished markers."""

        placeholder = re.compile(r"\b(?:TBD|TODO|FIXME)\b")
        for relative_path in REQUIRED_DOCUMENTS:
            body = (AUTOMATION_DOCS / relative_path).read_text(encoding="utf-8")
            self.assertIsNone(placeholder.search(body), relative_path)


if __name__ == "__main__":
    unittest.main()
