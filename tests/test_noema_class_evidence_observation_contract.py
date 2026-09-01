"""Regression tests for class-specific Noema probe observation evidence."""

from __future__ import annotations

import pytest

from scripts.ci import noema_review_gate as noema


DIFF = """diff --git a/src/tool.py b/src/tool.py
--- a/src/tool.py
+++ b/src/tool.py
@@ -1 +1 @@
-old = 1
+new = 1
"""


def _location() -> dict[str, object]:
    """Return the single exact changed-side location used by this fixture."""
    return {"path": "src/tool.py", "line": 1, "side": "RIGHT"}


def _class_evidence(
    kind: str,
    *,
    observations: bool,
    repeated: bool = False,
    source_excerpt: bool = False,
    generic_but_different: bool = False,
) -> dict[str, object]:
    """Build class evidence spanning the intentionally weak and hardened schemas."""
    evidence: dict[str, object] = {}
    for index, field in enumerate(noema.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind], start=1):
        witness = _location()
        if observations:
            if repeated:
                witness["observation"] = "same generic observation"
            elif generic_but_different:
                witness["observation"] = f"Different generic concern number {index} appears in this area."
            else:
                witness["observation"] = (
                    f"The `new` assignment preserves runtime relationship {index} relevant to {field}."
                )
        if source_excerpt:
            witness["source_excerpt"] = "new = 1"
        evidence[field] = witness
    return evidence


def _probe(
    kind: str,
    *,
    observations: bool,
    repeated: bool = False,
    source_excerpt: bool = False,
    generic_but_different: bool = False,
) -> dict[str, object]:
    """Build one adversarial probe for the requested observed defect class."""
    return {
        **_location(),
        "probe_kind": kind,
        "class_evidence": _class_evidence(
            kind,
            observations=observations,
            repeated=repeated,
            source_excerpt=source_excerpt,
            generic_but_different=generic_but_different,
        ),
        "hypothesis": f"Generic hypothesis relabeled as {kind}.",
        "attack_or_counterexample": f"Generic attack relabeled as {kind}.",
        "evidence": f"Probe evidence for {kind}.",
        "outcome": "falsified",
    }


def _verdict(
    *,
    observations: bool,
    repeated: bool = False,
    source_excerpt: bool = False,
    generic_but_different: bool = False,
) -> dict[str, object]:
    """Build an otherwise-valid approval verdict with two distinct class labels."""
    return {
        "decision": "approve",
        "summary": "Two observed defect classes were attacked.",
        "findings": [],
        "reviewed_lines": [{**_location(), "analysis": "Reviewed exact changed line."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Unit fixture does not exercise an external runtime.",
            "probes": [
                _probe(
                    "mutable_alias",
                    observations=observations,
                    repeated=repeated,
                    source_excerpt=source_excerpt,
                    generic_but_different=generic_but_different,
                ),
                _probe(
                    "time_of_check_time_of_use",
                    observations=observations,
                    repeated=repeated,
                    source_excerpt=source_excerpt,
                    generic_but_different=generic_but_different,
                ),
            ],
        },
    }


def test_location_only_class_evidence_cannot_relabel_generic_probes() -> None:
    """Different taxonomy labels cannot make coordinate-only generic probes substantive."""
    with pytest.raises(noema.NoemaModelOutputError, match="non-empty observation"):
        noema.validate_substantive_verdict(_verdict(observations=False), DIFF, ["src/tool.py"])


def test_repeated_generic_observations_do_not_satisfy_class_specific_witnesses() -> None:
    """A probe must provide distinct observations for its class-specific witness fields."""
    with pytest.raises(noema.NoemaModelOutputError, match="distinct class-specific observations"):
        noema.validate_substantive_verdict(
            _verdict(observations=True, repeated=True, source_excerpt=True),
            DIFF,
            ["src/tool.py"],
        )


def test_differently_worded_generic_observations_without_source_signal_are_rejected() -> None:
    """Unique prose labels are not evidence unless they name concrete changed-source content."""
    with pytest.raises(noema.NoemaModelOutputError, match="concrete token from source_excerpt"):
        noema.validate_substantive_verdict(
            _verdict(
                observations=True,
                source_excerpt=True,
                generic_but_different=True,
            ),
            DIFF,
            ["src/tool.py"],
        )


def test_fabricated_source_excerpt_is_rejected() -> None:
    """A model cannot attach a plausible observation to source text absent from the cited line."""
    verdict = _verdict(observations=True, source_excerpt=True)
    verdict["adversarial_validation"]["probes"][0]["class_evidence"]["mutation_attempt"][
        "source_excerpt"
    ] = "fabricated = 2"

    with pytest.raises(noema.NoemaModelOutputError, match="exact changed-line source_excerpt"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_distinct_source_bound_class_observations_are_accepted() -> None:
    """Concrete source-backed observations preserve an otherwise-valid multi-class verdict."""
    noema.validate_substantive_verdict(
        _verdict(observations=True, source_excerpt=True),
        DIFF,
        ["src/tool.py"],
    )
