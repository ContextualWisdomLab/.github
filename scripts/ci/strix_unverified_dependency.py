#!/usr/bin/env python3
"""Classify a Strix finding about a package the repository does not depend on.

A model can report a CVE in a dependency the scanned repository never uses
(fast-mlsirm#2246: "CVE-2024-1234 in lodash 4.17.20" on a Rust/Python tree).
Such a finding has no file location, so the gate would fail closed as
unmapped. This helper lets the gate record it as unverified instead, but only
when every package the report names is absent from every dependency manifest
and lockfile in the repository. Reports that name no package are never
affected.

Usage: strix_unverified_dependency.py REPORT REPO_ROOT
Exit 0 when the finding is unverified, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MANIFEST_NAMES = frozenset({
    "Cargo.toml", "Cargo.lock", "pyproject.toml", "uv.lock", "poetry.lock", "Pipfile", "Pipfile.lock",
    "setup.cfg", "setup.py", "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
    "pnpm-lock.yaml", "go.mod", "go.sum", "Gemfile", "Gemfile.lock", "composer.json", "composer.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "packages.lock.json", "renv.lock", "DESCRIPTION",
})
SKIP_DIRS = frozenset({".git", "node_modules", "target", ".venv", "venv", "__pycache__", "vendor"})
MAX_MANIFEST_BYTES = 8 * 1024 * 1024

# A package is a bare name or an npm scope (``@scope/name``); anything with a
# path separator otherwise is a file, not a package.
_PACKAGE = r"(@[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*|[A-Za-z0-9][A-Za-z0-9_.-]*)"
_VERSION = r"v?\d+(?:\.\d+)+[A-Za-z0-9.+-]*"
# Report files use "**Target:** x"; the console log boxes the same fields as
# "│  Target: x   │".
_FIELD = r"^[ \t]*│?[ \t]*(?:\*\*)?{name}:(?:\*\*)?[ \t]*"
_END = r"[ \t]*│?[ \t]*$"
# Only Strix's structured dependency fields name packages; free text such as
# "weak TLS in openssl 1.1.1" never does.
FIELD_RES = (
    re.compile(_FIELD.format(name="Target") + rf"{_PACKAGE}(?:@|[ \t]+){_VERSION}{_END}", re.MULTILINE),
    re.compile(_FIELD.format(name="Package") + rf"{_PACKAGE}(?:(?:@|[ \t]+){_VERSION})?{_END}", re.MULTILINE),
    re.compile(_FIELD.format(name="Introduced By") + rf"{_PACKAGE}@{_VERSION}{_END}", re.MULTILINE),
)


def named_packages(report: str) -> set[str]:
    """Return lower-cased package names from the report's dependency fields."""
    return {m.group(1).lower() for regex in FIELD_RES for m in regex.finditer(report)}


def _is_requirements(name: str) -> bool:
    """Return whether a filename is a supported pip requirements manifest."""
    return name.startswith("requirements") and name.endswith((".txt", ".in"))


def _manifest_text(repo_root: Path) -> str:
    """Collect bounded dependency-manifest text beneath the repository root."""
    chunks = []
    for path in repo_root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(repo_root).parts[:-1]):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        if path.name not in MANIFEST_NAMES and not _is_requirements(path.name):
            continue
        if path.stat().st_size <= MAX_MANIFEST_BYTES:
            chunks.append(path.read_text(encoding="utf-8", errors="replace").lower())
    return "\n".join(chunks)


def unverified_dependency_finding(report: str, repo_root: Path) -> bool:
    """True when the report names packages and none appears in any manifest.

    Matching is deliberately loose (``node_modules/lodash`` counts), so doubt
    keeps the finding.
    """
    packages = named_packages(report)
    if not packages:
        return False
    manifests = _manifest_text(repo_root)
    return not any(re.search(rf"(?<![a-z0-9_-]){re.escape(p)}(?![a-z0-9_-])", manifests) for p in packages)


def main(argv: list[str]) -> int:
    """Return success only for a finding absent from all dependency manifests."""
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    report = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    if unverified_dependency_finding(report, Path(argv[2])):
        names = ", ".join(sorted(named_packages(report)))
        print(f"::warning::Strix finding names package(s) {names} absent from every dependency manifest and "
              "lockfile; recording it as unverified instead of failing closed.", file=sys.stderr)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
