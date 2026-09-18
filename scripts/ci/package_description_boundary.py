#!/usr/bin/env python3
"""Check what a package's description will look like on the registry page.

A repository README is developer-facing: links to internal design records and
working notes are legitimate there. The same file becomes the package
description on PyPI, npm, or crates.io, where two things change:

* Only the distribution's own files exist. ``docs/``, ``scripts/`` and
  ``examples/`` are normally not shipped, so a repo-relative link that works on
  GitHub is a 404 on the registry page.
* The audience is someone installing the package, not someone developing it.
  Internal go-to-market framing, a hard-coded internal deal value, or a quoted
  module path is implementation and commercial plumbing leaking into a public
  product page.

This reads the *built* description rather than the README on disk: for Python
it parses the sdist's PKG-INFO, which is what PyPI actually renders. Falling
back to the README is allowed only when no distribution is supplied.

Exit status is 1 when a blocking finding is present, so a CI job can gate on it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from email.parser import Parser
from pathlib import Path

# Links a registry page cannot resolve. Absolute URLs, anchors and mailto are fine.
_RELATIVE_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#|mailto:|data:)([^)\s]+)")

# Internal working records. docs/adr is deliberately absent: a public design
# record is legitimate to advertise, it just has to be an absolute URL.
_INTERNAL_DOCS = re.compile(r"docs/(?:superpowers|product|commercial|planning|doctoring)/")

# What these directories hold is not consistent across the organization. The
# central repository files operational incident records under docs/doctoring/;
# pg-llm-batch files operator documentation there ("Bootstrap source
# precedence", "cli-secret-input") that a package user genuinely needs. So the
# directory name alone cannot decide, and this rule advises rather than blocks.
# A link into one of these that is also repo-relative is still caught, and
# blocked, by the relative-link rule, which is the mechanical defect.
#
# An architecture decision record is a public design record wherever it is filed,
# including under docs/planning/adrs/. Only its link has to be absolute.
_ADR_PATH = re.compile(r"/adrs?[/-]", re.IGNORECASE)

# A quoted source path tells the reader which file implements the feature,
# which is plumbing rather than a job they can do.
_SOURCE_PATH = re.compile(
    r"`(?:src|python|scripts|crates|lib|app|internal|pkg)/[\w./{}-]+"
    r"\.(?:py|rs|ts|tsx|js|go|kt|java|rb)`"
)

# A hard-coded internal deal value has no meaning to someone installing a package.
_MONETARY_TARGET = re.compile(r"KRW\s*[\d,]{7,}|\b\d+B KRW\b|\b2,000,000,000\b")

_GTM_VOCAB = re.compile(
    r"commercial readiness|sales.readiness|enterprise sales|buyer (?:packet|evidence|demo|handoff)"
    r"|procurement (?:readiness|evidence)|due.dilig|PR queue governance|ROI evidence|saleability",
    re.IGNORECASE,
)

_REQUIREMENT_MAP = re.compile(r"PRD/TRD|implementation-compliance|requirements? traceability", re.I)


# Mechanical rules block: a relative link is dead, a module path is plumbing, a
# hard-coded deal value is never a product feature. The remaining two need human
# judgement - a product whose domain IS commercial readiness will name its own
# endpoints and tests that way - so they are advisory unless --strict is passed.
_ADVISORY_RULES = frozenset(
    {"go-to-market-vocabulary", "requirement-map", "internal-working-record"}
)


@dataclass
class Finding:
    """One boundary problem in a published package description."""

    rule: str
    detail: str
    blocking: bool = True


@dataclass
class Report:
    """Everything found in one package description."""

    source: str
    characters: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        """Findings that should fail the gate."""
        return [f for f in self.findings if f.blocking]

    def as_dict(self) -> dict[str, object]:
        """Machine-readable form for a CI job summary."""
        return {
            "source": self.source,
            "characters": self.characters,
            "status": "failed" if self.blocking else "ok",
            "findings": [
                {"rule": f.rule, "detail": f.detail, "blocking": f.blocking}
                for f in self.findings
            ],
        }


def description_from_sdist(path: Path) -> str:
    """Return the long description PyPI will render for a Python sdist."""
    with tarfile.open(path, "r:*") as archive:
        members = [m for m in archive.getmembers() if m.name.endswith("PKG-INFO")]
        if not members:
            raise ValueError(f"{path.name} contains no PKG-INFO")
        member = min(members, key=lambda m: m.name.count("/"))
        handle = archive.extractfile(member)
        if handle is None:
            raise ValueError(f"{path.name} PKG-INFO is not a regular file")
        parsed = Parser().parsestr(handle.read().decode("utf-8", "replace"))
    body = parsed.get_payload()
    return body if body.strip() else (parsed.get("Description") or "")


def description_from_wheel(path: Path) -> str:
    """Return the long description recorded in a built wheel's METADATA."""
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if not names:
            raise ValueError(f"{path.name} contains no METADATA")
        parsed = Parser().parsestr(archive.read(names[0]).decode("utf-8", "replace"))
    body = parsed.get_payload()
    return body if body.strip() else (parsed.get("Description") or "")


