"""Deterministic semantic admission for observed reviewer defect probes."""
from __future__ import annotations

import os
from typing import Any

OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS = {
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
OBSERVED_REVIEW_PROBE_KINDS = frozenset(OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS)
VACUOUS_OBSERVATIONS = frozenset({
    "works as expected", "looks correct", "seems correct", "appears correct",
    "no issue found", "no issues found", "safe", "valid", "passed", "falsified",
})


def observed_probe_taxonomy_required(env_name: str) -> bool:
    """Return whether the production caller enabled observed-defect admission."""
    return os.environ.get(env_name, "").strip().casefold() in {"1", "true", "yes", "on"}


def _normalized(value: str) -> str:
    return " ".join(value.split()).strip()


def observed_probe_class_evidence_error(probe: dict[str, Any], *, label: str) -> str:
    """Return why one probe lacks class-specific semantic observations."""
    kind = probe.get("probe_kind")
    if not isinstance(kind, str) or kind not in OBSERVED_REVIEW_PROBE_KINDS:
        return f"{label} requires probe_kind from the observed defect taxonomy"
    class_evidence = probe.get("class_evidence")
    if not isinstance(class_evidence, dict):
        return f"{label} class_evidence must be an object"
    expected = OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind]
    if set(class_evidence) != set(expected):
        return f"{label} class_evidence must contain exactly: {', '.join(expected)}"
    parent_evidence = str(probe.get("evidence") or "")
    normalized_parent = _normalized(parent_evidence)
    hypothesis = _normalized(str(probe.get("hypothesis") or "")).casefold()
    attack = _normalized(str(probe.get("attack_or_counterexample") or "")).casefold()
    seen: set[str] = set()
    for field in expected:
        raw = class_evidence.get(field)
        if not isinstance(raw, str):
            return f"{label} class_evidence.{field} requires a concrete observation"
        observation = _normalized(raw)
        folded = observation.casefold()
        if len(observation) < 16 or len(observation.split()) < 4:
            return f"{label} class_evidence.{field} is vacuous"
        if folded in VACUOUS_OBSERVATIONS or folded in {hypothesis, attack}:
            return f"{label} class_evidence.{field} is vacuous"
        if folded in seen:
            return f"{label} class_evidence observations must be distinct"
        seen.add(folded)
        witness = _normalized(f"{field}={observation}")
        if witness not in normalized_parent:
            return f"{label} class_evidence.{field} must be quoted in probe evidence"
    return ""
