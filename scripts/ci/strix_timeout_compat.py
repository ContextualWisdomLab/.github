#!/usr/bin/env python3
"""Launch Strix 1.5.3 with ContextualWisdomLab's unbounded inference contract.

Strix 1.5.3 models ``LLM_TIMEOUT`` as an integer and passes it both to request
settings and to ``asyncio.wait_for`` during model preflight. ``0`` therefore
cancels preflight immediately instead of meaning "no deadline". This trusted,
version-gated launcher keeps Strix's non-model operational timeouts intact while
removing only model-request and model-warm-up wall-clock deadlines.
"""

from __future__ import annotations

import importlib.metadata
import inspect
import re
import os
import sys
from collections.abc import Awaitable, Mapping, MutableMapping
from functools import wraps
from typing import Any


SUPPORTED_VERSION = "1.5.3"
STRIX_DISTRIBUTION = "strix-agent"
SUPPORTED_SANDBOX_SDK_VERSION = "0.19.4"
_OMITTED = "<omitted>"
_SANDBOX_PHASES = frozenset({"authentication_start", "authentication_success", "authentication_failure"})
_SANDBOX_STATES = frozenset({"created", "running", "paused", "restarting", "exited", "removing", "dead"})


def normalize_inference_timeout_environment(environment: MutableMapping[str, str]) -> None:
    """Disable Strix request and stream-idle deadlines before settings import."""
    environment["LLM_TIMEOUT"] = "0"
    environment["LLM_STREAM_IDLE_TIMEOUT"] = "0"


class UnboundedInferenceAsyncio:
    """Delegate asyncio except that model warm-up ``wait_for`` has no deadline."""

    def __init__(self, asyncio_module: Any) -> None:
        """Retain the real asyncio module for every operation except ``wait_for``."""
        self._asyncio_module = asyncio_module

    def __getattr__(self, attribute_name: str) -> Any:
        """Delegate non-warm-up asyncio attributes without changing semantics."""
        return getattr(self._asyncio_module, attribute_name)

    async def wait_for(self, awaitable: Awaitable[Any], timeout: object) -> Any:
        """Await model warm-up without a fixed wall-clock deadline."""
        del timeout
        return await self._asyncio_module.wait_for(awaitable, timeout=None)


