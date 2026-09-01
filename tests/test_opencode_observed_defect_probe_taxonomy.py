"""Regression corpus for observed OpenCode reviewer false-negative shapes."""

from __future__ import annotations

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
    return {
        field: f"{field} observed a concrete {kind} result at {path}:{line}"
        for field in PROBE_FIELDS[kind]
    }


def probe(kind: str, line: int) -> dict[str, object]:
    path = "scripts/ci/example.py"
    witnesses = class_evidence(kind, path=path, line=line)
    evidence = "; ".join(f"{field}={observation}" for field, observation in witnesses.items())
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


def patch_dependencies(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_REQUIRE_OBSERVED_PROBE_TAXONOMY", "true")
    monkeypatch.setattr(opencode, "current_changed_files", lambda: ("scripts/ci/example.py",))
    monkeypatch.setattr(opencode, "required_adversarial_probe_count", lambda: 2)
    monkeypatch.setattr(opencode, "adversarial_probe_location_error", lambda _path, _line: "")
    monkeypatch.setattr(opencode, "adversarial_probe_source_receipt_error", lambda _evidence, _path, _line: "")
    monkeypatch.setattr(opencode, "adversarial_evidence_rejection_reason", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(opencode, "unreceipted_runtime_tool_claim", lambda _evidence: "")


def validation_error(probes: list[dict[str, object]]) -> str:
    return opencode.adversarial_validation_error(
        {
            "status": "passed",
            "probes": probes,
            "residual_risk": "Bounded current-head evidence cannot model every runtime interleaving.",
        },
        result="APPROVE",
        findings=[],
    )


def test_requires_observed_probe_kind_and_class_witness(monkeypatch):
    patch_dependencies(monkeypatch)
    first = probe("mutable_alias", 7)
    second = probe("time_of_check_time_of_use", 8)
    first.pop("probe_kind")
    first.pop("class_evidence")
    assert "requires probe_kind from the observed defect taxonomy" in validation_error([first, second])


def test_requires_distinct_observed_classes_for_material_changes(monkeypatch):
    patch_dependencies(monkeypatch)
    assert "requires at least 2 distinct probe_kind values" in validation_error(
        [probe("mutable_alias", 7), probe("mutable_alias", 8)]
    )


def test_rejects_coordinate_only_class_evidence(monkeypatch):
    patch_dependencies(monkeypatch)
    bad = probe("test_oracle", 7)
    bad["class_evidence"] = {
        field: {"path": bad["path"], "line": bad["line"]}
        for field in PROBE_FIELDS["test_oracle"]
    }
    assert "class_evidence.assertion_under_test requires a concrete observation" in validation_error(
        [bad, probe("cross_contract", 8)]
    )


def test_rejects_witness_not_bound_into_parent_evidence(monkeypatch):
    patch_dependencies(monkeypatch)
    bad = probe("authority_boundary", 7)
    bad["class_evidence"]["external_authority"] = (
        "external_authority observed a different host-owned decision at scripts/ci/example.py:7"
    )
    assert "class_evidence.external_authority must be quoted in probe evidence" in validation_error(
        [bad, probe("dependency_context", 8)]
    )


def test_rejects_vacuous_class_observation(monkeypatch):
    patch_dependencies(monkeypatch)
    bad = probe("coercion_boundary", 7)
    bad["class_evidence"]["raw_value"] = "works as expected"
    bad["evidence"] += "; raw_value=works as expected"
    assert "class_evidence.raw_value is vacuous" in validation_error(
        [bad, probe("execution_identity", 8)]
    )


def test_accepts_two_semantically_bound_observed_classes(monkeypatch):
    patch_dependencies(monkeypatch)
    assert validation_error(
        [probe("mutable_alias", 7), probe("time_of_check_time_of_use", 8)]
    ) == ""
