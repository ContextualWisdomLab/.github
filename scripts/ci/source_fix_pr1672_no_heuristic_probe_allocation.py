#!/usr/bin/env python3
"""Replace Noema's hand-tuned 1/2-probe rule with exhaustive diff-scope evidence.

The causal defect is a live test-time-compute decision based only on a path
classification: source/test/workflow changes receive two adversarial probes
and other paths one.  No cited standard, statistical model, psychometric
model, or experiment identifies either number.  This repair does not invent
a substitute threshold.  It defines the finite review scope L as the exact
changed-side locations parsed from the trusted diff and requires complete
enumeration: reviewed-line evidence and adversarial probes must each cover
L.  Therefore the schema cardinality is |L| and Python validation proves set
coverage, both mathematical consequences of the input rather than tuned
allocation policy.
"""

from __future__ import annotations

import re
from pathlib import Path


GATE = Path("scripts/ci/noema_review_gate.py")
TELEMETRY_TEST = Path("tests/test_noema_repair_attempt_telemetry.py")
DOCTORING = Path("docs/doctoring/noema-repair-attempt-telemetry.md")
GAP = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, *, label: str) -> str:
    updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one regex anchor, found {count}")
    return updated


def patch_gate() -> None:
    text = GATE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\n\n",
        "",
        label="remove path-name material classifier import",
    )

    text = regex_once(
        text,
        r"# ``adversarial_validation\.probes`` carries a ``minItems`` floor built fresh\n"
        r".*?"
        r"# \(\"Noema adversarial validation requires at least 2 concrete probe\(s\)\"\)\.\n",
        "# ``adversarial_validation.probes`` and ``reviewed_lines`` carry a per-request\n"
        "# ``minItems`` value equal to |L|, where L is the finite set of exact changed-\n"
        "# side locations parsed from the trusted diff.  This is complete enumeration,\n"
        "# not a sample-size heuristic: every formal verdict must cover every member of\n"
        "# L in both review analysis and adversarial evidence.  The Python validator\n"
        "# independently proves set coverage because array cardinality alone cannot prove\n"
        "# that the model covered distinct locations.  JSON Schema Draft 2020-12 defines\n"
        "# ``minItems`` as a structural array-cardinality assertion; the allocation itself\n"
        "# is mathematically identified by the exact review scope, not by file names,\n"
        "# hand-tuned thresholds, or a model/provider preference.\n",
        label="replace heuristic probe-floor rationale",
    )

    text = replace_once(
        text,
        '            "reviewed_lines": {\n                "type": ["array", "null"],\n                "items": _NOEMA_REVIEWED_LINE_SCHEMA,\n            },',
        '            "reviewed_lines": {\n                "type": ["array", "null"],\n                "minItems": required_probes,\n                "items": _NOEMA_REVIEWED_LINE_SCHEMA,\n            },',
        label="schema reviewed-line cardinality",
    )

    text = regex_once(
        text,
        r"def _required_probe_count\(diff: str, changed_paths: Sequence\[str\] = \(\)\) -> int:\n"
        r".*?"
        r"\n\ndef validate_substantive_verdict\(",
        "def _required_probe_count(diff: str, changed_paths: Sequence[str] = ()) -> int:\n"
        "    \"\"\"Return |L| for the exact changed-side location set L.\n\n"
        "    ``changed_paths`` is retained only for API compatibility with existing callers;\n"
        "    it has no allocation authority.  Complete enumeration removes the former\n"
        "    path-name-based 1/2-probe sampling rule.\n"
        "    \"\"\"\n"
        "    del changed_paths\n"
        "    return len(changed_diff_locations(diff))\n\n\n"
        "def validate_substantive_verdict(",
        label="replace required probe count",
    )

    text = replace_once(
        text,
        '    reviewed_lines = verdict.get("reviewed_lines")\n'
        '    if not isinstance(reviewed_lines, list) or not reviewed_lines:\n'
        '        raise NoemaModelOutputError("Noema formal verdict requires at least one reviewed changed line")\n'
        '    for index, reviewed in enumerate(reviewed_lines, start=1):',
        '    reviewed_lines = verdict.get("reviewed_lines")\n'
        '    if not isinstance(reviewed_lines, list):\n'
        '        raise NoemaModelOutputError("Noema formal verdict requires reviewed_lines array evidence")\n'
        '    reviewed_locations: set[tuple[str, int, str]] = set()\n'
        '    for index, reviewed in enumerate(reviewed_lines, start=1):',
        label="replace reviewed-line numeric floor",
    )
    text = replace_once(
        text,
        '        if not isinstance(analysis, str) or not analysis.strip():\n'
        '            raise NoemaModelOutputError(f"Noema reviewed line {index} requires concrete analysis")\n\n'
        '    validation = verdict.get("adversarial_validation")',
        '        if not isinstance(analysis, str) or not analysis.strip():\n'
        '            raise NoemaModelOutputError(f"Noema reviewed line {index} requires concrete analysis")\n'
        '        reviewed_locations.add((str(location[0]), int(location[1]), str(location[2])))\n'
        '    if reviewed_locations != locations:\n'
        '        raise NoemaModelOutputError("Noema formal verdict must review every exact changed-side line")\n\n'
        '    validation = verdict.get("adversarial_validation")',
        label="enforce exhaustive reviewed-line coverage",
    )

    text = replace_once(
        text,
        '    probes = validation.get("probes")\n'
        '    required_probes = _required_probe_count(diff, changed_paths)\n'
        '    if not isinstance(probes, list) or len(probes) < required_probes:\n'
        '        raise NoemaModelOutputError(f"Noema adversarial validation requires at least {required_probes} concrete probe(s)")\n\n'
        '    confirmed: set[tuple[str, int, str]] = set()\n'
        '    identities: set[tuple[Any, ...]] = set()',
        '    probes = validation.get("probes")\n'
        '    if not isinstance(probes, list):\n'
        '        raise NoemaModelOutputError("Noema adversarial validation requires probes array evidence")\n\n'
        '    confirmed: set[tuple[str, int, str]] = set()\n'
        '    identities: set[tuple[Any, ...]] = set()\n'
        '    probed_locations: set[tuple[str, int, str]] = set()',
        label="replace adversarial numeric floor",
    )
    text = replace_once(
        text,
        '        if location not in locations:\n'
        '            raise NoemaModelOutputError(f"Noema adversarial probe {index} is not an exact changed-side line")\n'
        '        for field in ("hypothesis", "attack_or_counterexample", "evidence"):',
        '        if location not in locations:\n'
        '            raise NoemaModelOutputError(f"Noema adversarial probe {index} is not an exact changed-side line")\n'
        '        probed_locations.add((str(location[0]), int(location[1]), str(location[2])))\n'
        '        for field in ("hypothesis", "attack_or_counterexample", "evidence"):',
        label="collect adversarial probe locations",
    )
    text = replace_once(
        text,
        '        if outcome == "confirmed":\n'
        '            confirmed.add((str(probe["path"]), int(probe["line"]), str(probe["side"])))\n\n'
        '    if decision == "approve" and confirmed:',
        '        if outcome == "confirmed":\n'
        '            confirmed.add((str(probe["path"]), int(probe["line"]), str(probe["side"])))\n\n'
        '    if probed_locations != locations:\n'
        '        raise NoemaModelOutputError("Noema adversarial validation must probe every exact changed-side line")\n\n'
        '    if decision == "approve" and confirmed:',
        label="enforce exhaustive probe coverage",
    )

    text = replace_once(
        text,
        '                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",',
        '                "Every formal verdict must exhaustively cover the exact changed-side location set in reviewed_lines and with at least one distinct adversarial probe at every changed-side location; this is complete enumeration, not path-name-based sampling. APPROVE requires all concrete regression hypotheses to be falsified. REQUEST_CHANGES requires a confirmed probe at a finding location.",',
        label="replace prompt heuristic",
    )

    GATE.write_text(text, encoding="utf-8")


