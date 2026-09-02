"""Regression tests for class-specific Noema probe observation evidence."""

from __future__ import annotations

import pytest

from scripts.ci import noema_review_gate as noema


DIFF = """diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+new = 1
"""


def _location() -> dict[str, object]:
    """Return the single exact changed-side location used by this fixture."""
    return {"path": "src/tool.py", "line": 1, "side": "RIGHT"}


def _class_evidence(
    kind: str,
    *,
    observations: bool,
    repeated: bool = False,
    source_excerpt: bool = False,
    generic_but_different: bool = False,
) -> dict[str, object]:
    """Build class evidence spanning the intentionally weak and hardened schemas."""
    evidence: dict[str, object] = {}
    for index, field in enumerate(noema.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind], start=1):
        witness = _location()
        witness["claim_role"] = noema.OBSERVED_REVIEW_PROBE_CLAIM_ROLES[kind][field]
        if observations:
            if repeated:
                witness["observation"] = "new = 1 is the same repeated source observation."
            elif generic_but_different:
                witness["observation"] = (
                    f"Generic {field.replace('_', ' ')} concern appears in this area."
                )
            else:
                witness["observation"] = (
                    f"new = 1 is exact source evidence for structured witness {index}: {field}."
                )
        if source_excerpt:
            witness["source_excerpt"] = "new = 1"
        evidence[field] = witness
    return evidence


def _probe(
    kind: str,
    *,
    observations: bool,
    repeated: bool = False,
    source_excerpt: bool = False,
    generic_but_different: bool = False,
) -> dict[str, object]:
    """Build one adversarial probe for the requested observed defect class."""
    return {
        **_location(),
        "probe_kind": kind,
        "class_evidence": _class_evidence(
            kind,
            observations=observations,
            repeated=repeated,
            source_excerpt=source_excerpt,
            generic_but_different=generic_but_different,
        ),
        "hypothesis": f"Generic hypothesis relabeled as {kind}.",
        "attack_or_counterexample": f"Generic attack relabeled as {kind}.",
        "evidence": f"Probe evidence for {kind}.",
        "outcome": "falsified",
    }


