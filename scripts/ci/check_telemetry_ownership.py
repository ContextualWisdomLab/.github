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
    other = frozenset({"other"})
    module = frozenset({"module"})
    direct = frozenset({"direct"})

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

            def visit_comprehension_scope(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
                for generator in node.generators:
                    self.visit(generator.iter)
                    for condition in generator.ifs:
                        self.visit(condition)
                if isinstance(node, ast.DictComp):
                    self.visit(node.key)
                    self.visit(node.value)
                else:
                    self.visit(node.elt)

            visit_ListComp = visit_comprehension_scope
            visit_SetComp = visit_comprehension_scope
            visit_DictComp = visit_comprehension_scope
            visit_GeneratorExp = visit_comprehension_scope

        collector = Collector()
        collector.visit(scope.args)
        for statement in scope.body:
            collector.visit(statement)
        return collector.names

    class Scanner(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: dict[str, frozenset[str]] = {}
            self.findings: list[tuple[int, str]] = []
            self.class_outer: dict[str, frozenset[str]] | None = None

        def join(self, branches: list[dict[str, frozenset[str]]]) -> dict[str, frozenset[str]]:
            names = set().union(*(branch.keys() for branch in branches))
            return {name: frozenset().union(*(branch.get(name, other) for branch in branches)) for name in names}

        def run(self, start: dict[str, frozenset[str]], statements: list[ast.stmt]) -> dict[str, frozenset[str]]:
            self.bindings = start.copy()
            for statement in statements:
                self.visit(statement)
            return self.bindings.copy()

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                self.bindings[name] = module if alias.name == "opentelemetry" or alias.name.startswith("opentelemetry.") else other

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            otel = node.module == "opentelemetry" or (node.module or "").startswith("opentelemetry.")
            for alias in node.names:
                name = alias.asname or alias.name
                self.bindings[name] = direct if otel and alias.name in BOOTSTRAP_NAMES else module if otel else other

        def visit_Name(self, node: ast.Name) -> None:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                self.bindings[node.id] = other

        def visit_Assign(self, node: ast.Assign) -> None:
            self.visit(node.value)
            for target in node.targets:
                self.visit(target)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)
            self.visit(node.target)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self.visit(node.value)
            self.visit(node.target)

        def visit_Call(self, node: ast.Call) -> None:
            name = node.func
            if isinstance(name, ast.Name) and "direct" in self.bindings.get(name.id, other):
                self.findings.append((node.lineno, name.id))
            elif isinstance(name, ast.Attribute) and name.attr in BOOTSTRAP_NAMES:
                root = name.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and "module" in self.bindings.get(root.id, other):
                    self.findings.append((node.lineno, name.attr))
            self.generic_visit(node)

        def visit_comprehension_scope(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
            self.visit(node.generators[0].iter)
            previous = self.bindings
            self.bindings = previous.copy()
            for generator in node.generators:
                for name in ast.walk(generator.target):
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                        self.bindings[name.id] = other
            for index, generator in enumerate(node.generators):
                if index:
                    self.visit(generator.iter)
                self.visit(generator.target)
                for condition in generator.ifs:
                    self.visit(condition)
            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
            self.bindings = previous

        visit_ListComp = visit_comprehension_scope
        visit_SetComp = visit_comprehension_scope
        visit_DictComp = visit_comprehension_scope
        visit_GeneratorExp = visit_comprehension_scope

        def visit_If(self, node: ast.If) -> None:
            self.visit(node.test)
            start = self.bindings.copy()
            self.bindings = self.join([self.run(start, node.body), self.run(start, node.orelse)])

        def visit_Try(self, node: ast.Try | ast.TryStar) -> None:
            start = self.bindings.copy()
            prefixes = [start]
            self.bindings = start.copy()
            for statement in node.body:
                self.visit(statement)
                prefixes.append(self.bindings.copy())
            normal = self.run(self.bindings, node.orelse)
            handler_start = self.join(prefixes)
            branches = [normal]
            for handler in node.handlers:
                branches.append(self.run(handler_start, [handler]))
            self.bindings = self.join([self.run(branch, node.finalbody) for branch in branches])

        visit_TryStar = visit_Try

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.type is not None:
                self.visit(node.type)
            if node.name is not None:
                self.bindings[node.name] = other
            for statement in node.body:
                self.visit(statement)

        def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
            self.visit(node.iter)
            start = self.bindings.copy()
            self.bindings = start.copy()
            self.visit(node.target)
            body = self.run(self.bindings, node.body)
            self.bindings = self.run(self.join([start, body]), node.orelse)

        visit_AsyncFor = visit_For

        def visit_While(self, node: ast.While) -> None:
            self.visit(node.test)
            start = self.bindings.copy()
            body = self.run(start, node.body)
            self.bindings = self.run(self.join([start, body]), node.orelse)

        def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)
            previous = self.bindings
            outer_class = self.class_outer
            self.bindings = (outer_class if outer_class is not None else previous) | dict.fromkeys(bound_names(node), other)
            self.class_outer = None
            for statement in node.body:
                self.visit(statement)
            self.bindings = previous
            self.class_outer = outer_class
            self.bindings[node.name] = other

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            previous = self.bindings
            outer_class = self.class_outer
            self.bindings = previous.copy()
            self.class_outer = previous.copy()
            for statement in node.body:
                self.visit(statement)
            self.bindings = previous
            self.class_outer = outer_class
            self.bindings[node.name] = other

    scanner = Scanner()
    scanner.visit(ast.parse(source))
    return tuple(sorted(set(scanner.findings)))


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
