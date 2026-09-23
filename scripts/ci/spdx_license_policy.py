#!/usr/bin/env python3
"""Parse SPDX license expressions and decide the organization's release policy.

Issue #2342: the central pre-publish dependency gate must deny GPL, LGPL, and
AGPL in *every* version and in both the ``-only`` and ``-or-later`` spellings,
and it must reach that verdict by **parsing** the declared SPDX expression
rather than by substring matching. ``MIT OR GPL-2.0-only`` and
``GPL-2.0-only WITH Classpath-exception-2.0`` are different facts, and a
substring scan for ``GPL`` cannot tell them apart from ``AGPL-3.0-only`` or
from the perfectly permissive ``Apache-2.0``.

The grammar implemented here is SPDX 2.3 Annex D, restricted to what a
dependency declaration can legally contain::

    expression   := or-expression
    or-expression  := and-expression ( "OR" and-expression )*
    and-expression := with-expression ( "AND" with-expression )*
    with-expression := simple ( "WITH" idstring )?
    simple       := idstring [ "+" ] | "(" expression ")"

Policy, applied to the parsed tree and never to raw text:

* every leaf in the GPL family (``GPL``/``LGPL``/``AGPL``, any version, any
  suffix, with or without an exception) is denied;
* every remaining leaf must appear in :data:`ALLOWED_LICENSE_IDENTIFIERS`;
  ``LicenseRef-*``, ``NOASSERTION``, ``NONE``, ``UNKNOWN``, ``custom`` and any
  other unrecognized identifier therefore fail closed rather than passing as an
  unknown-but-probably-fine license;
* ``AND`` propagates the first non-allowed operand, because a conjunction
  imposes *every* operand's obligations;
* ``OR`` never passes on its own. A dual-licensed dependency passes only when
  the caller explicitly selects one non-denied operand and supplies a
  rationale, which the gate copies into the artifact provenance.

Substring matching *is* correct for bundled license **text**
(:func:`scan_license_text`): a file containing "GNU GENERAL PUBLIC LICENSE" is
GPL-licensed regardless of what the metadata claims.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Union

#: Stable, machine-checkable failure codes. Callers assert on these, never on prose.
LICENSE_DENIED_GPL = "LICENSE_DENIED_GPL"
LICENSE_DENIED_LGPL = "LICENSE_DENIED_LGPL"
LICENSE_DENIED_AGPL = "LICENSE_DENIED_AGPL"
LICENSE_UNPARSEABLE = "LICENSE_UNPARSEABLE"
LICENSE_UNRECOGNIZED = "LICENSE_UNRECOGNIZED"
LICENSE_MISSING = "LICENSE_MISSING"
LICENSE_SELECTION_REQUIRED = "LICENSE_SELECTION_REQUIRED"
LICENSE_SELECTION_INVALID = "LICENSE_SELECTION_INVALID"
LICENSE_TEXT_MISSING = "LICENSE_TEXT_MISSING"
LICENSE_TEXT_UNVERIFIED = "LICENSE_TEXT_UNVERIFIED"

_IDSTRING_RE = re.compile(r"[A-Za-z0-9.\-+]+")
_VALID_IDSTRING_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_GPL_FAMILY_RE = re.compile(r"^(AGPL|LGPL|GPL)(?:[-.].*)?$", re.IGNORECASE)
_GPL_FAMILY_CODES = {
    "AGPL": LICENSE_DENIED_AGPL,
    "LGPL": LICENSE_DENIED_LGPL,
    "GPL": LICENSE_DENIED_GPL,
}

#: Identifiers the organization accepts for a commercially redistributable release.
ALLOWED_LICENSE_IDENTIFIERS: frozenset[str] = frozenset(
    {
        "0BSD",
        "Apache-1.1",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSD-3-Clause-Clear",
        "BSL-1.0",
        "CC0-1.0",
        "ISC",
        "MIT",
        "MIT-0",
        "MPL-2.0",
        "NCSA",
        "PSF-2.0",
        "PostgreSQL",
        "Python-2.0",
        "Python-2.0.1",
        "Unicode-3.0",
        "Unlicense",
        "Zlib",
    }
)

#: Exceptions that may qualify an already-allowed license identifier.
ALLOWED_LICENSE_EXCEPTIONS: frozenset[str] = frozenset(
    {"LLVM-exception", "Classpath-exception-2.0"}
)

#: Bundled-text markers, longest/most specific family first.
_LICENSE_TEXT_MARKERS: tuple[tuple[str, str], ...] = (
    ("GNU AFFERO GENERAL PUBLIC LICENSE", LICENSE_DENIED_AGPL),
    ("GNU LESSER GENERAL PUBLIC LICENSE", LICENSE_DENIED_LGPL),
    ("GNU LIBRARY GENERAL PUBLIC LICENSE", LICENSE_DENIED_LGPL),
    ("GNU GENERAL PUBLIC LICENSE", LICENSE_DENIED_GPL),
)

#: Deliberately bounded evidence registry, NOT general SPDX text coverage.
#: Source: repository LICENSE at 48caafec7160dd0cb9bafc58b28a884dc4c35cbb;
#: raw SHA256 08f1fd81fb120bc468b69dc3e58ea0dc23c216305c766e45e107f56c76559e3f.
#: Digest covers the ENTIRE text after ASCII layout-whitespace normalization.
#: Additional complete artifact texts and provenance are pinned in
#: tests/fixtures/release_license_texts/provenance.json. Every copyright/header
#: is part of its exact digest. These are text recognitions, not whole-package
#: approvals: missing declarations, other files and incomplete scope still HOLD.
#: Any other text remains UNKNOWN, including unreviewed copyright variants.
_VERIFIED_LICENSE_TEXT_DIGESTS: dict[str, frozenset[str]] = {
    "f5ac0308cf2b3f96a0f49a8c0c9e4a2a02c483afc72a646af8de1f356983de06": frozenset({"MIT"}),
    "25480d7a337b885c258cc7e7299af35c39a2d2e5e8ead3970a26b0e1a3cd2a3e": frozenset({"MIT"}),
    "0ffddef9e48f8a09aed5caf2d44f7ba1c1be2d9b8e0a6f693b1635b2d5566645": frozenset({"Apache-2.0"}),
    "a66ace7bb1d24a3290b823ae25fcd5f95fc5a3dd5af95c45dd77dc37ee593bcd": frozenset({"BSD-2-Clause"}),
    "9384ef020bec4dca54f36ac8b293a41d0ff2ec0df4140b649d90edaa7bc242a5": frozenset({"BSD-3-Clause"}),
    "121aea2578cd98e64faa0ca32acfd4f83551b1ecd293730a9541a4f5a37bf85c": frozenset({"ISC"}),
    "3a31f72fe7c9baf376c3da1d7d0154366be8ef0bab0a3f7531db4c2abf1ad062": frozenset({"Zlib"}),
    "2069c208cba553e43cd0b730df8a0c10bf1b1101b96f661e2f1307c73b9722e3": frozenset({"Unlicense"}),
}

#: Trove classifier to SPDX identifier, used when no PEP 639 expression exists.
CLASSIFIER_TO_SPDX: dict[str, str] = {
    "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-3-Clause",
    "License :: OSI Approved :: Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": (
        "LGPL-3.0-only"
    ),
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: Zlib/libpng License": "Zlib",
}


class SpdxParseError(ValueError):
    """Raised when a declared license expression is not valid SPDX."""


@dataclass(frozen=True)
class LicenseId:
    """One SPDX license identifier, optionally carrying the legacy ``+`` suffix."""

    identifier: str
    or_later: bool = False


@dataclass(frozen=True)
class WithException:
    """A license identifier qualified by an SPDX license exception."""

    license: LicenseId
    exception: str


@dataclass(frozen=True)
class Conjunction:
    """An SPDX ``AND`` node; every operand's obligations apply simultaneously."""

    operands: tuple["Node", ...]


