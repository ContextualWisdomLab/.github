"""SPDX expression parsing and release license policy (issue #2342).

Substring matching cannot distinguish ``AGPL-3.0-only`` from ``Apache-2.0`` or
``MIT OR GPL-2.0-only`` from ``MIT AND GPL-2.0-only``; these tests pin the
parsed-expression behaviour the central pre-publish gate depends on.
"""

from __future__ import annotations

import pytest

from scripts.ci import spdx_license_policy as policy


def test_parses_and_renders_nested_operators() -> None:
    """AND/OR/WITH and parentheses round-trip through the operator tree."""
    node = policy.parse_license_expression("(MIT OR Apache-2.0) AND BSD-3-Clause")
    assert isinstance(node, policy.Conjunction)
    assert policy.render_expression(node) == "(MIT OR Apache-2.0) AND BSD-3-Clause"

    exception = policy.parse_license_expression("Apache-2.0 WITH LLVM-exception")
    assert isinstance(exception, policy.WithException)
    assert policy.render_expression(exception) == "Apache-2.0 WITH LLVM-exception"

    or_later = policy.parse_license_expression("Apache-2.0+")
    assert or_later == policy.LicenseId("Apache-2.0", True)
    assert policy.render_expression(or_later) == "Apache-2.0+"


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "MIT AND",
        "AND MIT",
        "(MIT",
        "MIT)",
        ")",
        "(MIT MIT)",
        "MIT Apache-2.0",
        "(MIT OR Apache-2.0) WITH LLVM-exception",
        "Apache-2.0 WITH (MIT)",
        "MIT AND $$$",
        "+",
    ],
)
def test_malformed_expressions_do_not_parse(expression: str) -> None:
    """Every unparseable expression raises rather than silently degrading."""
    with pytest.raises(policy.SpdxParseError):
        policy.parse_license_expression(expression)


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        ("GPL-2.0-only", policy.LICENSE_DENIED_GPL),
        ("GPL-3.0-or-later", policy.LICENSE_DENIED_GPL),
        ("GPL-2.0+", policy.LICENSE_DENIED_GPL),
        ("gpl-3.0", policy.LICENSE_DENIED_GPL),
        ("LGPL-2.1-only", policy.LICENSE_DENIED_LGPL),
        ("LGPL-3.0-or-later", policy.LICENSE_DENIED_LGPL),
        ("AGPL-3.0-only", policy.LICENSE_DENIED_AGPL),
        ("AGPL-3.0-or-later", policy.LICENSE_DENIED_AGPL),
        ("GPL-2.0-only WITH Classpath-exception-2.0", policy.LICENSE_DENIED_GPL),
        ("MIT AND LGPL-3.0-only", policy.LICENSE_DENIED_LGPL),
    ],
)
def test_copyleft_families_are_denied_in_every_spelling(expression: str, code: str) -> None:
    """GPL, LGPL, and AGPL are denied in every version and both -only/-or-later forms."""
    decision = policy.evaluate_license_expression(expression)
    assert (decision.allowed, decision.code) == (False, code)


@pytest.mark.parametrize(
    "expression", ["MIT", "Apache-2.0", "BSD-3-Clause", "MIT AND Apache-2.0"]
)
def test_permissive_expressions_are_allowed(expression: str) -> None:
    """Permissive identifiers and conjunctions of them pass."""
    decision = policy.evaluate_license_expression(expression)
    assert decision.allowed
    assert decision.selected == expression


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (None, policy.LICENSE_MISSING),
        ("", policy.LICENSE_MISSING),
        ("NOASSERTION", policy.LICENSE_UNRECOGNIZED),
        ("NONE", policy.LICENSE_UNRECOGNIZED),
        ("UNKNOWN", policy.LICENSE_UNRECOGNIZED),
        ("custom", policy.LICENSE_UNRECOGNIZED),
        ("LicenseRef-Proprietary", policy.LICENSE_UNRECOGNIZED),
        ("MIT AND", policy.LICENSE_UNPARSEABLE),
        ("Apache-2.0 WITH Unknown-exception", policy.LICENSE_UNRECOGNIZED),
    ],
)
def test_missing_unknown_and_unparseable_declarations_fail(value: str | None, code: str) -> None:
    """A gate cannot pass what it could not read: every such case fails closed."""
    decision = policy.evaluate_license_expression(value)
    assert (decision.allowed, decision.code) == (False, code)


