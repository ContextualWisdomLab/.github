#!/usr/bin/env python3
"""Detect executable Python placeholder implementations in changed runtime code."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


RUNTIME_TEST_PARTS = {
    "test",
    "tests",
    "testing",
    "fixture",
    "fixtures",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    symbol: str
    reason: str


class ClassContext:
    def __init__(self, name: str, is_protocol_or_abc: bool) -> None:
        self.name = name
        self.is_protocol_or_abc = is_protocol_or_abc


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return ""


def is_protocol_or_abc_base(node: ast.AST) -> bool:
    name = dotted_name(node)
    return name in {"Protocol", "typing.Protocol", "ABC", "abc.ABC"}


def is_abstract_or_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        name = dotted_name(decorator)
        if name.endswith(".abstractmethod") or name == "abstractmethod":
            return True
        if name.endswith(".overload") or name == "overload":
            return True
    return False


def strip_docstring(
    body: list[ast.stmt],
) -> list[ast.stmt]:
    if not body:
        return body
    first = body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return body[1:]
    return body


def placeholder_reason(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    body = strip_docstring(node.body)
    if len(body) != 1:
        return None
    only = body[0]
    if isinstance(only, ast.Pass):
        return "pass-only body"
    if (
        isinstance(only, ast.Expr)
        and isinstance(only.value, ast.Constant)
        and only.value.value is Ellipsis
    ):
        return "ellipsis-only body"
    if isinstance(only, ast.Raise) and only.exc is not None:
        exc_name = dotted_name(only.exc)
        if exc_name == "NotImplementedError":
            return "raises NotImplementedError"
    return None


class PlaceholderVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.class_stack: list[ClassContext] = []
        self.findings: list[Finding] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        is_protocol_or_abc = any(is_protocol_or_abc_base(base) for base in node.bases)
        self.class_stack.append(ClassContext(node.name, is_protocol_or_abc))
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if any(context.is_protocol_or_abc for context in self.class_stack):
            return
        if is_abstract_or_overload(node):
            return
        reason = placeholder_reason(node)
        if reason is not None:
            symbol_parts = [context.name for context in self.class_stack] + [node.name]
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    symbol=".".join(symbol_parts),
                    reason=reason,
                )
            )
        self.generic_visit(node)


def is_runtime_python_path(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    return not any(part in RUNTIME_TEST_PARTS for part in path.parts)


def changed_paths_from_file(path: Path) -> list[Path]:
    if not path.exists():
        return []
    changed_paths: list[Path] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        clean_line = line.strip().lstrip("\ufeff")
        if clean_line and not clean_line.startswith("/"):
            changed_paths.append(Path(clean_line))
    return changed_paths


def scan_python_file(repo_root: Path, relative_path: Path) -> list[Finding]:
    source_path = repo_root / relative_path
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(relative_path))
    visitor = PlaceholderVisitor(relative_path.as_posix())
    visitor.visit(tree)
    return visitor.findings


def scan_changed_paths(
    repo_root: Path, changed_paths: Iterable[Path]
) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    errors: list[str] = []
    seen: set[str] = set()
    for relative_path in changed_paths:
        key = relative_path.as_posix()
        if key in seen or not is_runtime_python_path(relative_path):
            continue
        seen.add(key)
        source_path = repo_root / relative_path
        if not source_path.is_file():
            continue
        try:
            findings.extend(scan_python_file(repo_root, relative_path))
        except SyntaxError as exc:
            line = exc.lineno or 1
            errors.append(f"{key}:{line} could not be parsed: {exc.msg}")
    return findings, errors


def render_report(findings: list[Finding], errors: list[str], checked_count: int) -> str:
    lines = [
        "# Implementation Completeness Scan",
        "",
        f"- Checked runtime Python files: {checked_count}",
        "- Declaration handling: typing.Protocol, abc.ABC, @abstractmethod, and @overload placeholders are treated as contracts, not executable missing implementations.",
    ]
    if errors:
        lines.extend(
            [
                "- Result: FAIL",
                "- Reason: one or more changed Python runtime files could not be parsed before placeholder scanning.",
                "",
                "Parse errors:",
            ]
        )
        lines.extend(f"- {error}" for error in errors)
        return "\n".join(lines) + "\n"
    if findings:
        lines.extend(
            [
                "- Result: FAIL",
                "- Reason: changed runtime code contains executable placeholder implementations.",
                "",
                "Findings:",
            ]
        )
        lines.extend(
            f"- {finding.path}:{finding.line} `{finding.symbol}` - {finding.reason}"
            for finding in findings
        )
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "- Result: PASS",
            "- Reason: no executable placeholder implementations were found in changed runtime Python files.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--changed-files", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    changed_paths = changed_paths_from_file(Path(args.changed_files))
    runtime_paths = [
        path
        for path in dict.fromkeys(changed_paths)
        if is_runtime_python_path(path) and (repo_root / path).is_file()
    ]
    findings, errors = scan_changed_paths(repo_root, runtime_paths)
    print(render_report(findings, errors, len(runtime_paths)), end="")
    return 1 if findings or errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
