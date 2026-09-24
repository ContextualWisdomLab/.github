#!/usr/bin/env python3
"""Report product-owned OpenTelemetry SDK and OTLP bootstrap calls.

This is a canary fitness check. It does not run source files or imply that a
shared runtime dependency has been released.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path


BOOTSTRAP_NAMES = frozenset(
    {
        "OTLPSpanExporter",
        "OTLPMetricExporter",
        "OTLPLogExporter",
        "TracerProvider",
        "MeterProvider",
        "LoggerProvider",
        "BatchSpanProcessor",
        "PeriodicExportingMetricReader",
    }
)
SKIP_DIRS = frozenset({".git", ".venv", "build", "dist", "tests", "docs", "__pycache__"})


def scan_source(source: str) -> tuple[tuple[int, str], ...]:
    """Find calls to SDK bootstrap symbols imported from OpenTelemetry."""
    tree = ast.parse(source)
    imported: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("opentelemetry."):
            imported.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name in BOOTSTRAP_NAMES
            )
            modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name not in BOOTSTRAP_NAMES
            )
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname or alias.name.split(".")[0]
                for alias in node.names
                if alias.name.startswith("opentelemetry.")
            )
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func
        if isinstance(name, ast.Name) and name.id in imported:
            findings.append((node.lineno, name.id))
        elif isinstance(name, ast.Attribute) and name.attr in BOOTSTRAP_NAMES:
            root = name.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in modules:
                findings.append((node.lineno, name.attr))
    return tuple(sorted(findings))


def scan_tree(root: Path) -> tuple[str, ...]:
    """Scan product Python source while excluding tests and generated paths."""
    findings = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if SKIP_DIRS.intersection(relative.parts) or path.is_symlink():
            continue
        for line, name in scan_source(path.read_text(encoding="utf-8")):
            findings.append(f"{relative}:{line}: product-owned {name}()")
    return tuple(sorted(findings))


def main() -> int:
    """Print canary findings and fail when product bootstrap is present."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    if not args.repository.is_dir():
        parser.error("repository must be a directory")
    findings = scan_tree(args.repository)
    print("\n".join(findings) if findings else "No product-owned OTLP bootstrap calls found")
    return bool(findings)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
