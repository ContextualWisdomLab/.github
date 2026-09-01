"""Regression contract for Noema probes derived from observed reviewer findings."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.ci import noema_review_gate as gate


DIFF = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1,2 +1,2 @@
-old = False
+candidate = source.value
 keep = True
"""

CLASS_EVIDENCE_FIELDS = {
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


def _class_evidence(probe_kind: str) -> dict[str, dict[str, object]]:
    """Bind every class-specific witness field to the exact changed probe line."""
    source_ref = {"path": "tool.py", "line": 1, "side": "RIGHT"}
    return {field: dict(source_ref) for field in CLASS_EVIDENCE_FIELDS[probe_kind]}


def _verdict(*, first_kind: Any, second_kind: Any) -> dict:
    """Build a material approval verdict with two exact-line adversarial probes."""
    probes = [
        {
            "path": "tool.py", "line": 1, "side": "RIGHT",
            "hypothesis": "A caller-owned alias cannot mutate admitted state after validation.",
            "attack_or_counterexample": "Mutate the original object after the reviewed assignment.",
            "evidence": "The returned state is detached from the caller-owned object.",
            "outcome": "falsified",
        },
        {
            "path": "tool.py", "line": 1, "side": "RIGHT",
            "hypothesis": "A signal for another execution cannot advance this execution.",
            "attack_or_counterexample": "Replay the same transition with a mismatched execution identity.",
            "evidence": "The transition rejects the mismatched identity before state mutation.",
            "outcome": "falsified",
        },
    ]
    for probe, probe_kind in zip(probes, (first_kind, second_kind), strict=True):
        if probe_kind is not None:
            probe["probe_kind"] = probe_kind
        if isinstance(probe_kind, str) and probe_kind in CLASS_EVIDENCE_FIELDS:
            probe["class_evidence"] = _class_evidence(probe_kind)
    return {
        "decision": "approve",
        "summary": "Reviewed the changed material line against observed defect classes.",
        "reviewed_lines": [
            {"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "Checked the assignment boundary."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "The bounded review cannot execute every downstream consumer.",
            "probes": probes,
        },
        "findings": [],
    }


def test_formal_material_verdict_rejects_unclassified_adversarial_probe() -> None:
    """A probe without an observed defect-class identity must fail closed."""
    with pytest.raises(RuntimeError, match="probe_kind"):
        gate.validate_substantive_verdict(
            _verdict(first_kind=None, second_kind="execution_identity"), DIFF, ["tool.py"]
        )


def test_formal_material_verdict_rejects_unknown_adversarial_probe_kind() -> None:
    """Free-form labels must not bypass the executable review taxonomy."""
    with pytest.raises(RuntimeError, match="probe_kind"):
        gate.validate_substantive_verdict(
            _verdict(first_kind="generic_correctness", second_kind="execution_identity"),
            DIFF,
            ["tool.py"],
        )


@pytest.mark.parametrize("bad_kind", [["mutable_alias"], {"kind": "mutable_alias"}])
def test_probe_kind_container_fails_closed_as_review_validation(bad_kind: Any) -> None:
    """Malformed unhashable model output must fail closed, never crash the review job."""
    with pytest.raises(RuntimeError, match="probe_kind"):
        gate.validate_substantive_verdict(
            _verdict(first_kind=bad_kind, second_kind="execution_identity"), DIFF, ["tool.py"]
        )


def test_arbitrary_distinct_labels_without_class_witnesses_do_not_satisfy_diversity() -> None:
    """Distinct labels alone cannot turn generic evidence into two observed defect classes."""
    verdict = _verdict(first_kind="mutable_alias", second_kind="execution_identity")
    verdict["adversarial_validation"]["probes"][0]["class_evidence"] = {
        "generic_observation": "The changed line exists."
    }
    with pytest.raises(RuntimeError, match="class_evidence"):
        gate.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


def test_material_verdict_requires_distinct_observed_probe_classes() -> None:
    """Two structurally valid probes of one class must not satisfy material diversity."""
    with pytest.raises(RuntimeError, match="distinct probe_kind"):
        gate.validate_substantive_verdict(
            _verdict(first_kind="mutable_alias", second_kind="mutable_alias"), DIFF, ["tool.py"]
        )


def test_formal_material_verdict_accepts_class_bound_observed_defect_probes() -> None:
    """Two observed classes with their exact witness schemas remain admissible."""
    gate.validate_substantive_verdict(
        _verdict(first_kind="mutable_alias", second_kind="execution_identity"), DIFF, ["tool.py"]
    )


def test_rendered_prompt_contains_every_class_specific_witness_schema(monkeypatch) -> None:
    """Exercise call_llm and inspect the actual rendered request, not bytecode constants."""
    captured: dict[str, Any] = {}
    verdict = _verdict(first_kind="mutable_alias", second_kind="execution_identity")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(verdict)}}]}
            ).encode("utf-8")

    class Opener:
        def open(self, request):
            captured["payload"] = json.loads(request.data)
            return Response()

    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://127.0.0.1:18080/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setattr(gate.urllib.request, "build_opener", lambda *_args: Opener())

    result = gate.call_llm(
        "owner/repo", 7, {"title": "probe contract", "headRefOid": "a" * 40},
        DIFF, False, "a" * 40, "bounded changed-file context", ["tool.py"],
    )
    assert result["decision"] == "approve"
    prompt_text = captured["payload"]["messages"][1]["content"]
    assert "bounded changed-file context" in prompt_text
    for probe_kind, fields in CLASS_EVIDENCE_FIELDS.items():
        assert probe_kind in prompt_text
        for field in fields:
            assert field in prompt_text
