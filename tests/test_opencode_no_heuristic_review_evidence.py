"""No-heuristics contracts for OpenCode review-evidence admission.

The review model may be required to cite exact current-head evidence, but the
caller must not allocate review quality by filename class or by a hand-picked
number of probes.  Formal review evidence is complete when its exact changed
path universe is covered; the workflow may fail closed when that evidence is
unavailable, but it must not manufacture a smaller numerical substitute.
"""

from __future__ import annotations

from pathlib import Path


_PROMPTS = (
    Path("ci-review-prompt.md"),
    Path("scripts/ci/opencode_review_prompt_template.md"),
)


def test_opencode_prompts_have_no_name_based_probe_count_admission_rule() -> None:
    """Retire the filename/materiality-derived two-versus-one probe threshold."""
    forbidden = (
        "needs two falsified probes",
        "requires at least two falsified probes",
        "at least two falsified probes",
        "at least one for non-code",
        "at least one for non-code changes",
        "source, workflow, config, package, or test changes",
        "source, workflow, config, package, or test changes and at least one",
    )
    for path in _PROMPTS:
        text = path.read_text(encoding="utf-8")
        found = [phrase for phrase in forbidden if phrase in text]
        assert not found, f"{path}: unsupported probe-count admission remains: {found}"


def test_opencode_prompts_define_exact_changed_path_coverage() -> None:
    """Formal approval evidence uses deterministic set coverage of the PR delta."""
    required = (
        "every exact changed path",
        "exact changed-path set",
        "no filename, extension, or change-type classification",
    )
    for path in _PROMPTS:
        text = path.read_text(encoding="utf-8")
        for phrase in required:
            assert phrase in text, f"{path}: missing exact-evidence contract: {phrase}"


def test_opencode_prompts_fail_closed_when_complete_evidence_is_unavailable() -> None:
    """Missing complete evidence cannot be converted into an informal smaller quota."""
    for path in _PROMPTS:
        text = path.read_text(encoding="utf-8")
        assert "complete exact changed-path evidence is unavailable" in text
        assert "fail closed" in text
