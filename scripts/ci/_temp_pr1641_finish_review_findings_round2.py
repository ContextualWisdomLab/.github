#!/usr/bin/env python3
"""Finish PR #1641 after exact-head review exposed source-binding edge cases."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path("scripts/ci/noema_review_gate.py")
CORPUS_TEST = Path("tests/test_noema_observed_defect_corpus_current_main.py")
DOCTOR = Path("docs/doctoring/noema-observed-defect-corpus-current-main.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one trusted generated-source anchor or fail closed."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def patch_validator() -> None:
    """Bind evidence to exact source text without ASCII/token-shape heuristics."""
    text = SOURCE.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''        if (
            not isinstance(source_excerpt, str)
            or not source_excerpt.strip()
            or expected_excerpt is None
            or source_excerpt != expected_excerpt
        ):
''',
        '''        if (
            not isinstance(source_excerpt, str)
            or expected_excerpt is None
            or source_excerpt != expected_excerpt
        ):
''',
        "blank exact-source admission",
    )

    old_tokens = '''        source_tokens = {
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
'''
    new_tokens = '''        source_marker = source_excerpt if source_excerpt else "<blank>"
        if source_marker not in observation:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} observation "
                "must quote the exact source_excerpt (or <blank> for an empty line)"
            )
        relation_tokens = {
            "accepts",
            "after",
            "aliases",
            "allows",
            "before",
            "because",
            "blocks",
            "bypasses",
            "cancels",
            "causes",
            "changes",
            "conflicts",
            "depends",
            "differs",
            "escapes",
            "fails",
            "mismatches",
            "mutates",
            "prevents",
            "preserves",
            "races",
            "reads",
            "rejects",
            "relationship",
            "reuses",
            "shares",
            "truncates",
            "when",
            "while",
            "without",
            "writes",
        }
        observation_tokens = {
            token.casefold()
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", observation)
        }
        if not relation_tokens.intersection(observation_tokens):
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires a "
                "causal relationship, not an arbitrary source-adjacent word"
            )
'''
    text = replace_once(text, old_tokens, new_tokens, "causal source binding")

    text = replace_once(
        text,
        '''        if raw_line.startswith("+"):
            if not new_path:
                return {}
            texts[(new_path, new_line, "RIGHT")] = raw_line[1:]
            new_line += 1
        elif raw_line.startswith("-"):
            if not old_path:
                return {}
            texts[(old_path, old_line, "LEFT")] = raw_line[1:]
            old_line += 1
''',
        '''        if raw_line.startswith("+"):
            if not new_path:
                return {}
            source_text = raw_line[1:]
            if source_text != "[overlong changed line content omitted]":
                texts[(new_path, new_line, "RIGHT")] = source_text
            new_line += 1
        elif raw_line.startswith("-"):
            if not old_path:
                return {}
            source_text = raw_line[1:]
            if source_text != "[overlong changed line content omitted]":
                texts[(old_path, old_line, "LEFT")] = source_text
            old_line += 1
''',
        "truncated source exclusion",
    )

    text = replace_once(
        text,
        '''                "Every class_evidence witness must include path, line, side, source_excerpt, and observation. source_excerpt must be the exact cited changed-side line. The observation must name a concrete token from that source_excerpt and explain a causal or behavioral relation beyond taxonomy labels; differently worded generic labels are not evidence.",
''',
        '''                "Every class_evidence witness must include path, line, side, source_excerpt, and observation. source_excerpt must be the exact cited changed-side line, including an empty string for a blank line; an overlong-line omission marker is never source evidence. The observation must quote that exact source_excerpt (or <blank>) and state a causal/behavioral relationship; an arbitrary adjacent word or differently worded generic label is not evidence.",
''',
        "prompt exact-source contract",
    )

    ast.parse(text, filename=str(SOURCE))
    SOURCE.write_text(text, encoding="utf-8")


def patch_corpus_fixture() -> None:
    """Make the durable corpus satisfy the strengthened exact-source relation contract."""
    text = CORPUS_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'f"The `new` assignment preserves runtime relationship {index} relevant to {field}."',
        'f"The exact `new = 1` source preserves runtime relationship {index} relevant to {field}."',
        "corpus source quotation",
    )
    text = replace_once(
        text,
        '"The `old` assignment is removed before the attempted mutation relationship."',
        '"The exact `old = 1` source is removed before the attempted mutation relationship."',
        "wrong-side source quotation",
    )
    ast.parse(text, filename=str(CORPUS_TEST))
    CORPUS_TEST.write_text(text, encoding="utf-8")


def patch_traceability() -> None:
    """Record why lexical heuristics and bounded-diff omission markers are non-authoritative."""
    doctor = DOCTOR.read_text(encoding="utf-8")
    doctor = doctor.replace(
        "`observation` must name a concrete source token plus a causal/behavioral relation beyond taxonomy labels",
        "`observation` must quote the exact source line (or `<blank>`) plus a causal/behavioral relation beyond taxonomy labels; ASCII token shape is not admission authority",
    )
    doctor += (
        "\n\nExact-head follow-up also makes bounded-diff omission markers ineligible as source evidence. "
        "Short identifiers, symbol-only lines, blank changed lines, and non-ASCII source remain admissible "
        "through exact string equality rather than lexical guessing.\n"
    )
    DOCTOR.write_text(doctor, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    baseline = baseline.replace(
        "whose exact `source_excerpt` must match the cited changed line and whose observation must name concrete source content plus causal behavior",
        "whose exact `source_excerpt` must match the cited changed line and whose observation must quote that exact source (or `<blank>`) plus causal behavior without ASCII/token-shape heuristics",
    )
    baseline += (
        "\n- **Noema exact-source follow-up (PR #1641):** bounded-diff overlong-line omission markers are not admissible source evidence; "
        "short, symbol-only, blank, and non-ASCII changed lines use exact source equality, while arbitrary source-adjacent words do not satisfy causal evidence.\n"
    )
    BASELINE.write_text(baseline, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    changelog = changelog.replace(
        "class witnesses bind to exact changed-side source text with non-vacuous causal observations",
        "class witnesses bind to exact changed-side source text (including lexical-shape-independent blank/non-ASCII lines) with non-vacuous causal observations, while bounded-diff omission markers are rejected",
    )
    CHANGELOG.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Apply the second exact-head review follow-up."""
    patch_validator()
    patch_corpus_fixture()
    patch_traceability()


if __name__ == "__main__":
    main()
