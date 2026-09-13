"""Regression contract for request-changes finding/probe binding.

A formal request-changes verdict is not structurally reviewable when findings and confirmed
adversarial probes are only parallel arrays. The response schema must make the relationship explicit
so the model and contextual-orchestrator repair pass can reason about the same contract that the local
validator enforces.
"""

from __future__ import annotations

import copy

import pytest

from scripts.ci import noema_review_gate as noema


def _material_diff() -> str:
    """Return a two-probe material Python diff with stable changed-side locations."""
    return """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
-old
+new
+other
"""


def _request_changes_verdict() -> dict[str, object]:
    """Return the smallest valid request-changes verdict for the binding contract."""
    return {
        "decision": "request_changes",
        "summary": "The first changed line violates the reviewed contract.",
        "reviewed_lines": [
            {
                "path": "app.py",
                "line": 1,
                "side": "RIGHT",
                "analysis": "The changed value needs a blocking correction.",
            }
        ],
        "adversarial_validation": {
            "status": "failed",
            "residual_risk": "The published finding remains until the change is corrected.",
            "probes": [
                {
                    "path": "app.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The first change breaks the contract.",
                    "attack_or_counterexample": "Exercise the changed branch directly.",
                    "evidence": "The counterexample confirms the blocking defect.",
                    "outcome": "confirmed",
                    "finding_index": 0,
                },
                {
                    "path": "app.py",
                    "line": 2,
                    "side": "RIGHT",
                    "hypothesis": "The second change introduces the same defect.",
                    "attack_or_counterexample": "Exercise the second changed line independently.",
                    "evidence": "The second hypothesis is falsified.",
                    "outcome": "falsified",
                    "finding_index": None,
                },
            ],
        },
        "findings": [
            {
                "severity": "high",
                "file": "app.py",
                "line": 1,
                "side": "RIGHT",
                "message": "Correct the blocking contract violation.",
            }
        ],
    }


def test_probe_schema_carries_explicit_published_finding_binding() -> None:
    """Every probe must expose a schema-declared finding binding coordinate."""
    schema = noema._noema_verdict_json_schema(required_probes=2)
    probe_schema = schema["properties"]["adversarial_validation"]["properties"]["probes"]["items"]

    assert "finding_index" in probe_schema["properties"]
    assert "finding_index" in probe_schema["required"]
    assert probe_schema["properties"]["finding_index"] == {
        "type": ["integer", "null"],
        "minimum": 0,
    }


def test_request_changes_prompt_explains_confirmed_probe_binding() -> None:
    """The model prompt must explain how the schema link is populated for each probe outcome."""
    source = noema.__loader__.get_source(noema.__name__)
    assert source is not None
    assert "confirmed probe must set finding_index" in source
    assert "falsified probe must set finding_index to null" in source


def test_validator_accepts_confirmed_probe_bound_to_same_location_finding() -> None:
    """A confirmed probe may bind only to the published finding at its exact location."""
    noema.validate_substantive_verdict(_request_changes_verdict(), _material_diff())


@pytest.mark.parametrize("binding", [None, True, "0", -1, 1])
def test_validator_rejects_invalid_confirmed_probe_binding(binding: object) -> None:
    """Confirmed probes fail closed on null, bool, non-int, negative, or out-of-range bindings."""
    verdict = _request_changes_verdict()
    verdict["adversarial_validation"]["probes"][0]["finding_index"] = binding  # type: ignore[index]

    with pytest.raises(RuntimeError, match="finding_index"):
        noema.validate_substantive_verdict(verdict, _material_diff())


def test_validator_rejects_missing_confirmed_probe_binding() -> None:
    """The deterministic backstop rejects a confirmed probe that omits the required binding."""
    verdict = _request_changes_verdict()
    del verdict["adversarial_validation"]["probes"][0]["finding_index"]  # type: ignore[index]

    with pytest.raises(RuntimeError, match="finding_index"):
        noema.validate_substantive_verdict(verdict, _material_diff())


def test_validator_rejects_confirmed_binding_to_different_finding_location() -> None:
    """The referenced finding must share the confirmed probe's exact changed-side location."""
    verdict = _request_changes_verdict()
    verdict["findings"][0]["line"] = 2  # type: ignore[index]

    with pytest.raises(RuntimeError, match="finding_index.*location"):
        noema.validate_substantive_verdict(verdict, _material_diff())


def test_validator_rejects_falsified_probe_with_finding_binding() -> None:
    """Falsified probes cannot claim ownership of a published blocking finding."""
    verdict = _request_changes_verdict()
    verdict["adversarial_validation"]["probes"][1]["finding_index"] = 0  # type: ignore[index]

    with pytest.raises(RuntimeError, match="falsified.*finding_index"):
        noema.validate_substantive_verdict(verdict, _material_diff())


def test_validator_rejects_falsified_probe_without_explicit_null_binding() -> None:
    """The local validator mirrors the schema requirement instead of treating omission as null."""
    verdict = _request_changes_verdict()
    del verdict["adversarial_validation"]["probes"][1]["finding_index"]  # type: ignore[index]

    with pytest.raises(RuntimeError, match="finding_index"):
        noema.validate_substantive_verdict(verdict, _material_diff())
