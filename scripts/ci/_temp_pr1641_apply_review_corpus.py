#!/usr/bin/env python3
"""Temporary one-shot PR #1641 source repair; removed by its workflow."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path("scripts/ci/noema_review_gate.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one trusted source anchor or fail closed."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def apply_source_repair() -> None:
    """Harden canonical locations and observed defect-class review evidence."""
    text = SOURCE.read_text(encoding="utf-8")

    constants_anchor = 'DIFF_HUNK_RE = re.compile(r"^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@")\n'
    constants = '''DIFF_HUNK_RE = re.compile(r"^@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@")
OBSERVED_REVIEW_PROBE_KINDS = frozenset(
    {
        "mutable_alias",
        "time_of_check_time_of_use",
        "execution_identity",
        "coercion_boundary",
        "test_oracle",
        "cross_contract",
        "authority_boundary",
        "dependency_context",
        "state_machine_race",
    }
)
OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "mutable_alias": ("alias_origin", "mutation_attempt", "post_validation_observation"),
    "time_of_check_time_of_use": ("check_observation", "intervening_change", "use_observation"),
    "execution_identity": ("incoming_identity", "retained_identity", "mismatch_guard"),
    "coercion_boundary": ("raw_value", "conversion_path", "canonicality_guard"),
    "test_oracle": ("assertion_under_test", "negative_control", "distinguishing_observation"),
    "cross_contract": ("first_contract", "second_contract", "contradiction_or_alignment"),
    "authority_boundary": ("component_authority", "external_authority", "enforcement_boundary"),
    "dependency_context": ("dependency", "omitted_or_included_context", "causal_effect"),
    "state_machine_race": ("initial_state", "event_order", "invariant_observation"),
}
'''
    text = replace_once(text, constants_anchor, constants, "taxonomy constants")

    helper_anchor = '''    return value.removeprefix(prefix)\n\n\ndef validate_substantive_verdict(\n'''
    helper = '''    return value.removeprefix(prefix)


def _canonical_changed_location(record: dict[str, Any], label: str) -> tuple[str, int, str]:
    """Return a canonical changed-side location without bool/int coercion."""
    path_value = record.get("path")
    line_value = record.get("line")
    side_value = record.get("side")
    if not isinstance(path_value, str) or not path_value.strip():
        raise NoemaModelOutputError(f"{label} requires a canonical changed-side path")
    if type(line_value) is not int or line_value <= 0:
        raise NoemaModelOutputError(f"{label} requires a canonical positive integer line")
    if side_value not in {"LEFT", "RIGHT"}:
        raise NoemaModelOutputError(f"{label} requires canonical LEFT/RIGHT side")
    return (path_value, line_value, side_value)


def _validate_observed_probe_class_evidence(
    probe: dict[str, Any], probe_kind: str, index: int, location: tuple[str, int, str]
) -> None:
    """Require defect-class witnesses to bind to the probe's exact changed line."""
    class_evidence = probe.get("class_evidence")
    required_fields = OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[probe_kind]
    if not isinstance(class_evidence, dict) or set(class_evidence) != set(required_fields):
        expected = ", ".join(required_fields)
        raise NoemaModelOutputError(
            f"Noema adversarial probe {index} class_evidence for {probe_kind} "
            f"must contain exactly: {expected}"
        )
    for field in required_fields:
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