@dataclass(frozen=True)
class Disjunction:
    """An SPDX ``OR`` node; the licensee chooses exactly one operand."""

    operands: tuple["Node", ...]


Node = Union[LicenseId, WithException, Conjunction, Disjunction]


@dataclass(frozen=True)
class LicenseDecision:
    """Fail-closed policy verdict for one declared license expression."""

    allowed: bool
    code: str
    detail: str
    selected: str | None = None
    rationale: str | None = None


def _tokenize(text: str) -> list[str]:
    """Split an SPDX expression into identifier, operator, and parenthesis tokens."""

    tokens: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if character in "()":
            tokens.append(character)
            index += 1
            continue
        match = _IDSTRING_RE.match(text, index)
        if match is None:
            raise SpdxParseError(f"unexpected character {character!r} in license expression")
        tokens.append(match.group(0))
        index = match.end()
    return tokens


class _Parser:
    """Recursive-descent parser over a tokenized SPDX license expression."""

    def __init__(self, tokens: list[str]) -> None:
        """Store the token stream and start at its first token."""
        self._tokens = tokens
        self._position = 0

    def _peek(self) -> str | None:
        """Return the current token without consuming it."""
        if self._position >= len(self._tokens):
            return None
        return self._tokens[self._position]

    def _next(self) -> str:
        """Consume and return the current token, failing on a truncated expression."""
        token = self._peek()
        if token is None:
            raise SpdxParseError("license expression ended unexpectedly")
        self._position += 1
        return token

    def parse(self) -> Node:
        """Parse a complete expression and reject trailing tokens."""
        node = self._parse_or()
        if self._peek() is not None:
            raise SpdxParseError(f"unexpected trailing token {self._peek()!r}")
        return node

    def _parse_or(self) -> Node:
        """Parse an ``OR`` chain."""
        operands = [self._parse_and()]
        while (token := self._peek()) is not None and token.upper() == "OR":
            self._next()
            operands.append(self._parse_and())
        if len(operands) == 1:
            return operands[0]
        return Disjunction(tuple(operands))

    def _parse_and(self) -> Node:
        """Parse an ``AND`` chain."""
        operands = [self._parse_with()]
        while (token := self._peek()) is not None and token.upper() == "AND":
            self._next()
            operands.append(self._parse_with())
        if len(operands) == 1:
            return operands[0]
        return Conjunction(tuple(operands))

    def _parse_with(self) -> Node:
        """Parse one simple term and an optional ``WITH`` exception."""
        node = self._parse_simple()
        token = self._peek()
        if token is not None and token.upper() == "WITH":
            self._next()
            exception = self._next()
            if not isinstance(node, LicenseId):
                raise SpdxParseError("WITH must qualify a single license identifier")
            if not _VALID_IDSTRING_RE.match(exception):
                raise SpdxParseError(f"invalid license exception {exception!r}")
            return WithException(node, exception)
        return node

    def _parse_simple(self) -> Node:
        """Parse a parenthesized expression or a single license identifier."""
        token = self._next()
        if token == "(":
            node = self._parse_or()
            closing = self._next()
            if closing != ")":
                raise SpdxParseError("unbalanced parenthesis in license expression")
            return node
        if token == ")":
            raise SpdxParseError("unbalanced parenthesis in license expression")
        if token.upper() in {"AND", "OR", "WITH"}:
            raise SpdxParseError(f"operator {token!r} used where a license was expected")
        or_later = token.endswith("+")
        identifier = token[:-1] if or_later else token
        if not identifier or not _VALID_IDSTRING_RE.match(identifier):
            raise SpdxParseError(f"invalid license identifier {token!r}")
        return LicenseId(identifier, or_later)


