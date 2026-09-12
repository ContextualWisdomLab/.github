"""Quality contract for explanatory commercial-readiness documentation."""

import ast
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "scripts/ci/organization_commercial_readiness_loop.py"
MARKER_EXCEPTIONS = {"GitHubError", "SnapshotChanged"}


def test_shipped_symbols_have_explanatory_multiline_docstrings() -> None:
    """The coordinator's public and policy symbols explain their contracts."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in MARKER_EXCEPTIONS:
            continue
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring is None or "\n" not in docstring:
            violations.append((node.name, node.lineno))

    assert not violations, f"symbols need explanatory multiline docstrings: {violations}"
