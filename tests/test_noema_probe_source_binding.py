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


def _valid_verdict() -> dict:
    """Return one fully source-bound verdict for coordinate-shape regressions."""
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
    return _verdict(first, second)


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
    gate.validate_substantive_verdict(_valid_verdict(), DIFF, ["tool.py"])


def test_probe_class_witness_cannot_point_at_an_unrelated_changed_line() -> None:
    """A class cannot borrow another probe's line merely because that line also changed."""
    verdict = _valid_verdict()
    wrong_ref = _source_ref(10)
    verdict["adversarial_validation"]["probes"][0]["class_evidence"] = {
        "alias_origin": dict(wrong_ref),
        "mutation_attempt": dict(wrong_ref),
        "post_validation_observation": dict(wrong_ref),
    }
    with pytest.raises(RuntimeError, match="probe location"):
        gate.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


@pytest.mark.parametrize("bad_line", [True, False])
def test_reviewed_line_rejects_boolean_coordinate(bad_line: bool) -> None:
    """JSON booleans must never compare equal to integer diff coordinates."""
    verdict = _valid_verdict()
    verdict["reviewed_lines"][0]["line"] = bad_line
    with pytest.raises(RuntimeError, match="canonical positive integer line"):
        gate.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


@pytest.mark.parametrize("bad_line", [True, False])
def test_probe_location_rejects_boolean_coordinate(bad_line: bool) -> None:
    """Probe locations must carry canonical integer line numbers before membership checks."""
    verdict = _valid_verdict()
    verdict["adversarial_validation"]["probes"][0]["line"] = bad_line
    with pytest.raises(RuntimeError, match="canonical positive integer line"):
        gate.validate_substantive_verdict(verdict, DIFF, ["tool.py"])


@pytest.mark.parametrize("bad_line", [True, False])
def test_class_evidence_rejects_boolean_coordinate(bad_line: bool) -> None:
    """Class-evidence references cannot exploit bool/int equality in dictionary comparison."""
    verdict = _valid_verdict()
    verdict["adversarial_validation"]["probes"][0]["class_evidence"]["alias_origin"]["line"] = bad_line
    with pytest.raises(RuntimeError, match="canonical positive integer line"):
        gate.validate_substantive_verdict(verdict, DIFF, ["tool.py"])