def parse_license_expression(text: str) -> Node:
    """Parse an SPDX license expression into its operator tree."""

    if not isinstance(text, str) or not text.strip():
        raise SpdxParseError("license expression is empty")
    tokens = _tokenize(text)
    if not tokens:  # pragma: no cover - a non-blank string always yields a token
        raise SpdxParseError("license expression is empty")
    return _Parser(tokens).parse()


def render_expression(node: Node) -> str:
    """Render a parsed node back to canonical SPDX text for provenance records."""

    if isinstance(node, LicenseId):
        return node.identifier + ("+" if node.or_later else "")
    if isinstance(node, WithException):
        return f"{render_expression(node.license)} WITH {node.exception}"
    if isinstance(node, Conjunction):
        return " AND ".join(_render_operand(item) for item in node.operands)
    return " OR ".join(_render_operand(item) for item in node.operands)


def _render_operand(node: Node) -> str:
    """Render one operand, parenthesizing nested compound nodes."""

    rendered = render_expression(node)
    if isinstance(node, (Conjunction, Disjunction)):
        return f"({rendered})"
    return rendered


def classify_identifier(identifier: str) -> LicenseDecision:
    """Decide policy for a single SPDX license identifier."""

    family = _GPL_FAMILY_RE.match(identifier)
    if family is not None:
        code = _GPL_FAMILY_CODES[family.group(1).upper()]
        return LicenseDecision(
            allowed=False,
            code=code,
            detail=f"{identifier} is in the denied copyleft family",
        )
    if identifier in ALLOWED_LICENSE_IDENTIFIERS:
        return LicenseDecision(
            allowed=True,
            code="LICENSE_ALLOWED",
            detail=f"{identifier} is an allowed commercially usable license",
            selected=identifier,
        )
    return LicenseDecision(
        allowed=False,
        code=LICENSE_UNRECOGNIZED,
        detail=(
            f"{identifier} is not an allowed identifier; unknown, custom, and "
            "LicenseRef licenses fail closed"
        ),
    )


