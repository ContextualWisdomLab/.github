"""Regression contract for direct-OpenAI fallback API-base isolation.

The Strix quality gate must never route an explicit direct-OpenAI fallback
model (openai-direct/... or openai_direct/...) through another provider's
ambient ``LLM_API_BASE``. In nvidia_nim or openrouter modes that ambient base
is the primary provider's gateway, which answers an OpenAI-keyed chat request
with a literal "404 page not found", so the contracted final OpenAI fallback
could previously never succeed. The gate must return an empty base for these
models so litellm uses its default https://api.openai.com/v1 endpoint, while
non-OpenAI models keep inheriting the ambient base.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Optional


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_GATE = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
GITHUB_MODELS_API_BASE = "https://models.github.ai/inference"


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace.

    The relevant Strix resolver functions contain no nested top-level function
    declarations. Requiring a brace on a line by itself keeps extraction bounded
    and makes source-shape drift fail the test instead of silently selecting the
    wrong shell code.
    """

    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _resolve_api_base(
    model: str,
    *,
    ambient_base: Optional[str],
    github_models_base: Optional[str],
) -> tuple[int, str]:
    """Execute the production base resolver against one bounded synthetic case."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    function_source = _function_block(
        gate_source,
        "resolved_llm_api_base_for_model",
    )

    with tempfile.TemporaryDirectory(prefix="strix-openai-base-") as temp_dir:
        env: dict[str, str] = {
            "PATH": "/usr/bin:/bin",
            "HOME": os.environ.get("HOME", str(Path.home())),
        }
        if ambient_base is None:
            ambient_file = ""
        else:
            ambient_file = str(Path(temp_dir) / "ambient_base.txt")
            Path(ambient_file).write_text(ambient_base, encoding="utf-8")
            env["LLM_API_BASE_FILE"] = ambient_file
        if github_models_base is None:
            env["STRIX_GITHUB_MODELS_API_BASE_FILE"] = ""
        else:
            models_file = Path(temp_dir) / "github_models_base.txt"
            models_file.write_text(github_models_base, encoding="utf-8")
            env["STRIX_GITHUB_MODELS_API_BASE_FILE"] = str(models_file)

        script = "\n".join(
            (
                "set -euo pipefail",
                # Minimal stand-ins for the sourced helper functions the real
                # gate provides; only behavior this contract depends on.
                'trim_whitespace() { local v="$1"; v="${v#"${v%%[![:space:]]*}"}"; printf \'%s\' "${v%"${v##*[![:space:]]}"}"; }',
                "is_vertex_model() { return 1; }",
                'is_explicit_openai_model() { case "$1" in openai_direct/* | openai-direct/*) return 0 ;; *) return 1 ;; esac; }',
                'is_github_models_model() { case "$1" in github_models/*) return 0 ;; *) return 1 ;; esac; }',
                f'is_github_models_api_base() {{ [ "$1" = "{GITHUB_MODELS_API_BASE}" ]; }}',
                "is_github_models_api_compatible_model() { return 0; }",
                'resolve_trusted_input_file() { local label="$1" path="$2"; [ -f "$path" ] || { echo "ERROR: missing $label" >&2; return 2; }; printf \'%s\\n\' "$path"; }',
                "",
                function_source,
                'resolved_llm_api_base_for_model "$1"',
            )
        )
        completed = subprocess.run(
            ["/usr/bin/env", "bash", "-c", script, "gate-resolver", model],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return completed.returncode, completed.stdout.strip()


class StrixOpenAiFallbackBaseIsolationTests(unittest.TestCase):
    """Direct-OpenAI fallbacks must not inherit a foreign provider API base."""

    def test_openai_direct_fallback_ignores_ambient_nvidia_base(self) -> None:
        returncode, output = _resolve_api_base(
            "openai-direct/gpt-5.6-luna",
            ambient_base=NVIDIA_API_BASE,
            github_models_base=None,
        )
        self.assertEqual(returncode, 0)
        self.assertEqual(output, "")

    def test_openai_direct_spelling_is_isolated_too(self) -> None:
        returncode, output = _resolve_api_base(
            "openai_direct/gpt-5.6-luna",
            ambient_base=NVIDIA_API_BASE,
            github_models_base=None,
        )
        self.assertEqual(returncode, 0)
        self.assertEqual(output, "")

    def test_non_openai_models_keep_inheriting_the_ambient_base(self) -> None:
        returncode, output = _resolve_api_base(
            "nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5",
            ambient_base=NVIDIA_API_BASE,
            github_models_base=None,
        )
        self.assertEqual(returncode, 0)
        self.assertEqual(output, NVIDIA_API_BASE)

    def test_github_models_fallback_still_uses_dedicated_base(self) -> None:
        returncode, output = _resolve_api_base(
            "github_models/openai/gpt-5.6",
            ambient_base=NVIDIA_API_BASE,
            github_models_base=GITHUB_MODELS_API_BASE,
        )
        self.assertEqual(returncode, 0)
        self.assertEqual(output, GITHUB_MODELS_API_BASE)


if __name__ == "__main__":
    unittest.main()
