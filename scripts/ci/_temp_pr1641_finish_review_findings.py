#!/usr/bin/env python3
"""Finish PR #1641 after proving first-stage review-evidence false negatives."""

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
    """Require exact source excerpts and non-vacuous class observations."""
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
    source_texts = changed_diff_line_texts(diff)
    for field in required_fields:
        source_ref = class_evidence.get(field)
        if not isinstance(source_ref, dict) or set(source_ref) != {
            "path",
            "line",
            "side",
            "source_excerpt",
            "observation",
        }:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires "
                "path, line, side, exact source_excerpt, and non-empty observation"
            )
        source_location = _canonical_changed_location(
            source_ref, f"Noema adversarial probe {index} class_evidence.{field}"
        )
        if source_location != location:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} must bind to "
                "the probe location"
            )
        expected_excerpt = source_texts.get(source_location)
        source_excerpt = source_ref.get("source_excerpt")
        if (
            not isinstance(source_excerpt, str)
            or not source_excerpt.strip()
            or expected_excerpt is None
            or source_excerpt != expected_excerpt
        ):
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires the "
                "exact changed-line source_excerpt"
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
        source_tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|\\d+", source_excerpt)
        }
        observation_tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|\\d+", observation)
        }
        if not source_tokens or not source_tokens.intersection(observation_tokens):
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} observation "
                "must name a concrete token from source_excerpt"
            )
        label_tokens = {probe_kind.casefold(), field.casefold()} | {
            token.casefold()
            for token in re.findall(
                r"[A-Za-z_][A-Za-z0-9_]{2,}",
                f"{probe_kind} {field}".replace("_", " "),
            )
        }
        filler_tokens = {
            "area",
            "changed",
            "concern",
            "concrete",
            "evidence",
            "exact",
            "generic",
            "here",
            "line",
            "nearby",
            "observed",
            "observation",
            "probe",
            "review",
            "source",
            "this",
            "value",
        }
        causal_tokens = observation_tokens - source_tokens - label_tokens - filler_tokens
        if not causal_tokens:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires a "
                "concrete causal observation beyond source and taxonomy labels"
            )
        normalized_observations.append(observation.strip().casefold())
    if len(set(normalized_observations)) != len(normalized_observations):
        raise NoemaModelOutputError(
            f"Noema adversarial probe {index} requires distinct class-specific observations"
        )
'''
    text = replace_once(text, old_block, new_block, "class observation validation")

    text = replace_once(
        text,
        '''def _validate_observed_probe_class_evidence(
    probe: dict[str, Any], probe_kind: str, index: int, location: tuple[str, int, str]
) -> None:
''',
        '''def _validate_observed_probe_class_evidence(
    probe: dict[str, Any],
    probe_kind: str,
    index: int,
    location: tuple[str, int, str],
    diff: str,
) -> None:
''',
        "class evidence validator signature",
    )

    helper_anchor = '''    return locations


def parse_diff_path(raw: str, prefix: str) -> str:
'''
    helper = '''    return locations


def changed_diff_line_texts(diff: str) -> dict[tuple[str, int, str], str]:
    """Return exact changed-side source text keyed by canonical diff location."""
    texts: dict[tuple[str, int, str], str] = {}
    old_path = new_path = ""
    old_line = new_line = 0
    in_hunk = False
    for raw_line in diff.splitlines():
        if raw_line.startswith("diff --git "):
            old_path = new_path = ""
            in_hunk = False
            continue
        if not in_hunk and raw_line.startswith("--- "):
            old_path = parse_diff_path(raw_line[4:], "a/")
            continue
        if not in_hunk and raw_line.startswith("+++ "):
            new_path = parse_diff_path(raw_line[4:], "b/")
            continue
        match = DIFF_HUNK_RE.match(raw_line)
        if match:
            old_line, new_line = map(int, match.groups())
            in_hunk = True
            continue
        if not in_hunk or raw_line.startswith("\\ No newline"):
            continue
        if raw_line.startswith("+"):
            if not new_path:
                return {}
            texts[(new_path, new_line, "RIGHT")] = raw_line[1:]
            new_line += 1
        elif raw_line.startswith("-"):
            if not old_path:
                return {}
            texts[(old_path, old_line, "LEFT")] = raw_line[1:]
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return texts


