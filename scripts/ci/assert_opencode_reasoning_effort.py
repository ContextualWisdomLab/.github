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


def strip_jsonc_comments(text: str) -> str:
    """Return ``text`` with ``//`` and ``/* */`` comments removed outside strings.

    ``opencode.jsonc`` is genuinely JSONC (it carries explanatory ``//`` notes,
    e.g. above the ``contextual-orchestrator`` provider block), so a plain
    :func:`json.loads` rejects it. Comment markers are only recognized outside
    JSON string literals, so a string value that itself contains ``//`` (the
    ``"$schema": "https://opencode.ai/config.json"`` line) is preserved
    unchanged. Newlines inside removed content are kept so any remaining
    ``json.JSONDecodeError`` still reports an accurate line number.
    """
    result: list[str] = []
    in_string = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            result.append(char)
            if char == "\\" and index + 1 < length:
                result.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            index += 2
            while index < length and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (
                text[index] == "*" and text[index + 1] == "/"
            ):
                if text[index] in "\r\n":
                    result.append(text[index])
                index += 1
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def load_config(path: Path) -> dict[str, Any]:
    """Load the OpenCode JSONC config, tolerating ``//`` and ``/* */`` comments."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"OpenCode config not found: {path}") from None
    try:
        return json.loads(strip_jsonc_comments(raw_text))
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

    if not config_for_model:
        if provider == "github-models" or is_known_reasoning_capable(model_name):
            return [
                f"OpenCode candidate {candidate} is not defined in opencode.jsonc "
                f"under provider {provider}."
            ]
        return []

    configured_reasoning = config_for_model.get("reasoning") is True
    if not (configured_reasoning or is_known_reasoning_capable(model_name)):
        return []

    errors: list[str] = []
    prefix = f"OpenCode reasoning-capable candidate {candidate} must set"
    suffix = "in opencode.jsonc."

    if not configured_reasoning:
        errors.append(f"{prefix} reasoning=true {suffix}")
    if (config_for_model.get("options") or {}).get("reasoningEffort") != "high":
        errors.append(f"{prefix} options.reasoningEffort=high {suffix}")
    if ((config_for_model.get("variants") or {}).get("high") or {}).get("reasoningEffort") != "high":
        errors.append(f"{prefix} variants.high.reasoningEffort=high {suffix}")

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
