#!/usr/bin/env python3
"""Finish PR #1641 by replacing lexical causality guesses with structural evidence roles."""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path("scripts/ci/noema_review_gate.py")
CORPUS_TEST = Path("tests/test_noema_observed_defect_corpus_current_main.py")
OBSERVATION_TEST = Path("tests/test_noema_class_evidence_observation_contract.py")
DOCTOR = Path("docs/doctoring/noema-observed-defect-corpus-current-main.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")
CHANGELOG = Path("CHANGELOG.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one trusted post-round-two anchor or fail closed."""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one source anchor, found {count}")
    return text.replace(old, new, 1)


def patch_validator() -> None:
    """Make source grounding language-neutral and class semantics structurally explicit."""
    text = SOURCE.read_text(encoding="utf-8")

    evidence_anchor = '''OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
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
    evidence_with_roles = evidence_anchor + '''OBSERVED_REVIEW_PROBE_CLAIM_ROLES: dict[str, dict[str, str]] = {
    kind: {field: f"{kind}:{field}" for field in fields}
    for kind, fields in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS.items()
}
'''
    text = replace_once(text, evidence_anchor, evidence_with_roles, "claim-role contract")

    text = replace_once(
        text,
        '''        if not isinstance(source_ref, dict) or set(source_ref) != {
            "path",
            "line",
            "side",
            "source_excerpt",
            "observation",
        }:
''',
        '''        if not isinstance(source_ref, dict) or set(source_ref) != {
            "path",
            "line",
            "side",
            "source_excerpt",
            "claim_role",
            "observation",
        }:
''',
        "witness schema",
    )
    text = replace_once(
        text,
        '''                "path, line, side, exact source_excerpt, and non-empty observation"
''',
        '''                "path, line, side, exact source_excerpt, class-specific claim_role, and non-empty observation"
''',
        "witness schema diagnostic",
    )

    relation_block = '''        source_marker = source_excerpt if source_excerpt else "<blank>"
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
    structural_block = '''        source_marker = source_excerpt if source_excerpt else "<blank>"
        if source_marker not in observation:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} observation "
                "must quote the exact source_excerpt (or <blank> for an empty line)"
            )
        expected_claim_role = OBSERVED_REVIEW_PROBE_CLAIM_ROLES[probe_kind][field]
        claim_role = source_ref.get("claim_role")
        if claim_role != expected_claim_role:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} claim_role "
                f"must be {expected_claim_role!r}"
            )
'''
    text = replace_once(text, relation_block, structural_block, "lexical relation heuristic")

    text = replace_once(
        text,
        '''                                            "source_excerpt": "exact changed-line text",
                                            "observation": (
                                                f"Concrete {field} causal observation naming a token "
                                                "from source_excerpt."
                                            ),
''',
        '''                                            "source_excerpt": "exact changed-line text",
                                            "claim_role": OBSERVED_REVIEW_PROBE_CLAIM_ROLES["mutable_alias"][field],
                                            "observation": (
                                                "Quote the exact source_excerpt (or <blank>) and explain "
                                                f"the behavior for the structured {field} claim role."
                                            ),
''',
        "prompt witness example",
    )

    text = replace_once(
        text,
        '''                "Every class_evidence witness must include path, line, side, source_excerpt, and observation. source_excerpt must be the exact cited changed-side line, including an empty string for a blank line; an overlong-line omission marker is never source evidence. The observation must quote that exact source_excerpt (or <blank>) and state a causal/behavioral relationship; an arbitrary adjacent word or differently worded generic label is not evidence.",
''',
        '''                "Every class_evidence witness must include path, line, side, source_excerpt, claim_role, and observation. source_excerpt must be the exact cited changed-side line, including an empty string for a blank line; an overlong-line omission marker is never source evidence. claim_role is the exact class-and-field role emitted by the schema. The observation must quote that exact source_excerpt (or <blank>) and explain the claimed behavior. The deterministic gate validates source identity and the structural role; it deliberately does not guess causality from an English relation-word list.",
''',
        "prompt language-neutral contract",
    )

    ast.parse(text, filename=str(SOURCE))
    SOURCE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    """Make final regressions exercise structural roles and language-neutral source binding."""
    corpus = CORPUS_TEST.read_text(encoding="utf-8")
    corpus = replace_once(
        corpus,
        '''            "source_excerpt": "new = 1",
            "observation": (
                f"The exact `new = 1` source preserves runtime relationship {index} relevant to {field}."
            ),
''',
        '''            "source_excerpt": "new = 1",
            "claim_role": noema.OBSERVED_REVIEW_PROBE_CLAIM_ROLES[kind][field],
            "observation": (
                f"The exact `new = 1` source is evidence for structured role {index}: {field}."
            ),
''',
        "corpus claim roles",
    )
    corpus = replace_once(
        corpus,
        '''        "source_excerpt": "old = 1",
        "observation": "The exact `old = 1` source is removed before the attempted mutation relationship.",
''',
        '''        "source_excerpt": "old = 1",
        "claim_role": noema.OBSERVED_REVIEW_PROBE_CLAIM_ROLES["mutable_alias"]["mutation_attempt"],
        "observation": "The exact `old = 1` source is evidence for the mutation-attempt role.",
''',
        "wrong-side claim role fixture",
    )
    ast.parse(corpus, filename=str(CORPUS_TEST))
    CORPUS_TEST.write_text(corpus, encoding="utf-8")

    observations = OBSERVATION_TEST.read_text(encoding="utf-8")
    observations = replace_once(
        observations,
        '''        witness = _location()
        if observations:
''',
        '''        witness = _location()
        witness["claim_role"] = noema.OBSERVED_REVIEW_PROBE_CLAIM_ROLES[kind][field]
        if observations:
''',
        "observation claim-role fixture",
    )
    observations = observations.replace(
        'match="concrete token from source_excerpt"',
        'match="quote the exact source_excerpt"',
        1,
    )
    acceptance_anchor = '''def test_distinct_source_bound_class_observations_are_accepted() -> None:
'''
    role_test = '''def test_invented_claim_role_cannot_replace_class_specific_evidence() -> None:
    """Free-form labels cannot substitute for the schema's exact class-and-field role."""
    verdict = _verdict(observations=True, source_excerpt=True)
    verdict["adversarial_validation"]["probes"][0]["class_evidence"]["mutation_attempt"][
        "claim_role"
    ] = "banana"

    with pytest.raises(noema.NoemaModelOutputError, match="claim_role must be"):
        noema.validate_substantive_verdict(verdict, DIFF, ["src/tool.py"])


def test_distinct_source_bound_class_observations_are_accepted() -> None:
'''
    observations = replace_once(observations, acceptance_anchor, role_test, "claim-role regression")
    ast.parse(observations, filename=str(OBSERVATION_TEST))
    OBSERVATION_TEST.write_text(observations, encoding="utf-8")


def patch_traceability() -> None:
    """Document the deterministic/semantic boundary instead of claiming lexical proof."""
    doctor = DOCTOR.read_text(encoding="utf-8")
    doctor += (
        "\nThe exact-head structural follow-up removes the fixed English relation-word list. "
        "Formal evidence now carries a schema-derived `claim_role` for each defect-class witness, "
        "while the deterministic gate verifies exact source identity, canonical coordinates, role identity, "
        "and distinct observations. Semantic causal adequacy remains a reviewer/evaluation responsibility; "
        "the validator does not pretend English keyword presence proves causality.\n"
    )
    DOCTOR.write_text(doctor, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    baseline += (
        "\n- **Noema structural-causality follow-up (PR #1641):** removed fixed English relation-word admission. "
        "Each class witness now carries an exact schema-derived `claim_role` plus exact changed-line source text; "
        "deterministic validation stays language-neutral and semantic causality is tested through reviewer/evaluation regressions rather than guessed from keywords.\n"
    )
    BASELINE.write_text(baseline, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    changelog += (
        "\n- Noema review evidence now uses exact class-and-field claim roles and source excerpts instead of a fixed English causal-word heuristic, preserving non-ASCII and symbol-only review evidence without treating keywords as proof.\n"
    )
    CHANGELOG.write_text(changelog, encoding="utf-8")


def main() -> None:
    """Apply the structural evidence-role repair after the exact-source follow-up."""
    patch_validator()
    patch_tests()
    patch_traceability()


if __name__ == "__main__":
    main()