def parse_diff_path(raw: str, prefix: str) -> str:
'''
    text = replace_once(text, helper_anchor, helper, "changed-line source helper")

    text = replace_once(
        text,
        "            _validate_observed_probe_class_evidence(probe, probe_kind, index, location)\n",
        "            _validate_observed_probe_class_evidence(probe, probe_kind, index, location, diff)\n",
        "class evidence validator call",
    )

    old_schema = '''                                    "class_evidence": {
                                        field: location_example
                                        for field in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS["mutable_alias"]
                                    },
'''
    new_schema = '''                                    "class_evidence": {
                                        field: {
                                            **location_example,
                                            "source_excerpt": "exact changed-line text",
                                            "observation": (
                                                f"Concrete {field} causal observation naming a token "
                                                "from source_excerpt."
                                            ),
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
                "Every class_evidence witness must include path, line, side, source_excerpt, and observation. source_excerpt must be the exact cited changed-side line. The observation must name a concrete token from that source_excerpt and explain a causal or behavioral relation beyond taxonomy labels; differently worded generic labels are not evidence.",
                "Actively attack mutable alias/immutability escapes, time-of-check/time-of-use or changing-getter behavior, execution/tenant/request identity confusion, coercion boundaries, weak or vacuous test oracles, cross-file/cross-document contract contradictions, internal-vs-external authority overreach, missing causal dependency context, and security/reliability state-machine races. For automation or CI that mutates a branch or source and then relies on later events, verify that the mutation uses a workflow-starting credential/actor and that downstream required checks can actually be created on the successor head. Distinguish confirmed defects from falsified hypotheses; do not manufacture findings to satisfy the taxonomy.",
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
            "source_excerpt": "new = 1",
            "observation": (
                f"The `new` assignment preserves runtime relationship {index} relevant to {field}."
            ),
        }
        for index, field in enumerate(
            noema.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind],
            start=1,
        )
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
        "source_excerpt": "old = 1",
        "observation": "The `old` assignment is removed before the attempted mutation relationship.",
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
        "Witness values are `{path,line,side,source_excerpt,observation}` records bound to the probe location. `source_excerpt` must equal the exact changed-side line, and `observation` must name a concrete source token plus a causal/behavioral relation beyond taxonomy labels; repeated or differently worded generic labels do not satisfy the deterministic validator.",
        "doctoring observation contract",
    )
    doctor = doctor.replace(
        "A falsified hypothesis is valid evidence and must not be promoted into a finding merely to satisfy taxonomy diversity.",
        "A falsified hypothesis is valid evidence and must not be promoted into a finding merely to satisfy taxonomy diversity. For CI/automation changes, the review prompt also requires checking whether the mutation credential can create the downstream events/checks the state machine depends on.",
    )
    DOCTOR.write_text(doctor, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    baseline = replace_once(
        baseline,
        "- **Repair:** exact changed-side coordinates now require canonical positive integers; production review verdicts use a closed observed-defect taxonomy with class-specific, source-bound witness fields and distinct classes for material changes; the prompt actively attacks the same external-review failure families.",
        "- **Repair:** exact changed-side coordinates now require canonical positive integers; production review verdicts use a closed observed-defect taxonomy with class-specific source-bound witnesses whose exact `source_excerpt` must match the cited changed line and whose observation must name concrete source content plus causal behavior. Material changes require distinct classes, and the prompt explicitly checks workflow-starting mutation credentials before relying on downstream required checks.",
        "baseline observation contract",
    )
    BASELINE.write_text(baseline, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    changelog = replace_once(
        changelog,
        "class witnesses bind to exact changed-side source coordinates, and the prompt explicitly attacks mutable-alias, TOCTOU, ",
        "class witnesses bind to exact changed-side source text with non-vacuous causal observations, and the prompt explicitly attacks workflow-event authority plus mutable-alias, TOCTOU, ",
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
