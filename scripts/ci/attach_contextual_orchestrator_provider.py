#!/usr/bin/env python3
"""Optionally attach ContextualWisdomLab/contextual-orchestrator to OpenCode config.

NIM-direct remains the default. This helper is a no-op unless
``CONTEXTUAL_ORCHESTRATOR_URL`` is set. It never adds GitHub Models.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse


PROVIDER_NAME = "contextual-orchestrator"
FORBIDDEN_HOST_MARKERS = (
    "models.github.ai",
    "github-models",
    "models.github.com",
)
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def load_config(path: Path) -> dict[str, Any]:
    """Load one isolated OpenCode JSON config."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"OpenCode config not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"OpenCode config is not valid JSON: {path}: {exc}") from None
    if not isinstance(loaded, dict):
        raise SystemExit(f"OpenCode config root must be an object: {path}")
    return loaded


def normalize_orchestrator_url(raw_url: str) -> str | None:
    """Return a usable orchestrator base URL, or None when the env is unset."""
    stripped = raw_url.strip()
    if not stripped:
        return None
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit(
            "CONTEXTUAL_ORCHESTRATOR_URL must be an http(s) OpenAI-compatible "
            "base URL; refusing to attach the orchestrator provider."
        )
    if parsed.username or parsed.password:
        raise SystemExit(
            "CONTEXTUAL_ORCHESTRATOR_URL must not embed credentials; "
            "refusing to attach the orchestrator provider."
        )
    host = (parsed.hostname or "").casefold()
    if not host:
        raise SystemExit(
            "CONTEXTUAL_ORCHESTRATOR_URL is missing a host; refusing to attach "
            "the orchestrator provider."
        )
    if any(marker in stripped.casefold() or marker in host for marker in FORBIDDEN_HOST_MARKERS):
        raise SystemExit(
            "CONTEXTUAL_ORCHESTRATOR_URL must not point at GitHub Models; "
            "refusing to attach the orchestrator provider."
        )
    if parsed.scheme == "http" and host not in LOOPBACK_HOSTS:
        raise SystemExit(
            "CONTEXTUAL_ORCHESTRATOR_URL may use http only for a loopback "
            "sidecar; refusing to attach the orchestrator provider."
        )
    return stripped.rstrip("/")


def attach_orchestrator_provider(
    config: dict[str, Any], orchestrator_url: str
) -> dict[str, Any]:
    """Attach one OpenAI-compatible orchestrator provider without changing NIM defaults."""
    providers = config.setdefault("provider", {})
    if not isinstance(providers, dict):
        raise SystemExit("OpenCode config provider map must be an object.")
    if "github-models" in providers:
        raise SystemExit(
            "OpenCode config still names github-models; refusing to attach "
            "the orchestrator provider."
        )
    enabled = list(config.get("enabled_providers") or [])
    if "nvidia-nim" not in enabled:
        raise SystemExit(
            "OpenCode config must keep nvidia-nim enabled; refusing to attach "
            "the orchestrator provider."
        )
    providers[PROVIDER_NAME] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Contextual Orchestrator",
        "options": {
            "baseURL": orchestrator_url,
        },
    }
    if PROVIDER_NAME not in enabled:
        enabled.append(PROVIDER_NAME)
    config["enabled_providers"] = enabled
    config["provider"] = providers
    return config


def main(argv: list[str] | None = None) -> int:
    """Attach the orchestrator provider when CONTEXTUAL_ORCHESTRATOR_URL is set."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args(argv)
    raw_url = os.environ.get("CONTEXTUAL_ORCHESTRATOR_URL", "")
    try:
        orchestrator_url = normalize_orchestrator_url(raw_url)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    if orchestrator_url is None:
        print("Contextual orchestrator URL unset; keeping NIM-direct OpenCode defaults.")
        return 0
    try:
        config = load_config(args.config)
        attach_orchestrator_provider(config, orchestrator_url)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    args.config.write_text(
        json.dumps(config, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Attached contextual-orchestrator provider at "
        f"{orchestrator_url}; NIM-direct remains the default model."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