def validate_substantive_verdict(
'''
    text = replace_once(text, helper_anchor, helper, "location helpers")

    text = replace_once(
        text,
        '        location = (reviewed.get("path"), reviewed.get("line"), reviewed.get("side"))\n',
        '        location = _canonical_changed_location(reviewed, f"Noema reviewed line {index}")\n',
        "reviewed-line location",
    )
    text = replace_once(
        text,
        '    identities: set[tuple[Any, ...]] = set()\n    for index, probe in enumerate(probes, start=1):\n',
        '    identities: set[tuple[Any, ...]] = set()\n    probe_kinds: set[str] = set()\n    enforce_observed_taxonomy = bool(changed_paths)\n    for index, probe in enumerate(probes, start=1):\n',
        "probe taxonomy state",
    )
    text = replace_once(
        text,
        '        location = (probe.get("path"), probe.get("line"), probe.get("side"))\n        if location not in locations:\n',
        '        location = _canonical_changed_location(probe, f"Noema adversarial probe {index}")\n        if location not in locations:\n',
        "probe location",
    )
    text = replace_once(
        text,
        '        outcome = probe.get("outcome")\n        if outcome not in {"falsified", "confirmed"}:\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} outcome must be falsified or confirmed")\n        identity = (*location, probe["hypothesis"].strip().casefold(), probe["attack_or_counterexample"].strip().casefold())\n',
        '        outcome = probe.get("outcome")\n        if outcome not in {"falsified", "confirmed"}:\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} outcome must be falsified or confirmed")\n        if enforce_observed_taxonomy:\n            probe_kind = probe.get("probe_kind")\n            if not isinstance(probe_kind, str) or probe_kind not in OBSERVED_REVIEW_PROBE_KINDS:\n                raise NoemaModelOutputError(\n                    f"Noema adversarial probe {index} requires probe_kind from the observed defect taxonomy"\n                )\n            _validate_observed_probe_class_evidence(probe, probe_kind, index, location)\n            probe_kinds.add(probe_kind)\n        identity = (*location, probe["hypothesis"].strip().casefold(), probe["attack_or_counterexample"].strip().casefold())\n',
        "probe class validation",
    )
    text = replace_once(
        text,
        '    if decision == "approve" and confirmed:\n',
        '    if enforce_observed_taxonomy and len(probe_kinds) < required_probes:\n        raise NoemaModelOutputError(\n            f"Noema {decision} requires at least {required_probes} distinct probe_kind values"\n        )\n\n    if decision == "approve" and confirmed:\n',
        "probe diversity validation",
    )

    text = replace_once(
        text,
        '                                    **location_example,\n                                    "hypothesis": "...",\n',
        '                                    **location_example,\n                                    "probe_kind": "mutable_alias",\n                                    "class_evidence": {\n                                        field: location_example\n                                        for field in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS["mutable_alias"]\n                                    },\n                                    "hypothesis": "...",\n',
        "prompt schema example",
    )
    text = replace_once(
        text,
        '                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",\n',
        '                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; material source or test changes require at least two distinct probe_kind values and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",\n                "Observed defect taxonomy and required source-bound class_evidence keys: "\n                + json.dumps(\n                    {kind: list(fields) for kind, fields in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS.items()},\n                    sort_keys=True,\n                    separators=(",", ":"),\n                ),\n                "Actively attack mutable alias/immutability escapes, time-of-check/time-of-use or changing-getter behavior, execution/tenant/request identity confusion, coercion boundaries, weak or vacuous test oracles, cross-file/cross-document contract contradictions, internal-vs-external authority overreach, missing causal dependency context, and security/reliability state-machine races. Distinguish confirmed defects from falsified hypotheses; do not manufacture findings to satisfy the taxonomy.",\n',
        "prompt taxonomy instruction",
    )
    text = replace_once(
        text,
        '                f"- `{probe.get(\'path\')}:{probe.get(\'line\')} ({probe.get(\'side\')})` "\n                f"{probe.get(\'outcome\')}: {str(probe.get(\'hypothesis\') or \'\').strip()} — "\n',
        '                f"- [{probe.get(\'probe_kind\') or \'legacy\'}] `{probe.get(\'path\')}:{probe.get(\'line\')} ({probe.get(\'side\')})` "\n                f"{probe.get(\'outcome\')}: {str(probe.get(\'hypothesis\') or \'\').strip()} — "\n',
        "review evidence class",
    )

    ast.parse(text, filename=str(SOURCE))
    SOURCE.write_text(text, encoding="utf-8")


def update_docs() -> None:
    """Record the operating contract and the externally observed regression corpus."""
    doctor = Path("docs/doctoring/noema-observed-defect-corpus-current-main.md")
    doctor.write_text(
        """# Noema observed-defect review corpus

The trusted Noema review gate treats externally demonstrated review misses as executable regression evidence, not as benchmark claims. Material source/test reviews must exercise at least two distinct observed defect classes and every admitted class witness remains bound to an exact changed-side source coordinate.

The current closed taxonomy is: `mutable_alias`, `time_of_check_time_of_use`, `execution_identity`, `coercion_boundary`, `test_oracle`, `cross_contract`, `authority_boundary`, `dependency_context`, and `state_machine_race`. Each class has class-specific witness keys. Witness values are exact `{path,line,side}` references to the probe location; prose labels alone do not satisfy the deterministic validator.

The model is explicitly asked to attack mutable/immutability escapes, changing getters/TOCTOU, request or tenant identity confusion, weak/vacuous oracles, cross-contract contradictions, authority overreach, missing causal dependency context, and reliability/security state-machine races. A falsified hypothesis is valid evidence and must not be promoted into a finding merely to satisfy taxonomy diversity.

JSON booleans are rejected as line coordinates even though Python considers `True == 1`: changed-line evidence requires `type(line) is int` and a positive value. Production review calls always provide the complete changed-path manifest, which activates the observed taxonomy; direct validator unit tests may omit that manifest to exercise lower-level generic schema boundaries independently.

This repair is a narrow current-main successor to the heavily diverged PR #1589 evidence lineage. It does not copy CodeRabbitAI or Devin wording and makes no superiority claim.
""",
        encoding="utf-8",
    )

    baseline = Path("docs/product-technical-gap-baseline.md")
    baseline_text = baseline.read_text(encoding="utf-8")
    marker = "### 2026-09-02 — Noema observed-defect false-negative corpus (#1641)"
    if marker not in baseline_text:
        baseline_text += f"""

{marker}

- **Verified gap:** protected current main admitted Noema adversarial evidence by count/prose identity and compared model line coordinates with Python integers without excluding booleans. Thus `true` could alias line `1`, and two differently worded probes could satisfy material-change diversity without proving distinct observed defect shapes.
- **Repair:** exact changed-side coordinates now require canonical positive integers; production review verdicts use a closed observed-defect taxonomy with class-specific, source-bound witness fields and distinct classes for material changes; the prompt actively attacks the same external-review failure families.
- **Regression evidence:** `tests/test_noema_observed_defect_corpus_current_main.py` is committed before the causal production change and covers boolean aliasing, malformed/unknown class labels, duplicate-class diversity, witness/source binding, a valid multi-class verdict, and rendered prompt coverage.
- **Authority boundary:** no reviewer, provider, routing, merge, or repository-write authority is widened. The taxonomy is evaluation/admission evidence only.
"""
        baseline.write_text(baseline_text, encoding="utf-8")

    changelog = Path("CHANGELOG.md")
    changelog_text = changelog.read_text(encoding="utf-8")
    entry = (
        "- **Require source-bound observed defect classes in Noema formal reviews (#1641).** "
        "Canonical changed-line coordinates now reject JSON booleans, material reviews must cover "
        "distinct classes from the executable external-finding corpus, class witnesses bind to exact "
        "changed-side source coordinates, and the prompt explicitly attacks mutable-alias, TOCTOU, "
        "identity, oracle, contract, authority, dependency-context, coercion, and state-machine failure "
        "shapes without fabricating benchmark claims.\n"
    )
    if entry not in changelog_text:
        anchor = "## [Unreleased]\n"
        if changelog_text.count(anchor) != 1:
            raise SystemExit("could not locate unique Unreleased changelog anchor")
        changelog.write_text(changelog_text.replace(anchor, anchor + entry, 1), encoding="utf-8")


def main() -> None:
    """Apply the one-shot code and traceability repair."""
    apply_source_repair()
    update_docs()


if __name__ == "__main__":
    main()
