#!/usr/bin/env python3
"""Machine-check the canonical automation documentation graph."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_ROOT = ROOT / "docs" / "automation"
STATUS_VALUES = {
    "implemented_on_protected_main",
    "active_pr",
    "accepted_architecture",
    "planned",
    "research_only",
    "superseded",
    "out_of_scope",
}
REQUIRED_DOCS = (
    "README.md",
    "PRD.md",
    "TRD.md",
    "ARCHITECTURE.md",
    "DATA_MODEL.md",
    "UML.md",
    "SECURITY.md",
    "THREAT_MODEL.md",
    "TEST_STRATEGY.md",
    "OPERABILITY.md",
    "INCIDENT_RUNBOOK.md",
    "TRACEABILITY.md",
)
REQUIRED_ADRS = tuple(f"{number:04d}-" for number in range(1, 9))
WORKFLOW_REFERENCES = (
    ".github/workflows/opencode-review.yml",
    ".github/workflows/opencode-review-dispatch.yml",
    ".github/workflows/pr-review-merge-scheduler.yml",
    ".github/workflows/pr-auto-rebase.yml",
)


class AutomationDocumentationContract(unittest.TestCase):
    """Protect the code-current documentation graph from silent drift."""

    def test_required_documents_and_statuses(self) -> None:
        """Every canonical document exists and uses the controlled status vocabulary."""
        for relative_path in REQUIRED_DOCS:
            path = DOC_ROOT / relative_path
            self.assertTrue(path.is_file(), relative_path)
            text = path.read_text(encoding="utf-8")
            match = re.search(r"^Status: ([a-z_]+)$", text, re.MULTILINE)
            self.assertIsNotNone(match, relative_path)
            self.assertIn(match.group(1), STATUS_VALUES, relative_path)

    def test_indexes_cover_documents_and_adrs(self) -> None:
        """Indexes link every required document and detailed ADR."""
        readme = (DOC_ROOT / "README.md").read_text(encoding="utf-8")
        for relative_path in REQUIRED_DOCS[1:]:
            self.assertIn(f"]({relative_path})", readme, relative_path)

        adr_root = DOC_ROOT / "adr"
        index = (adr_root / "README.md").read_text(encoding="utf-8")
        adr_names = sorted(path.name for path in adr_root.glob("[0-9][0-9][0-9][0-9]-*.md"))
        for prefix in REQUIRED_ADRS:
            self.assertTrue(any(name.startswith(prefix) for name in adr_names), prefix)
        for name in adr_names:
            self.assertIn(f"]({name})", index, name)

    def test_diagrams_and_immutable_architecture_are_well_formed(self) -> None:
        """Markdown fences close and timeless architecture does not pin ephemeral SHAs."""
        full_sha = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")
        for relative_path in REQUIRED_DOCS:
            path = DOC_ROOT / relative_path
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("~~~") % 2, 0, relative_path)
            self.assertEqual(text.count("```") % 2, 0, relative_path)
            self.assertIsNone(full_sha.search(text), relative_path)
            for block in re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL):
                self.assertTrue(block.strip(), relative_path)

    def test_traceability_names_live_workflows(self) -> None:
        """Traceability maps the protected-main workflow surfaces that implement policy."""
        traceability = (DOC_ROOT / "TRACEABILITY.md").read_text(encoding="utf-8")
        for workflow in WORKFLOW_REFERENCES:
            self.assertTrue((ROOT / workflow).is_file(), workflow)
            self.assertIn(workflow, traceability, workflow)


if __name__ == "__main__":
    unittest.main()
