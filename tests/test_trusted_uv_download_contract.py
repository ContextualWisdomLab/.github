"""Static security contract for the pinned trusted-uv network boundary."""

from __future__ import annotations

import ast
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_MATERIALIZER = _REPO_ROOT / "scripts" / "ci" / "materialize_base_python_requirements.py"
_EXPECTED_URL = (
    "https://releases.astral.sh/github/uv/releases/download/0.12.1/"
    "uv-x86_64-unknown-linux-gnu.tar.gz"
)
_SEMGREP_DYNAMIC_URL_RULE = (
    "python.lang.security.audit.dynamic-urllib-use-detected."
    "dynamic-urllib-use-detected"
)


def _module_tree() -> ast.Module:
    """Parse the materializer without importing or executing repository code."""
    return ast.parse(_MATERIALIZER.read_text(encoding="utf-8"), filename=str(_MATERIALIZER))


def _download_function() -> ast.FunctionDef:
    """Return the trusted-uv single-attempt network-sink function from the module.

    ``_download_trusted_uv_archive`` is a bounded-retry wrapper around this
    function; the literal-URL network sink itself lives in
    ``_fetch_trusted_uv_archive_once`` so it runs unchanged on every attempt.
    """
    for node in _module_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == "_fetch_trusted_uv_archive_once":
            return node
    raise AssertionError("trusted uv single-attempt downloader function is missing")


def _assigned_literal(name: str) -> object:
    """Return one module-level literal assignment without evaluating code."""
    for node in _module_tree().body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"module literal {name} is missing")


def _urlopen_calls() -> list[ast.Call]:
    """Return calls whose attribute name is exactly ``urlopen``."""
    return [
        node
        for node in ast.walk(_download_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "urlopen"
    ]


def test_urlopen_receives_one_literal_https_release_url() -> None:
    """Static analysis can prove repository or user data never selects the URL."""
    calls = _urlopen_calls()

    assert len(calls) == 1
    assert len(calls[0].args) == 1
    url_argument = calls[0].args[0]
    assert isinstance(url_argument, ast.Constant)
    assert isinstance(url_argument.value, str)
    assert url_argument.value == _EXPECTED_URL


def test_literal_network_sink_matches_the_documented_release_constant() -> None:
    """The scanner-friendly sink literal cannot drift from the release identity."""
    assert _assigned_literal("TRUSTED_UV_ARCHIVE_URL") == _EXPECTED_URL


def test_downloader_never_constructs_a_dynamic_request_object() -> None:
    """The audited downloader cannot hide a dynamic URL inside ``Request``."""
    request_calls = [
        node
        for node in ast.walk(_download_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Request"
    ]

    assert request_calls == []


def test_literal_urlopen_sink_has_one_scoped_semgrep_suppression() -> None:
    """The known false positive is suppressed only at the audited literal sink."""
    source_lines = _MATERIALIZER.read_text(encoding="utf-8").splitlines()
    sink_lines = [line for line in source_lines if "with urllib.request.urlopen(" in line]

    assert len(sink_lines) == 1
    assert f"# nosemgrep: {_SEMGREP_DYNAMIC_URL_RULE}" in sink_lines[0]