def patch_existing_tests() -> None:
    text = TELEMETRY_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    expected_format = gate._noema_verdict_response_format(1)  # README.md is not material',
        '    expected_format = gate._noema_verdict_response_format(len(gate.changed_diff_locations(DIFF)))',
        label="telemetry response-format expectation",
    )
    text = replace_once(
        text,
        '    assert expected == 2\n    assert probes_schema["minItems"] == expected',
        '    assert expected == len(gate.changed_diff_locations(material_diff))\n    assert probes_schema["minItems"] == expected',
        label="material response-format cardinality expectation",
    )

    replacement = '''def test_required_probe_count_is_the_shared_source_for_the_python_check_too():
    """Schema cardinality and Python coverage share the exact changed-line scope."""
    locations = gate.changed_diff_locations(DIFF)
    assert gate._required_probe_count(DIFF, ("README.md",)) == len(locations)

    verdict = _malformed_probe_verdict()
    verdict["adversarial_validation"]["probes"][0]["outcome"] = "falsified"
    verdict["reviewed_lines"].append(
        {
            "path": "README.md",
            "line": 1,
            "side": "LEFT",
            "analysis": "Reviewed the removed changed-side line.",
        }
    )
    verdict["adversarial_validation"]["probes"].append(
        {
            "path": "README.md",
            "line": 1,
            "side": "LEFT",
            "hypothesis": "The removed line could reveal a regression.",
            "attack_or_counterexample": "Compare the removed side with the replacement.",
            "evidence": "Observed the exact removed changed-side line in the diff.",
            "outcome": "falsified",
        }
    )
    gate.validate_substantive_verdict(verdict, DIFF, ("README.md",))


'''
    text = regex_once(
        text,
        r"def test_required_probe_count_is_the_shared_source_for_the_python_check_too\(\):\n.*?\n\ndef test_served_model_telemetry_reads_envelope_model_field_when_present",
        replacement + "def test_served_model_telemetry_reads_envelope_model_field_when_present",
        label="replace old 1/2 shared-source test",
    )
    TELEMETRY_TEST.write_text(text, encoding="utf-8")


