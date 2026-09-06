"""No-heuristics contracts for Noema review evidence allocation.

These regressions deliberately distinguish protocol/security invariants from
model-evidence allocation.  A review caller may validate exact Git locations
and the declared JSON shape, but it must not sample PR evidence by hand-picked
character/file/body caps, infer review effort from a filename, or suppress
model findings with a fixed display slice.  Evidence completeness is defined
by set coverage of the exact changed paths supplied by Git/GitHub; when the
full evidence cannot be served, the model/gateway path must fail closed rather
than silently sample it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import noema_review_gate as noema


_SOURCE = Path("scripts/ci/noema_review_gate.py")


def _two_path_diff() -> str:
    """Return a minimal unified diff with exact changed locations in two paths."""
    return (
        "diff --git a/src/a.py b/src/a.py\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -1 +1 @@\n"
        "-old_a\n"
        "+new_a\n"
        "diff --git a/docs/b.md b/docs/b.md\n"
        "--- a/docs/b.md\n"
        "+++ b/docs/b.md\n"
        "@@ -1 +1 @@\n"
        "-old_b\n"
        "+new_b\n"
    )


def _probe(path: str, line: int = 1) -> dict[str, object]:
    """Build one syntactically valid falsified probe at an exact changed line."""
    return {
        "path": path,
        "line": line,
        "side": "RIGHT",
        "hypothesis": f"regression in {path}",
        "attack_or_counterexample": f"exercise changed behavior in {path}",
        "evidence": f"exact changed-line evidence for {path}",
        "outcome": "falsified",
    }


def _reviewed(path: str, line: int = 1) -> dict[str, object]:
    """Build one syntactically valid changed-line analysis."""
    return {
        "path": path,
        "line": line,
        "side": "RIGHT",
        "analysis": f"reviewed exact changed line in {path}",
    }


def _approve(paths: tuple[str, ...]) -> dict[str, object]:
    """Build an approval whose evidence covers exactly ``paths``."""
    return {
        "decision": "approve",
        "summary": "All exact changed paths have explicit review evidence.",
        "reviewed_lines": [_reviewed(path) for path in paths],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Residual risk is limited to evidence outside this exact PR snapshot.",
            "probes": [_probe(path) for path in paths],
        },
        "findings": [],
    }


def test_source_has_no_caller_authored_evidence_sampling_or_name_based_effort() -> None:
    """Keep PR evidence allocation out of hand-authored constants and filename rules."""
    source = _SOURCE.read_text(encoding="utf-8")
    forbidden = (
        "MAX_DIFF_CHARS",
        "MAX_CONTEXT_FILES",
        "MAX_FILE_CONTEXT_CHARS",
        "MAX_REVIEW_CONTEXT_CHARS",
        "MAX_THREAD_BODY_CHARS",
        "changed_file_is_material",
        "_required_probe_count",
        "[:20]",
    )
    assert not [token for token in forbidden if token in source]


def test_fetch_diff_preserves_the_complete_git_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Noema forwards the complete immutable PR diff instead of caller-side sampling."""
    diff = _two_path_diff() + "+" + ("evidence" * 1000) + "\n"
    monkeypatch.setattr(noema, "run", lambda *_args, **_kwargs: diff)

    observed, truncated = noema.fetch_diff("owner/repo", 1)

    assert observed == diff
    assert truncated is False


def test_changed_file_context_preserves_every_supplied_path_and_full_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changed-file context is complete; unavailable capacity must fail elsewhere."""
    changed = [("src/a.py", "modified"), ("docs/b.md", "modified")]
    bodies = {
        "src/a.py": "alpha\n" + ("A" * 5000),
        "docs/b.md": "beta\n" + ("B" * 5000),
    }
    monkeypatch.setattr(
        noema,
        "fetch_file_content_at_ref",
        lambda _repo, path, _ref: bodies[path],
    )

    context = noema.changed_file_context(
        "owner/repo",
        1,
        "a" * 40,
        changed_files=changed,
    )

    for path, body in bodies.items():
        assert f"### {path}" in context
        assert body in context
    assert "omitted from context budget" not in context
    assert "[truncated " not in context


def test_formal_verdict_evidence_is_exact_changed_path_set_coverage() -> None:
    """Approval fails closed unless analyses and probes cover every changed path."""
    diff = _two_path_diff()
    changed_paths = ("src/a.py", "docs/b.md")

    noema.validate_substantive_verdict(_approve(changed_paths), diff, changed_paths)

    with pytest.raises(noema.NoemaModelOutputError, match="cover every changed path"):
        noema.validate_substantive_verdict(_approve(("src/a.py",)), diff, changed_paths)


def test_structured_output_schema_has_no_arbitrary_probe_count_floor() -> None:
    """Path coverage is validated logically; JSON Schema does not invent a count floor."""
    schema = noema._noema_verdict_json_schema()
    probes = schema["properties"]["adversarial_validation"]["properties"]["probes"]
    assert "minItems" not in probes


def test_json_preparse_depth_is_derived_from_declared_verdict_schema() -> None:
    """DoS protection derives from the accepted schema rather than a hand-picked depth."""
    source = _SOURCE.read_text(encoding="utf-8")
    assert "MAX_JSON_NESTING_DEPTH = 100" not in source
    assert noema._schema_max_container_depth(noema._noema_verdict_json_schema()) > 0
