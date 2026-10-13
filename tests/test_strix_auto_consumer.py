"""Connected Strix auto routing; real shell helpers, no scanner or network."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from tests.test_strix_openai_fallback_api_base import _function_block

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/ci/strix_quick_gate.sh"
UTILS = ROOT / "scripts/ci/strix_model_utils.sh"


def _consume(tmp_path: Path, base: str | None, provider: str = "contextual_orchestrator") -> subprocess.CompletedProcess[str]:
    """Execute normalize -> trusted API-base resolver -> actual child qualifier."""
    gate = GATE.read_text(encoding="utf-8")
    utils = UTILS.read_text(encoding="utf-8")
    names = (
        "is_vertex_model", "is_contextual_orchestrator_model",
        "is_contextual_orchestrator_api_base", "is_github_models_model",
        "is_github_models_api_base", "is_known_foreign_provider_api_base",
        "is_github_models_api_compatible_model", "is_explicit_openai_model",
        "resolve_trusted_input_file", "resolved_llm_api_base_for_model",
        "child_model_for_api_base",
    )
    helpers = [_function_block(gate, name) for name in names]
    helpers += [_function_block(utils, name) for name in (
        "trim_whitespace", "sanitize_provider_name", "is_vertex_resource_path",
        "extract_vertex_model_id", "normalize_model",
    )]
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path),
           "DEFAULT_PROVIDER": provider, "STRIX_INPUT_FILE_ROOT": str(tmp_path)}
    if base is not None:
        path = tmp_path / "base.txt"
        path.write_text(base, encoding="utf-8")
        env["LLM_API_BASE_FILE"] = str(path)
    script = "\n".join([
        "set -euo pipefail", *helpers,
        'model=$(normalize_model auto)',
        'printf "normalized=%s\\n" "$model"',
        'base=$(resolved_llm_api_base_for_model "$model")',
        'printf "base=%s\\n" "$base"',
        'child=$(child_model_for_api_base "$model" "$base")',
        'printf "child=%s\\n" "$child"',
    ])
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True,
                          text=True, timeout=10)


def test_workflow_auto_reaches_child_as_exact_auto(tmp_path: Path) -> None:
    result = _consume(tmp_path, "http://127.0.0.1:18080/v1")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "normalized=auto",
        "base=http://127.0.0.1:18080/v1", "child=openai/auto",
    ]
    # openai/ is the LiteLLM connector prefix, not part of the gateway model ID.
    child = result.stdout.splitlines()[-1].removeprefix("child=")
    assert child.removeprefix("openai/") == "auto"
    assert "free" not in result.stdout


@pytest.mark.parametrize("base", [None, "", "http://127.0.0.1:18081/v1",
                                     "http://localhost:18080/v1", "https://example.com/v1"])
def test_auto_cannot_escape_pinned_gateway(tmp_path: Path, base: str | None) -> None:
    result = _consume(tmp_path, base)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "child=" not in result.stdout


@pytest.mark.parametrize("provider", ["", "vertex_ai", "openai"])
def test_auto_requires_explicit_gateway_provider(tmp_path: Path, provider: str) -> None:
    result = _consume(tmp_path, "http://127.0.0.1:18080/v1", provider)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "normalized=" not in result.stdout
    assert "child=" not in result.stdout


def test_required_smoke_admits_repaired_literal_auto() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/ci/strix_required_workflow_smoke.sh")],
        cwd=ROOT, env={"PATH": os.environ["PATH"]},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_strix_sidecar_pool_matches_auto_consumer() -> None:
    workflow = (ROOT / ".github/workflows/strix.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: Provision contextual-orchestrator Strix sidecar\n", 1)[1].split("      - name:", 1)[0]
    assert "          CONTEXTUAL_ORCHESTRATOR_POOL: auto\n" in step
    assert "CONTEXTUAL_ORCHESTRATOR_POOL: free" not in step
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR:" in step
