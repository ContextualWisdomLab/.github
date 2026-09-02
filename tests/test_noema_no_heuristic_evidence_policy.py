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
@@ -1 +1 @@
-old
+new
"""


def _request_changes(*, finding_locations: set[tuple[str, int, str]], confirmed_locations: set[tuple[str, int, str]]) -> dict:
    return {
        "decision": "request_changes",
        "summary": "Concrete blocking findings are backed by changed-line counterexamples.",
        "reviewed_lines": [
            {"path": path, "line": line, "side": side, "analysis": "Exact changed-line analysis."}
            for path, line, side in sorted(finding_locations)
        ],
        "adversarial_validation": {
            "status": "failed",
            "residual_risk": "Blocking changed-line evidence remains.",
            "probes": [
                {
                    "path": path,
                    "line": line,
                    "side": side,
                    "hypothesis": "This changed line can cause the published blocking defect.",
                    "attack_or_counterexample": "Exercise the exact changed-line behavior.",
                    "evidence": "The exact changed-line counterexample confirms the defect.",
                    "outcome": "confirmed",
                }
                for path, line, side in sorted(confirmed_locations)
            ],
        },
        "findings": [
            {"severity": "high", "file": path, "line": line, "side": side, "message": "Concrete blocking defect."}
            for path, line, side in sorted(finding_locations)
        ],
    }


def test_noema_call_has_no_repository_authored_sampling_timeout_or_retry_allocation() -> None:
    source = inspect.getsource(gate.call_llm)
    assert '"temperature"' not in source
    assert "NOEMA_REPAIR_DEADLINE_SECONDS" not in source
    assert "_repair_wall_clock_deadline" not in source
    assert "return call_llm(" not in source
    assert not hasattr(gate, "NOEMA_REPAIR_DEADLINE_SECONDS")
    assert not hasattr(gate, "NoemaRepairDeadlineExceeded")


def test_structured_output_schema_has_no_hand_selected_probe_quota_and_cannot_authorize_approve() -> None:
    assert not hasattr(gate, "_required_probe_count")
    schema = gate._noema_verdict_json_schema()
    assert schema["properties"]["decision"]["enum"] == ["request_changes", "comment"]
    probes = schema["properties"]["adversarial_validation"]["properties"]["probes"]
    assert "minItems" not in probes
    assert "minItems" not in json.dumps(gate._noema_verdict_response_format())


def test_every_published_blocking_finding_requires_a_confirmed_probe_at_its_exact_location() -> None:
    locations = gate.changed_diff_locations(DIFF)
    assert len(locations) == 2
    all_findings = set(locations)
    one_confirmed = {next(iter(locations))}
    with pytest.raises(gate.NoemaModelOutputError, match="every published finding"):
        gate.validate_substantive_verdict(
            _request_changes(
                finding_locations=all_findings,
                confirmed_locations=one_confirmed,
            ),
            DIFF,
        )

    gate.validate_substantive_verdict(
        _request_changes(
            finding_locations=all_findings,
            confirmed_locations=all_findings,
        ),
        DIFF,
    )


def test_approve_is_fail_closed_without_an_independently_governed_admission_design() -> None:
    verdict = {
        "decision": "approve",
        "summary": "No issues found.",
        "reviewed_lines": [],
        "adversarial_validation": {"status": "passed", "residual_risk": "none", "probes": []},
        "findings": [],
    }
    with pytest.raises(gate.NoemaModelOutputError, match="does not authorize approve"):
        gate.validate_substantive_verdict(verdict, DIFF)
