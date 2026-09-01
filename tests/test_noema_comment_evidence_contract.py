"""Regression contracts for evidence-bearing Noema COMMENT reviews."""

from __future__ import annotations

import pytest

from scripts.ci import noema_review_gate as noema


DIFF = """diff --git a/src/reviewer.py b/src/reviewer.py
--- a/src/reviewer.py
+++ b/src/reviewer.py
@@ -1 +1 @@
-old
+new
"""
LOCATION = {"path": "src/reviewer.py", "line": 1, "side": "RIGHT"}


def _class_evidence(*fields: str) -> dict[str, dict[str, object]]:
    """Bind every class-specific witness to the exact changed line under review."""
    return {field: dict(LOCATION) for field in fields}


def _evidence_bearing_comment() -> dict[str, object]:
    """Return a material-change COMMENT carrying approval-grade falsification evidence."""
    return {
        "decision": "comment",
        "summary": "Non-blocking review with complete evidence.",
        "reviewed_lines": [{**LOCATION, "analysis": "The changed branch is inspected directly."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No residual blocking defect observed in the bounded changed-line probes.",
            "probes": [
                {
                    **LOCATION,
                    "probe_kind": "test_oracle",
                    "class_evidence": _class_evidence(
                        "assertion_under_test",
                        "negative_control",
                        "distinguishing_observation",
                    ),
                    "hypothesis": "A weak oracle could accept the opposite behavior.",
                    "attack_or_counterexample": "Exercise a negative control that differs only at the changed branch.",
                    "evidence": "The exact changed-line branch distinguishes the negative control.",
                    "outcome": "falsified",
                },
                {
                    **LOCATION,
                    "probe_kind": "dependency_context",
                    "class_evidence": _class_evidence(
                        "dependency",
                        "omitted_or_included_context",
                        "causal_effect",
                    ),
                    "hypothesis": "An omitted caller dependency could reverse the local conclusion.",
                    "attack_or_counterexample": "Trace the dependency entering the changed branch.",
                    "evidence": "The caller contract preserves the changed branch precondition.",
                    "outcome": "falsified",
                },
            ],
        },
        "findings": [],
    }


def test_comment_without_changed_line_or_probe_evidence_is_rejected() -> None:
    """COMMENT is presentation semantics, never a completed-review evidence bypass."""
    with pytest.raises(RuntimeError, match="reviewed changed line"):
        noema.validate_substantive_verdict(
            {"decision": "comment", "summary": "Looks interesting.", "findings": []},
            DIFF,
            ("src/reviewer.py",),
        )


def test_material_comment_requires_and_accepts_two_distinct_observed_probe_classes() -> None:
    """A non-blocking material review is admissible only with approval-grade evidence."""
    noema.validate_substantive_verdict(
        _evidence_bearing_comment(),
        DIFF,
        ("src/reviewer.py",),
    )


def test_call_llm_runtime_is_bound_to_the_strict_public_validator() -> None:
    """The production model-call path must resolve the same strict validator tested here."""
    assert noema.call_llm.__globals__["validate_substantive_verdict"] is noema.validate_substantive_verdict
    assert noema.validate_substantive_verdict.__module__ == "scripts.ci.noema_review_gate"
