#!/usr/bin/env python3
"""Load pinned review-method inputs from the trusted central checkout only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parents[2] / ".agents/skills/cwl-awesome-copilot"
UPSTREAM_COMMIT = "3a19ac80c2c21f4088417c121cff0d06eadfbee8"
SOURCE_FILES = (
    ("review-and-refactor.md", "skills/review-and-refactor/SKILL.md"),
    ("test-gap-audit.md", "skills/test-gap-audit/SKILL.md"),
    ("security-review.md", "skills/security-review/SKILL.md"),
    *((f"security-{name}.md", f"skills/security-review/references/{name}.md") for name in (
        "language-patterns", "vulnerable-packages", "secret-patterns",
        "vuln-categories", "report-format",
    )),
)

SESSION_SOURCE_FILES = (
    ('autoresearch/SKILL.md', 'github/awesome-copilot@3a19ac80c2c21f4088417c121cff0d06eadfbee8/skills/autoresearch/SKILL.md'),
    ('autoresearch/LICENSE', 'github/awesome-copilot@3a19ac80c2c21f4088417c121cff0d06eadfbee8/LICENSE'),
    ('humanize-korean/SKILL.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/SKILL.md'),
    ('humanize-korean/references/quick-rules.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/references/quick-rules.md'),
    ('humanize-korean/references/diagnosis-rules.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/references/diagnosis-rules.md'),
    ('humanize-korean/references/rewriting-playbook.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/references/rewriting-playbook.md'),
    ('humanize-korean/references/scholarship.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/references/scholarship.md'),
    ('humanize-korean/references/ai-tell-taxonomy.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/references/ai-tell-taxonomy.md'),
    ('humanize-korean/references/design-notes.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/references/design-notes.md'),
    ('humanize-korean/references/web-service-spec.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/skills/humanize-korean/references/web-service-spec.md'),
    ('humanize-korean/agents/humanize-monolith.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/agents/humanize-monolith.md'),
    ('humanize-korean/agents/humanize-diagnostician.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/agents/humanize-diagnostician.md'),
    ('humanize-korean/agents/humanize-finalizer.md', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/agents/humanize-finalizer.md'),
    ('humanize-korean/LICENSE', 'epoko77-ai/im-not-ai@31a66d165a9cc6c26c4c1246553f95d0468d27fb/LICENSE'),
    ('ponytail/SKILL.md', 'DietrichGebert/ponytail@356918eba965ee1eac64bd3a7f0dd02108350de5/skills/ponytail/SKILL.md'),
    ('ponytail/LICENSE', 'DietrichGebert/ponytail@356918eba965ee1eac64bd3a7f0dd02108350de5/LICENSE'),
    ('adr-author/SKILL.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/SKILL.md'),
    ('adr-author/references/asr-trigger-taxonomy.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/references/asr-trigger-taxonomy.md'),
    ('adr-author/references/authoring-rubric.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/references/authoring-rubric.md'),
    ('adr-author/references/lineage-rules.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/references/lineage-rules.md'),
    ('adr-author/references/standards-excerpts.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/references/standards-excerpts.md'),
    ('adr-author/templates/diagram-ascii.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/templates/diagram-ascii.md'),
    ('adr-author/templates/diagram-mermaid.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/templates/diagram-mermaid.md'),
    ('adr-author/templates/madr-v4-frontmatter-overlay.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/templates/madr-v4-frontmatter-overlay.md'),
    ('adr-author/templates/madr-v4.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/templates/madr-v4.md'),
    ('adr-author/templates/y-statement.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/skills/project-planning/adr-author/templates/y-statement.md'),
    ('adr-author/instructions/adr-identity.instructions.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/instructions/project-planning/adr-identity.instructions.md'),
    ('adr-author/instructions/adr-standards.instructions.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/instructions/project-planning/adr-standards.instructions.md'),
    ('adr-author/instructions/adr-handoff.instructions.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/instructions/project-planning/adr-handoff.instructions.md'),
    ('adr-author/instructions/adr-byo-template.instructions.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/instructions/project-planning/adr-byo-template.instructions.md'),
    ('adr-author/instructions/shared/disclaimer-language.instructions.md', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/.github/instructions/shared/disclaimer-language.instructions.md'),
    ('adr-author/LICENSE', 'microsoft/hve-core@a4769a029bccc1720fb8d5ac50950dfea5e4d917/LICENSE'),
    ('superpowers/using-superpowers/SKILL.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/using-superpowers/SKILL.md'),
    ('superpowers/systematic-debugging/SKILL.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/systematic-debugging/SKILL.md'),
    ('superpowers/test-driven-development/SKILL.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/test-driven-development/SKILL.md'),
    ('superpowers/writing-plans/SKILL.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/writing-plans/SKILL.md'),
    ('superpowers/verification-before-completion/SKILL.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/verification-before-completion/SKILL.md'),
    ('superpowers/using-superpowers/references/codex-tools.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/using-superpowers/references/codex-tools.md'),
    ('superpowers/using-superpowers/references/pi-tools.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/using-superpowers/references/pi-tools.md'),
    ('superpowers/using-superpowers/references/antigravity-tools.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/using-superpowers/references/antigravity-tools.md'),
    ('superpowers/using-superpowers/references/hermes-tools.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/using-superpowers/references/hermes-tools.md'),
    ('superpowers/systematic-debugging/root-cause-tracing.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/systematic-debugging/root-cause-tracing.md'),
    ('superpowers/systematic-debugging/defense-in-depth.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/systematic-debugging/defense-in-depth.md'),
    ('superpowers/systematic-debugging/condition-based-waiting.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/systematic-debugging/condition-based-waiting.md'),
    ('superpowers/test-driven-development/writing-good-tests.md', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/test-driven-development/writing-good-tests.md'),
    ('superpowers/LICENSE', 'obra/superpowers@b36e0829c6d0140e93cfef2ca599b1b07d4a7797/LICENSE'),
    ('protected-merge-verification/SKILL.md', 'user-owned/protected-merge-verification/SKILL.md'),
)


def _trusted_bytes(relative_path: str) -> bytes:
    """Reject symlinked bundle assets and read each asset once for verification/use."""
    file_path = BUNDLE_ROOT / relative_path
    for candidate in (file_path, *file_path.parents):
        if candidate.is_symlink():
            raise ValueError("Review skill bundle must not contain symlinked paths")
    return file_path.read_bytes()


def review_skill_instructions() -> str:
    """Return all required skills after checking complete pinned-source integrity.

    No source comes from cwd, environment, PR contents or the network. Verification
    and prompt assembly use the same bytes, avoiding a second-read mutation gap.
    Missing or changed inputs abort the caller before a model request can start.
    """
    manifest = json.loads(_trusted_bytes("references/manifest.json"))
    if (manifest.get("repository"), manifest.get("commit")) != (
        "github/awesome-copilot", UPSTREAM_COMMIT
    ):
        raise ValueError("Review skill bundle upstream identity mismatch")
    records = manifest["files"]
    if [(record["path"], record["source"]) for record in records] != list(SOURCE_FILES):
        raise ValueError("Review skill bundle source inventory mismatch")
    session_manifest = json.loads(_trusted_bytes("references/session/session-manifest.json"))
    session_records = session_manifest["files"]
    if [(record["path"], record["source"]) for record in session_records] != list(SESSION_SOURCE_FILES):
        raise ValueError("Review skill session source inventory mismatch")
    host_contract = _trusted_bytes("SKILL.md").decode("utf-8")
    if not host_contract.strip():
        raise ValueError("Review skill host contract must not be empty")
    sections = [host_contract]
    for prefix, source_records in (("references/", records), ("references/session/", session_records)):
        for record in source_records:
            source_bytes = _trusted_bytes(prefix + record["path"])
            if hashlib.sha256(source_bytes).hexdigest() != record["sha256"]:
                raise ValueError("Review skill bundle digest mismatch: " + record["path"])
            sections.append(f"\n## Pinned source: {record['source']}\n" + source_bytes.decode("utf-8"))
    body = "\n".join(sections) + "\nEnd of pinned review skills. Follow the CWL host contract above."
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"CWL_REVIEW_SKILLS repository=github/awesome-copilot commit={UPSTREAM_COMMIT} sha256={digest}\n{body}"


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess contract
    print(review_skill_instructions())