def test_allowed_exception_on_permissive_base_passes() -> None:
    """A recognized exception qualifying an allowed license stays allowed."""
    decision = policy.evaluate_license_expression("Apache-2.0 WITH LLVM-exception")
    assert decision.allowed
    assert decision.selected == "Apache-2.0 WITH LLVM-exception"


def test_dual_license_requires_an_explicit_selection() -> None:
    """OR never passes on its own, however permissive an operand may be."""
    decision = policy.evaluate_license_expression("MIT OR GPL-2.0-only")
    assert (decision.allowed, decision.code) == (False, policy.LICENSE_SELECTION_REQUIRED)


def test_dual_license_selection_records_its_rationale() -> None:
    """A selected non-GPL operand passes and carries the rationale into provenance."""
    decision = policy.evaluate_license_expression(
        "MIT OR GPL-2.0-only", selection="MIT", rationale="MIT chosen for commercial reuse"
    )
    assert decision.allowed
    assert decision.selected == "MIT"
    assert decision.rationale == "MIT chosen for commercial reuse"


def test_dual_license_selection_needs_a_rationale() -> None:
    """A selection without a written rationale is not a selection."""
    decision = policy.evaluate_license_expression("MIT OR GPL-2.0-only", selection="MIT")
    assert (decision.allowed, decision.code) == (False, policy.LICENSE_SELECTION_INVALID)


def test_selection_must_name_an_operand_of_the_expression() -> None:
    """A selection naming a license the dependency never offered is rejected."""
    decision = policy.evaluate_license_expression(
        "GPL-2.0-only OR AGPL-3.0-only", selection="MIT", rationale="wishful thinking"
    )
    assert (decision.allowed, decision.code) == (False, policy.LICENSE_SELECTION_INVALID)


def test_selecting_a_denied_operand_still_fails() -> None:
    """Selecting the copyleft half of a dual license does not launder it."""
    decision = policy.evaluate_license_expression(
        "MIT OR GPL-2.0-only", selection="GPL-2.0-only", rationale="explicitly chosen"
    )
    assert (decision.allowed, decision.code) == (False, policy.LICENSE_DENIED_GPL)


def test_conjunction_of_selected_disjunction_is_allowed() -> None:
    """A selection resolves an OR nested inside an AND."""
    decision = policy.evaluate_license_expression(
        "(MIT OR GPL-2.0-only) AND Apache-2.0",
        selection="MIT",
        rationale="MIT chosen for commercial reuse",
    )
    assert decision.allowed


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3", policy.LICENSE_DENIED_AGPL),
        ("GNU LESSER GENERAL PUBLIC LICENSE", policy.LICENSE_DENIED_LGPL),
        ("GNU LIBRARY GENERAL PUBLIC LICENSE", policy.LICENSE_DENIED_LGPL),
        ("gnu general public license", policy.LICENSE_DENIED_GPL),
    ],
)
def test_bundled_license_text_is_scanned_for_copyleft(text: str, code: str) -> None:
    """Bundled license *text* is matched by substring; that is correct for prose."""
    assert policy.scan_license_text(text) == code


def test_permissive_license_text_is_not_flagged() -> None:
    """MIT license text carries no copyleft marker."""
    assert policy.scan_license_text("MIT License\n\nPermission is hereby granted") is None


def test_classifier_fallback_maps_to_spdx() -> None:
    """Trove classifiers become an SPDX expression when no declaration exists."""
    assert policy.spdx_from_classifiers(["License :: OSI Approved :: MIT License"]) == "MIT"
    assert policy.spdx_from_classifiers(["Topic :: Utilities"]) is None
    assert (
        policy.spdx_from_classifiers(
            [
                "License :: OSI Approved :: MIT License",
                "License :: OSI Approved :: Apache Software License",
            ]
        )
        == "Apache-2.0 OR MIT"
    )


def test_unknown_identifier_is_not_silently_allowed() -> None:
    """An identifier outside the allowlist fails rather than passing as unknown."""
    decision = policy.classify_identifier("Elastic-2.0")
    assert (decision.allowed, decision.code) == (False, policy.LICENSE_UNRECOGNIZED)
