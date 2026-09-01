"""Regression corpus for observed Noema/OpenCode reviewer false-negative shapes."""

from __future__ import annotations

import pytest

from scripts.ci import noema_review_gate as noema
from scripts.ci import opencode_review_normalize_output as opencode


PROBE_FIELDS = {
    "mutable_alias": ("alias_origin", "mutation_attempt", "post_validation_observation"),
    "time_of_check_time_of_use": ("check_observation", "intervening_change", "use_observation"),
    "execution_identity": ("incoming_identity", "retained_identity", "mismatch_guard"),
    "coercion_boundary": ("raw_value", "conversion_path", "canonicality_guard"),
    "test_oracle": ("assertion_under_test", "negative_control", "distinguishing_observation"),
    "cross_contract": ("first_contract", "second_contract", "contradiction_or_alignment"),
    "authority_boundary": ("component_authority", "external_authority", "enforcement_boundary"),
    "dependency_context": ("dependency", "omitted_or_included_context", "causal_effect"),
    "state_machine_race": ("initial_state", "event_order", "invariant_observation"),
}


def class_evidence(kind: str, *, path: str, line: int) -> dict[str, str]:
    """Build three distinct, field-tagged semantic observations for one probe class."""
    return {
        field: f"{field} observed a concrete {kind} result at {path}:{line}"
        for field in PROBE_FIELDS[kind]
    }


def evidence_with_witnesses(kind: str, *, path: str, line: int) -> tuple[dict[str, str], str]:
    """Return semantic witnesses and the parent evidence that binds them verbatim."""
    witnesses = class_evidence(kind, path=path, line=line)
    evidence = "; ".join(f"{field}={observation}" for field, observation in witnesses.items())
    return witnesses, evidence


def opencode_probe(kind: str, line: int):
    path = "scripts/ci/example.py"
    witnesses, evidence = evidence_with_witnesses(kind, path=path, line=line)
    return {
        "path": path,
        "line": line,
        "probe_kind": kind,
        "class_evidence": witnesses,
        "hypothesis": f"Observed {kind} failure shape can violate the changed invariant.",
        "attack_or_counterexample": f"Exercise the {kind} counterexample at line {line}.",
        "evidence": evidence,
        "outcome": "falsified",
    }


