"""Regression tests for source-bound Noema adversarial probe evidence."""

from __future__ import annotations

import pytest

from scripts.ci import noema_review_gate as gate


DIFF = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1,2 +1,2 @@
-old = source.value
+candidate = source.value
 keep = candidate
@@ -10,1 +10,1 @@
-old_guard = previous_id
+guard = current_id
"""


def _source_ref(line: int) -> dict[str, object]:
    return {"path": "tool.py", "line": line, "side": "RIGHT"}


def _verdict(first_evidence: dict, second_evidence: dict) -> dict:
    return {
        "decision": "approve",
        "summary": "Checked exact changed source against two independent defect hypotheses.",
        "reviewed_lines": [
            {"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "Checked alias admission."},
            {"path": "tool.py", "line": 10, "side": "RIGHT", "analysis": "Checked identity guard."},
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Unchanged downstream consumers remain outside this bounded diff.",
            "probes": [
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "probe_kind": "mutable_alias",
                    "class_evidence": first_evidence,
                    "hypothesis": "A caller-owned alias could retain mutation authority after admission.",
                    "attack_or_counterexample": "Mutate source.value after candidate is retained.",
                    "evidence": "The changed assignment identifies the alias boundary under review.",
                    "outcome": "falsified",
                },
                {
                    "path": "tool.py",
                    "line": 10,
                    "side": "RIGHT",
                    "probe_kind": "execution_identity",
                    "class_evidence": second_evidence,
                    "hypothesis": "A mismatched execution identity could pass the changed guard.",
                    "attack_or_counterexample": "Replay the transition using a predecessor execution id.",
                    "evidence": "The changed guard is the exact identity boundary under review.",
                    "outcome": "falsified",
                },
            ],
        },
        "findings": [],
    }


def test_generic_boilerplate_witnesses_do_not_authorize_probe_classes() -> None:
    """Correct field names plus arbitrary prose must not count as source-backed classes."""
    verdict = _verdict(
        {
            "alias_origin": "source-traced witness text",
            "mutation_attempt": "source-traced witness text",
            "post_validation_observation": "source-traced witness text",
        },
        {
            "incoming_identity": "source-traced witness text",
            "retained_identity": "source-traced witness text",
            "mismatch_guard": "source-traced witness text",
        },
    )
    with pytest.raises(RuntimeError, match="source-bound"):
        gate.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


def test_exact_changed_source_refs_can_back_distinct_probe_classes() -> None:
    """Every class witness must resolve to the exact changed-side source line it claims."""
    first = {
        "alias_origin": _source_ref(1),
        "mutation_attempt": _source_ref(1),
        "post_validation_observation": _source_ref(1),
    }
    second = {
        "incoming_identity": _source_ref(10),
        "retained_identity": _source_ref(10),
        "mismatch_guard": _source_ref(10),
    }
    gate.validate_substantive_verdict(_verdict(first, second), DIFF, ["tool.py"])


def test_probe_class_witness_cannot_point_at_an_unrelated_changed_line() -> None:
    """A class cannot borrow another probe's line merely because that line also changed."""
    first = {
        "alias_origin": _source_ref(10),
        "mutation_attempt": _source_ref(10),
        "post_validation_observation": _source_ref(10),
    }
    second = {
        "incoming_identity": _source_ref(10),
        "retained_identity": _source_ref(10),
        "mismatch_guard": _source_ref(10),
    }
    with pytest.raises(RuntimeError, match="probe location"):
        gate.validate_substantive_verdict(_verdict(first, second), DIFF, ["tool.py"])
