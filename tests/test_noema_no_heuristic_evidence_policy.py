"""Noema contracts required by the repository's no-heuristics policy."""

from __future__ import annotations

import inspect
import json

import pytest

from scripts.ci import noema_review_gate as gate


DIFF = """diff --git a/example.py b/example.py
index 1111111..2222222 100644
--- a/example.py
+++ b/example.py
@@ -1 +1,2 @@
-old
+new
+more
"""


def _approve_verdict(probe_locations: set[tuple[str, int, str]]) -> dict:
    locations = gate.changed_diff_locations(DIFF)
    return {
        "decision": "approve",
        "summary": "Every changed-side location is explicitly accounted for.",
        "reviewed_lines": [
            {
                "path": path,
                "line": line,
                "side": side,
                "analysis": f"Exact changed-side analysis for {path}:{line}:{side}.",
            }
            for path, line, side in sorted(locations)
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Residual risk is recorded without inventing an acceptance threshold.",
            "probes": [
                {
                    "path": path,
                    "line": line,
                    "side": side,
                    "hypothesis": f"The change at {path}:{line}:{side} could regress behavior.",
                    "attack_or_counterexample": f"Trace the exact changed-side semantics at {path}:{line}:{side}.",
                    "evidence": f"Observed exact changed-side evidence at {path}:{line}:{side}.",
                    "outcome": "falsified",
                }
                for path, line, side in sorted(probe_locations)
            ],
        },
        "findings": [],
    }


def test_noema_call_has_no_repository_authored_sampling_or_network_repair_budget() -> None:
    source = inspect.getsource(gate.call_llm)
    assert '"temperature"' not in source
    assert "NOEMA_REPAIR_DEADLINE_SECONDS" not in source
    assert "_repair_wall_clock_deadline" not in source
    assert "return call_llm(" not in source
    assert not hasattr(gate, "NOEMA_REPAIR_DEADLINE_SECONDS")
    assert not hasattr(gate, "NoemaRepairDeadlineExceeded")


def test_structured_output_schema_has_no_hand_selected_probe_count_floor() -> None:
    assert not hasattr(gate, "_required_probe_count")
    schema = gate._noema_verdict_json_schema()
    probes = schema["properties"]["adversarial_validation"]["properties"]["probes"]
    assert "minItems" not in probes
    assert "minItems" not in json.dumps(gate._noema_verdict_response_format())


def test_approve_requires_set_complete_changed_side_evidence() -> None:
    locations = gate.changed_diff_locations(DIFF)
    assert len(locations) == 3
    incomplete = set(sorted(locations)[:-1])
    with pytest.raises(gate.NoemaModelOutputError, match="every changed-side line"):
        gate.validate_substantive_verdict(_approve_verdict(incomplete), DIFF)

    gate.validate_substantive_verdict(_approve_verdict(locations), DIFF)


def test_approve_fails_closed_when_the_diff_evidence_is_truncated() -> None:
    locations = gate.changed_diff_locations(DIFF)
    with pytest.raises(gate.NoemaModelOutputError, match="untruncated diff evidence"):
        gate.validate_substantive_verdict(
            _approve_verdict(locations),
            DIFF,
            truncated=True,
        )