def _verdict(
    *,
    observations: bool,
    repeated: bool = False,
    source_excerpt: bool = False,
    generic_but_different: bool = False,
) -> dict[str, object]:
    """Build an otherwise-valid approval verdict with two distinct class labels."""
    return {
        "decision": "approve",
        "summary": "Two observed defect classes were attacked.",
        "findings": [],
        "reviewed_lines": [{**_location(), "analysis": "Reviewed exact changed line."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Unit fixture does not exercise an external runtime.",
            "probes": [
                _probe(
                    "mutable_alias",
                    observations=observations,
                    repeated=repeated,
                    source_excerpt=source_excerpt,
                    generic_but_different=generic_but_different,
                ),
                _probe(
                    "time_of_check_time_of_use",
                    observations=observations,
                    repeated=repeated,
                    source_excerpt=source_excerpt,
                    generic_but_different=generic_but_different,
                ),
            ],
        },
    }


def test_location_only_class_evidence_cannot_relabel_generic_probes() -> None:
    """Different taxonomy labels cannot make coordinate-only generic probes substantive."""
    with pytest.raises(noema.NoemaModelOutputError, match="non-empty observation"):
        noema.validate_substantive_verdict(_verdict(observations=False), DIFF, ["src/tool.py"])


def test_class_evidence_requires_exact_observed_field_set() -> None:
    """A defect-class label cannot omit one of its schema-defined witness roles."""
    verdict = _verdict(observations=True, source_excerpt=True)
    verdict["adversarial_validation"]["probes"][0]["class_evidence"].pop("mutation_attempt")

    with pytest.raises(noema.NoemaModelOutputError, match="must contain exactly"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_empty_class_observation_is_rejected() -> None:
    """Exact source coordinates and excerpts do not substitute for an observation."""
    verdict = _verdict(observations=True, source_excerpt=True)
    verdict["adversarial_validation"]["probes"][0]["class_evidence"]["mutation_attempt"][
        "observation"
    ] = ""

    with pytest.raises(noema.NoemaModelOutputError, match="non-empty observation"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_repeated_generic_observations_do_not_satisfy_class_specific_witnesses() -> None:
    """A probe must provide distinct observations for its class-specific witness fields."""
    with pytest.raises(noema.NoemaModelOutputError, match="distinct class-specific observations"):
        noema.validate_substantive_verdict(
            _verdict(observations=True, repeated=True, source_excerpt=True),
            DIFF,
            ["src/tool.py"],
        )


def test_differently_worded_generic_observations_without_source_signal_are_rejected() -> None:
    """Unique prose labels are not evidence unless they name concrete changed-source content."""
    with pytest.raises(noema.NoemaModelOutputError, match="quote the exact source_excerpt"):
        noema.validate_substantive_verdict(
            _verdict(
                observations=True,
                source_excerpt=True,
                generic_but_different=True,
            ),
            DIFF,
            ["src/tool.py"],
        )


def test_fabricated_source_excerpt_is_rejected() -> None:
    """A model cannot attach a plausible observation to source text absent from the cited line."""
    verdict = _verdict(observations=True, source_excerpt=True)
    verdict["adversarial_validation"]["probes"][0]["class_evidence"]["mutation_attempt"][
        "source_excerpt"
    ] = "fabricated = 2"

    with pytest.raises(noema.NoemaModelOutputError, match="exact changed-line source_excerpt"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_invented_claim_role_cannot_replace_class_specific_evidence() -> None:
    """Free-form labels cannot substitute for the schema's exact class-and-field role."""
    verdict = _verdict(observations=True, source_excerpt=True)
    verdict["adversarial_validation"]["probes"][0]["class_evidence"]["mutation_attempt"][
        "claim_role"
    ] = "banana"

    with pytest.raises(noema.NoemaModelOutputError, match="claim_role must be"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_distinct_source_bound_class_observations_are_accepted() -> None:
    """Concrete source-backed observations preserve an otherwise-valid multi-class verdict."""
    noema.validate_substantive_verdict(
        _verdict(observations=True, source_excerpt=True),
        DIFF,
        ["src/tool.py"],
    )


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"path": "", "line": 1, "side": "RIGHT"}, "canonical changed-side path"),
        ({"path": "src/tool.py", "line": True, "side": "RIGHT"}, "canonical positive integer line"),
        ({"path": "src/tool.py", "line": 0, "side": "RIGHT"}, "canonical positive integer line"),
        ({"path": "src/tool.py", "line": 1, "side": "right"}, "canonical LEFT/RIGHT side"),
    ],
)
def test_canonical_changed_location_rejects_noncanonical_coordinates(
    record: dict[str, object], message: str
) -> None:
    """Canonical source coordinates reject empty paths, bool/int aliases, and invalid sides."""
    with pytest.raises(noema.NoemaModelOutputError, match=message):
        noema._canonical_changed_location(record, "fixture")


def test_changed_diff_line_texts_covers_context_markers_and_no_newline_marker() -> None:
    """Exact-source extraction skips omission markers while preserving neighboring changed text."""
    diff = """diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1,3 +1,3 @@
 context
-[overlong changed line content omitted]
+[overlong changed line content omitted]
-old
+new
\\ No newline at end of file
"""
    assert noema.changed_diff_line_texts(diff) == {
        ("src/tool.py", 3, "LEFT"): "old",
        ("src/tool.py", 3, "RIGHT"): "new",
    }


def test_changed_diff_line_texts_fails_closed_when_hunk_paths_are_missing() -> None:
    """A hunk without its canonical file headers cannot manufacture source evidence."""
    assert noema.changed_diff_line_texts("@@ -1 +1 @@\n+new\n") == {}
    assert noema.changed_diff_line_texts("@@ -1 +1 @@\n-old\n") == {}


def test_changed_diff_line_texts_handles_dev_null_addition() -> None:
    """New files may have an empty old path while their RIGHT-side source remains exact."""
    diff = """diff --git a/new.py b/new.py
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+value = 1
"""
    assert noema.changed_diff_line_texts(diff) == {("new.py", 1, "RIGHT"): "value = 1"}


def test_blank_changed_source_uses_explicit_blank_marker() -> None:
    """A blank changed line remains admissible through exact equality and the explicit marker."""
    diff = """diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+
"""
    verdict = _verdict(observations=True, source_excerpt=True)
    for probe in verdict["adversarial_validation"]["probes"]:
        for field, witness in probe["class_evidence"].items():
            witness["source_excerpt"] = ""
            witness["observation"] = f"<blank> is exact source evidence for {probe['probe_kind']}:{field}."
    noema.validate_substantive_verdict(verdict, diff, ["src/tool.py"])


def test_overlong_omission_marker_cannot_be_source_evidence() -> None:
    """A bounded-diff omission marker cannot be reintroduced as an exact source excerpt."""
    marker = "[overlong changed line content omitted]"
    diff = f"""diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+{marker}
"""
    verdict = _verdict(observations=True, source_excerpt=True)
    for probe in verdict["adversarial_validation"]["probes"]:
        for field, witness in probe["class_evidence"].items():
            witness["source_excerpt"] = marker
            witness["observation"] = f"{marker} is exact source evidence for {probe['probe_kind']}:{field}."
    with pytest.raises(noema.NoemaModelOutputError, match="exact changed-line source_excerpt"):
        noema.validate_substantive_verdict(verdict, diff, ["src/tool.py"])


def test_overlong_class_observation_is_rejected_before_semantic_admission() -> None:
    """Bounded review evidence refuses oversized witness prose without weakening source checks."""
    verdict = _verdict(observations=True, source_excerpt=True)
    witness = verdict["adversarial_validation"]["probes"][0]["class_evidence"]["mutation_attempt"]
    witness["observation"] = "x" * (noema.MAX_THREAD_BODY_CHARS + 1)
    with pytest.raises(noema.NoemaModelOutputError, match="exceeds"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])
