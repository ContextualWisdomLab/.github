"""No-heuristic contract for Noema adversarial-review compute allocation.

The live gate used a file-name classification to require two probes for
"material" paths and one for other paths.  Those fixed counts are not an
identified statistical, psychometric, or standards-backed allocation rule.
The replacement contract is complete enumeration of the finite changed-side
location set L parsed from the exact diff: every formal verdict must review
and adversarially probe every member of L.  The required count is therefore
|L|, a mathematical consequence of the review scope rather than a tuned
threshold or path-name inference.
"""

import pytest

from scripts.ci import noema_review_gate as gate


TWO_LINE_DOC_DIFF = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@
-old one
-old two
+new one
+new two
"""

ONE_LINE_CODE_DIFF = """diff --git a/example.py b/example.py
index 1111111..2222222 100644
--- a/example.py
+++ b/example.py
@@ -1 +1 @@
-old
+new
"""


def _approve_verdict(locations: set[tuple[str, int, str]]) -> dict:
    ordered = sorted(locations)
    return {
        "decision": "approve",
        "summary": "Every exact changed-side location was reviewed and challenged.",
        "reviewed_lines": [
            {
                "path": path,
                "line": line,
                "side": side,
                "analysis": f"Reviewed {path}:{line}:{side} against the exact diff.",
            }
            for path, line, side in ordered
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No confirmed counterexample remained in the exhaustively enumerated scope.",
            "probes": [
                {
                    "path": path,
                    "line": line,
                    "side": side,
                    "hypothesis": f"The change at {path}:{line}:{side} could be incorrect.",
                    "attack_or_counterexample": f"Challenge the exact changed-side evidence at {path}:{line}:{side}.",
                    "evidence": f"The exact changed-side location {path}:{line}:{side} was checked.",
                    "outcome": "falsified",
                }
                for path, line, side in ordered
            ],
        },
        "findings": [],
    }


def test_required_probe_count_is_exact_scope_cardinality_not_path_classification():
    doc_locations = gate.changed_diff_locations(TWO_LINE_DOC_DIFF)
    code_locations = gate.changed_diff_locations(ONE_LINE_CODE_DIFF)

    assert len(doc_locations) > len(code_locations)
    assert gate._required_probe_count(TWO_LINE_DOC_DIFF, ("README.md",)) == len(doc_locations)
    assert gate._required_probe_count(ONE_LINE_CODE_DIFF, ("example.py",)) == len(code_locations)


def test_formal_verdict_fails_closed_when_any_changed_location_is_not_reviewed():
    locations = gate.changed_diff_locations(TWO_LINE_DOC_DIFF)
    verdict = _approve_verdict(locations)
    verdict["reviewed_lines"].pop()

    with pytest.raises(gate.NoemaModelOutputError, match="review every exact changed-side line"):
        gate.validate_substantive_verdict(verdict, TWO_LINE_DOC_DIFF, ("README.md",))


def test_formal_verdict_fails_closed_when_any_changed_location_is_not_probed():
    locations = gate.changed_diff_locations(TWO_LINE_DOC_DIFF)
    verdict = _approve_verdict(locations)
    verdict["adversarial_validation"]["probes"].pop()

    with pytest.raises(gate.NoemaModelOutputError, match="probe every exact changed-side line"):
        gate.validate_substantive_verdict(verdict, TWO_LINE_DOC_DIFF, ("README.md",))


def test_schema_floor_is_exact_scope_cardinality():
    required = len(gate.changed_diff_locations(TWO_LINE_DOC_DIFF))
    schema = gate._noema_verdict_json_schema(required)
    reviewed = schema["properties"]["reviewed_lines"]
    probes = schema["properties"]["adversarial_validation"]["properties"]["probes"]

    assert reviewed["minItems"] == required
    assert probes["minItems"] == required
