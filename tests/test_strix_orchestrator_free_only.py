"""Contracts proving Strix cannot normalize a direct-provider model route."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODEL_UTILS = REPOSITORY_ROOT / "scripts" / "ci" / "strix_model_utils.sh"


def _normalize(model: str) -> subprocess.CompletedProcess[str]:
    """Run the production normalization helper for one model identifier."""
    return subprocess.run(
        [
            "bash",
            "-c",
            'set -euo pipefail; . "$1"; DEFAULT_PROVIDER=""; normalize_model "$2"',
            "bash",
            str(MODEL_UTILS),
            model,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_strix_accepts_only_the_governed_free_virtual_model_ids() -> None:
    """Both accepted spellings resolve to the same governed free pool boundary."""
    for model in (
        "orchestrator/free",
        "contextual-orchestrator/orchestrator/free",
    ):
        result = _normalize(model)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == model


def test_strix_rejects_every_direct_provider_model_before_execution() -> None:
    """A Strix model cannot name a provider or concrete model outside the gateway."""
    for model in (
        "openai-direct/gpt-5.4",
        "openai_direct/gpt-5.4",
        "openai/gpt-5",
        "openrouter/openai/gpt-oss-120b:free",
        "nvidia_nim/meta/llama-3.3-70b-instruct",
        "github_models/openai/gpt-5",
        "vertex_ai/gemini-2.5-pro",
        "gemini/gemini-2.5-pro",
        "gpt-5",
    ):
        result = _normalize(model)
        assert result.returncode == 2, (model, result.stdout, result.stderr)
        assert "Strix model must be orchestrator/free" in result.stderr
        assert result.stdout == ""
