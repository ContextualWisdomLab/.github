"""Regression contract for Noema probes derived from observed reviewer findings."""

from __future__ import annotations

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


def _verdict(*, first_kind: str | None, second_kind: str | None) -> dict:
    """Build a material approval verdict with two exact-line adversarial probes."""
    probes = [
        {
            "path": "tool.py",
            "line": 1,
            "side": "RIGHT",
            "hypothesis": "A caller-owned alias cannot mutate admitted state after validation.",
            "attack_or_counterexample": "Mutate the original object after the reviewed assignment.",
            "evidence": "The returned state is detached from the caller-owned object.",
            "outcome": "falsified",
        },
        {
            "path": "tool.py",
            "line": 1,
            "side": "RIGHT",
            "hypothesis": "A signal for another execution cannot advance this execution.",
            "attack_or_counterexample": "Replay the same transition with a mismatched execution identity.",
            "evidence": "The transition rejects the mismatched identity before state mutation.",
            "outcome": "falsified",
        },
    ]
    if first_kind is not None:
        probes[0]["probe_kind"] = first_kind
    if second_kind is not None:
        probes[1]["probe_kind"] = second_kind
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
            _verdict(first_kind=None, second_kind="execution_identity"),
            DIFF,
            ["tool.py"],
        )


def test_formal_material_verdict_rejects_unknown_adversarial_probe_kind() -> None:
    """Free-form labels must not bypass the executable review taxonomy."""
    with pytest.raises(RuntimeError, match="probe_kind"):
        gate.validate_substantive_verdict(
            _verdict(first_kind="generic_correctness", second_kind="execution_identity"),
            DIFF,
            ["tool.py"],
        )


def test_formal_material_verdict_accepts_observed_defect_probe_kinds() -> None:
    """Observed mutable-alias and execution-identity attacks remain admissible."""
    gate.validate_substantive_verdict(
        _verdict(first_kind="mutable_alias", second_kind="execution_identity"),
        DIFF,
        ["tool.py"],
    )


def test_prompt_contract_names_observed_false_negative_classes() -> None:
    """The reviewer prompt must actively enumerate the regression-corpus classes."""
    source = gate.call_llm.__code__.co_consts
    prompt_text = "\n".join(value for value in source if isinstance(value, str))
    for probe_kind in (
        "mutable_alias",
        "time_of_check_time_of_use",
        "execution_identity",
        "coercion_boundary",
        "test_oracle",
        "cross_contract",
        "authority_boundary",
        "dependency_context",
        "state_machine_race",
    ):
        assert probe_kind in prompt_text
