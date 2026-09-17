"""Documentation contract for trusted JavaScript lock materialization."""

import ast
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "scripts/ci/materialize_base_javascript_packages.py"


def test_materializer_symbols_have_explanatory_multiline_docstrings() -> None:
    """Lock discovery and validation code must explain its trust boundary."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring is None or "\n" not in docstring:
            violations.append((node.name, node.lineno))

    assert not violations, f"materializer symbols need explanatory docs: {violations}"
