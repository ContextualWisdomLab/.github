"""A permissive declaration is a claim; the bundled text is the evidence (#2342).

Independent review of `03ba1777` reproduced three prescreen passes that should
have been refusals. `evaluate_dependency_license` allowed the declared SPDX
expression and then only looked for a *denied* title in the bundled text, so
`scan_license_text` returning ``None`` was read as "the text is fine". It is not:
``None`` only says no GPL/LGPL/AGPL title was found.

Counterexamples from that review, all of which returned `passed=True` with an
empty `failures` list while the metadata declared MIT:

* `license_texts` = `{}` — nothing to check the declaration against;
* `LICENSE` = `UNKNOWN`;
* `LICENSE` = `Commercial redistribution is prohibited.`

Recognition is now required, so each fails closed. A separate GPL-titled file
still fails as before, and the permissive paths still pass, so the new check
cannot be satisfied by refusing everything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.ci import release_dependency_gate as gate
from scripts.ci import spdx_license_policy as policy
from tests.test_release_dependency_gate import (
    _python_evidence,
    build_capture,
    REVIEWED_TEXTS,
)

_MIT_TEXT = REVIEWED_TEXTS["pytest-9.1.1.txt"]


def _codes(capture: Path) -> list[str]:
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    return sorted(failure.code for failure in report.failures)


def _licence_stage(tmp_path: Path, **overrides: Any) -> list[str]:
    return _codes(build_capture(tmp_path, python_evidence=_python_evidence(**overrides)))


def test_a_permissive_declaration_with_no_bundled_text_is_refused(tmp_path: Path) -> None:
    """Review counterexample 1: `license_texts = {}` passed with no failures."""
    assert _licence_stage(tmp_path, license_texts={}) == [policy.LICENSE_TEXT_MISSING]


@pytest.mark.parametrize(
    "body",
    [
        "UNKNOWN",
        "Commercial redistribution is prohibited.",
        "",
        "See the project website for terms.",
        "Copyright 2026 Example Inc. All rights reserved.",
    ],
    ids=["unknown", "commercial-prohibited", "empty", "pointer", "all-rights-reserved"],
)
def test_an_unrecognizable_bundled_text_is_refused(tmp_path: Path, body: str) -> None:
    """Review counterexamples 2 and 3, plus the neighbouring unverifiable bodies."""
    assert _licence_stage(tmp_path, license_texts={"LICENSE": body}) == [
        policy.LICENSE_TEXT_UNVERIFIED
    ]


def test_a_recognized_text_that_contradicts_the_declaration_is_refused(
    tmp_path: Path,
) -> None:
    """Apache text under an MIT declaration is a disagreement, not a pass."""
    assert _licence_stage(
        tmp_path,
        license_expression="MIT",
        license_texts={"LICENSE": REVIEWED_TEXTS["atheris-3.1.0.txt"]},
    ) == [gate.LICENSE_TEXT_DISAGREEMENT]


def test_a_denied_title_still_fails_as_a_disagreement(tmp_path: Path) -> None:
    """The pre-existing GPL-title detection is unchanged by the new check."""
    codes = _licence_stage(
        tmp_path,
        license_texts={
            "LICENSE": _MIT_TEXT,
            "COPYING": "GNU GENERAL PUBLIC LICENSE Version 3",
        },
    )
    assert codes == [gate.LICENSE_TEXT_DISAGREEMENT]


def test_matching_declaration_and_text_still_passes(tmp_path: Path) -> None:
    """The positive case: the new requirement is satisfiable by a real license."""
    assert _licence_stage(tmp_path, license_texts={"LICENSE": _MIT_TEXT}) == []


@pytest.mark.parametrize(
    ("expression", "body"),
    [
        ("Apache-2.0", REVIEWED_TEXTS["atheris-3.1.0.txt"]),
        ("BSD-3-Clause", REVIEWED_TEXTS["colorama-0.4.6.txt"]),
        ("ISC", REVIEWED_TEXTS["libloading-0.8.9.txt"]),
        ("Unlicense", REVIEWED_TEXTS["memchr-2.8.3-UNLICENSE.txt"]),
    ],
)
def test_each_recognized_permissive_family_satisfies_its_declaration(
    tmp_path: Path, expression: str, body: str
) -> None:
    """Every family the recognizer knows must clear its own declaration."""
    assert (
        _licence_stage(
            tmp_path, license_expression=expression, license_texts={"LICENSE": body}
        )
        == []
    )


def test_a_dual_licence_selection_is_checked_against_every_declared_identifier(
    tmp_path: Path,
) -> None:
    """The unselected operand still counts as declared, so MIT text disagrees."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(
            license_expression="BSD-3-Clause OR GPL-2.0-only",
            license_texts={"LICENSE": _MIT_TEXT},
        ),
        selections=[
            {
                "ecosystem": "pypi",
                "name": "greenlib",
                "version": "1.0.0",
                "chosen": "BSD-3-Clause",
                "rationale": "BSD-3-Clause selected; GPL option is never exercised",
            }
        ],
    )
    assert _codes(capture) == [gate.LICENSE_TEXT_DISAGREEMENT]


@pytest.mark.parametrize("expression,body", [
    ("MPL-2.0", "Mozilla Public License Version 2.0"),
    ("BSL-1.0", "Boost Software License - Version 1.0"),
])
def test_unsupported_title_only_families_remain_unverified(tmp_path, expression, body):
    """Former positive cases have no reviewed whole text supporting acceptance."""
    assert _licence_stage(tmp_path, license_expression=expression,
                          license_texts={"LICENSE": body}) == [policy.LICENSE_TEXT_UNVERIFIED]


def test_hypothesis_composite_source_is_preserved_but_not_registered():
    """An MPL definition mentioning secondary licenses is not a GPL finding."""
    import hashlib
    import json

    row = json.loads((Path(__file__).parent / "fixtures/release_license_texts/unsupported-hypothesis.json")
                     .read_text(encoding="utf-8"))
    assert hashlib.sha256(row["text"].encode()).hexdigest() == row["raw_sha256"]
    assert policy.recognize_license_text(row["text"]) is None
    # No assertion turns the existing denial scanner's keyword hit into a
    # claim about actual copyleft dependencies or license election.


def test_declared_identifiers_ignores_operators_and_exceptions() -> None:
    """Operators must never be mistaken for identifiers a text could match."""
    assert gate._declared_identifiers("(MIT OR Apache-2.0) AND BSD-3-Clause") == frozenset(
        {"MIT", "Apache-2.0", "BSD-3-Clause"}
    )
    assert gate._declared_identifiers("GPL-2.0-only WITH Classpath-exception-2.0") == frozenset(
        {"GPL-2.0-only", "Classpath-exception-2.0"}
    )


def test_recognize_license_text_is_the_positive_half_of_the_scanner() -> None:
    """`scan_license_text` answers only about denial; recognition is separate."""
    assert policy.scan_license_text("UNKNOWN") is None
    assert policy.recognize_license_text("UNKNOWN") is None
    assert policy.scan_license_text(_MIT_TEXT) is None
    assert "MIT" in (policy.recognize_license_text(_MIT_TEXT) or frozenset())
