#!/usr/bin/env python3
"""Validate high reasoning effort for OpenCode models that support it."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Pre-compile regex at the module level to avoid re-compilation overhead during processing
# Match strings, line comments, and block comments (dotall)
_JSONC_COMMENT_RE = re.compile(
    r'(?P<string>"(?:\\.|[^"\\\n\r])*")'
    r'|(?P<line_comment>//[^\r\n]*)'
    r'|(?P<block_comment>/\*.*?\*/)',
    re.DOTALL,
)


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
    # Fast-path regex replacement for standard valid JSONC input
    # that doesn't trigger complex character-by-character parsing bottlenecks.
    def replacer(match: re.Match[str]) -> str:
        """Return the replacement for one matched string or comment token."""
        if match.group("string") is not None:
            return str(match.group("string"))
        if match.group("line_comment") is not None:
            return ""
        block = str(match.group("block_comment"))
        return "".join(c for c in block if c in "\r\n")

    return _JSONC_COMMENT_RE.sub(replacer, text)


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