def append_traceability() -> None:
    doctoring = DOCTORING.read_text(encoding="utf-8")
    section = """

## 2026-09-02 no-heuristic adversarial-evidence allocation amendment

RCA found a second independent decision defect in the live Noema gate: `_required_probe_count`
allocated two adversarial probes to paths classified as executable/test/workflow and one to all
other paths. Neither the incident evidence nor an authoritative standard, statistical model,
psychometric model, or cited experiment identified those counts. The path-name classification
therefore controlled test-time compute with a hand-authored threshold.

The replacement has no sampled count. Let `L = changed_diff_locations(diff)` be the finite set of
exact changed-side `(path, line, side)` locations parsed from the trusted diff. A formal verdict is
admissible only when both its reviewed-line location set and its adversarial-probe location set equal
`L`. The structural JSON-Schema lower bound is `|L|`; Python then proves set equality so duplicate
entries cannot manufacture coverage. This is complete enumeration of the declared review scope,
not a heuristic allocation, weighting rule, tie-break, or file-name inference. If `L` cannot be
parsed, the pre-existing formal-verdict validator fails closed.

The `minItems` use follows JSON Schema's normative array-cardinality vocabulary; it does not supply
or justify a sample size. The sample size is eliminated by exhaustive enumeration.

References (APA 7):

- JSON Schema. (2022). *JSON Schema validation: A vocabulary for structural validation of JSON (Draft 2020-12).* https://json-schema.org/draft/2020-12/json-schema-validation
- National Institute of Standards and Technology. (2023). *Artificial intelligence risk management framework (AI RMF 1.0)* (NIST AI 100-1). U.S. Department of Commerce. https://doi.org/10.6028/NIST.AI.100-1
"""
    if "2026-09-02 no-heuristic adversarial-evidence allocation amendment" not in doctoring:
        DOCTORING.write_text(doctoring.rstrip() + section + "\n", encoding="utf-8")

    gap = GAP.read_text(encoding="utf-8")
    gap_section = """

### 2026-09-02 — Noema probe allocation: path-name 1/2 rule removed

- **Live gap / RCA:** `scripts/ci/noema_review_gate.py` used `changed_file_is_material(path)` to
  allocate two probes for executable/test/workflow paths and one otherwise. The counts had no
  identified mathematical, statistical, psychometric, standards, or experimental authority.
- **Causal owner repair:** Noema now defines the admissible evidence scope as the exact finite set
  `L` of changed-side diff locations and requires complete reviewed-line and adversarial-probe
  coverage of `L`. Schema cardinality is `|L|`; Python independently verifies set equality.
- **Decision basis:** exhaustive enumeration is a mathematical consequence of scope membership;
  no path name, arbitrary threshold, weight, or fallback ranking controls compute allocation.
- **Failure behavior:** unparsable changed-line scope or incomplete coverage fails closed.
- **Executable provenance:** `tests/test_noema_no_heuristic_probe_allocation.py` pins path-name
  independence, exact cardinality, reviewed-line coverage, probe coverage, and schema parity.
- **References:** JSON Schema (2022), Draft 2020-12 validation vocabulary; NIST (2023), AI RMF 1.0,
  NIST AI 100-1. Full APA 7 entries are recorded in the Noema doctoring note.
"""
    if "Noema probe allocation: path-name 1/2 rule removed" not in gap:
        GAP.write_text(gap.rstrip() + gap_section + "\n", encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    entry = (
        "\n- Remove Noema's unsupported path-name-based one/two-probe test-time-compute rule. "
        "Formal verdicts now exhaustively enumerate the exact changed-side diff-location set; "
        "schema cardinality is the set cardinality and Python proves complete location coverage, "
        "failing closed on incomplete evidence.\n"
    )
    if "unsupported path-name-based one/two-probe" not in changelog:
        CHANGELOG.write_text(changelog.rstrip() + entry, encoding="utf-8")


def main() -> None:
    patch_gate()
    patch_existing_tests()
    append_traceability()


if __name__ == "__main__":
    main()
