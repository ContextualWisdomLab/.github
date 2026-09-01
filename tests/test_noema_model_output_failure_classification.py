"""Regression for #1611: malformed model verdicts are infrastructure/model evidence.

A schema-valid JSON envelope whose adversarial probe uses an out-of-domain
outcome is not a consumer repository defect. The deterministic validator must
still reject it, but with a typed model-output error so the retry/control plane
can preserve the distinction from source findings and provider exhaustion.
"""

import pytest

from scripts.ci import noema_review_gate as gate


DIFF = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


def _verdict() -> dict:
    return {
        "decision": "approve",
        "summary": "The changed line was reviewed.",
        "reviewed_lines": [
            {
                "path": "README.md",
                "line": 1,
                "side": "RIGHT",
                "analysis": "The replacement is bounded and reviewable.",
            }
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No additional risk identified.",
            "probes": [
                {
                    "path": "README.md",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The replacement could be wrong.",
                    "attack_or_counterexample": "Compare the exact changed line.",
                    "evidence": "Observed the exact replacement in the diff.",
                    "outcome": "passed",  # real #1611 failure shape
                }
            ],
        },
        "findings": [],
    }


def test_invalid_probe_outcome_is_typed_model_output_failure() -> None:
    """Reject malformed LLM evidence without reclassifying it as source failure."""
    error_type = getattr(gate, "NoemaModelOutputError", None)
    assert error_type is not None, (
        "Noema must expose a typed model-output/schema failure so malformed "
        "LLM evidence cannot collapse into an opaque generic RuntimeError"
    )

    with pytest.raises(error_type, match="outcome must be falsified or confirmed"):
        gate.validate_substantive_verdict(_verdict(), DIFF, ["README.md"])
