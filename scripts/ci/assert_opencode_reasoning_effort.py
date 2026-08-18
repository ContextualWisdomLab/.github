#!/usr/bin/env python3
"""Validate high reasoning effort for OpenCode models that support it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def is_known_reasoning_capable(model_name: str) -> bool:
    """Return whether the model family is expected to support reasoning effort."""
    return (
        model_name.startswith("openai/gpt-5")
        or model_name.startswith("openai/o3")
        or model_name.startswith("openai/o4")
        or model_name.startswith("deepseek/deepseek-r1")
    )


def load_config(path: Path) -> dict[str, Any]:
    """Load the OpenCode JSON config."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"OpenCode config not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"OpenCode config is not valid JSON: {path}: {exc}") from None


def model_config(config: dict[str, Any], candidate: str) -> tuple[str, str, dict[str, Any]]:
    """Return provider, model name, and model config for a provider-qualified candidate."""
    if "/" not in candidate:
        raise ValueError(f"OpenCode candidate {candidate} is not provider-qualified.")
    provider, model_name = candidate.split("/", 1)
    provider_config = (config.get("provider") or {}).get(provider) or {}
    models = provider_config.get("models") or {}
    return provider, model_name, models.get(model_name) or {}


def validate_candidate(config: dict[str, Any], candidate: str) -> list[str]:
    """Return validation errors for one candidate."""
    try:
        provider, model_name, config_for_model = model_config(config, candidate)
    except ValueError as exc:
        return [str(exc)]

    if not config_for_model and (
        provider == "github-models" or is_known_reasoning_capable(model_name)
    ):
        return [
            f"OpenCode candidate {candidate} is not defined in opencode.jsonc "
            f"under provider {provider}."
        ]
    if not config_for_model:
        return []

    configured_reasoning = config_for_model.get("reasoning") is True
    should_require_effort = configured_reasoning or is_known_reasoning_capable(model_name)
    if not should_require_effort:
        return []

    errors: list[str] = []
    if not configured_reasoning:
        errors.append(
            f"OpenCode reasoning-capable candidate {candidate} must set reasoning=true "
            "in opencode.jsonc."
        )
    if (config_for_model.get("options") or {}).get("reasoningEffort") != "high":
        errors.append(
            f"OpenCode reasoning-capable candidate {candidate} must set "
            "options.reasoningEffort=high in opencode.jsonc."
        )
    if ((config_for_model.get("variants") or {}).get("high") or {}).get(
        "reasoningEffort"
    ) != "high":
        errors.append(
            f"OpenCode reasoning-capable candidate {candidate} must set "
            "variants.high.reasoningEffort=high in opencode.jsonc."
        )
    return errors


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("opencode.jsonc"))
    parser.add_argument("candidates", nargs="+")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Validate all requested candidates."""
    args = parse_args(argv)
    config = load_config(args.config)
    errors: list[str] = []
    for candidate in args.candidates:
        errors.extend(validate_candidate(config, candidate))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
