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
    sections = [_trusted_bytes("SKILL.md").decode("utf-8")]
    for record in records:
        source_bytes = _trusted_bytes("references/" + record["path"])
        if hashlib.sha256(source_bytes).hexdigest() != record["sha256"]:
            raise ValueError("Review skill bundle digest mismatch: " + record["path"])
        sections.append(f"\n## Upstream source: {record['source']}\n" + source_bytes.decode("utf-8"))
    body = "\n".join(sections)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"CWL_REVIEW_SKILLS repository=github/awesome-copilot commit={UPSTREAM_COMMIT} sha256={digest}\n{body}"


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess contract
    print(review_skill_instructions())