def load_description(dist: Path | None, readme: Path | None) -> tuple[str, str]:
    """Return ``(description, source label)`` from a distribution or a README."""
    if dist is not None:
        if dist.is_dir():
            candidates = sorted(dist.glob("*.tar.gz")) + sorted(dist.glob("*.whl"))
            if not candidates:
                raise ValueError(f"{dist} holds no sdist or wheel")
            dist = candidates[0]
        if dist.suffix == ".whl":
            return description_from_wheel(dist), dist.name
        return description_from_sdist(dist), dist.name
    if readme is None:
        raise ValueError("pass --dist or --readme")
    return readme.read_text(encoding="utf-8"), readme.name


def inspect(description: str) -> Report:
    """Collect every boundary finding in one description."""
    report = Report(source="", characters=len(description))

    for link in _RELATIVE_LINK.findall(description):
        report.findings.append(
            Finding(
                "relative-link",
                f"{link} does not resolve on a registry page; use an absolute URL",
            )
        )
    for match in _INTERNAL_DOCS.finditer(description):
        line = _line_at(description, match.start())
        if _ADR_PATH.search(description[match.start() : match.start() + 120]):
            continue
        report.findings.append(Finding("internal-working-record", line, blocking=False))
    for match in _SOURCE_PATH.finditer(description):
        report.findings.append(Finding("source-path", match.group(0)))
    for match in _MONETARY_TARGET.finditer(description):
        report.findings.append(Finding("monetary-target", _line_at(description, match.start())))
    for match in _GTM_VOCAB.finditer(description):
        report.findings.append(
            Finding("go-to-market-vocabulary", _line_at(description, match.start()), blocking=False)
        )
    for match in _REQUIREMENT_MAP.finditer(description):
        report.findings.append(
            Finding("requirement-map", _line_at(description, match.start()), blocking=False)
        )
    return report


def _line_at(text: str, index: int) -> str:
    """Return the trimmed source line containing ``index``."""
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start : end if end != -1 else len(text)].strip()[:200]


def build_parser() -> argparse.ArgumentParser:
    """Command-line contract for the boundary gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dist", type=Path, help="built sdist/wheel, or a dist directory")
    source.add_argument("--readme", type=Path, help="README to check when no distribution exists")
    parser.add_argument("--json", type=Path, help="write the machine-readable report here")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        choices=sorted({"relative-link", "internal-working-record", "source-path",
                        "monetary-target", "go-to-market-vocabulary", "requirement-map"}),
        help="report this rule without failing (repeatable)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail on the advisory rules that normally need human judgement",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the gate and return a process exit status."""
    args = build_parser().parse_args(argv)
    try:
        description, source = load_description(args.dist, args.readme)
    except (OSError, ValueError) as error:
        print(f"package description boundary: {error}", file=sys.stderr)
        return 2

    report = inspect(description)
    report.source = source
    for finding in report.findings:
        if args.strict and finding.rule in _ADVISORY_RULES:
            finding.blocking = True
        if finding.rule in args.allow:
            finding.blocking = False

    if args.json:
        args.json.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")

    if not report.findings:
        print(f"package description boundary: {source} is clean ({report.characters} chars)")
        return 0

    for finding in report.findings:
        marker = "FAIL" if finding.blocking else "warn"
        print(f"{marker} [{finding.rule}] {finding.detail}")
    blocking = len(report.blocking)
    print(f"\n{source}: {len(report.findings)} finding(s), {blocking} blocking")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
