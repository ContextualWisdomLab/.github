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
_EXPECTED_USER_AGENT = "ContextualWisdomLab-OpenCode-Coverage/1"
_SEMGREP_DYNAMIC_URL_RULE = (
    "python.lang.security.audit.dynamic-urllib-use-detected."
    "dynamic-urllib-use-detected"
)


def _module_tree() -> ast.Module:
    """Parse the materializer without importing or executing repository code."""
    return ast.parse(_MATERIALIZER.read_text(encoding="utf-8"), filename=str(_MATERIALIZER))


def _download_function() -> ast.FunctionDef:
    """Return the trusted-uv downloader function from the parsed module."""
    for node in _module_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == "_download_trusted_uv_archive":
            return node
    raise AssertionError("trusted uv downloader function is missing")


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


def test_urlopen_receives_one_static_request() -> None:
    """Static analysis can prove the downloader passes one named request object."""
    calls = _urlopen_calls()

    assert len(calls) == 1
    assert len(calls[0].args) == 1
    request_argument = calls[0].args[0]
    assert isinstance(request_argument, ast.Name)
    assert request_argument.id == "request"


def test_literal_network_sink_matches_the_documented_release_constant() -> None:
    """The scanner-friendly sink literal cannot drift from the release identity."""
    assert _assigned_literal("TRUSTED_UV_ARCHIVE_URL") == _EXPECTED_URL


def test_literal_user_agent_matches_the_documented_identity() -> None:
    """The request identity remains fixed and contains no user-controlled data."""
    assert _assigned_literal("TRUSTED_UV_USER_AGENT") == _EXPECTED_USER_AGENT


def test_downloader_constructs_one_static_request() -> None:
    """The request URL and User-Agent are both statically constrained."""
    request_calls = [
        node
        for node in ast.walk(_download_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Request"
    ]

    assert len(request_calls) == 1
    request_call = request_calls[0]
    assert len(request_call.args) == 1
    url_argument = request_call.args[0]
    assert isinstance(url_argument, ast.Constant)
    assert url_argument.value == _EXPECTED_URL

    headers_keyword = next(
        keyword for keyword in request_call.keywords if keyword.arg == "headers"
    )
    assert isinstance(headers_keyword.value, ast.Dict)
    assert len(headers_keyword.value.keys) == 1
    key = headers_keyword.value.keys[0]
    value = headers_keyword.value.values[0]
    assert isinstance(key, ast.Constant)
    assert key.value == "User-Agent"
    assert isinstance(value, ast.Name)
    assert value.id == "TRUSTED_UV_USER_AGENT"


def test_literal_urlopen_sink_has_one_scoped_semgrep_suppression() -> None:
    """The known false positive is suppressed only at the audited literal sink."""
    source_lines = _MATERIALIZER.read_text(encoding="utf-8").splitlines()
    sink_lines = [line for line in source_lines if "with urllib.request.urlopen(" in line]

    assert len(sink_lines) == 1
    assert f"# nosemgrep: {_SEMGREP_DYNAMIC_URL_RULE}" in sink_lines[0]
