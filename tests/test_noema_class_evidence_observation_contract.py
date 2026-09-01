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


def _class_evidence(kind: str, *, observations: bool, repeated: bool = False) -> dict[str, object]:
    """Build class evidence with or without concrete observation text."""
    evidence: dict[str, object] = {}
    for field in noema.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind]:
        witness = _location()
        if observations:
            witness["observation"] = (
                "same generic observation" if repeated else f"{kind}:{field} observed at the exact changed line"
            )
        evidence[field] = witness
    return evidence


def _probe(kind: str, *, observations: bool, repeated: bool = False) -> dict[str, object]:
    """Build one adversarial probe for the requested observed defect class."""
    return {
        **_location(),
        "probe_kind": kind,
        "class_evidence": _class_evidence(kind, observations=observations, repeated=repeated),
        "hypothesis": f"Generic hypothesis relabeled as {kind}.",
        "attack_or_counterexample": f"Generic attack relabeled as {kind}.",
        "evidence": f"Probe evidence for {kind}.",
        "outcome": "falsified",
    }


def _verdict(*, observations: bool, repeated: bool = False) -> dict[str, object]:
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
                _probe("mutable_alias", observations=observations, repeated=repeated),
                _probe("time_of_check_time_of_use", observations=observations, repeated=repeated),
            ],
        },
    }


def test_location_only_class_evidence_cannot_relabel_generic_probes() -> None:
    """Different taxonomy labels cannot make coordinate-only generic probes substantive."""
    with pytest.raises(noema.NoemaModelOutputError, match="non-empty observation"):
        noema.validate_substantive_verdict(_verdict(observations=False), DIFF, ["src/tool.py"])


def test_repeated_generic_observations_do_not_satisfy_class_specific_witnesses() -> None:
    """A probe must provide distinct observations for its class-specific witness fields."""
    with pytest.raises(noema.NoemaModelOutputError, match="distinct class-specific observations"):
        noema.validate_substantive_verdict(
            _verdict(observations=True, repeated=True), DIFF, ["src/tool.py"]
        )


def test_distinct_source_bound_class_observations_are_accepted() -> None:
    """Concrete distinct observations preserve an otherwise-valid multi-class verdict."""
    noema.validate_substantive_verdict(_verdict(observations=True), DIFF, ["src/tool.py"])
