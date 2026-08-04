#!/usr/bin/env python3
"""Noema entry point with contextual-orchestrator free-first fallback policy."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_WRAPPER_NAME = __name__
_WRAPPER_FILE = __file__
_CORE_PATH = Path(__file__).with_name("noema_review_gate_core.py")
if not _CORE_PATH.is_file() or _CORE_PATH.is_symlink():
    raise RuntimeError("Noema review-gate core is unavailable")
try:
    globals()["__name__"] = "scripts.ci.noema_review_gate_core_exec"
    globals()["__file__"] = str(_CORE_PATH)
    exec(compile(_CORE_PATH.read_bytes(), str(_CORE_PATH), "exec"), globals(), globals())
finally:
    globals()["__name__"] = _WRAPPER_NAME
    globals()["__file__"] = _WRAPPER_FILE

from scripts.ci.contextual_fallback_policy import (  # noqa: E402
    FallbackPolicyIntegrationError,
    plan_models,
)

_SINGLE_MODEL_CALL_LLM = call_llm
_NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_NVIDIA_MODELS = frozenset(
    {
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/nemotron-3-super-120b-a12b",
    }
)
_NOEMA_ENV_KEYS = (
    "NOEMA_LLM_API_URL",
    "NOEMA_LLM_MODEL",
    "NOEMA_LLM_API_KEY",
    "NOEMA_CUSTOM_LLM_CONFIGURED",
)


def _repository_visibility() -> str:
    """Return the validated target visibility supplied by the trusted workflow."""
    value = os.environ.get("TARGET_REPOSITORY_PRIVATE", "").strip().lower()
    if value in {"", "false"}:
        return "public"
    if value == "true":
        return "private"
    raise RuntimeError(
        "TARGET_REPOSITORY_PRIVATE must resolve to true or false for Noema"
    )


def _custom_noema_config() -> dict[str, str] | None:
    """Return an operator configuration unless it is the workflow's NIM default."""
    api_url = os.environ.get("NOEMA_LLM_API_URL", "").strip()
    api_key = os.environ.get("NOEMA_LLM_API_KEY", "").strip()
    model = os.environ.get("NOEMA_LLM_MODEL", "").strip() or "noema-default"
    if not api_url or not api_key:
        return None
    nvidia_key = os.environ.get("NVIDIA_NIM_API_KEY", "").strip()
    if (
        api_url == _NVIDIA_API_URL
        and model in _NVIDIA_MODELS
        and nvidia_key
        and api_key == nvidia_key
    ):
        return None
    return {
        "NOEMA_LLM_API_URL": api_url,
        "NOEMA_LLM_MODEL": model,
        "NOEMA_LLM_API_KEY": api_key,
    }


@contextmanager
def _temporary_noema_environment(values: dict[str, str]) -> Iterator[None]:
    """Apply one candidate's transport settings and restore the caller exactly."""
    previous = {key: os.environ.get(key) for key in _NOEMA_ENV_KEYS}
    try:
        for key in _NOEMA_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ.update(values)
        yield
    finally:
        for key in _NOEMA_ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value


def _candidate_environment(
    model: str, custom_config: dict[str, str] | None
) -> dict[str, str]:
    """Map one policy model to the existing Noema OpenAI-compatible transport."""
    if model == "configured/noema-custom":
        if custom_config is None:
            raise RuntimeError("Noema custom model was selected without configuration")
        return dict(custom_config)
    if model not in _NVIDIA_MODELS:
        raise RuntimeError(f"Noema policy selected an unsupported model: {model}")
    nvidia_key = os.environ.get("NVIDIA_NIM_API_KEY", "").strip()
    if not nvidia_key:
        raise RuntimeError("NVIDIA_NIM_API_KEY is unavailable for Noema")
    return {
        "NOEMA_LLM_API_URL": _NVIDIA_API_URL,
        "NOEMA_LLM_MODEL": model,
        "NOEMA_LLM_API_KEY": nvidia_key,
    }


def _failure_label(error: Exception) -> str:
    """Return a secret-free failure class and optional HTTP status code."""
    status = getattr(error, "code", None)
    if isinstance(status, int):
        return f"{type(error).__name__}:{status}"
    return type(error).__name__


def call_llm(
    repo: str,
    number: int,
    pr: dict[str, Any],
    diff: str,
    truncated: bool,
    review_context: str = "",
) -> dict[str, Any]:
    """Call eligible free models first, then paid fallback, until verdict valid."""
    custom_config = _custom_noema_config()
    integration_environment = dict(os.environ)
    if custom_config is not None:
        integration_environment["NOEMA_CUSTOM_LLM_CONFIGURED"] = "1"
    try:
        models = plan_models(
            "noema",
            repository_visibility=_repository_visibility(),
            required_capabilities=("structured_output",),
            environ=integration_environment,
        )
    except FallbackPolicyIntegrationError as exc:
        if custom_config is None and not os.environ.get("NVIDIA_NIM_API_KEY", "").strip():
            raise RuntimeError(
                "Noema LLM review unavailable: no eligible configured model"
            ) from exc
        raise

    failures: list[tuple[str, Exception]] = []
    for model in models:
        try:
            candidate_environment = _candidate_environment(model, custom_config)
            with _temporary_noema_environment(candidate_environment):
                return _SINGLE_MODEL_CALL_LLM(
                    repo,
                    number,
                    pr,
                    diff,
                    truncated,
                    review_context,
                )
        except Exception as exc:
            failures.append((model, exc))
            print(
                f"Noema candidate failed: model={model} error={_failure_label(exc)}",
                file=sys.stderr,
            )
    if len(failures) == 1:
        raise failures[0][1]
    attempted = ",".join(model for model, _ in failures)
    failure_types = ",".join(_failure_label(error) for _, error in failures)
    raise RuntimeError(
        "Noema exhausted the shared fallback plan: "
        f"models={attempted}; failures={failure_types}"
    )


if _WRAPPER_NAME == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
