"""Contracts for published dependency-review carryover evidence."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = REPOSITORY_ROOT / "CHANGELOG.md"
GAP_BASELINE_PATH = REPOSITORY_ROOT / "docs/product-technical-gap-baseline.md"
PUBLISHED_SECURITY_PARENT = "229027280e8bce6cc4f13e722b2b0c280a1ac17d"
PUBLISHED_RUNNER_PARENT = "cd2c3f9748e6bc50efd8bdfee9a385a74ec6e3ba"
MERGE_EVIDENCE_PATTERN = re.compile(
    r"ordinary (?:two-parent )?merge\s+`([0-9a-f]{40})`"
)


def _dependency_review_evidence(document_text: str, record_marker: str) -> str:
    """Return the bounded dependency-review evidence paragraph or table row."""
    if record_marker.startswith("Dependency Review"):
        section_start = document_text.index(f"### {record_marker}")
        section_end = document_text.find("\n### ", section_start + 4)
        evidence_section = document_text[
            section_start : section_end if section_end >= 0 else None
        ]
        assert "#2565" in evidence_section
        assert "ordinary" in evidence_section
        assert "merge" in evidence_section
        return evidence_section

    evidence_blocks = [
        block
        for block in document_text.split("\n\n")
        if record_marker in block
        and "#2565" in block
        and "ordinary" in block
        and "merge" in block
    ]
    assert len(evidence_blocks) == 1, (
        "#2565 must have one ordinary-merge evidence record"
    )
    return evidence_blocks[0]


def _published_merge_sha(evidence_text: str) -> str:
    """Extract the full published merge identifier from one evidence record."""
    match = MERGE_EVIDENCE_PATTERN.search(evidence_text)
    assert match is not None, "#2565 evidence must name a full ordinary-merge SHA"
    return match.group(1)


def _git_output(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one read-only Git evidence query from the repository root."""
    return subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_dependency_review_receipts_bind_published_two_parent_merge() -> None:
    """Both owner receipts must name the same reachable two-parent merge."""
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    baseline = GAP_BASELINE_PATH.read_text(encoding="utf-8")
    changelog_evidence = _dependency_review_evidence(
        changelog, "Dependency Review requires a completed authenticated comparison"
    )
    baseline_evidence = _dependency_review_evidence(
        baseline, "CONTROL-DEPENDENCY-REVIEW-TRANSPORT-EXIT-01"
    )

    changelog_sha = _published_merge_sha(changelog_evidence)
    baseline_sha = _published_merge_sha(baseline_evidence)
    assert changelog_sha == baseline_sha

    resolvable = _git_output("cat-file", "-e", f"{changelog_sha}^{{commit}}")
    assert resolvable.returncode == 0, (
        f"#2565 evidence {changelog_sha} is not a published commit"
    )

    ancestor = _git_output("merge-base", "--is-ancestor", changelog_sha, "HEAD")
    assert ancestor.returncode == 0, (
        f"#2565 evidence {changelog_sha} is not in current HEAD ancestry"
    )

    parents = _git_output("show", "-s", "--format=%P", changelog_sha)
    assert parents.returncode == 0
    assert parents.stdout.strip().split() == [
        PUBLISHED_RUNNER_PARENT,
        PUBLISHED_SECURITY_PARENT,
    ]


def test_dependency_review_receipts_bind_current_exact_tree_counts() -> None:
    """Both owner receipts must retain the exact merged-tree test counts."""
    changelog_evidence = _dependency_review_evidence(
        CHANGELOG_PATH.read_text(encoding="utf-8"),
        "Dependency Review requires a completed authenticated comparison",
    )
    baseline_evidence = _dependency_review_evidence(
        GAP_BASELINE_PATH.read_text(encoding="utf-8"),
        "CONTROL-DEPENDENCY-REVIEW-TRANSPORT-EXIT-01",
    )

    for evidence_text in (changelog_evidence, baseline_evidence):
        assert "53/53" in evidence_text
        assert "5,437 passed, 10 skipped, 40 subtests" in evidence_text
