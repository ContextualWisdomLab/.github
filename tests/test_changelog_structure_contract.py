"""Structural guardrails for the union-merged changelog."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
ATTRIBUTES = ROOT / ".gitattributes"


def test_changelog_uses_union_merge_driver() -> None:
    """Prepending independent release notes must not create pairwise conflicts."""
    assert "CHANGELOG.md merge=union" in ATTRIBUTES.read_text(encoding="utf-8")


def test_changelog_sections_are_nonempty_and_fences_are_balanced() -> None:
    """Union merging must not silently swallow a heading inside a code fence."""
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    headings = [index for index, line in enumerate(lines) if line.startswith("### ")]
    assert headings
    assert headings[0] == 0

    in_fence = False
    fence_count = 0
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            fence_count += 1
        if line.startswith("### "):
            assert not in_fence
    assert fence_count % 2 == 0

    for start, end in zip(headings, [*headings[1:], len(lines)]):
        body = [line for line in lines[start + 1 : end] if line.strip()]
        assert body, f"empty changelog section at line {start + 1}"
        assert re.match(r"^### .+", lines[start])
