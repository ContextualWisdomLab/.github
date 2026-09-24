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
    def bound_names(scope: ast.AST) -> set[str]:
        class Collector(ast.NodeVisitor):
            def __init__(self) -> None:
                self.names: set[str] = set()

            def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                self.names.add(node.name)

            visit_AsyncFunctionDef = visit_FunctionDef
            visit_ClassDef = visit_FunctionDef

            def visit_Name(self, node: ast.Name) -> None:
                if isinstance(node.ctx, (ast.Store, ast.Del)):
                    self.names.add(node.id)

            def visit_arg(self, node: ast.arg) -> None:
                self.names.add(node.arg)

            def visit_Import(self, node: ast.Import) -> None:
                self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                self.names.update(alias.asname or alias.name for alias in node.names)

        collector = Collector()
        collector.visit(scope.args)
        for statement in scope.body:
            collector.visit(statement)
        return collector.names

    class Scanner(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: dict[str, str] = {}
            self.findings: list[tuple[int, str]] = []

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                self.bindings[name] = (
                    "module" if alias.name == "opentelemetry" or alias.name.startswith("opentelemetry.") else "other"
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            otel = node.module == "opentelemetry" or (node.module or "").startswith("opentelemetry.")
            for alias in node.names:
                name = alias.asname or alias.name
                self.bindings[name] = "direct" if otel and alias.name in BOOTSTRAP_NAMES else "module" if otel else "other"

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self.bindings[node.id] = "other"

        def visit_Call(self, node: ast.Call) -> None:
            name = node.func
            if isinstance(name, ast.Name) and self.bindings.get(name.id) == "direct":
                self.findings.append((node.lineno, name.id))
            elif isinstance(name, ast.Attribute) and name.attr in BOOTSTRAP_NAMES:
                root = name.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and self.bindings.get(root.id) == "module":
                    self.findings.append((node.lineno, name.attr))
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            previous = self.bindings
            self.bindings = previous | dict.fromkeys(bound_names(node), "other")
            for statement in node.body:
                self.visit(statement)
            self.bindings = previous
            self.bindings[node.name] = "other"

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            previous = self.bindings
            self.bindings = previous.copy()
            for statement in node.body:
                self.visit(statement)
            self.bindings = previous
            self.bindings[node.name] = "other"

    scanner = Scanner()
    scanner.visit(ast.parse(source))
    return tuple(sorted(scanner.findings))


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
