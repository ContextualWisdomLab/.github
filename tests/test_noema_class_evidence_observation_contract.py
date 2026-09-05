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


def _assert_matches_declared_schema(value: object, schema: dict[str, object]) -> None:
    """Apply the strict-output JSON Schema subset used by the Noema contract."""
    variants = schema.get("anyOf")
    if isinstance(variants, list):
        failures: list[str] = []
        for variant in variants:
            try:
                _assert_matches_declared_schema(value, variant)
            except AssertionError as exc:
                failures.append(str(exc))
            else:
                return
        raise AssertionError("no anyOf variant admitted the verdict: " + "; ".join(failures))

    expected_type = schema.get("type")
    allowed_types = expected_type if isinstance(expected_type, list) else [expected_type]
    if value is None:
        actual_type = "null"
    elif isinstance(value, dict):
        actual_type = "object"
    elif isinstance(value, list):
        actual_type = "array"
    elif type(value) is int:
        actual_type = "integer"
    elif isinstance(value, str):
        actual_type = "string"
    else:
        actual_type = type(value).__name__
    assert actual_type in allowed_types, f"expected {allowed_types}, got {actual_type}"

    if "enum" in schema:
        assert value in schema["enum"]
    if actual_type == "object":
        properties = schema.get("properties")
        assert isinstance(properties, dict)
        required = schema.get("required")
        assert isinstance(required, list)
        assert set(required) == set(properties), "strict objects require every property"
        assert set(value) == set(properties), "required/additional properties diverged"
        for key, child_schema in properties.items():
            _assert_matches_declared_schema(value[key], child_schema)
    elif actual_type == "array":
        assert len(value) >= int(schema.get("minItems", 0))
        for item in value:
            _assert_matches_declared_schema(item, schema["items"])


def _assert_strict_object_contract(schema: dict[str, object]) -> None:
    """Require every nested object variant to use the strict SDK shape."""
    variants = schema.get("anyOf")
    if isinstance(variants, list):
        for variant in variants:
            _assert_strict_object_contract(variant)
        return
    schema_type = schema.get("type")
    allowed_types = schema_type if isinstance(schema_type, list) else [schema_type]
    if "object" in allowed_types:
        properties = schema.get("properties")
        assert isinstance(properties, dict)
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", [])) == set(properties)
        for child_schema in properties.values():
            _assert_strict_object_contract(child_schema)
    if "array" in allowed_types:
        _assert_strict_object_contract(schema["items"])


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


def test_outbound_strict_schema_and_local_validator_admit_the_same_verdict() -> None:
    """The exact structured-output receipt cannot contradict local admission."""
    verdict = _verdict(observations=True, source_excerpt=True)
    schema = noema._noema_verdict_json_schema(required_probes=2)

    _assert_matches_declared_schema(verdict, schema)
    noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_every_outbound_probe_variant_is_strict_and_taxonomy_complete() -> None:
    """Nested unions remain SDK-compatible and cover the closed local taxonomy."""
    response_format = noema._noema_verdict_response_format(required_probes=2)
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["type"] == "object"
    _assert_strict_object_contract(schema)

    probe_variants = schema["properties"]["adversarial_validation"]["properties"]["probes"][
        "items"
    ]["anyOf"]
    assert {
        variant["properties"]["probe_kind"]["enum"][0]
        for variant in probe_variants
    } == noema.OBSERVED_REVIEW_PROBE_KINDS
    assert schema["properties"]["adversarial_validation"]["type"] == ["object", "null"]
    assert all(
        variant["properties"]["class_evidence"]["type"] == "object"
        for variant in probe_variants
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
    """A genuine marker-shaped source line remains exact review evidence."""
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
        ("src/tool.py", 2, "LEFT"): "[overlong changed line content omitted]",
        ("src/tool.py", 2, "RIGHT"): "[overlong changed line content omitted]",
        ("src/tool.py", 3, "LEFT"): "old",
        ("src/tool.py", 3, "RIGHT"): "new",
    }
    assert noema.changed_diff_locations(diff) == set(noema.changed_diff_line_texts(diff))


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


def test_whitespace_only_changed_source_uses_explicit_blank_marker() -> None:
    """Whitespace-only source cannot satisfy evidence through incidental prose spaces."""
    spaces = "   "
    diff = f"""diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+{spaces}
"""
    verdict = _verdict(observations=True, source_excerpt=True)
    for probe in verdict["adversarial_validation"]["probes"]:
        for field, witness in probe["class_evidence"].items():
            witness["source_excerpt"] = spaces
            witness["observation"] = f"ordinary prose space is not evidence for {probe['probe_kind']}:{field}."

    with pytest.raises(noema.NoemaModelOutputError, match=r"must quote the exact source_excerpt"):
        noema.validate_substantive_verdict(verdict, diff, ["src/tool.py"])

    for probe in verdict["adversarial_validation"]["probes"]:
        for field, witness in probe["class_evidence"].items():
            witness["observation"] = f"<blank> is exact source evidence for {probe['probe_kind']}:{field}."
    noema.validate_substantive_verdict(verdict, diff, ["src/tool.py"])


def test_literal_omission_marker_source_remains_reviewable() -> None:
    """Literal source text must not alias synthetic prompt-truncation metadata."""
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
    noema.validate_substantive_verdict(verdict, diff, ["src/tool.py"])


def test_overlong_class_observation_is_rejected_before_semantic_admission() -> None:
    """Bounded review evidence refuses oversized witness prose without weakening source checks."""
    verdict = _verdict(observations=True, source_excerpt=True)
    witness = verdict["adversarial_validation"]["probes"][0]["class_evidence"]["mutation_attempt"]
    witness["observation"] = "x" * (noema.MAX_THREAD_BODY_CHARS + 1)
    with pytest.raises(noema.NoemaModelOutputError, match="exceeds"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])