def _require_supported_version() -> None:
    """Fail closed instead of applying a compatibility shim to unknown Strix code."""
    try:
        installed_version = importlib.metadata.version(STRIX_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("Pinned Strix distribution is not installed.") from exc
    if installed_version != SUPPORTED_VERSION:
        raise RuntimeError(
            "Strix timeout compatibility supports exactly "
            f"{SUPPORTED_VERSION}; installed version is {installed_version}."
        )


def emit_sandbox_diagnostic(session: Any, phase: str, docker_session_type: type | None) -> None:
    """Read already cached bound Docker metadata without I/O or authentication interference."""
    if type(phase) is not str or phase not in _SANDBOX_PHASES:
        return
    fields = (_OMITTED, _OMITTED, _OMITTED, _OMITTED)
    try:
        inner = getattr(session, "_inner", None)
        if docker_session_type is not None and isinstance(inner, docker_session_type):
            container = inner._container
            identity = inner.container_id
            if isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{64}", identity) and container.id == identity:
                # attrs is the SDK-owned Docker object's already available cache.
                # No reload, daemon request, image lookup or readiness probe occurs.
                attrs = container.attrs
                if isinstance(attrs, Mapping) and attrs.get("Id") == identity:
                    state = attrs.get("State")
                    state = state if isinstance(state, Mapping) else {}
                    image = attrs.get("Image")
                    image = image if isinstance(image, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", image) else _OMITTED
                    status = state.get("Status")
                    status = status if isinstance(status, str) and status in _SANDBOX_STATES else _OMITTED
                    exit_code = state.get("ExitCode")
                    exit_code = str(exit_code) if type(exit_code) is int and 0 <= exit_code <= 255 else _OMITTED
                    oom = state.get("OOMKilled")
                    oom = str(oom).lower() if type(oom) is bool else _OMITTED
                    fields = (image, status, exit_code, oom)
    except BaseException:
        # Cache inspection is best effort, never a new scan verdict.
        pass
    try:
        image, status, exit_code, oom = fields
        print(f"STRIX_SANDBOX_STATE phase={phase} freshness=cached image_config_id={image} status={status} "
              f"exit_code={exit_code} oom_killed={oom}", file=sys.stderr)
    except BaseException:
        # Output failure must not replace the original authentication result.
        pass


def wrap_sandbox_authentication(original: Any, docker_session_type: type) -> Any:
    """Observe authentication while preserving the exact call, return and exception objects."""
    @wraps(original)
    async def observed_login(session: Any, *, container_url: str, attempts: int = 10) -> str:
        """Observe only cached metadata around the unmodified guest-token operation."""
        emit_sandbox_diagnostic(session, "authentication_start", docker_session_type)
        try:
            token = await original(session, container_url=container_url, attempts=attempts)
        except BaseException:
            emit_sandbox_diagnostic(session, "authentication_failure", docker_session_type)
            raise
        emit_sandbox_diagnostic(session, "authentication_success", docker_session_type)
        return token
    return observed_login


def install_sandbox_diagnostics() -> None:
    """Optional observations cannot impose new runtime version or ABI requirements."""
    try:
        if importlib.metadata.version("openai-agents") != SUPPORTED_SANDBOX_SDK_VERSION:
            raise ValueError("unsupported SDK")
        from agents.sandbox.sandboxes.docker import DockerSandboxSession
        from strix.runtime import caido_bootstrap

        original = caido_bootstrap._login_as_guest
        parameters = inspect.signature(original).parameters
        if (tuple(parameters) != ("session", "container_url", "attempts")
                or parameters["session"].kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD
                or parameters["session"].default is not inspect.Parameter.empty
                or parameters["container_url"].kind is not inspect.Parameter.KEYWORD_ONLY
                or parameters["container_url"].default is not inspect.Parameter.empty
                or parameters["attempts"].kind is not inspect.Parameter.KEYWORD_ONLY
                or parameters["attempts"].default != 10
                or not inspect.iscoroutinefunction(original)):
            raise ValueError("unsupported ABI")
        observed = wrap_sandbox_authentication(original, DockerSandboxSession)
    except BaseException:
        try:
            print("STRIX_SANDBOX_DIAGNOSTICS unavailable", file=sys.stderr)
        except BaseException:
            pass
        return
    caido_bootstrap._login_as_guest = observed


def install_runtime_compatibility() -> Any:
    """Install narrowly scoped model-timeout compatibility and return Strix main."""
    _require_supported_version()
    normalize_inference_timeout_environment(os.environ)

    # Import only after timeout normalization so Strix settings cannot cache the
    # workflow's positive parser-compatibility value as an inference deadline.
    from strix.core import inputs as strix_inputs

    original_make_model_settings = strix_inputs.make_model_settings

    @wraps(original_make_model_settings)
    def make_model_settings_without_request_deadline(*args: Any, **kwargs: Any) -> Any:
        """Preserve every model setting except the fixed request timeout."""
        kwargs["request_timeout"] = None
        return original_make_model_settings(*args, **kwargs)

    strix_inputs.make_model_settings = make_model_settings_without_request_deadline

    # These are the two Strix 1.5.3 modules that wrap model warm-up calls in
    # asyncio.wait_for(timeout=llm.timeout). Replacing their module-local asyncio
    # references leaves proxy/MCP/UI/process timeouts elsewhere intact.
    from strix.interface import scan_setup

    scan_setup.asyncio = UnboundedInferenceAsyncio(scan_setup.asyncio)

    # strix/interface/__init__.py runs ``from .main import main``, which rebinds
    # the package attribute ``strix.interface.main`` to the *function* it
    # imports, shadowing the submodule of the same name. Both
    # ``from strix.interface import main as strix_main`` and
    # ``import strix.interface.main as strix_main`` resolve through that
    # shadowed package attribute and return the function, not the module, so
    # every ``strix_main.<attr>`` access below raised AttributeError. Look the
    # submodule up directly in sys.modules by its exact dotted path instead,
    # which the shadow never touches.
    import strix.interface.main  # noqa: F401 - imported for its sys.modules registration

    strix_main = sys.modules["strix.interface.main"]

    strix_main.asyncio = UnboundedInferenceAsyncio(strix_main.asyncio)
    install_sandbox_diagnostics()
    return strix_main


def main() -> None:
    """Apply the version-gated compatibility boundary and enter Strix normally."""
    strix_main = install_runtime_compatibility()
    strix_main.main()


if __name__ == "__main__":
    main()