def _evaluate_node(node: Node, selections: frozenset[str]) -> LicenseDecision:
    """Evaluate one parsed node against the policy and the caller's selections."""

    if isinstance(node, LicenseId):
        return classify_identifier(node.identifier)
    if isinstance(node, WithException):
        base = classify_identifier(node.license.identifier)
        if not base.allowed:
            return base
        if node.exception not in ALLOWED_LICENSE_EXCEPTIONS:
            return LicenseDecision(
                allowed=False,
                code=LICENSE_UNRECOGNIZED,
                detail=f"license exception {node.exception} is not recognized",
            )
        return LicenseDecision(
            allowed=True,
            code="LICENSE_ALLOWED",
            detail=f"{render_expression(node)} is allowed",
            selected=render_expression(node),
        )
    if isinstance(node, Conjunction):
        for operand in node.operands:
            decision = _evaluate_node(operand, selections)
            if not decision.allowed:
                return decision
        return LicenseDecision(
            allowed=True,
            code="LICENSE_ALLOWED",
            detail=f"every operand of {render_expression(node)} is allowed",
            selected=render_expression(node),
        )

    rendered_operands = [render_expression(operand) for operand in node.operands]
    if not selections:
        return LicenseDecision(
            allowed=False,
            code=LICENSE_SELECTION_REQUIRED,
            detail=(
                f"dual-licensed expression {render_expression(node)} requires an "
                "explicit selection with a recorded rationale"
            ),
        )
    for operand, rendered in zip(node.operands, rendered_operands):
        if rendered not in selections:
            continue
        decision = _evaluate_node(operand, selections)
        if decision.allowed:
            return LicenseDecision(
                allowed=True,
                code="LICENSE_ALLOWED",
                detail=f"selected {rendered} from {render_expression(node)}",
                selected=rendered,
            )
        return LicenseDecision(
            allowed=False,
            code=decision.code,
            detail=f"selected operand {rendered} is not usable: {decision.detail}",
        )
    return LicenseDecision(
        allowed=False,
        code=LICENSE_SELECTION_INVALID,
        detail=(
            f"selection does not name any operand of {render_expression(node)}; "
            f"operands are {sorted(rendered_operands)}"
        ),
    )


def evaluate_license_expression(
    text: str | None,
    *,
    selection: str | None = None,
    rationale: str | None = None,
) -> LicenseDecision:
    """Return the fail-closed policy decision for one declared license expression."""

    if text is None or not str(text).strip():
        return LicenseDecision(
            allowed=False,
            code=LICENSE_MISSING,
            detail="no license expression was declared",
        )
    normalized = str(text).strip()
    if normalized.upper() in {"NOASSERTION", "NONE", "UNKNOWN", "CUSTOM"}:
        return LicenseDecision(
            allowed=False,
            code=LICENSE_UNRECOGNIZED,
            detail=f"{normalized} is not a usable license declaration",
        )
    try:
        node = parse_license_expression(normalized)
    except SpdxParseError as error:
        return LicenseDecision(
            allowed=False,
            code=LICENSE_UNPARSEABLE,
            detail=f"{normalized!r} is not a valid SPDX expression: {error}",
        )
    selections: frozenset[str] = frozenset()
    if selection is not None and selection.strip():
        if rationale is None or not rationale.strip():
            return LicenseDecision(
                allowed=False,
                code=LICENSE_SELECTION_INVALID,
                detail="a license selection requires a written rationale",
            )
        selections = frozenset({selection.strip()})
    decision = _evaluate_node(node, selections)
    if decision.allowed and selections:
        return LicenseDecision(
            allowed=True,
            code=decision.code,
            detail=decision.detail,
            selected=decision.selected,
            rationale=rationale,
        )
    return decision


def scan_license_text(text: str) -> str | None:
    """Return a denial code when bundled license text is GPL, LGPL, or AGPL."""

    upper = text.upper()
    for marker, code in _LICENSE_TEXT_MARKERS:
        if marker in upper:
            return code
    return None


def recognize_license_text(text: str) -> frozenset[str] | None:
    """Return identifiers for a reviewed whole text, or None for unknown text.

    This bounded registry does not infer license terms from SPDX declarations,
    titles or permission fragments. Unsupported legitimate texts also remain
    unverified; adding a license requires new whole-source evidence and tests.
    """

    # Full-text evidence, not a title/phrase classifier. Only ASCII layout
    # whitespace is folded: no case folding, Unicode/control deletion, copyright
    # stripping, prefix/suffix removal, or arbitrary header allowance. An extra
    # condition anywhere therefore changes the digest and remains unverified.
    normalized = re.sub(r"[ \t\r\n]+", " ", text).strip(" \t\r\n")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return _VERIFIED_LICENSE_TEXT_DIGESTS.get(digest)


def spdx_from_classifiers(classifiers: list[str]) -> str | None:
    """Return an SPDX expression derived from PyPI trove classifiers, if any."""

    identifiers = [
        CLASSIFIER_TO_SPDX[classifier]
        for classifier in classifiers
        if classifier in CLASSIFIER_TO_SPDX
    ]
    if not identifiers:
        return None
    unique = sorted(set(identifiers))
    if len(unique) == 1:
        return unique[0]
    return " OR ".join(unique)
