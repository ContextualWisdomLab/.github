#!/usr/bin/env python3
"""Finish PR #1641 after proving the first-stage generic-evidence false negative."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path("scripts/ci/noema_review_gate.py")
CORPUS_TEST = Path("tests/test_noema_observed_defect_corpus_current_main.py")
DOCTOR = Path("docs/doctoring/noema-observed-defect-corpus-current-main.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact trusted anchor or stop instead of guessing."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def patch_validator() -> None:
    """Require concrete distinct class observations in addition to coordinates."""
    text = SOURCE.read_text(encoding="utf-8")
    old_block = '''    for field in required_fields:
        source_ref = class_evidence.get(field)
        if not isinstance(source_ref, dict) or set(source_ref) != {"path", "line", "side"}:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires a "
                "source-bound changed-line reference"
            )
        source_location = _canonical_changed_location(
            source_ref, f"Noema adversarial probe {index} class_evidence.{field}"
        )
        if source_location != location:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} must bind to "
                "the probe location"
            )
'''
    new_block = '''    normalized_observations: list[str] = []
    for field in required_fields:
        source_ref = class_evidence.get(field)
        if not isinstance(source_ref, dict) or set(source_ref) != {
            "path",
            "line",
            "side",
            "observation",
        }:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires a "
                "source-bound changed-line reference with a non-empty observation"
            )
        observation = source_ref.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires a "
                "non-empty observation"
            )
        if len(observation) > MAX_THREAD_BODY_CHARS:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} observation "
                f"exceeds {MAX_THREAD_BODY_CHARS} characters"
            )
        normalized_observations.append(observation.strip().casefold())
        source_location = _canonical_changed_location(
            source_ref, f"Noema adversarial probe {index} class_evidence.{field}"
        )
        if source_location != location:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} must bind to "
                "the probe location"
            )
    if len(set(normalized_observations)) != len(normalized_observations):
        raise NoemaModelOutputError(
            f"Noema adversarial probe {index} requires distinct class-specific observations"
        )
'''
    text = replace_once(text, old_block, new_block, "class observation validation")

    old_schema = '''                                    "class_evidence": {
                                        field: location_example
                                        for field in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS["mutable_alias"]
                                    },
'''
    new_schema = '''                                    "class_evidence": {
                                        field: {
                                            **location_example,
                                            "observation": f"Concrete {field} observation at this changed line.",
                                        }
                                        for field in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS["mutable_alias"]
                                    },
'''
    text = replace_once(text, old_schema, new_schema, "prompt class-evidence schema")

    old_prompt = '''                "Observed defect taxonomy and required source-bound class_evidence keys: "
                + json.dumps(
                    {kind: list(fields) for kind, fields in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS.items()},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "Actively attack mutable alias/immutability escapes, time-of-check/time-of-use or changing-getter behavior, execution/tenant/request identity confusion, coercion boundaries, weak or vacuous test oracles, cross-file/cross-document contract contradictions, internal-vs-external authority overreach, missing causal dependency context, and security/reliability state-machine races. Distinguish confirmed defects from falsified hypotheses; do not manufacture findings to satisfy the taxonomy.",
'''
    new_prompt = '''                "Observed defect taxonomy and required source-bound class_evidence keys: "
                + json.dumps(
                    {kind: list(fields) for kind, fields in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS.items()},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "Every class_evidence witness must include path, line, side, and a non-empty concrete observation of that class-specific field at the cited changed line; observation strings within one probe must be distinct. Coordinates or taxonomy labels alone are not evidence.",
                "Actively attack mutable alias/immutability escapes, time-of-check/time-of-use or changing-getter behavior, execution/tenant/request identity confusion, coercion boundaries, weak or vacuous test oracles, cross-file/cross-document contract contradictions, internal-vs-external authority overreach, missing causal dependency context, and security/reliability state-machine races. Distinguish confirmed defects from falsified hypotheses; do not manufacture findings to satisfy the taxonomy.",
'''
    text = replace_once(text, old_prompt, new_prompt, "prompt observation contract")
    ast.parse(text, filename=str(SOURCE))
    SOURCE.write_text(text, encoding="utf-8")


def patch_regression_corpus() -> None:
    """Update the original corpus fixtures to the stronger observation schema."""
    text = CORPUS_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''def _class_evidence(kind: str) -> dict[str, dict[str, object]]:
    return {field: _source_ref() for field in noema.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind]}
''',
        '''def _class_evidence(kind: str) -> dict[str, dict[str, object]]:
    return {
        field: {
            **_source_ref(),
            "observation": f"{kind}:{field} observed at the exact changed line.",
        }
        for field in noema.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind]
    }
''',
        "corpus evidence fixture",
    )
    text = replace_once(
        text,
        '''    probe["class_evidence"]["mutation_attempt"] = {"path": "src/tool.py", "line": 1, "side": "LEFT"}
''',
        '''    probe["class_evidence"]["mutation_attempt"] = {
        "path": "src/tool.py",
        "line": 1,
        "side": "LEFT",
        "observation": "Mutation attempt observed on the wrong diff side.",
    }
''',
        "wrong-side corpus fixture",
    )
    ast.parse(text, filename=str(CORPUS_TEST))
    CORPUS_TEST.write_text(text, encoding="utf-8")


def patch_traceability() -> None:
    """Keep doctoring, baseline, and changelog aligned with executable evidence."""
    doctor = DOCTOR.read_text(encoding="utf-8")
    doctor = replace_once(
        doctor,
        "Witness values are exact `{path,line,side}` references to the probe location; prose labels alone do not satisfy the deterministic validator.",
        "Witness values are exact `{path,line,side,observation}` records bound to the probe location; every observation must be non-empty, bounded, and distinct across that probe's class-specific witness fields, so coordinates or prose taxonomy labels alone do not satisfy the deterministic validator.",
        "doctoring observation contract",
    )
    DOCTOR.write_text(doctor, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    baseline = replace_once(
        baseline,
        "- **Repair:** exact changed-side coordinates now require canonical positive integers; production review verdicts use a closed observed-defect taxonomy with class-specific, source-bound witness fields and distinct classes for material changes; the prompt actively attacks the same external-review failure families.",
        "- **Repair:** exact changed-side coordinates now require canonical positive integers; production review verdicts use a closed observed-defect taxonomy with class-specific source-bound witnesses that each carry non-empty bounded observations, reject repeated generic observations, and require distinct classes for material changes; the prompt actively attacks the same external-review failure families and states that coordinates or labels alone are insufficient evidence.",
        "baseline observation contract",
    )
    BASELINE.write_text(baseline, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    changelog = replace_once(
        changelog,
        "class witnesses bind to exact changed-side source coordinates, and the prompt explicitly attacks mutable-alias, TOCTOU, ",
        "class witnesses bind to exact changed-side source coordinates with non-empty distinct observations, and the prompt explicitly attacks mutable-alias, TOCTOU, ",
        "changelog observation contract",
    )
    CHANGELOG.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Apply the independently demonstrated review-followup repair."""
    patch_validator()
    patch_regression_corpus()
    patch_traceability()


if __name__ == "__main__":
    main()