def patch_opencode_probe_dependencies(monkeypatch):
    monkeypatch.setenv("OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    monkeypatch.setattr(opencode, "current_changed_files", lambda: ("scripts/ci/example.py",))
    monkeypatch.setattr(opencode, "required_adversarial_probe_count", lambda: 2)
    monkeypatch.setattr(opencode, "adversarial_probe_location_error", lambda _path, _line: "")
    monkeypatch.setattr(opencode, "adversarial_probe_source_receipt_error", lambda _evidence, _path, _line: "")
    monkeypatch.setattr(opencode, "adversarial_evidence_rejection_reason", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(opencode, "unreceipted_runtime_tool_claim", lambda _evidence: "")


def test_opencode_requires_observed_probe_kind_and_class_witness(monkeypatch):
    """Generic prose probes cannot satisfy the durable observed-defect corpus."""
    patch_opencode_probe_dependencies(monkeypatch)
    first = opencode_probe("mutable_alias", 7)
    second = opencode_probe("time_of_check_time_of_use", 8)
    first.pop("probe_kind")
    first.pop("class_evidence")
    error = opencode.adversarial_validation_error(
        {
            "status": "passed",
            "probes": [first, second],
            "residual_risk": "Bounded review evidence cannot model every runtime interleaving.",
        },
        result="APPROVE",
        findings=[],
    )
    assert "requires probe_kind from the observed defect taxonomy" in error


def test_opencode_requires_distinct_observed_classes_for_material_changes(monkeypatch):
    """Two differently worded probes from one class do not prove attack diversity."""
    patch_opencode_probe_dependencies(monkeypatch)
    error = opencode.adversarial_validation_error(
        {
            "status": "passed",
            "probes": [opencode_probe("mutable_alias", 7), opencode_probe("mutable_alias", 8)],
            "residual_risk": "Bounded review evidence cannot model every runtime interleaving.",
        },
        result="APPROVE",
        findings=[],
    )
    assert "requires at least 2 distinct probe_kind values" in error


def test_opencode_rejects_coordinate_only_class_evidence(monkeypatch):
    """Source references alone cannot masquerade as class-specific observations."""
    patch_opencode_probe_dependencies(monkeypatch)
    bad = opencode_probe("test_oracle", 7)
    bad["class_evidence"] = {
        field: {"path": bad["path"], "line": bad["line"]}
        for field in PROBE_FIELDS["test_oracle"]
    }
    error = opencode.adversarial_validation_error(
        {
            "status": "passed",
            "probes": [bad, opencode_probe("cross_contract", 8)],
            "residual_risk": "Bounded review evidence cannot model every runtime interleaving.",
        },
        result="APPROVE",
        findings=[],
    )
    assert "class_evidence.assertion_under_test requires a concrete observation" in error


def test_opencode_rejects_witness_not_bound_into_parent_evidence(monkeypatch):
    """A relabeled witness must be present in the independently validated evidence text."""
    patch_opencode_probe_dependencies(monkeypatch)
    bad = opencode_probe("authority_boundary", 7)
    bad["class_evidence"]["external_authority"] = (
        "external_authority observed a different host-owned decision at scripts/ci/example.py:7"
    )
    error = opencode.adversarial_validation_error(
        {
            "status": "passed",
            "probes": [bad, opencode_probe("dependency_context", 8)],
            "residual_risk": "Bounded review evidence cannot model every runtime interleaving.",
        },
        result="APPROVE",
        findings=[],
    )
    assert "class_evidence.external_authority must be quoted in probe evidence" in error


def test_opencode_rejects_vacuous_class_observation(monkeypatch):
    """A class field cannot use the same generic review conclusion as all witnesses."""
    patch_opencode_probe_dependencies(monkeypatch)
    bad = opencode_probe("coercion_boundary", 7)
    bad["class_evidence"]["raw_value"] = "works as expected"
    bad["evidence"] += "; raw_value=works as expected"
    error = opencode.adversarial_validation_error(
        {
            "status": "passed",
            "probes": [bad, opencode_probe("execution_identity", 8)],
            "residual_risk": "Bounded review evidence cannot model every runtime interleaving.",
        },
        result="APPROVE",
        findings=[],
    )
    assert "class_evidence.raw_value is vacuous" in error


def test_opencode_accepts_two_semantically_bound_observed_classes(monkeypatch):
    """Distinct observed classes with field-specific evidence remain publishable."""
    patch_opencode_probe_dependencies(monkeypatch)
    error = opencode.adversarial_validation_error(
        {
            "status": "passed",
            "probes": [
                opencode_probe("mutable_alias", 7),
                opencode_probe("time_of_check_time_of_use", 8),
            ],
            "residual_risk": "Bounded review evidence cannot model every runtime interleaving.",
        },
        result="APPROVE",
        findings=[],
    )
    assert error == ""


def noema_probe(kind: str, *, line: int, side: str = "RIGHT"):
    path = "example.py"
    witnesses, evidence = evidence_with_witnesses(kind, path=path, line=line)
    return {
        "path": path,
        "line": line,
        "side": side,
        "probe_kind": kind,
        "class_evidence": witnesses,
        "hypothesis": f"Observed {kind} failure shape can violate the changed invariant.",
        "attack_or_counterexample": f"Exercise the {kind} counterexample at line {line}.",
        "evidence": evidence,
        "outcome": "falsified",
    }


def noema_diff() -> str:
    return """diff --git a/example.py b/example.py
index 1111111..2222222 100644
--- a/example.py
+++ b/example.py
@@ -1,2 +1,2 @@
-old
+new
 context
@@ -7,1 +7,2 @@
-old-seven
+new-seven
+new-eight
"""


def noema_verdict(probes):
    return {
        "decision": "approve",
        "summary": "Source-bound observed failure classes were independently attacked.",
        "reviewed_lines": [
            {"path": "example.py", "line": 1, "side": "RIGHT", "analysis": "Changed value reviewed."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "External platform behavior remains outside this bounded diff.",
            "probes": probes,
        },
        "findings": [],
    }


def test_noema_requires_distinct_observed_classes_when_enabled(monkeypatch):
    """Noema production admission rejects two generic probes from one class."""
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "1")
    verdict = noema_verdict(
        [noema_probe("state_machine_race", line=7), noema_probe("state_machine_race", line=8)]
    )
    with pytest.raises(noema.NoemaModelOutputError, match="at least 2 distinct probe_kind values"):
        noema.validate_substantive_verdict(verdict, noema_diff(), ("example.py",))


def test_noema_rejects_missing_observed_probe_kind_when_enabled(monkeypatch):
    """Noema cannot publish material formal evidence with an unclassified probe."""
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "1")
    first = noema_probe("execution_identity", line=7)
    first.pop("probe_kind")
    first.pop("class_evidence")
    verdict = noema_verdict([first, noema_probe("authority_boundary", line=8)])
    with pytest.raises(noema.NoemaModelOutputError, match="requires probe_kind from the observed defect taxonomy"):
        noema.validate_substantive_verdict(verdict, noema_diff(), ("example.py",))


def test_noema_rejects_coordinate_only_class_evidence_when_enabled(monkeypatch):
    """Noema also rejects labels backed only by repeated source coordinates."""
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "1")
    first = noema_probe("cross_contract", line=7)
    first["class_evidence"] = {
        field: {"path": first["path"], "line": first["line"], "side": first["side"]}
        for field in PROBE_FIELDS["cross_contract"]
    }
    verdict = noema_verdict([first, noema_probe("test_oracle", line=8)])
    with pytest.raises(noema.NoemaModelOutputError, match="class_evidence.first_contract requires a concrete observation"):
        noema.validate_substantive_verdict(verdict, noema_diff(), ("example.py",))


def test_noema_rejects_boolean_changed_line_alias(monkeypatch):
    """JSON true cannot impersonate integer changed line 1 through Python equality."""
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "1")
    verdict = noema_verdict(
        [noema_probe("mutable_alias", line=7), noema_probe("execution_identity", line=8)]
    )
    verdict["reviewed_lines"][0]["line"] = True
    with pytest.raises(noema.NoemaModelOutputError, match="canonical positive integer line"):
        noema.validate_substantive_verdict(verdict, noema_diff(), ("example.py",))


def test_noema_accepts_two_semantically_bound_observed_classes(monkeypatch):
    """Noema accepts distinct classes only when semantic witnesses bind into evidence."""
    monkeypatch.setenv("NOEMA_REQUIRE_OBSERVED_PROBE_TAXONOMY", "1")
    verdict = noema_verdict(
        [noema_probe("mutable_alias", line=7), noema_probe("execution_identity", line=8)]
    )
    noema.validate_substantive_verdict(verdict, noema_diff(), ("example.py",))
